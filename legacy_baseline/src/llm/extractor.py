from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from json_repair import repair_json
from openai import OpenAI

from src.config.model_config import DEFAULT_MODEL_CONFIG
from src.schemas.context import ChapterExtractionResult, ContextDraft
from src.schemas.state import ChapterTask


class ContextLLMExtractor:
    """使用 VLM 完成目录识别与章节 Context 抽取。"""

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=DEFAULT_MODEL_CONFIG.api_key,
            base_url=DEFAULT_MODEL_CONFIG.base_url,
        )
        self._toc_model = DEFAULT_MODEL_CONFIG.vl_model_name
        self._chapter_model = DEFAULT_MODEL_CONFIG.vl_model_name
        self._reduce_model = DEFAULT_MODEL_CONFIG.text_model_name
        self._vl_temperature = DEFAULT_MODEL_CONFIG.vl_temperature
        self._text_temperature = DEFAULT_MODEL_CONFIG.text_temperature
        self._max_json_retries = int(os.getenv("JSON_REPAIR_MAX_RETRIES", "2"))
        self._prompts_dir = Path(__file__).resolve().parents[2] / "prompts"

    def extract_toc(self, base64_images: list[str]) -> list[ChapterTask]:
        """从前置页面图片中识别目录并返回章节任务列表。"""
        schema = {
            "type": "object",
            "properties": {
                "chapters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "chapter_title": {"type": "string"},
                            "start_page": {"type": "integer"},
                            "end_page": {"type": "integer"},
                        },
                        "required": ["chapter_title", "start_page", "end_page"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["chapters"],
            "additionalProperties": False,
        }

        response = self._client.chat.completions.create(
            model=self._toc_model,
            messages=self._build_toc_messages(base64_images),
            temperature=self._vl_temperature,
            response_format={"type": "json_schema", "json_schema": {"name": "toc_schema", "schema": schema}},
        )
        self._dump_raw_response(response, "toc")
        payload = self._parse_json_response(response)
        chapters = payload.get("chapters", [])
        return [ChapterTask.model_validate(item) for item in chapters]

    def extract_chapter_result(self, base64_images: list[str], chapter_schema: dict[str, Any]) -> ChapterExtractionResult:
        """根据章节图片抽取单章中间结果。"""
        response = self._client.chat.completions.create(
            model=self._chapter_model,
            messages=self._build_chapter_messages(base64_images, chapter_schema),
            temperature=self._vl_temperature,
        )
        self._dump_raw_response(response, "chapter_result")
        payload = self._parse_json_response(response)
        return ChapterExtractionResult.model_validate(payload)

    def reduce_context(self, chapter_contexts: list[dict[str, Any]], enabled_modules: list[str]) -> ContextDraft:
        """将所有章节局部 Context 综合为最终 ContextDraft。"""
        response = self._client.chat.completions.create(
            model=self._reduce_model,
            messages=self._build_reduce_messages(chapter_contexts, enabled_modules),
            temperature=self._text_temperature,
        )
        self._dump_raw_response(response, "final_context")
        payload = self._parse_json_response(response)
        return ContextDraft.model_validate(payload)

    def _build_toc_messages(self, base64_images: list[str]) -> list[dict[str, Any]]:
        prompt_text = self._read_prompt("toc_prompt.md")
        content_list: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
        for image in base64_images:
            content_list.append({"type": "image_url", "image_url": {"url": image}})
        return [{"role": "user", "content": content_list}]

    def _build_chapter_messages(self, base64_images: list[str], chapter_schema: dict[str, Any]) -> list[dict[str, Any]]:
        prompt_text = self._read_prompt("chapter_context_prompt.md")
        schema_text = json.dumps(chapter_schema, ensure_ascii=False, indent=2)
        merged_prompt = f"{prompt_text}\n\n【本次启用的 Schema 范围】\n{schema_text}"
        print(f"[DEBUG] chapter prompt 长度={len(merged_prompt)} schema 字段={list(chapter_schema.get('properties', {}).keys())}", flush=True)
        content_list: list[dict[str, Any]] = [{"type": "text", "text": merged_prompt}]
        for image in base64_images:
            content_list.append({"type": "image_url", "image_url": {"url": image}})
        return [{"role": "user", "content": content_list}]

    def _build_reduce_messages(self, chapter_contexts: list[dict[str, Any]], enabled_modules: list[str]) -> list[dict[str, Any]]:
        prompt_text = self._read_prompt("context.md")
        enabled_modules_text = json.dumps(enabled_modules, ensure_ascii=False, indent=2)
        contexts_text = json.dumps(chapter_contexts, ensure_ascii=False, indent=2)
        merged_prompt = (
            f"{prompt_text}\n\n【本次启用的 Schema 范围】\n{enabled_modules_text}\n\n"
            f"【各章节局部 Context】\n{contexts_text}"
        )
        return [{"role": "user", "content": merged_prompt}]

    def _read_prompt(self, filename: str) -> str:
        path = self._prompts_dir / filename
        return path.read_text(encoding="utf-8")

    def _dump_raw_response(self, response: Any, tag: str) -> None:
        """把模型原始响应写入 outputs/debug/ 目录，方便排查。"""
        from datetime import datetime

        content = response.choices[0].message.content
        if isinstance(content, list):
            text = "".join(part.text if hasattr(part, "text") else getattr(part, "content", "") for part in content)
        else:
            text = str(content)

        debug_dir = Path("outputs/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%H%M%S")
        path = debug_dir / f"{timestamp}_{tag}.txt"
        path.write_text(text, encoding="utf-8")

    def _parse_json_response(self, response: Any) -> dict[str, Any]:
        content = response.choices[0].message.content
        if isinstance(content, list):
            text = "".join(part.text if hasattr(part, "text") else getattr(part, "content", "") for part in content)
        else:
            text = str(content)

        last_error: Exception | None = None
        for attempt in range(1, self._max_json_retries + 1):
            candidates = self._build_json_candidates(text)
            for candidate in candidates:
                parsed = self._try_parse_json(candidate)
                if parsed is not None:
                    return parsed

            if attempt < self._max_json_retries:
                repaired = self._repair_json_text(text)
                if repaired and repaired != text:
                    text = repaired
                    continue

        preview = text[:500].replace("\n", "\\n")
        raise RuntimeError(
            f"VLM 返回的内容不是合法 JSON，已重试 {self._max_json_retries} 次仍失败。\n原始响应前 500 字符: {preview}"
        ) from last_error

    def _build_json_candidates(self, text: str) -> list[str]:
        normalized = self._normalize_json_text(text)
        candidates = [normalized]
        extracted = self._extract_json_candidate(normalized)
        if extracted and extracted not in candidates:
            candidates.insert(0, extracted)
        return candidates

    def _try_parse_json(self, text: str) -> dict[str, Any] | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _repair_json_text(self, text: str) -> str | None:
        normalized = self._normalize_json_text(text)
        try:
            repaired = repair_json(normalized)
        except Exception:
            return None
        if isinstance(repaired, str):
            return repaired
        return json.dumps(repaired, ensure_ascii=False)

    def _normalize_json_text(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        return text

    def _extract_json_candidate(self, text: str) -> str | None:
        start_positions = [index for index, char in enumerate(text) if char in "{["]
        if not start_positions:
            return None

        for start in start_positions:
            candidate = self._extract_balanced_json(text, start)
            if candidate is not None:
                return candidate
        return None

    def _extract_balanced_json(self, text: str, start: int) -> str | None:
        opening = text[start]
        stack: list[str] = []
        in_string = False
        escape = False

        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue
            if char in "[{":
                stack.append(char)
                continue
            if char in "]}":
                if not stack:
                    return None
                last = stack.pop()
                expected = "]" if last == "[" else "}"
                if char != expected:
                    return None
                if not stack:
                    if opening == "{" and char == "}":
                        return text[start : index + 1]
                    if opening == "[" and char == "]":
                        return text[start : index + 1]
        return None
