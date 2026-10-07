"""
Evidence reference and source metadata for traceability.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .common import ConfidenceLevel, EvidenceLevel


class SourceRef(BaseModel):
    """Reference to a source document or file."""

    file_name: str = Field(..., description="Original file name.")
    file_path: Path | str = Field(..., description="Absolute or relative path to the source file.")
    file_type: str = Field(..., description="Type of the source file, e.g., pdf, docx, md.")
    document_id: Optional[str] = Field(
        default=None,
        pattern=r"^DOC-[A-F0-9]{12}$",
        description="Stable parsed-document identifier when the source belongs to a project corpus.",
    )
    block_id: Optional[str] = Field(
        default=None,
        pattern=r"^BLK-[A-F0-9]{16}$",
        description="Stable parsed content-block identifier when available.",
    )
    parser_version: Optional[str] = Field(
        default=None,
        description="Parser version that produced the referenced content block.",
    )
    page_number: Optional[int] = Field(
        default=None,
        ge=1,
        description="One-based physical page number in the source file.",
    )
    printed_page_label: Optional[str] = Field(
        default=None,
        description="Page label printed in the source document, which may differ from the physical PDF page.",
    )
    section_path: list[str] = Field(
        default_factory=list,
        description="Ordered chapter or section hierarchy associated with the cited block.",
    )
    clause_number: Optional[str] = Field(default=None, description="Clause or section number in the source.")
    annex: Optional[str] = Field(default=None, description="Annex identifier, if applicable.")
    hash_sha256: Optional[str] = Field(default=None, description="SHA256 hash of the source file content.")


class EvidenceRef(BaseModel):
    """Evidence reference linking a conclusion to its source."""

    evidence_id: str = Field(..., description="Unique identifier for this evidence reference.")
    source: SourceRef = Field(..., description="Source document reference.")
    quote: Optional[str] = Field(default=None, description="Exact quoted text from the source.")
    evidence_level: EvidenceLevel = Field(..., description="Strength level of the evidence.")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.NONE, description="Confidence level in the evidence.")
    retrieved_by: Optional[str] = Field(default=None, description="Tool or method used to retrieve this evidence.")
    is_human_confirmed: bool = Field(default=False, description="Whether this evidence has been confirmed by a human reviewer.")
    notes: Optional[str] = Field(default=None, description="Additional notes or context about the evidence.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When this evidence reference was created.")


class LegalBasis(BaseModel):
    """Reference to a legal or standard clause."""

    regulation: str = Field(..., description="Name of the regulation or standard, e.g., CRA, prEN 40000-1-2.")
    article: Optional[str] = Field(default=None, description="Article number, if applicable.")
    clause: Optional[str] = Field(default=None, description="Clause or section number.")
    annex: Optional[str] = Field(default=None, description="Annex identifier.")
    sub_clause: Optional[str] = Field(default=None, description="Sub-clause or paragraph identifier.")
    normative: bool = Field(default=True, description="Whether this clause is normative or informative.")
    description: Optional[str] = Field(default=None, description="Brief description of the clause content.")
