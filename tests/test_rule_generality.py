from pathlib import Path
import re

from prompts import load_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_RULE_FILES = (
    PROJECT_ROOT / "main.py",
    *(
        path
        for directory in ("core", "nodes", "schemas", "tools", "prompts")
        for path in (PROJECT_ROOT / directory).rglob("*")
        if path.suffix in {".py", ".md"}
    ),
)

PROMPT_SEGMENTS = {
    "field_fact_extraction.md": ("field_fact",),
    "retrieval_guidance.md": (
        "generic",
        "context_functions",
        "context_components",
        "context_communications",
        "context_security_functions",
        "asset_data",
        "asset_credentials",
        "asset_software_configuration",
        "asset_hardware_network",
        "asset_external_services",
        "asset_functions",
        "asset_impacts",
    ),
    "node0_scope.md": ("scope_direct", "scope_synthesis"),
    "node1_context.md": (
        "context_direct",
        "section_common",
        "section_overview",
        "section_functions",
        "section_components",
        "section_communications",
        "context_section_template",
    ),
    "node2_assets.md": (
        "asset_direct",
        "section_common",
        "section_data_credentials_software",
        "section_systems_services",
        "section_functions_impacts",
        "asset_section_template",
        "asset_function_mapping",
    ),
    "node3_threats.md": ("threat_direct",),
}


def _production_rule_text() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in PRODUCTION_RULE_FILES
    )


def test_production_rules_do_not_embed_reference_project_terms():
    text = _production_rule_text().casefold()
    reference_project_terms = (
        "emu300a",
        "logger5000",
        "logger4000",
        "阳光云",
        "sungrow",
        "moxa",
        "mplc",
        "pid&iso",
        "insight",
        "eth3",
        "eth4",
        "9998",
        "9999",
        "4460",
        "goose",
        "nts",
        "syslog",
        "iec104",
        "光伏",
        "逆变器",
        "电表",
        "箱变",
        "站控",
        "综自",
        "快调",
        "光纤环网",
        "终端盒",
        "开关电源",
        "防雷",
        "断路器",
        "工业网络",
        "南向",
        "北向",
        "生产设备",
        "生产安全",
        "36行",
        "42项资产",
        "31项功能",
        "18项功能",
    )

    found = []
    for term in reference_project_terms:
        if term.isascii() and term.isalnum():
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text):
                found.append(term)
        elif term in text:
            found.append(term)
    assert not found


def test_business_prompts_are_external_reviewable_and_comments_are_not_loaded():
    for file_name, prompt_names in PROMPT_SEGMENTS.items():
        source = (PROJECT_ROOT / "prompts" / file_name).read_text(encoding="utf-8")
        for prompt_name in prompt_names:
            marker = f"<!-- PROMPT:{prompt_name} -->"
            marker_index = source.index(marker)
            preceding_comment = source[max(0, marker_index - 700):marker_index]
            assert "调用节点：" in preceding_comment
            assert "调用代码：" in preceding_comment
            assert "作用：" in preceding_comment
            body = load_prompt(file_name, prompt_name)
            assert body
            assert "<!--" not in body
            assert "调用节点：" not in body


def test_node_modules_do_not_embed_business_prompt_bodies():
    node_sources = "\n".join(
        (PROJECT_ROOT / "nodes" / file_name).read_text(encoding="utf-8")
        for file_name in (
            "field_extractor.py",
            "context_builder.py",
            "asset_threat_modeler.py",
        )
    )
    assert "【任务边界】" not in node_sources
    assert "【共同规则】" not in node_sources
    assert "【目标 JSON Schema】" not in node_sources


def test_production_rules_do_not_read_human_reference_outputs():
    production_paths = (
        PROJECT_ROOT / "core",
        PROJECT_ROOT / "nodes",
        PROJECT_ROOT / "schemas",
        PROJECT_ROOT / "tools",
        PROJECT_ROOT / "prompts",
    )
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for root in production_paths
        for path in root.rglob("*.py")
    ).casefold()

    assert "legacy_baseline" not in text
    assert "产品安全风险与安全需求分析-20260727" not in text
