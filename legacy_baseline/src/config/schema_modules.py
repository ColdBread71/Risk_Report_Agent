from __future__ import annotations

import os
from copy import deepcopy

from src.schemas.context import ChapterExtractionResult, ContextDraft

# 可用的模块名称，与 ContextDraft 的字段名一致
AVAILABLE_MODULES = [
    "basic_info",
    "use_cases",
    "environment",
    "matrix",
    "security_functions",
    "components",
]

# 默认启用的模块列表
DEFAULT_ENABLED_MODULES: list[str] = [
    "basic_info",
    "use_cases",
    "environment",
    "matrix",
    "security_functions",
    "components",
]


def _parse_enabled_modules_from_env() -> list[str] | None:
    raw_value = os.getenv("TARA_ENABLED_CONTEXT_MODULES")
    if not raw_value:
        return None
    modules = [item.strip() for item in raw_value.split(",") if item.strip()]
    return modules or None


# 修改这里，或使用环境变量 TARA_ENABLED_CONTEXT_MODULES 控制本次运行启用哪些模块
ENABLED_MODULES: list[str] = _parse_enabled_modules_from_env() or DEFAULT_ENABLED_MODULES.copy()


def get_enabled_modules() -> list[str]:
    """返回当前启用的模块列表。"""
    return ENABLED_MODULES.copy()


def is_module_enabled(module_name: str) -> bool:
    """检查指定模块是否已启用。"""
    return module_name in ENABLED_MODULES


def build_enabled_context_schema() -> dict:
    """构建用于单章抽取的 ContextDraft 子集 schema。"""
    full_schema = ContextDraft.model_json_schema()
    properties = full_schema.get("properties", {})

    filtered_properties: dict[str, object] = {"update_thoughts": deepcopy(properties.get("update_thoughts"))}
    for module_name in ENABLED_MODULES:
        if module_name in properties:
            filtered_properties[module_name] = deepcopy(properties[module_name])

    for fixed_field in ("open_questions", "missing_items_note"):
        if fixed_field in properties:
            filtered_properties[fixed_field] = deepcopy(properties[fixed_field])

    required_fields = ["update_thoughts", *ENABLED_MODULES, "open_questions", "missing_items_note"]
    return {
        "type": "object",
        "properties": filtered_properties,
        "required": required_fields,
        "additionalProperties": False,
    }


def build_chapter_extraction_schema() -> dict:
    """构建单章抽取的完整输出 schema，其中 chapter_context 受启用模块控制。"""
    outer_schema = ChapterExtractionResult.model_json_schema()
    outer_schema["properties"] = deepcopy(outer_schema.get("properties", {}))
    outer_schema["properties"]["chapter_context"] = build_enabled_context_schema()
    return outer_schema
