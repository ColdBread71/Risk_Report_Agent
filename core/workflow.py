"""Executable LangGraph for the Node [0]-[3] MVP slice."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from core.state import TaraState
from nodes.asset_threat_modeler import (
    identify_assets,
    model_threats,
    review_assets,
    route_after_asset_review,
    route_after_assets,
)
from nodes.context_builder import (
    build_product_context,
    define_scope,
    route_after_context,
    route_after_scope,
)
from schemas.common import AssessmentVerdict, ConfidenceLevel, EvidenceLevel
from schemas.evidence import EvidenceRef, LegalBasis, SourceRef
from schemas.legal import ProductClassification, ScopeStatement
from schemas.methodology import RiskMethodology
from schemas.product import (
    Asset,
    CommunicationMatrix,
    CommunicationMatrixEntry,
    ComponentInventory,
    ComponentInventoryEntry,
    CybersecurityObjective,
    IPRFU,
    OperationalEnvironment,
    ProductContext,
    ProductFunction,
    UserDescription,
)
from schemas.run_input import EvidencePacketRef
from schemas.risk import RiskAcceptanceCriteria
from schemas.threat import StrideCategory, ThreatAssessment, ThreatScenario


workflow = StateGraph(TaraState)
workflow.add_node("define_scope", define_scope)
workflow.add_node("build_product_context", build_product_context)
workflow.add_node("identify_assets", identify_assets)
workflow.add_node("review_assets", review_assets)
workflow.add_node("model_threats", model_threats)
workflow.add_edge(START, "define_scope")
workflow.add_conditional_edges(
    "define_scope",
    route_after_scope,
    {"build_product_context": "build_product_context", "end": END},
)
workflow.add_conditional_edges(
    "build_product_context",
    route_after_context,
    {"identify_assets": "identify_assets", "end": END},
)
workflow.add_conditional_edges(
    "identify_assets",
    route_after_assets,
    {"review_assets": "review_assets", "end": END},
)
workflow.add_conditional_edges(
    "review_assets",
    route_after_asset_review,
    {"model_threats": "model_threats", "end": END},
)
workflow.add_edge("model_threats", END)

checkpoint_serializer = JsonPlusSerializer(
    allowed_msgpack_modules=[
        AssessmentVerdict,
        ConfidenceLevel,
        EvidenceLevel,
        SourceRef,
        EvidenceRef,
        LegalBasis,
        ProductClassification,
        ScopeStatement,
        IPRFU,
        UserDescription,
        OperationalEnvironment,
        ProductFunction,
        CommunicationMatrixEntry,
        CommunicationMatrix,
        ComponentInventoryEntry,
        ComponentInventory,
        CybersecurityObjective,
        ProductContext,
        RiskMethodology,
        RiskAcceptanceCriteria,
        EvidencePacketRef,
        Asset,
        StrideCategory,
        ThreatScenario,
        ThreatAssessment,
    ]
)
checkpointer = MemorySaver(serde=checkpoint_serializer)
tara_graph = workflow.compile(checkpointer=checkpointer)

node0_workflow = StateGraph(TaraState)
node0_workflow.add_node("define_scope", define_scope)
node0_workflow.add_edge(START, "define_scope")
node0_workflow.add_edge("define_scope", END)
node0_graph = node0_workflow.compile(checkpointer=checkpointer)

node1_workflow = StateGraph(TaraState)
node1_workflow.add_node("build_product_context", build_product_context)
node1_workflow.add_edge(START, "build_product_context")
node1_workflow.add_edge("build_product_context", END)
node1_graph = node1_workflow.compile(checkpointer=checkpointer)

node2_workflow = StateGraph(TaraState)
node2_workflow.add_node("identify_assets", identify_assets)
node2_workflow.add_node("review_assets", review_assets)
node2_workflow.add_edge(START, "identify_assets")
node2_workflow.add_conditional_edges(
    "identify_assets",
    route_after_assets,
    {"review_assets": "review_assets", "end": END},
)
node2_workflow.add_edge("review_assets", END)
node2_graph = node2_workflow.compile(checkpointer=checkpointer)

app = tara_graph

__all__ = [
    "app",
    "checkpointer",
    "checkpoint_serializer",
    "node0_graph",
    "node1_graph",
    "node2_graph",
    "tara_graph",
]
