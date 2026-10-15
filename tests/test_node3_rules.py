"""Offline Node3 contracts and saved-baseline integration, with all networking blocked."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from openpyxl import load_workbook
import pytest
from pydantic import ValidationError

from core.node3_runner import load_node3_draft
from nodes import asset_threat_modeler as node
from schemas.product import Asset
from schemas.threat import ThreatAssessment, ThreatCandidateResult
from tools.evidence_input import load_evidence_packet


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "output/emu-node012-local-fixes-20261014-01"
PACKET = ROOT / "project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import core.llm
    def blocked(*args, **kwargs):
        raise AssertionError("Offline Node3 verification attempted network access")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    # The tokenizer vocabulary is not cached on this host. UTF-8 byte length
    # is a conservative upper bound on cl100k token count; avoid downloading it.
    monkeypatch.setattr(core.llm, "_token_encoding", lambda: SimpleNamespace(
        encode=lambda text, **kwargs: text.encode("utf-8")))


def candidate(**changes):
    data = {
        "threat_id": "THREAT-001", "stride_category": "tampering", "title": "配置被篡改",
        "description": "可访问维护入口的攻击者若绕过写入授权，可修改配置并破坏配置完整性。",
        "targeted_asset_ids": ["ASSET-001"], "compromised_objective_ids": ["OBJ-001"],
        "cause_of_compromise": "配置写入授权若可绕过，将允许非授权修改。",
        "threat_actor": "可访问维护网络的攻击者", "attack_path": "维护入口→写入授权绕过→配置修改（条件待确认）",
        "analysis_basis": "输入识别配置资产和完整性目标；授权绕过是条件性攻击机理，尚无漏洞证明。",
        "assumptions": ["存在可绕过的写入授权缺陷（未证实）"],
        "confirmation_questions": ["配置写入的身份认证和授权如何实施？"],
    }
    return {**data, **changes}


def inventory():
    return [Asset(asset_id=f"ASSET-{i:03}", name=f"配置{i}", asset_type="data", status="needs_confirmation", description="配置数据",
                  related_objectives=[{"objective_id": f"OBJ-{i:03}", "category": "integrity", "description": "配置不可被非授权修改"}])
            for i in (1, 2)]


def validate(*items):
    result = ThreatCandidateResult(threats=list(items), assessment="PASS")
    return node._canonicalize_and_validate_threats(result, inventory())


def test_coverage_gaps_preserve_candidate_and_canonical_objects():
    result = validate(candidate())
    assert result.assessment.value == "PARTIAL"
    assert "ASSET-002" in result.notes
    assert result.threats[0].targeted_assets[0] == inventory()[0]
    assert result.threats[0].compromised_objectives[0] == inventory()[0].related_objectives[0]
    assert result.threats[0].analysis_basis


def test_coverage_warning_never_upgrades_model_fail():
    result = ThreatCandidateResult(threats=[candidate()], assessment="FAIL", notes="覆盖不足")
    assert node._canonicalize_and_validate_threats(result, inventory()).assessment.value == "FAIL"


@pytest.mark.parametrize("changes", [
    {"targeted_asset_ids": ["ASSET-999"]},
    {"compromised_objective_ids": ["OBJ-002"]},
    {"targeted_asset_ids": ["ASSET-001", "ASSET-001"]},
    {"compromised_objective_ids": ["OBJ-001", "OBJ-001"]},
    {"targeted_asset_ids": ["ASSET-001", "ASSET-002"]},
    {"analysis_basis": " "}, {"cause_of_compromise": " "}, {"attack_path": None},
])
def test_invalid_links_or_empty_analysis_rejected(changes):
    with pytest.raises(ValueError):
        validate(candidate(**changes))


def test_duplicate_ids_and_invalid_stride_rejected():
    with pytest.raises(ValidationError):
        validate(candidate(), candidate())
    with pytest.raises(ValidationError):
        validate(candidate(stride_category="generic"))


def test_multi_asset_scenario_and_node4_contract():
    result = validate(candidate(targeted_asset_ids=["ASSET-001", "ASSET-002"], compromised_objective_ids=["OBJ-001", "OBJ-002"]))
    saved = ThreatAssessment(threats=result.threats, assessment=result.assessment)
    restored = ThreatAssessment.model_validate_json(saved.model_dump_json())
    assert restored.threats[0].threat_id == "THREAT-001"
    assert len(restored.threats[0].targeted_assets) == 2
    assert restored.scores == []


def test_formal_flow_still_requires_approval(monkeypatch):
    from nodes.asset_threat_modeler import route_after_asset_review
    monkeypatch.setattr(node, "get_llm", lambda: pytest.fail("Unapproved formal path reached LLM"))
    assert node.model_threats({"assets": inventory()})["status"] == "threat_modeling_blocked"
    assert route_after_asset_review({"status": "asset_identification_partial_draft", "asset_review_approved": False}) == "end"
    assert route_after_asset_review({"status": "asset_review_approved", "asset_review_approved": True}) == "model_threats"


@pytest.fixture
def baseline():
    if not (BASE / "report.json").exists() or not PACKET.exists():
        pytest.skip("Local customer baseline is not available")
    binding = load_evidence_packet(PACKET, workspace=ROOT, verify_source_files=True)
    return load_node3_draft(BASE / "report.json", binding), binding


def emu_fixture():
    """Handwritten test responses, NOT an LLM/business assessment of this product."""
    specs = [
        ("spoofing", "开发者身份冒用", [3], [5], "若开发者凭据泄露或身份验证可绕过，攻击者可能冒用维护身份。", "输入列有开发者凭据和真实性目标；凭据泄露与验证绕过仅为待确认前提。"),
        ("tampering", "升级包或信任公钥被替换", [5, 10], [7, 12], "若更新输入或信任公钥写入边界可绕过，攻击者可能替换更新内容并加载非授权代码。", "输入识别升级包、公钥及完整性目标；已有签名功能不证明密钥替换不可行，也不证明可行。"),
        ("repudiation", "攻击后改写操作记录", [1, 27], [1, 33], "若执行敏感操作的身份还能改写日志，可删除或修改操作记录以掩盖行为。", "输入识别操作日志及完整性目标；抵赖机理关联记录篡改，不额外创建问责目标。"),
        ("information_disclosure", "root凭据泄露", [4], [6], "若维护会话或凭据存储暴露给非授权主体，root凭据可能被读取并用于后续访问。", "输入存在root凭据资产；具体存储方式及保护强度未知。"),
        ("denial_of_service", "北向入口资源耗尽", [15, 20], [18, 25], "可达北向接口的攻击者若以高频或异常请求耗尽共享资源，数据转发可能中断。", "输入识别北向接口和转发可用性目标；需确认协议入口可达性、限流与资源隔离。"),
        ("elevation_of_privilege", "低权限身份越权修改Web参数", [23], [29], "若服务端写入操作未严格检查角色权限，低权限用户可能修改其职责之外的参数。", "输入包含Web配置和分角色用户；服务端鉴权缺陷并未证实。"),
        ("tampering", "伪造或重放远程调度指令", [21, 19], [26, 27, 22], "若接收端无法有效验证来源及新鲜性，可达调度通道的攻击者可能注入或重放指令并影响本地执行。", "输入识别远程接收和本地调度目标；认证及重放防护需要确认。"),
        ("information_disclosure", "云转发链路数据外泄", [16, 22], [19, 28], "若部署启用了云转发且对端身份校验或传输保护可绕过，路径上的攻击者可能获取转发数据。", "仅考虑产品到云的交互及数据保密性，不假设云平台内部存在漏洞。"),
        ("denial_of_service", "异常调度导致财产影响", [29], [35], "若网络侧非授权调度可改变实际设备输出且现场保护未阻断，可能中断现场业务并造成财产影响。", "输入识别财产安全目标；网络指令到物理输出的因果链、现场联锁和影响范围均待确认。"),
    ]
    return {"threats": [candidate(
        threat_id=f"THREAT-{i:03}", stride_category=kind, title=title,
        targeted_asset_ids=[f"ASSET-{a:03}" for a in assets],
        compromised_objective_ids=[f"OBJ-{o:03}" for o in objectives],
        description=description, analysis_basis=basis,
        cause_of_compromise=description,
        attack_path=description,
        assumptions=["场景中的缺陷及访问条件尚未证实，需工程师确认"],
        confirmation_questions=[basis + "请核实对应控制、访问条件和实际部署。"],
        known_vulnerabilities=[], evidence=[],
    ) for i, (kind, title, assets, objectives, description, basis) in enumerate(specs, 1)],
        "assessment": "PARTIAL", "notes": "手写离线测试响应，仅验证程序链路；尚未完成全部资产及攻击面的分析。"}


def test_saved_baseline_cli_offline(monkeypatch, baseline, tmp_path):
    import main
    state, binding = baseline
    protected = [ROOT / "CRA_TARA_workflow_prEN40000.md", *BASE.glob("*.*")]
    hashes = {path: sha256(path.read_bytes()).hexdigest() for path in protected}
    response = emu_fixture()
    response["threats"][0]["evidence"] = [state["assets"][2].evidence[0].model_dump(mode="json")]
    response["threats"][0]["evidence"][0]["is_human_confirmed"] = True
    calls = []

    def invoke(prompt):
        calls.append(prompt)
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False), response_metadata={})
    monkeypatch.setattr(node, "get_llm", lambda: SimpleNamespace(invoke=invoke, model_name="qwen-plus"))
    args = ["--node", "3", "--upstream-report", str(BASE / "report.json"),
            "--allow-unreviewed-draft", "--evidence-packet", str(PACKET),
            "--output-dir", str(tmp_path), "--run-id", "offline-node3"]
    assert main.main(args) == 0
    assert len(calls) == 1
    raw = json.loads((tmp_path / "offline-node3/report.json").read_text(encoding="utf-8"))
    output = raw["state"]
    assessment = ThreatAssessment.model_validate(output["threat_assessment"])
    assert output["status"] == "threat_modeling_draft"
    assert output["asset_review_approved"] is False
    assert assessment.review_status == "unreviewed_draft"
    assert assessment.assessment.value == "PARTIAL"
    assert len(assessment.threats) == 9 and len({t.stride_category for t in assessment.threats}) == 6
    assert assessment.uncovered_asset_ids and assessment.scores == []
    assert assessment.threats[0].evidence[0].is_human_confirmed is False
    assert [a.model_dump(mode="json") for a in state["assets"]] == output["assets"]
    workbook = load_workbook(tmp_path / "offline-node3/report.xlsx")
    rows = list(workbook["Node3 STRIDE 威胁"].values)
    assert "未审核草稿" in rows[0][0]
    assert len(rows[4:]) == len(assessment.threats)
    for threat, row in zip(assessment.threats, rows[4:]):
        assert threat.threat_id == row[0]
        assert threat.analysis_basis == row[11]
        assert threat.assumptions[0] in row[12]
        assert row[15] == "unreviewed_draft"
    workbook.close()
    manifest = json.loads((tmp_path / "offline-node3/run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["upstream"]["node_2"]["business_reviewed"] is False
    assert manifest["upstream"]["node_2"]["sha256"] == hashes[BASE / "report.json"]
    assert set(manifest["outputs"]) == {"report.json", "report.xlsx"}
    assert main.main(args) == 1  # refuse overwrite
    assert hashes == {path: sha256(path.read_bytes()).hexdigest() for path in protected}


def test_missing_optin_does_not_call_llm(monkeypatch, tmp_path):
    import main
    monkeypatch.setattr(node, "get_llm", lambda: pytest.fail("Missing opt-in reached LLM"))
    assert main.main(["--node", "3", "--evidence-packet", str(PACKET),
                      "--output-dir", str(tmp_path), "--run-id", "blocked-node3"]) == 1
    assert not (tmp_path / "blocked-node3").exists()


@pytest.mark.parametrize("change", ["packet", "technical", "objective"])
def test_invalid_upstream_refused(baseline, tmp_path, change):
    state, binding = baseline
    raw = json.loads((BASE / "report.json").read_text(encoding="utf-8"))
    if change == "packet":
        raw["evidence_packet_ref"]["packet_sha256"] = "0" * 64
    elif change == "technical":
        raw["workflow_status"] = "asset_identification_technical_incomplete"
    else:
        raw["asset_identification"]["assets"][0]["related_objectives"] = []
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        load_node3_draft(source, binding)


def test_fabricated_evidence_rejected(baseline, monkeypatch):
    state, binding = baseline
    response = emu_fixture()
    evidence = deepcopy(state["assets"][2].evidence[0].model_dump(mode="json"))
    evidence["source"]["block_id"] = "BLK-0000000000000000"
    response["threats"][0]["evidence"] = [evidence]
    monkeypatch.setattr(node, "get_llm", lambda: SimpleNamespace(
        invoke=lambda prompt: SimpleNamespace(content=json.dumps(response), response_metadata={}), model_name="qwen-plus"))
    result = node.model_threats(state, {"configurable": {
        "evidence_packet_path": str(PACKET), "workspace": str(ROOT), "allow_unreviewed_threat_draft": True}})
    assert result["status"] == "threat_modeling_failed"
    assert result["threat_assessment"] is None
    assert "outside the evidence packet" in result["errors"][-1]


def test_approved_node3_retains_formal_path(baseline, monkeypatch):
    state, binding = baseline
    state = {**state, "status": "asset_review_approved", "asset_review_approved": True}
    response = emu_fixture()
    monkeypatch.setattr(node, "get_llm", lambda: SimpleNamespace(
        invoke=lambda prompt: SimpleNamespace(content=json.dumps(response), response_metadata={}), model_name="qwen-plus"))
    result = node.model_threats(state, {"configurable": {
        "evidence_packet_path": str(PACKET), "workspace": str(ROOT)}})
    assert result["status"] == "threat_modeling_completed"
    assert result["threat_assessment"].upstream_asset_review_approved is True
    assert result["threat_assessment"].review_status == "unreviewed_draft"


def test_valid_packet_block_not_in_node3_input_is_rejected(baseline, monkeypatch):
    from tools.evidence_input import canonicalize_evidence_payload, iter_evidence_refs
    state, binding = baseline
    used = {e.source.block_id for e in iter_evidence_refs(state)}
    block_id = next(block_id for block_id in binding.blocks if block_id not in used)
    evidence = canonicalize_evidence_payload({"evidence": [{
        "evidence_id": "EVD-unseen", "source": {"block_id": block_id}}]}, binding)["evidence"][0]
    response = emu_fixture()
    response["threats"][0]["evidence"] = [evidence]
    monkeypatch.setattr(node, "get_llm", lambda: SimpleNamespace(
        invoke=lambda prompt: SimpleNamespace(content=json.dumps(response), response_metadata={}), model_name="qwen-plus"))
    result = node.model_threats(state, {"configurable": {
        "evidence_packet_path": str(PACKET), "workspace": str(ROOT), "allow_unreviewed_threat_draft": True}})
    assert result["status"] == "threat_modeling_failed"
    assert "not present in validated upstream results" in result["errors"][-1]


def test_runtime_packet_mismatch_stops_before_llm(baseline, monkeypatch):
    state, binding = baseline
    state = {**state, "evidence_packet_ref": state["evidence_packet_ref"].model_copy(update={"packet_sha256": "0" * 64})}
    monkeypatch.setattr(node, "get_llm", lambda: pytest.fail("Mismatched packet reached LLM"))
    result = node.model_threats(state, {"configurable": {
        "evidence_packet_path": str(PACKET), "workspace": str(ROOT), "allow_unreviewed_threat_draft": True}})
    assert result["status"] == "threat_modeling_failed"
    assert "upstream identity" in result["errors"][-1]
