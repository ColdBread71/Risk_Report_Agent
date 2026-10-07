"""LangGraph state contract for the Node [0]-[3] MVP slice."""

from typing import Optional, TypedDict

from schemas.common import AssessmentVerdict
from schemas.legal import ScopeStatement
from schemas.methodology import RiskMethodology
from schemas.product import Asset, ProductContext
from schemas.risk import RiskAcceptanceCriteria
from schemas.run_input import EvidencePacketRef
from schemas.threat import ThreatAssessment


class TaraState(TypedDict, total=False):
    """State containing validated domain objects and workflow control data only."""

    evidence_packet_ref: Optional[EvidencePacketRef]
    scope: Optional[ScopeStatement]
    product_context: Optional[ProductContext]
    risk_methodology: Optional[RiskMethodology]
    risk_acceptance_criteria: Optional[RiskAcceptanceCriteria]
    assets: list[Asset]
    asset_assessment: Optional[AssessmentVerdict]
    asset_notes: Optional[str]
    asset_review_approved: bool
    asset_review_notes: Optional[str]
    threat_assessment: Optional[ThreatAssessment]
    errors: list[str]
    current_step: str
    status: str
