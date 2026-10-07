"""Frozen risk-method snapshot established during workflow step [1]."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskMethodology(BaseModel):
    """Auditable view of the static method selected before threat/risk analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_version: str = Field(..., min_length=1)
    threat_modelling_method: Literal["STRIDE"]
    risk_estimation_method: Literal["DREAD"]
    statutory_risk_factors: tuple[Literal["likelihood", "magnitude"], ...]
    risk_combination_rule: Literal["likelihood × magnitude"]
    likelihood_dimensions: tuple[str, ...] = Field(..., min_length=1)
    magnitude_dimensions: tuple[str, ...] = Field(..., min_length=1)
    damage_required_coverage: tuple[str, ...] = Field(..., min_length=1)
    risk_acceptance_rule: str = Field(..., min_length=1)
    treatment_priority: tuple[str, ...] = Field(..., min_length=4, max_length=4)
    node_4_scale_status: Literal["pending_approval", "frozen"]
    source_references: tuple[str, ...] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_frozen_order_and_factors(self) -> Self:
        """Reject a policy snapshot that changes the approved method ordering."""
        if self.statutory_risk_factors != ("likelihood", "magnitude"):
            raise ValueError("statutory_risk_factors must be likelihood then magnitude")
        if self.treatment_priority != ("Avoid", "Mitigate", "Accept", "Transfer"):
            raise ValueError("treatment_priority must be Avoid, Mitigate, Accept, Transfer")
        return self


__all__ = ["RiskMethodology"]
