"""
Threat identification and DREAD scoring models.
"""

from enum import Enum
from typing import List, Optional, Self

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


class ThreatScenario(BaseModel):
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
    targeted_assets: List[Asset] = Field(..., description="Assets targeted by this threat.")
    compromised_objectives: List[CybersecurityObjective] = Field(..., description="Cybersecurity objectives compromised by this threat.")
    cause_of_compromise: str = Field(..., description="Cause of compromise of the cybersecurity objective.")
    threat_actor: Optional[str] = Field(default=None, description="Threat actor or source of the threat.")
    attack_path: Optional[str] = Field(default=None, description="Attack path or preconditions.")
    known_vulnerabilities: List[str] = Field(default_factory=list, description="Relevant known exploitable vulnerabilities.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting this threat scenario.")
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.NONE, description="Confidence in the threat scenario.")


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


class ThreatIdentificationResult(BaseModel):
    """Validated step [3] STRIDE output before DREAD scoring."""

    model_config = ConfigDict(extra="forbid")

    threats: List[ThreatScenario] = Field(
        ...,
        min_length=1,
        description="STRIDE threat scenarios linked to the approved asset inventory.",
    )
    assessment: AssessmentVerdict = Field(
        default=AssessmentVerdict.FAIL,
        description="Set PASS only when every approved asset has sufficient threat coverage.",
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
