"""Step [2] asset identification and step [3] STRIDE threat modelling nodes."""

import json
import re
import unicodedata
from hashlib import sha256
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import ValidationError

from core.llm import get_llm
from core.logger import setup_logger
from core.state import TaraState
from core.structured_extraction import extract_with_retry
from core.workflow_status import (
    ASSET_IDENTIFICATION_BLOCKED,
    ASSET_IDENTIFICATION_COMPLETED,
    ASSET_IDENTIFICATION_FAILED,
    is_asset_reviewable_state,
    resolve_asset_identification_status,
)
from nodes.field_extractor import extract_node_facts, load_runtime_scope
from prompts import load_prompt
from schemas.common import AssessmentVerdict
from schemas.evidence_packet import EvidenceTargetNode
from schemas.product import (
    Asset,
    AssetFunctionRelationship,
    AssetFunctionMappingResult,
    AssetIdentificationResult,
    AssetSectionResult,
    CybersecurityObjective,
)
from schemas.retrieval import RetrievalField
from schemas.threat import ThreatAssessment, ThreatIdentificationResult
from tools.evidence_input import (
    canonicalize_evidence_from_upstream,
    canonicalize_evidence_payload,
    iter_evidence_refs,
    validate_evidence_bindings,
    validate_evidence_block_subset,
    validate_evidence_subset,
)


logger = setup_logger("asset_threat_modeler")


ASSET_RULE_VERSION = "node2_asset_rules.v2.7"


_ASSET_PROMPT_TEMPLATE = load_prompt("node2_assets.md", "asset_direct")


_ASSET_SECTION_FIELDS: dict[str, frozenset[RetrievalField]] = {
    "data_credentials_software": frozenset(
        {
            RetrievalField.DATA_ASSETS,
            RetrievalField.CREDENTIALS_AND_KEYS,
            RetrievalField.SOFTWARE_AND_CONFIGURATION,
        }
    ),
    "systems_services": frozenset(
        {
            RetrievalField.HARDWARE_AND_NETWORK,
            RetrievalField.EXTERNAL_SERVICES,
        }
    ),
    "functions_impacts": frozenset(
        {
            RetrievalField.FUNCTION_ASSETS,
            RetrievalField.USER_PROPERTY_ENVIRONMENT,
        }
    ),
}

_ASSET_SECTION_ALLOWED_TYPES = {
    "data_credentials_software": frozenset({"data", "credential", "software", "other"}),
    "systems_services": frozenset({"hardware", "network", "service", "other"}),
    "functions_impacts": frozenset(
        {"function", "user", "property", "environment", "public_interest", "other"}
    ),
}

_VALID_ASSET_TYPES = frozenset(
    {
        "data",
        "credential",
        "software",
        "hardware",
        "network",
        "service",
        "function",
        "user",
        "property",
        "environment",
        "public_interest",
        "other",
    }
)
_VALID_ASSET_STATUSES = frozenset(
    {"confirmed", "conditional", "external_affected", "needs_confirmation"}
)
_VALID_OBJECTIVE_CATEGORIES = frozenset(
    {
        "confidentiality",
        "integrity",
        "availability",
        "authenticity",
        "accountability",
        "data_minimization",
    }
)
_VALID_OBJECTIVE_BASES = frozenset(
    {
        "explicit_requirement",
        "asset_value_or_consequence",
        "legal_or_standard",
        "analyst_minimum",
        "unknown",
    }
)
_VALID_OBJECTIVE_STATUSES = frozenset({"supported", "needs_confirmation"})
_VALID_FUNCTION_RELATIONSHIP_TYPES = frozenset(
    {
        "reads",
        "creates",
        "modifies",
        "transmits",
        "authenticates_with",
        "implements",
        "protects",
        "depends_on",
        "affects",
    }
)
_ASSET_SECTION_INSTRUCTIONS = {
    section_name: load_prompt("node2_assets.md", f"section_{section_name}")
    for section_name in (
        "data_credentials_software",
        "systems_services",
        "functions_impacts",
    )
}
_ASSET_SECTION_COMMON_RULES = load_prompt("node2_assets.md", "section_common")


_ASSET_FUNCTION_MAPPING_PROMPT = load_prompt(
    "node2_assets.md", "asset_function_mapping"
)


def _asset_section_prompt(section_name: str) -> str:
    template = load_prompt("node2_assets.md", "asset_section_template")
    return (
        template.replace("[[SECTION_NAME]]", section_name)
        .replace("[[COMMON_RULES]]", _ASSET_SECTION_COMMON_RULES)
        .replace("[[SECTION_BODY]]", _ASSET_SECTION_INSTRUCTIONS[section_name])
    )


def _normalized_enum_token(value: Any) -> str:
    """Normalize a model-produced enum token without guessing domain meaning."""
    return re.sub(r"[\s\-/]+", "_", str(value or "").strip().casefold())


def _normalize_asset_section_payload(
    payload: dict[str, Any],
    *,
    section_name: str,
) -> dict[str, Any]:
    """Validate one model item at a time so a bad item cannot discard its peers.

    Only spelling-level enum normalization is allowed here. Domain aliases are
    deliberately not guessed: an ambiguous item is rejected with a concise
    diagnostic and the remaining valid section content stays reviewable.
    """
    if not isinstance(payload, dict) or section_name not in _ASSET_SECTION_ALLOWED_TYPES:
        return payload
    raw_assets = payload.get("assets")
    rejections: list[str] = []
    if not isinstance(raw_assets, list):
        raw_assets = []
        rejections.append("section/assets: 必须为数组")

    def rejection_label(item: Any, index: int) -> str:
        if isinstance(item, dict) and str(item.get("asset_id") or "").strip():
            return str(item["asset_id"]).strip()
        return f"asset[{index}]"

    def validation_reason(exc: ValidationError) -> str:
        error = exc.errors(include_url=False, include_input=False)[0]
        location = ".".join(str(part) for part in error.get("loc", ())) or "item"
        return f"{location}: {error.get('msg', '校验失败')}"

    allowed_types = _ASSET_SECTION_ALLOWED_TYPES[section_name]
    normalized_assets: list[dict[str, Any]] = []
    seen_asset_ids: set[str] = set()
    seen_objective_ids: set[str] = set()

    for index, raw_asset in enumerate(raw_assets):
        label = rejection_label(raw_asset, index)
        if not isinstance(raw_asset, dict):
            rejections.append(f"{label}/asset: 必须为对象")
            continue
        asset = dict(raw_asset)
        asset_type = _normalized_enum_token(asset.get("asset_type"))
        status = _normalized_enum_token(asset.get("status"))
        if asset_type not in _VALID_ASSET_TYPES or asset_type not in allowed_types:
            rejections.append(f"{label}/asset: asset_type不属于本分段允许枚举")
            continue
        if status not in _VALID_ASSET_STATUSES:
            rejections.append(f"{label}/asset: status不是支持的枚举")
            continue
        asset["asset_type"] = asset_type
        asset["status"] = status

        valid_objectives: list[dict[str, Any]] = []
        raw_objectives = asset.get("related_objectives", [])
        if not isinstance(raw_objectives, list):
            rejections.append(f"{label}/related_objectives: 必须为数组")
            raw_objectives = []
        local_objective_ids: set[str] = set()
        for child_index, raw_objective in enumerate(raw_objectives):
            child_label = f"{label}/objective[{child_index}]"
            if not isinstance(raw_objective, dict):
                rejections.append(f"{child_label}: 必须为对象")
                continue
            objective = dict(raw_objective)
            for field, allowed in (
                ("category", _VALID_OBJECTIVE_CATEGORIES),
                ("basis", _VALID_OBJECTIVE_BASES),
                ("status", _VALID_OBJECTIVE_STATUSES),
            ):
                if field in objective:
                    token = _normalized_enum_token(objective[field])
                    if token in allowed:
                        objective[field] = token
            try:
                validated_objective = CybersecurityObjective.model_validate(objective)
            except ValidationError as exc:
                rejections.append(f"{child_label}: {validation_reason(exc)}")
                continue
            objective_id = validated_objective.objective_id
            if objective_id in local_objective_ids or objective_id in seen_objective_ids:
                rejections.append(f"{child_label}: objective_id重复")
                continue
            local_objective_ids.add(objective_id)
            valid_objectives.append(validated_objective.model_dump(mode="python"))
        asset["related_objectives"] = valid_objectives

        valid_relationships: list[dict[str, Any]] = []
        raw_relationships = asset.get("function_relationships", [])
        if not isinstance(raw_relationships, list):
            rejections.append(f"{label}/function_relationships: 必须为数组")
            raw_relationships = []
        for child_index, raw_relationship in enumerate(raw_relationships):
            child_label = f"{label}/relationship[{child_index}]"
            if not isinstance(raw_relationship, dict):
                rejections.append(f"{child_label}: 必须为对象")
                continue
            relationship = dict(raw_relationship)
            relationship_type = _normalized_enum_token(
                relationship.get("relationship_type")
            )
            if relationship_type in _VALID_FUNCTION_RELATIONSHIP_TYPES:
                relationship["relationship_type"] = relationship_type
            try:
                validated_relationship = AssetFunctionRelationship.model_validate(
                    relationship
                )
            except ValidationError as exc:
                rejections.append(f"{child_label}: {validation_reason(exc)}")
                continue
            valid_relationships.append(
                validated_relationship.model_dump(mode="python")
            )
        asset["function_relationships"] = valid_relationships

        try:
            validated_asset = Asset.model_validate(asset)
        except ValidationError as exc:
            rejections.append(f"{label}/asset: {validation_reason(exc)}")
            continue
        if validated_asset.asset_id in seen_asset_ids:
            rejections.append(f"{label}/asset: asset_id重复")
            continue
        seen_asset_ids.add(validated_asset.asset_id)
        seen_objective_ids.update(local_objective_ids)
        normalized_assets.append(validated_asset.model_dump(mode="python"))

    assessment = str(payload.get("assessment") or "PARTIAL").strip().upper()
    if assessment not in {item.value for item in AssessmentVerdict}:
        assessment = AssessmentVerdict.PARTIAL.value
        rejections.append("section/assessment: 不是支持的枚举")
    existing_notes = str(payload.get("notes") or "").strip()
    if rejections:
        assessment = AssessmentVerdict.PARTIAL.value
        isolation_note = f"逐项校验隔离了{len(rejections)}条无效记录；有效资产继续保留。"
        existing_notes = " ".join(part for part in (existing_notes, isolation_note) if part)
    elif not normalized_assets and not existing_notes:
        existing_notes = "本分段未识别到可验证资产。"

    return {
        "assets": normalized_assets,
        "assessment": assessment,
        "notes": existing_notes or None,
        # Ignore any model-provided diagnostics; only this validator may create them.
        "rejected_items": rejections[:50],
    }


def _prepare_asset_section_payload(
    payload: dict[str, Any],
    *,
    section_name: str,
    binding: Any,
    allowed_block_ids: set[str],
) -> dict[str, Any]:
    """Canonicalize evidence and apply bounded schema-tolerance before validation."""
    canonical = canonicalize_evidence_payload(
        payload,
        binding,
        allowed_block_ids=allowed_block_ids,
    )
    return _normalize_asset_section_payload(canonical, section_name=section_name)


_THREAT_PROMPT_TEMPLATE = load_prompt("node3_threats.md", "threat_direct")


def _validate_asset_semantics(
    result: AssetIdentificationResult | AssetSectionResult,
) -> AssetIdentificationResult | AssetSectionResult:
    """Validate fields whose meaning cannot be expressed by the JSON Schema alone."""
    for asset in result.assets:
        if not asset.name.strip() or not asset.asset_type.strip() or not asset.description.strip():
            raise ValueError(f"Asset {asset.asset_id} must have non-empty name, asset_type, and description.")
        for objective in asset.related_objectives:
            if not objective.description.strip() or not objective.category.strip():
                raise ValueError(
                    f"Objective {objective.objective_id} must have non-empty description and category."
                )
    return result


def _validate_asset_evidence_subset(
    result: AssetIdentificationResult,
    *upstream_values: Any,
) -> AssetIdentificationResult:
    """Reject Node [2] citations that were not validated in Node [0]/[1]."""
    return validate_evidence_subset(result, *upstream_values)


def _stable_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _llm_model_name(llm: Any) -> str:
    return str(getattr(llm, "model_name", None) or getattr(llm, "model", "unknown"))


def _compact_scope_for_assets(scope: Any) -> dict[str, Any]:
    """Keep only boundary facts useful for candidate selection."""
    return {
        "product_name": scope.product_name,
        "product_version": scope.product_version,
        "scope_description": scope.scope_description,
        "in_scope_components": scope.in_scope_components,
        "conditional_scope_components": scope.conditional_scope_components,
        "out_of_scope_components": scope.out_of_scope_components,
        "open_questions": scope.assumptions,
        "has_rdps": scope.classification.has_rdps,
    }


def _compact_function(function: Any) -> dict[str, Any]:
    return {
        "function_id": function.function_id,
        "name": function.name,
        "description": function.description,
        "is_security_function": function.is_security_function,
        "function_category": function.function_category,
        "interfaces": function.interfaces,
        "rdps_dependencies": getattr(function, "rdps_dependencies", []),
        "limitations": function.limitations,
    }


def _compact_component(component: Any) -> dict[str, Any]:
    return {
        "component_id": component.component_id,
        "name": component.name,
        "component_type": component.component_type,
        "scope_status": component.scope_status,
        "conditions": component.conditions,
        "version": component.version,
        "role": component.role,
        "interfaces": component.interfaces,
    }


def _compact_flow(flow: Any) -> dict[str, Any]:
    return {
        "flow_id": flow.flow_id,
        "source": flow.source,
        "destination": flow.destination,
        "direction": flow.direction,
        "direction_basis": getattr(flow, "direction_basis", "unknown"),
        "business_data_direction": getattr(
            flow, "business_data_direction", "unknown"
        ),
        "activation_status": getattr(flow, "activation_status", "unknown"),
        "conditions": getattr(flow, "conditions", []),
        "interface": flow.interface,
        "protocol": flow.protocol,
        "port": flow.port,
        "data_exchanged": getattr(flow, "data_exchanged", []),
        "authentication": flow.authentication,
        "encryption": flow.encryption,
        "security_notes": flow.security_notes,
    }


def _asset_candidate_context(section_name: str, product_context: Any) -> dict[str, Any]:
    """Render a compact, explicitly non-evidentiary Node [1] candidate list."""
    functions = [_compact_function(item) for item in product_context.functions]
    flows = [_compact_flow(item) for item in product_context.communication_matrix.entries]
    environment = product_context.operational_environment
    if section_name == "data_credentials_software":
        return {
            "product_name": product_context.product_name,
            "functions": functions,
            "communication_endpoints": flows,
            "existing_security_function_names": product_context.existing_security_functions,
        }
    if section_name == "systems_services":
        return {
            "product_name": product_context.product_name,
            "functions": functions,
            "components": [
                _compact_component(item)
                for item in product_context.component_inventory.entries
            ],
            "communication_endpoints": flows,
            "networks": environment.networks,
            "integrated_systems": environment.integrated_systems,
            "network_boundaries": environment.network_boundaries,
            "constraints": environment.constraints,
        }
    return {
        "product_name": product_context.product_name,
        "intended_use": product_context.iprfu.model_dump(
            mode="json",
            exclude={"evidence"},
        ),
        "users": product_context.user_description.model_dump(
            mode="json",
            exclude={"evidence"},
        ),
        "functions": functions,
        "integrated_systems": environment.integrated_systems,
        "constraints": environment.constraints,
    }


def _asset_section_material(
    *,
    section_name: str,
    scope: Any,
    product_context: Any,
    facts: Any,
) -> tuple[dict[str, Any], set[str]]:
    fields = _ASSET_SECTION_FIELDS[section_name]
    fact_payload = facts.prompt_payload(set(fields))
    allowed_block_ids = set(facts.fact_block_ids(fields))
    if section_name == "functions_impacts":
        function_support: dict[str, list[str]] = {}
        for function in product_context.functions:
            block_ids = list(
                dict.fromkeys(
                    evidence.source.block_id
                    for evidence in iter_evidence_refs(function)
                    if evidence.source.block_id
                )
            )
            if block_ids:
                function_support[function.function_id] = block_ids
                allowed_block_ids.update(block_ids)
        fact_payload["evidence_contract"]["node1_function_support"] = function_support
        fact_payload["evidence_contract"]["candidate_context_rule"] = (
            "candidate_context.functions是已验证的Node1功能清单，可用于功能分组和related_function_ids；"
            "function资产可引用node1_function_support中对应FUNC-xxx的证据块。"
        )
    else:
        fact_payload["evidence_contract"]["candidate_context_rule"] = (
            "candidate_context可用于related_function_ids映射，但不能单独证明本段资产存在；"
            "confirmed资产仍需field_batches.facts直接支持。"
        )
    return (
        {
            "scope": _compact_scope_for_assets(scope),
            "candidate_context": _asset_candidate_context(
                section_name,
                product_context,
            ),
            **fact_payload,
        },
        allowed_block_ids,
    )


def _asset_section_cache_inputs(
    *,
    section_name: str,
    source_packet_sha256: str,
    text_model: str,
    material_payload: dict[str, Any],
) -> dict[str, str]:
    return {
        "section_name": section_name,
        "source_packet_sha256": source_packet_sha256,
        "text_model": text_model,
        "asset_rule_version": ASSET_RULE_VERSION,
        "material_sha256": _stable_sha256(material_payload),
        "prompt_sha256": sha256(
            _asset_section_prompt(section_name).encode("utf-8")
        ).hexdigest(),
        "schema_sha256": _stable_sha256(
            AssetSectionResult.model_json_schema()
        ),
    }


def _asset_section_checkpoint_path(
    config: RunnableConfig,
    section_name: str,
) -> Path | None:
    raw_directory = config.get("configurable", {}).get(
        "asset_section_checkpoint_dir"
    )
    if not raw_directory:
        return None
    return Path(raw_directory) / f"{section_name}.json"


def _load_asset_section_checkpoint(
    *,
    path: Path | None,
    fingerprint: str,
) -> AssetSectionResult | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "asset_section_checkpoint.v1":
            return None
        if payload.get("fingerprint") != fingerprint:
            return None
        return AssetSectionResult.model_validate(payload["result"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Node [2] 分段缓存无效，将重新生成：%s (%s)", path, exc)
        return None


def _save_asset_section_checkpoint(
    *,
    path: Path | None,
    cache_inputs: dict[str, str],
    fingerprint: str,
    result: AssetSectionResult,
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "asset_section_checkpoint.v1",
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


def _asset_function_mapping_material(
    assets: list[Asset],
    product_functions: list[Any],
) -> dict[str, Any]:
    """Build a compact mapping-only payload without repeating evidence or objectives."""
    return {
        "functions": [
            {
                "function_id": function.function_id,
                "name": function.name,
                "description": getattr(function, "description", None),
                "is_security_function": getattr(function, "is_security_function", None),
                "function_category": getattr(function, "function_category", None),
                "interfaces": getattr(function, "interfaces", []),
                "rdps_dependencies": getattr(function, "rdps_dependencies", []),
                "limitations": getattr(function, "limitations", []),
            }
            for function in product_functions
        ],
        "assets": [
            {
                "asset_id": asset.asset_id,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "status": asset.status,
                "description": asset.description,
                "value": asset.value,
                "provisional_related_function_ids": asset.related_function_ids,
                "provisional_function_relationships": [
                    relationship.model_dump(mode="json")
                    for relationship in asset.function_relationships
                ],
            }
            for asset in assets
        ],
    }


def _asset_function_mapping_cache_inputs(
    *,
    source_packet_sha256: str,
    text_model: str,
    material_payload: dict[str, Any],
) -> dict[str, str]:
    return {
        "source_packet_sha256": source_packet_sha256,
        "text_model": text_model,
        "asset_rule_version": ASSET_RULE_VERSION,
        "material_sha256": _stable_sha256(material_payload),
        "prompt_sha256": sha256(
            _ASSET_FUNCTION_MAPPING_PROMPT.encode("utf-8")
        ).hexdigest(),
        "schema_sha256": _stable_sha256(
            AssetFunctionMappingResult.model_json_schema()
        ),
    }


def _load_asset_function_mapping_checkpoint(
    *,
    path: Path | None,
    fingerprint: str,
) -> AssetFunctionMappingResult | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "asset_function_mapping_checkpoint.v1":
            return None
        if payload.get("fingerprint") != fingerprint:
            return None
        return AssetFunctionMappingResult.model_validate(payload["result"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        logger.warning("Node [2] 功能映射缓存无效，将重新生成：%s (%s)", path, exc)
        return None


def _save_asset_function_mapping_checkpoint(
    *,
    path: Path | None,
    cache_inputs: dict[str, str],
    fingerprint: str,
    result: AssetFunctionMappingResult,
) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "asset_function_mapping_checkpoint.v1",
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


def _extract_asset_function_mapping(
    *,
    llm: Any,
    assets: list[Asset],
    product_functions: list[Any],
    binding: Any,
    config: RunnableConfig,
) -> AssetFunctionMappingResult:
    """Generate one focused mapping after the independently produced sections are merged."""
    material_payload = _asset_function_mapping_material(assets, product_functions)
    cache_inputs = _asset_function_mapping_cache_inputs(
        source_packet_sha256=binding.reference.packet_sha256,
        text_model=_llm_model_name(llm),
        material_payload=material_payload,
    )
    fingerprint = _stable_sha256(cache_inputs)
    checkpoint_path = _asset_section_checkpoint_path(config, "function_mapping")
    cache_policy = config.get("configurable", {}).get(
        "asset_section_cache_policy", "reuse"
    )
    if cache_policy not in {"reuse", "refresh"}:
        raise ValueError(
            "configurable.asset_section_cache_policy must be 'reuse' or 'refresh'"
        )

    if cache_policy == "reuse":
        cached = _load_asset_function_mapping_checkpoint(
            path=checkpoint_path,
            fingerprint=fingerprint,
        )
        if cached is not None:
            logger.info("Node [2] 复用资产功能映射缓存")
            return cached

    logger.info("Node [2] 生成资产与功能统一映射")
    result = extract_with_retry(
        llm=llm,
        prompt_template=_ASSET_FUNCTION_MAPPING_PROMPT,
        schema_class=AssetFunctionMappingResult,
        sample_input=json.dumps(material_payload, ensure_ascii=False, indent=2),
        max_retries=2,
    )
    _save_asset_function_mapping_checkpoint(
        path=checkpoint_path,
        cache_inputs=cache_inputs,
        fingerprint=fingerprint,
        result=result,
    )
    return result


def _validate_asset_section(
    result: AssetSectionResult,
    *,
    section_name: str,
    binding: Any,
    allowed_block_ids: set[str],
) -> AssetSectionResult:
    result = _validate_asset_semantics(result)
    invalid_types = sorted(
        {
            asset.asset_type
            for asset in result.assets
            if asset.asset_type not in _ASSET_SECTION_ALLOWED_TYPES[section_name]
        }
    )
    if invalid_types:
        raise ValueError(
            f"Asset section {section_name} returned out-of-section types: {invalid_types}"
        )
    validate_evidence_bindings(result, binding)
    return validate_evidence_block_subset(result, allowed_block_ids)


def _extract_asset_section(
    *,
    llm: Any,
    section_name: str,
    scope: Any,
    product_context: Any,
    facts: Any,
    binding: Any,
    config: RunnableConfig,
) -> AssetSectionResult:
    material_payload, allowed_block_ids = _asset_section_material(
        section_name=section_name,
        scope=scope,
        product_context=product_context,
        facts=facts,
    )
    cache_inputs = _asset_section_cache_inputs(
        section_name=section_name,
        source_packet_sha256=binding.reference.packet_sha256,
        text_model=_llm_model_name(llm),
        material_payload=material_payload,
    )
    fingerprint = _stable_sha256(cache_inputs)
    checkpoint_path = _asset_section_checkpoint_path(config, section_name)
    cache_policy = config.get("configurable", {}).get(
        "asset_section_cache_policy", "reuse"
    )
    if cache_policy not in {"reuse", "refresh"}:
        raise ValueError(
            "configurable.asset_section_cache_policy must be 'reuse' or 'refresh'"
        )

    if cache_policy == "reuse":
        cached = _load_asset_section_checkpoint(
            path=checkpoint_path,
            fingerprint=fingerprint,
        )
        if cached is not None:
            try:
                cached = _validate_asset_section(
                    cached,
                    section_name=section_name,
                    binding=binding,
                    allowed_block_ids=allowed_block_ids,
                )
                logger.info("Node [2] 复用分段缓存：%s", section_name)
                return cached
            except ValueError as exc:
                logger.warning(
                    "Node [2] 分段缓存证据校验失败，将重新生成：%s (%s)",
                    section_name,
                    exc,
                )

    logger.info("Node [2] 生成分段：%s", section_name)
    result = extract_with_retry(
        llm=llm,
        prompt_template=_asset_section_prompt(section_name),
        schema_class=AssetSectionResult,
        sample_input=json.dumps(material_payload, ensure_ascii=False, indent=2),
        semantic_validator=lambda value: _validate_asset_section(
            value,
            section_name=section_name,
            binding=binding,
            allowed_block_ids=allowed_block_ids,
        ),
        payload_transformer=lambda payload: _prepare_asset_section_payload(
            payload,
            section_name=section_name,
            binding=binding,
            allowed_block_ids=allowed_block_ids,
        ),
        max_retries=2,
    )
    _save_asset_section_checkpoint(
        path=checkpoint_path,
        cache_inputs=cache_inputs,
        fingerprint=fingerprint,
        result=result,
    )
    return result


def _normalized_asset_name(value: str) -> str:
    """Normalize presentation-only variation without removing semantic qualifiers."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"[\s\-_/·•:：,，.。()（）\[\]【】]+", "", normalized)
    if len(normalized) > 4 and normalized.endswith("资产"):
        normalized = normalized[:-2]
    return normalized


def _normalized_comparison_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(
        r"\s+",
        "",
        unicodedata.normalize("NFKC", value).casefold(),
    )


def _asset_evidence_keys(asset: Asset) -> set[str]:
    keys: set[str] = set()
    for evidence in asset.evidence:
        source = evidence.source
        block_id = getattr(source, "block_id", None)
        if block_id:
            keys.add(f"block:{block_id}")
            continue
        source_path = getattr(source, "file_path", None) or getattr(
            source, "file_name", ""
        )
        quote = (evidence.quote or "").strip()
        if source_path and quote:
            keys.add(f"quote:{source_path}:{quote}")
    return keys


def _assets_are_conservative_merge_candidates(left: Asset, right: Asset) -> bool:
    """Merge only same-boundary duplicates with compatible facts and shared evidence."""
    if left.asset_type != right.asset_type or left.status != right.status:
        return False
    if _normalized_asset_name(left.name) != _normalized_asset_name(right.name):
        return False
    if not (_asset_evidence_keys(left) & _asset_evidence_keys(right)):
        return False
    for left_value, right_value in (
        (left.location, right.location),
        (left.value, right.value),
    ):
        if (
            left_value
            and right_value
            and _normalized_comparison_text(left_value)
            != _normalized_comparison_text(right_value)
        ):
            return False
    left_description = _normalized_comparison_text(left.description)
    right_description = _normalized_comparison_text(right.description)
    if not (
        left_description == right_description
        or left_description in right_description
        or right_description in left_description
    ):
        return False
    return True


def _merge_asset_duplicates(
    left: Asset,
    right: Asset,
    *,
    function_order: dict[str, int],
) -> Asset:
    """Combine a proven duplicate while preferring the less expansive statement."""
    relationship_by_key: dict[tuple[str, str], AssetFunctionRelationship] = {}
    for item in [*left.function_relationships, *right.function_relationships]:
        key = (item.function_id, item.relationship_type)
        existing = relationship_by_key.get(key)
        if existing is None or len(_normalized_comparison_text(item.rationale)) < len(
            _normalized_comparison_text(existing.rationale)
        ):
            relationship_by_key[key] = item
    function_ids = sorted(
        set(left.related_function_ids)
        | set(right.related_function_ids)
        | {item.function_id for item in relationship_by_key.values()},
        key=function_order.__getitem__,
    )
    objective_by_key = {
        (item.category, _normalized_comparison_text(item.description)): item
        for item in [*left.related_objectives, *right.related_objectives]
    }
    evidence_by_key = {
        _stable_sha256(item.model_dump(mode="json")): item
        for item in [*left.evidence, *right.evidence]
    }
    description = min(
        (left.description, right.description),
        key=lambda value: len(_normalized_comparison_text(value)),
    )
    return left.model_copy(
        update={
            "description": description,
            "location": left.location or right.location,
            "value": left.value or right.value,
            "related_function_ids": function_ids,
            "function_relationships": list(relationship_by_key.values()),
            "related_objectives": list(objective_by_key.values()),
            "evidence": list(evidence_by_key.values()),
        }
    )


_OBJECTIVE_RESULT_TEMPLATES = {
    "confidentiality": "确保{asset_name}仅可被获授权主体访问或使用。",
    "integrity": "确保{asset_name}不被未经授权地修改。",
    "availability": "确保{asset_name}在预期运行期间保持可用。",
    "authenticity": "确保{asset_name}的来源或身份可被验证。",
    "accountability": "确保与{asset_name}相关的关键操作可追溯到责任主体。",
    "data_minimization": "确保仅处理实现预期用途所必需的{asset_name}。",
}

_FALLBACK_OBJECTIVE_CATEGORY = {
    "credential": "confidentiality",
    "data": "integrity",
    "software": "integrity",
    "other": "integrity",
    "hardware": "availability",
    "network": "availability",
    "service": "availability",
    "function": "availability",
    "user": "availability",
    "property": "availability",
    "environment": "availability",
    "public_interest": "availability",
}

_SECRET_MARKERS = (
    "私钥",
    "密钥",
    "密码",
    "口令",
    "重置秘密",
    "secret",
    "token",
    "令牌",
)

_PUBLIC_AUTHENTICATION_MATERIAL_MARKERS = (
    "公开证书",
    "公钥证书",
    "公钥",
    "publiccertificate",
    "publickey",
)

_INFERRED_LOCATION_MARKERS = (
    "存储介质",
    "可信执行环境",
    "本地认证数据库",
    "本地数据库",
    "持久化存储",
)
_EXTERNAL_AFFECTED_TYPES = {"user", "property", "environment", "public_interest"}
_UNSUPPORTED_VALUE_DETAIL_MARKERS = (
    "攻击者",
    "漏洞利用",
    "横向移动",
    "中间人",
    "凭证填充",
    "供应链攻击",
    "vlan跳跃",
    "火灾",
    "电压崩溃",
)
_PASSIVE_SUPPORT_BEHAVIOR_MARKERS = (
    "无可配置数字逻辑",
    "无独立数字功能",
    "被动支撑部件",
    "仅用于物理连接",
    "仅提供物理连接",
    "物理保护",
    "线路接续",
    "线缆固定",
    "仅用于供电",
    "仅用于电气保护",
    "passivecomponent",
)
_DIGITAL_CAPABILITY_MARKERS = (
    "可配置",
    "管理功能",
    "固件",
    "软件",
    "处理数据",
    "存储数据",
    "路由",
    "交换功能",
    "网关",
    "控制器",
    "认证",
    "远程管理",
    "数据采集",
)
def _is_passive_support_asset(asset: Asset) -> bool:
    """Identify clearly passive support parts that have no independent digital behavior."""
    if asset.asset_type not in {"hardware", "network", "other"}:
        return False
    evidence_text = " ".join(
        evidence.quote or "" for evidence in asset.evidence
    ).casefold()
    combined = f"{asset.name} {asset.description} {evidence_text}".casefold()
    return (
        any(marker in evidence_text for marker in _PASSIVE_SUPPORT_BEHAVIOR_MARKERS)
        and not any(marker in combined for marker in _DIGITAL_CAPABILITY_MARKERS)
    )


def _iter_scope_named_statuses(scope: Any, product_context: Any):
    inventory = getattr(product_context, "component_inventory", None)
    for component in getattr(inventory, "entries", []) or []:
        yield component.name, component.scope_status
    for field_name, status in (
        ("in_scope_components", "confirmed"),
        ("conditional_scope_components", "conditional"),
        ("out_of_scope_components", "external"),
    ):
        for item in getattr(scope, field_name, []) or []:
            if isinstance(item, str):
                yield item, status


def _align_asset_scope_status(
    asset: Asset,
    *,
    scope: Any | None,
    product_context: Any | None,
) -> tuple[Asset, tuple[str, ...]]:
    """Prevent an exact upstream component candidate from becoming more certain in Node [2]."""
    if (
        scope is None
        or product_context is None
        or asset.asset_type not in {"hardware", "software", "network", "service", "other"}
    ):
        return asset, ()
    asset_name = _normalized_asset_name(asset.name)
    statuses = {
        status
        for name, status in _iter_scope_named_statuses(scope, product_context)
        if _normalized_asset_name(name) == asset_name
    }
    if not statuses or statuses == {"confirmed"}:
        return asset, ()
    if len(statuses) > 1 or "unknown" in statuses:
        target = "needs_confirmation"
        action = "上游范围状态冲突或未知的资产已降为待工程师确认"
    elif "external" in statuses:
        target = "external_affected"
        action = "上游范围外对象已保持为外部受影响状态"
    else:
        target = "conditional"
        action = "上游条件组件的资产状态已保持为条件项"
    if asset.status in {"needs_confirmation", "external_affected"} and target == "conditional":
        return asset, ()
    if asset.status == target:
        return asset, ()
    return asset.model_copy(update={"status": target}), (action,)


def _has_overbroad_function_mapping(asset: Asset, function_count: int) -> bool:
    """Flag non-function mappings that cover too much of a sizable catalog to be direct."""
    link_count = len(asset.related_function_ids)
    return (
        asset.asset_type != "function"
        and function_count > 0
        and link_count >= 9
        and link_count * 2 >= function_count
    )


def _objective_result_description(asset_name: str, category: str) -> str:
    """Return a neutral protection result without asserting an implementation control."""
    return _OBJECTIVE_RESULT_TEMPLATES[category].format(asset_name=asset_name)


def _evidence_reference_key(evidence: Any) -> str:
    block_id = getattr(evidence.source, "block_id", None)
    if block_id:
        return f"block:{block_id}"
    source_path = getattr(evidence.source, "file_path", None) or getattr(
        evidence.source, "file_name", ""
    )
    return f"quote:{source_path}:{(evidence.quote or '').strip()}"


def _normalized_legal_token(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(
        r"[^0-9a-z\u4e00-\u9fff]+",
        "",
        unicodedata.normalize("NFKC", value).casefold(),
    )


def _supported_legal_bases(
    objective: CybersecurityObjective,
    evidence: list[Any],
) -> list[Any]:
    """Keep only legal references whose instrument and locator occur in cited text."""
    source_text = _normalized_legal_token(
        " ".join(item.quote or "" for item in evidence)
    )
    supported = []
    for legal_basis in objective.legal_basis:
        regulation = _normalized_legal_token(legal_basis.regulation)
        locators = [
            _normalized_legal_token(value)
            for value in (
                legal_basis.article,
                legal_basis.clause,
                legal_basis.annex,
                legal_basis.sub_clause,
            )
            if value
        ]
        if regulation and regulation in source_text and any(
            locator and locator in source_text for locator in locators
        ):
            supported.append(legal_basis)
    return supported


def _repair_objective_for_asset(
    objective: CybersecurityObjective,
    asset: Asset,
    *,
    asset_evidence: tuple[Any, ...],
    public_authentication_material: bool,
) -> tuple[CybersecurityObjective, tuple[str, ...]]:
    """Turn one objective into a traceable protection result, never a control claim."""
    actions: list[str] = []
    asset_evidence_keys = {
        _evidence_reference_key(item) for item in asset_evidence
    }
    objective_evidence = [
        item
        for item in objective.evidence
        if _evidence_reference_key(item) in asset_evidence_keys
    ]
    if len(objective_evidence) != len(objective.evidence):
        actions.append("未同时支持父资产的目标证据已移除")

    category = objective.category
    if public_authentication_material and category == "confidentiality":
        category = "authenticity"
        actions.append("公开认证材料的保密目标已改为真实性目标")

    canonical_description = _objective_result_description(asset.name, category)
    if _normalized_comparison_text(objective.description) != _normalized_comparison_text(
        canonical_description
    ):
        actions.append("目标描述已规范为不声明控制实现的保护结果")

    legal_basis = _supported_legal_bases(objective, objective_evidence)
    if len(legal_basis) != len(objective.legal_basis):
        actions.append("缺少可追溯条款证据的法律或标准依据已移除")
    if objective.basis != "legal_or_standard" and legal_basis:
        legal_basis = []
        actions.append("与目标依据类型不一致的法律或标准依据已移除")

    basis = objective.basis
    basis_supported = False
    if basis == "explicit_requirement":
        basis_supported = bool(objective_evidence)
    elif basis == "asset_value_or_consequence":
        basis_supported = bool(asset.value and objective_evidence)
    elif basis == "legal_or_standard":
        basis_supported = bool(legal_basis and objective_evidence)
    elif basis == "analyst_minimum":
        basis_supported = False
    else:
        basis = "unknown"

    if not asset_evidence or asset.status == "needs_confirmation":
        basis_supported = False
        if basis != "analyst_minimum":
            basis = "unknown"
    elif not basis_supported and basis not in {"analyst_minimum", "unknown"}:
        basis = "unknown"
        actions.append("缺少直接支持的目标依据已改为未知")

    status = "supported" if basis_supported else "needs_confirmation"
    if objective.status != status:
        actions.append("目标支持状态已按证据充分性纠正")
    if status == "needs_confirmation":
        actions.append("网络安全目标依据待工程师确认")

    return (
        objective.model_copy(
            update={
                "category": category,
                "description": canonical_description,
                "basis": basis,
                "status": status,
                "legal_basis": legal_basis,
                "evidence": objective_evidence,
            }
        ),
        tuple(dict.fromkeys(actions)),
    )


def _fallback_objective_for_asset(
    asset: Asset,
    *,
    objective_id: str,
) -> CybersecurityObjective:
    """Keep an extracted asset reviewable when the model omitted its objectives."""
    category = _FALLBACK_OBJECTIVE_CATEGORY.get(asset.asset_type, "integrity")
    asset_text = f"{asset.name} {asset.description}".casefold()
    if (
        asset.asset_type == "credential"
        and any(
            marker in _normalized_comparison_text(asset_text)
            for marker in _PUBLIC_AUTHENTICATION_MATERIAL_MARKERS
        )
        and not any(marker in asset_text for marker in _SECRET_MARKERS)
    ):
        category = "authenticity"
    description = _objective_result_description(asset.name, category)
    return CybersecurityObjective(
        objective_id=objective_id,
        description=description,
        category=category,
        basis="analyst_minimum",
        status="needs_confirmation",
    )


def _repair_asset_business_rules(asset: Asset) -> tuple[Asset, tuple[str, ...]]:
    """Apply conservative, deterministic correctness rules without retrying the model."""
    actions: list[str] = []
    evidence = tuple(asset.evidence)
    has_direct_evidence = bool(evidence)
    status = asset.status
    asset_description = asset.description
    asset_value = asset.value
    support_text = " ".join(
        evidence_ref.quote or "" for evidence_ref in evidence
    ).casefold()
    asset_text = f"{asset.name} {asset.description} {support_text}".casefold()

    if not has_direct_evidence and status != "needs_confirmation":
        status = "needs_confirmation"
        actions.append("无直接证据候选已降为待工程师确认")
    if not has_direct_evidence:
        asset_description = (
            f"{asset.name}为候选资产；现有材料未提供可直接引用的存在性、边界或用途证据，需工程师确认。"
        )
        asset_value = None
        actions.append("无直接证据候选的推测内容已清空")
    elif asset.asset_type in _EXTERNAL_AFFECTED_TYPES and status == "confirmed":
        status = "external_affected"
        actions.append("产品边界外受影响对象已改为外部受影响状态")

    public_authentication_material = (
        any(
            marker in _normalized_comparison_text(asset_text)
            for marker in _PUBLIC_AUTHENTICATION_MATERIAL_MARKERS
        )
        and not any(marker in asset_text for marker in _SECRET_MARKERS)
    )
    if public_authentication_material and asset_value and "私钥" in asset_value:
        asset_value = None
        actions.append("公开认证材料中无依据的私钥价值描述已清空")
    if asset_value and has_direct_evidence:
        value_folded = asset_value.casefold()
        if any(
            marker in value_folded and marker not in support_text
            for marker in _UNSUPPORTED_VALUE_DETAIL_MARKERS
        ):
            asset_value = None
            actions.append("缺少原文支持的具体攻击或灾害链已清空")
    repaired_asset = asset.model_copy(update={"value": asset_value, "status": status})
    objectives: list[CybersecurityObjective] = []
    objective_indexes: dict[tuple[str, str], int] = {}
    for objective in asset.related_objectives:
        repaired_objective, objective_actions = _repair_objective_for_asset(
            objective,
            repaired_asset,
            asset_evidence=evidence,
            public_authentication_material=public_authentication_material,
        )
        actions.extend(objective_actions)
        identity = (
            repaired_objective.category,
            _normalized_comparison_text(repaired_objective.description),
        )
        if identity in objective_indexes:
            actions.append("纠错后重复的保护目标已合并")
            existing_index = objective_indexes[identity]
            existing = objectives[existing_index]
            preferred = (
                repaired_objective
                if repaired_objective.status == "supported"
                and existing.status != "supported"
                else existing
            )
            evidence_by_key = {
                _evidence_reference_key(item): item
                for item in [*existing.evidence, *repaired_objective.evidence]
            }
            legal_by_key = {
                _stable_sha256(item.model_dump(mode="json")): item
                for item in [*existing.legal_basis, *repaired_objective.legal_basis]
            }
            objectives[existing_index] = preferred.model_copy(
                update={
                    "objective_id": existing.objective_id,
                    "evidence": list(evidence_by_key.values()),
                    "legal_basis": list(legal_by_key.values()),
                }
            )
            continue
        objective_indexes[identity] = len(objectives)
        objectives.append(repaired_objective)

    location = asset.location
    if location and not has_direct_evidence:
        location = None
        actions.append("无直接证据候选的位置已清空")
    elif location:
        location_folded = location.casefold()
        support_text = " ".join(
            evidence_ref.quote or "" for evidence_ref in evidence
        ).casefold()
        unsupported_markers = [
            marker
            for marker in _INFERRED_LOCATION_MARKERS
            if marker in location_folded and marker not in support_text
        ]
        if unsupported_markers:
            location = None
            actions.append("缺少原文支持的推断位置已清空")

    return (
        asset.model_copy(
            update={
                "status": status,
                "location": location,
                "description": asset_description,
                "value": asset_value,
                "related_objectives": objectives,
            }
        ),
        tuple(dict.fromkeys(actions)),
    )


def _normalize_asset_function_links(
    asset: Asset,
    *,
    function_order: dict[str, int],
) -> tuple[Asset, tuple[str, ...]]:
    """Keep exact upstream function IDs and degrade missing mappings without retrying."""
    actions: list[str] = []
    normalized: list[str] = []
    unknown_count = 0
    duplicate_count = 0
    relationships: list[AssetFunctionRelationship] = []
    relationship_keys: set[tuple[str, str]] = set()
    incompatible_count = 0
    for relationship in asset.function_relationships:
        function_id = relationship.function_id.strip()
        if function_id not in function_order:
            unknown_count += 1
            continue
        if (
            asset.asset_type == "function"
            and relationship.relationship_type != "implements"
        ) or (
            asset.asset_type in _EXTERNAL_AFFECTED_TYPES
            and relationship.relationship_type != "affects"
        ):
            incompatible_count += 1
            continue
        key = (function_id, relationship.relationship_type)
        if key in relationship_keys:
            duplicate_count += 1
            continue
        relationship_keys.add(key)
        relationships.append(
            relationship.model_copy(update={"function_id": function_id})
        )
    if not asset.function_relationships:
        for raw_id in asset.related_function_ids:
            function_id = raw_id.strip()
            if function_id not in function_order:
                unknown_count += 1
                continue
            if function_id in normalized:
                duplicate_count += 1
                continue
            normalized.append(function_id)
    for relationship in relationships:
        if relationship.function_id not in normalized:
            normalized.append(relationship.function_id)
    normalized.sort(key=function_order.__getitem__)
    if unknown_count:
        actions.append("未知功能编号已移除")
    if duplicate_count:
        actions.append("重复功能编号已合并")
    if incompatible_count:
        actions.append("与资产类型不一致的功能关系已移除")
    if not normalized:
        actions.append("资产缺少有效功能关联")
    relationships.sort(
        key=lambda item: (
            function_order[item.function_id],
            item.relationship_type,
        )
    )
    return (
        asset.model_copy(
            update={
                "related_function_ids": normalized,
                "function_relationships": relationships,
            }
        ),
        tuple(actions),
    )


def _function_coverage_notes(
    assets: list[Asset],
    product_functions: list[Any],
) -> tuple[list[str], bool]:
    """Report uncovered Node [1] functions without rejecting or regenerating the inventory."""
    function_names = {
        function.function_id: function.name for function in product_functions
    }
    mapped_ids = {
        function_id
        for asset in assets
        for function_id in asset.related_function_ids
    }
    function_asset_ids = {
        function_id
        for asset in assets
        if asset.asset_type == "function"
        for function_id in asset.related_function_ids
    }
    missing_relationships = [
        function_id
        for function_id in function_names
        if function_id not in mapped_ids
    ]
    missing_function_assets = [
        function_id
        for function_id in function_names
        if function_id not in function_asset_ids
    ]
    notes: list[str] = []
    if missing_relationships:
        rendered = "、".join(
            f"{function_id} {function_names[function_id]}"
            for function_id in missing_relationships
        )
        notes.append(f"尚未关联任何资产的Node1功能：{rendered}。")
    if missing_function_assets:
        rendered = "、".join(
            f"{function_id} {function_names[function_id]}"
            for function_id in missing_function_assets
        )
        notes.append(f"尚未由功能资产覆盖的Node1功能：{rendered}。")
    return notes, bool(missing_relationships or missing_function_assets)


def _apply_asset_function_mapping(
    result: AssetIdentificationResult,
    mapping: AssetFunctionMappingResult | None,
    product_functions: list[Any],
) -> AssetIdentificationResult:
    """Apply focused mappings conservatively; incomplete output degrades instead of blocking."""
    function_order = {
        function.function_id: index
        for index, function in enumerate(product_functions)
    }
    asset_by_id = {asset.asset_id: asset for asset in result.assets}
    known_asset_ids = set(asset_by_id)
    mapped_ids: dict[str, list[str]] = {}
    mapped_relationships: dict[str, list[AssetFunctionRelationship]] = {}
    unknown_asset_count = 0
    duplicate_mapping_count = 0
    unknown_function_count = 0
    duplicate_relationship_count = 0
    untyped_mapping_count = 0
    inconsistent_compatibility_count = 0

    if mapping is not None:
        for entry in mapping.mappings:
            if entry.asset_id not in known_asset_ids:
                unknown_asset_count += 1
                continue
            if entry.asset_id in mapped_ids:
                duplicate_mapping_count += 1
            current_ids = mapped_ids.setdefault(entry.asset_id, [])
            current_relationships = mapped_relationships.setdefault(
                entry.asset_id, []
            )
            if entry.relationships:
                relationship_ids = {
                    relationship.function_id
                    for relationship in entry.relationships
                }
                if entry.related_function_ids and set(entry.related_function_ids) != relationship_ids:
                    inconsistent_compatibility_count += 1
                for relationship in entry.relationships:
                    function_id = relationship.function_id
                    if function_id not in function_order:
                        unknown_function_count += 1
                        continue
                    key = (function_id, relationship.relationship_type)
                    if any(
                        (item.function_id, item.relationship_type) == key
                        for item in current_relationships
                    ):
                        duplicate_relationship_count += 1
                        continue
                    current_relationships.append(relationship)
                    if function_id not in current_ids:
                        current_ids.append(function_id)
                continue
            if entry.related_function_ids:
                untyped_mapping_count += 1
            for function_id in entry.related_function_ids:
                if function_id not in function_order:
                    unknown_function_count += 1
                    continue
                if function_id not in current_ids:
                    current_ids.append(function_id)

        for asset_id, function_ids in mapped_ids.items():
            function_ids.sort(key=function_order.__getitem__)

    missing_mapping_count = 0
    empty_mapping_count = 0
    overbroad_mapping_count = 0
    incompatible_relationship_count = 0
    assets: list[Asset] = []
    for asset in result.assets:
        if mapping is not None and asset.asset_id in mapped_ids:
            related_function_ids = mapped_ids[asset.asset_id]
            function_relationships = mapped_relationships[asset.asset_id]
        else:
            related_function_ids = asset.related_function_ids
            function_relationships = asset.function_relationships
            missing_mapping_count += 1
        normalized_asset, normalization_actions = _normalize_asset_function_links(
            asset.model_copy(
                update={
                    "related_function_ids": related_function_ids,
                    "function_relationships": function_relationships,
                }
            ),
            function_order=function_order,
        )
        if "与资产类型不一致的功能关系已移除" in normalization_actions:
            incompatible_relationship_count += 1
        if _has_overbroad_function_mapping(
            normalized_asset,
            len(function_order),
        ):
            normalized_asset = normalized_asset.model_copy(
                update={
                    "related_function_ids": [],
                    "function_relationships": [],
                }
            )
            overbroad_mapping_count += 1
        if not normalized_asset.related_function_ids:
            empty_mapping_count += 1
        assets.append(normalized_asset)

    notes = [result.notes] if result.notes else []
    if mapping is None:
        notes.append("资产与功能统一映射因技术错误未完成，已保留分段中的临时关系供人工复核。")
    elif mapping.notes:
        notes.append(f"资产功能映射：{mapping.notes}")

    correction_parts: list[str] = []
    if unknown_asset_count:
        correction_parts.append(f"忽略未知资产编号{unknown_asset_count}项")
    if unknown_function_count:
        correction_parts.append(f"移除未知功能编号{unknown_function_count}项")
    if duplicate_mapping_count:
        correction_parts.append(f"合并重复资产映射{duplicate_mapping_count}项")
    if duplicate_relationship_count:
        correction_parts.append(f"合并重复类型化关系{duplicate_relationship_count}项")
    if inconsistent_compatibility_count:
        correction_parts.append(
            f"忽略与类型化关系不一致的兼容编号列表{inconsistent_compatibility_count}项"
        )
    if untyped_mapping_count:
        correction_parts.append(
            f"保留缺少关系类型和依据的兼容映射{untyped_mapping_count}项"
        )
    if incompatible_relationship_count:
        correction_parts.append(
            f"移除与资产对象类型不一致的关系{incompatible_relationship_count}项"
        )
    if missing_mapping_count:
        correction_parts.append(f"保留未返回映射资产的临时关系{missing_mapping_count}项")
    if empty_mapping_count:
        correction_parts.append(f"无可靠功能关系、留待人工确认的资产{empty_mapping_count}项")
    if overbroad_mapping_count:
        correction_parts.append(
            f"清空无法区分主要直接关系的过宽映射{overbroad_mapping_count}项"
        )
    if correction_parts:
        notes.append("资产功能映射纠错：" + "；".join(correction_parts) + "。")

    coverage_notes, coverage_incomplete = _function_coverage_notes(
        assets,
        product_functions,
    )
    notes.extend(coverage_notes)
    mapping_incomplete = (
        mapping is None
        or bool(unknown_asset_count)
        or bool(unknown_function_count)
        or bool(duplicate_mapping_count)
        or bool(duplicate_relationship_count)
        or bool(inconsistent_compatibility_count)
        or bool(untyped_mapping_count)
        or bool(incompatible_relationship_count)
        or bool(missing_mapping_count)
        or bool(empty_mapping_count)
        or bool(overbroad_mapping_count)
        or coverage_incomplete
    )
    return result.model_copy(
        update={
            "assets": assets,
            "assessment": (
                AssessmentVerdict.PARTIAL
                if mapping_incomplete
                else result.assessment
            ),
            "notes": " ".join(notes) or None,
        }
    )


def _finalize_unsectioned_asset_result(
    result: AssetIdentificationResult,
    product_functions: list[Any],
    *,
    scope: Any | None = None,
    product_context: Any | None = None,
) -> AssetIdentificationResult:
    """Apply the same non-blocking business and function checks to the full-input path."""
    function_order = {
        function.function_id: index
        for index, function in enumerate(product_functions)
    }
    assets: list[Asset] = []
    action_counts: dict[str, int] = {}
    for asset in result.assets:
        asset, business_actions = _repair_asset_business_rules(asset)
        asset, scope_actions = _align_asset_scope_status(
            asset,
            scope=scope,
            product_context=product_context,
        )
        asset, function_actions = _normalize_asset_function_links(
            asset,
            function_order=function_order,
        )
        for action in (*business_actions, *scope_actions, *function_actions):
            action_counts[action] = action_counts.get(action, 0) + 1
        assets.append(asset)

    notes = [result.notes] if result.notes else []
    if action_counts:
        notes.append(
            "确定性业务纠错："
            + "；".join(
                f"{action}{count}项" for action, count in action_counts.items()
            )
            + "。"
        )
    coverage_notes, coverage_incomplete = _function_coverage_notes(
        assets,
        product_functions,
    )
    notes.extend(coverage_notes)
    needs_partial = coverage_incomplete or any(
        action in action_counts
        for action in (
            "无直接证据候选已降为待工程师确认",
            "缺少原文支持的推断位置已清空",
            "资产缺少有效功能关联",
            "网络安全目标依据待工程师确认",
        )
    )
    return result.model_copy(
        update={
            "assets": assets,
            "assessment": (
                AssessmentVerdict.PARTIAL if needs_partial else result.assessment
            ),
            "notes": " ".join(notes) or None,
        }
    )


def _assemble_asset_sections(
    section_results: list[tuple[str, AssetSectionResult]],
    *,
    section_failures: list[str],
    field_failures: tuple[tuple[RetrievalField, str], ...],
    product_functions: list[Any],
    defer_function_coverage: bool = False,
    scope: Any | None = None,
    product_context: Any | None = None,
) -> AssetIdentificationResult:
    """Merge successful sections without another LLM call."""
    assets: list[Asset] = []
    notes: list[str] = []
    duplicate_count = 0
    possible_duplicate_count = 0
    business_action_counts: dict[str, int] = {}
    function_order = {
        function.function_id: index
        for index, function in enumerate(product_functions)
    }

    for section_name, section in section_results:
        if section.notes:
            notes.append(f"{section_name}：{section.notes}")
        if section.rejected_items:
            notes.append(
                f"{section_name}逐项拒绝：{'；'.join(section.rejected_items)}。"
            )
        for asset in section.assets:
            asset, business_actions = _repair_asset_business_rules(asset)
            asset, scope_actions = _align_asset_scope_status(
                asset,
                scope=scope,
                product_context=product_context,
            )
            if _is_passive_support_asset(asset):
                action = "无独立数字功能的被动支撑对象已并入平台或网络路径"
                business_action_counts[action] = business_action_counts.get(action, 0) + 1
                continue
            asset, function_actions = _normalize_asset_function_links(
                asset,
                function_order=function_order,
            )
            if defer_function_coverage:
                function_actions = tuple(
                    action
                    for action in function_actions
                    if action != "资产缺少有效功能关联"
                )
            for action in (*business_actions, *scope_actions, *function_actions):
                business_action_counts[action] = business_action_counts.get(action, 0) + 1
            duplicate_index = next(
                (
                    index
                    for index, existing in enumerate(assets)
                    if _assets_are_conservative_merge_candidates(existing, asset)
                ),
                None,
            )
            if duplicate_index is not None:
                duplicate_count += 1
                assets[duplicate_index] = _merge_asset_duplicates(
                    assets[duplicate_index],
                    asset,
                    function_order=function_order,
                )
                continue
            if any(
                existing.asset_type == asset.asset_type
                and _normalized_asset_name(existing.name)
                == _normalized_asset_name(asset.name)
                for existing in assets
            ):
                possible_duplicate_count += 1
            assets.append(asset)

    if not assets:
        raise ValueError("All Node [2] asset synthesis sections were empty or failed")

    renumbered_assets: list[Asset] = []
    objective_number = 1
    for asset_number, asset in enumerate(assets, start=1):
        objectives = []
        for objective in asset.related_objectives:
            objectives.append(
                objective.model_copy(
                    update={"objective_id": f"OBJ-{objective_number:03d}"}
                )
            )
            objective_number += 1
        if not objectives:
            objectives.append(
                _fallback_objective_for_asset(
                    asset,
                    objective_id=f"OBJ-{objective_number:03d}",
                )
            )
            objective_number += 1
            action = "缺少保护目标的资产已补充中性待确认目标"
            business_action_counts[action] = business_action_counts.get(action, 0) + 1
        renumbered_assets.append(
            asset.model_copy(
                update={
                    "asset_id": f"ASSET-{asset_number:03d}",
                    "related_objectives": objectives,
                }
            )
        )
    assets = renumbered_assets

    for section_name in section_failures:
        notes.append(f"{section_name}分段因技术错误未完成，其他分段已保留，需人工复核该分段。")
    for field_id, _error in field_failures:
        notes.append(f"{field_id.value}字段因技术错误未完成，需人工复核该类别。")
    if duplicate_count:
        notes.append(
            f"确定性合并时移除了{duplicate_count}项同类型、同范围状态且证据相交的重复资产。"
        )
    if possible_duplicate_count:
        notes.append(
            f"保留{possible_duplicate_count}组同名但边界、属性或证据不足以安全合并的候选，需人工确认。"
        )
    if business_action_counts:
        notes.append(
            "确定性业务纠错："
            + "；".join(
                f"{action}{count}项"
                for action, count in business_action_counts.items()
            )
            + "。"
        )
    if defer_function_coverage:
        function_coverage_incomplete = False
    else:
        coverage_notes, function_coverage_incomplete = _function_coverage_notes(
            assets,
            product_functions,
        )
        notes.extend(coverage_notes)

    complete = (
        len(section_results) == len(_ASSET_SECTION_FIELDS)
        and not section_failures
        and not field_failures
        and all(
            result.assessment == AssessmentVerdict.PASS
            for _name, result in section_results
        )
        and not any(
            action in business_action_counts
            for action in (
                "无直接证据候选已降为待工程师确认",
                "缺少原文支持的推断位置已清空",
                "资产缺少有效功能关联",
                "缺少保护目标的资产已补充中性待确认目标",
                "上游范围状态冲突或未知的资产已降为待工程师确认",
                "网络安全目标依据待工程师确认",
            )
        )
        and not possible_duplicate_count
        and not function_coverage_incomplete
    )
    return AssetIdentificationResult(
        assets=assets,
        assessment=(AssessmentVerdict.PASS if complete else AssessmentVerdict.PARTIAL),
        notes=" ".join(notes) or None,
    )


def _canonicalize_and_validate_threats(
    result: ThreatIdentificationResult,
    approved_assets: list[Asset],
) -> ThreatIdentificationResult:
    """Bind LLM threat references to canonical approved assets and enforce coverage."""
    asset_by_id = {asset.asset_id: asset for asset in approved_assets}
    objective_by_id = {
        objective.objective_id: objective
        for asset in approved_assets
        for objective in asset.related_objectives
    }
    covered_asset_ids: set[str] = set()
    canonical_threats = []

    for threat in result.threats:
        if not threat.title.strip() or not threat.description.strip() or not threat.cause_of_compromise.strip():
            raise ValueError(
                f"Threat {threat.threat_id} must have non-empty title, description, and cause_of_compromise."
            )

        target_ids = [asset.asset_id for asset in threat.targeted_assets]
        if not target_ids:
            raise ValueError(f"Threat {threat.threat_id} must target at least one approved asset.")
        if len(target_ids) != len(set(target_ids)):
            raise ValueError(f"Threat {threat.threat_id} contains duplicate targeted asset IDs.")

        unknown_assets = sorted(set(target_ids) - set(asset_by_id))
        if unknown_assets:
            raise ValueError(
                f"Threat {threat.threat_id} references unknown asset IDs: {unknown_assets}."
            )

        allowed_objective_ids = {
            objective.objective_id
            for asset_id in target_ids
            for objective in asset_by_id[asset_id].related_objectives
        }
        objective_ids = [objective.objective_id for objective in threat.compromised_objectives]
        if not objective_ids:
            raise ValueError(
                f"Threat {threat.threat_id} must compromise at least one objective of its targeted assets."
            )
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError(f"Threat {threat.threat_id} contains duplicate objective IDs.")

        invalid_objectives = sorted(set(objective_ids) - allowed_objective_ids)
        if invalid_objectives:
            raise ValueError(
                f"Threat {threat.threat_id} references objectives not owned by its targets: {invalid_objectives}."
            )

        canonical_threats.append(
            threat.model_copy(
                update={
                    "targeted_assets": [asset_by_id[asset_id] for asset_id in target_ids],
                    "compromised_objectives": [objective_by_id[objective_id] for objective_id in objective_ids],
                }
            )
        )
        covered_asset_ids.update(target_ids)

    uncovered_assets = sorted(set(asset_by_id) - covered_asset_ids)
    if uncovered_assets:
        raise ValueError(f"Approved assets without a threat scenario: {uncovered_assets}.")

    return result.model_copy(update={"threats": canonical_threats})


def identify_assets(state: TaraState, config: RunnableConfig) -> dict[str, Any]:
    """Generate the step [2] asset inventory and cybersecurity objectives."""
    logger.info("进入 Node [2] 资产与网络安全目标识别节点")
    errors = list(state.get("errors", []))
    updates: dict[str, Any] = {
        "assets": [],
        "asset_assessment": AssessmentVerdict.FAIL,
        "asset_notes": None,
        "asset_review_approved": False,
        "asset_review_notes": None,
        "threat_assessment": None,
        "errors": errors,
        "current_step": "node_2_asset_identification",
    }

    scope = state.get("scope")
    product_context = state.get("product_context")
    if scope is None or product_context is None:
        errors.append("Asset identification requires validated scope and product_context.")
        updates.update({"status": ASSET_IDENTIFICATION_BLOCKED, "errors": errors})
        return updates

    technical_incomplete = False
    try:
        llm = get_llm()
        if config.get("configurable", {}).get("rag_index_dir"):
            binding = load_runtime_scope(config)
            packet_ref = state.get("evidence_packet_ref")
            if packet_ref is None or binding.reference != packet_ref:
                raise ValueError("Runtime evidence packet does not match Node [0] identity")
            facts = extract_node_facts(
                llm=llm,
                scope=binding,
                node_id=EvidenceTargetNode.ASSETS,
                config=config,
            )
            for field_id, failure in facts.failures:
                errors.append(f"Asset field {field_id.value} failed: {failure}")
            section_results: list[tuple[str, AssetSectionResult]] = []
            section_failures: list[str] = []
            for section_name in _ASSET_SECTION_FIELDS:
                try:
                    section_results.append(
                        (
                            section_name,
                            _extract_asset_section(
                                llm=llm,
                                section_name=section_name,
                                scope=scope,
                                product_context=product_context,
                                facts=facts,
                                binding=binding,
                                config=config,
                            ),
                        )
                    )
                except Exception as exc:
                    section_failures.append(section_name)
                    errors.append(f"Asset section {section_name} failed: {exc}")
                    logger.error(
                        "Node [2] 分段综合失败，已局部降级：%s (%s)",
                        section_name,
                        exc,
                    )
            technical_incomplete = bool(section_failures or facts.failures)
            result = _assemble_asset_sections(
                section_results,
                section_failures=section_failures,
                field_failures=facts.failures,
                product_functions=product_context.functions,
                defer_function_coverage=True,
                scope=scope,
                product_context=product_context,
            )
            try:
                mapping = _extract_asset_function_mapping(
                    llm=llm,
                    assets=result.assets,
                    product_functions=product_context.functions,
                    binding=binding,
                    config=config,
                )
            except Exception as exc:
                mapping = None
                errors.append(f"Asset function mapping failed: {exc}")
                logger.error(
                    "Node [2] 资产功能映射失败，已保留分段临时关系：%s",
                    exc,
                )
            result = _apply_asset_function_mapping(
                result,
                mapping,
                product_context.functions,
            )
        else:
            analysis_input = json.dumps(
                {
                    "scope": scope.model_dump(mode="json"),
                    "product_context": product_context.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
            result = extract_with_retry(
                llm=llm,
                prompt_template=_ASSET_PROMPT_TEMPLATE,
                schema_class=AssetIdentificationResult,
                sample_input=analysis_input,
                semantic_validator=lambda candidate: _validate_asset_evidence_subset(
                    _validate_asset_semantics(candidate),
                    scope,
                    product_context,
                ),
                payload_transformer=lambda payload: canonicalize_evidence_from_upstream(
                    payload,
                    scope,
                    product_context,
                ),
            )
            result = _finalize_unsectioned_asset_result(
                result,
                product_context.functions,
                scope=scope,
                product_context=product_context,
            )
    except Exception as exc:
        errors.append(f"Asset identification failed: {exc}")
        updates.update({"status": ASSET_IDENTIFICATION_FAILED, "errors": errors})
        return updates

    workflow_status = resolve_asset_identification_status(
        result.assessment,
        technical_incomplete=technical_incomplete,
        asset_count=len(result.assets),
    )

    updates.update(
        {
            "assets": result.assets,
            "asset_assessment": result.assessment,
            "asset_notes": result.notes,
            "status": workflow_status,
            "errors": errors,
        }
    )
    if technical_incomplete:
        logger.error(
            "Node [2] 仅形成不完整资产快照：%d 项资产；技术失败阻断业务审批",
            len(result.assets),
        )
    else:
        logger.info(
            "Node [2] 资产识别形成%s：%d 项资产",
            "完整结果" if workflow_status == ASSET_IDENTIFICATION_COMPLETED else "可复核草稿",
            len(result.assets),
        )
    return updates


def review_assets(state: TaraState) -> dict[str, Any]:
    """Pause the graph for mandatory human confirmation of step [2] assets."""
    assets = state.get("assets", [])
    if not assets:
        errors = list(state.get("errors", []))
        errors.append("Asset review requires a non-empty asset inventory.")
        return {
            "asset_review_approved": False,
            "errors": errors,
            "current_step": "node_2_asset_review",
            "status": "asset_review_blocked",
        }

    decision = interrupt(
        {
            "review_type": "asset_confirmation",
            "step_id": "2",
            "title": "确认资产与网络安全目标",
            "description": "确认资产清单及其网络安全目标完整、准确后，方可进入 STRIDE 威胁建模。",
            "asset_assessment": state.get("asset_assessment"),
            "asset_notes": state.get("asset_notes"),
            "assets": [asset.model_dump(mode="json") for asset in assets],
            "required_action": {"approved": "boolean", "notes": "optional string"},
        }
    )

    if isinstance(decision, bool):
        approved = decision
        notes = None
    elif isinstance(decision, dict) and isinstance(decision.get("approved"), bool):
        approved = decision["approved"]
        raw_notes = decision.get("notes")
        notes = str(raw_notes).strip() if raw_notes is not None else None
    else:
        raise TypeError("Asset review decision must be a boolean or {'approved': bool, 'notes': str}.")

    logger.info("Node [2] 人工复核结果：%s", "approved" if approved else "rejected")
    return {
        "asset_review_approved": approved,
        "asset_review_notes": notes,
        "current_step": "node_2_asset_review",
        "status": "asset_review_approved" if approved else "asset_review_rejected",
    }


def model_threats(state: TaraState) -> dict[str, Any]:
    """Generate step [3] STRIDE scenarios from the approved asset inventory."""
    logger.info("进入 Node [3] STRIDE 威胁建模节点")
    errors = list(state.get("errors", []))
    updates: dict[str, Any] = {
        "threat_assessment": None,
        "errors": errors,
        "current_step": "node_3_threat_modeling",
    }

    approved_assets = state.get("assets", [])
    product_context = state.get("product_context")
    if not state.get("asset_review_approved"):
        errors.append("Threat modelling requires explicit human approval of the asset inventory.")
        updates.update({"status": "threat_modeling_blocked", "errors": errors})
        return updates
    if not approved_assets or product_context is None:
        errors.append("Threat modelling requires approved assets and product_context.")
        updates.update({"status": "threat_modeling_blocked", "errors": errors})
        return updates

    try:
        llm = get_llm()
        analysis_input = json.dumps(
            {
                "product_context": product_context.model_dump(mode="json"),
                "approved_assets": [asset.model_dump(mode="json") for asset in approved_assets],
                "asset_review_notes": state.get("asset_review_notes"),
            },
            ensure_ascii=False,
            indent=2,
        )
        result = extract_with_retry(
            llm=llm,
            prompt_template=_THREAT_PROMPT_TEMPLATE,
            schema_class=ThreatIdentificationResult,
            sample_input=analysis_input,
            semantic_validator=lambda candidate: _canonicalize_and_validate_threats(
                candidate,
                approved_assets,
            ),
        )
    except Exception as exc:
        errors.append(f"Threat modelling failed: {exc}")
        updates.update({"status": "threat_modeling_failed", "errors": errors})
        return updates

    threat_assessment = ThreatAssessment(
        threats=result.threats,
        scores=[],
        assessment=result.assessment,
        notes=result.notes,
    )
    updates.update(
        {
            "threat_assessment": threat_assessment,
            "status": "threat_modeling_completed",
            "errors": errors,
        }
    )
    logger.info("Node [3] STRIDE 威胁建模完成：%d 个场景", len(result.threats))
    return updates


def route_after_assets(state: TaraState) -> str:
    """Continue to human review only for a non-empty validated inventory."""
    return "review_assets" if is_asset_reviewable_state(state) else "end"


def route_after_asset_review(state: TaraState) -> str:
    """Run threat modelling only after explicit approval."""
    review_is_approved = (
        state.get("status") == "asset_review_approved"
        and state.get("asset_review_approved") is True
    )
    return "model_threats" if review_is_approved else "end"


__all__ = [
    "ASSET_RULE_VERSION",
    "identify_assets",
    "model_threats",
    "review_assets",
    "route_after_asset_review",
    "route_after_assets",
]
