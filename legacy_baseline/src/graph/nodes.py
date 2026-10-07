from __future__ import annotations

from pathlib import Path

from src.config.schema_modules import build_chapter_extraction_schema, get_enabled_modules
from src.io.document import PDFImageRenderer
from src.llm.extractor import ContextLLMExtractor
from src.preprocess.context_exporter import ContextExporter
from src.schemas.context import ChapterExtractionResult, ContextDraft
from src.schemas.state import ChapterTask, ContextState


class GraphNodes:
    """承载 LangGraph 各节点的业务逻辑。"""

    def __init__(self, output_dir: str | Path = "outputs") -> None:
        self._renderer = PDFImageRenderer()
        self._extractor = ContextLLMExtractor()
        self._exporter = ContextExporter()
        self._output_dir = Path(output_dir)
        self._intermediate_dir = self._output_dir / "intermediate"

    def node_initialize(self, state: ContextState) -> ContextState:
        print("[node_initialize] 读取 PDF 页数并初始化上下文", flush=True)
        state["total_pages"] = self._renderer.get_total_pages(state["pdf_path"])
        state["chapter_queue"] = []
        state["current_chapter_index"] = 0
        state["chapter_results"] = []
        state["context_draft"] = ContextDraft()
        enabled_modules = get_enabled_modules()
        self._exporter.append_log_line(
            self._output_dir / "pipeline.log",
            f"initialize total_pages={state['total_pages']} enabled_modules={enabled_modules}",
        )
        print(f"[node_initialize] total_pages={state['total_pages']} enabled_modules={enabled_modules}", flush=True)
        return state

    def node_build_toc(self, state: ContextState) -> ContextState:
        if state.get("chapter_queue"):
            print("[node_build_toc] 检测到已有 chapter_queue，跳过 TOC 提取", flush=True)
            return state

        toc_end_page = min(10, state["total_pages"])
        print(f"[node_build_toc] 渲染目录探测页 1-{toc_end_page}", flush=True)
        images = self._renderer.render_pages_to_base64(state["pdf_path"], 1, toc_end_page)
        print(f"[node_build_toc] 已得到 {len(images)} 张目录图片，开始调用抽取器", flush=True)
        chapter_queue = self._extractor.extract_toc(images)
        state["chapter_queue"] = chapter_queue
        state["current_chapter_index"] = 0
        print(f"[node_build_toc] 识别到 {len(chapter_queue)} 个章节", flush=True)
        return state

    def node_process_chapter(self, state: ContextState) -> ContextState:
        current_index = state["current_chapter_index"]
        if current_index >= len(state["chapter_queue"]):
            print("[node_process_chapter] 章节队列已处理完毕", flush=True)
            return state

        chapter: ChapterTask = state["chapter_queue"][current_index]
        total_pages = state["total_pages"]
        start_page = max(1, min(chapter.start_page, total_pages))
        end_page = max(start_page, min(chapter.end_page, total_pages))
        if start_page != chapter.start_page or end_page != chapter.end_page:
            print(
                f"[node_process_chapter] 页码已裁剪: {chapter.start_page}-{chapter.end_page} -> {start_page}-{end_page}",
                flush=True,
            )

        print(
            f"[node_process_chapter] 正在处理第 {current_index + 1}/{len(state['chapter_queue'])} 章: "
            f"{chapter.chapter_title} ({start_page}-{end_page})",
            flush=True,
        )
        images = self._renderer.render_pages_to_base64(
            state["pdf_path"],
            start_page,
            end_page,
        )
        print(f"[node_process_chapter] 已渲染 {len(images)} 张章节图片，开始调用抽取器", flush=True)

        chapter_schema = build_chapter_extraction_schema()
        chapter_result = self._extractor.extract_chapter_result(images, chapter_schema)
        state["chapter_results"].append(chapter_result)
        self._write_intermediate_result(current_index + 1, chapter_result)

        state["current_chapter_index"] = current_index + 1
        self._exporter.append_log_line(
            self._output_dir / "pipeline.log",
            f"chapter={current_index + 1} title={chapter.chapter_title} pages={start_page}-{end_page} summary={chapter_result.chapter_summary} facts={len(chapter_result.key_facts)}",
        )
        print(f"[node_process_chapter] 已完成章节抽取，current_chapter_index={state['current_chapter_index']}", flush=True)
        return state

    def node_finalize(self, state: ContextState) -> ContextState:
        print("[node_finalize] 正在综合所有章节结果", flush=True)
        chapter_contexts = [result.chapter_context.model_dump(mode="json") for result in state["chapter_results"]]
        enabled_modules = get_enabled_modules()
        final_context = self._extractor.reduce_context(chapter_contexts, enabled_modules)
        state["context_draft"] = final_context

        self._exporter.append_log_line(
            self._output_dir / "pipeline.log",
            f"finalize total_pages={state['total_pages']} chapters={len(state['chapter_queue'])} processed={state['current_chapter_index']} enabled_modules={enabled_modules}",
        )
        self._exporter.export_json(final_context, self._output_dir / "final_context.json")
        print(f"[node_finalize] 收口完成 enabled_modules={enabled_modules}", flush=True)
        return state

    def _write_intermediate_result(self, chapter_index: int, result: ChapterExtractionResult) -> None:
        self._intermediate_dir.mkdir(parents=True, exist_ok=True)
        base_path = self._intermediate_dir / f"chapter_{chapter_index}"
        self._exporter.export_chapter_result(result, base_path)
