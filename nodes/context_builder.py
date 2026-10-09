"""Independent Node [0]/[1] extraction over a validated evidence packet."""

import json
import re
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from core.llm import get_llm
from core.logger import setup_logger
from core.policy import build_risk_acceptance_criteria, build_risk_methodology
from core.state import TaraState
from core.structured_extraction import extract_with_retry
from nodes.field_extractor import extract_node_facts
from prompts import load_prompt
from schemas.common import AssessmentVerdict
from schemas.evidence import EvidenceRef
from schemas.evidence_packet import EvidenceTargetNode
from schemas.legal import ScopeStatement
from schemas.product import (
    CommunicationMatrix,
    ComponentInventory,
    ProductContext,
    ProductContextOverview,
    ProductFunctionCatalog,
)
from schemas.retrieval import RetrievalField
from tools.evidence_input import (
    EvidencePacketBinding,
    canonicalize_evidence_payload,
    iter_evidence_refs,
    load_evidence_packet,
    render_evidence_material,
    validate_evidence_bindings,
    validate_evidence_block_subset,
)


logger = setup_logger("context_builder")

SCOPE_RULE_VERSION = "node0_scope_rules.v7.2"
CONTEXT_RULE_VERSION = "node1_context_rules.v7.4"

# Keep unchanged section caches reusable when a rule release only affects selected
# synthesis sections. Deterministic repairs still run after all sections are assembled.
_CONTEXT_SECTION_RULE_VERSIONS = {
    "overview": "node1_context_rules.v7.1",
    "functions": "node1_context_rules.v7.1",
    "components": CONTEXT_RULE_VERSION,
    "communications": CONTEXT_RULE_VERSION,
}

_INTERNAL_REFERENCE_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:FACT-(?:\d+|X{2,})|BLK-(?:[A-F0-9]+|X{2,})|GAP-[A-Z0-9-]+)(?![A-Z0-9])",
    re.IGNORECASE,
)
_CONDITIONAL_MARKERS = (
    "选配",
    "可选",
    "若启用",
    "如启用",
    "默认关闭",
    "待确认",
    "未确认",
    "取决于",
    "合同",
    "BOM",
    "现场配置",
)
_UNRESOLVED_MARKERS = ("待确认", "未确认", "未知", "不明确", "未提供", "未说明", "未定义")
_QUESTION_MARKERS = (
    "是否",
    "何种",
    "哪些",
    "哪个",
    "哪一",
    "什么",
    "多少",
    "何时",
    "由谁",
    "如何",
    "能否",
    "有无",
    "请确认",
)
_RDPS_CERTAINTY_PATTERNS = (
    re.compile(r"(?:远程数据处理方案|RDPS).{0,8}(?:被证实|已证实|已确认|确定存在)"),
    re.compile(r"(?:被认定|认定|判定|确定).{0,8}(?:为|是).{0,4}RDPS", re.IGNORECASE),
)
_EXPERIENCE_EVIDENCE_MARKERS = (
    "培训",
    "经验",
    "资质",
    "技能",
    "专业人员",
    "知识要求",
    "能力要求",
)
_RESPONSIBILITY_EVIDENCE_MARKERS = (
    "供应商",
    "制造商",
    "开发方",
    "运营方",
    "第三方",
    "外部厂商",
    "自研",
    "本公司",
    "supplier",
    "vendor",
    "operator",
    "third party",
)
_COMPONENT_CONFIRMED_DELIVERY_MARKERS = (
    "内含",
    "内置",
    "标准配置",
    "标准内置",
    "集成于",
    "集成有",
    "组成部分",
    "included",
    "built-in",
    "integrated",
)


def _normalized_boundary_item(value: str) -> str:
    return "".join(value.casefold().split()).strip("，。；;,.：:")


def _boundary_identity(value: str) -> str:
    """Return a conservative identity key for cross-list scope conflict checks."""
    cleaned = _clean_business_text(value)
    head = re.split(r"[：:；;（(\[]", cleaned, maxsplit=1)[0]
    identifiers = re.findall(
        r"[a-z]+(?:[-&]?[a-z0-9]+)*\d+[a-z0-9-]*",
        head.casefold(),
    )
    if identifiers:
        return "id:" + "|".join(dict.fromkeys(identifiers))
    return "name:" + _normalized_boundary_item(head)


def _resolve_scope_boundary_conflicts(
    confirmed: list[str],
    conditional: list[str],
    excluded: list[str],
) -> tuple[list[str], list[str], list[str], int]:
    """Move objects classified into multiple boundary states to conditional review."""
    grouped: dict[str, list[tuple[str, str]]] = {}
    for status, values in (
        ("confirmed", confirmed),
        ("conditional", conditional),
        ("excluded", excluded),
    ):
        for value in values:
            identity = _boundary_identity(value)
            if identity not in {"name:", "id:"}:
                grouped.setdefault(identity, []).append((status, value))

    repaired_confirmed: list[str] = []
    repaired_conditional: list[str] = []
    repaired_excluded: list[str] = []
    conflicts = 0
    for records in grouped.values():
        statuses = {status for status, _ in records}
        if len(statuses) == 1:
            target = {
                "confirmed": repaired_confirmed,
                "conditional": repaired_conditional,
                "excluded": repaired_excluded,
            }[next(iter(statuses))]
            target.extend(value for _, value in records)
            continue

        conflicts += 1
        representative = next(
            (value for status, value in records if status == "conditional"),
            records[0][1],
        )
        if "范围分类冲突" not in representative:
            representative = f"{representative}（范围分类冲突，待确认）"
        repaired_conditional.append(representative)

    return repaired_confirmed, repaired_conditional, repaired_excluded, conflicts


def _scope_business_text(scope: ScopeStatement):
    yield "scope_description", scope.scope_description
    if scope.classification.rdps_description:
        yield "classification.rdps_description", scope.classification.rdps_description
    for field_name in (
        "in_scope_components",
        "conditional_scope_components",
        "out_of_scope_components",
        "assumptions",
    ):
        for index, item in enumerate(getattr(scope, field_name)):
            yield f"{field_name}[{index}]", item


def _looks_like_heading_only(value: str | None) -> bool:
    """Reject short/generic headings that cannot independently support a scope fact."""
    if not value or len("".join(value.split())) < 12:
        return True
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines or len(lines) > 3:
        return False
    heading_line = re.compile(
        r"^(?:用户手册|目录|第?\d+(?:\.\d+)*\s*[\u4e00-\u9fffA-Za-z /_-]+)$"
    )
    return all(heading_line.fullmatch(line) for line in lines)


def _clean_business_text(value: str) -> str:
    cleaned = _INTERNAL_REFERENCE_PATTERN.sub("", value)
    cleaned = re.sub(r"\(\s*[,/，、;；]*\s*\)", "", cleaned)
    cleaned = re.sub(r"（\s*[,/，、;；]*\s*）", "", cleaned)
    cleaned = re.sub(r"\s+([，。；：,.!?？])", r"\1", cleaned)
    cleaned = re.sub(r"([（(])\s*[,/，、;；]+", r"\1", cleaned)
    return cleaned.strip()


def _deduplicate(values: list[str], seen: set[str] | None = None) -> list[str]:
    known = seen if seen is not None else set()
    result: list[str] = []
    for value in values:
        normalized = _normalized_boundary_item(value)
        if normalized and normalized not in known:
            known.add(normalized)
            result.append(value)
    return result


def _downgrade_unknown_rdps_wording(value: str) -> str:
    result = value
    result = re.sub(
        r"[^，。；\n]{0,30}作为远程数据处理方案(?:被证实|已证实|已确认|确定)存在",
        "材料显示存在远程连接或数据处理相关能力",
        result,
    )
    result = re.sub(
        r"远程数据处理方案(?:被证实|已证实|已确认|确定存在)",
        "远程连接或数据处理相关能力已有材料描述",
        result,
    )
    return result


def _validate_scope(
    scope: ScopeStatement,
    binding: EvidencePacketBinding | None,
    allowed_block_ids: set[str] | None = None,
) -> ScopeStatement:
    """Conservatively repair local quality issues; only source-integrity failures remain blocking."""
    notes: list[str] = []
    if scope.review_notes:
        notes.append("已忽略模型生成的审阅备注；本栏只记录系统确定性降级。")
    cleaned_values: dict[str, str] = {}
    cleaned_internal_paths: list[str] = []
    for path, value in _scope_business_text(scope):
        cleaned = _clean_business_text(value)
        cleaned_values[path] = cleaned
        if cleaned != value:
            cleaned_internal_paths.append(path)
    if cleaned_internal_paths:
        notes.append(f"已从 {len(cleaned_internal_paths)} 个业务字段移除内部处理编号。")

    confirmed: list[str] = []
    conditional = [
        cleaned_values[f"conditional_scope_components[{index}]"]
        for index in range(len(scope.conditional_scope_components))
    ]
    moved_from_confirmed: list[str] = []
    for index in range(len(scope.in_scope_components)):
        item = cleaned_values[f"in_scope_components[{index}]"]
        if any(marker in item for marker in _CONDITIONAL_MARKERS):
            conditional.append(item)
            moved_from_confirmed.append(item)
        else:
            confirmed.append(item)

    if moved_from_confirmed:
        notes.append(f"已将 {len(moved_from_confirmed)} 个带条件的项目移至条件范围。")

    excluded: list[str] = []
    moved_from_excluded: list[str] = []
    for index in range(len(scope.out_of_scope_components)):
        item = cleaned_values[f"out_of_scope_components[{index}]"]
        if any(marker in item for marker in _UNRESOLVED_MARKERS):
            conditional.append(item)
            moved_from_excluded.append(item)
        else:
            excluded.append(item)

    if moved_from_excluded:
        notes.append(f"已将 {len(moved_from_excluded)} 个证据不足的排除项降级为条件范围。")

    questions: list[str] = []
    converted_questions = 0
    for index in range(len(scope.assumptions)):
        item = cleaned_values[f"assumptions[{index}]"]
        if not item.rstrip().endswith(("？", "?")) or not any(
            marker in item for marker in _QUESTION_MARKERS
        ):
            item = f"请确认以下说法是否成立：{item.rstrip('。.!！?？')}？"
            converted_questions += 1
        questions.append(item)
    if converted_questions:
        notes.append(f"已将 {converted_questions} 个假设答案降级为待确认问题。")

    classification = scope.classification
    scope_description = cleaned_values["scope_description"]
    rdps_description = cleaned_values.get("classification.rdps_description")
    if classification.has_rdps is None:
        combined = "\n".join(filter(None, (scope_description, rdps_description)))
        if any(pattern.search(combined) for pattern in _RDPS_CERTAINTY_PATTERNS):
            scope_description = _downgrade_unknown_rdps_wording(scope_description)
            if rdps_description:
                rdps_description = _downgrade_unknown_rdps_wording(rdps_description)
            notes.append("RDPS 尚未判定，已将肯定表述降级为远程能力/候选依赖描述。")

    evidence = []
    removed_low_information: list[str] = []
    removed_outside_packet: list[str] = []
    removed_outside_retrieval: list[str] = []
    for item in scope.evidence:
        block_id = item.source.block_id
        if _looks_like_heading_only(item.quote):
            removed_low_information.append(item.evidence_id)
            continue
        if binding is not None and block_id not in binding.blocks:
            removed_outside_packet.append(item.evidence_id)
            continue
        if allowed_block_ids is not None and block_id not in allowed_block_ids:
            removed_outside_retrieval.append(item.evidence_id)
            continue
        evidence.append(item)
    if removed_low_information:
        notes.append(f"已移除 {len(removed_low_information)} 条不能独立支撑范围事实的低信息证据。")
    if removed_outside_packet:
        notes.append(f"已移除 {len(removed_outside_packet)} 条证据包之外的引用。")
    if removed_outside_retrieval:
        notes.append(f"已移除 {len(removed_outside_retrieval)} 条本次检索集合之外的引用。")

    confirmed, conditional, excluded, boundary_conflicts = _resolve_scope_boundary_conflicts(
        confirmed,
        conditional,
        excluded,
    )
    if boundary_conflicts:
        notes.append(
            f"已将 {boundary_conflicts} 个跨范围状态冲突的对象降级为条件范围，等待人工确认。"
        )
    confirmed = _deduplicate(confirmed)
    conditional = _deduplicate(conditional)
    excluded = _deduplicate(excluded)
    updated = scope.model_copy(
        update={
            "scope_description": scope_description,
            "classification": classification.model_copy(update={"rdps_description": rdps_description}),
            "in_scope_components": confirmed,
            "conditional_scope_components": conditional,
            "out_of_scope_components": excluded,
            "assumptions": _deduplicate(questions),
            "evidence": evidence,
            "review_notes": _deduplicate(notes),
        }
    )
    if binding is not None:
        validate_evidence_bindings(updated, binding)
    return updated


_SCOPE_PROMPT_TEMPLATE = load_prompt("node0_scope.md", "scope_direct")


_CONTEXT_PROMPT_TEMPLATE = load_prompt("node1_context.md", "context_direct")


_SCOPE_SYNTHESIS_PROMPT = load_prompt("node0_scope.md", "scope_synthesis")


_CONTEXT_COMMON_RULES = load_prompt("node1_context.md", "section_common")
_CONTEXT_SECTION_BODIES = {
    section_name: load_prompt("node1_context.md", f"section_{section_name}")
    for section_name in ("overview", "functions", "components", "communications")
}


_CONTEXT_SECTION_FIELDS: dict[str, frozenset[RetrievalField]] = {
    "overview": frozenset(
        {
            RetrievalField.IPRFU,
            RetrievalField.USERS,
            RetrievalField.OPERATIONAL_ENVIRONMENT,
            RetrievalField.RDPS_DEPENDENCIES,
        }
    ),
    "functions": frozenset(
        {
            RetrievalField.FUNCTIONS,
            RetrievalField.SECURITY_FUNCTIONS,
            RetrievalField.COMMUNICATIONS,
            RetrievalField.USERS,
        }
    ),
    "components": frozenset(
        {
            RetrievalField.COMPONENTS,
            RetrievalField.FUNCTIONS,
            RetrievalField.SECURITY_FUNCTIONS,
        }
    ),
    "communications": frozenset(
        {
            RetrievalField.COMMUNICATIONS,
            RetrievalField.FUNCTIONS,
            RetrievalField.OPERATIONAL_ENVIRONMENT,
        }
    ),
}

_CONTEXT_SCOPE_EVIDENCE_SECTIONS = frozenset({"overview", "components"})


def _stable_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _context_section_prompt(section_name: str) -> str:
    template = load_prompt("node1_context.md", "context_section_template")
    return (
        template.replace("[[SECTION_NAME]]", section_name)
        .replace("[[COMMON_RULES]]", _CONTEXT_COMMON_RULES)
        .replace("[[SECTION_BODY]]", _CONTEXT_SECTION_BODIES[section_name])
    )


def _context_section_cache_inputs(
    *,
    section_name: str,
    source_packet_sha256: str,
    text_model: str,
    material_payload: dict[str, Any],
    schema_class: type[BaseModel],
) -> dict[str, str]:
    """Describe every deterministic input that may change one context section."""
    return {
        "section_name": section_name,
        "source_packet_sha256": source_packet_sha256,
        "text_model": text_model,
        "context_rule_version": _CONTEXT_SECTION_RULE_VERSIONS[section_name],
        "material_sha256": _stable_sha256(material_payload),
        "prompt_sha256": sha256(
            _context_section_prompt(section_name).encode("utf-8")
        ).hexdigest(),
        "schema_sha256": _stable_sha256(schema_class.model_json_schema()),
    }


def _context_section_checkpoint_path(
    config: RunnableConfig,
    section_name: str,
) -> Path | None:
    raw_directory = config.get("configurable", {}).get(
        "context_section_checkpoint_dir"
    )
    if not raw_directory:
        return None
    return Path(raw_directory) / f"{section_name}.json"


def _load_context_section_checkpoint(
    *,
    path: Path | None,
    fingerprint: str,
    schema_class: type[BaseModel],
) -> BaseModel | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "context_section_checkpoint.v1":
            return None
        if payload.get("fingerprint") != fingerprint:
            return None
        return schema_class.model_validate(payload["result"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Node [1] 分段缓存无效，将重新生成：%s (%s)", path, exc)
        return None


def _save_context_section_checkpoint(
    *,
    path: Path | None,
    cache_inputs: dict[str, str],
    fingerprint: str,
    result: BaseModel,
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "context_section_checkpoint.v1",
        "fingerprint": fingerprint,
        "cache_inputs": cache_inputs,
        "result": result.model_dump(mode="json"),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _llm_model_name(llm: Any) -> str:
    return str(getattr(llm, "model_name", None) or getattr(llm, "model", "unknown"))


def _scope_evidence_contract(scope: ScopeStatement, section_name: str) -> list[dict[str, Any]]:
    """Expose upstream references only where Node [0] boundary facts are relevant."""
    if section_name not in _CONTEXT_SCOPE_EVIDENCE_SECTIONS:
        return []
    return [
        {
            "evidence_id": evidence.evidence_id,
            "block_id": evidence.source.block_id,
            "quote": evidence.quote,
            "allowed_uses": ["产品身份", "Node0边界", "范围状态"],
        }
        for evidence in iter_evidence_refs(scope)
        if evidence.source.block_id is not None
    ]


def _context_section_material(
    *,
    section_name: str,
    scope: ScopeStatement,
    facts: Any,
) -> tuple[dict[str, Any], set[str]]:
    """Build the section input and its exact fact-backed evidence allowlist."""
    fields = _CONTEXT_SECTION_FIELDS[section_name]
    fact_payload = facts.prompt_payload(set(fields))
    scope_payload = _scope_downstream_payload(scope)
    scope_payload.pop("evidence", None)
    scope_support = _scope_evidence_contract(scope, section_name)
    fact_payload["evidence_contract"]["scope_support"] = scope_support
    fact_payload["evidence_contract"]["scope_rule"] = (
        "scope_support 仅可用于产品身份、Node0边界和范围状态；列表为空时不得引用Scope证据。"
    )
    allowed_block_ids = set(facts.fact_block_ids(fields))
    allowed_block_ids.update(item["block_id"] for item in scope_support)
    return {"scope": scope_payload, **fact_payload}, allowed_block_ids


def _extract_context_section(
    *,
    llm: Any,
    section_name: str,
    schema_class: type[BaseModel],
    scope: ScopeStatement,
    facts: Any,
    binding: EvidencePacketBinding,
    config: RunnableConfig,
) -> BaseModel:
    """Generate or reuse one independently fingerprinted ProductContext section."""
    material_payload, allowed_block_ids = _context_section_material(
        section_name=section_name,
        scope=scope,
        facts=facts,
    )
    cache_inputs = _context_section_cache_inputs(
        section_name=section_name,
        source_packet_sha256=binding.reference.packet_sha256,
        text_model=_llm_model_name(llm),
        material_payload=material_payload,
        schema_class=schema_class,
    )
    fingerprint = _stable_sha256(cache_inputs)
    checkpoint_path = _context_section_checkpoint_path(config, section_name)
    cache_policy = config.get("configurable", {}).get(
        "context_section_cache_policy", "reuse"
    )
    if cache_policy not in {"reuse", "refresh"}:
        raise ValueError(
            "configurable.context_section_cache_policy must be 'reuse' or 'refresh'"
        )

    if cache_policy == "reuse":
        cached = _load_context_section_checkpoint(
            path=checkpoint_path,
            fingerprint=fingerprint,
            schema_class=schema_class,
        )
        if cached is not None:
            try:
                cached = _validated_retrieved_output(
                    cached,
                    binding,
                    allowed_block_ids,
                )
                logger.info("Node [1] 复用分段缓存：%s", section_name)
                return cached
            except ValueError as exc:
                logger.warning(
                    "Node [1] 分段缓存证据校验失败，将重新生成：%s (%s)",
                    section_name,
                    exc,
                )

    logger.info("Node [1] 生成分段：%s", section_name)
    result = extract_with_retry(
        task_label=f"node_1/{section_name}",
        llm=llm,
        prompt_template=_context_section_prompt(section_name),
        schema_class=schema_class,
        sample_input=json.dumps(material_payload, ensure_ascii=False, indent=2),
        semantic_validator=lambda value: _validated_retrieved_output(
            value,
            binding,
            allowed_block_ids,
        ),
        payload_transformer=lambda payload: canonicalize_evidence_payload(
            payload,
            binding,
            allowed_block_ids=allowed_block_ids,
        ),
    )
    _save_context_section_checkpoint(
        path=checkpoint_path,
        cache_inputs=cache_inputs,
        fingerprint=fingerprint,
        result=result,
    )
    return result


def _assemble_product_context(
    overview: ProductContextOverview,
    functions: ProductFunctionCatalog,
    components: ComponentInventory,
    communications: CommunicationMatrix,
) -> ProductContext:
    """Combine four validated sections without another LLM call."""
    return ProductContext(
        product_name=overview.product_name,
        product_version=overview.product_version,
        iprfu=overview.iprfu,
        user_description=overview.user_description,
        operational_environment=overview.operational_environment,
        functions=functions.functions,
        communication_matrix=communications,
        component_inventory=components,
        existing_security_functions=functions.existing_security_functions,
        existing_non_security_functions=functions.existing_non_security_functions,
        rdps_dependencies=overview.rdps_dependencies,
        evidence=overview.evidence,
        assessment=overview.assessment,
        assessment_notes=overview.assessment_notes,
    )


def _uses_field_retrieval(config: RunnableConfig) -> bool:
    return bool(config.get("configurable", {}).get("rag_index_dir"))


def _validated_retrieved_output(value, binding, allowed_block_ids: set[str]):
    validate_evidence_bindings(value, binding)
    return validate_evidence_block_subset(value, allowed_block_ids)


def _load_runtime_evidence(config: RunnableConfig) -> EvidencePacketBinding:
    """Resolve the evidence packet from runtime config without storing its path in State."""
    configurable = config.get("configurable", {})
    packet_path = configurable.get("evidence_packet_path")
    if not packet_path:
        raise ValueError("configurable.evidence_packet_path is required")
    workspace = configurable.get("workspace")
    return load_evidence_packet(
        packet_path,
        workspace=workspace,
        verify_source_files=True,
    )


def _scope_downstream_payload(scope: ScopeStatement) -> dict[str, Any]:
    """Keep Node [0] system review diagnostics out of Node [1] business synthesis."""
    payload = scope.model_dump(mode="json")
    payload.pop("review_notes", None)
    return payload


def _component_name_matches_scope(component_name: str, scope_text: str) -> bool:
    """Match stable model/type identifiers without treating generic words as identity."""
    compact_name = "".join(component_name.casefold().split())
    compact_scope = "".join(scope_text.casefold().split())
    if compact_name and compact_name in compact_scope:
        return True
    identifiers = re.findall(r"[a-z]+(?:[-&]?[a-z0-9]+)*\d+[a-z0-9-]*", compact_name)
    if any(identifier in compact_scope for identifier in identifiers):
        return True
    return False


def _component_evidence_scope_status(component: Any) -> str | None:
    """Derive only explicit delivery status from the component's own evidence."""
    evidence_text = " ".join(
        evidence.quote or "" for evidence in getattr(component, "evidence", [])
    )
    if not evidence_text:
        return None
    compact_name = _compact_business_token(component.name)
    identifiers = re.findall(r"[a-z][a-z0-9-]*", component.name.casefold())
    matching_segments = [
        segment
        for segment in re.split(r"[，,、;；\n]", evidence_text)
        if compact_name in _compact_business_token(segment)
        or any(identifier in segment.casefold() for identifier in identifiers)
    ]
    local_text = " ".join(matching_segments)
    if local_text and any(marker in local_text.casefold() for marker in ("选配", "可选", "optional")):
        return "conditional"
    lowered = evidence_text.casefold()
    if any(marker.casefold() in lowered for marker in _COMPONENT_CONFIRMED_DELIVERY_MARKERS):
        return "confirmed"
    return None


def _field_facts(facts: Any, field_id: RetrievalField) -> list[Any]:
    if facts is None:
        return []
    return [
        fact
        for batch in getattr(facts, "batches", ())
        if batch.field_id == field_id
        for fact in batch.facts
    ]


def _fact_records(facts: Any, field_id: RetrievalField) -> list[tuple[str, set[str]]]:
    return [
        (fact.statement, set(fact.block_ids))
        for fact in _field_facts(facts, field_id)
    ]


def _compact_business_token(value: str | None) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (value or "").casefold())


def _best_communication_fact(
    flow: Any,
    records: list[tuple[str, set[str]]],
) -> str | None:
    evidence_blocks = {
        evidence.source.block_id
        for evidence in iter_evidence_refs(flow)
        if evidence.source.block_id is not None
    }
    protocol = _compact_business_token(flow.protocol)
    port_numbers = re.findall(r"\d+", flow.port or "")
    ranked: list[tuple[int, str]] = []
    for statement, block_ids in records:
        if evidence_blocks and not evidence_blocks.intersection(block_ids):
            continue
        compact = _compact_business_token(statement)
        score = 0
        if protocol and protocol in compact:
            score += 20
        elif protocol:
            continue
        score += 4 * sum(number in statement for number in port_numbers)
        score += int(_compact_business_token(flow.source) in compact)
        score += int(_compact_business_token(flow.destination) in compact)
        ranked.append((score, statement))
    if not ranked:
        return None
    return max(ranked, key=lambda item: item[0])[1]


def _fact_attribute(fact: Any, key: str) -> str | None:
    value = getattr(fact, "attributes", {}).get(key) if fact is not None else None
    return value if isinstance(value, str) else None


def _fact_attribute_list(fact: Any, key: str) -> list[str] | None:
    value = getattr(fact, "attributes", {}).get(key) if fact is not None else None
    return list(value) if isinstance(value, list) else None


def _best_structured_communication_fact(flow: Any, facts: list[Any]) -> Any | None:
    """Match a flow to the best same-block fact without parsing generated prose."""
    evidence_blocks = {
        evidence.source.block_id
        for evidence in iter_evidence_refs(flow)
        if evidence.source.block_id is not None
    }
    protocol = _compact_business_token(flow.protocol)
    port_numbers = re.findall(r"\d+", flow.port or "")
    ranked: list[tuple[int, Any]] = []
    for fact in facts:
        attributes = getattr(fact, "attributes", {})
        if not attributes:
            continue
        block_ids = set(fact.block_ids)
        if evidence_blocks and not evidence_blocks.intersection(block_ids):
            continue
        searchable = " ".join(
            [
                fact.statement,
                *(
                    " ".join(value) if isinstance(value, list) else value or ""
                    for value in attributes.values()
                ),
            ]
        )
        compact = _compact_business_token(searchable)
        score = 0
        if protocol and protocol in compact:
            score += 20
        elif protocol:
            continue
        score += 4 * sum(number in searchable for number in port_numbers)
        score += int(_compact_business_token(flow.source) in compact)
        score += int(_compact_business_token(flow.destination) in compact)
        ranked.append((score, fact))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


def _best_structured_component_fact(component: Any, facts: list[Any]) -> Any | None:
    """Match one component to a structured component fact using name and evidence blocks."""
    evidence_blocks = {
        evidence.source.block_id
        for evidence in iter_evidence_refs(component)
        if evidence.source.block_id is not None
    }
    component_name = _compact_business_token(component.name)
    ranked: list[tuple[int, Any]] = []
    for fact in facts:
        attributes = getattr(fact, "attributes", {})
        fact_name = attributes.get("component_name")
        if not isinstance(fact_name, str):
            continue
        block_ids = set(fact.block_ids)
        if evidence_blocks and not evidence_blocks.intersection(block_ids):
            continue
        compact_fact_name = _compact_business_token(fact_name)
        if not component_name or not compact_fact_name:
            continue
        if component_name == compact_fact_name:
            score = 20
        elif component_name in compact_fact_name or compact_fact_name in component_name:
            score = 10
        else:
            continue
        score += 5 * bool(evidence_blocks.intersection(block_ids))
        ranked.append((score, fact))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


def _labeled_fact_value(statement: str, label: str) -> str | None:
    match = re.search(rf"{label}\s*([^，。；;]+)", statement)
    return match.group(1).strip() if match else None


def _fact_endpoint_value(statement: str | None, role: str) -> str | None:
    """Read endpoints from both label-style and natural field-fact sentences."""
    if not statement:
        return None
    patterns = (
        (r"源设备为\s*([^，。；;]+)", r"([^，。；;]+?)作为源设备")
        if role == "source"
        else (r"目的设备为\s*([^，。；;]+)", r"向\s*([^，。；;]+?)目的设备")
    )
    for pattern in patterns:
        match = re.search(pattern, statement)
        if match:
            return match.group(1).strip()
    return None


def _fact_destination_port(statement: str | None) -> str | None:
    if not statement:
        return None
    labeled = _labeled_fact_value(statement, r"目的端口(?:范围)?为")
    if labeled:
        return labeled
    match = re.search(r"目的设备的\s*([^，。；;]+?)\s*端口(?:范围)?(?:发起|建立|连接|，|。)", statement)
    return match.group(1).strip() if match else None


def _fact_communication_attribute(statement: str | None, label: str) -> str | None:
    if not statement:
        return None
    return _labeled_fact_value(statement, rf"{label}为")


def _communication_support_text(
    flow: Any,
    records: list[tuple[str, set[str]]],
    best_statement: str | None,
) -> str:
    evidence_blocks = {
        evidence.source.block_id
        for evidence in iter_evidence_refs(flow)
        if evidence.source.block_id is not None
    }
    linked = [
        statement
        for statement, block_ids in records
        if evidence_blocks and evidence_blocks.intersection(block_ids)
    ]
    if best_statement and best_statement not in linked:
        linked.append(best_statement)
    return " ".join(linked)


def _supported_communication_value(value: str | None, support_text: str) -> bool:
    """Require a material communication attribute to appear in its supporting facts."""
    if not value or not support_text:
        return False
    compact_value = _compact_business_token(value)
    compact_support = _compact_business_token(support_text)
    if compact_value and compact_value in compact_support:
        return True
    if compact_value in {"none", "no", "无", "未说明", "未知"}:
        return any(marker in support_text for marker in ("无", "未说明", "未知", "不支持"))
    return False


def _fact_direction_basis(statement: str | None) -> str:
    if not statement:
        return "unknown"
    if any(marker in statement for marker in ("监听", "开放端口", "暴露端口", "服务端口")):
        return "listener_exposure"
    if any(marker in statement for marker in ("发起连接", "连接发起", "客户端连接")):
        return "connection_initiation"
    if any(marker in statement for marker in ("业务数据方向", "数据流向", "上送", "下发")):
        return "business_data_flow"
    if "源设备为" in statement and "目的设备为" in statement:
        return "documented_endpoints"
    return "unknown"


def _fact_business_direction(statement: str | None, product_name: str) -> str:
    if not statement:
        return "unknown"
    explicit = _labeled_fact_value(statement, r"(?:业务)?数据(?:流向|方向)为")
    if explicit:
        normalized = _compact_business_token(explicit)
        if any(marker in normalized for marker in ("双向", "bidirectional")):
            return "bidirectional"
        product = _compact_business_token(product_name)
        if product and product in normalized:
            if normalized.startswith(product) or any(
                marker in explicit for marker in ("产品到", "设备到", "产品发往", "设备发往")
            ):
                return "from_product"
            if normalized.endswith(product) or any(
                marker in explicit for marker in ("到产品", "到设备", "发往产品", "发往设备")
            ):
                return "to_product"
        if any(marker in explicit for marker in ("产品发出", "设备发出", "上送")):
            return "from_product"
        if any(marker in explicit for marker in ("产品接收", "设备接收", "下发")):
            return "to_product"
    return "unknown"


def _fact_activation_status(support_text: str) -> str:
    if any(marker in support_text for marker in ("默认关闭", "默认禁用")):
        return "disabled_by_default"
    if any(marker in support_text for marker in ("默认开启", "默认启用", "已启用")):
        return "enabled"
    if any(marker in support_text for marker in _CONDITIONAL_MARKERS):
        return "conditional"
    return "unknown"


def _reconcile_enum_value(left: str, right: str, unknown: str = "unknown") -> str:
    if left == right:
        return left
    if left == unknown:
        return right
    if right == unknown:
        return left
    return unknown


def _flow_direction(source: str, destination: str, product_name: str) -> str | None:
    identifiers = re.findall(
        r"[a-z]+(?:[-&]?[a-z0-9]+)*\d+[a-z0-9-]*",
        product_name.casefold(),
    )

    def is_product(value: str) -> bool:
        compact = _compact_business_token(value)
        return bool(compact) and (
            compact in _compact_business_token(product_name)
            or any(identifier in compact for identifier in identifiers)
        )

    source_is_product = is_product(source)
    destination_is_product = is_product(destination)
    if source_is_product and not destination_is_product:
        return "outbound"
    if destination_is_product and not source_is_product:
        return "inbound"
    return None


def _repair_communication_matrix(
    context: ProductContext,
    scope: ScopeStatement,
    facts: Any,
) -> tuple[Any, list[str]]:
    communication_facts = _field_facts(facts, RetrievalField.COMMUNICATIONS)
    records = _fact_records(facts, RetrievalField.COMMUNICATIONS)
    if not records:
        records = [
            (evidence.quote, {evidence.source.block_id})
            for flow in context.communication_matrix.entries
            for evidence in iter_evidence_refs(flow)
            if evidence.quote and evidence.source.block_id is not None
        ]
    if not records:
        return context.communication_matrix, []
    repaired: list[Any] = []
    notes: list[str] = []
    seen: dict[tuple[str, ...], int] = {}
    for flow in context.communication_matrix.entries:
        structured_fact = _best_structured_communication_fact(flow, communication_facts)
        statement = (
            structured_fact.statement
            if structured_fact is not None
            else _best_communication_fact(flow, records)
        )
        updates: dict[str, Any] = {}
        fact_source = _fact_attribute(structured_fact, "source")
        fact_destination = _fact_attribute(structured_fact, "destination")
        fact_port = _fact_attribute(structured_fact, "port")
        fact_protocol = _fact_attribute(structured_fact, "protocol")
        fact_interface = _fact_attribute(structured_fact, "interface")
        if statement:
            fact_source = fact_source or _fact_endpoint_value(statement, "source")
            fact_destination = fact_destination or _fact_endpoint_value(statement, "destination")
            fact_port = fact_port or _fact_destination_port(statement)
            if fact_source:
                updates["source"] = fact_source
            if fact_destination:
                updates["destination"] = fact_destination
            if fact_port:
                updates["port"] = fact_port
            if fact_protocol:
                updates["protocol"] = fact_protocol
            if fact_interface:
                updates["interface"] = fact_interface

        supporting_text = _communication_support_text(flow, records, statement)
        if structured_fact is not None:
            supporting_text += " " + " ".join(
                " ".join(value) if isinstance(value, list) else value or ""
                for value in structured_fact.attributes.values()
            )
        if statement:
            if not fact_source and not _supported_communication_value(
                flow.source, supporting_text
            ):
                updates["source"] = "未说明"
                notes.append("通信源端缺少对应事实支持，已恢复为未知。")
            if not fact_destination and not _supported_communication_value(
                flow.destination, supporting_text
            ):
                updates["destination"] = "未说明"
                notes.append("通信目的端缺少对应事实支持，已恢复为未知。")
        endpoint_unknown = bool(
            statement
            and re.search(r"(?:端点|目的设备|目的端)(?:为)?(?:未说明|未知|未提供)", statement)
        )
        if endpoint_unknown and not fact_destination:
            updates["destination"] = "未说明"
            notes.append("通信目的端缺少对应事实支持，已恢复为未知。")
        if (
            not fact_port
            and flow.port
            and supporting_text
            and flow.port not in supporting_text
        ):
            updates["port"] = None
            notes.append("通信端口缺少对应事实支持，已恢复为未知。")

        source = updates.get("source", flow.source)
        destination = updates.get("destination", flow.destination)
        structured_basis = _fact_attribute(structured_fact, "direction_basis")
        basis = "documented_endpoints" if fact_source and fact_destination else (
            structured_basis or _fact_direction_basis(statement)
        )
        if basis == "documented_endpoints":
            direction = _flow_direction(source, destination, scope.product_name)
            updates["direction"] = direction
            updates["direction_basis"] = basis
        elif basis in {"connection_initiation", "listener_exposure"}:
            updates["direction_basis"] = basis
            if basis == "listener_exposure":
                updates["direction"] = None
        else:
            if flow.direction is not None:
                updates["direction"] = None
                notes.append("通信连接方向缺少端点或连接角色事实，已恢复为未知。")
            updates["direction_basis"] = basis

        business_direction = _fact_attribute(
            structured_fact, "business_data_direction"
        ) or _fact_business_direction(statement, scope.product_name)
        if business_direction == "unknown" and flow.business_data_direction != "unknown":
            notes.append("业务数据方向缺少直接事实，已恢复为未知。")
        updates["business_data_direction"] = business_direction

        activation_status = _fact_attribute(
            structured_fact, "activation_status"
        ) or _fact_activation_status(supporting_text)
        updates["activation_status"] = activation_status
        structured_conditions = _fact_attribute_list(structured_fact, "conditions")
        if activation_status == "disabled_by_default":
            updates["conditions"] = structured_conditions or [
                "材料说明该通信能力默认关闭；实际启用状态待确认。"
            ]
        elif activation_status == "conditional":
            supported_conditions = [
                item
                for item in flow.conditions
                if _supported_communication_value(item, supporting_text)
            ]
            updates["conditions"] = structured_conditions or supported_conditions or [
                "启用或适用状态取决于材料所述条件。"
            ]
        elif activation_status == "enabled":
            updates["conditions"] = []
        elif flow.conditions:
            updates["conditions"] = []
            notes.append("通信适用条件缺少直接事实，已恢复为未知。")

        structured_data = _fact_attribute_list(structured_fact, "data_exchanged")
        if structured_data is not None:
            updates["data_exchanged"] = structured_data
        else:
            supported_data = [
                item
                for item in flow.data_exchanged
                if _supported_communication_value(item, supporting_text)
            ]
            if len(supported_data) != len(flow.data_exchanged):
                updates["data_exchanged"] = supported_data
                notes.append("已移除通信流中缺少直接事实的数据用途描述。")
        for field_name, label in (
            ("encryption", "加密机制"),
            ("authentication", "认证机制"),
        ):
            value = getattr(flow, field_name)
            fact_label = "加密方式" if field_name == "encryption" else "认证方式"
            fact_value = _fact_attribute(structured_fact, field_name)
            if not fact_value:
                fact_value = _fact_communication_attribute(statement, fact_label)
            if fact_value:
                updates[field_name] = fact_value
            elif value and not _supported_communication_value(value, supporting_text):
                updates[field_name] = None
                notes.append(f"{label}缺少直接事实支持，已恢复为未知。")
        if (
            not fact_interface
            and flow.interface
            and not _supported_communication_value(flow.interface, supporting_text)
        ):
            updates["interface"] = None
            notes.append("通信接口缺少直接事实支持，已恢复为未知。")
        supported_security_notes = [
            item
            for item in flow.security_notes
            if _supported_communication_value(item, supporting_text)
            or any(marker in item for marker in _UNRESOLVED_MARKERS)
        ]
        if len(supported_security_notes) != len(flow.security_notes):
            updates["security_notes"] = supported_security_notes
            notes.append("已移除通信流中缺少直接事实的安全说明。")

        candidate = flow.model_copy(update=updates)
        key = tuple(
            _compact_business_token(value)
            for value in (
                candidate.source,
                candidate.destination,
                candidate.protocol,
                candidate.port,
                candidate.interface,
                candidate.direction,
                candidate.direction_basis,
                candidate.business_data_direction,
            )
        )
        if key in seen:
            index = seen[key]
            existing = repaired[index]
            evidence_by_key = {
                (item.evidence_id, item.source.block_id): item
                for item in (*existing.evidence, *candidate.evidence)
            }
            repaired[index] = existing.model_copy(
                update={
                    "evidence": list(evidence_by_key.values()),
                    "data_exchanged": list(
                        dict.fromkeys((*existing.data_exchanged, *candidate.data_exchanged))
                    ),
                    "security_notes": list(
                        dict.fromkeys((*existing.security_notes, *candidate.security_notes))
                    ),
                    "activation_status": _reconcile_enum_value(
                        existing.activation_status,
                        candidate.activation_status,
                    ),
                    "conditions": list(
                        dict.fromkeys((*existing.conditions, *candidate.conditions))
                    ),
                }
            )
            notes.append("已合并由同一事实重复生成的通信流。")
            continue
        seen[key] = len(repaired)
        repaired.append(candidate)

    repaired = [
        flow.model_copy(update={"flow_id": f"FLOW-{index:03d}"})
        for index, flow in enumerate(repaired, start=1)
    ]
    return context.communication_matrix.model_copy(update={"entries": repaired}), notes


def _repair_function_security_flags(
    context: ProductContext,
    facts: Any,
) -> tuple[list[Any], list[str]]:
    security_blocks = {
        block_id
        for _, block_ids in _fact_records(facts, RetrievalField.SECURITY_FUNCTIONS)
        for block_id in block_ids
    }
    repaired = []
    notes = []
    for function in context.functions:
        evidence_blocks = {
            evidence.source.block_id
            for evidence in iter_evidence_refs(function)
            if evidence.source.block_id is not None
        }
        if not function.is_security_function and evidence_blocks.intersection(security_blocks):
            function = function.model_copy(update={"is_security_function": True})
            notes.append(f"功能“{function.name}”由安全功能事实支持，已标记为安全功能。")
        repaired.append(function)
    return repaired, notes


def _repair_sensitive_function_descriptions(
    context: ProductContext,
    facts: Any,
) -> tuple[list[Any], list[str]]:
    """Collapse unsupported high-impact details back to the closest atomic fact."""
    records = [
        *_fact_records(facts, RetrievalField.FUNCTIONS),
        *_fact_records(facts, RetrievalField.SECURITY_FUNCTIONS),
    ]
    repaired = []
    notes = []
    for function in context.functions:
        evidence_blocks = {
            evidence.source.block_id
            for evidence in iter_evidence_refs(function)
            if evidence.source.block_id is not None
        }
        supported = [
            statement
            for statement, block_ids in records
            if not evidence_blocks or evidence_blocks.intersection(block_ids)
        ]
        description = function.description
        name = function.name.casefold()

        if "更新" in name or "升级" in name:
            direct = next(
                (
                    statement
                    for statement in supported
                    if "更新" in statement or "升级" in statement
                ),
                None,
            )
            unsupported = [
                marker
                for marker in ("回滚", "完整性校验")
                if marker in description and not any(marker in item for item in supported)
            ]
            if direct and unsupported:
                description = direct
                notes.append(f"功能“{function.name}”已移除证据未支持的更新机制描述。")

        if "恢复出厂" in name:
            direct = next(
                (statement for statement in supported if "恢复出厂" in statement),
                None,
            )
            deletion_details = ("用户配置", "网络参数", "证书", "所有日志", "初始交付状态")
            unsupported = [
                marker
                for marker in deletion_details
                if marker in description and not any(marker in item for item in supported)
            ]
            if direct and unsupported:
                description = direct
                notes.append(f"功能“{function.name}”已按直接证据收窄数据清除范围。")

        repaired.append(function.model_copy(update={"description": description}))
    return repaired, notes


def _repair_component_types(
    context: ProductContext,
    facts: Any,
) -> tuple[Any, list[str]]:
    component_facts = _field_facts(facts, RetrievalField.COMPONENTS)
    records = _fact_records(facts, RetrievalField.COMPONENTS)
    repaired = []
    notes = []
    for component in context.component_inventory.entries:
        component_type = component.component_type
        structured_fact = _best_structured_component_fact(component, component_facts)
        structured_type = _fact_attribute(structured_fact, "component_type")
        if structured_type:
            component_type = structured_type
            if component_type != component.component_type:
                notes.append(
                    f"组件“{component.name}”的类型已按结构化证据事实恢复为{component_type}。"
                )
        elif component_type.casefold() in {"firmware", "software"} and not any(
            marker in component.name.casefold() for marker in ("固件", "软件", "镜像", "firmware")
        ):
            name = _compact_business_token(component.name)
            related = " ".join(
                statement
                for statement, _ in records
                if name and name in _compact_business_token(statement)
            )
            combined = f"{component.role} {related}"
            if any(marker in combined for marker in ("数据采集器", "子系统")):
                component_type = "embedded_subsystem"
            elif any(
                marker in combined
                for marker in ("接口", "网口", "端口", "总线", "模块", "继电器", "数字量")
            ):
                component_type = "hardware_module"
            if component_type != component.component_type:
                notes.append(
                    f"组件“{component.name}”存在物理接口/子系统事实，已取消{component.component_type}类型。"
                )
        repaired.append(component.model_copy(update={"component_type": component_type}))
    return context.component_inventory.model_copy(update={"entries": repaired}), notes


def _clean_context_internal_references(value: Any) -> Any:
    if isinstance(value, EvidenceRef):
        return value
    if isinstance(value, Enum):
        return value
    if isinstance(value, BaseModel):
        return value.model_copy(
            update={
                field_name: _clean_context_internal_references(getattr(value, field_name))
                for field_name in type(value).model_fields
            }
        )
    if isinstance(value, list):
        return [_clean_context_internal_references(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clean_context_internal_references(item) for item in value)
    if isinstance(value, str):
        return _clean_business_text(value)
    return value


def _mark_product_context_as_draft(
    context: ProductContext,
    scope: ScopeStatement,
    facts: Any = None,
) -> ProductContext:
    """Make machine-generated context explicitly reviewable without blocking Node [2]."""
    draft_note = "本结果为材料整理草稿；资料完整度、实际交付配置和适用结论待工程师确认。"
    repair_notes: list[str] = []
    generated_note = _clean_business_text(context.assessment_notes or "")
    foreseeable_use = []
    for item in context.iprfu.reasonably_foreseeable_use:
        if "未明确" in item and any(marker in item for marker in ("合理预期", "推测", "假定")):
            repair_notes.append("已移除无证据的合理预期/推测性使用场景。")
            continue
        foreseeable_use.append(_clean_business_text(item))
    iprfu = context.iprfu.model_copy(update={"reasonably_foreseeable_use": foreseeable_use})

    user_evidence_text = "\n".join(
        item.quote or "" for item in context.user_description.evidence
    )
    experience_level = context.user_description.experience_level
    if experience_level and not any(
        marker in user_evidence_text for marker in _EXPERIENCE_EVIDENCE_MARKERS
    ):
        experience_level = None
        repair_notes.append("用户经验/培训缺少直接证据，已恢复为未知。")

    user_description = context.user_description.model_copy(
        update={"experience_level": experience_level}
    )
    functions = context.functions
    environment = context.operational_environment
    rdps_dependencies = context.rdps_dependencies
    if scope.classification.has_rdps is not True:
        if (
            context.rdps_dependencies
            or context.operational_environment.rdps_dependency_map
            or context.user_description.rdps_dependence
            or any(function.rdps_dependencies for function in context.functions)
        ):
            repair_notes.append("Node0尚未确认RDPS，已清空Node1的确定性RDPS依赖字段。")
        rdps_dependencies = None
        environment = environment.model_copy(update={"rdps_dependency_map": None})
        user_description = user_description.model_copy(update={"rdps_dependence": None})
        functions = [
            function.model_copy(update={"rdps_dependencies": []})
            for function in context.functions
        ]

    confirmed_scope = "\n".join(scope.in_scope_components)
    conditional_scope = "\n".join(scope.conditional_scope_components)
    external_scope = "\n".join(scope.out_of_scope_components)
    component_facts = _field_facts(facts, RetrievalField.COMPONENTS)
    component_entries = []
    for component in context.component_inventory.entries:
        status = component.scope_status
        conditions = [_clean_business_text(item) for item in component.conditions]
        structured_fact = _best_structured_component_fact(component, component_facts)
        structured_status = _fact_attribute(structured_fact, "scope_status")
        structured_conditions = _fact_attribute_list(structured_fact, "conditions") or []
        conditions = list(dict.fromkeys((*conditions, *structured_conditions)))
        if structured_fact is not None:
            evidence_scope_status = (
                structured_status if structured_status != "unknown" else None
            )
        else:
            evidence_scope_status = _component_evidence_scope_status(component)
        scope_matches = {
            boundary_status
            for boundary_status, boundary_text in (
                ("confirmed", confirmed_scope),
                ("conditional", conditional_scope),
                ("external", external_scope),
            )
            if _component_name_matches_scope(component.name, boundary_text)
        }
        if len(scope_matches) > 1:
            status = "unknown"
            conflict_note = "Node0对该对象存在多个范围状态，需人工确认。"
            if conflict_note not in conditions:
                conditions.append(conflict_note)
            repair_notes.append(f"组件“{component.name}”的上游范围状态冲突，已恢复为unknown。")
        elif scope_matches == {"confirmed"}:
            status = "confirmed"
        elif scope_matches == {"conditional"}:
            status = "conditional"
        elif scope_matches == {"external"}:
            status = "external"
        elif not scope_matches and evidence_scope_status is not None:
            status = evidence_scope_status
            if status == "confirmed":
                conditions = [
                    condition
                    for condition in conditions
                    if "Node0未确认该组件属于实际交付范围" not in condition
                ]
            repair_notes.append(
                f"组件“{component.name}”的交付状态已按其直接证据恢复为{status}。"
            )
        elif status == "confirmed":
            status = "unknown"
            if not conditions:
                conditions = ["Node0未确认该组件属于实际交付范围，需结合BOM/合同核实。"]
            repair_notes.append(f"组件“{component.name}”缺少Node0确认，已取消confirmed状态。")
        if status != "external" and any(
            marker in condition for condition in conditions for marker in ("选配", "可选")
        ):
            if status != "conditional":
                repair_notes.append(
                    f"组件“{component.name}”包含明确选配/可选条件，已改为conditional状态。"
                )
            status = "conditional"

        is_third_party = component.is_third_party
        responsibility_text = " ".join(evidence.quote or "" for evidence in component.evidence)
        supplier_supported = bool(
            component.supplier
            and _compact_business_token(component.supplier)
            in _compact_business_token(responsibility_text)
        )
        responsibility_supported = supplier_supported or any(
            marker.casefold() in responsibility_text.casefold()
            for marker in _RESPONSIBILITY_EVIDENCE_MARKERS
        )
        if is_third_party is not None and not responsibility_supported:
            is_third_party = None
            repair_notes.append(
                f"组件“{component.name}”的供应责任缺少直接证据，第三方属性已恢复为unknown。"
            )
        component_entries.append(
            component.model_copy(
                update={
                    "scope_status": status,
                    "conditions": conditions,
                    "is_third_party": is_third_party,
                }
            )
        )
    components = context.component_inventory.model_copy(
        update={
            "entries": component_entries,
            "completeness_notes": _clean_business_text(
                context.component_inventory.completeness_notes or ""
            )
            or None
        }
    )
    functions, function_notes = _repair_function_security_flags(
        context.model_copy(update={"functions": functions}),
        facts,
    )
    functions, function_description_notes = _repair_sensitive_function_descriptions(
        context.model_copy(update={"functions": functions}),
        facts,
    )
    components, component_notes = _repair_component_types(
        context.model_copy(update={"component_inventory": components}),
        facts,
    )
    communications, communication_notes = _repair_communication_matrix(
        context,
        scope,
        facts,
    )
    repair_notes.extend(function_notes)
    repair_notes.extend(function_description_notes)
    repair_notes.extend(component_notes)
    repair_notes.extend(communication_notes)
    communication_completeness = _clean_business_text(
        communications.completeness_notes or ""
    )
    clauses = re.split(r"(?<=[。；;])", communication_completeness)
    communication_completeness = "".join(
        clause
        for clause in clauses
        if not (
            "udp" in clause.casefold()
            and any(marker in clause for marker in ("未提及", "未说明", "不存在"))
        )
    ).strip()
    communications = context.communication_matrix.model_copy(
        update={
            "entries": communications.entries,
            "completeness_notes": communication_completeness or None,
        }
    )
    updates: dict[str, Any] = {
        "product_name": scope.product_name,
        "iprfu": iprfu,
        "user_description": user_description,
        "operational_environment": environment,
        "functions": functions,
        "rdps_dependencies": rdps_dependencies,
        "assessment": AssessmentVerdict.PARTIAL,
        "assessment_notes": " ".join(
            item for item in (generated_note, *dict.fromkeys(repair_notes), draft_note) if item
        ),
        "component_inventory": components,
        "communication_matrix": communications,
    }
    if scope.product_version is not None:
        updates["product_version"] = scope.product_version
    return _clean_context_internal_references(context.model_copy(update=updates))


def _validate_product_context(
    context: ProductContext,
    scope: ScopeStatement,
    binding: EvidencePacketBinding,
    allowed_block_ids: set[str] | None = None,
    facts: Any = None,
) -> ProductContext:
    if allowed_block_ids is None:
        validate_evidence_bindings(context, binding)
    else:
        _validated_retrieved_output(context, binding, allowed_block_ids)
    return _mark_product_context_as_draft(context, scope, facts)


def define_scope(state: TaraState, config: RunnableConfig) -> dict:
    """Node [0]: define the legal/product scope from validated packet evidence."""
    logger.info("进入 Node [0] 法律/产品定界节点")
    errors = list(state.get("errors", []))
    updates: dict = {
        "scope": None,
        "product_context": None,
        "risk_methodology": None,
        "risk_acceptance_criteria": None,
        "assets": [],
        "asset_assessment": None,
        "asset_notes": None,
        "asset_review_approved": False,
        "asset_review_notes": None,
        "threat_assessment": None,
        "errors": errors,
        "current_step": "node_0_scope",
    }

    try:
        binding = _load_runtime_evidence(config)
        updates["evidence_packet_ref"] = binding.reference
        llm = get_llm()
        if _uses_field_retrieval(config):
            facts = extract_node_facts(
                llm=llm,
                scope=binding,
                node_id=EvidenceTargetNode.SCOPE,
                config=config,
            )
            material = json.dumps(facts.prompt_payload(), ensure_ascii=False, indent=2)
            allowed_blocks = set(facts.retrieved_block_ids)
            scope = extract_with_retry(
                llm=llm,
                prompt_template=_SCOPE_SYNTHESIS_PROMPT,
                schema_class=ScopeStatement,
                sample_input=material,
                max_retries=2,
                semantic_validator=lambda value: _validate_scope(
                    value,
                    binding,
                    allowed_blocks,
                ),
                payload_transformer=lambda payload: canonicalize_evidence_payload(
                    payload,
                    binding,
                ),
            )
        else:
            material = render_evidence_material(binding)
            scope = extract_with_retry(
                llm=llm,
                prompt_template=_SCOPE_PROMPT_TEMPLATE,
                schema_class=ScopeStatement,
                sample_input=material,
                max_retries=2,
                semantic_validator=lambda value: _validate_scope(value, binding),
                payload_transformer=lambda payload: canonicalize_evidence_payload(payload, binding),
            )
    except Exception as exc:
        errors.append(f"Node [0] scope extraction failed: {exc}")
        updates.update({"status": "node_0_failed", "errors": errors})
        return updates

    updates.update(
        {
            "scope": scope,
            "status": "node_0_completed",
            "errors": errors,
        }
    )
    logger.info("Node [0] 法律/产品定界完成")
    return updates


def build_product_context(state: TaraState, config: RunnableConfig) -> dict:
    """Node [1]: build Product Context and freeze the method/acceptance criteria."""
    logger.info("进入 Node [1] 产品上下文与方法准则节点")
    errors = list(state.get("errors", []))
    updates: dict = {
        "product_context": None,
        "risk_methodology": None,
        "risk_acceptance_criteria": None,
        "assets": [],
        "asset_assessment": None,
        "asset_notes": None,
        "asset_review_approved": False,
        "asset_review_notes": None,
        "threat_assessment": None,
        "errors": errors,
        "current_step": "node_1_product_context",
    }

    scope = state.get("scope")
    packet_ref = state.get("evidence_packet_ref")
    if scope is None or packet_ref is None:
        errors.append("Node [1] requires validated Node [0] scope and evidence_packet_ref.")
        updates.update({"status": "node_1_blocked", "errors": errors})
        return updates

    try:
        binding = _load_runtime_evidence(config)
        if binding.reference != packet_ref:
            raise ValueError("Runtime evidence packet does not match the Node [0] packet identity")
        llm = get_llm()
        if _uses_field_retrieval(config):
            facts = extract_node_facts(
                llm=llm,
                scope=binding,
                node_id=EvidenceTargetNode.CONTEXT,
                config=config,
            )
            allowed_blocks = set(facts.fact_block_ids())
            allowed_blocks.update(
                evidence.source.block_id
                for evidence in iter_evidence_refs(scope)
                if evidence.source.block_id is not None
            )
            overview = _extract_context_section(
                llm=llm,
                section_name="overview",
                schema_class=ProductContextOverview,
                scope=scope,
                facts=facts,
                binding=binding,
                config=config,
            )
            functions = _extract_context_section(
                llm=llm,
                section_name="functions",
                schema_class=ProductFunctionCatalog,
                scope=scope,
                facts=facts,
                binding=binding,
                config=config,
            )
            components = _extract_context_section(
                llm=llm,
                section_name="components",
                schema_class=ComponentInventory,
                scope=scope,
                facts=facts,
                binding=binding,
                config=config,
            )
            communications = _extract_context_section(
                llm=llm,
                section_name="communications",
                schema_class=CommunicationMatrix,
                scope=scope,
                facts=facts,
                binding=binding,
                config=config,
            )
            product_context = _validate_product_context(
                _assemble_product_context(
                    overview,
                    functions,
                    components,
                    communications,
                ),
                scope,
                binding,
                allowed_blocks,
                facts,
            )
        else:
            material = json.dumps(
                {
                    "scope": _scope_downstream_payload(scope),
                    "customer_evidence": render_evidence_material(binding),
                },
                ensure_ascii=False,
                indent=2,
            )
            product_context = extract_with_retry(
                llm=llm,
                prompt_template=_CONTEXT_PROMPT_TEMPLATE,
                schema_class=ProductContext,
                sample_input=material,
                semantic_validator=lambda value: _validate_product_context(
                    value,
                    scope,
                    binding,
                ),
                payload_transformer=lambda payload: canonicalize_evidence_payload(payload, binding),
            )

        methodology = build_risk_methodology()
        criteria = build_risk_acceptance_criteria(scope, product_context)
    except Exception as exc:
        errors.append(f"Node [1] context/method extraction failed: {exc}")
        updates.update({"status": "node_1_failed", "errors": errors})
        return updates

    updates.update(
        {
            "product_context": product_context,
            "risk_methodology": methodology,
            "risk_acceptance_criteria": criteria,
            "status": "node_1_completed",
            "errors": errors,
        }
    )
    logger.info("Node [1] 产品上下文与方法准则完成")
    return updates


def route_after_scope(state: TaraState) -> str:
    """Continue only after Node [0] produced scope and a bound evidence identity."""
    complete = (
        state.get("status") == "node_0_completed"
        and state.get("scope") is not None
        and state.get("evidence_packet_ref") is not None
    )
    return "build_product_context" if complete else "end"


def route_after_context(state: TaraState) -> str:
    """Continue only after every mandatory Node [1] output exists."""
    complete = (
        state.get("status") == "node_1_completed"
        and state.get("scope") is not None
        and state.get("product_context") is not None
        and state.get("risk_methodology") is not None
        and state.get("risk_acceptance_criteria") is not None
    )
    return "identify_assets" if complete else "end"


__all__ = [
    "CONTEXT_RULE_VERSION",
    "build_product_context",
    "define_scope",
    "route_after_context",
    "route_after_scope",
]
