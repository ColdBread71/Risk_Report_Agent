import json
from hashlib import sha256
from pathlib import Path

from openpyxl import load_workbook
import pytest

from core.exporter import (
    export_asset_review,
    export_workflow_progress,
    validate_asset_review_artifacts,
)
from core.run_manifest import (
    load_stage_upstream,
    prepare_stage_manifest,
    record_stage_result,
)
from nodes.asset_threat_modeler import _repair_asset_business_rules
from schemas.common import AssessmentVerdict
from schemas.legal import ScopeStatement, ProductClassification
from schemas.methodology import RiskMethodology
from schemas.product import Asset, ProductContext
from schemas.risk import RiskAcceptanceCriteria
from schemas.run_input import EvidencePacketRef


def test_compact_progress_keeps_upstream_on_failure(tmp_path):
    scope = ScopeStatement(product_name="示例", classification=ProductClassification(is_pde=True), scope_description="测试范围")
    state = {"scope": scope, "status": "node_0_completed", "errors": []}
    export_workflow_progress(state, tmp_path, "v1", "define_scope")
    state.update(status="node_1_failed", errors=["transport failed"])
    export_workflow_progress(state, tmp_path, "v1", "build_product_context")
    assert {p.name for p in tmp_path.iterdir()} == {"report.json", "report.xlsx"}
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert payload["state"]["scope"]["product_name"] == "示例"
    assert payload["state"]["errors"] == ["transport failed"]


def test_staged_progress_uses_node_name_and_preserves_report(tmp_path):
    (tmp_path / "report.json").write_text("baseline", encoding="utf-8")
    scope = ScopeStatement(
        product_name="示例",
        classification=ProductClassification(is_pde=True),
        scope_description="测试范围",
    )
    export_workflow_progress(
        {"scope": scope, "status": "node_0_completed", "errors": []},
        tmp_path,
        "v6",
        "define_scope",
        artifact_stem="node0",
    )
    assert (tmp_path / "report.json").read_text(encoding="utf-8") == "baseline"
    assert (tmp_path / "node0.json").is_file()
    assert (tmp_path / "node0.xlsx").is_file()


def test_stage_manifest_binds_same_directory_upstream_by_hash(tmp_path):
    packet_ref = {"packet_sha256": "a" * 64}
    (tmp_path / "report.json").write_text("baseline-report", encoding="utf-8")
    (tmp_path / "run_manifest.json").write_text("baseline-manifest", encoding="utf-8")
    prepare_stage_manifest(
        run_directory=tmp_path,
        run_id="v6",
        project_id="project",
        evidence_packet_ref=packet_ref,
        text_model="qwen-plus",
        node_id="0",
        rule_versions={"scope": "v1"},
        provenance={"source_sha256": {"main.py": "b" * 64}},
    )
    assert (tmp_path / "report.json").read_text(encoding="utf-8") == "baseline-report"
    assert (tmp_path / "run_manifest.json").read_text(encoding="utf-8") == "baseline-manifest"
    state = {
        "evidence_packet_ref": packet_ref,
        "scope": ScopeStatement(
            product_name="示例",
            classification=ProductClassification(is_pde=True),
            scope_description="测试范围",
        ),
        "status": "node_0_completed",
        "errors": [],
    }
    export_workflow_progress(state, tmp_path, "v6", "define_scope", artifact_stem="node0")
    record_stage_result(
        run_directory=tmp_path,
        node_id="0",
        status="node_0_completed",
        completed_node="define_scope",
    )
    loaded, pointer = load_stage_upstream(
        run_directory=tmp_path,
        upstream_node_id="0",
        expected_packet_sha256="a" * 64,
    )
    assert loaded["scope"]["product_name"] == "示例"
    assert pointer["output_json"] == "node0.json"

    (tmp_path / "node0.json").write_text("{}", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="hash"):
        load_stage_upstream(
            run_directory=tmp_path,
            upstream_node_id="0",
            expected_packet_sha256="a" * 64,
        )


def test_repeated_stage_attempts_use_suffix_and_latest_successful_upstream(tmp_path):
    packet_ref = {
        "packet_id": "test_packet",
        "packet_version": 1,
        "project_id": "project",
        "packet_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "config_sha256": "c" * 64,
        "parser_name": "test-parser",
        "parser_version": "1.0",
        "document_ids": ["DOC-AAAAAAAAAAAA"],
        "block_count": 1,
    }
    common = {
        "run_directory": tmp_path,
        "run_id": "v6",
        "project_id": "project",
        "evidence_packet_ref": packet_ref,
        "text_model": "qwen-plus",
        "node_id": "0",
        "rule_versions": {"scope": "v6.1"},
    }
    state = {
        "evidence_packet_ref": packet_ref,
        "scope": ScopeStatement(
            product_name="第一次结果",
            classification=ProductClassification(is_pde=None),
            scope_description="测试范围",
        ),
        "status": "node_0_completed",
        "errors": [],
    }

    _, first_attempt = prepare_stage_manifest(**common)
    assert first_attempt == "node0"
    export_workflow_progress(
        state, tmp_path, "v6", "define_scope", artifact_stem=first_attempt
    )
    record_stage_result(
        run_directory=tmp_path,
        node_id="0",
        status="node_0_completed",
        completed_node="define_scope",
        attempt_id=first_attempt,
    )
    first_bytes = (tmp_path / "node0.json").read_bytes()

    _, second_attempt = prepare_stage_manifest(**common)
    assert second_attempt == "node0_1"
    while_prepared, pointer = load_stage_upstream(
        run_directory=tmp_path,
        upstream_node_id="0",
        expected_packet_sha256="a" * 64,
    )
    assert pointer["attempt_id"] == "node0"
    assert while_prepared["scope"]["product_name"] == "第一次结果"

    state["scope"] = ScopeStatement(
        product_name="第二次结果",
        classification=ProductClassification(is_pde=None),
        scope_description="测试范围",
        review_notes=["这只是生成过程备注，不是产品事实"],
    )
    export_workflow_progress(
        state, tmp_path, "v6", "define_scope", artifact_stem=second_attempt
    )
    record_stage_result(
        run_directory=tmp_path,
        node_id="0",
        status="node_0_completed",
        completed_node="define_scope",
        attempt_id=second_attempt,
    )

    loaded, pointer = load_stage_upstream(
        run_directory=tmp_path,
        upstream_node_id="0",
        expected_packet_sha256="a" * 64,
    )
    manifest = json.loads((tmp_path / "stage_manifest.json").read_text(encoding="utf-8"))
    assert (tmp_path / "node0.json").read_bytes() == first_bytes
    assert (tmp_path / "node0_1.json").is_file()
    assert loaded["scope"]["product_name"] == "第二次结果"
    assert pointer["attempt_id"] == "node0_1"
    assert pointer["downstream_status"] == "draft_eligible"
    assert pointer["business_reviewed"] is False
    assert manifest["stages"]["node_0"]["selected_attempt"] == "node0_1"
    assert len(manifest["stages"]["node_0"]["attempts"]) == 2

    import main

    downstream_state, _ = main._single_node_input(
        node_id="1",
        run_output_dir=tmp_path,
        packet_sha256="a" * 64,
    )
    assert downstream_state["scope"].review_notes == []


def test_failed_retry_does_not_replace_last_successful_upstream(tmp_path):
    packet_ref = {"packet_sha256": "a" * 64}
    common = {
        "run_directory": tmp_path,
        "run_id": "v6",
        "project_id": "project",
        "evidence_packet_ref": packet_ref,
        "text_model": "qwen-plus",
        "node_id": "0",
        "rule_versions": {"scope": "v6.1"},
    }
    state = {
        "evidence_packet_ref": packet_ref,
        "scope": ScopeStatement(
            product_name="有效结果",
            classification=ProductClassification(is_pde=None),
            scope_description="测试范围",
        ),
        "status": "node_0_completed",
        "errors": [],
    }
    _, first_attempt = prepare_stage_manifest(**common)
    export_workflow_progress(state, tmp_path, "v6", "define_scope", artifact_stem=first_attempt)
    record_stage_result(
        run_directory=tmp_path,
        node_id="0",
        status="node_0_completed",
        completed_node="define_scope",
        attempt_id=first_attempt,
    )

    _, retry_attempt = prepare_stage_manifest(**common)
    state.update(status="node_0_failed", errors=["offline failure"])
    export_workflow_progress(state, tmp_path, "v6", "define_scope", artifact_stem=retry_attempt)
    record_stage_result(
        run_directory=tmp_path,
        node_id="0",
        status="node_0_failed",
        completed_node="define_scope",
        attempt_id=retry_attempt,
    )
    loaded, pointer = load_stage_upstream(
        run_directory=tmp_path,
        upstream_node_id="0",
        expected_packet_sha256="a" * 64,
    )
    assert retry_attempt == "node0_1"
    assert pointer["attempt_id"] == "node0"
    assert loaded["scope"]["product_name"] == "有效结果"


def test_partial_node2_draft_is_selected_as_reviewable_stage_result(tmp_path):
    packet_ref = {"packet_sha256": "a" * 64}
    _, attempt_id = prepare_stage_manifest(
        run_directory=tmp_path,
        run_id="v7",
        project_id="project",
        evidence_packet_ref=packet_ref,
        text_model="qwen-plus",
        node_id="2",
        rule_versions={"asset": "v2.6"},
    )
    (tmp_path / f"{attempt_id}.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"{attempt_id}.xlsx").write_bytes(b"reviewable")

    record_stage_result(
        run_directory=tmp_path,
        node_id="2",
        status="asset_identification_partial_draft",
        completed_node="identify_assets",
        attempt_id=attempt_id,
    )

    manifest = json.loads((tmp_path / "stage_manifest.json").read_text(encoding="utf-8"))
    group = manifest["stages"]["node_2"]
    assert group["selected_attempt"] == attempt_id
    assert group["downstream_status"] == "draft_eligible"
    assert group["attempts"][0]["downstream_usable"] is True


def test_existing_v1_stage_manifest_migrates_before_retry(tmp_path):
    packet_ref = {"packet_sha256": "a" * 64}
    state = {
        "evidence_packet_ref": packet_ref,
        "scope": ScopeStatement(
            product_name="旧版结果",
            classification=ProductClassification(is_pde=None),
            scope_description="测试范围",
        ),
        "status": "node_0_completed",
        "errors": [],
    }
    export_workflow_progress(state, tmp_path, "v6", "define_scope", artifact_stem="node0")
    old_manifest = {
        "schema_version": "staged_node_run_manifest.v1",
        "run_id": "v6",
        "project_id": "project",
        "created_at": "2026-09-14T00:00:00+00:00",
        "updated_at": "2026-09-14T00:00:00+00:00",
        "evidence_packet_ref": packet_ref,
        "stages": {
            "node_0": {
                "status": "node_0_completed",
                "generated_at": "2026-09-14T00:00:00+00:00",
                "output_json": "node0.json",
                "output_excel": "node0.xlsx",
                "output_json_sha256": sha256((tmp_path / "node0.json").read_bytes()).hexdigest(),
                "output_excel_sha256": sha256((tmp_path / "node0.xlsx").read_bytes()).hexdigest(),
            }
        },
    }
    (tmp_path / "stage_manifest.json").write_text(
        json.dumps(old_manifest), encoding="utf-8"
    )

    _, attempt_id = prepare_stage_manifest(
        run_directory=tmp_path,
        run_id="v6",
        project_id="project",
        evidence_packet_ref=packet_ref,
        text_model="qwen-plus",
        node_id="0",
        rule_versions={"scope": "v6.1"},
    )
    loaded, pointer = load_stage_upstream(
        run_directory=tmp_path,
        upstream_node_id="0",
        expected_packet_sha256="a" * 64,
    )
    migrated = json.loads((tmp_path / "stage_manifest.json").read_text(encoding="utf-8"))
    assert attempt_id == "node0_1"
    assert loaded["scope"]["product_name"] == "旧版结果"
    assert pointer["attempt_id"] == "node0"
    assert migrated["schema_version"] == "staged_node_run_manifest.v2"
    assert len(migrated["stages"]["node_0"]["attempts"]) == 2


def test_full_cli_records_identity_and_does_not_overwrite(tmp_path, monkeypatch):
    import main
    from pathlib import Path

    class OfflineGraph:
        def stream(self, *args, **kwargs):
            yield {"define_scope": {"status": "node_0_failed", "errors": ["offline failure"]}}

    monkeypatch.setattr(main, "tara_graph", OfflineGraph())
    root = Path(__file__).resolve().parents[1]
    args = ["--mode", "assets", "--evidence-packet", str(root / "project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json"), "--output-dir", str(tmp_path), "--run-id", "offline-test"]
    assert main.main(args) == 1
    destination = tmp_path / "offline-test"
    assert {p.name for p in destination.iterdir()} == {"report.json", "report.xlsx", "run_manifest.json"}
    manifest = json.loads((destination / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["requested_node"] == "0-2"
    assert manifest["status"] == "node_0_failed"
    assert "main.py" in manifest["provenance"]["source_sha256"]
    before = (destination / "run_manifest.json").read_bytes()
    assert main.main(args) == 1
    assert before == (destination / "run_manifest.json").read_bytes()


def test_failed_full_run_cache_reuse_requires_matching_identity(tmp_path):
    import main

    workspace = tmp_path / "workspace"
    output_directory = tmp_path / "output"
    source_run = "failed-v8"
    project_id = "project"
    packet_sha256 = "a" * 64
    source_output = output_directory / source_run
    source_output.mkdir(parents=True)
    (source_output / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "node_run_manifest.v1",
                "run_id": source_run,
                "project_id": project_id,
                "requested_node": "0-2",
                "status": "node_1_failed",
                "evidence_packet_ref": {"packet_sha256": packet_sha256},
            }
        ),
        encoding="utf-8",
    )
    cache_path = (
        workspace
        / "project_artifacts"
        / project_id
        / "runs"
        / source_run
        / "field_facts"
    )
    cache_path.mkdir(parents=True)

    assert main._failed_run_field_cache(
        source_run_id=source_run,
        target_run_id="retry-v9",
        output_directory=output_directory,
        workspace=workspace,
        project_id=project_id,
        packet_sha256=packet_sha256,
        requested_node="0-2",
    ) == cache_path

    with pytest.raises(ValueError, match="证据包不一致"):
        main._failed_run_field_cache(
            source_run_id=source_run,
            target_run_id="retry-v9",
            output_directory=output_directory,
            workspace=workspace,
            project_id=project_id,
            packet_sha256="b" * 64,
            requested_node="0-2",
        )


def test_asset_review_export_is_self_auditing_and_json_excel_consistent(tmp_path):
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads(
        (root / "output/emu-node012-v6/node2_4.json").read_text(encoding="utf-8")
    )
    raw_identification = fixture["asset_identification"]
    repaired_assets = [
        _repair_asset_business_rules(Asset.model_validate(item))[0]
        for item in raw_identification["assets"]
    ]
    state = {
        "evidence_packet_ref": EvidencePacketRef.model_validate(
            fixture["evidence_packet_ref"]
        ),
        "scope": ScopeStatement.model_validate(fixture["scope"]),
        "product_context": ProductContext.model_validate(fixture["product_context"]),
        "risk_methodology": RiskMethodology.model_validate(
            fixture["risk_methodology"]
        ),
        "risk_acceptance_criteria": RiskAcceptanceCriteria.model_validate(
            fixture["risk_acceptance_criteria"]
        ),
        "assets": repaired_assets,
        "asset_assessment": AssessmentVerdict.PARTIAL,
        "asset_notes": "离线集成测试。",
        "asset_review_approved": False,
        "threat_assessment": None,
        "current_step": "node_2_asset_review",
        "status": "asset_identification_partial_draft",
        "errors": [],
    }

    json_path, excel_path = export_asset_review(
        state,
        tmp_path,
        "integration-test",
        artifact_stem="report",
    )
    summary = validate_asset_review_artifacts(json_path, excel_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert summary["asset_count"] == len(repaired_assets)
    assert summary["objective_count"] == sum(
        len(asset.related_objectives) for asset in repaired_assets
    )
    assert payload["review_summary"] == summary
    assert payload["workflow_status"] == "asset_identification_partial_draft"

    inconsistent_state = dict(state)
    inconsistent_state["status"] = "asset_identification_completed"
    with pytest.raises(ValueError, match="consistent reviewable"):
        export_asset_review(
            inconsistent_state,
            tmp_path,
            "integration-test",
            artifact_stem="node2_99",
        )

    mismatched_payload = dict(payload)
    mismatched_payload["workflow_status"] = "asset_identification_completed"
    mismatched_json = tmp_path / "mismatched.json"
    mismatched_json.write_text(
        json.dumps(mismatched_payload, ensure_ascii=False), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="does not match"):
        validate_asset_review_artifacts(mismatched_json, excel_path)

    workbook = load_workbook(excel_path)
    workbook["Node2 资产与目标"]["K4"] = "错误目标列"
    workbook.save(excel_path)
    workbook.close()
    with pytest.raises(ValueError, match="headers"):
        validate_asset_review_artifacts(json_path, excel_path)
