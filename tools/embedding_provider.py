"""Observable, retry-bounded embedding provider with persistent query caching."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Protocol, Sequence
from uuid import uuid4

from openai import OpenAI

from core.logger import setup_logger


logger = setup_logger("embedding_provider")

_DEFAULT_EMBEDDING_MODEL = "text-embedding-v4"
_DEFAULT_EMBEDDING_DIMENSIONS = 1_024
_DEFAULT_EMBEDDING_BATCH_SIZE = 10
_DEFAULT_TIMEOUT_SECONDS = 60.0
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF_SECONDS = 1.0
_QUERY_CACHE_VERSION = "1.0"
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


class EmbeddingProvider(Protocol):
    """Minimal provider contract used by indexing and retrieval."""

    model_name: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbeddingProviderError(RuntimeError):
    """Base error raised at the remote embedding boundary."""


class TransientEmbeddingError(EmbeddingProviderError):
    """A retryable provider or transport error exhausted its bounded attempts."""


class PermanentEmbeddingError(EmbeddingProviderError):
    """A deterministic request, authentication, or response-contract error."""


def _positive_float(value: str | float, *, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return result


def _positive_int(value: str | int, *, name: str) -> int:
    result = int(value)
    if result <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return result


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if value is None:
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _request_id(value: Any) -> str | None:
    for attribute in ("request_id", "_request_id"):
        request_id = getattr(value, attribute, None)
        if request_id:
            return str(request_id)
    response = getattr(value, "response", None)
    headers = getattr(response, "headers", None)
    if headers:
        return headers.get("x-request-id") or headers.get("request-id")
    return None


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if _status_code(exc) in _TRANSIENT_STATUS_CODES:
        return True
    return exc.__class__.__name__ in {
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
    }


class DashScopeEmbeddingProvider:
    """OpenAI-compatible DashScope adapter with visible retries and query cache."""

    def __init__(
        self,
        *,
        query_cache_dir: str | Path | None = None,
        timeout_seconds: float | None = None,
        max_attempts: int | None = None,
        backoff_seconds: float | None = None,
        client: Any | None = None,
    ) -> None:
        self.model_name = os.getenv("DASHSCOPE_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL)
        self.dimensions = _positive_int(
            os.getenv("DASHSCOPE_EMBEDDING_DIMENSIONS", str(_DEFAULT_EMBEDDING_DIMENSIONS)),
            name="embedding dimensions",
        )
        self.batch_size = _positive_int(
            os.getenv("DASHSCOPE_EMBEDDING_BATCH_SIZE", str(_DEFAULT_EMBEDDING_BATCH_SIZE)),
            name="embedding batch size",
        )
        if self.batch_size > 10:
            raise ValueError("embedding batch size must be 1..10")
        self.timeout_seconds = _positive_float(
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("DASHSCOPE_EMBEDDING_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT_SECONDS)),
            name="embedding timeout seconds",
        )
        self.max_attempts = _positive_int(
            max_attempts
            if max_attempts is not None
            else os.getenv("DASHSCOPE_EMBEDDING_MAX_ATTEMPTS", str(_DEFAULT_MAX_ATTEMPTS)),
            name="embedding max attempts",
        )
        self.backoff_seconds = _positive_float(
            backoff_seconds
            if backoff_seconds is not None
            else os.getenv("DASHSCOPE_EMBEDDING_BACKOFF_SECONDS", str(_DEFAULT_BACKOFF_SECONDS)),
            name="embedding backoff seconds",
        )
        self.base_url = os.getenv(
            "DASHSCOPE_EMBEDDING_BASE_URL",
            os.getenv(
                "OPENAI_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        ).rstrip("/")
        self.query_cache_dir = (
            Path(query_cache_dir).resolve() if query_cache_dir is not None else None
        )

        if client is None:
            api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("DASHSCOPE_API_KEY or OPENAI_API_KEY is not configured")
            # Disable opaque SDK retries: every remote attempt is classified and logged here.
            client = OpenAI(
                api_key=api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                max_retries=0,
            )
        self._client = client

    def _cache_identity(self, text: str) -> dict[str, Any]:
        return {
            "cache_version": _QUERY_CACHE_VERSION,
            "provider": "dashscope-openai-compatible",
            "base_url_sha256": _sha256_text(self.base_url),
            "model": self.model_name,
            "dimensions": self.dimensions,
            "query_sha256": _sha256_text(text),
        }

    def _query_cache_path(self, text: str) -> Path | None:
        if self.query_cache_dir is None:
            return None
        identity = self._cache_identity(text)
        key = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self.query_cache_dir / f"{key}.json"

    def _validated_vector(self, value: Any) -> list[float]:
        if not isinstance(value, list) or len(value) != self.dimensions:
            raise ValueError(
                f"embedding vector length must be {self.dimensions}, got "
                f"{len(value) if isinstance(value, list) else 'non-list'}"
            )
        result = [float(item) for item in value]
        if not all(math.isfinite(item) for item in result):
            raise ValueError("embedding vector contains a non-finite value")
        return result

    def _load_query_cache(self, text: str) -> list[float] | None:
        path = self._query_cache_path(text)
        if path is None or not path.is_file():
            return None
        query_hash = _sha256_text(text)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("identity") != self._cache_identity(text):
                raise ValueError("cache identity mismatch")
            vector = self._validated_vector(payload.get("vector"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning(
                "查询向量缓存无效，将重新请求：query_sha256=%s cache=%s error_type=%s",
                query_hash,
                path,
                exc.__class__.__name__,
            )
            return None
        logger.info(
            "复用查询向量缓存：query_sha256=%s model=%s dimensions=%d",
            query_hash,
            self.model_name,
            self.dimensions,
        )
        return vector

    def _save_query_cache(self, text: str, vector: list[float]) -> None:
        path = self._query_cache_path(text)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "identity": self._cache_identity(text),
            "vector": self._validated_vector(vector),
        }
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _request_batch(self, batch: list[str]) -> list[list[float]]:
        batch_hash = _sha256_text("\u0000".join(batch))
        for attempt in range(1, self.max_attempts + 1):
            started = time.perf_counter()
            try:
                logger.info(
                    "发起 embedding 请求：model=%s batch=%d attempt=%d/%d input_sha256=%s",
                    self.model_name,
                    len(batch),
                    attempt,
                    self.max_attempts,
                    batch_hash,
                )
                response = self._client.embeddings.create(
                    model=self.model_name,
                    input=batch,
                    dimensions=self.dimensions,
                    encoding_format="float",
                )
                ordered = sorted(response.data, key=lambda item: item.index)
                if len(ordered) != len(batch):
                    raise PermanentEmbeddingError(
                        "embedding response count does not match request count"
                    )
                vectors = [self._validated_vector(item.embedding) for item in ordered]
                logger.info(
                    "embedding 请求成功：model=%s batch=%d attempt=%d elapsed=%.2fs request_id=%s",
                    self.model_name,
                    len(batch),
                    attempt,
                    time.perf_counter() - started,
                    _request_id(response) or "unknown",
                )
                return vectors
            except PermanentEmbeddingError:
                raise
            except Exception as exc:
                transient = _is_transient_error(exc)
                status = _status_code(exc)
                request_id = _request_id(exc)
                logger.warning(
                    "embedding 请求失败：model=%s batch=%d attempt=%d/%d elapsed=%.2fs "
                    "category=%s error_type=%s status=%s request_id=%s",
                    self.model_name,
                    len(batch),
                    attempt,
                    self.max_attempts,
                    time.perf_counter() - started,
                    "transient" if transient else "permanent",
                    exc.__class__.__name__,
                    status if status is not None else "unknown",
                    request_id or "unknown",
                )
                if not transient:
                    raise PermanentEmbeddingError(
                        f"permanent embedding failure ({exc.__class__.__name__}, "
                        f"status={status if status is not None else 'unknown'})"
                    ) from exc
                if attempt == self.max_attempts:
                    raise TransientEmbeddingError(
                        f"transient embedding failure after {attempt} attempts "
                        f"({exc.__class__.__name__}, "
                        f"status={status if status is not None else 'unknown'})"
                    ) from exc
                delay = min(self.backoff_seconds * (2 ** (attempt - 1)), 8.0)
                logger.info("embedding 临时错误退避 %.2fs 后重试", delay)
                time.sleep(delay)
        raise AssertionError("unreachable embedding retry state")

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for offset in range(0, len(texts), self.batch_size):
            results.extend(self._request_batch(list(texts[offset : offset + self.batch_size])))
        return results

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        cached = self._load_query_cache(text)
        if cached is not None:
            return cached
        vector = self._embed([text])[0]
        self._save_query_cache(text, vector)
        return vector


__all__ = [
    "DashScopeEmbeddingProvider",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "PermanentEmbeddingError",
    "TransientEmbeddingError",
]
