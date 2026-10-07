from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(env_path: Path) -> None:
    """加载本地 .env 文件到进程环境变量。"""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file(Path(__file__).resolve().parents[1] / ".env")


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class ModelConfig:
    """描述当前阶段使用的模型配置。"""

    provider: str = os.getenv("DASHSCOPE_PROVIDER", "dashscope")
    embedding_model_name: str = os.getenv("DASHSCOPE_EMBEDDING_MODEL", "qwen3.7-text-embedding")
    vl_model_name: str = os.getenv("DASHSCOPE_VL_MODEL", os.getenv("DASHSCOPE_MODEL", "qwen-vl-max"))
    text_model_name: str = os.getenv("DASHSCOPE_TEXT_MODEL", os.getenv("DASHSCOPE_MODEL", "qwen-plus"))
    vl_temperature: float = _env_float("DASHSCOPE_VL_TEMPERATURE", 0.1)
    text_temperature: float = _env_float("DASHSCOPE_TEXT_TEMPERATURE", 0.1)
    api_key: str | None = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


DEFAULT_MODEL_CONFIG = ModelConfig()


def test_chat_api() -> None:
    """发送一个最小对话请求，用于检查当前模型接口是否可用。"""
    if not DEFAULT_MODEL_CONFIG.api_key:
        raise RuntimeError("OPENAI_API_KEY / DASHSCOPE_API_KEY is missing")

    try:
        import dashscope  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - dependency/import guard
        raise RuntimeError("dashscope is required for model testing") from exc

    dashscope.api_key = DEFAULT_MODEL_CONFIG.api_key
    response = dashscope.Generation.call(
        model=DEFAULT_MODEL_CONFIG.text_model_name,
        messages=[
            {"role": "system", "content": "你是一个简洁的测试助手。"},
            {"role": "user", "content": "请只回复：api test ok"},
        ],
        result_format="message",
    )
    if getattr(response, "status_code", None) != 200:
        raise RuntimeError(f"DashScope test failed: {response}")

    output = getattr(response, "output", None)
    choices = getattr(output, "choices", None) if output is not None else None
    if not choices:
        raise RuntimeError("DashScope test response missing choices")
    message = getattr(choices[0], "message", None)
    if message is None:
        raise RuntimeError("DashScope test response missing message")
    content = getattr(message, "content", None)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get("text") or item.get("content") or "")
            else:
                parts.append(getattr(item, "text", None) or getattr(item, "content", None) or "")
        text = "".join(parts)
    elif isinstance(content, str):
        text = content
    else:
        raise RuntimeError("DashScope test response missing content")

    print(text.strip())


if __name__ == "__main__":
    test_chat_api()
