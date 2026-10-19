"""Small, explicit development entry point for saved unreviewed Node [2] drafts."""

from hashlib import sha256
import json
from pathlib import Path
import re

from core.exporter import ASSET_REVIEW_SCHEMA_VERSION, PROGRESS_SCHEMA_VERSION, export_workflow_progress
from core.run_manifest import initialize_run_manifest, record_run_status
from core.workflow_status import is_asset_reviewable_state
from schemas.legal import ScopeStatement
from schemas.methodology import RiskMethodology
from schemas.product import AssetIdentificationResult, ProductContext
from schemas.risk import RiskAcceptanceCriteria
from schemas.run_input import EvidencePacketRef
from tools.evidence_input import validate_evidence_bindings


def load_node3_draft(source: Path, binding) -> dict:
    """Read existing review/progress contracts; never import an approval decision."""
    raw = json.loads(source.read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version == ASSET_REVIEW_SCHEMA_VERSION:
        if raw.get("awaiting_asset_approval") is not True:
            raise ValueError("Node3 draft input must be awaiting asset approval")
        data = raw
        inventory = data["asset_identification"]
        status = data.get("workflow_status")
    elif version == PROGRESS_SCHEMA_VERSION:
        data = raw["state"]
        if data.get("asset_review_approved") or data.get("threat_assessment") is not None:
            raise ValueError("Node3 draft input must precede approval and threat modelling")
        inventory = {"assets": data.get("assets"), "assessment": data.get("asset_assessment"), "notes": data.get("asset_notes")}
        status = data.get("status")
    else:
        raise ValueError("Expected a saved Node2 asset review or workflow progress JSON")
    assets = AssetIdentificationResult.model_validate(inventory)
    state = {
        "evidence_packet_ref": EvidencePacketRef.model_validate(data["evidence_packet_ref"]),
        "scope": ScopeStatement.model_validate(data["scope"]),
        "product_context": ProductContext.model_validate(data["product_context"]),
        "risk_methodology": RiskMethodology.model_validate(data["risk_methodology"]),
        "risk_acceptance_criteria": RiskAcceptanceCriteria.model_validate(data["risk_acceptance_criteria"]),
        "assets": assets.assets,
        "asset_assessment": assets.assessment,
        "asset_notes": assets.notes,
        "status": status,
        "asset_review_approved": False,
        "asset_review_notes": None,
        "threat_assessment": None,
        "errors": list(data.get("errors", [])),
    }
    if not is_asset_reviewable_state(state):
        raise ValueError("Node3 requires a nonempty, technically complete, reviewable Node2 draft")
    if state["evidence_packet_ref"] != binding.reference:
        raise ValueError("Node3 source evidence packet identity mismatch")
    validate_evidence_bindings(state, binding)
    return state


def run_node3_draft(*, args, binding, run_id, output_directory, config, provenance, text_model) -> int:
    """Persist source identity, diagnostics and draft output in a fresh run directory."""
    from core.workflow import node3_graph
    from nodes.asset_threat_modeler import THREAT_RULE_VERSION

    if not args.allow_unreviewed_draft or not args.upstream_report:
        raise ValueError("--node 3 requires --upstream-report and --allow-unreviewed-draft; formal approval remains in --mode full")
    if args.reuse_failed_run or args.rag_index or args.mode != "assets":
        raise ValueError("Saved Node3 drafts do not use --reuse-failed-run, --rag-index or --mode full")
    source = Path(args.upstream_report)
    if not source.is_absolute():
        source = Path(args.workspace) / source
    source = source.resolve()
    source_hash = sha256(source.read_bytes()).hexdigest()
    state = load_node3_draft(source, binding)
    destination = output_directory / run_id
    if destination.exists():
        raise ValueError("Node3 requires a new --run-id; source and previous results are read-only")
    config["configurable"]["allow_unreviewed_threat_draft"] = True
    config["configurable"]["node3_batch_dir"] = str(destination / "node3_batches")
    config["configurable"]["node3_source_sha256"] = source_hash
    if args.reuse_node3_batches:
        previous_id = args.reuse_node3_batches
        if previous_id == run_id or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", previous_id) is None:
            raise ValueError("Batch reuse requires a different valid source run-id")
        if args.cache_policy != "reuse":
            raise ValueError("Batch reuse cannot be combined with --cache-policy refresh")
        previous = output_directory / previous_id
        prior = json.loads((previous / "run_manifest.json").read_text(encoding="utf-8"))
        if not (
            prior.get("run_id") == previous_id
            and prior.get("requested_node") == "3"
            and prior.get("project_id") == binding.reference.project_id
            and prior.get("evidence_packet_ref") == binding.reference.model_dump(mode="json")
            and prior.get("text_model") == text_model
            and prior.get("rule_versions", {}).get("threat") == THREAT_RULE_VERSION
            and prior.get("upstream", {}).get("node_2", {}).get("sha256") == source_hash
        ):
            raise ValueError("Node3 reuse source identity/model/input/rule mismatch; no model calls made")
        if not (previous / "node3_batches").is_dir():
            raise ValueError("Source run has no Node3 batch checkpoints")
        config["configurable"]["node3_reuse_batch_dir"] = str(previous / "node3_batches")
    initialize_run_manifest(
        run_directory=destination, run_id=run_id,
        project_id=binding.reference.project_id,
        evidence_packet_ref=binding.reference.model_dump(mode="json"),
        text_model=text_model, requested_node="3",
        rule_versions={"threat": THREAT_RULE_VERSION},
        upstream={"node_2": {"path": str(source), "sha256": source_hash, "business_reviewed": False}},
        provenance={**provenance, "node3_reused_run": args.reuse_node3_batches,
                    "node3_read_timeout_seconds": 1800, "node3_sdk_max_retries": 0},
    )
    result = node3_graph.invoke(state, config=config)
    export_workflow_progress(result, destination, run_id, "model_threats")
    record_run_status(destination, result["status"], awaiting_review=True)
    # Record result digests as well as the exact source digest for later scoring runs.
    manifest_path = destination / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"] = {
        name: sha256((destination / name).read_bytes()).hexdigest()
        for name in ("report.json", "report.xlsx")
    }
    manifest["review_status"] = "unreviewed_draft"
    batch_directory = destination / "node3_batches"
    manifest["batch_artifacts"] = {
        str(path.relative_to(destination)).replace("\\", "/"): sha256(path.read_bytes()).hexdigest()
        for path in sorted(batch_directory.glob("*.json"))
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "threat_modeling_draft" else 1
