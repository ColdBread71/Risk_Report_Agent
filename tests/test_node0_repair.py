import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.exporter import _build_progress_workbook, _scope_freeze_blockers
from core.run_manifest import initialize_run_manifest, mark_node_checked, record_node_result
from core.structured_extraction import extract_with_retry
from nodes.context_builder import _looks_like_heading_only, _validate_scope
from schemas.common import ConfidenceLevel, EvidenceLevel
from schemas.evidence import EvidenceRef, SourceRef
from schemas.legal import ProductClassification, ScopeStatement
from tools.evidence_input import (
    canonicalize_evidence_payload, canonicalize_evidence_from_upstream,
    load_evidence_packet, validate_evidence_ref, validate_evidence_subset,
    validate_evidence_block_subset,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = PROJECT_ROOT / "project_artifacts/yangguang_emu/evidence_packets/node_0_3_v1.json"


def _scope(**overrides) -> ScopeStatement:
    payload = {
        "product_name": "EMU300A",
        "classification": ProductClassification(is_pde=True, has_rdps=None),
        "scope_description": "评估 EMU300A 已确认组成，并保留配置待确认项。",
        "in_scope_components": ["EMU300A 整机", "Logger5000 数据采集器"],
        "conditional_scope_components": ["光纤环网交换机：选配，实际 BOM 待客户确认"],
        "out_of_scope_components": ["第三方南向设备本体：由集成边界另一方负责"],
        "assumptions": ["阳光云是否满足 CRA RDPS 必要性条件？"],
    }
    payload.update(overrides)
    return ScopeStatement.model_validate(payload)


def test_scope_supports_unknown_rdps_and_separate_conditional_items():
    scope = _scope()
    assert _validate_scope(scope, None) == scope

    workbook = _build_progress_workbook(
        {"scope": scope, "status": "node_0_completed", "errors": []},
        "node0-test",
        "define_scope",
        "2026-09-14T00:00:00+00:00",
    )
    sheet = workbook["Node0 范围定界"]
    values = {(row[1].value, row[2].value) for row in sheet.iter_rows(min_row=5)}
    assert ("是否包含远程数据处理方案（RDPS）", "待确认") in values
    assert any(label == "条件适用的组件、接口与服务" for label, _ in values)
    assert not any(label in {"评估结论", "结论说明"} for label, _ in values)


def test_unknown_legal_decisions_are_visible_as_freeze_blockers():
    scope = _scope(
        product_version=None,
        classification=ProductClassification(
            is_pde=None,
            classification=None,
            has_rdps=None,
            applicable_annex=None,
            overlapping_regulations=None,
        ),
        legal_basis=[],
    )
    blockers = _scope_freeze_blockers(scope)
    assert "CRA PDE适用性" in blockers
    assert "RED/MD及其他欧盟法规叠加" in blockers

    workbook = _build_progress_workbook(
        {"scope": scope, "status": "node_0_completed", "errors": []},
        "node0-test",
        "define_scope",
        "2026-09-14T00:00:00+00:00",
    )
    sheet = workbook["Node0 范围定界"]
    values = {(row[1].value, row[2].value) for row in sheet.iter_rows(min_row=5)}
    assert ("Node0 范围冻结状态", "未冻结（可继续生成资产草稿）") in values
    assert ("是否属于含数字元素产品（PDE）", "待确认") in values
    assert ("产品分类", "待法规/业务确认") in values
    assert ("可能叠加的其他法规", "待法规/业务确认") in values
    assert ("法律与标准依据", "待法规依据确认") in values


def test_scope_moves_conditional_item_out_of_confirmed_boundary():
    scope = _scope(
        in_scope_components=["EMU300A 整机", "NTS 对时功能（若启用）"],
        conditional_scope_components=[],
    )
    repaired = _validate_scope(scope, None)
    assert "NTS 对时功能（若启用）" not in repaired.in_scope_components
    assert "NTS 对时功能（若启用）" in repaired.conditional_scope_components
    assert repaired.review_notes


def test_scope_rdps_boundary_wording_does_not_trigger_generation_retry():
    scope = _scope(
        classification=ProductClassification(
            is_pde=True,
            has_rdps=True,
            rdps_description="阳光云被认定为产品功能所需的 RDPS。",
        ),
        conditional_scope_components=["阳光云 RDPS 及产品连接边界：合同配置待确认"],
        out_of_scope_components=["阳光云平台：不属于产品组成部分"],
    )
    assert _validate_scope(scope, None) == scope


def test_scope_downgrades_confirmed_rdps_wording_when_decision_is_unknown():
    scope = _scope(
        classification=ProductClassification(
            is_pde=None,
            has_rdps=None,
            rdps_description="材料中的远程数据处理方案已确认存在，但必要性待确认。",
        )
    )
    repaired = _validate_scope(scope, None)
    assert "远程数据处理方案已确认" not in repaired.classification.rdps_description
    assert repaired.classification.has_rdps is None
    assert any("RDPS 尚未判定" in item for item in repaired.review_notes)


def test_scope_downgrades_assumed_answer_and_removes_internal_identifiers():
    assumed = _scope(assumptions=["MPLC 与 PLC 为同一通信能力。"])
    repaired_assumed = _validate_scope(assumed, None)
    assert repaired_assumed.assumptions == ["请确认以下说法是否成立：MPLC 与 PLC 为同一通信能力？"]

    leaked = _scope(
        conditional_scope_components=["光纤交换机为选配，BOM 待确认（FACT-007）"]
    )
    repaired_leaked = _validate_scope(leaked, None)
    assert "FACT-007" not in repaired_leaked.conditional_scope_components[0]
    assert any("内部处理编号" in item for item in repaired_leaked.review_notes)

    generated_note = _scope(review_notes=["FACT-001 支撑范围判断"])
    repaired_note = _validate_scope(generated_note, None)
    assert all("FACT-001" not in item for item in repaired_note.review_notes)
    assert repaired_note.review_notes == ["已忽略模型生成的审阅备注；本栏只记录系统确定性降级。"]


def test_scope_moves_unknown_exclusion_to_conditional_scope():
    scope = _scope(out_of_scope_components=["Logger4000 适用性未确认，因此暂不纳入"])
    repaired = _validate_scope(scope, None)
    assert repaired.out_of_scope_components == []
    assert repaired.conditional_scope_components[-1].startswith("Logger4000")
    assert any("降级为条件范围" in item for item in repaired.review_notes)


def test_scope_removes_heading_only_evidence_without_failing_scope():
    evidence = EvidenceRef(
        evidence_id="EVD-HEADING",
        source=SourceRef(file_name="manual.pdf", file_path="manual.pdf", file_type="pdf"),
        quote="用户手册\n4 电气连接",
        evidence_level=EvidenceLevel.DIRECT,
        confidence=ConfidenceLevel.HIGH,
    )
    scope = _scope(evidence=[evidence])
    assert _looks_like_heading_only(evidence.quote)
    assert not _looks_like_heading_only("MODBUS/IEC104/GOOSE 协议默认关闭状态。")
    repaired = _validate_scope(scope, None)
    assert repaired.evidence == []
    assert any("低信息证据" in item for item in repaired.review_notes)


def test_scope_downgrades_cross_list_boundary_conflict_instead_of_picking_a_winner():
    scope = _scope(out_of_scope_components=["EMU300A 整机"])
    repaired = _validate_scope(scope, None)
    assert repaired.in_scope_components == ["Logger5000 数据采集器"]
    assert repaired.out_of_scope_components == []
    assert any("EMU300A 整机" in item for item in repaired.conditional_scope_components)
    assert any("跨范围状态冲突" in item for item in repaired.review_notes)


def test_scope_detects_same_object_with_different_status_explanations():
    scope = _scope(
        in_scope_components=["控制器X100：标准内置"],
        conditional_scope_components=["控制器X100：仅在订购选项中提供"],
        out_of_scope_components=[],
    )
    repaired = _validate_scope(scope, None)
    assert repaired.in_scope_components == []
    assert repaired.out_of_scope_components == []
    assert len(repaired.conditional_scope_components) == 1
    assert "范围分类冲突" in repaired.conditional_scope_components[0]
    assert "标准内置" in repaired.conditional_scope_components[0]
    assert "仅在订购选项中提供" in repaired.conditional_scope_components[0]


@pytest.mark.parametrize("included,excluded", [
    ("RS485通信接口（物理端口及协议栈）", "RS485通讯端子线缆（不随设备供货）"),
    ("控制器X100", "X100配套线缆"),
    ("X100（电源）", "X100（控制器）"),
])
def test_scope_keeps_different_objects_with_shared_identifiers(included, excluded):
    scope = _scope(in_scope_components=[included], conditional_scope_components=[],
                   out_of_scope_components=[excluded])
    repaired = _validate_scope(scope, None)
    assert repaired.in_scope_components == [included]
    assert repaired.out_of_scope_components == [excluded]
    assert repaired.conditional_scope_components == []


def test_scope_detects_same_object_despite_explicit_scope_annotation():
    scope = _scope(in_scope_components=["控制器X100（标准内置）"],
                   conditional_scope_components=[],
                   out_of_scope_components=["控制器X100：不在交付范围"])
    repaired = _validate_scope(scope, None)
    assert repaired.in_scope_components == repaired.out_of_scope_components == []
    assert len(repaired.conditional_scope_components) == 1
    assert "范围分类冲突" in repaired.conditional_scope_components[0]


def test_local_scope_quality_issue_does_not_trigger_llm_retry(monkeypatch):
    monkeypatch.setattr("core.structured_extraction.enforce_input_token_budget", lambda *_: 100)
    payload = _scope(
        out_of_scope_components=["Logger4000：适用性未确认（GAP-LOGGER4000-SCOPE）"]
    ).model_dump(mode="json")

    class FakeLlm:
        model_name = "offline-test-model"
        calls = 0

        def invoke(self, _prompt):
            self.calls += 1
            return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False))

    llm = FakeLlm()
    result = extract_with_retry(
        llm=llm,
        prompt_template="{json_schema}\n{sample_input}",
        schema_class=ScopeStatement,
        sample_input="{}",
        max_retries=2,
        semantic_validator=lambda value: _validate_scope(value, None),
    )
    assert llm.calls == 1
    assert result.out_of_scope_components == []
    assert result.conditional_scope_components[-1].startswith("Logger4000")


def test_canonical_evidence_fills_exact_block_text():
    binding = load_evidence_packet(
        PACKET_PATH,
        workspace=PROJECT_ROOT,
        verify_source_files=False,
    )
    block = next(iter(binding.blocks.values()))
    payload = {
        "evidence": [
            {
                "source": {"block_id": block.block_id},
                "quote": "模型改写的非逐字引文",
            }
        ]
    }
    result = canonicalize_evidence_payload(payload, binding)
    evidence = result["evidence"][0]
    assert evidence["quote"] == block.text.strip()
    assert "规范文本块原文" in evidence["notes"]


@pytest.mark.parametrize("claim", [True, "true", 1])
def test_model_cannot_claim_confirmation_while_valid_citation_survives(claim):
    binding = load_evidence_packet(PACKET_PATH, workspace=PROJECT_ROOT, verify_source_files=False)
    block = next(iter(binding.blocks.values()))
    raw = {"evidence": [{"evidence_id": "EVD-TEST", "source": {"block_id": block.block_id},
                         "quote": block.text.strip(), "is_human_confirmed": claim}]}
    canonical = canonicalize_evidence_payload(raw, binding)
    evidence = EvidenceRef.model_validate(canonical["evidence"][0])
    assert validate_evidence_ref(evidence, binding).is_human_confirmed is False
    assert evidence.evidence_id == "EVD-TEST"
    assert evidence.quote == block.text.strip()
    assert raw["evidence"][0]["is_human_confirmed"] == claim


@pytest.mark.parametrize("confirmed", [False, True])
def test_upstream_record_authority_is_preserved_without_trusting_model_flag(confirmed):
    binding = load_evidence_packet(PACKET_PATH, workspace=PROJECT_ROOT, verify_source_files=False)
    block = next(iter(binding.blocks.values()))
    canonical = canonicalize_evidence_payload({"evidence": [{
        "source": {"block_id": block.block_id}, "quote": block.text.strip(),
    }]}, binding)
    upstream = EvidenceRef.model_validate(canonical["evidence"][0])
    upstream.is_human_confirmed = confirmed
    upstream.notes = "Existing upstream record, not a model-written review."
    raw = upstream.model_dump(mode="json")
    raw.update(is_human_confirmed=not confirmed, notes="Model tries to replace review metadata")
    copied = canonicalize_evidence_from_upstream({"evidence": [raw]}, upstream)
    result = EvidenceRef.model_validate(copied["evidence"][0])
    assert result == upstream
    assert validate_evidence_ref(upstream, binding).is_human_confirmed is confirmed
    assert validate_evidence_subset(result, upstream) == result


def test_unknown_and_out_of_contract_child_references_still_rejected():
    binding = load_evidence_packet(PACKET_PATH, workspace=PROJECT_ROOT, verify_source_files=False)
    first, second = list(binding.blocks.values())[:2]
    raw = {"asset": {"name": "运行配置", "related_objectives": [{
        "objective_id": "OBJ-001", "evidence": [
            {"source": {"block_id": first.block_id}, "quote": first.text.strip()},
            {"source": {"block_id": second.block_id}, "quote": second.text.strip()},
            {"source": {"block_id": "BLK-0000000000000000"}, "quote": "fabricated"},
        ],
    }]}}
    repaired = canonicalize_evidence_payload(raw, binding, allowed_block_ids={first.block_id})
    child = repaired["asset"]["related_objectives"][0]
    assert repaired["asset"]["name"] == "运行配置" and child["objective_id"] == "OBJ-001"
    assert [e["source"]["block_id"] for e in child["evidence"]] == [first.block_id]
    evidence = EvidenceRef.model_validate(child["evidence"][0])
    with pytest.raises(ValueError, match="not retrieved"):
        validate_evidence_block_subset(evidence, {second.block_id})
    with pytest.raises(ValueError, match="quote is not present"):
        validate_evidence_ref(evidence.model_copy(update={"quote": "fabricated-nonexistent-quote"}), binding)
    unresolved = canonicalize_evidence_from_upstream({"evidence": [{
        **evidence.model_dump(mode="json"),
        "source": {**evidence.source.model_dump(mode="json"), "block_id": "BLK-0000000000000000"},
        "is_human_confirmed": True,
    }]}, evidence)
    unknown = EvidenceRef.model_validate(unresolved["evidence"][0])
    assert unknown.is_human_confirmed is False
    with pytest.raises(ValueError, match="not present in validated upstream"):
        validate_evidence_subset(unknown, evidence)


def test_canonical_evidence_drops_unbound_reference_without_dropping_content():
    binding = load_evidence_packet(
        PACKET_PATH,
        workspace=PROJECT_ROOT,
        verify_source_files=False,
    )
    payload = {
        "name": "应保留的组件",
        "evidence": [
            {
                "evidence_id": "FACT-009",
                "source": {"file_name": "模型只写了文件名"},
            }
        ],
    }
    result = canonicalize_evidence_payload(payload, binding)
    assert result["name"] == "应保留的组件"
    assert result["evidence"] == []


def test_canonical_evidence_drops_reference_outside_fact_contract():
    binding = load_evidence_packet(
        PACKET_PATH,
        workspace=PROJECT_ROOT,
        verify_source_files=False,
    )
    blocks = list(binding.blocks.values())
    payload = {
        "name": "应保留的业务内容",
        "evidence": [
            {
                "evidence_id": "EVD-OUTSIDE",
                "source": {"block_id": blocks[1].block_id},
                "quote": blocks[1].text,
            }
        ],
    }
    result = canonicalize_evidence_payload(
        payload,
        binding,
        allowed_block_ids={blocks[0].block_id},
    )
    assert result["name"] == "应保留的业务内容"
    assert result["evidence"] == []


def _create_checked_run(project_dir: Path, run_id: str, node_id: str, upstream=None):
    run_dir = project_dir / run_id
    initialize_run_manifest(
        run_directory=run_dir,
        run_id=run_id,
        project_id="project",
        evidence_packet_ref={"packet_sha256": "a" * 64},
        text_model="qwen-plus",
        requested_node=node_id,
        rule_versions={"scope": "v2"},
        upstream=upstream,
    )
    stage = {
        "0": "node_0_scope",
        "1": "node_1_context",
        "2": "node_2_assets",
    }[node_id]
    progress = run_dir / "progress"
    progress.mkdir(parents=True)
    (progress / f"{stage}.json").write_text("{}", encoding="utf-8")
    (progress / f"{stage}.xlsx").write_bytes(b"xlsx")
    record_node_result(
        run_directory=run_dir,
        node_id=node_id,
        status=f"node_{node_id}_completed",
        completed_node="test",
    )
    mark_node_checked(project_output_directory=project_dir, run_id=run_id, node_id=node_id)


def test_new_checked_node0_invalidates_registered_downstream(tmp_path: Path):
    _create_checked_run(tmp_path, "node0-a", "0")
    upstream = {"node_0": {"run_id": "node0-a"}}
    _create_checked_run(tmp_path, "node1-a", "1", upstream=upstream)
    _create_checked_run(tmp_path, "node0-b", "0")

    registry = json.loads((tmp_path / "checked_upstreams.json").read_text(encoding="utf-8"))
    assert registry["nodes"]["node_0"]["run_id"] == "node0-b"
    assert registry["nodes"]["node_1"]["checked_usable"] is False
    assert registry["nodes"]["node_1"]["requires_revalidation"] is True


def test_distinct_switch_interface_and_optional_device_are_not_conflict():
    scope = _scope(in_scope_components=["EMU300A 整机", "核心交换机连接接口"])
    assert _validate_scope(scope, None) == scope

