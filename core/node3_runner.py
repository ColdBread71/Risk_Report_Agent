"""Small, explicit development entry point for saved unreviewed Node [2] drafts."""

from hashlib import sha256
import json
from pathlib import Path

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
    initialize_run_manifest(
        run_directory=destination, run_id=run_id,
        project_id=binding.reference.project_id,
        evidence_packet_ref=binding.reference.model_dump(mode="json"),
        text_model=text_model, requested_node="3",
        rule_versions={"threat": THREAT_RULE_VERSION},
        upstream={"node_2": {"path": str(source), "sha256": source_hash, "business_reviewed": False}},
        provenance=provenance,
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
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "threat_modeling_draft" else 1
