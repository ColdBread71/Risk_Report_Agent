"""Offline regressions for the shared model-output boundary and diagnostics."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from core import structured_extraction as extraction
from schemas.retrieval import FieldExtractionResult
from schemas.evidence_packet import EvidenceTargetNode
from schemas.retrieval import RetrievalField
from tools.retrieval_profiles import get_profiles_for_node, get_retrieval_profile


def payload(attributes):
    return {
        "node_id": "node_1", "field_id": "communications",
        "facts": [{"fact_id": "FACT-001", "statement": "设备提供管理接口。",
                   "block_ids": ["BLK-1234567890ABCDEF"], "attributes": attributes}],
    }


class FakeLlm:
    model_name = "offline"

    def __init__(self, *responses):
        self.responses = iter(responses)
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False))


def run(llm, tmp_path, **kwargs):
    return RunnableLambda(lambda _: extraction.extract_with_retry(
        llm, "{json_schema}\n{sample_input}", FieldExtractionResult, "evidence",
        task_label="node_1/communications", **kwargs,
    )).invoke({}, config={"configurable": {
        "thread_id": "offline-run", "extraction_log_dir": str(tmp_path),
    }})


@pytest.fixture(autouse=True)
def no_tokenizer_download(monkeypatch):
    monkeypatch.setattr(extraction, "enforce_input_token_budget", lambda *_: 100)


def test_format_variations_preserve_values_without_retry(tmp_path):
    llm = FakeLlm(payload({"port": 8080, "conditions": "订购后启用",
                           "data_exchanged": "管理配置", "authentication": None}))
    result = run(llm, tmp_path)
    assert len(llm.prompts) == 1
    assert result.facts[0].attributes == {
        "port": "8080", "conditions": ["订购后启用"], "data_exchanged": ["管理配置"],
    }
    record = json.loads(next(tmp_path.rglob("attempt-1.json")).read_text(encoding="utf-8"))
    assert json.loads(record["raw_response"])["facts"][0]["attributes"]["port"] == 8080
    assert record["result"]["facts"][0]["attributes"]["port"] == "8080"


@pytest.mark.parametrize("attributes,location", [
    ({"conditions": ["x"] * 11}, ("conditions",)),
    ({"conditions": [" "]}, ("conditions", 0)),
    ({"port": True}, ("port",)),
    ({"port": 80.5}, ("port",)),
    ({"port": ["80", "443"]}, ("port",)),
    ({"activation_status": "probably"}, ("activation_status",)),
])
def test_invalid_content_is_rejected_at_exact_attribute(attributes, location):
    with pytest.raises(ValidationError) as error:
        FieldExtractionResult.model_validate(payload(attributes))
    assert error.value.errors()[0]["loc"] == ("facts", 0, "attributes", *location)


def test_model_schema_exposes_runtime_constraints():
    schema = FieldExtractionResult.model_json_schema()
    assert schema["$defs"]["RetrievedFact"]["properties"]["attributes"]["$ref"] == "#/$defs/FactAttributes"
    attributes = schema["$defs"]["FactAttributes"]
    assert attributes["additionalProperties"] is False
    props = attributes["properties"]
    assert props["conditions"]["anyOf"][0]["type"] == "array"
    assert props["conditions"]["anyOf"][0]["maxItems"] == 10
    assert props["port"]["anyOf"][0]["type"] == "string"
    assert "unknown" in props["activation_status"]["anyOf"][0]["enum"]


def test_failed_reply_and_exact_value_saved_across_retry(tmp_path):
    llm = FakeLlm(payload({"conditions": ["x"] * 11}), payload({"conditions": ["x"]}))
    run(llm, tmp_path)
    paths = sorted(tmp_path.rglob("attempt-*.json"))
    assert len(paths) == 2 and paths[0].parent == paths[1].parent
    first, second = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    assert first["status"] == "failed" and second["status"] == "succeeded"
    assert first["phase"] == "schema_validation"
    assert first["validation_errors"][0]["loc"] == ["facts", 0, "attributes", "conditions"]
    assert first["validation_errors"][0]["input"] == ["x"] * 11
    assert first["run_id"] == "offline-run"
    assert first["raw_response"] in second["prompt"]


def test_semantic_failure_preserves_pre_transform_reply(tmp_path):
    def transform(value):
        value["facts"][0]["statement"] = "transformed"
        return value

    def reject(value):
        raise ValueError("Evidence block not in retrieval set")

    with pytest.raises(RuntimeError, match="diagnostics:"):
        run(FakeLlm(payload({})), tmp_path, max_retries=1,
            payload_transformer=transform, semantic_validator=reject)
    record = json.loads(next(tmp_path.rglob("*.json")).read_text(encoding="utf-8"))
    assert record["phase"] == "semantic_validation"
    assert record["parsed_payload"]["facts"][0]["statement"] == "设备提供管理接口。"
    assert record["validation_payload"]["facts"][0]["statement"] == "transformed"


def test_request_failure_is_not_misreported_as_schema_failure(tmp_path):
    with pytest.raises(RuntimeError):
        run(FakeLlm(TimeoutError("offline timeout")), tmp_path, max_retries=1)
    record = json.loads(next(tmp_path.rglob("*.json")).read_text(encoding="utf-8"))
    assert record["phase"] == "request"
    assert record["error_type"] == "TimeoutError"
    assert "raw_response" not in record


def test_transport_retry_does_not_invent_json_correction_feedback(tmp_path):
    llm = FakeLlm(TimeoutError("offline timeout"), payload({}))
    run(llm, tmp_path, max_retries=2)
    assert llm.prompts[0] == llm.prompts[1]


def test_budget_failure_is_saved_without_model_request(tmp_path, monkeypatch):
    def reject(*_):
        raise extraction.LLMInputBudgetExceededError("offline budget limit")

    monkeypatch.setattr(extraction, "enforce_input_token_budget", reject)
    llm = FakeLlm(payload({}))
    with pytest.raises(extraction.LLMInputBudgetExceededError):
        run(llm, tmp_path)
    assert llm.prompts == []
    records = list(tmp_path.rglob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["status"] == "failed" and record["phase"] == "input_budget"


def test_interruption_is_saved_and_not_retried(tmp_path):
    llm = FakeLlm(KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        run(llm, tmp_path)
    assert len(llm.prompts) == 1
    record = json.loads(next(tmp_path.rglob("*.json")).read_text(encoding="utf-8"))
    assert record["status"] == "interrupted" and record["phase"] == "request"


def test_logging_failure_prevents_paid_request(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("existing", encoding="utf-8")
    llm = FakeLlm(payload({}))
    with pytest.raises(OSError):
        run(llm, blocked)
    assert llm.prompts == []


def test_graph_propagates_run_and_node_to_diagnostics(tmp_path, monkeypatch):
    secret = "test-only-secret-123456789"
    monkeypatch.setenv("TEST_API_KEY", secret)
    graph = StateGraph(dict)

    def node(state):
        result = extraction.extract_with_retry(
            FakeLlm(payload({})), "{json_schema}\n{sample_input}",
            FieldExtractionResult, secret,
        )
        return result.model_dump()

    graph.add_node("build_product_context", node)
    graph.add_edge(START, "build_product_context")
    graph.add_edge("build_product_context", END)
    graph.compile().invoke({}, config={"configurable": {
        "thread_id": "graph-run", "extraction_log_dir": str(tmp_path),
    }})
    text = next(tmp_path.rglob("*.json")).read_text(encoding="utf-8")
    record = json.loads(text)
    assert record["node"] == "build_product_context"
    assert record["run_id"] == "graph-run"
    assert secret not in text
    assert "[REDACTED]" in record["prompt"]


PROFILES = [profile for node in (
    EvidenceTargetNode.SCOPE, EvidenceTargetNode.CONTEXT, EvidenceTargetNode.ASSETS,
) for profile in get_profiles_for_node(node)]


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.field_id.value)
def test_every_field_advertises_only_attributes_it_accepts(profile):
    schema = FieldExtractionResult.schema_for_profile(profile)
    props = schema["$defs"]["FactAttributes"]["properties"]
    expected = {
        "components": {"component_name", "component_type", "scope_status", "conditions"},
        "communications": {"source", "destination", "protocol", "port", "interface",
                           "authentication", "encryption", "data_exchanged", "conditions",
                           "direction_basis", "business_data_direction", "activation_status"},
    }.get(profile.field_id.value, set())
    assert set(props) == expected
    assert schema["$defs"]["FactAttributes"]["additionalProperties"] is False
    assert schema["properties"]["node_id"]["const"] == profile.node_id.value
    assert schema["properties"]["field_id"]["const"] == profile.field_id.value
    assert schema["properties"]["facts"]["maxItems"] == profile.max_facts
    for key in expected:
        value = [] if key in {"conditions", "data_exchanged"} else "unknown"
        candidate = payload({key: value})
        candidate.update(node_id=profile.node_id, field_id=profile.field_id)
        FieldExtractionResult.model_validate(candidate)
    candidate = payload({"invented_key": None})
    candidate.update(node_id=profile.node_id, field_id=profile.field_id)
    with pytest.raises(ValueError, match="attributes are not allowed"):
        FieldExtractionResult.model_validate(candidate)


def test_scope_error_reports_forbidden_attributes_before_destination_type(tmp_path):
    profile = get_retrieval_profile(EvidenceTargetNode.SCOPE, RetrievalField.SCOPE_BOUNDARY)
    failed = payload({"destination": ["System A", "System B"], "component_name": "switch"})
    failed.update(node_id="node_0", field_id="scope_boundary")
    corrected = deepcopy(failed)
    corrected["facts"][0]["attributes"] = {}
    llm = FakeLlm(failed, corrected)
    result = run(llm, tmp_path, json_schema=FieldExtractionResult.schema_for_profile(profile))
    assert result.facts[0].attributes == {}
    assert '"component_name"' not in llm.prompts[0]
    assert "allowed keys: []" in llm.prompts[1]
    # The previous reply appears once; error feedback no longer repeats all facts.
    assert llm.prompts[1].count('"statement"') == llm.prompts[0].count('"statement"') + 1
    record = json.loads(next(tmp_path.rglob("attempt-1.json")).read_text(encoding="utf-8"))
    assert record["validation_errors"][0]["input"] == failed


def test_task_schema_changes_cache_identity_and_enforces_fact_limit():
    from nodes.field_extractor import _field_schema_sha256, _validate_field_result
    from schemas.retrieval import RetrievalRequest

    profile = get_retrieval_profile(EvidenceTargetNode.CONTEXT, RetrievalField.COMMUNICATIONS)
    smaller = profile.model_copy(update={"max_facts": 1})
    assert _field_schema_sha256(profile) != _field_schema_sha256(smaller)
    candidate = payload({})
    candidate["facts"].append({**candidate["facts"][0], "fact_id": "FACT-002"})
    result = FieldExtractionResult.model_validate(candidate)
    request = RetrievalRequest(project_id="test", node_id=profile.node_id, field_id=profile.field_id)
    with pytest.raises(ValueError, match="at most 1"):
        _validate_field_result(result, request, SimpleNamespace(blocks={}), max_facts=1)


@pytest.mark.parametrize("profile", PROFILES, ids=lambda p: p.field_id.value)
def test_production_field_call_passes_scoped_schema(profile, monkeypatch):
    from nodes import field_extractor as fields

    trace = SimpleNamespace(selected_count=0, selected_token_count=0,
                            index_id="offline", effective_query="offline")
    monkeypatch.setattr(fields, "retrieve_evidence", lambda **_: (None, trace))
    monkeypatch.setattr(fields, "bind_materialized_packet", lambda _: SimpleNamespace(blocks={}))
    monkeypatch.setattr(fields, "render_evidence_material", lambda _: "offline evidence")
    monkeypatch.setattr(fields, "_cache_inputs", lambda **_: {})
    llm = FakeLlm({"node_id": profile.node_id.value, "field_id": profile.field_id.value,
                   "facts": [], "unknowns": ["证据不足"]})
    fields._extract_profile_facts(
        llm=llm, profile=profile, scope=SimpleNamespace(packet=SimpleNamespace(project_id="test")),
        config={}, loaded=None, provider=None, text_model="offline", cache_policy="refresh",
    )
    schema, _ = json.JSONDecoder().raw_decode(llm.prompts[0].split("【目标 JSON Schema】", 1)[1].lstrip())
    assert schema == FieldExtractionResult.schema_for_profile(profile)
