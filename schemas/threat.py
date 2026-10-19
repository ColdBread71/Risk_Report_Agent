"""
Threat identification and DREAD scoring models.
"""

from enum import Enum
from typing import List, Literal, Optional, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import AssessmentVerdict, ConfidenceLevel
from .evidence import EvidenceRef
from .product import Asset, CybersecurityObjective


class StrideCategory(str, Enum):
    """Canonical STRIDE categories used by step [3]."""

    SPOOFING = "spoofing"
    TAMPERING = "tampering"
    REPUDIATION = "repudiation"
    INFORMATION_DISCLOSURE = "information_disclosure"
    DENIAL_OF_SERVICE = "denial_of_service"
    ELEVATION_OF_PRIVILEGE = "elevation_of_privilege"


class ThreatDetails(BaseModel):
    """Threat scenario per prEN 40000-1-2 section 6.4.3."""

    model_config = ConfigDict(extra="forbid")

    threat_id: str = Field(
        ...,
        pattern=r"^THREAT-[0-9]{3,}$",
        description="Stable unique threat identifier such as THREAT-001.",
    )
    stride_category: StrideCategory = Field(..., description="Canonical STRIDE category for the threat scenario.")
    title: str = Field(..., description="Short title for the threat.")
    description: str = Field(..., description="Threat scenario description.")
    cause_of_compromise: str = Field(..., description="Cause of compromise of the cybersecurity objective.")
    threat_actor: Optional[str] = Field(default=None, description="Threat actor or source of the threat.")
    attack_path: Optional[str] = Field(default=None, description="Attack path or preconditions.")
    known_vulnerabilities: List[str] = Field(default_factory=list, description="Relevant known exploitable vulnerabilities.")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.NONE, description="Confidence in the threat scenario.")
    analysis_basis: str = Field(..., min_length=1, description="Explain how supplied product facts and general attack mechanisms support this candidate; citations alone are not proof.")
    assumptions: list[str] = Field(default_factory=list, description="Unverified preconditions, explicitly conditional rather than asserted product facts.")
    confirmation_questions: list[str] = Field(default_factory=list, description="Product details an engineer should confirm before scoring.")


class ThreatScenario(ThreatDetails):
    """Canonical stored scenario, retaining full upstream objects for Node [4]."""

    targeted_assets: List[Asset] = Field(..., min_length=1)
    compromised_objectives: List[CybersecurityObjective] = Field(..., min_length=1)
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Original input citations supporting this candidate, not proof of exploitation.")


class ThreatCandidate(ThreatDetails):
    """Compact model output; code resolves references without regenerating assets."""

    targeted_asset_ids: list[str] = Field(..., min_length=1)
    compromised_objective_ids: list[str] = Field(..., min_length=1)
    evidence: List[EvidenceRef] = Field(default_factory=list)


class ThreatBatchCandidate(ThreatDetails):
    """Internal model format; public scenarios still contain complete EvidenceRef objects."""

    targeted_asset_ids: list[str] = Field(..., min_length=1)
    compromised_objective_ids: list[str] = Field(..., min_length=1)
    evidence_block_ids: list[str] = Field(default_factory=list, description="Reuse exact block_id values from evidence_catalog. Empty is allowed for an explicitly disclosed evidence gap.")


class DreadDimensionScore(BaseModel):
    """One DREAD dimension score."""

    name: str = Field(..., description="Dimension name, e.g., damage, reproducibility, exploitability, affected_users, discoverability.")
    score: float = Field(..., ge=0, description="Numeric score for the dimension.")
    rationale: str = Field(..., description="Explanation for the score.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting the score.")


class DreadScore(BaseModel):
    """DREAD scoring result mapped to likelihood and magnitude."""

    threat_id: str = Field(..., description="Threat identifier for this score.")
    damage: DreadDimensionScore = Field(..., description="Damage dimension.")
    reproducibility: DreadDimensionScore = Field(..., description="Reproducibility dimension.")
    exploitability: DreadDimensionScore = Field(..., description="Exploitability dimension.")
    affected_users: DreadDimensionScore = Field(..., description="Affected users dimension.")
    discoverability: DreadDimensionScore = Field(..., description="Discoverability dimension.")
    likelihood: float = Field(..., ge=0, description="Combined likelihood score.")
    magnitude: float = Field(..., ge=0, description="Combined magnitude score.")
    risk_value: float = Field(..., ge=0, description="Combined risk value.")
    formula: str = Field(..., description="Formula used to calculate the risk value.")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.NONE, description="Confidence in the scoring result.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting the scoring result.")


class ThreatAssessment(BaseModel):
    """Assessment result for the threat identification and scoring stage."""

    model_config = ConfigDict(extra="forbid")

    threats: List[ThreatScenario] = Field(default_factory=list, description="Threat scenarios identified for the product.")
    scores: List[DreadScore] = Field(default_factory=list, description="DREAD scores for the identified threats.")
    assessment: AssessmentVerdict = Field(default=AssessmentVerdict.FAIL, description="Assessment verdict for the stage.")
    notes: Optional[str] = Field(default=None, description="Notes on sufficiency or missing coverage.")
    review_status: Literal["unreviewed_draft"] = "unreviewed_draft"
    upstream_asset_review_approved: bool = False
    uncovered_asset_ids: list[str] = Field(default_factory=list)


class ThreatIdentificationResult(BaseModel):
    """Validated step [3] STRIDE output before DREAD scoring."""

    model_config = ConfigDict(extra="forbid")

    threats: List[ThreatScenario] = Field(
        ...,
        min_length=1,
        description="STRIDE threat scenarios linked to the supplied asset inventory.",
    )
    assessment: AssessmentVerdict = Field(
        default=AssessmentVerdict.FAIL,
        description="Candidate coverage assessment, not human approval. Use PARTIAL for gaps or unverified preconditions.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Explain threat-coverage gaps, unknown attack paths, or evidence limitations.",
    )

    @model_validator(mode="after")
    def validate_threat_identity(self) -> Self:
        """Reject blank or duplicate threat identifiers."""
        threat_ids = [threat.threat_id.strip() for threat in self.threats]
        if any(not threat_id for threat_id in threat_ids):
            raise ValueError("Every threat must have a non-empty threat_id.")
        if len(threat_ids) != len(set(threat_ids)):
            raise ValueError("threat_id values must be unique within the threat inventory.")
        return self


class ThreatCandidateResult(ThreatIdentificationResult):
    """LLM wire format; the saved contract remains ThreatIdentificationResult."""

    threats: list[ThreatCandidate] = Field(..., min_length=1)


class ThreatBatchResult(ThreatIdentificationResult):
    """One perspective may be empty without forcing an invented scenario."""

    threats: list[ThreatBatchCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def explain_empty_batch(self) -> Self:
        if not self.threats and not (self.notes or "").strip():
            raise ValueError("An empty perspective requires an applicability/coverage explanation in notes.")
        return self
