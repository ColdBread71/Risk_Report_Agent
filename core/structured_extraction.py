"""Shared bounded structured-LLM extraction with validation feedback."""

import json
import os
import time
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from json_repair import repair_json
from langchain_core.runnables import ensure_config
from pydantic import ValidationError

from core.llm import LLMInputBudgetExceededError, enforce_input_token_budget
from core.logger import setup_logger


logger = setup_logger("structured_extraction")


def _save_attempt(path: Path | None, record: dict) -> None:
    """Persist only explicit request/response fields, never client or config objects."""
    if path is None:
        return
    text = json.dumps(record, ensure_ascii=False, indent=2, default=str)
    for name, value in os.environ.items():
        if value and name.upper().endswith(("API_KEY", "TOKEN", "SECRET", "PASSWORD")):
            text = text.replace(json.dumps(value, ensure_ascii=False)[1:-1], "[REDACTED]")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def extract_with_retry(
    llm,
    prompt_template: str,
    schema_class,
    sample_input: str,
    max_retries: int = 3,
    semantic_validator: Callable | None = None,
    payload_transformer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    task_label: str | None = None,
    json_schema: dict | None = None,
):
    """Execute one structured extraction with bounded validation feedback."""
    json_schema_str = json.dumps(
        json_schema if json_schema is not None else schema_class.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    base_prompt = prompt_template.format(
        json_schema=json_schema_str,
        sample_input=sample_input,
    )
    current_prompt = base_prompt
    last_exception: Exception | None = None
    runtime = ensure_config()
    configurable = runtime.get("configurable", {})
    node = runtime.get("metadata", {}).get("langgraph_node")
    call_id = uuid4().hex
    label = f"{task_label or node or schema_class.__name__}/{call_id[:8]}"
    diagnostics = configurable.get("extraction_log_dir")
    directory = Path(diagnostics) / call_id if diagnostics else None

    for attempt in range(max_retries):
        attempt_started = time.perf_counter()
        response = None
        record = {
            "run_id": configurable.get("thread_id"),
            "node": node,
            "task": task_label,
            "call_id": call_id,
            "schema": schema_class.__name__,
            "model": str(getattr(llm, "model_name", None) or getattr(llm, "model", "unknown")),
            "attempt": attempt + 1,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "started",
            "phase": "pending",
            "prompt": current_prompt,
        }
        path = directory / f"attempt-{attempt + 1}.json" if directory else None
        # Fail before a paid request if its diagnostic record cannot be saved.
        _save_attempt(path, record)
        logger.info("[%s] 发起 LLM 请求 (Attempt %d)，记录=%s", label, attempt + 1, path)
        try:
            record["phase"] = "input_budget"
            estimated_tokens = enforce_input_token_budget(current_prompt, llm)
            record["estimated_input_tokens"] = estimated_tokens
            logger.info(
                "[%s] 输入预算检查通过：estimated_input_tokens=%d",
                schema_class.__name__,
                estimated_tokens,
            )
            record["phase"] = "request"
            response = llm.invoke(current_prompt)
            record["raw_response"] = response.content
            metadata = getattr(response, "response_metadata", {}) or {}
            record["response_metadata"] = {
                key: metadata[key] for key in ("finish_reason", "token_usage", "model_name")
                if key in metadata
            }
            record["phase"] = "json_parse"
            logger.info("[%s] LLM 请求返回，开始 JSON 清洗与 Pydantic 校验", schema_class.__name__)
            parsed_data = repair_json(response.content, return_objects=True)
            record["parsed_payload"] = deepcopy(parsed_data)
            if not isinstance(parsed_data, dict):
                raise ValueError("Parsed result is not a JSON object (dictionary).")
            if payload_transformer is not None:
                record["phase"] = "payload_transform"
                parsed_data = payload_transformer(parsed_data)

            record["validation_payload"] = deepcopy(parsed_data)
            record["phase"] = "schema_validation"
            validated = schema_class.model_validate(parsed_data)
            if semantic_validator is not None:
                record["phase"] = "semantic_validation"
                validated = semantic_validator(validated)
            record["result"] = validated.model_dump(mode="json")
            record["status"] = "succeeded"
            record["phase"] = "complete"
            elapsed = time.perf_counter() - attempt_started
            logger.info("[%s] 提取并校验成功（耗时 %.2fs），记录=%s", label, elapsed, path)
            return validated
        except Exception as exc:
            last_exception = exc
            record["status"] = "failed"
            record["error_type"] = type(exc).__name__
            record["error"] = str(exc)
            record["traceback"] = traceback.format_exc()
            if isinstance(exc, ValidationError):
                record["validation_errors"] = exc.errors(include_context=False, include_url=False)
            # The complete input is already in diagnostics and the previous
            # reply. Repeating it in a root validation error bloats every retry.
            errors = record.get("validation_errors")
            feedback = json.dumps(
                [{key: error[key] for key in ("type", "loc", "msg")} for error in errors]
                if errors else str(exc), ensure_ascii=False, default=str,
            )
            elapsed = time.perf_counter() - attempt_started
            logger.warning(
                "[%s] 第 %d 次失败（耗时 %.2fs），阶段=%s，记录=%s。错误:\n%s",
                label,
                attempt + 1,
                elapsed,
                record["phase"],
                path,
                feedback,
            )
            if isinstance(exc, LLMInputBudgetExceededError):
                raise
            if attempt == max_retries - 1:
                break
            if response is None:
                # A transport failure provides no JSON for the model to correct.
                continue
            previous_output = getattr(response, "content", "") if response is not None else ""
            current_prompt = base_prompt + (
                "\n\n[系统纠错反馈：上一次生成的 JSON 未通过校验。]\n"
                f"错误原因如下：\n{feedback}\n"
                "请基于下面的上一版 JSON 修正错误，并重新输出完整的纯 JSON 对象。\n"
                "若错误涉及 EvidenceRef.quote，quote 必须是对应 block 的连续逐字原文；"
                "无法逐字复制时必须设为 null，禁止使用改写、摘要或拼接文本。\n"
                "[上一版无效 JSON]\n"
                f"{previous_output}"
            )
        finally:
            if record["status"] == "started":
                record["status"] = "interrupted"
            record["elapsed_seconds"] = round(time.perf_counter() - attempt_started, 3)
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            _save_attempt(path, record)

    raise RuntimeError(
        f"Extraction failed after {max_retries} attempts. "
        f"Task: {label}; diagnostics: {directory}. Last error: {last_exception}"
    )


__all__ = ["extract_with_retry"]
