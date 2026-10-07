"""Node [0] scope models for CRA legal and product boundary definition."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .evidence import EvidenceRef, LegalBasis


class ProductClassification(BaseModel):
    """CRA classification facts extracted for the product scope."""

    model_config = ConfigDict(extra="forbid")

    is_pde: Optional[bool] = Field(
        default=None,
        description=(
            "Set true or false only when CRA applicability has been assessed from an approved "
            "legal basis and supported product facts; use null when the customer product material "
            "alone does not establish the legal conclusion."
        ),
    )
    classification: Optional[str] = Field(
        default=None,
        description="Enter exactly one supported CRA classification, such as Default, Important, or Critical, only when justified by evidence; otherwise leave null.",
    )
    has_rdps: Optional[bool] = Field(
        default=None,
        description=(
            "Set true only when evidence shows that a remote data processing solution is "
            "required for a product function, false only when evidence rules this out, and "
            "null when remote capability is evidenced but the CRA RDPS dependency test or "
            "delivered configuration remains unresolved."
        ),
    )
    rdps_description: Optional[str] = Field(
        default=None,
        description=(
            "Describe the confirmed RDPS, or when has_rdps is null summarize the evidenced remote "
            "capability and the missing necessity, operator/responsibility, exchanged-data, trust, "
            "or degraded-mode facts. Leave null only when no remote solution is evidenced."
        ),
    )
    applicable_annex: Optional[str] = Field(
        default=None,
        description="State the applicable CRA annex or annexes, for example Annex III, Annex IV, or both; leave null when applicability cannot yet be determined.",
    )
    overlapping_regulations: Optional[list[str]] = Field(
        default=None,
        description=(
            "List other assessed EU legal instruments, one concise instrument name per item; use "
            "an empty list only when the legal assessment has confirmed none, and null when the "
            "overlap assessment has not been completed."
        ),
    )


class ScopeStatement(BaseModel):
    """Node [0] legal/product scope statement."""

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(
        ...,
        description="Extract the official product name exactly as stated in the input material; do not normalize or invent a name.",
    )
    product_version: Optional[str] = Field(
        default=None,
        description="Extract the product, hardware, or software version exactly as stated; use null when no version is provided.",
    )
    classification: ProductClassification = Field(
        ...,
        description="Provide the evidence-based CRA product classification and scope indicators; unresolved indicators must remain null or explicitly false according to their field rules.",
    )
    scope_description: str = Field(
        ...,
        description=(
            "Write a concise scope statement covering the assessed product, components, interfaces, "
            "external dependencies, and assessment boundary. When has_rdps is null, describe only "
            "evidenced remote capabilities or candidate dependencies, never a confirmed RDPS."
        ),
    )
    in_scope_components: list[str] = Field(
        default_factory=list,
        description=(
            "List each confirmed product component, interface, service, and dependency included "
            "in the assessment as a separate item. Do not place optional, ordered, disabled, or "
            "configuration-dependent items here."
        ),
    )
    conditional_scope_components: list[str] = Field(
        default_factory=list,
        description=(
            "List product capabilities or boundary items that are relevant only for an option, "
            "order, contract, BOM, deployment, or enabled configuration. State the condition and "
            "the customer confirmation needed for each item."
        ),
    )
    out_of_scope_components: list[str] = Field(
        default_factory=list,
        description="List each excluded component or boundary as a separate item and include the reason for exclusion when known; do not silently omit exclusions.",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Despite the legacy field name, list only unanswered customer or legal confirmation "
            "questions. Each item must contain an interrogative, end with a question mark, and must "
            "not assert a provisional answer. Use at most five consolidated questions."
        ),
    )
    review_notes: list[str] = Field(
        default_factory=list,
        description=(
            "Record non-blocking review notes added when uncertain or misplaced generated content "
            "is conservatively downgraded. These notes do not prevent Node 1/2 draft extraction."
        ),
    )
    legal_basis: list[LegalBasis] = Field(
        default_factory=list,
        description="Record each applicable CRA article, annex, or relevant standard clause as a separate structured legal basis; include only sources supported by the input or approved knowledge base.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach source evidence for the scope facts, including file identity and page/clause location whenever available; leave empty only when no evidence was supplied.",
    )
