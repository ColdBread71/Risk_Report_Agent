from types import SimpleNamespace

import pytest

from tools import embedding_provider
from tools.embedding_provider import (
    DashScopeEmbeddingProvider,
    PermanentEmbeddingError,
    TransientEmbeddingError,
)


class _FakeEmbeddings:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, outcomes):
        self.embeddings = _FakeEmbeddings(outcomes)


class _StatusError(RuntimeError):
    def __init__(self, status_code):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def _response(vector, request_id="req-test"):
    return SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=vector)],
        _request_id=request_id,
    )


@pytest.fixture(autouse=True)
def _embedding_environment(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_EMBEDDING_MODEL", "embedding-test")
    monkeypatch.setenv("DASHSCOPE_EMBEDDING_DIMENSIONS", "3")
    monkeypatch.setenv("DASHSCOPE_EMBEDDING_BATCH_SIZE", "10")
    monkeypatch.setenv("DASHSCOPE_EMBEDDING_BASE_URL", "https://embedding.invalid/v1")


def test_transient_failures_retry_at_provider_boundary(monkeypatch):
    client = _FakeClient(
        [TimeoutError("slow"), _StatusError(503), _response([0.1, 0.2, 0.3])]
    )
    sleeps = []
    monkeypatch.setattr(embedding_provider.time, "sleep", sleeps.append)
    provider = DashScopeEmbeddingProvider(
        client=client,
        max_attempts=3,
        backoff_seconds=1,
    )

    assert provider.embed_query("query") == [0.1, 0.2, 0.3]
    assert len(client.embeddings.calls) == 3
    assert sleeps == [1.0, 2.0]


def test_transient_failure_reports_exhausted_attempts(monkeypatch):
    client = _FakeClient([TimeoutError("slow"), TimeoutError("still slow")])
    monkeypatch.setattr(embedding_provider.time, "sleep", lambda _seconds: None)
    provider = DashScopeEmbeddingProvider(client=client, max_attempts=2)

    with pytest.raises(TransientEmbeddingError, match="after 2 attempts"):
        provider.embed_query("query")
    assert len(client.embeddings.calls) == 2


def test_permanent_failure_is_not_retried(monkeypatch):
    client = _FakeClient([_StatusError(401), _response([0.1, 0.2, 0.3])])
    monkeypatch.setattr(
        embedding_provider.time,
        "sleep",
        lambda _seconds: pytest.fail("permanent errors must not back off"),
    )
    provider = DashScopeEmbeddingProvider(client=client, max_attempts=3)

    with pytest.raises(PermanentEmbeddingError, match="status=401"):
        provider.embed_query("query")
    assert len(client.embeddings.calls) == 1


def test_query_cache_avoids_second_remote_call(tmp_path):
    first_client = _FakeClient([_response([0.1, 0.2, 0.3])])
    first = DashScopeEmbeddingProvider(
        client=first_client,
        query_cache_dir=tmp_path,
    )
    assert first.embed_query("stable query") == [0.1, 0.2, 0.3]

    second_client = _FakeClient([AssertionError("remote call should be bypassed")])
    second = DashScopeEmbeddingProvider(
        client=second_client,
        query_cache_dir=tmp_path,
    )
    assert second.embed_query("stable query") == [0.1, 0.2, 0.3]
    assert len(first_client.embeddings.calls) == 1
    assert second_client.embeddings.calls == []
    cache_text = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "stable query" not in cache_text


def test_corrupt_query_cache_is_replaced(tmp_path):
    client = _FakeClient([_response([0.1, 0.2, 0.3])])
    provider = DashScopeEmbeddingProvider(client=client, query_cache_dir=tmp_path)
    cache_path = provider._query_cache_path("query")
    assert cache_path is not None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text('{"bad": true}', encoding="utf-8")

    assert provider.embed_query("query") == [0.1, 0.2, 0.3]
    assert len(client.embeddings.calls) == 1
    assert "identity" in cache_path.read_text(encoding="utf-8")


def test_sdk_retries_are_disabled_and_timeout_is_explicit(monkeypatch):
    captured = {}
    fake_client = _FakeClient([])

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(embedding_provider, "OpenAI", fake_openai)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    provider = DashScopeEmbeddingProvider(timeout_seconds=45, max_attempts=2)

    assert provider.max_attempts == 2
    assert captured["timeout"] == 45
    assert captured["max_retries"] == 0
    assert captured["base_url"] == "https://embedding.invalid/v1"
