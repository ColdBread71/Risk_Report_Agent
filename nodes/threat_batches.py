"""Three bounded Node3 perspectives, compact citations and run-local result reuse."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import httpx

from core.logger import setup_logger
from core.structured_extraction import extract_with_retry
from prompts import load_prompt
from schemas.common import AssessmentVerdict, ConfidenceLevel
from schemas.evidence import EvidenceRef
from schemas.threat import ThreatBatchResult, ThreatCandidateResult, ThreatIdentificationResult
from tools.evidence_input import iter_evidence_refs, strip_model_confirmation, validate_evidence_bindings, validate_evidence_subset


logger = setup_logger("threat_batches")
BATCH_RULE_VERSION = "node3_threat_batches.v1"
PERSPECTIVES = (
    ("identity_management", "身份与管理面",
     "交互/管理入口、身份与会话、授权和多租户隔离、配置与信任材料管理、审计。入口可为界面、API、命令行或其他实际存在的管理方式。考虑恢复流程与管理功能的恶意使用。"),
    ("communications_operations", "通信与业务运行面",
     "产品数据流、外部服务与设备交互、业务/控制请求、时间依赖、可用性与资源耗尽。按实际部署分析远端信任和启用条件；涉及物理过程时说明对人员、财产或相邻系统影响的条件链。"),
    ("lifecycle_local", "生命周期与本地维护面",
     "分发、安装、更新、加载/启动、依赖或工具供应链、本地/物理维护、敏感存储、备份恢复、重置及退役。设备、软件、云服务均仅分析实际存在的能力，允许本视角不适用。"),
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def compact_threat_input(state: dict) -> tuple[dict, dict[str, list[EvidenceRef]]]:
    """Keep every product/asset/objective fact; deduplicate source blocks and excerpts."""
    roots = {"scope": state.get("scope"), "product_context": state["product_context"], "assets": state["assets"]}
    by_block: dict[str, list[EvidenceRef]] = {}
    catalog: dict[str, dict] = {}
    for evidence in iter_evidence_refs(roots):
        ref = EvidenceRef.model_validate(strip_model_confirmation(evidence.model_dump(mode="json")))
        block_id = ref.source.block_id
        if not block_id:
            raise ValueError("Node3 citations require source block IDs")
        entry = catalog.setdefault(block_id, {
            "block_id": block_id, "document_id": ref.source.document_id,
            "file_name": ref.source.file_name, "page_number": ref.source.page_number,
            "quotes": [],
        })
        refs = by_block.setdefault(block_id, [])
        if not any(item.quote == ref.quote for item in refs):
            refs.append(ref)
            if ref.quote:
                entry["quotes"].append(ref.quote)

    def compact(value):
        if hasattr(value, "model_dump"):
            return compact(value.model_dump(mode="json"))
        if isinstance(value, dict):
            if "evidence_id" in value and isinstance(value.get("source"), dict):
                return value["source"]["block_id"]
            return {key: compact(item) for key, item in value.items() if key != "review_notes"}
        if isinstance(value, list):
            items = [compact(item) for item in value]
            # Repeated references to one block need not repeat on each object.
            return list(dict.fromkeys(items)) if items and all(isinstance(v, str) and v.startswith("BLK-") for v in items) else items
        return value

    shared = compact(roots)
    shared["asset_review_approved"] = state.get("asset_review_approved") is True
    shared["upstream_draft_notes"] = state.get("asset_notes")
    shared["evidence_catalog"] = [catalog[key] for key in sorted(catalog)]
    return shared, by_block


def _resolve_batch(result, by_block, assets, binding, canonicalize):
    candidates = []
    upstream_refs = [ref for refs in by_block.values() for ref in refs]
    for candidate in result.threats:
        missing = set(candidate.evidence_block_ids) - set(by_block)
        if missing:
            raise ValueError(f"Evidence blocks not present in Node3 input: {sorted(missing)}")
        data = candidate.model_dump(mode="json", exclude={"evidence_block_ids"})
        data["evidence"] = [ref for block_id in dict.fromkeys(candidate.evidence_block_ids) for ref in by_block[block_id]]
        candidates.append(data)
    if not candidates:
        return []
    typed = ThreatCandidateResult(threats=candidates, assessment=result.assessment, notes=result.notes)
    validate_evidence_bindings(typed, binding)
    validate_evidence_subset(typed, upstream_refs)
    return canonicalize(typed, assets, report_coverage=False).threats


def _configured_client(llm, timeout_seconds):
    """Configure only the synchronous Node3 client; other nodes are unchanged."""
    if timeout_seconds <= 0:
        raise ValueError("Node3 read timeout must be positive")
    if getattr(llm, "root_client", None) is not None:
        timeout = httpx.Timeout(connect=30, read=timeout_seconds, write=60, pool=60)
        root = llm.root_client.with_options(timeout=timeout, max_retries=0)
        return llm.model_copy(update={"root_client": root, "client": root.chat.completions,
                                      "request_timeout": timeout, "max_retries": 0})
    return llm


def _write(path: Path | None, payload: dict):
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _save_batch(path, inputs, result):
    payload = result.model_dump(mode="json")
    _write(path, {"schema_version": "node3_batch_checkpoint.v1", "inputs": inputs,
                  "fingerprint": _hash(inputs), "result_sha256": _hash(payload), "result": payload})


def _load_batch(path, inputs):
    if path is None or not path.exists():
        return None
    saved = json.loads(path.read_text(encoding="utf-8"))
    if (saved.get("schema_version") != "node3_batch_checkpoint.v1"
            or saved.get("inputs") != inputs or saved.get("fingerprint") != _hash(inputs)):
        raise ValueError(f"Node3 batch input fingerprint mismatch: {path}; stopped before new requests")
    if saved.get("result_sha256") != _hash(saved.get("result")):
        raise ValueError(f"Node3 batch result hash mismatch: {path}")
    return ThreatBatchResult.model_validate(saved["result"])


def _merge(resolved):
    """Merge exact analytical duplicates only; retain different chains/conditions."""
    threats, seen, sources = [], {}, {}
    confidence_order = {v: i for i, v in enumerate((ConfidenceLevel.NONE, ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH))}
    for batch_id, entries in resolved:
        for threat in entries:
            data = threat.model_dump(mode="json", exclude={"threat_id", "evidence", "confidence", "targeted_assets", "compromised_objectives"})
            data["asset_ids"] = sorted(a.asset_id for a in threat.targeted_assets)
            data["objective_ids"] = sorted(o.objective_id for o in threat.compromised_objectives)
            key = _hash(data)
            origin = {"batch_id": batch_id, "local_threat_id": threat.threat_id}
            if key in seen:
                existing = threats[seen[key]]
                refs = {e.model_dump_json(): e for e in [*existing.evidence, *threat.evidence]}
                confidence = min((existing.confidence, threat.confidence), key=confidence_order.get)
                threats[seen[key]] = existing.model_copy(update={"evidence": list(refs.values()), "confidence": confidence})
                sources[existing.threat_id].append(origin)
            else:
                public_id = f"THREAT-{len(threats) + 1:03}"
                seen[key] = len(threats)
                threats.append(threat.model_copy(update={"threat_id": public_id}))
                sources[public_id] = [origin]
    return threats, sources


def analyze_threat_batches(*, state, binding, config, llm_factory, canonicalize):
    """Run three perspectives, reusing only complete fingerprint-matching results."""
    options = (config or {}).get("configurable", {})
    directory = Path(options["node3_batch_dir"]) if options.get("node3_batch_dir") else None
    reuse = Path(options["node3_reuse_batch_dir"]) if options.get("node3_reuse_batch_dir") else None
    prompt = load_prompt("node3_threats.md", "threat_direct")
    shared, by_block = compact_threat_input(state)
    llm = _configured_client(llm_factory(), float(options.get("node3_read_timeout_seconds", 1800)))
    model = str(getattr(llm, "model_name", None) or getattr(llm, "model", "unknown"))
    index = {"schema_version": "node3_batch_index.v1", "status": "running", "batches": [], "scenario_sources": {}}
    plans = []
    # Validate all available reused results BEFORE making any new paid request.
    for batch_id, label, focus in PERSPECTIVES:
        material = {"perspective": {"id": batch_id, "name": label, "focus": focus}, **shared}
        inputs = {"rule_version": BATCH_RULE_VERSION, "batch_id": batch_id, "model": model,
                  "packet_sha256": binding.reference.packet_sha256,
                  "source_snapshot_sha256": options.get("node3_source_sha256"),
                  "input_sha256": _hash(material), "prompt_sha256": sha256(prompt.encode()).hexdigest(),
                  "schema_sha256": _hash(ThreatBatchResult.model_json_schema())}
        path = directory / f"{batch_id}.json" if directory else None
        cached = _load_batch(path, inputs)
        if cached is None and reuse:
            cached = _load_batch(reuse / f"{batch_id}.json", inputs)
        if cached is not None:
            _resolve_batch(cached, by_block, state["assets"], binding, canonicalize)
        plans.append((batch_id, label, material, inputs, path, cached))
        index["batches"].append({"batch_id": batch_id, "name": label, "status": "pending"})
    index_path = directory / "batch_index.json" if directory else None
    _write(index_path, index)
    resolved, notes, verdicts = [], [], []
    for plan, record in zip(plans, index["batches"]):
        batch_id, label, material, inputs, path, result = plan
        try:
            reused = result is not None
            if result is None:
                logger.info("Node3 分析视角：%s", label)

                def validate(candidate):
                    _resolve_batch(candidate, by_block, state["assets"], binding, canonicalize)
                    return candidate

                result = extract_with_retry(llm=llm, prompt_template=prompt, schema_class=ThreatBatchResult,
                    sample_input=json.dumps(material, ensure_ascii=False, separators=(",", ":")),
                    semantic_validator=validate, task_label=f"node3/{batch_id}", max_retries=2,
                    retry_request_errors=False)
            entries = _resolve_batch(result, by_block, state["assets"], binding, canonicalize)
            _save_batch(path, inputs, result)
            record.update(status="reused" if reused else "succeeded", candidate_count=len(entries),
                          fingerprint=_hash(inputs), notes=result.notes)
            resolved.append((batch_id, entries))
            verdicts.append(result.assessment)
            notes.append(f"{label}：{result.notes or '候选场景待人工复核。'}")
            _write(index_path, index)
        except Exception as exc:
            record.update(status="failed", error_type=type(exc).__name__)
            index["status"] = "failed"
            _write(index_path, index)
            raise RuntimeError(f"Node3 batch {batch_id} failed; successful batches remain saved for reuse. {exc}") from exc
    threats, sources = _merge(resolved)
    if not threats:
        index["status"] = "failed"
        _write(index_path, index)
        raise ValueError("All perspectives returned no candidate threats; inspect applicability notes before proceeding")
    missing_evidence = [t.threat_id for t in threats if not t.evidence]
    if missing_evidence:
        notes.append("以下候选没有场景级原文引用，依据和前提需确认：" + ", ".join(missing_evidence))
    notes.append("仅合并分析内容完全相同的条目；条件或链条不同的场景保留，近似重叠需人工复核，勿重复计算影响。")
    result = canonicalize(ThreatIdentificationResult(threats=threats,
        assessment=AssessmentVerdict.FAIL if AssessmentVerdict.FAIL in verdicts else AssessmentVerdict.PARTIAL,
        notes="\n".join(notes)), state["assets"])
    index.update(status="completed", scenario_sources=sources, final_threat_count=len(result.threats))
    _write(index_path, index)
    return result
