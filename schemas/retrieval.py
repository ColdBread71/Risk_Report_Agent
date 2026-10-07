"""Strict contracts for reusable node/field-level evidence retrieval."""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.document import DocumentBlockType
from schemas.evidence_packet import EvidenceTargetNode


class RetrievalField(StrEnum):
    """Supported retrieval slices before Node [0]-[2] structured extraction."""

    PRODUCT_IDENTITY = "product_identity"
    INTENDED_PURPOSE = "intended_purpose"
    SCOPE_BOUNDARY = "scope_boundary"
    REMOTE_SERVICES = "remote_services"
    CLASSIFICATION_INPUTS = "classification_inputs"

    IPRFU = "iprfu"
    USERS = "users"
    OPERATIONAL_ENVIRONMENT = "operational_environment"
    FUNCTIONS = "functions"
    COMPONENTS = "components"
    COMMUNICATIONS = "communications"
    SECURITY_FUNCTIONS = "security_functions"
    RDPS_DEPENDENCIES = "rdps_dependencies"

    DATA_ASSETS = "data_assets"
    CREDENTIALS_AND_KEYS = "credentials_and_keys"
    SOFTWARE_AND_CONFIGURATION = "software_and_configuration"
    HARDWARE_AND_NETWORK = "hardware_and_network"
    EXTERNAL_SERVICES = "external_services"
    FUNCTION_ASSETS = "function_assets"
    USER_PROPERTY_ENVIRONMENT = "user_property_environment"


_FIELDS_BY_NODE = {
    EvidenceTargetNode.SCOPE: {
        RetrievalField.PRODUCT_IDENTITY,
        RetrievalField.INTENDED_PURPOSE,
        RetrievalField.SCOPE_BOUNDARY,
        RetrievalField.REMOTE_SERVICES,
        RetrievalField.CLASSIFICATION_INPUTS,
    },
    EvidenceTargetNode.CONTEXT: {
        RetrievalField.IPRFU,
        RetrievalField.USERS,
        RetrievalField.OPERATIONAL_ENVIRONMENT,
        RetrievalField.FUNCTIONS,
        RetrievalField.COMPONENTS,
        RetrievalField.COMMUNICATIONS,
        RetrievalField.SECURITY_FUNCTIONS,
        RetrievalField.RDPS_DEPENDENCIES,
    },
    EvidenceTargetNode.ASSETS: {
        RetrievalField.DATA_ASSETS,
        RetrievalField.CREDENTIALS_AND_KEYS,
        RetrievalField.SOFTWARE_AND_CONFIGURATION,
        RetrievalField.HARDWARE_AND_NETWORK,
        RetrievalField.EXTERNAL_SERVICES,
        RetrievalField.FUNCTION_ASSETS,
        RetrievalField.USER_PROPERTY_ENVIRONMENT,
    },
}


class RetrievalProfile(BaseModel):
    """Versioned default query for one workflow field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: EvidenceTargetNode
    field_id: RetrievalField
    query: str = Field(..., min_length=1)
    token_budget: int = Field(default=12_000, ge=256, le=100_000)
    max_blocks: int = Field(default=24, ge=1, le=200)
    neighbor_window: int = Field(default=1, ge=0, le=4)
    max_facts: int = Field(default=12, ge=1, le=24)
    extraction_guidance: str = Field(
        default="逐条保留与本字段直接相关的原子事实；未知信息写入 unknowns。",
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_node_field_pair(self) -> Self:
        if self.field_id not in _FIELDS_BY_NODE.get(self.node_id, set()):
            raise ValueError(f"{self.field_id.value} is not valid for {self.node_id.value}")
        return self


class RetrievalFilters(BaseModel):
    """Optional metadata filters applied after semantic ranking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_ids: tuple[str, ...] = ()
    section_path_terms: tuple[str, ...] = ()
    block_types: tuple[DocumentBlockType, ...] = ()
    exclude_review_required: bool = False

    @model_validator(mode="after")
    def validate_unique_values(self) -> Self:
        for name in ("document_ids", "section_path_terms", "block_types"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique values")
        if any(not value.strip() for value in self.section_path_terms):
            raise ValueError("section_path_terms must be non-empty")
        return self


class RetrievalRequest(BaseModel):
    """One bounded retrieval request for a Node/field pair."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(..., min_length=1)
    node_id: EvidenceTargetNode
    field_id: RetrievalField
    query: str | None = None
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    token_budget: int = Field(default=12_000, ge=256, le=100_000)
    max_blocks: int = Field(default=24, ge=1, le=200)
    neighbor_window: int = Field(default=1, ge=0, le=4)

    @model_validator(mode="after")
    def validate_node_field_pair(self) -> Self:
        RetrievalProfile(node_id=self.node_id, field_id=self.field_id, query="validation")
        if self.query is not None and not self.query.strip():
            raise ValueError("query must be non-empty when provided")
        return self


class RetrievalHit(BaseModel):
    """Auditable ranking metadata for one selected source block."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: str = Field(..., pattern=r"^BLK-[A-F0-9]{16}$")
    document_id: str = Field(..., pattern=r"^DOC-[A-F0-9]{12}$")
    rank: int = Field(..., ge=1)
    score: float
    estimated_tokens: int = Field(..., ge=0)
    is_neighbor: bool = False
    seed_block_id: str | None = Field(default=None, pattern=r"^BLK-[A-F0-9]{16}$")


class RetrievedFact(BaseModel):
    """One atomic fact extracted from a field-specific evidence packet."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(..., pattern=r"^FACT-[0-9]{3,}$")
    statement: str = Field(..., min_length=1, max_length=1_000)
    block_ids: list[str] = Field(..., min_length=1, max_length=4)
    is_uncertain: bool = False
    attributes: dict[str, str | list[str] | None] = Field(
        default_factory=dict,
        max_length=14,
        description=(
            "Optional field-specific values copied from the same evidence. Only communications "
            "and components use the reviewed keys validated by FieldExtractionResult."
        ),
    )

    @model_validator(mode="after")
    def validate_unique_blocks(self) -> Self:
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("block_ids must be unique within a fact")
        invalid = [
            block_id
            for block_id in self.block_ids
            if re.fullmatch(r"BLK-[A-F0-9]{16}", block_id) is None
        ]
        if invalid:
            raise ValueError(f"Invalid block_id values: {invalid}")
        return self


class FieldExtractionResult(BaseModel):
    """Compact persisted candidate facts for one Node/field slice."""

    model_config = ConfigDict(extra="forbid")

    node_id: EvidenceTargetNode
    field_id: RetrievalField
    facts: list[RetrievedFact] = Field(default_factory=list, max_length=24)
    unknowns: list[str] = Field(default_factory=list, max_length=10)
    contradictions: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        RetrievalProfile(node_id=self.node_id, field_id=self.field_id, query="validation")
        fact_ids = [fact.fact_id for fact in self.facts]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("fact_id values must be unique within a field batch")
        if not self.facts and not self.unknowns:
            raise ValueError("A field batch requires facts or explicit unknowns")
        allowed_keys = {
            RetrievalField.COMMUNICATIONS: {
                "source",
                "destination",
                "protocol",
                "port",
                "interface",
                "direction_basis",
                "business_data_direction",
                "activation_status",
                "authentication",
                "encryption",
                "data_exchanged",
                "conditions",
            },
            RetrievalField.COMPONENTS: {
                "component_name",
                "component_type",
                "scope_status",
                "conditions",
            },
        }.get(self.field_id, set())
        enum_values = {
            "direction_basis": {
                "documented_endpoints",
                "connection_initiation",
                "listener_exposure",
                "business_data_flow",
                "unknown",
            },
            "business_data_direction": {
                "to_product",
                "from_product",
                "bidirectional",
                "unknown",
            },
            "activation_status": {
                "enabled",
                "disabled_by_default",
                "conditional",
                "unknown",
            },
            "scope_status": {"confirmed", "conditional", "external", "unknown"},
        }
        list_keys = {"data_exchanged", "conditions"}
        for fact in self.facts:
            unexpected = set(fact.attributes) - allowed_keys
            if unexpected:
                raise ValueError(
                    f"attributes are not allowed for {self.field_id.value}: {sorted(unexpected)}"
                )
            normalized_attributes = {}
            for key, value in fact.attributes.items():
                # Optional structured values may be emitted as null or an empty
                # list. Both mean "not supplied" and must not force an LLM retry.
                if value is None or (key in list_keys and value == []):
                    continue
                if key in list_keys:
                    if not isinstance(value, list) or len(value) > 10:
                        raise ValueError(f"{key} must be a non-empty list with at most 10 items")
                    if any(not item.strip() for item in value):
                        raise ValueError(f"{key} items must be non-empty strings")
                elif isinstance(value, list):
                    raise ValueError(f"{key} must be a string or null")
                elif isinstance(value, str) and not value.strip():
                    raise ValueError(f"{key} must be non-empty when provided")
                if key in enum_values and value not in enum_values[key]:
                    raise ValueError(f"Unsupported {key}: {value}")
                normalized_attributes[key] = value
            fact.attributes = normalized_attributes
        return self


class VectorIndexMetadata(BaseModel):
    """Integrity metadata for one persisted local FAISS index."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    index_id: str = Field(..., pattern=r"^IDX-[A-F0-9]{16}$")
    project_id: str = Field(..., min_length=1)
    manifest_path: str = Field(..., min_length=1)
    manifest_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    parser_name: str = Field(..., min_length=1)
    parser_version: str = Field(..., min_length=1)
    scope_packet_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    scope_block_count: int = Field(..., ge=1)
    embedding_model: str = Field(..., min_length=1)
    embedding_dimensions: int = Field(..., ge=1)
    embedding_text_version: str = Field(..., min_length=1)
    built_at: datetime
    block_ids: list[str] = Field(..., min_length=1)
    faiss_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_unique_blocks(self) -> Self:
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("block_ids must be unique")
        return self


class RetrievalTrace(BaseModel):
    """Machine-readable trace for one materialized retrieval packet."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    request: RetrievalRequest
    effective_query: str
    index_id: str = Field(..., pattern=r"^IDX-[A-F0-9]{16}$")
    scope_packet_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    packet_id: str = Field(..., min_length=1)
    packet_sha256: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    candidate_count: int = Field(..., ge=0)
    selected_count: int = Field(..., ge=1)
    selected_token_count: int = Field(..., ge=0)
    truncated_by_budget: bool
    truncated_by_max_blocks: bool
    hits: list[RetrievalHit] = Field(..., min_length=1)


__all__ = [
    "FieldExtractionResult",
    "RetrievalField",
    "RetrievalFilters",
    "RetrievalHit",
    "RetrievalProfile",
    "RetrievalRequest",
    "RetrievalTrace",
    "RetrievedFact",
    "VectorIndexMetadata",
]
