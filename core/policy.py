"""Static policy constants for the CRA/prEN 40000 TARA workflow."""

from enum import StrEnum
from typing import Final

from schemas.methodology import RiskMethodology
from schemas.legal import ScopeStatement
from schemas.product import ProductContext
from schemas.risk import RiskAcceptanceCriteria


class RiskTreatmentPriority(StrEnum):
    """Treatment order required by prEN 40000-1-2, 6.5.1.6."""

    AVOID = "Avoid"
    MITIGATE = "Mitigate"
    ACCEPT = "Accept"
    TRANSFER = "Transfer"


class ThreatModellingMethod(StrEnum):
    """Default threat modelling method for the workflow."""

    STRIDE = "STRIDE"


class RiskEstimationMethod(StrEnum):
    """Default quantitative risk estimation method for the workflow."""

    DREAD = "DREAD"


class RiskAcceptancePolicy:
    """Static risk acceptance rules for prEN 40000-1-2, 6.4.5."""

    RISK_EXISTS_DEFAULT_ACCEPTED: Final[bool] = False
    RISK_EXISTS_RULE: Final[str] = "If a risk exists, it is not accepted by default."
    REQUIRES_WRITTEN_JUSTIFICATION: Final[bool] = True


class DreadPolicy:
    """Static DREAD-to-standard mapping requirements."""

    METHOD: Final[RiskEstimationMethod] = RiskEstimationMethod.DREAD
    DAMAGE_REQUIRED_COVERAGE: Final[tuple[str, ...]] = (
        "health and safety",
        "adjacent devices/networks",
        "attack scalability",
    )
    LIKELIHOOD_DIMENSIONS: Final[tuple[str, ...]] = (
        "reproducibility",
        "exploitability",
        "discoverability",
    )
    MAGNITUDE_DIMENSIONS: Final[tuple[str, ...]] = (
        "damage",
        "affected users",
    )


class WorkflowPolicy:
    """Authoritative static methodology and treatment policy for the workflow."""

    VERSION: Final[str] = "policy-v1.0"
    THREAT_MODELLING_METHOD: Final[ThreatModellingMethod] = ThreatModellingMethod.STRIDE
    RISK_ESTIMATION_METHOD: Final[RiskEstimationMethod] = RiskEstimationMethod.DREAD
    RISK_ACCEPTANCE_RULE: Final[str] = RiskAcceptancePolicy.RISK_EXISTS_RULE
    RISK_EXISTS_DEFAULT_ACCEPTED: Final[bool] = RiskAcceptancePolicy.RISK_EXISTS_DEFAULT_ACCEPTED
    RISK_COMBINATION_RULE: Final[str] = "likelihood × magnitude"
    RISK_TREATMENT_PRIORITY: Final[tuple[RiskTreatmentPriority, ...]] = (
        RiskTreatmentPriority.AVOID,
        RiskTreatmentPriority.MITIGATE,
        RiskTreatmentPriority.ACCEPT,
        RiskTreatmentPriority.TRANSFER,
    )
    DREAD_DAMAGE_REQUIRED_COVERAGE: Final[tuple[str, ...]] = DreadPolicy.DAMAGE_REQUIRED_COVERAGE
    DREAD_LIKELIHOOD_DIMENSIONS: Final[tuple[str, ...]] = DreadPolicy.LIKELIHOOD_DIMENSIONS
    DREAD_MAGNITUDE_DIMENSIONS: Final[tuple[str, ...]] = DreadPolicy.MAGNITUDE_DIMENSIONS
    SOURCE_REFERENCES: Final[tuple[str, ...]] = (
        "prEN 40000-1-2 Section 6.4.4",
        "prEN 40000-1-2 Section 6.4.5",
        "prEN 40000-1-2 Section 6.5.1.6",
        "CRA Annex I Part I (2)(i)",
    )


def build_risk_methodology() -> RiskMethodology:
    """Create the immutable Node [1] snapshot of the currently approved method."""
    return RiskMethodology(
        policy_version=WorkflowPolicy.VERSION,
        threat_modelling_method=WorkflowPolicy.THREAT_MODELLING_METHOD.value,
        risk_estimation_method=WorkflowPolicy.RISK_ESTIMATION_METHOD.value,
        statutory_risk_factors=("likelihood", "magnitude"),
        risk_combination_rule=WorkflowPolicy.RISK_COMBINATION_RULE,
        likelihood_dimensions=WorkflowPolicy.DREAD_LIKELIHOOD_DIMENSIONS,
        magnitude_dimensions=WorkflowPolicy.DREAD_MAGNITUDE_DIMENSIONS,
        damage_required_coverage=WorkflowPolicy.DREAD_DAMAGE_REQUIRED_COVERAGE,
        risk_acceptance_rule=WorkflowPolicy.RISK_ACCEPTANCE_RULE,
        treatment_priority=tuple(item.value for item in WorkflowPolicy.RISK_TREATMENT_PRIORITY),
        node_4_scale_status="pending_approval",
        source_references=WorkflowPolicy.SOURCE_REFERENCES,
    )


def build_risk_acceptance_criteria(
    scope: ScopeStatement,
    context: ProductContext,
) -> RiskAcceptanceCriteria:
    """Build a conservative Node [1] draft without asking the model to judge risk."""
    user_types = "、".join(context.user_description.user_types) or "用户类型待确认"
    product_factors = [
        f"围绕 {context.product_name} 的预期用途（{context.iprfu.intended_purpose}）、运行环境、接口、组件和现有功能评估风险。",
    ]
    if scope.product_version is None or scope.conditional_scope_components:
        product_factors.append(
            "产品版本、实际交付 BOM、选配件或启用状态未冻结的部分保持条件适用并由工程师确认。"
        )
    if scope.classification.has_rdps is None:
        product_factors.append(
            "远程服务是否构成必要 RDPS 及其责任边界尚未冻结，相关场景暂按候选依赖保留。"
        )
    return RiskAcceptanceCriteria(
        policy_version=WorkflowPolicy.VERSION,
        regulatory_factors=[
            "风险存在时默认不接受；任何接受决定均需书面理由和人工批准。",
            "风险评估应覆盖发生可能性、损害规模以及多个风险的聚合影响。",
        ],
        contractual_factors=[],
        risk_nature_factors=[
            "后续逐项识别威胁场景，并按 likelihood × magnitude 评估；当前节点不预判具体风险。",
            "损害分析覆盖健康与安全、相邻设备或网络以及攻击可扩展性。",
        ],
        user_factors=[
            f"考虑已识别用户类型及其能力、权限和责任：{user_types}；缺失信息由工程师确认。"
        ],
        product_factors=product_factors,
        state_of_art_factors=[],
        aggregate_risk_considered=True,
        evidence=[],
    )


__all__ = [
    "DreadPolicy",
    "RiskAcceptancePolicy",
    "RiskEstimationMethod",
    "RiskTreatmentPriority",
    "ThreatModellingMethod",
    "WorkflowPolicy",
    "build_risk_acceptance_criteria",
    "build_risk_methodology",
]
