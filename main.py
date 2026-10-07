"""Command-line entry point for the Node [0]-[3] workflow slice."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
import re
from pathlib import Path
from typing import Sequence
from uuid import uuid4

from langgraph.types import Command

from core.exporter import export_asset_review, export_tara_report, export_workflow_progress
from core.logger import setup_logger
from core.run_manifest import (
    initialize_run_manifest,
    load_stage_upstream,
    prepare_stage_manifest,
    record_run_status,
    record_stage_result,
    record_stage_status,
)
from core.workflow_status import ASSET_REVIEWABLE_STATUSES
from core.workflow import node0_graph, node1_graph, node2_graph, tara_graph
from nodes.asset_threat_modeler import ASSET_RULE_VERSION
from nodes.context_builder import CONTEXT_RULE_VERSION, SCOPE_RULE_VERSION
from nodes.field_extractor import FIELD_FACT_PROMPT_VERSION
from schemas.legal import ScopeStatement
from schemas.methodology import RiskMethodology
from schemas.product import ProductContext
from schemas.risk import RiskAcceptanceCriteria
from schemas.run_input import EvidencePacketRef
from tools.evidence_input import load_evidence_packet
from tools.retrieval_profiles import PROFILE_VERSION


logger = setup_logger("main")
PROJECT_ROOT = Path(__file__).resolve().parent


def _build_parser() -> argparse.ArgumentParser:
    """Define explicit inputs and execution boundaries for one workflow run."""
    parser = argparse.ArgumentParser(description="Run the CRA/TARA workflow.")
    parser.add_argument(
        "--mode",
        choices=("assets", "full"),
        default="assets",
        help="assets stops at Node [2]; full may continue to Node [3] after approval.",
    )
    parser.add_argument(
        "--node",
        choices=("0", "1", "2"),
        help=(
            "Run only one business node. Repeated runs create node0_1/node0_2 etc. "
            "Node 1/2 use the selected successful upstream attempt in the same run-id directory."
        ),
    )
    parser.add_argument(
        "--evidence-packet",
        required=True,
        help="Path to a validated evidence-packet JSON file.",
    )
    parser.add_argument(
        "--workspace",
        default=str(PROJECT_ROOT),
        help="Workspace used to resolve packet, manifest, and source paths.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "output"),
        help="Base directory for run-specific outputs.",
    )
    parser.add_argument(
        "--run-id",
        help=(
            "Version ID. Full runs require a new ID; staged node runs append distinct "
            "node0/node1/node2 artifacts without overwriting existing results."
        ),
    )
    parser.add_argument(
        "--rag-index",
        help=(
            "Optional persisted FAISS index directory. When supplied, Node [0]-[2] "
            "use field retrieval and partial fact extraction instead of the full packet prompt."
        ),
    )
    parser.add_argument(
        "--cache-policy",
        choices=("reuse", "refresh"),
        default="reuse",
        help=(
            "reuse only matching field fingerprints; refresh regenerates every field "
            "in the requested node/workflow run."
        ),
    )
    parser.add_argument(
        "--reuse-failed-run",
        help=(
            "Reuse only fingerprint-matching field checkpoints from a failed full run. "
            "The source output remains unchanged and the new run still requires a new --run-id."
        ),
    )
    return parser


def _resume_asset_review(result: dict, config: dict) -> dict:
    """Collect the mandatory step [2] asset decision in the full CLI mode."""
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return result

    assets = result.get("assets", [])
    logger.info("Node [2] 等待人工确认，共 %d 项资产", len(assets))
    asset_assessment = result.get("asset_assessment")
    assessment_text = getattr(asset_assessment, "value", asset_assessment)
    logger.info("资产识别评估: %s", assessment_text)
    logger.info("资产识别说明: %s", result.get("asset_notes") or "无")
    for asset in assets:
        logger.info(
            "待确认资产 %s: %s | 类型=%s | 位置=%s | 价值=%s",
            asset.asset_id,
            asset.name,
            asset.asset_type,
            asset.location or "未知",
            asset.value or "未知",
        )
        logger.info("资产描述: %s", asset.description)
        for objective in asset.related_objectives:
            logger.info(
                "  目标 %s [%s | basis=%s | status=%s]: %s",
                objective.objective_id,
                objective.category,
                objective.basis,
                objective.status,
                objective.description,
            )

    try:
        answer = input(
            "Type APPROVE to confirm the complete Node [2] asset inventory: "
        ).strip()
        approved = answer == "APPROVE"
        notes = input("Review notes (optional): ").strip() or None
    except EOFError:
        logger.warning("当前终端不可交互；工作流保持在 Node [2] 人工确认点")
        return result

    return tara_graph.invoke(
        Command(resume={"approved": approved, "notes": notes}),
        config=config,
    )


def _log_result(result: dict) -> None:
    """Log a compact summary without serializing source material."""
    logger.info("当前状态: %s", result.get("status"))
    for error in result.get("errors", []):
        logger.error("捕获到的错误: %s", error)

    scope = result.get("scope")
    product_context = result.get("product_context")
    logger.info("Node 0 Scope 产品名: %s", scope.product_name if scope else None)
    logger.info("Node 1 Context 产品名: %s", product_context.product_name if product_context else None)
    logger.info("Node 2 识别资产数: %d", len(result.get("assets", [])))
    threat_assessment = result.get("threat_assessment")
    logger.info("Node 3 识别威胁数: %d", len(threat_assessment.threats) if threat_assessment else 0)


def _run_with_progress(
    graph,
    initial_state: dict,
    config: dict,
    run_output_dir: Path,
    run_id: str,
    artifact_stem: str = "report",
    staged_node_id: str | None = None,
    staged_attempt_id: str | None = None,
) -> dict:
    """Stream graph updates and persist every completed or failed business node."""
    result: dict = dict(initial_state)
    result.setdefault("errors", [])
    interrupts = []
    for update in graph.stream(initial_state, config=config, stream_mode="updates"):
        if "__interrupt__" in update:
            interrupts = update["__interrupt__"]
            completed_node = None
        else:
            completed_node = next(iter(update), None)
            node_update = update.get(completed_node, {}) if completed_node else {}
            if isinstance(node_update, dict):
                result.update(node_update)
        if interrupts:
            result["__interrupt__"] = interrupts
        try:
            export_workflow_progress(
                result,
                run_output_dir,
                run_id,
                completed_node,
                artifact_stem=artifact_stem,
            )
            if staged_node_id is None:
                record_run_status(
                    run_output_dir,
                    str(result.get("status", "unknown")),
                    bool(interrupts),
                )
            else:
                record_stage_status(
                    run_output_dir,
                    staged_node_id,
                    str(result.get("status", "unknown")),
                    bool(interrupts),
                    attempt_id=staged_attempt_id,
                )
        except Exception as exc:
            logger.exception(
                "进度 Excel/快照写入失败，但工作流继续执行；请确认输出文件未被占用: %s",
                exc,
            )
    return result


def _single_node_input(
    *,
    node_id: str,
    run_output_dir: Path,
    packet_sha256: str,
) -> tuple[dict, dict]:
    """Build typed state from the exact preceding artifact in this version directory."""
    if node_id == "0":
        return {"errors": []}, {}

    upstream_id = "0" if node_id == "1" else "1"
    raw, pointer = load_stage_upstream(
        run_directory=run_output_dir,
        upstream_node_id=upstream_id,
        expected_packet_sha256=packet_sha256,
    )
    scope = ScopeStatement.model_validate(raw["scope"])
    state = {
        "errors": list(raw.get("errors", [])),
        "evidence_packet_ref": EvidencePacketRef.model_validate(raw["evidence_packet_ref"]),
        # Review notes explain how one artifact was generated. They are not product facts
        # and must not influence later context or asset extraction.
        "scope": scope.model_copy(update={"review_notes": []}),
    }
    if node_id == "2":
        state.update(
            {
                "product_context": ProductContext.model_validate(raw["product_context"]),
                "risk_methodology": RiskMethodology.model_validate(raw["risk_methodology"]),
                "risk_acceptance_criteria": RiskAcceptanceCriteria.model_validate(
                    raw["risk_acceptance_criteria"]
                ),
            }
        )
    return state, {f"node_{upstream_id}": pointer}


def _configured_text_model() -> str:
    return os.getenv(
        "DASHSCOPE_TEXT_MODEL",
        os.getenv("DASHSCOPE_MODEL", os.getenv("OPENAI_MODEL", "qwen-max")),
    )


def _run_provenance(args) -> dict:
    """Fingerprint generation code without copying secrets or customer input."""
    files = [PROJECT_ROOT / "main.py", PROJECT_ROOT / "requirements.txt", PROJECT_ROOT / "CRA_TARA_workflow_prEN40000.md"]
    for directory in ("core", "nodes", "schemas", "tools", "prompts"):
        files.extend(path for path in (PROJECT_ROOT / directory).rglob("*") if path.suffix in {".py", ".md"})
    return {
        "source_sha256": {str(path.relative_to(PROJECT_ROOT)): sha256(path.read_bytes()).hexdigest() for path in sorted(files)},
        "rag_index": str(Path(args.rag_index).resolve()) if args.rag_index else None,
        "mode": args.mode,
        "cache_policy": args.cache_policy,
        "reused_failed_run": args.reuse_failed_run,
    }


def _failed_run_field_cache(
    *,
    source_run_id: str,
    target_run_id: str,
    output_directory: Path,
    workspace: Path,
    project_id: str,
    packet_sha256: str,
    requested_node: str,
) -> Path:
    """Validate a failed full run before exposing its field cache read-only."""
    if source_run_id == target_run_id:
        raise ValueError("失败运行复用必须使用新的 --run-id")
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source_run_id) is None:
        raise ValueError("--reuse-failed-run 包含非法运行编号")
    manifest_path = output_directory / source_run_id / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"失败运行清单不存在: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    allowed_statuses = {
        "node_0_failed",
        "node_1_failed",
        "asset_identification_failed",
        "asset_identification_technical_incomplete",
    }
    if payload.get("status") not in allowed_statuses:
        raise ValueError("只能复用明确失败或技术不完整的整轮运行")
    if payload.get("project_id") != project_id:
        raise ValueError("失败运行与当前项目不一致")
    source_packet = payload.get("evidence_packet_ref", {}).get("packet_sha256")
    if source_packet != packet_sha256:
        raise ValueError("失败运行与当前证据包不一致")
    if payload.get("requested_node") != requested_node:
        raise ValueError("失败运行与当前运行模式不一致")
    cache_path = (
        workspace
        / "project_artifacts"
        / project_id
        / "runs"
        / source_run_id
        / "field_facts"
    )
    if not cache_path.is_dir():
        raise ValueError(f"失败运行没有可复用字段检查点: {cache_path}")
    return cache_path


def main(argv: Sequence[str] | None = None) -> int:
    """Run to the selected boundary and export only validated results."""
    args = _build_parser().parse_args(argv)
    run_id = args.run_id or uuid4().hex
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id) is None:
        logger.error("run_id 只能包含字母、数字、下划线和连字符，最长 64 字符")
        return 1
    workspace = Path(args.workspace).resolve()
    try:
        evidence_binding = load_evidence_packet(
            args.evidence_packet,
            workspace=workspace,
            verify_source_files=True,
        )
    except Exception as exc:
        logger.error("证据包加载失败: %s", exc)
        return 1
    output_directory = Path(args.output_dir).resolve()
    run_output_dir = output_directory / run_id
    base_cache_dir = workspace / "project_artifacts" / evidence_binding.packet.project_id / "runs" / run_id
    cache_dir = (
        base_cache_dir / "stages" / f"node_{args.node}"
        if args.node is not None
        else base_cache_dir
    )
    if args.node is None and (run_output_dir.exists() or cache_dir.exists()):
        logger.error("运行编号已使用，请选择新的 --run-id: %s", run_id)
        return 1
    if args.reuse_failed_run and args.node is not None:
        logger.error("--reuse-failed-run 只适用于整轮运行")
        return 1
    if args.reuse_failed_run and args.cache_policy == "refresh":
        logger.error("--reuse-failed-run 需要 --cache-policy reuse")
        return 1
    config = {
        "configurable": {
            "thread_id": run_id,
            "evidence_packet_path": args.evidence_packet,
            "workspace": str(workspace),
            "field_checkpoint_dir": str(cache_dir / "field_facts"),
            "field_cache_policy": args.cache_policy,
            "context_section_checkpoint_dir": str(cache_dir / "context_sections"),
            "context_section_cache_policy": args.cache_policy,
            "asset_section_checkpoint_dir": str(cache_dir / "asset_sections"),
            "asset_section_cache_policy": args.cache_policy,
        }
    }
    if args.rag_index:
        config["configurable"]["rag_index_dir"] = str(Path(args.rag_index).resolve())
    if args.reuse_failed_run:
        try:
            fallback_cache = _failed_run_field_cache(
                source_run_id=args.reuse_failed_run,
                target_run_id=run_id,
                output_directory=output_directory,
                workspace=workspace,
                project_id=evidence_binding.packet.project_id,
                packet_sha256=evidence_binding.reference.packet_sha256,
                requested_node="0-2" if args.mode == "assets" else "0-3",
            )
        except Exception as exc:
            logger.error("失败运行检查点复用准备失败: %s", exc)
            return 1
        config["configurable"]["field_checkpoint_fallback_dir"] = str(
            fallback_cache
        )
        logger.info(
            "本次只读复用失败运行 %s 中指纹匹配的字段检查点",
            args.reuse_failed_run,
        )

    if args.node is not None:
        try:
            initial_state, upstream = _single_node_input(
                node_id=args.node,
                run_output_dir=run_output_dir,
                packet_sha256=evidence_binding.reference.packet_sha256,
            )
            _, attempt_id = prepare_stage_manifest(
                run_directory=run_output_dir,
                run_id=run_id,
                project_id=evidence_binding.packet.project_id,
                evidence_packet_ref=evidence_binding.reference.model_dump(mode="json"),
                text_model=_configured_text_model(),
                node_id=args.node,
                rule_versions={
                    "scope": SCOPE_RULE_VERSION,
                    "context": CONTEXT_RULE_VERSION,
                    "retrieval_profile": PROFILE_VERSION,
                    "field_fact_prompt": FIELD_FACT_PROMPT_VERSION,
                    "asset": ASSET_RULE_VERSION,
                },
                upstream=upstream,
                provenance=_run_provenance(args),
            )
            config["configurable"]["thread_id"] = f"{run_id}:{attempt_id}"
        except Exception as exc:
            logger.error("单节点运行准备失败: %s", exc)
            return 1
        graph = {"0": node0_graph, "1": node1_graph, "2": node2_graph}[args.node]
        completed_name = {"0": "define_scope", "1": "build_product_context", "2": "identify_assets"}[
            args.node
        ]
        accepted_statuses = {
            "0": frozenset({"node_0_completed"}),
            "1": frozenset({"node_1_completed"}),
            "2": ASSET_REVIEWABLE_STATUSES,
        }[args.node]
        logger.info(
            "启动单节点运行，node=%s，run_id=%s，attempt=%s，cache_policy=%s",
            args.node,
            run_id,
            attempt_id,
            args.cache_policy,
        )
        result = _run_with_progress(
            graph,
            initial_state,
            config,
            run_output_dir,
            run_id,
            artifact_stem=attempt_id,
            staged_node_id=args.node,
            staged_attempt_id=attempt_id,
        )
        status = str(result.get("status", "unknown"))
        if args.node == "2" and status in accepted_statuses:
            try:
                export_asset_review(
                    result,
                    run_output_dir,
                    run_id,
                    artifact_stem=attempt_id,
                )
            except Exception as exc:
                logger.error("Node [2] 审核包导出失败: %s", exc)
                return 1
        try:
            manifest_path = record_stage_result(
                run_directory=run_output_dir,
                node_id=args.node,
                status=status,
                completed_node=completed_name,
                attempt_id=attempt_id,
            )
        except Exception as exc:
            logger.error("运行清单写入失败: %s", exc)
            return 1
        _log_result(result)
        if status not in accepted_statuses:
            logger.error("Node %s 未完成，status=%s；清单=%s", args.node, status, manifest_path)
            return 1
        logger.info("Node %s JSON/Excel 已生成并记录于阶段清单: %s", args.node, manifest_path)
        return 0

    initialize_run_manifest(
        run_directory=run_output_dir,
        run_id=run_id,
        project_id=evidence_binding.packet.project_id,
        evidence_packet_ref=evidence_binding.reference.model_dump(mode="json"),
        text_model=_configured_text_model(),
        requested_node="0-2" if args.mode == "assets" else "0-3",
        rule_versions={"scope": SCOPE_RULE_VERSION, "context": CONTEXT_RULE_VERSION, "retrieval_profile": PROFILE_VERSION, "field_fact_prompt": FIELD_FACT_PROMPT_VERSION, "asset": ASSET_RULE_VERSION},
        provenance=_run_provenance(args),
    )
    logger.info("启动工作流，模式=%s，run_id=%s", args.mode, run_id)
    result = _run_with_progress(
        tara_graph,
        {"errors": []},
        config,
        run_output_dir,
        run_id,
    )
    _log_result(result)

    if args.mode == "assets":
        if not result.get("__interrupt__"):
            logger.error("资产模式未到达 Node [2] 人工确认点；不生成审核包")
            return 1
        try:
            json_path, excel_path = export_asset_review(result, run_output_dir, run_id)
        except Exception as exc:
            logger.error("Node [0]-[2] 审核包导出失败: %s", exc)
            return 1
        logger.info("JSON 审核结果: %s", json_path)
        logger.info("Excel 审核结果: %s", excel_path)
        logger.info("工作流保持在 Node [2]；未批准资产，未执行 Node [3]")
        return 0

    result = _resume_asset_review(result, config)
    _log_result(result)
    if result.get("status") != "threat_modeling_completed":
        logger.warning("工作流未完成 Node [3]，不导出完整报告")
        return 1

    report_path = run_output_dir / "tara_report.xlsx"
    export_tara_report(result, str(report_path))
    logger.info("Node [0]-[3] 报告已导出: %s", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
