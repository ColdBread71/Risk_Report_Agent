"""Bounded batch generation/reuse and latest-customer-input checks, all offline."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import httpx
from openai import APITimeoutError
import pytest
from pydantic import ValidationError

import main
from core.node3_runner import load_node3_draft
from nodes import asset_threat_modeler as node
from nodes import threat_batches as batches
from schemas.threat import ThreatAssessment, ThreatBatchResult
from tools.evidence_input import load_evidence_packet


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/emu-node2-resume-qwen38max-20261019-01-export-fix/report.json"
PACKET = ROOT / "project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json"
LATEST = ROOT / "output/emu-node3-qwen38max-20261019-01"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import core.llm
    def blocked(*args, **kwargs):
        raise AssertionError("Offline test attempted network access")
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setenv("DASHSCOPE_TEXT_MODEL", "qwen-plus")
    monkeypatch.setattr(core.llm, "_token_encoding", lambda: SimpleNamespace(
        encode=lambda text, **kwargs: text.encode("utf-8")))


@pytest.fixture
def latest():
    if not SOURCE.exists() or not (LATEST / "report.json").exists():
        pytest.skip("Local latest customer input unavailable")
    binding = load_evidence_packet(PACKET, workspace=ROOT, verify_source_files=True)
    state = load_node3_draft(SOURCE, binding)
    saved = json.loads((LATEST / "report.json").read_text(encoding="utf-8"))["state"]["threat_assessment"]["threats"]
    # Historical narratives are response fixtures only, not a quality claim.
    responses = []
    for indexes in ((0, 1), (4, 11), (8, 15)):
        threats = []
        for index in indexes:
            original = saved[index]
            value = {k: deepcopy(v) for k, v in original.items()
                     if k not in {"targeted_assets", "compromised_objectives", "evidence"}}
            value["targeted_asset_ids"] = [a["asset_id"] for a in original["targeted_assets"]]
            value["compromised_objective_ids"] = [o["objective_id"] for o in original["compromised_objectives"]]
            value["evidence_block_ids"] = list(dict.fromkeys(
                e["source"]["block_id"] for a in original["targeted_assets"] for e in a["evidence"]))
            threats.append(value)
        responses.append({"threats": threats, "assessment": "PARTIAL", "notes": "离线响应夹具，覆盖及前提待人工复核。"})
    return state, binding, responses


def command(tmp_path, run_id, reuse=None):
    args = ["--node", "3", "--upstream-report", str(SOURCE), "--allow-unreviewed-draft",
            "--evidence-packet", str(PACKET), "--output-dir", str(tmp_path), "--run-id", run_id]
    return args + (["--reuse-node3-batches", reuse] if reuse else [])


def mock_llm(monkeypatch, responses):
    queue, calls = iter(responses), []
    def invoke(prompt):
        calls.append(prompt)
        response = next(queue)
        if isinstance(response, BaseException):
            raise response
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False), response_metadata={})
    monkeypatch.setattr(node, "get_llm", lambda: SimpleNamespace(model_name="qwen-plus", invoke=invoke))
    return calls


def test_latest_input_facts_and_unique_excerpts_are_preserved(latest):
    state, binding, responses = latest
    shared, refs = batches.compact_threat_input(state)
    assert len(shared["assets"]) == 52
    assert sum(len(a["related_objectives"]) for a in shared["assets"]) == 93
    assert len(shared["evidence_catalog"]) == len(refs) == 104
    original = {a.asset_id: a for a in state["assets"]}
    for asset in shared["assets"]:
        source = original[asset["asset_id"]]
        assert asset["description"] == source.description
        assert asset["status"] == source.status
        assert [(o["objective_id"], o["description"], o["status"]) for o in asset["related_objectives"]] == [
            (o.objective_id, o.description, o.status) for o in source.related_objectives]
    assert all(not ref.is_human_confirmed for values in refs.values() for ref in values)
    assert "created_at" not in json.dumps(shared, ensure_ascii=False)
    assert all(len(e["quotes"]) == len(set(e["quotes"])) for e in shared["evidence_catalog"])


def test_generic_perspectives_keep_cloud_and_cross_boundary_context():
    state = {"product_context": {"product_name": "Tenant Ledger", "functions": [
        {"function_id": "FUNC-001", "name": "Tenant API", "description": "租户数据导入与恢复"}],
        "dependencies": ["External identity provider"]}, "scope": None, "assets": [], "asset_review_approved": False}
    shared, refs = batches.compact_threat_input(state)
    prompt = batches.load_prompt("node3_threats.md", "threat_direct")
    perspective_text = json.dumps(batches.PERSPECTIVES, ensure_ascii=False) + prompt
    assert all(term not in perspective_text for term in ("EMU300A", "RS485", "GOOSE", "iConfig", "Micro SD"))
    assert "Tenant API" in json.dumps(shared) and refs == {}
    assert "多租户" in perspective_text and "完整的多步骤攻击链" in prompt
    assert "不机械限制入口数量" in prompt


def test_three_batches_latest_cli_preserves_public_contract_and_sources(latest, monkeypatch, tmp_path):
    state, binding, responses = latest
    protected = [SOURCE, *LATEST.glob("*.*"), ROOT / "CRA_TARA_workflow_prEN40000.md"]
    hashes = {p: sha256(p.read_bytes()).hexdigest() for p in protected}
    calls = mock_llm(monkeypatch, responses)
    assert main.main(command(tmp_path, "latest-offline")) == 0
    assert len(calls) == 3
    path = tmp_path / "latest-offline"
    payload = json.loads((path / "report.json").read_text(encoding="utf-8"))["state"]
    assessment = ThreatAssessment.model_validate(payload["threat_assessment"])
    assert len(assessment.threats) == 6
    assert [t.threat_id for t in assessment.threats] == [f"THREAT-{i:03}" for i in range(1, 7)]
    assert assessment.scores == [] and assessment.review_status == "unreviewed_draft"
    assert payload["assets"] == [a.model_dump(mode="json") for a in state["assets"]]
    assert all(t.evidence for t in assessment.threats)
    assert all(not e.is_human_confirmed for t in assessment.threats for e in t.evidence)
    # Full multi-step chains survive intact; the code does not split by step/entry count.
    assert assessment.threats[4].attack_path == responses[2]["threats"][0]["attack_path"]
    index = json.loads((path / "node3_batches/batch_index.json").read_text(encoding="utf-8"))
    assert index["status"] == "completed"
    assert len(index["scenario_sources"]) == 6
    manifest = json.loads((path / "run_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["batch_artifacts"]) == 4
    assert hashes == {p: sha256(p.read_bytes()).hexdigest() for p in protected}


def test_failed_batch_then_reuse_calls_only_unfinished_batches(latest, monkeypatch, tmp_path):
    state, binding, responses = latest
    timeout = APITimeoutError(request=httpx.Request("POST", "https://offline.invalid"))
    first = mock_llm(monkeypatch, [responses[0], timeout])
    assert main.main(command(tmp_path, "partial")) == 1
    assert len(first) == 2  # timeout is NOT automatically resubmitted
    directory = tmp_path / "partial"
    index = json.loads((directory / "node3_batches/batch_index.json").read_text(encoding="utf-8"))
    assert [b["status"] for b in index["batches"]] == ["succeeded", "failed", "pending"]
    failed = json.loads((directory / "report.json").read_text(encoding="utf-8"))["state"]
    assert failed["status"] == "threat_modeling_failed" and failed["threat_assessment"] is None
    protected = list(directory.glob("**/*.json")) + [directory / "report.xlsx"]
    hashes = {p: sha256(p.read_bytes()).hexdigest() for p in protected}
    retry = mock_llm(monkeypatch, responses[1:])
    assert main.main(command(tmp_path, "recovered", reuse="partial")) == 0
    assert len(retry) == 2
    recovered = json.loads((tmp_path / "recovered/node3_batches/batch_index.json").read_text(encoding="utf-8"))
    assert [b["status"] for b in recovered["batches"]] == ["reused", "succeeded", "succeeded"]
    assert hashes == {p: sha256(p.read_bytes()).hexdigest() for p in protected}
    no_new_calls = mock_llm(monkeypatch, [])
    assert main.main(command(tmp_path, "fully-reused", reuse="recovered")) == 0
    assert no_new_calls == []


@pytest.mark.parametrize("field", ["model", "prompt_sha256", "schema_sha256", "input_sha256", "packet_sha256"])
def test_reuse_preflights_all_cached_fingerprints_before_any_request(latest, monkeypatch, tmp_path, field):
    state, binding, responses = latest
    mock_llm(monkeypatch, responses)
    assert main.main(command(tmp_path, "complete")) == 0
    directory = tmp_path / "complete/node3_batches"
    (directory / "identity_management.json").unlink()  # first batch now needs generation
    path = directory / "lifecycle_local.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["inputs"][field] = "changed"
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    calls = mock_llm(monkeypatch, [])
    assert main.main(command(tmp_path, "mismatch", reuse="complete")) == 1
    assert calls == []  # invalid last batch blocks regeneration of the missing first batch


def test_empty_view_and_changed_conditions_are_not_merged(latest, monkeypatch, tmp_path):
    state, binding, responses = latest
    original = deepcopy(responses[0])
    original["threats"] = original["threats"][:1]
    changed = deepcopy(original)
    changed["threats"][0]["assumptions"] = ["另一交付配置允许远程维护；访问能力和影响范围不同。"]
    calls = mock_llm(monkeypatch, [original, {"threats": [], "assessment": "PARTIAL", "notes": "此视角无适用接口，需确认交付。"}, changed])
    assert main.main(command(tmp_path, "conditions")) == 0 and len(calls) == 3
    result = json.loads((tmp_path / "conditions/report.json").read_text(encoding="utf-8"))["state"]["threat_assessment"]
    assert len(result["threats"]) == 2
    assert "此视角无适用接口" in result["notes"]
    with pytest.raises(ValidationError):
        ThreatBatchResult(threats=[], notes=" ")


def test_identical_findings_merge_without_losing_provenance(latest, monkeypatch, tmp_path):
    state, binding, responses = latest
    repeated = deepcopy(responses[0])
    calls = mock_llm(monkeypatch, [repeated, repeated, repeated])
    assert main.main(command(tmp_path, "duplicates")) == 0 and len(calls) == 3
    index = json.loads((tmp_path / "duplicates/node3_batches/batch_index.json").read_text(encoding="utf-8"))
    assert index["final_threat_count"] == 2
    assert all(len(origins) == 3 for origins in index["scenario_sources"].values())


def test_structured_correction_is_bounded_to_two_attempts_per_batch(latest, monkeypatch, tmp_path):
    state, binding, responses = latest
    broken = {"threats": [], "notes": " "}
    calls = mock_llm(monkeypatch, [v for response in responses for v in (broken, response)])
    assert main.main(command(tmp_path, "corrections")) == 0
    assert len(calls) == 6


def test_client_options_affect_only_node3_copy():
    recorded = []
    class Root:
        def with_options(self, **options):
            recorded.append(options)
            return SimpleNamespace(chat=SimpleNamespace(completions="bounded-client"))
    class Llm:
        root_client = Root()
        def model_copy(self, update):
            return SimpleNamespace(**update)
    original = Llm()
    configured = batches._configured_client(original, 1800)
    assert configured.client == "bounded-client" and configured.max_retries == 0
    assert recorded[0]["timeout"].read == 1800 and recorded[0]["timeout"].connect == 30
    assert original.root_client.__class__ is Root


def test_real_client_configuration_requires_no_request_and_preserves_original():
    from langchain_openai import ChatOpenAI
    original = ChatOpenAI(model="offline", api_key="offline-placeholder", base_url="https://offline.invalid")
    old_timeout = original.root_client.timeout
    old_retries = original.root_client.max_retries
    configured = batches._configured_client(original, 1800)
    assert configured.root_client.timeout.read == 1800
    assert configured.root_client.max_retries == 0
    assert original.root_client.timeout == old_timeout
    assert original.root_client.max_retries == old_retries


def test_corrupt_result_hash_rejected_without_regeneration(latest, monkeypatch, tmp_path):
    state, binding, responses = latest
    mock_llm(monkeypatch, responses)
    assert main.main(command(tmp_path, "original")) == 0
    path = tmp_path / "original/node3_batches/identity_management.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["result"]["threats"][0]["description"] += " changed"
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    calls = mock_llm(monkeypatch, [])
    assert main.main(command(tmp_path, "corrupt", reuse="original")) == 1
    assert calls == []


def test_complete_empty_batch_set_is_not_published_as_success(latest, monkeypatch, tmp_path):
    empty = {"threats": [], "assessment": "PARTIAL", "notes": "无法形成可用候选，缺少适用性信息。"}
    calls = mock_llm(monkeypatch, [empty, empty, empty])
    assert main.main(command(tmp_path, "empty-set")) == 1
    assert len(calls) == 3
    directory = tmp_path / "empty-set"
    state = json.loads((directory / "report.json").read_text(encoding="utf-8"))["state"]
    assert state["status"] == "threat_modeling_failed" and state["threat_assessment"] is None
    assert len(list((directory / "node3_batches").glob("*.json"))) == 4


def test_model_cannot_add_human_authority_to_wire_format(latest):
    state, binding, responses = latest
    forged = deepcopy(responses[0])
    forged["threats"][0]["is_human_confirmed"] = True
    with pytest.raises(ValidationError):
        ThreatBatchResult.model_validate(forged)
