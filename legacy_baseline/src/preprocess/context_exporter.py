from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.schemas.context import ChapterExtractionResult, ContextDraft


class ContextExporter:
    """将 Context 初稿导出为可查看结果，并支持增量写入。"""

    def export_json(self, draft: ContextDraft, output_path: str | Path) -> Path:
        """导出 Context JSON。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def export_markdown(self, draft: ContextDraft, output_path: str | Path) -> Path:
        """导出 Context Markdown。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = ["# Context 初稿", ""]
        lines.extend(self._render_section("更新思考", draft.update_thoughts))
        lines.extend(self._render_section("产品基本信息", draft.basic_info.model_dump()))
        lines.extend(self._render_section("预期用途与合理可预见使用", draft.use_cases.model_dump()))
        lines.extend(self._render_section("通信环境", draft.environment.model_dump()))
        lines.extend(self._render_section("通信矩阵", draft.matrix.model_dump()))
        lines.extend(self._render_section("安全功能场景", draft.security_functions.model_dump()))
        lines.extend(self._render_section("数字组件", draft.components.model_dump()))
        lines.extend(self._render_list_section("待确认项", draft.open_questions))
        lines.extend(self._render_list_section("缺失项说明", draft.missing_items_note))
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def export_chapter_result(self, result: ChapterExtractionResult, output_base_path: str | Path) -> tuple[Path, Path]:
        """同时导出单章抽取结果的 JSON 和 Markdown 版本。"""
        base_path = Path(output_base_path)
        json_path = base_path.with_suffix(".json")
        md_path = base_path.with_suffix(".md")

        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(result.model_dump_json(indent=2, ensure_ascii=False), encoding="utf-8")

        md_lines: list[str] = ["# Chapter Extraction Result", ""]
        md_lines.extend(self._render_section("章节总结", result.chapter_summary))
        md_lines.extend(self._render_list_section("高价值信息", result.key_facts))
        md_lines.extend(self._render_section("章节 Context", result.chapter_context.model_dump()))
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        return json_path, md_path

    def write_snapshot(self, draft: ContextDraft, json_path: str | Path, md_path: str | Path) -> tuple[Path, Path]:
        """同时写入 JSON 和 Markdown 快照。"""
        return self.export_json(draft, json_path), self.export_markdown(draft, md_path)

    def append_log_line(self, log_path: str | Path, message: str) -> Path:
        """向日志文件追加一行记录。"""
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        line = f"[{timestamp}] {message}"
        content = f"{existing}{line}\n" if existing else f"{line}\n"
        path.write_text(content, encoding="utf-8")
        return path

    def _render_section(self, title: str, payload: dict | str | None) -> list[str]:
        return [f"## {title}", "", "```json", json.dumps(payload, ensure_ascii=False, indent=2), "```", ""]

    def _render_list_section(self, title: str, items: list) -> list[str]:
        lines = [f"## {title}", ""]
        if not items:
            lines.extend(["- 无", ""])
            return lines
        for item in items:
            if isinstance(item, dict):
                lines.append(f"- `{json.dumps(item, ensure_ascii=False)}`")
            else:
                lines.append(f"- {item}")
        lines.append("")
        return lines
