"""
Risk evaluation models.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .common import AssessmentVerdict, RiskStatus, SeverityLevel
from .evidence import EvidenceRef
from .threat import DreadScore, ThreatScenario


class RiskAcceptanceCriteria(BaseModel):
    """Risk acceptance criteria established in step [1]."""

    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(..., description="Policy version used for the criteria.")
    regulatory_factors: List[str] = Field(default_factory=list, description="Relevant regulatory factors.")
    contractual_factors: List[str] = Field(default_factory=list, description="Relevant contractual or stakeholder factors.")
    risk_nature_factors: List[str] = Field(default_factory=list, description="Nature of known risks.")
    user_factors: List[str] = Field(default_factory=list, description="Nature of the users.")
    product_factors: List[str] = Field(default_factory=list, description="Nature of the product.")
    state_of_art_factors: List[str] = Field(default_factory=list, description="State of the art and current societal values.")
    aggregate_risk_considered: bool = Field(default=True, description="Whether aggregate risks are covered.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting the acceptance criteria.")


class EvaluatedRisk(BaseModel):
    """Risk item after evaluation against acceptance criteria."""

    model_config = ConfigDict(extra="forbid")

    risk_id: str = Field(..., description="Unique risk identifier.")
    threat: ThreatScenario = Field(..., description="Threat scenario linked to this risk.")
    score: DreadScore = Field(..., description="DREAD scoring result.")
    status: RiskStatus = Field(default=RiskStatus.IDENTIFIED, description="Current risk status.")
    severity: SeverityLevel = Field(..., description="Risk severity classification.")
    is_acceptable: bool = Field(..., description="Whether the risk is acceptable under the current criteria.")
    acceptance_reason: Optional[str] = Field(default=None, description="Reason for accepting or rejecting the risk.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting the evaluation.")


class RiskRegister(BaseModel):
    """Collection of evaluated risks."""

    model_config = ConfigDict(extra="forbid")

    acceptance_criteria: RiskAcceptanceCriteria = Field(..., description="Risk acceptance criteria used for the register.")
    evaluated_risks: List[EvaluatedRisk] = Field(default_factory=list, description="All evaluated risks.")
    assessment: AssessmentVerdict = Field(default=AssessmentVerdict.FAIL, description="Assessment verdict for the risk register.")
    notes: Optional[str] = Field(default=None, description="Notes on completeness and sufficiency.")
