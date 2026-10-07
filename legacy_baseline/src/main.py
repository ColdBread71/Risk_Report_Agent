from __future__ import annotations

import argparse
from pathlib import Path

from src.config.model_config import DEFAULT_MODEL_CONFIG

from src.graph.builder import GraphBuilder
from src.preprocess.context_exporter import ContextExporter
from src.schemas.context import ContextDraft
from src.schemas.state import ContextState


class ProgressPrinter:
    """用于输出简洁的阶段性进度提示。"""

    def __init__(self) -> None:
        self._step = 0

    def start(self, message: str) -> None:
        self._step += 1
        print(f"[{self._step}] {message} ...", flush=True)

    def done(self, message: str) -> None:
        print(f"    ✓ {message}", flush=True)

    def info(self, message: str) -> None:
        print(f"    - {message}", flush=True)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Risk Report Agent VLM Context 阶段入口")
    parser.add_argument("pdf_path", type=str, help="输入 PDF 文件路径")
    parser.add_argument("--output-dir", type=str, default="outputs", help="本次运行的所有产物输出目录（默认 outputs）")
    parser.add_argument("--context-output-json", type=str, default=None, help="Context 初稿 JSON 输出路径（默认 <output-dir>/context_draft.json）")
    parser.add_argument("--context-output-md", type=str, default=None, help="Context 初稿 Markdown 输出路径（默认 <output-dir>/context_draft.md）")
    parser.add_argument("--context-log", type=str, default=None, help="Context 更新日志输出路径（默认 <output-dir>/context_updates.log）")
    return parser


def run_pipeline(
    pdf_path: str | Path,
    output_dir: str | Path,
    context_output_json: str | Path,
    context_output_md: str | Path,
    context_log: str | Path,
) -> None:
    progress = ProgressPrinter()

    progress.start("初始化图流水线")
    graph = GraphBuilder(output_dir=output_dir).build()
    progress.done("LangGraph 已构建")

    progress.start("准备初始状态")
    initial_state: ContextState = {
        "pdf_path": str(pdf_path),
        "total_pages": 0,
        "chapter_queue": [],
        "current_chapter_index": 0,
        "chapter_results": [],
        "context_draft": ContextDraft(),
    }
    progress.done("初始状态已准备")

    progress.start("执行 VLM 抽取流程")
    print("  - flow: initialize -> build_toc -> process_chapter* -> finalize", flush=True)
    final_state = graph.invoke(initial_state)
    progress.done("Context 状态已更新完毕")

    progress.start("导出 Context 初稿")
    exporter = ContextExporter()
    json_path = exporter.export_json(final_state["context_draft"], context_output_json)
    md_path = exporter.export_markdown(final_state["context_draft"], context_output_md)
    log_path = exporter.append_log_line(context_log, f"final_export json={json_path} md={md_path} chapters={len(final_state['chapter_queue'])}")
    progress.done(f"Context 已导出到 {json_path} 和 {md_path}")

    progress.start("汇总结果")
    progress.info(f"pdf_path: {pdf_path}")
    progress.info(f"total_pages: {final_state['total_pages']}")
    progress.info(f"chapters: {len(final_state['chapter_queue'])}")
    progress.info(f"current_chapter_index: {final_state['current_chapter_index']}")
    progress.info(f"context_json: {json_path}")
    progress.info(f"context_md: {md_path}")
    progress.info(f"context_log: {log_path}")
    progress.done("流水线执行完毕")


def main() -> None:
    if not DEFAULT_MODEL_CONFIG.api_key:
        raise RuntimeError("OPENAI_API_KEY / DASHSCOPE_API_KEY is missing")

    parser = build_argument_parser()
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    context_output_json = args.context_output_json or str(output_dir / "context_draft.json")
    context_output_md = args.context_output_md or str(output_dir / "context_draft.md")
    context_log = args.context_log or str(output_dir / "context_updates.log")

    run_pipeline(
        args.pdf_path,
        output_dir,
        context_output_json,
        context_output_md,
        context_log,
    )


if __name__ == "__main__":
    main()
