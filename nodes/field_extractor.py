"""Field-level retrieval and compact fact extraction inside workflow nodes."""

from __future__ import annotations

import json
from hashlib import sha256
from dataclasses import dataclass
from pathlib import Path

from langchain_core.runnables import RunnableConfig

from core.logger import setup_logger
from core.structured_extraction import extract_with_retry
from prompts import load_prompt
from schemas.evidence_packet import EvidenceTargetNode
from schemas.retrieval import (
    FieldExtractionResult,
    RetrievalField,
    RetrievalProfile,
    RetrievalTrace,
)
from tools.evidence_input import (
    EvidencePacketBinding,
    bind_materialized_packet,
    load_evidence_packet,
    render_evidence_material,
)
from tools.embedding_provider import DashScopeEmbeddingProvider
from tools.rag_retriever import load_vector_index, retrieve_evidence
from tools.retrieval_profiles import get_profiles_for_node, get_targeted_anchor_groups
from tools.retrieval_profiles import PROFILE_VERSION
from schemas.retrieval import RetrievalRequest


logger = setup_logger("field_extractor")

FIELD_FACT_PROMPT_VERSION = "2.5"


def _model_name(llm) -> str:
    return str(getattr(llm, "model_name", None) or getattr(llm, "model", "unknown"))


def _field_schema_sha256(profile: RetrievalProfile) -> str:
    payload = json.dumps(
        FieldExtractionResult.schema_for_profile(profile),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _stable_sha256(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


_FIELD_FACT_PROMPT = load_prompt("field_fact_extraction.md", "field_fact")


def _field_prompt_template(profile: RetrievalProfile) -> str:
    return _FIELD_FACT_PROMPT.format(
        node_field=f"{profile.node_id.value}/{profile.field_id.value}",
        max_facts=profile.max_facts,
        extraction_guidance=profile.extraction_guidance,
        json_schema="{json_schema}",
        sample_input="{sample_input}",
    )


def _cache_inputs(
    *,
    request: RetrievalRequest,
    trace: RetrievalTrace,
    text_model: str,
    profile: RetrievalProfile,
) -> dict[str, str]:
    """Return every deterministic input that can change one field result."""
    profile_payload = profile.model_dump(mode="json")
    anchor_groups = get_targeted_anchor_groups(profile.node_id, profile.field_id)
    if anchor_groups:
        profile_payload["targeted_anchor_groups"] = [list(group) for group in anchor_groups]
    return {
        "node_id": request.node_id.value,
        "field_id": request.field_id.value,
        "source_packet_sha256": trace.scope_packet_sha256,
        "retrieval_packet_sha256": trace.packet_sha256,
        "rag_index_id": trace.index_id,
        "text_model": text_model,
        "retrieval_profile_sha256": _stable_sha256(profile_payload),
        "field_prompt_sha256": sha256(
            _field_prompt_template(profile).encode("utf-8")
        ).hexdigest(),
        "field_schema_sha256": _field_schema_sha256(profile),
    }


@dataclass(frozen=True)
class NodeFactBundle:
    """In-memory field facts plus retrieval identities for final synthesis."""

    batches: tuple[FieldExtractionResult, ...]
    traces: tuple[RetrievalTrace, ...]
    retrieved_block_ids: frozenset[str]
    failures: tuple[tuple[RetrievalField, str], ...] = ()

    def prompt_payload(
        self,
        field_ids: set[RetrievalField] | frozenset[RetrievalField] | None = None,
    ) -> dict:
        """Render all facts or only the fields needed by one synthesis section."""
        batches = (
            self.batches
            if field_ids is None
            else tuple(batch for batch in self.batches if batch.field_id in field_ids)
        )
        traces = (
            self.traces
            if field_ids is None
            else tuple(trace for trace in self.traces if trace.request.field_id in field_ids)
        )
        payload = {
            "field_batches": [batch.model_dump(mode="json") for batch in batches],
            "retrieval_summary": [
                {
                    "node_id": trace.request.node_id.value,
                    "field_id": trace.request.field_id.value,
                    "selected_blocks": trace.selected_count,
                    "selected_tokens": trace.selected_token_count,
                }
                for trace in traces
            ],
            "extraction_failures": [
                {"field_id": field_id.value, "reason": "technical_failure"}
                for field_id, _error in self.failures
                if field_ids is None or field_id in field_ids
            ],
        }
        if field_ids is not None:
            payload["evidence_contract"] = {
                "fact_support": [
                    {
                        "fact_ref": f"{batch.field_id.value}/{fact.fact_id}",
                        "field_id": batch.field_id.value,
                        "statement": fact.statement,
                        "block_ids": fact.block_ids,
                        "is_uncertain": fact.is_uncertain,
                    }
                    for batch in batches
                    for fact in batch.facts
                ],
                "rule": (
                    "每个业务结论只能使用一条或多条直接支持它的 fact；EvidenceRef.block_id "
                    "必须来自这些 fact 自己的 block_ids。unknowns 和 contradictions 不能作为事实证据。"
                ),
            }
        return payload

    def fact_block_ids(
        self,
        field_ids: set[RetrievalField] | frozenset[RetrievalField] | None = None,
    ) -> frozenset[str]:
        """Return blocks explicitly accepted by field facts, excluding unused retrieval hits."""
        batches = (
            self.batches
            if field_ids is None
            else tuple(batch for batch in self.batches if batch.field_id in field_ids)
        )
        return frozenset(
            block_id
            for batch in batches
            for fact in batch.facts
            for block_id in fact.block_ids
        )


def load_runtime_scope(config: RunnableConfig) -> EvidencePacketBinding:
    """Load the approved static scope packet from workflow runtime configuration."""
    configurable = config.get("configurable", {})
    packet_path = configurable.get("evidence_packet_path")
    if not packet_path:
        raise ValueError("configurable.evidence_packet_path is required")
    return load_evidence_packet(
        packet_path,
        workspace=configurable.get("workspace"),
        verify_source_files=True,
    )


def _validate_field_result(
    result: FieldExtractionResult,
    request: RetrievalRequest,
    binding: EvidencePacketBinding,
    max_facts: int = 24,
) -> FieldExtractionResult:
    if result.node_id != request.node_id or result.field_id != request.field_id:
        raise ValueError("Field extraction result does not match its retrieval request")
    if len(result.facts) > max_facts:
        raise ValueError(f"facts must contain at most {max_facts} items for {request.field_id.value}")
    unknown_blocks = {
        block_id
        for fact in result.facts
        for block_id in fact.block_ids
        if block_id not in binding.blocks
    }
    if unknown_blocks:
        raise ValueError(f"Field facts reference blocks outside retrieval result: {sorted(unknown_blocks)}")
    return result


def _field_checkpoint_path(config: RunnableConfig, request: RetrievalRequest) -> Path | None:
    raw_directory = config.get("configurable", {}).get("field_checkpoint_dir")
    if not raw_directory:
        return None
    return Path(raw_directory) / request.node_id.value / f"{request.field_id.value}.json"


def _field_checkpoint_fallback_path(
    config: RunnableConfig,
    request: RetrievalRequest,
) -> Path | None:
    raw_directory = config.get("configurable", {}).get(
        "field_checkpoint_fallback_dir"
    )
    if not raw_directory:
        return None
    return Path(raw_directory) / request.node_id.value / f"{request.field_id.value}.json"


def _load_field_checkpoint(
    path: Path | None,
    *,
    request: RetrievalRequest,
    binding: EvidencePacketBinding,
    cache_inputs: dict[str, str],
    max_facts: int = 24,
) -> tuple[FieldExtractionResult | None, str]:
    if path is None or not path.is_file():
        return None, "没有字段缓存"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "field_fact_checkpoint.v3":
            return None, "旧缓存格式不含完整自动指纹"
        stored_inputs = payload.get("cache_inputs")
        stored_fingerprint = payload.get("cache_fingerprint")
        expected_fingerprint = _stable_sha256(cache_inputs)
        if stored_fingerprint != expected_fingerprint or stored_inputs != cache_inputs:
            changed = [
                key
                for key, value in cache_inputs.items()
                if not isinstance(stored_inputs, dict) or stored_inputs.get(key) != value
            ]
            reason = "、".join(changed) if changed else "缓存指纹损坏"
            return None, f"输入指纹不一致：{reason}"
        result = FieldExtractionResult.model_validate(payload.get("result"))
        return _validate_field_result(result, request, binding, max_facts=max_facts), "输入指纹一致"
    except Exception as exc:
        logger.warning("忽略无效字段检查点 %s：%s", path, exc)
        return None, f"缓存文件无效：{exc}"


def _save_field_checkpoint(
    path: Path | None,
    *,
    result: FieldExtractionResult,
    trace: RetrievalTrace,
    cache_inputs: dict[str, str],
) -> None:
    if path is None:
        return
    payload = {
        "schema_version": "field_fact_checkpoint.v3",
        "node_id": trace.request.node_id.value,
        "field_id": trace.request.field_id.value,
        "index_id": trace.index_id,
        "packet_sha256": trace.packet_sha256,
        "retrieval_profile_version": PROFILE_VERSION,
        "field_fact_prompt_version": FIELD_FACT_PROMPT_VERSION,
        "cache_inputs": cache_inputs,
        "cache_fingerprint": _stable_sha256(cache_inputs),
        "result": result.model_dump(mode="json"),
        "retrieval_trace": trace.model_dump(mode="json"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _extract_profile_facts(
    *,
    llm,
    profile: RetrievalProfile,
    scope: EvidencePacketBinding,
    config: RunnableConfig,
    loaded,
    provider,
    text_model: str,
    cache_policy: str,
) -> tuple[FieldExtractionResult, RetrievalTrace, frozenset[str]]:
    """Retrieve, reuse, or generate one field batch."""
    request = RetrievalRequest(
        project_id=scope.packet.project_id,
        node_id=profile.node_id,
        field_id=profile.field_id,
        token_budget=profile.token_budget,
        max_blocks=profile.max_blocks,
        neighbor_window=profile.neighbor_window,
    )
    packet, trace = retrieve_evidence(
        loaded=loaded,
        scope=scope,
        request=request,
        provider=provider,
    )
    logger.info(
        "字段检索完成：%s/%s，blocks=%d，estimated_tokens=%d，index=%s",
        profile.node_id.value,
        profile.field_id.value,
        trace.selected_count,
        trace.selected_token_count,
        trace.index_id,
    )
    field_binding = bind_materialized_packet(packet)
    checkpoint_path = _field_checkpoint_path(config, request)
    fallback_checkpoint_path = _field_checkpoint_fallback_path(config, request)
    cache_inputs = _cache_inputs(
        request=request,
        trace=trace,
        text_model=text_model,
        profile=profile,
    )
    if cache_policy == "refresh":
        cached_result, cache_reason = None, "命令行要求 refresh"
    else:
        cached_result, cache_reason = _load_field_checkpoint(
            checkpoint_path,
            request=request,
            binding=field_binding,
            cache_inputs=cache_inputs,
            max_facts=profile.max_facts,
        )
        if cached_result is None and fallback_checkpoint_path is not None:
            fallback_result, fallback_reason = _load_field_checkpoint(
                fallback_checkpoint_path,
                request=request,
                binding=field_binding,
                cache_inputs=cache_inputs,
                max_facts=profile.max_facts,
            )
            if fallback_result is not None:
                cached_result = fallback_result
                cache_reason = f"复用失败运行检查点：{fallback_reason}"
                _save_field_checkpoint(
                    checkpoint_path,
                    result=cached_result,
                    trace=trace,
                    cache_inputs=cache_inputs,
                )
    if cached_result is not None:
        logger.info(
            "复用字段检查点：%s/%s（%s）",
            profile.node_id.value,
            profile.field_id.value,
            cache_reason,
        )
        return cached_result, trace, frozenset(field_binding.blocks)

    field_input = json.dumps(
        {
            "node_id": profile.node_id.value,
            "field_id": profile.field_id.value,
            "retrieval_intent": trace.effective_query,
            "evidence": render_evidence_material(field_binding),
        },
        ensure_ascii=False,
        indent=2,
    )
    logger.info(
        "重新生成字段事实：%s/%s（%s）",
        profile.node_id.value,
        profile.field_id.value,
        cache_reason,
    )
    result = extract_with_retry(
        task_label=f"{profile.node_id.value}/{profile.field_id.value}",
        llm=llm,
        prompt_template=_field_prompt_template(profile),
        schema_class=FieldExtractionResult,
        json_schema=FieldExtractionResult.schema_for_profile(profile),
        sample_input=field_input,
        semantic_validator=lambda value: _validate_field_result(
            value,
            request,
            field_binding,
            max_facts=profile.max_facts,
        ),
        max_retries=(
            2
            if profile.node_id in {EvidenceTargetNode.SCOPE, EvidenceTargetNode.ASSETS}
            else 3
        ),
    )
    _save_field_checkpoint(
        checkpoint_path,
        result=result,
        trace=trace,
        cache_inputs=cache_inputs,
    )
    return result, trace, frozenset(field_binding.blocks)


def extract_node_facts(
    *,
    llm,
    scope: EvidencePacketBinding,
    node_id: EvidenceTargetNode,
    config: RunnableConfig,
) -> NodeFactBundle:
    """Retrieve and extract every configured field for one workflow node."""
    configurable = config.get("configurable", {})
    index_value = configurable.get("rag_index_dir")
    if not index_value:
        raise ValueError("configurable.rag_index_dir is required for field retrieval")
    workspace = Path(configurable.get("workspace", Path.cwd())).resolve()
    index_path = Path(index_value)
    if not index_path.is_absolute():
        index_path = workspace / index_path
    loaded = load_vector_index(index_directory=index_path, workspace=workspace)
    provider = DashScopeEmbeddingProvider(
        query_cache_dir=loaded.directory / "query_embeddings"
    )
    text_model = _model_name(llm)
    cache_policy = str(configurable.get("field_cache_policy", "reuse"))
    if cache_policy not in {"reuse", "refresh"}:
        raise ValueError(f"Unsupported field_cache_policy: {cache_policy}")

    batches = []
    traces = []
    failures: list[tuple[RetrievalField, str]] = []
    retrieved_block_ids: set[str] = set()
    for profile in get_profiles_for_node(node_id):
        try:
            result, trace, block_ids = _extract_profile_facts(
                llm=llm,
                profile=profile,
                scope=scope,
                config=config,
                loaded=loaded,
                provider=provider,
                text_model=text_model,
                cache_policy=cache_policy,
            )
            batches.append(result)
            traces.append(trace)
            retrieved_block_ids.update(block_ids)
        except Exception as exc:
            if node_id != EvidenceTargetNode.ASSETS:
                raise
            failure = str(exc)
            failures.append((profile.field_id, failure))
            batches.append(
                FieldExtractionResult(
                    node_id=node_id,
                    field_id=profile.field_id,
                    unknowns=[
                        "该检索主题因技术错误未完成；其他主题继续处理，本主题需人工复核。"
                    ],
                )
            )
            logger.error(
                "Node [2] 字段提取失败，已局部降级：%s (%s)",
                profile.field_id.value,
                exc,
            )

    return NodeFactBundle(
        batches=tuple(batches),
        traces=tuple(traces),
        retrieved_block_ids=frozenset(retrieved_block_ids),
        failures=tuple(failures),
    )


__all__ = ["NodeFactBundle", "extract_node_facts", "load_runtime_scope"]
