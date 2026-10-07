"""
Risk treatment and residual risk models.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from .common import AssessmentVerdict, TreatmentOption
from .evidence import EvidenceRef
from .risk import EvaluatedRisk


class SecureDesignMapping(BaseModel):
    """Mapping from risk to secure design controls."""

    risk_id: str = Field(..., description="Risk identifier.")
    threat_reference: str = Field(..., description="Threat reference or category.")
    security_objective_reference: Optional[str] = Field(default=None, description="Related security objective reference.")
    recommended_controls: List[str] = Field(default_factory=list, description="Recommended control identifiers.")
    existing_customer_features: List[str] = Field(default_factory=list, description="Existing customer functions that already address the risk.")
    coverage_status: str = Field(..., description="Coverage status: Covered, Partial, Missing.")
    gap_description: Optional[str] = Field(default=None, description="Description of the remaining gap.")
    lifecycle_stage: List[str] = Field(default_factory=list, description="Lifecycle stages where the control applies.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting the mapping.")


class RiskTreatmentDecision(BaseModel):
    """Risk treatment decision for one risk."""

    risk_id: str = Field(..., description="Risk identifier.")
    treatment_option: TreatmentOption = Field(..., description="Selected treatment option.")
    justification: str = Field(..., description="Justification for the selected treatment.")
    actions: List[str] = Field(default_factory=list, description="Concrete actions to implement.")
    re_evaluation_required: bool = Field(default=True, description="Whether the risk must be reevaluated after treatment.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting the treatment decision.")


class ResidualRisk(BaseModel):
    """Residual risk after treatment."""

    risk_id: str = Field(..., description="Risk identifier.")
    treated_risk: EvaluatedRisk = Field(..., description="Original evaluated risk.")
    remaining_risk_value: float = Field(..., ge=0, description="Residual risk value.")
    residual_acceptance_reason: Optional[str] = Field(default=None, description="Reason why the residual risk is acceptable.")
    user_communication: List[str] = Field(default_factory=list, description="Messages to communicate to users or stakeholders.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting the residual risk.")


class TreatmentRegister(BaseModel):
    """Collection of treatment decisions and residual risks."""

    decisions: List[RiskTreatmentDecision] = Field(default_factory=list, description="Risk treatment decisions.")
    residual_risks: List[ResidualRisk] = Field(default_factory=list, description="Residual risks after treatment.")
    assessment: AssessmentVerdict = Field(default=AssessmentVerdict.FAIL, description="Assessment verdict for the treatment stage.")
    notes: Optional[str] = Field(default=None, description="Notes on treatment sufficiency.")
