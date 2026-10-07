"""Reusable parsed-document models for project evidence artifacts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DocumentBlockType(StrEnum):
    """Supported block types emitted by the deterministic PDF parser."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    FIGURE_CAPTION = "figure_caption"
    UNRESOLVED_IMAGE = "unresolved_image"


class ExtractionMethod(StrEnum):
    """Method used to create a parsed block."""

    NATIVE_TEXT = "native_text"
    TABLE_EXTRACTION = "table_extraction"
    OCR = "ocr"
    MANUAL = "manual"


class PageLabelRule(BaseModel):
    """One PDF page-label rule as exposed by PyMuPDF."""

    model_config = ConfigDict(extra="forbid")

    start_page_index: int = Field(..., ge=0)
    prefix: str = ""
    first_page_number: int = Field(default=1, ge=1)
    style: str = ""


class DocumentSectionRef(BaseModel):
    """One entry in the PDF table of contents."""

    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(..., pattern=r"^SEC-[A-F0-9]{16}$")
    toc_index: int = Field(..., ge=0)
    level: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    pdf_page: int = Field(..., ge=1)
    section_path: list[str] = Field(..., min_length=1)


class DocumentBlock(BaseModel):
    """One ordered, source-addressable unit of PDF content."""

    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(..., pattern=r"^BLK-[A-F0-9]{16}$")
    document_id: str = Field(..., pattern=r"^DOC-[A-F0-9]{12}$")
    source_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    parser_version: str = Field(..., min_length=1)
    pdf_page: int = Field(..., ge=1)
    printed_page_label: str | None = None
    block_order: int = Field(..., ge=0)
    section_id: str = Field(..., pattern=r"^SEC-[A-F0-9]{16}$")
    section_path: list[str] = Field(..., min_length=1)
    section_title: str = Field(..., min_length=1)
    block_type: DocumentBlockType
    text: str
    table_cells: list[list[str | None]] | None = None
    bbox: tuple[float, float, float, float] | None = None
    extraction_method: ExtractionMethod
    needs_review: bool = False
    review_notes: list[str] = Field(default_factory=list)


class ParsedSection(BaseModel):
    """Section artifact containing its ordered content blocks."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    document_id: str = Field(..., pattern=r"^DOC-[A-F0-9]{12}$")
    source_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    parser_version: str = Field(..., min_length=1)
    section_id: str = Field(..., pattern=r"^SEC-[A-F0-9]{16}$")
    section_path: list[str] = Field(..., min_length=1)
    section_title: str = Field(..., min_length=1)
    start_pdf_page: int = Field(..., ge=1)
    end_pdf_page: int = Field(..., ge=1)
    blocks: list[DocumentBlock]


class DocumentParseSummary(BaseModel):
    """Compact quality summary for one parsed PDF."""

    model_config = ConfigDict(extra="forbid")

    page_count: int = Field(..., ge=1)
    toc_entry_count: int = Field(..., ge=0)
    section_file_count: int = Field(..., ge=0)
    block_count: int = Field(..., ge=0)
    table_count: int = Field(..., ge=0)
    low_text_pages: list[int]
    image_only_pages: list[int]
    unmapped_pages: list[int]
    review_required_pages: list[int]


class ParsedDocument(BaseModel):
    """Document-level metadata and references to section artifacts."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    document_id: str = Field(..., pattern=r"^DOC-[A-F0-9]{12}$")
    source_file_name: str = Field(..., min_length=1)
    source_path: str = Field(..., min_length=1)
    source_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    source_size_bytes: int = Field(..., ge=1)
    parser_name: str = Field(..., min_length=1)
    parser_version: str = Field(..., min_length=1)
    parsed_at: datetime
    metadata: dict[str, str | None]
    page_label_rules: list[PageLabelRule]
    table_of_contents: list[DocumentSectionRef]
    section_files: list[str]
    summary: DocumentParseSummary


class CorpusDocumentRef(BaseModel):
    """Manifest reference to the active parsed version of a document."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(..., pattern=r"^DOC-[A-F0-9]{12}$")
    source_file_name: str = Field(..., min_length=1)
    source_path: str = Field(..., min_length=1)
    source_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    document_artifact: str = Field(..., min_length=1)
    page_count: int = Field(..., ge=1)
    section_file_count: int = Field(..., ge=0)
    review_required_pages: list[int]


class CorpusManifest(BaseModel):
    """Active parsed-document versions for one project."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    parser_name: str = Field(..., min_length=1)
    parser_version: str = Field(..., min_length=1)
    generated_at: datetime
    source_directory: str = Field(..., min_length=1)
    documents: list[CorpusDocumentRef]


__all__ = [
    "CorpusDocumentRef",
    "CorpusManifest",
    "DocumentBlock",
    "DocumentBlockType",
    "DocumentParseSummary",
    "DocumentSectionRef",
    "ExtractionMethod",
    "PageLabelRule",
    "ParsedDocument",
    "ParsedSection",
]
