"""Node [1] TOE Context models for product definition."""

from typing import Literal, Optional, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .common import AssessmentVerdict
from .evidence import EvidenceRef, LegalBasis


class UserDescription(BaseModel):
    """Target user description required by prEN 40000-1-2 6.2.1.6."""

    model_config = ConfigDict(extra="forbid")

    user_types: list[str] = Field(
        ...,
        description="List each intended user type separately, including end users, administrators, maintainers, installers, and downstream integrators when applicable; use an empty list only when no user information is available.",
    )
    experience_level: Optional[str] = Field(
        default=None,
        description="Describe evidenced cybersecurity knowledge, training, or operational ability; use null when the material only lists roles or permissions.",
    )
    vulnerable_groups: list[str] = Field(
        default_factory=list,
        description="List vulnerable or accessibility-relevant user groups, such as children or users with impairments, only when stated or reasonably supported by the input; otherwise use an empty list.",
    )
    is_component: Optional[bool] = Field(
        default=None,
        description="Set true when the product is intended to be integrated as a component, false when explicitly excluded, and null when the evidence does not establish this.",
    )
    rdps_dependence: Optional[str] = Field(
        default=None,
        description="Describe how users or integrators depend on an RDPS for onboarding, operation, maintenance, or decommissioning; use null when no RDPS dependence is evidenced.",
    )
    responsibilities: list[str] = Field(
        default_factory=list,
        description="List cybersecurity responsibilities explicitly expected from users, operators, or integrators, one responsibility per item; do not invent responsibilities.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach evidence supporting user types, abilities, vulnerable groups, component use, and responsibilities, with source location whenever available.",
    )


class IPRFU(BaseModel):
    """Intended purpose and reasonably foreseeable use."""

    model_config = ConfigDict(extra="forbid")

    intended_purpose: str = Field(
        ...,
        description="Extract the manufacturer's intended purpose in a concise factual statement, including the product role and primary use; do not expand beyond the supplied evidence.",
    )
    reasonably_foreseeable_use: list[str] = Field(
        default_factory=list,
        description="List reasonably foreseeable use or misuse scenarios separately, including foreseeable integration, configuration, credential-sharing, or environmental conditions supported by evidence.",
    )
    health_safety_considerations: list[str] = Field(
        default_factory=list,
        description="List any evidenced effects of cybersecurity incidents on user health, safety, property, other persons, animals, environment, or public interest; use an empty list when no effect is evidenced.",
    )
    accessibility_considerations: list[str] = Field(
        default_factory=list,
        description="List accessibility needs or constraints affecting secure installation, authentication, operation, maintenance, or decommissioning; do not infer a user group without evidence.",
    )
    support_period: Optional[str] = Field(
        default=None,
        description="Extract the intended support period or end-of-support information exactly as provided; use null when it is not stated.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach evidence for intended purpose, foreseeable use, safety, accessibility, and support period, including source location whenever available.",
    )


class OperationalEnvironment(BaseModel):
    """Operational environment, network boundaries, and constraints."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(
        ...,
        description="Describe where and how the product operates, including deployment context, physical setting, connected systems, and relevant cybersecurity conditions.",
    )
    networks: list[str] = Field(
        default_factory=list,
        description="List each relevant network separately, including local, industrial, cloud, cellular, wireless, or internet-connected networks evidenced in the input.",
    )
    integrated_systems: list[str] = Field(
        default_factory=list,
        description="List each system, device, platform, or service integrated with the product as a separate item; preserve stated names.",
    )
    physical_environment: list[str] = Field(
        default_factory=list,
        description="List relevant physical conditions and access assumptions, such as indoor/outdoor deployment, temperature, environmental exposure, or physical protection.",
    )
    network_boundaries: list[str] = Field(
        default_factory=list,
        description="List each network or trust boundary separately and identify the interface or control that defines it when available.",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="List operational, connectivity, availability, safety, regulatory, or third-party platform constraints that affect cybersecurity; one constraint per item.",
    )
    rdps_dependency_map: Optional[str] = Field(
        default=None,
        description="Summarize RDPS operator, exchanged data, connectivity, authentication/trust relationship, availability expectation, and degraded mode; use null when no RDPS exists or is evidenced.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach source evidence for the operational environment, networks, boundaries, integrated systems, and constraints, with page/location whenever available.",
    )


class ProductFunction(BaseModel):
    """Existing product and cybersecurity function."""

    model_config = ConfigDict(extra="forbid")

    function_id: str = Field(
        ...,
        description="Assign a stable identifier such as FUNC-001 within this product context; do not reuse an identifier for different functions.",
    )
    name: str = Field(
        ...,
        description="Extract the function name as stated in the input material; keep names concise and distinguish similarly named functions.",
    )
    description: str = Field(
        ...,
        description="Describe the observable behavior, inputs, outputs, users, and connected components of the function using only supported facts.",
    )
    is_security_function: bool = Field(
        ...,
        description="Set true when the function directly provides or enforces cybersecurity protection, such as authentication, authorization, secure update, logging, cryptography, or input validation; otherwise set false.",
    )
    function_category: Optional[str] = Field(
        default=None,
        description="Classify the function, for example data collection, communication, configuration, authentication, access control, update, logging, or cryptography; use null when classification is unsupported.",
    )
    interfaces: list[str] = Field(
        default_factory=list,
        description="List product interfaces used or exposed by this function, one interface per item; preserve interface names and types from the evidence.",
    )
    rdps_dependencies: list[str] = Field(
        default_factory=list,
        description="List RDPS services or dependencies required by this function; use an empty list when none are evidenced.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="List known limitations, exclusions, or conditions that restrict this function, one item per limitation; do not invent missing behavior.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach evidence supporting the function behavior, category, security classification, interfaces, and dependencies.",
    )


class CommunicationMatrixEntry(BaseModel):
    """One communication flow in the TOE communication matrix."""

    model_config = ConfigDict(extra="forbid")

    flow_id: str = Field(
        ...,
        description="Assign a stable identifier such as FLOW-001 for this communication flow; do not combine different directions or protocols into one entry.",
    )
    source: str = Field(
        ...,
        description="Identify the source device, component, user, service, or network exactly as stated in the input.",
    )
    destination: str = Field(
        ...,
        description="Identify the destination device, component, user, service, or network exactly as stated in the input.",
    )
    direction: Optional[str] = Field(
        default=None,
        description=(
            "State the product-relative connection direction as inbound, outbound, or "
            "bidirectional only when the documented endpoints or connection role establish it; "
            "use null when the material only describes a listener, port exposure, topology, or "
            "business data direction without establishing connection direction."
        ),
    )
    direction_basis: Literal[
        "documented_endpoints",
        "connection_initiation",
        "listener_exposure",
        "business_data_flow",
        "unknown",
    ] = Field(
        default="unknown",
        description=(
            "Record what the direction statement means. Do not treat a listener/port table or "
            "business data direction as proof of connection initiation."
        ),
    )
    business_data_direction: Literal[
        "to_product",
        "from_product",
        "bidirectional",
        "unknown",
    ] = Field(
        default="unknown",
        description=(
            "Record the evidenced business payload direction separately from connection "
            "initiation; leave unknown when only endpoints, a listener, or a protocol are known."
        ),
    )
    activation_status: Literal[
        "enabled",
        "disabled_by_default",
        "conditional",
        "unknown",
    ] = Field(
        default="unknown",
        description=(
            "Record whether the communication is enabled, disabled by default, conditional on "
            "configuration/deployment, or unresolved. Capability existence is not the same as "
            "activation in the delivered configuration."
        ),
    )
    conditions: list[str] = Field(
        default_factory=list,
        description=(
            "List activation, option, deployment, or configuration conditions stated for this "
            "flow; do not invent missing conditions."
        ),
    )
    interface: Optional[str] = Field(
        default=None,
        description="State the physical or logical interface used by the flow, such as Ethernet, RS485, USB, cellular, API, or Web; use null when not specified.",
    )
    protocol: Optional[str] = Field(
        default=None,
        description="State the communication protocol exactly as evidenced, such as TCP, UDP, HTTP, HTTPS, MQTT, Modbus, or proprietary; use null when not specified.",
    )
    port: Optional[str] = Field(
        default=None,
        description="Record the port number or port range exactly as stated, including transport where available, for example TCP/443; use null when not specified.",
    )
    data_exchanged: list[str] = Field(
        default_factory=list,
        description="List the data, commands, credentials, configuration, telemetry, or updates exchanged by this flow; use one data category per item.",
    )
    encryption: Optional[str] = Field(
        default=None,
        description="Describe the evidenced encryption mechanism and scope, such as TLS 1.3, VPN encryption, link encryption, or none stated; do not infer encryption from the protocol name.",
    )
    authentication: Optional[str] = Field(
        default=None,
        description="Describe the evidenced endpoint, user, or message authentication mechanism; use null when authentication is not specified.",
    )
    security_notes: list[str] = Field(
        default_factory=list,
        description="List communication-specific security observations or limitations, one item per observation; distinguish evidence from open questions.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach evidence for every material communication-matrix field, including page, diagram, table, or section location whenever available.",
    )


class CommunicationMatrix(BaseModel):
    """TOE communication matrix."""

    model_config = ConfigDict(extra="forbid")

    entries: list[CommunicationMatrixEntry] = Field(
        default_factory=list,
        description="List every evidenced communication flow in the TOE as a separate entry, preserving direction and interface distinctions; use an empty list only when no communication is evidenced.",
    )
    completeness_notes: Optional[str] = Field(
        default=None,
        description="State known coverage limitations, missing diagrams, or unresolved communication details; use null when no limitation is known.",
    )


class ComponentInventoryEntry(BaseModel):
    """One hardware, software, firmware, service, or third-party component."""

    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(
        ...,
        description="Assign a stable identifier such as COMP-001 for this component; do not reuse an identifier for different components.",
    )
    name: str = Field(
        ...,
        description="Extract the component name exactly as stated in the input material, including vendor/product name when available.",
    )
    component_type: str = Field(
        ...,
        description="Classify the component as hardware, firmware, software, cloud service, RDPS, library, operating system, network device, or other evidenced type.",
    )
    scope_status: Literal["confirmed", "conditional", "external", "unknown"] = Field(
        default="unknown",
        description="Mark whether the component is confirmed in the assessed product, conditional on BOM/configuration, external to the product, or unresolved.",
    )
    conditions: list[str] = Field(
        default_factory=list,
        description="List delivery, BOM, option, configuration, or boundary conditions; leave empty only for an unconditionally confirmed component.",
    )
    version: Optional[str] = Field(
        default=None,
        description="Extract the component version, release, model, or revision exactly as stated; use null when not provided.",
    )
    supplier: Optional[str] = Field(
        default=None,
        description="Extract the component supplier, vendor, developer, or operator exactly as stated; use null when not provided.",
    )
    role: str = Field(
        ...,
        description="Describe the component's role in delivering the product function or cybersecurity function using supported facts.",
    )
    is_third_party: Optional[bool] = Field(
        default=None,
        description=(
            "Set true only when evidence identifies an external supplier, developer, or operator; "
            "set false only when first-party responsibility is evidenced; otherwise use null. "
            "Being outside the assessed product boundary does not by itself prove third-party ownership."
        ),
    )
    support_period: Optional[str] = Field(
        default=None,
        description="Extract the component support period or end-of-support information exactly as provided; use null when not stated.",
    )
    interfaces: list[str] = Field(
        default_factory=list,
        description="List interfaces through which this component connects to the TOE or external systems, one interface per item.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach evidence supporting component identity, type, version, supplier, role, third-party status, and interfaces.",
    )


class ComponentInventory(BaseModel):
    """Digital component inventory for the TOE."""

    model_config = ConfigDict(extra="forbid")

    entries: list[ComponentInventoryEntry] = Field(
        default_factory=list,
        description="List every identified hardware, firmware, software, service, RDPS, and relevant third-party component as a separate entry.",
    )
    completeness_notes: Optional[str] = Field(
        default=None,
        description="State missing bills of materials, unknown versions, unidentified suppliers, or other inventory limitations; use null when no limitation is known.",
    )


class CybersecurityObjective(BaseModel):
    """Cybersecurity objective retained for later asset analysis stages."""

    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(
        ...,
        pattern=r"^OBJ-[0-9]{3,}$",
        description="Assign a stable identifier such as OBJ-001 for this cybersecurity objective; do not reuse an identifier for different objectives.",
    )
    description: str = Field(
        ...,
        description="State the security result to be achieved for the related asset, using a concise and verifiable outcome.",
    )
    category: Literal[
        "confidentiality",
        "integrity",
        "availability",
        "authenticity",
        "accountability",
        "data_minimization",
    ] = Field(
        ...,
        description="Classify the objective using one supported protection-result category.",
    )
    basis: Literal[
        "explicit_requirement",
        "asset_value_or_consequence",
        "legal_or_standard",
        "analyst_minimum",
        "unknown",
    ] = Field(
        default="unknown",
        description=(
            "State why this protection result is proposed: an explicit customer requirement, "
            "an evidenced asset value or consequence, a cited legal/standard requirement, a "
            "conservative analyst minimum, or unknown. This does not assert that a control exists."
        ),
    )
    status: Literal["supported", "needs_confirmation"] = Field(
        default="needs_confirmation",
        description=(
            "Use supported only when the selected basis is directly traceable. Analyst-minimum, "
            "unknown, missing, or conflicting bases remain needs_confirmation."
        ),
    )
    legal_basis: list[LegalBasis] = Field(
        default_factory=list,
        description=(
            "Record only legal or standard references explicitly present in the cited material, "
            "including a traceable article, clause, annex, or sub-clause; otherwise use an empty list."
        ),
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description=(
            "Attach evidence supporting the need for this protection result and its relationship "
            "to the asset. Reuse evidence also attached to the parent asset. Evidence that a "
            "feature exists does not prove that the objective is already achieved."
        ),
    )


class AssetFunctionRelationship(BaseModel):
    """Typed, reviewable relationship between one asset and one Node [1] function."""

    model_config = ConfigDict(extra="forbid")

    function_id: str = Field(
        ...,
        pattern=r"^FUNC-[0-9]{3,}$",
        description="Reuse one exact function_id from the supplied Node [1] function catalog.",
    )
    relationship_type: Literal[
        "reads",
        "creates",
        "modifies",
        "transmits",
        "authenticates_with",
        "implements",
        "protects",
        "depends_on",
        "affects",
    ] = Field(
        ...,
        description=(
            "Describe the direct relationship from the function to the asset. Use affects for "
            "an evidenced consequence on an external person, property, environment, or public "
            "interest; do not use co-location or a generic platform dependency as a relationship."
        ),
    )
    rationale: str = Field(
        ...,
        min_length=1,
        description=(
            "Briefly state the input-supported behavior that makes the relationship direct; "
            "do not add an attack scenario, implementation control, or unsupported capability."
        ),
    )


class Asset(BaseModel):
    """Asset model retained for later step [2] analysis."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(
        ...,
        pattern=r"^ASSET-[0-9]{3,}$",
        description="Assign a stable identifier such as ASSET-001 for this asset; do not reuse an identifier for different assets.",
    )
    name: str = Field(
        ...,
        description="Extract the asset name exactly as supported by the input; do not invent an asset that is not related to the TOE.",
    )
    asset_type: Literal[
        "data",
        "credential",
        "software",
        "hardware",
        "network",
        "service",
        "function",
        "user",
        "property",
        "environment",
        "public_interest",
        "other",
    ] = Field(
        ...,
        description="Use one reviewed minimum-coverage asset type; use other only when none of the listed types fits and explain the reason.",
    )
    status: Literal[
        "confirmed",
        "conditional",
        "external_affected",
        "needs_confirmation",
    ] = Field(
        ...,
        description=(
            "Set confirmed for an evidenced product asset, conditional when presence or delivery depends on BOM/configuration, "
            "external_affected for a connected or affected object outside the product, and needs_confirmation when the evidence "
            "only supports a candidate requiring engineer confirmation. A disabled-by-default feature may still be confirmed."
        ),
    )
    related_function_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Compatibility index of Node [1] FUNC-xxx identifiers related to this asset. It is "
            "derived from function_relationships when typed relationships are available; the "
            "relationship does not itself prove that the asset exists."
        ),
    )
    function_relationships: list[AssetFunctionRelationship] = Field(
        default_factory=list,
        description=(
            "List only major, direct, typed relationships to Node [1] functions. Keep this empty "
            "when the available material supports the asset but not a specific functional link."
        ),
    )
    description: str = Field(
        ...,
        description="Describe the value-bearing asset and how it relates to, is processed by, or may be affected by the TOE.",
    )
    location: Optional[str] = Field(
        default=None,
        description="State where the asset is stored, processed, transmitted, implemented, or located; use null when unknown.",
    )
    value: Optional[str] = Field(
        default=None,
        description="Describe the asset value or consequence of compromise using supported facts; use null when not established.",
    )
    related_objectives: list[CybersecurityObjective] = Field(
        default_factory=list,
        description="List every cybersecurity objective related to this asset; use an empty list only when objective analysis has not yet been performed.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach evidence supporting the asset, its location, value, and related objectives.",
    )


class AssetIdentificationResult(BaseModel):
    """Validated output of step [2] asset and cybersecurity-objective identification."""

    model_config = ConfigDict(extra="forbid")

    assets: list[Asset] = Field(
        ...,
        min_length=1,
        description="List all identified value-bearing assets. Every asset must include at least one cybersecurity objective.",
    )
    assessment: AssessmentVerdict = Field(
        default=AssessmentVerdict.FAIL,
        description="Set PASS only when asset and objective coverage is complete; otherwise use PARTIAL or FAIL.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Explain coverage limitations, missing evidence, unresolved assets, or required reviewer attention.",
    )

    @model_validator(mode="after")
    def validate_asset_identity_and_objectives(self) -> Self:
        """Reject duplicate/blank identifiers and assets without security objectives."""
        asset_ids: list[str] = []
        objective_ids: list[str] = []
        for asset in self.assets:
            asset_id = asset.asset_id.strip()
            if not asset_id:
                raise ValueError("Every asset must have a non-empty asset_id.")
            if not asset.related_objectives:
                raise ValueError(f"Asset {asset_id} must have at least one cybersecurity objective.")
            asset_ids.append(asset_id)

            for objective in asset.related_objectives:
                objective_id = objective.objective_id.strip()
                if not objective_id:
                    raise ValueError(f"Asset {asset_id} contains a blank objective_id.")
                objective_ids.append(objective_id)

        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_id values must be unique within the asset inventory.")
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("objective_id values must be unique across the asset inventory.")
        return self


class AssetSectionResult(BaseModel):
    """One independently generated Node [2] asset section; it may be empty with an explanation."""

    model_config = ConfigDict(extra="forbid")

    assets: list[Asset] = Field(
        default_factory=list,
        description="List assets supported for this section; use an empty list when this section has no supported asset.",
    )
    assessment: AssessmentVerdict = Field(
        default=AssessmentVerdict.PARTIAL,
        description="Set PASS only when this section is complete; otherwise use PARTIAL or FAIL.",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Explain an empty section, evidence gaps, conditions, or reviewer attention.",
    )
    rejected_items: list[str] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "System-generated concise reasons for item-level validation rejection. "
            "The model must leave this empty."
        ),
    )

    @model_validator(mode="after")
    def validate_section_identity_and_notes(self) -> Self:
        if not self.assets and not (self.notes or "").strip():
            raise ValueError("An empty asset section requires explanatory notes.")
        asset_ids = [asset.asset_id.strip() for asset in self.assets]
        objective_ids = [
            objective.objective_id.strip()
            for asset in self.assets
            for objective in asset.related_objectives
        ]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("asset_id values must be unique within an asset section.")
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("objective_id values must be unique within an asset section.")
        return self


class AssetFunctionMappingEntry(BaseModel):
    """One focused many-to-many mapping from an existing asset to Node [1] functions."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(
        ...,
        pattern=r"^ASSET-[0-9]{3,}$",
        description="Reuse one exact asset_id from the supplied asset inventory.",
    )
    related_function_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Legacy compatibility list. Leave empty when relationships is populated; new mapping "
            "results should express every accepted link as a typed relationship."
        ),
    )
    relationships: list[AssetFunctionRelationship] = Field(
        default_factory=list,
        description=(
            "Typed direct relationships for this asset. Do not emit a relationship merely to "
            "cover a function identifier."
        ),
    )


class AssetFunctionMappingResult(BaseModel):
    """Focused function relationships; it cannot add or rewrite business assets."""

    model_config = ConfigDict(extra="forbid")

    mappings: list[AssetFunctionMappingEntry] = Field(default_factory=list)
    notes: Optional[str] = Field(
        default=None,
        description="Briefly state unresolved mapping uncertainty; do not repeat the mappings.",
    )


class ProductContextOverview(BaseModel):
    """Identity, use, users, environment, and completeness for section synthesis."""

    model_config = ConfigDict(extra="forbid")

    product_name: str
    product_version: Optional[str] = None
    iprfu: IPRFU
    user_description: UserDescription
    operational_environment: OperationalEnvironment
    rdps_dependencies: Optional[str] = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assessment: AssessmentVerdict = AssessmentVerdict.FAIL
    assessment_notes: Optional[str] = None


class ProductFunctionCatalog(BaseModel):
    """Detailed functions and their two human-readable summary lists."""

    model_config = ConfigDict(extra="forbid")

    functions: list[ProductFunction] = Field(default_factory=list)
    existing_security_functions: list[str] = Field(default_factory=list)
    existing_non_security_functions: list[str] = Field(default_factory=list)


class ProductContext(BaseModel):
    """Aggregated TOE Context for Node [1]."""

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(
        ...,
        description="Extract the official product name exactly as stated in the input material; use the same name consistently throughout the context.",
    )
    product_version: Optional[str] = Field(
        default=None,
        description="Extract the product version, model, hardware revision, or software version exactly as stated; use null when no version is provided.",
    )
    iprfu: IPRFU = Field(
        ...,
        description="Provide the structured intended purpose and reasonably foreseeable use for the TOE, including safety and accessibility considerations.",
    )
    user_description: UserDescription = Field(
        ...,
        description="Provide the structured description of intended users, their capabilities, vulnerable groups, and responsibilities.",
    )
    operational_environment: OperationalEnvironment = Field(
        ...,
        description="Provide the structured operational environment, networks, boundaries, integrated systems, RDPS dependencies, and constraints.",
    )
    functions: list[ProductFunction] = Field(
        default_factory=list,
        description="List all evidenced product functions, including both cybersecurity functions and non-security functions; do not omit security functions.",
    )
    communication_matrix: CommunicationMatrix = Field(
        ...,
        description="Provide the complete structured communication matrix for the TOE, based only on evidenced flows.",
    )
    component_inventory: ComponentInventory = Field(
        ...,
        description="Provide the structured inventory of TOE hardware, software, firmware, services, RDPS, and third-party components.",
    )
    existing_security_functions: list[str] = Field(
        default_factory=list,
        description="Summarize existing cybersecurity functions already evidenced in the customer materials, one function per item; do not infer implementation.",
    )
    existing_non_security_functions: list[str] = Field(
        default_factory=list,
        description="Summarize existing non-security product functions already evidenced in the customer materials, one function per item.",
    )
    rdps_dependencies: Optional[str] = Field(
        default=None,
        description="Summarize all RDPS dependencies and their role in the TOE; use null only when no RDPS dependency is evidenced.",
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list,
        description="Attach evidence supporting the aggregated TOE Context and its major sections; retain source locations for later traceability.",
    )
    assessment: AssessmentVerdict = Field(
        default=AssessmentVerdict.FAIL,
        description="Set PASS only when the required TOE Context sections exist and have sufficient supporting evidence; otherwise use FAIL or PARTIAL.",
    )
    assessment_notes: Optional[str] = Field(
        default=None,
        description="Explain context completeness, missing evidence, unresolved questions, contradictions, or required human review; use null only when no note is needed.",
    )
