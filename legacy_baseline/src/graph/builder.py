from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from src.graph.nodes import GraphNodes
from src.schemas.state import ContextState


class GraphBuilder:
    """构建基于章节阅读任务的 Context 抽取图。"""

    def __init__(self, output_dir: str | Path = "outputs") -> None:
        self._nodes = GraphNodes(output_dir=output_dir)

    def build(self):
        graph = StateGraph(ContextState)
        graph.add_node("node_initialize", self._nodes.node_initialize)
        graph.add_node("node_build_toc", self._nodes.node_build_toc)
        graph.add_node("node_process_chapter", self._nodes.node_process_chapter)
        graph.add_node("node_finalize", self._nodes.node_finalize)

        graph.set_entry_point("node_initialize")
        graph.add_edge("node_initialize", "node_build_toc")
        graph.add_edge("node_build_toc", "node_process_chapter")
        graph.add_conditional_edges(
            "node_process_chapter",
            self._should_continue,
            {
                "continue": "node_process_chapter",
                "end": "node_finalize",
            },
        )
        graph.add_edge("node_finalize", END)
        return graph.compile()

    def _should_continue(self, state: ContextState) -> str:
        if state["current_chapter_index"] < len(state["chapter_queue"]):
            return "continue"
        return "end"
