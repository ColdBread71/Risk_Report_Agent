"""LLM factory and request-budget guards for structured extraction."""

import os
from functools import lru_cache
from pathlib import Path

import tiktoken
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


_DEFAULT_MODEL = "qwen-max"
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Provider input limits for the moving aliases used by this project. An explicit
# environment override is available for pinned snapshots or regional endpoints.
_MODEL_INPUT_TOKEN_LIMITS = {
    "qwen-max": 30_720,
    "qwen-plus": 997_952,
}
_INPUT_BUDGET_RATIO = 0.90
_CHAT_MESSAGE_OVERHEAD_TOKENS = 32


class LLMInputBudgetExceededError(ValueError):
    """Raised before an API call when a prompt exceeds its safe input budget."""


@lru_cache(maxsize=1)
def _token_encoding():
    """Return a stable local tokenizer used for conservative preflight estimates."""
    return tiktoken.get_encoding("cl100k_base")


def estimate_text_tokens(text: str) -> int:
    """Estimate tokens for text material without chat-message overhead."""
    return len(_token_encoding().encode(text, disallowed_special=()))


def estimate_input_tokens(prompt: str) -> int:
    """Estimate chat input tokens locally without sending customer evidence."""
    return estimate_text_tokens(prompt) + _CHAT_MESSAGE_OVERHEAD_TOKENS


def _resolve_model_name(llm) -> str:
    """Read a model name from ChatOpenAI or a compatible test double."""
    return str(getattr(llm, "model_name", None) or getattr(llm, "model", "unknown"))


def get_input_token_limit(model_name: str) -> int | None:
    """Resolve an optional provider limit, preferring an explicit deployment override."""
    override = os.getenv("DASHSCOPE_TEXT_INPUT_TOKEN_LIMIT")
    if override:
        try:
            limit = int(override)
        except ValueError as exc:
            raise ValueError("DASHSCOPE_TEXT_INPUT_TOKEN_LIMIT must be a positive integer") from exc
        if limit <= 0:
            raise ValueError("DASHSCOPE_TEXT_INPUT_TOKEN_LIMIT must be a positive integer")
        return limit

    normalized = model_name.strip().lower()
    return _MODEL_INPUT_TOKEN_LIMITS.get(normalized)


def enforce_input_token_budget(prompt: str, llm) -> int:
    """Reject oversized prompts before invoking the external model endpoint."""
    model_name = _resolve_model_name(llm)
    provider_limit = get_input_token_limit(model_name)
    estimated_tokens = estimate_input_tokens(prompt)
    if provider_limit is None:
        return estimated_tokens

    safe_budget = int(provider_limit * _INPUT_BUDGET_RATIO)
    if estimated_tokens > safe_budget:
        over_by = estimated_tokens - safe_budget
        raise LLMInputBudgetExceededError(
            "LLM input budget exceeded before request: "
            f"model={model_name}, estimated_input_tokens={estimated_tokens}, "
            f"safe_budget={safe_budget}, provider_input_limit={provider_limit}, "
            f"over_budget_by={over_by}, prompt_characters={len(prompt)}. "
            "Reduce the evidence set with node/field-specific retrieval before retrying."
        )
    return estimated_tokens


def get_llm() -> ChatOpenAI:
    """Create a deterministic OpenAI-compatible chat model for structured output."""
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY or DASHSCOPE_API_KEY is not configured")

    model = os.getenv(
        "DASHSCOPE_TEXT_MODEL",
        os.getenv("DASHSCOPE_MODEL", os.getenv("OPENAI_MODEL", _DEFAULT_MODEL)),
    )
    temperature = float(
        os.getenv("DASHSCOPE_TEXT_TEMPERATURE", os.getenv("OPENAI_TEMPERATURE", "0"))
    )

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=os.getenv("OPENAI_BASE_URL", _DEFAULT_BASE_URL),
        temperature=temperature,
    )


__all__ = [
    "LLMInputBudgetExceededError",
    "enforce_input_token_budget",
    "estimate_input_tokens",
    "estimate_text_tokens",
    "get_input_token_limit",
    "get_llm",
]
