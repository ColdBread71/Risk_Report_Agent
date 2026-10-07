"""Schemas for deterministic corpus lookup and curated evidence packets."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.document import DocumentBlock


class EvidenceTargetNode(StrEnum):
    """Workflow nodes supported by the first evidence-packet contract."""

    SCOPE = "node_0"
    CONTEXT = "node_1"
    ASSETS = "node_2"
    THREATS = "node_3"


class EvidenceSelectorKind(StrEnum):
    """One deterministic selector modality."""

    SECTION_IDS = "section_ids"
    SECTION_PATH_PREFIX = "section_path_prefix"
    PAGE_RANGE = "page_range"
    BLOCK_IDS = "block_ids"


class EvidencePacketSelection(BaseModel):
    """One reviewed rule selecting blocks from exactly one source document."""

    model_config = ConfigDict(extra="forbid")

    selection_id: str = Field(..., pattern=r"^SEL-[A-Z0-9_-]+$")
    document_id: str = Field(..., pattern=r"^DOC-[A-F0-9]{12}$")
    selector_kind: EvidenceSelectorKind
    section_ids: list[str] = Field(default_factory=list)
    section_path_prefix: list[str] = Field(default_factory=list)
    pdf_page_start: int | None = Field(default=None, ge=1)
    pdf_page_end: int | None = Field(default=None, ge=1)
    block_ids: list[str] = Field(default_factory=list)
    rationale: str = Field(..., min_length=1)
    target_nodes: list[EvidenceTargetNode] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_selector_payload(self) -> "EvidencePacketSelection":
        """Require only the payload belonging to the declared selector kind."""
        populated = {
            EvidenceSelectorKind.SECTION_IDS: bool(self.section_ids),
            EvidenceSelectorKind.SECTION_PATH_PREFIX: bool(self.section_path_prefix),
            EvidenceSelectorKind.PAGE_RANGE: self.pdf_page_start is not None or self.pdf_page_end is not None,
            EvidenceSelectorKind.BLOCK_IDS: bool(self.block_ids),
        }
        if not populated[self.selector_kind] or sum(populated.values()) != 1:
            raise ValueError("Exactly the declared selector payload must be populated")
        if self.selector_kind == EvidenceSelectorKind.PAGE_RANGE:
            if self.pdf_page_start is None or self.pdf_page_end is None:
                raise ValueError("Page-range selectors require both start and end pages")
            if self.pdf_page_start > self.pdf_page_end:
                raise ValueError("pdf_page_start must not exceed pdf_page_end")
        if len(self.target_nodes) != len(set(self.target_nodes)):
            raise ValueError("target_nodes must be unique")
        if len(self.section_ids) != len(set(self.section_ids)):
            raise ValueError("section_ids must be unique")
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("block_ids must be unique")
        if any(not part.strip() for part in self.section_path_prefix):
            raise ValueError("section_path_prefix components must be non-empty")
        return self


class EvidencePacketGap(BaseModel):
    """Known limitation retained with the project-specific packet."""

    model_config = ConfigDict(extra="forbid")

    gap_id: str = Field(..., pattern=r"^GAP-[A-Z0-9_-]+$")
    description: str = Field(..., min_length=1)
    affected_nodes: list[EvidenceTargetNode] = Field(..., min_length=1)
    disposition: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_unique_nodes(self) -> "EvidencePacketGap":
        if len(self.affected_nodes) != len(set(self.affected_nodes)):
            raise ValueError("affected_nodes must be unique")
        return self


class EvidencePacketConfig(BaseModel):
    """Static, reviewable instructions for constructing one packet version."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    packet_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]+$")
    packet_version: int = Field(..., ge=1)
    project_id: str = Field(..., min_length=1)
    purpose: str = Field(..., min_length=1)
    manifest_path: str = Field(..., min_length=1)
    selections: list[EvidencePacketSelection] = Field(..., min_length=1)
    known_gaps: list[EvidencePacketGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "EvidencePacketConfig":
        """Keep selection and gap identities stable and unambiguous."""
        selection_ids = [item.selection_id for item in self.selections]
        gap_ids = [item.gap_id for item in self.known_gaps]
        if len(selection_ids) != len(set(selection_ids)):
            raise ValueError("selection_id values must be unique")
        if len(gap_ids) != len(set(gap_ids)):
            raise ValueError("gap_id values must be unique")
        return self


class EvidenceSelectionSummary(BaseModel):
    """Resolved result of one configured selection rule."""

    model_config = ConfigDict(extra="forbid")

    selection_id: str
    document_id: str
    section_ids: list[str]
    section_paths: list[list[str]]
    pdf_pages: list[int]
    block_count: int = Field(..., ge=1)
    character_count: int = Field(..., ge=0)
    rationale: str
    target_nodes: list[EvidenceTargetNode]


class EvidencePacketDocument(BaseModel):
    """Source identity and selected coverage for one packet document."""

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(..., pattern=r"^DOC-[A-F0-9]{12}$")
    source_file_name: str
    source_path: str
    source_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    parser_version: str
    selected_section_ids: list[str]
    selected_pdf_pages: list[int]
    selected_block_count: int = Field(..., ge=1)


class EvidencePacketStats(BaseModel):
    """Compact packet-size and quality counters."""

    model_config = ConfigDict(extra="forbid")

    document_count: int = Field(..., ge=1)
    section_count: int = Field(..., ge=1)
    page_count: int = Field(..., ge=1)
    block_count: int = Field(..., ge=1)
    character_count: int = Field(..., ge=0)
    table_count: int = Field(..., ge=0)
    review_block_count: int = Field(..., ge=0)


class EvidencePacket(BaseModel):
    """Materialized, source-bound evidence passed to later controlled runs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    packet_id: str
    packet_version: int
    project_id: str
    purpose: str
    manifest_path: str
    manifest_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    config_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    parser_name: str
    parser_version: str
    documents: list[EvidencePacketDocument] = Field(..., min_length=1)
    selection_summaries: list[EvidenceSelectionSummary] = Field(..., min_length=1)
    known_gaps: list[EvidencePacketGap]
    stats: EvidencePacketStats
    blocks: list[DocumentBlock] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_materialized_content(self) -> "EvidencePacket":
        """Reject internally inconsistent or detached packet content."""
        document_ids = [document.document_id for document in self.documents]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("documents must have unique document_id values")
        documents = {document.document_id: document for document in self.documents}
        block_ids = [block.block_id for block in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("blocks must have unique block_id values")
        for block in self.blocks:
            document = documents.get(block.document_id)
            if document is None:
                raise ValueError(f"Block references an unknown packet document: {block.block_id}")
            if block.source_sha256 != document.source_sha256:
                raise ValueError(f"Block source hash mismatch: {block.block_id}")
            if block.parser_version != document.parser_version or block.parser_version != self.parser_version:
                raise ValueError(f"Block parser version mismatch: {block.block_id}")

        for document in self.documents:
            selected = [block for block in self.blocks if block.document_id == document.document_id]
            if document.selected_block_count != len(selected):
                raise ValueError(f"Document block-count mismatch: {document.document_id}")
            if document.selected_section_ids != list(dict.fromkeys(block.section_id for block in selected)):
                raise ValueError(f"Document section coverage mismatch: {document.document_id}")
            if document.selected_pdf_pages != list(dict.fromkeys(block.pdf_page for block in selected)):
                raise ValueError(f"Document page coverage mismatch: {document.document_id}")

        expected_stats = {
            "document_count": len(self.documents),
            "section_count": len({(block.document_id, block.section_id) for block in self.blocks}),
            "page_count": len({(block.document_id, block.pdf_page) for block in self.blocks}),
            "block_count": len(self.blocks),
            "character_count": sum(len(block.text) for block in self.blocks),
            "table_count": sum(block.block_type.value == "table" for block in self.blocks),
            "review_block_count": sum(block.needs_review for block in self.blocks),
        }
        if self.stats.model_dump() != expected_stats:
            raise ValueError("Packet stats do not match materialized blocks")
        return self


__all__ = [
    "EvidencePacket",
    "EvidencePacketConfig",
    "EvidencePacketDocument",
    "EvidencePacketGap",
    "EvidencePacketSelection",
    "EvidencePacketStats",
    "EvidenceSelectionSummary",
    "EvidenceSelectorKind",
    "EvidenceTargetNode",
]
