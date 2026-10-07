"""Shared bounded structured-LLM extraction with validation feedback."""

import json
import time
from typing import Any, Callable

from json_repair import repair_json

from core.llm import LLMInputBudgetExceededError, enforce_input_token_budget
from core.logger import setup_logger


logger = setup_logger("structured_extraction")


def extract_with_retry(
    llm,
    prompt_template: str,
    schema_class,
    sample_input: str,
    max_retries: int = 3,
    semantic_validator: Callable | None = None,
    payload_transformer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
):
    """Execute one structured extraction with bounded validation feedback."""
    json_schema_str = json.dumps(
        schema_class.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    base_prompt = prompt_template.format(
        json_schema=json_schema_str,
        sample_input=sample_input,
    )
    current_prompt = base_prompt
    last_exception: Exception | None = None

    for attempt in range(max_retries):
        attempt_started = time.perf_counter()
        response = None
        logger.info("[%s] 发起 LLM 请求 (Attempt %d)...", schema_class.__name__, attempt + 1)
        try:
            estimated_tokens = enforce_input_token_budget(current_prompt, llm)
            logger.info(
                "[%s] 输入预算检查通过：estimated_input_tokens=%d",
                schema_class.__name__,
                estimated_tokens,
            )
            response = llm.invoke(current_prompt)
            logger.info("[%s] LLM 请求返回，开始 JSON 清洗与 Pydantic 校验", schema_class.__name__)
            parsed_data = repair_json(response.content, return_objects=True)
            if not isinstance(parsed_data, dict):
                raise ValueError("Parsed result is not a JSON object (dictionary).")
            if payload_transformer is not None:
                parsed_data = payload_transformer(parsed_data)

            validated = schema_class.model_validate(parsed_data)
            if semantic_validator is not None:
                validated = semantic_validator(validated)
            elapsed = time.perf_counter() - attempt_started
            logger.info("[%s] 提取并校验成功（耗时 %.2fs）", schema_class.__name__, elapsed)
            return validated
        except LLMInputBudgetExceededError:
            logger.error(
                "[%s] 输入预算检查失败；请求未发送至 LLM",
                schema_class.__name__,
            )
            raise
        except Exception as exc:
            last_exception = exc
            elapsed = time.perf_counter() - attempt_started
            logger.warning(
                "[%s] 第 %d 次校验失败（耗时 %.2fs）。完整错误:\n%s",
                schema_class.__name__,
                attempt + 1,
                elapsed,
                exc,
            )
            if attempt == max_retries - 1:
                break
            previous_output = getattr(response, "content", "") if response is not None else ""
            current_prompt = base_prompt + (
                "\n\n[系统纠错反馈：上一次生成的 JSON 未通过校验。]\n"
                f"错误原因如下：\n{exc}\n"
                "请基于下面的上一版 JSON 修正错误，并重新输出完整的纯 JSON 对象。\n"
                "若错误涉及 EvidenceRef.quote，quote 必须是对应 block 的连续逐字原文；"
                "无法逐字复制时必须设为 null，禁止使用改写、摘要或拼接文本。\n"
                "[上一版无效 JSON]\n"
                f"{previous_output}"
            )

    raise RuntimeError(
        f"Extraction failed after {max_retries} attempts. Last error: {last_exception}"
    )


__all__ = ["extract_with_retry"]
