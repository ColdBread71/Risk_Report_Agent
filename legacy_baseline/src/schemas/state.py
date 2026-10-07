from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel, Field

from src.schemas.context import ChapterExtractionResult, ContextDraft


class ChapterTask(BaseModel):
    chapter_title: str = Field(..., description="章节名称。")
    start_page: int = Field(..., description="章节起始页码。")
    end_page: int = Field(..., description="章节结束页码。")


class ContextState(TypedDict):
    pdf_path: str
    total_pages: int
    chapter_queue: list[ChapterTask]
    current_chapter_index: int
    chapter_results: list[ChapterExtractionResult]
    context_draft: ContextDraft
