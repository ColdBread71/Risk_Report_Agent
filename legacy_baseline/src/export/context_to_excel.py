from __future__ import annotations

import json
import shutil
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ── 中文映射表（与 docs/01_context_spec.md 对齐） ──────────────────────────

SECTION_NAMES: dict[str, str] = {
    "basic_info": "一、产品基本信息",
    "use_cases": "二、产品预期用途以及合理可预见的使用",
    "environment": "三、产品通信环境",
    "matrix": "四、产品通信矩阵",
    "security_functions": "五、产品功能场景（网络安全相关）",
    "components": "六、产品构成（数字组件）",
}

FIELD_NAMES: dict[str, dict[str, str]] = {
    "basic_info": {
        "product_name": "产品名称",
        "product_summary": "产品简介",
        "product_type": "产品类型",
        "product_model": "产品型号",
        "product_software_version": "产品软件版本",
        "product_hardware_version": "产品硬件版本",
    },
    "use_cases": {
        "intended_use": "预期用途",
        "foreseeable_use": "合理可预见的使用",
        "usage_scenarios": "适用场景",
    },
    "environment": {
        "communication_environment_description": "通信环境说明",
        "deployment_mode": "部署方式",
        "runtime_environment": "运行环境",
        "network_boundary": "网络边界",
        "trust_boundary": "信任边界",
        "southbound_communication": "南向通信",
        "northbound_communication": "北向通信",
    },
    "matrix": {
        "communication_matrix": "通信矩阵",
        "communication_targets": "通信对象",
        "communication_protocols": "通信协议",
        "interface_types": "接口类型",
        "data_flows": "数据流转",
    },
    "security_functions": {
        "function_scenario_descriptions": "功能场景描述",
        "core_functions": "核心功能",
        "security_related_functions": "网络安全相关功能",
        "management_functions": "管理功能",
        "known_limitations": "已知限制",
    },
    "components": {
        "product_components": "产品构成",
        "digital_components": "数字组件",
        "modules": "模块划分",
        "external_dependencies": "外部依赖",
    },
}

EXTRA_FIELDS: list[tuple[str, str]] = [
    ("open_questions", "待确认项"),
    ("missing_items_note", "缺失项说明"),
]

# ── 样式常量 ────────────────────────────────────────────────────────────────

TITLE_FONT = Font(name="微软雅黑", size=14, bold=True)
SECTION_FONT = Font(name="微软雅黑", size=11, bold=True, color="FFFFFF")
FIELD_FONT = Font(name="微软雅黑", size=10, bold=True)
VALUE_FONT = Font(name="微软雅黑", size=10)
SECTION_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
LABEL_FILL = PatternFill(start_color="D9E2F3", end_color="D9E2F3", fill_type="solid")
THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)
WRAP_ALIGNMENT = Alignment(wrap_text=True, vertical="top")
CENTER_ALIGNMENT = Alignment(horizontal="center", vertical="center")


def _format_value(value: object) -> str:
    """将 JSON 值格式化为可读文本。"""
    if value is None:
        return "无"
    if isinstance(value, list):
        if not value:
            return "无"
        return "\n".join(f"• {item}" for item in value)
    if isinstance(value, str):
        return value.strip()
    return str(value)


def build_context_to_excel(input_path: str | Path, output_path: str | Path) -> Path:
    """读取 final_context.json 并生成阅读友好的 Excel。"""
    # 读取 JSON
    input_path = Path(input_path)
    data = json.loads(input_path.read_text(encoding="utf-8"))

    wb = Workbook()
    ws = wb.active
    ws.title = "Context 初稿"
    ws.sheet_properties.tabColor = "4472C4"

    # 列宽
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 120

    # 全表自动换行
    for col in ("A", "B", "C"):
        for cell in ws[col]:
            cell.alignment = WRAP_ALIGNMENT if col != "A" else Alignment(horizontal="center", vertical="center", wrap_text=True)

    # 行高自适应（显式换行 + 按新列宽自动折行 都算进去）
    def _auto_row_height(row_num: int) -> None:
        cells = [ws.cell(row=row_num, column=2), ws.cell(row=row_num, column=3)]
        total_lines = 1
        for value_cell in cells:
            text = value_cell.value or ""
            lines = str(text).split("\n")
            # C 列更宽：120；中文按每字符约 2 宽度单位估算，约每行 60 个中文字
            chars_per_line = 60 if value_cell.column == 3 else 18
            for line in lines:
                total_lines += max(1, -(-len(line) // chars_per_line)) - 1
        # 每行约 18pt，下限 20pt，上限 520pt
        ws.row_dimensions[row_num].height = min(max(total_lines * 18, 20), 520)

    row = 1

    # ── 标题行 ──────────────────────────────────────────────────────────
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    title_cell = ws.cell(row=row, column=1, value="Context 初稿 — 产品画像")
    title_cell.font = TITLE_FONT
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    for c in range(1, 4):
        ws.cell(row=row, column=c).border = THIN_BORDER
    row += 2

    # ── 表头 ────────────────────────────────────────────────────────────
    headers = ["序号", "字段名称", "内容"]
    for col, text in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        cell.alignment = CENTER_ALIGNMENT
        cell.border = THIN_BORDER
    row += 1

    seq = 0

    # ── 遍历各模块 ──────────────────────────────────────────────────────
    for section_key, section_title in SECTION_NAMES.items():
        section_data = data.get(section_key, {})
        field_map = FIELD_NAMES.get(section_key, {})

        # 检查该模块是否有内容
        has_content = any(
            section_data.get(field_key) not in (None, [], "", {})
            for field_key in field_map
        )
        if not has_content:
            continue

        # 模块标题行
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        cell = ws.cell(row=row, column=1, value=section_title)
        cell.font = SECTION_FONT
        cell.fill = SECTION_FILL
        cell.alignment = Alignment(vertical="center")
        for c in range(1, 4):
            ws.cell(row=row, column=c).border = THIN_BORDER
            ws.cell(row=row, column=c).fill = SECTION_FILL
        row += 1

        for field_key, chinese_name in field_map.items():
            raw_value = section_data.get(field_key)
            if raw_value in (None, [], "", {}):
                continue

            seq += 1
            ws.cell(row=row, column=1, value=seq).font = VALUE_FONT
            ws.cell(row=row, column=1).alignment = CENTER_ALIGNMENT
            ws.cell(row=row, column=1).border = THIN_BORDER

            label_cell = ws.cell(row=row, column=2, value=chinese_name)
            label_cell.font = FIELD_FONT
            label_cell.fill = LABEL_FILL
            label_cell.alignment = WRAP_ALIGNMENT
            label_cell.border = THIN_BORDER

            value_cell = ws.cell(row=row, column=3, value=_format_value(raw_value))
            value_cell.font = VALUE_FONT
            value_cell.alignment = WRAP_ALIGNMENT
            value_cell.border = THIN_BORDER

            _auto_row_height(row)
            row += 1

    # ── 额外字段（open_questions / missing_items_note） ──────────────────
    extra_data = []
    for field_key, chinese_name in EXTRA_FIELDS:
        raw_value = data.get(field_key, [])
        if raw_value not in (None, [], ""):
            extra_data.append((chinese_name, raw_value))

    if extra_data:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        cell = ws.cell(row=row, column=1, value="七、待确认与缺失项")
        cell.font = SECTION_FONT
        cell.fill = SECTION_FILL
        cell.alignment = Alignment(vertical="center")
        for c in range(1, 4):
            ws.cell(row=row, column=c).border = THIN_BORDER
            ws.cell(row=row, column=c).fill = SECTION_FILL
        row += 1

        for chinese_name, raw_value in extra_data:
            seq += 1
            ws.cell(row=row, column=1, value=seq).font = VALUE_FONT
            ws.cell(row=row, column=1).alignment = CENTER_ALIGNMENT
            ws.cell(row=row, column=1).border = THIN_BORDER

            label_cell = ws.cell(row=row, column=2, value=chinese_name)
            label_cell.font = FIELD_FONT
            label_cell.fill = LABEL_FILL
            label_cell.alignment = WRAP_ALIGNMENT
            label_cell.border = THIN_BORDER

            value_cell = ws.cell(row=row, column=3, value=_format_value(raw_value))
            value_cell.font = VALUE_FONT
            value_cell.alignment = WRAP_ALIGNMENT
            value_cell.border = THIN_BORDER

            _auto_row_height(row)
            row += 1

    # ── 保存 ────────────────────────────────────────────────────────────
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    print(f"✓ Excel 已导出到 {output_path}")
    return output_path


def find_latest_final_context() -> Path | None:
    """在 outputs/ 下找最新的 final_context.json。"""
    outputs_dir = Path("outputs")
    if not outputs_dir.exists():
        return None
    candidates = sorted(outputs_dir.glob("final_context.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def main() -> None:
    src = find_latest_final_context()
    if src is None:
        print("✗ 未找到 outputs/final_context.json，请先运行 pipeline。")
        return

    dest = Path("outputs/context_draft.xlsx")
    print(f"输入: {src}")
    build_context_to_excel(src, dest)
    print(f"完成。")


if __name__ == "__main__":
    main()