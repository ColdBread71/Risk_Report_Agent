"""
Reporting and audit trace models.
"""

from typing import List, Optional

from pydantic import BaseModel, Field

from .common import AssessmentVerdict
from .evidence import EvidenceRef
from .legal import ScopeStatement
from .product import ProductContext
from .risk import RiskRegister
from .treatment import TreatmentRegister
from .threat import ThreatAssessment


class AuditTraceItem(BaseModel):
    """Single trace item linking a conclusion to evidence and legal basis."""

    item_id: str = Field(..., description="Unique trace item identifier.")
    step_id: str = Field(..., description="Workflow step that produced the item.")
    conclusion: str = Field(..., description="Conclusion or statement being traced.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Supporting evidence.")
    notes: Optional[str] = Field(default=None, description="Additional audit notes.")


class AuditTrace(BaseModel):
    """Audit trace for the overall workflow."""

    scope: Optional[ScopeStatement] = Field(default=None, description="Scope statement trace.")
    product_context: Optional[ProductContext] = Field(default=None, description="Product context trace.")
    threat_assessment: Optional[ThreatAssessment] = Field(default=None, description="Threat assessment trace.")
    risk_register: Optional[RiskRegister] = Field(default=None, description="Risk register trace.")
    treatment_register: Optional[TreatmentRegister] = Field(default=None, description="Treatment register trace.")
    items: List[AuditTraceItem] = Field(default_factory=list, description="Detailed trace items.")


class ReportSummary(BaseModel):
    """Top-level summary for a TARA report."""

    product_name: str = Field(..., description="Name of the product.")
    status: AssessmentVerdict = Field(..., description="Overall assessment verdict.")
    summary: str = Field(..., description="Short summary of the report.")
    unresolved_questions: List[str] = Field(default_factory=list, description="Unresolved questions from the workflow.")
    evidence: List[EvidenceRef] = Field(default_factory=list, description="Evidence supporting the summary.")
