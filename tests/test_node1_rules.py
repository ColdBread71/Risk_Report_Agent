from types import SimpleNamespace

import pytest

from main import _build_parser
from core.exporter import _build_progress_workbook
from core.policy import build_risk_acceptance_criteria
from nodes.field_extractor import NodeFactBundle, _cache_inputs, _stable_sha256
from nodes.asset_threat_modeler import _asset_candidate_context
from nodes.context_builder import (
    _assemble_product_context,
    _context_section_cache_inputs,
    _context_section_material,
    _load_context_section_checkpoint,
    _mark_product_context_as_draft,
    _save_context_section_checkpoint,
    _scope_downstream_payload,
)
from schemas.evidence_packet import EvidenceTargetNode
from schemas.evidence import EvidenceRef, SourceRef
from schemas.legal import ProductClassification, ScopeStatement
from schemas.product import (
    CommunicationMatrixEntry,
    ComponentInventoryEntry,
    ProductContext,
    ProductContextOverview,
    ProductFunctionCatalog,
)
from schemas.retrieval import (
    FieldExtractionResult,
    RetrievalField,
    RetrievalRequest,
    RetrievedFact,
)
from tools.rag_retriever import _promote_targeted_anchors
from tools.retrieval_profiles import (
    get_retrieval_profile,
    get_targeted_anchor_groups,
)


def _scope() -> ScopeStatement:
    return ScopeStatement(
        product_name="EMU300A",
        classification=ProductClassification(has_rdps=None),
        scope_description="EMU300A 产品范围草稿。",
        assumptions=["实际交付 BOM 是什么？"],
        review_notes=["系统内部修复说明不应传给下游模型。"],
    )


def _context() -> ProductContext:
    return ProductContext.model_validate(
        {
            "product_name": "EMU300A",
            "iprfu": {"intended_purpose": "采集数据并执行调度。"},
            "user_description": {
                "user_types": ["运维人员"],
                "experience_level": "材料未说明具体培训水平。",
                "is_component": None,
            },
            "operational_environment": {"description": "工业网络环境。"},
            "communication_matrix": {},
            "component_inventory": {},
            "assessment": "PARTIAL",
        }
    )


def _evidence(block_id: str, quote: str) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=f"EVD-{block_id[-8:]}",
        source=SourceRef(
            file_name="manual.pdf",
            file_path="Project/manual.pdf",
            file_type="pdf",
            document_id="DOC-AAAAAAAAAAAA",
            block_id=block_id,
        ),
        quote=quote,
        evidence_level="direct",
    )


def test_node1_dense_fields_have_larger_bounded_profiles():
    communications = get_retrieval_profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.COMMUNICATIONS,
    )
    assert communications.max_blocks == 48
    assert communications.neighbor_window == 4
    assert communications.max_facts == 24
    assert "跨页或拆块表格" in communications.extraction_guidance
    assert "日志服务" in communications.query
    assert "管理端口" in communications.query

    users = get_retrieval_profile(EvidenceTargetNode.CONTEXT, RetrievalField.USERS)
    assert users.max_blocks == 24
    assert users.max_facts == 12


def test_communication_anchor_groups_promote_four_generic_evidence_blocks():
    blocks = [
        SimpleNamespace(
            block_id="ordinary",
            document_id="doc",
            section_path=["普通通信"],
            text="HTTPS TCP 443",
        ),
        SimpleNamespace(
            block_id="endpoints",
            document_id="doc",
            section_path=["通信矩阵"],
            text="源设备为控制器，目的设备为上级系统。",
        ),
        SimpleNamespace(
            block_id="protocol_port",
            document_id="doc",
            section_path=["协议端口"],
            text="协议为TCP，端口为443。",
        ),
        SimpleNamespace(
            block_id="interface_direction",
            document_id="doc",
            section_path=["接口方向"],
            text="接口为WAN口，方向为上行。",
        ),
        SimpleNamespace(
            block_id="default_enabled",
            document_id="doc",
            section_path=["默认状态"],
            text="该通信能力默认启用。",
        ),
    ]
    ranked = [(block, 1.0 - index / 10) for index, block in enumerate(blocks)]
    anchors = get_targeted_anchor_groups(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.COMMUNICATIONS,
    )
    promoted = _promote_targeted_anchors(
        ranked,
        source_names={"doc": "manual.pdf"},
        anchor_groups=anchors,
    )
    assert [item[0].block_id for item in promoted[:4]] == [
        "endpoints",
        "protocol_port",
        "interface_direction",
        "default_enabled",
    ]


def test_field_cache_fingerprint_changes_with_profile_content():
    profile = get_retrieval_profile(
        EvidenceTargetNode.CONTEXT,
        RetrievalField.COMMUNICATIONS,
    )
    request = RetrievalRequest(
        project_id="project",
        node_id=profile.node_id,
        field_id=profile.field_id,
    )
    trace = SimpleNamespace(
        scope_packet_sha256="a" * 64,
        packet_sha256="b" * 64,
        index_id="IDX-1234567890ABCDEF",
    )
    original = _cache_inputs(
        request=request,
        trace=trace,
        text_model="qwen-plus",
        profile=profile,
    )
    changed = _cache_inputs(
        request=request,
        trace=trace,
        text_model="qwen-plus",
        profile=profile.model_copy(update={"query": profile.query + " 新规则"}),
    )
    assert _stable_sha256(original) != _stable_sha256(changed)


def test_node_fact_bundle_can_limit_final_synthesis_to_relevant_fields():
    functions = FieldExtractionResult(
        node_id=EvidenceTargetNode.CONTEXT,
        field_id=RetrievalField.FUNCTIONS,
        facts=[
            RetrievedFact(
                fact_id="FACT-001",
                statement="设备支持数据采集。",
                block_ids=["BLK-AAAAAAAAAAAAAAAA"],
            )
        ],
    )
    components = FieldExtractionResult(
        node_id=EvidenceTargetNode.CONTEXT,
        field_id=RetrievalField.COMPONENTS,
        unknowns=["组件待确认"],
    )
    bundle = NodeFactBundle(
        batches=(functions, components),
        traces=(),
        retrieved_block_ids=frozenset(
            {"BLK-AAAAAAAAAAAAAAAA", "BLK-BBBBBBBBBBBBBBBB"}
        ),
    )
    payload = bundle.prompt_payload({RetrievalField.FUNCTIONS})
    assert [batch["field_id"] for batch in payload["field_batches"]] == ["functions"]
    assert payload["evidence_contract"]["fact_support"] == [
        {
            "fact_ref": "functions/FACT-001",
            "field_id": "functions",
            "statement": "设备支持数据采集。",
            "block_ids": ["BLK-AAAAAAAAAAAAAAAA"],
            "is_uncertain": False,
        }
    ]
    assert bundle.fact_block_ids({RetrievalField.FUNCTIONS}) == frozenset(
        {"BLK-AAAAAAAAAAAAAAAA"}
    )


def test_section_evidence_contract_limits_scope_references_by_section():
    scope_evidence = EvidenceRef(
        evidence_id="EVD-SCOPE",
        source=SourceRef(
            file_name="scope.pdf",
            file_path="Project/scope.pdf",
            file_type="pdf",
            document_id="DOC-AAAAAAAAAAAA",
            block_id="BLK-CCCCCCCCCCCCCCCC",
        ),
        evidence_level="direct",
    )
    scope = _scope().model_copy(update={"evidence": [scope_evidence]})
    functions = FieldExtractionResult(
        node_id=EvidenceTargetNode.CONTEXT,
        field_id=RetrievalField.FUNCTIONS,
        facts=[
            RetrievedFact(
                fact_id="FACT-001",
                statement="设备支持数据采集。",
                block_ids=["BLK-AAAAAAAAAAAAAAAA"],
            )
        ],
    )
    components = FieldExtractionResult(
        node_id=EvidenceTargetNode.CONTEXT,
        field_id=RetrievalField.COMPONENTS,
        unknowns=["组件待确认"],
    )
    bundle = NodeFactBundle(
        batches=(functions, components),
        traces=(),
        retrieved_block_ids=frozenset(
            {"BLK-AAAAAAAAAAAAAAAA", "BLK-CCCCCCCCCCCCCCCC"}
        ),
    )

    function_material, function_blocks = _context_section_material(
        section_name="functions",
        scope=scope,
        facts=bundle,
    )
    assert function_material["evidence_contract"]["scope_support"] == []
    assert function_blocks == {"BLK-AAAAAAAAAAAAAAAA"}

    component_material, component_blocks = _context_section_material(
        section_name="components",
        scope=scope,
        facts=bundle,
    )
    assert component_material["evidence_contract"]["scope_support"][0][
        "block_id"
    ] == "BLK-CCCCCCCCCCCCCCCC"
    assert component_blocks == {
        "BLK-AAAAAAAAAAAAAAAA",
        "BLK-CCCCCCCCCCCCCCCC",
    }


def test_four_context_sections_assemble_to_the_existing_product_context_contract():
    context = _context()
    overview = ProductContextOverview(
        product_name=context.product_name,
        product_version=context.product_version,
        iprfu=context.iprfu,
        user_description=context.user_description,
        operational_environment=context.operational_environment,
        rdps_dependencies=context.rdps_dependencies,
        evidence=context.evidence,
        assessment=context.assessment,
        assessment_notes=context.assessment_notes,
    )
    functions = ProductFunctionCatalog(
        functions=context.functions,
        existing_security_functions=context.existing_security_functions,
        existing_non_security_functions=context.existing_non_security_functions,
    )
    assembled = _assemble_product_context(
        overview,
        functions,
        context.component_inventory,
        context.communication_matrix,
    )
    assert assembled.model_dump(mode="json") == context.model_dump(mode="json")


def test_context_section_cache_is_fingerprinted_and_round_trips(tmp_path):
    material = {"scope": {"product_name": "EMU300A"}, "field_batches": []}
    inputs = _context_section_cache_inputs(
        section_name="functions",
        source_packet_sha256="a" * 64,
        text_model="qwen-plus",
        material_payload=material,
        schema_class=ProductFunctionCatalog,
    )
    changed = _context_section_cache_inputs(
        section_name="functions",
        source_packet_sha256="a" * 64,
        text_model="qwen-plus",
        material_payload={**material, "field_batches": [{"new": "fact"}]},
        schema_class=ProductFunctionCatalog,
    )
    fingerprint = _stable_sha256(inputs)
    assert fingerprint != _stable_sha256(changed)
    assert inputs["context_rule_version"] == "node1_context_rules.v7.1"
    overview_inputs = _context_section_cache_inputs(
        section_name="overview",
        source_packet_sha256="a" * 64,
        text_model="qwen-plus",
        material_payload=material,
        schema_class=ProductContextOverview,
    )
    assert overview_inputs["context_rule_version"] == "node1_context_rules.v7.1"
    communication_inputs = _context_section_cache_inputs(
        section_name="communications",
        source_packet_sha256="a" * 64,
        text_model="qwen-plus",
        material_payload=material,
        schema_class=type(_context().communication_matrix),
    )
    assert communication_inputs["context_rule_version"] == "node1_context_rules.v7.4"

    path = tmp_path / "functions.json"
    result = ProductFunctionCatalog(existing_security_functions=["身份鉴别"])
    _save_context_section_checkpoint(
        path=path,
        cache_inputs=inputs,
        fingerprint=fingerprint,
        result=result,
    )
    loaded = _load_context_section_checkpoint(
        path=path,
        fingerprint=fingerprint,
        schema_class=ProductFunctionCatalog,
    )
    assert loaded == result
    assert (
        _load_context_section_checkpoint(
            path=path,
            fingerprint="different",
            schema_class=ProductFunctionCatalog,
        )
        is None
    )


def test_cli_cache_policy_is_explicit_and_defaults_to_reuse():
    parser = _build_parser()
    required = ["--evidence-packet", "packet.json"]
    assert parser.parse_args(required).cache_policy == "reuse"
    assert parser.parse_args([*required, "--cache-policy", "refresh"]).cache_policy == "refresh"


def test_node1_can_represent_unknown_component_status():
    assert _context().user_description.is_component is None


def test_upstream_schema_additions_are_backward_compatible_with_old_json():
    flow = CommunicationMatrixEntry.model_validate(
        {
            "flow_id": "FLOW-001",
            "source": "产品",
            "destination": "外部服务",
        }
    )
    assert flow.direction_basis == "unknown"
    assert flow.business_data_direction == "unknown"
    assert flow.activation_status == "unknown"
    assert flow.conditions == []

    component = ComponentInventoryEntry.model_validate(
        {
            "component_id": "COMP-001",
            "name": "控制模块",
            "component_type": "hardware",
            "role": "执行产品功能。",
        }
    )
    assert component.is_third_party is None


def test_product_context_is_an_engineer_review_draft():
    context = _context().model_copy(
        update={"assessment_notes": "检查 FACT-012 和 FACT-XXX，当前资料仍有缺口。"}
    )
    draft = _mark_product_context_as_draft(context, _scope())
    assert draft.product_name == "EMU300A"
    assert draft.assessment.value == "PARTIAL"
    assert "FACT-012" not in draft.assessment_notes
    assert "FACT-XXX" not in draft.assessment_notes
    assert "待工程师确认" in draft.assessment_notes


def test_node1_correction_rules_keep_optional_components_and_claims_conservative():
    support_block = "BLK-6666666666666666"
    communication_block = "BLK-7777777777777777"
    facts = NodeFactBundle(
        batches=(
            FieldExtractionResult(
                node_id=EvidenceTargetNode.CONTEXT,
                field_id=RetrievalField.SECURITY_FUNCTIONS,
                facts=[
                    RetrievedFact(
                        fact_id="FACT-001",
                        statement="支持软件和固件更新。",
                        block_ids=[support_block],
                    ),
                    RetrievedFact(
                        fact_id="FACT-002",
                        statement="支持恢复出厂设置功能，删除设备数据。",
                        block_ids=[support_block],
                    ),
                ],
            ),
            FieldExtractionResult(
                node_id=EvidenceTargetNode.CONTEXT,
                field_id=RetrievalField.COMMUNICATIONS,
                facts=[
                    RetrievedFact(
                        fact_id="FACT-001",
                        statement="PC到EMU300A使用UDP协议，目的端口为9998–9999。",
                        block_ids=[communication_block],
                    )
                ],
            ),
        ),
        traces=(),
        retrieved_block_ids=frozenset({support_block, communication_block}),
    )
    payload = _context().model_dump(mode="json")
    payload["functions"] = [
        {
            "function_id": "FUNC-001",
            "name": "软件与固件更新",
            "description": "支持更新，具备完整性校验与回滚能力。",
            "is_security_function": True,
            "evidence": [_evidence(support_block, "软件和固件更新").model_dump(mode="json")],
        },
        {
            "function_id": "FUNC-002",
            "name": "恢复出厂设置",
            "description": "清除所有用户配置、网络参数、证书和所有日志，恢复初始交付状态。",
            "is_security_function": True,
            "evidence": [
                _evidence(support_block, "恢复出厂设置功能，删除设备数据").model_dump(
                    mode="json"
                )
            ],
        },
    ]
    payload["component_inventory"] = {
        "entries": [
            {
                "component_id": "COMP-001",
                "name": "MPLC模块",
                "component_type": "hardware",
                "scope_status": "confirmed",
                "conditions": ["可选配置，支持1路或2路MPLC通信能力"],
                "role": "提供MPLC通信能力。",
                "is_third_party": False,
            }
        ]
    }
    payload["communication_matrix"] = {
        "entries": [],
        "completeness_notes": "TCP/UDP等未提及接口不生成条目；其他信息待确认。",
    }
    scope = _scope().model_copy(
        update={"in_scope_components": ["MPLC通信能力（物理接口存在）"]}
    )

    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(payload),
        scope,
        facts,
    )

    assert draft.functions[0].description == "支持软件和固件更新。"
    assert draft.functions[1].description == "支持恢复出厂设置功能，删除设备数据。"
    assert draft.component_inventory.entries[0].scope_status == "conditional"
    assert "UDP" not in (draft.communication_matrix.completeness_notes or "")
    assert "其他信息待确认" in (draft.communication_matrix.completeness_notes or "")


def test_product_context_downgrades_unconfirmed_rdps_and_unsupported_inference():
    payload = _context().model_dump(mode="json")
    payload["iprfu"]["reasonably_foreseeable_use"] = [
        "断网时依赖离线能力（未明确说明，但属合理预期）"
    ]
    payload["user_description"]["experience_level"] = "所有用户均接受安全培训。"
    payload["user_description"]["rdps_dependence"] = "用户依赖云端RDPS。"
    payload["operational_environment"]["rdps_dependency_map"] = "阳光云作为RDPS。"
    payload["functions"] = [
        {
            "function_id": "FUNC-001",
            "name": "云上传",
            "description": "上传数据。",
            "is_security_function": False,
            "rdps_dependencies": ["阳光云"],
        }
    ]
    payload["rdps_dependencies"] = "阳光云作为RDPS。"
    draft = _mark_product_context_as_draft(ProductContext.model_validate(payload), _scope())
    assert draft.iprfu.reasonably_foreseeable_use == []
    assert draft.user_description.experience_level is None
    assert draft.user_description.rdps_dependence is None
    assert draft.operational_environment.rdps_dependency_map is None
    assert draft.rdps_dependencies is None
    assert draft.functions[0].rdps_dependencies == []
    assert "尚未确认RDPS" in draft.assessment_notes


def test_node1_deterministic_rules_repair_high_impact_model_errors():
    nts_block = "BLK-1111111111111111"
    goose_block = "BLK-2222222222222222"
    port_block = "BLK-3333333333333333"
    security_block = "BLK-4444444444444444"
    component_block = "BLK-5555555555555555"
    batches = (
        FieldExtractionResult(
            node_id=EvidenceTargetNode.CONTEXT,
            field_id=RetrievalField.COMMUNICATIONS,
            facts=[
                RetrievedFact(
                    fact_id="FACT-001",
                    statement=(
                        "EMU300A支持NTS协议，源设备为EMU300A，目的设备为NTS对时服务器，"
                        "目的端口为4460，默认关闭。"
                    ),
                    block_ids=[nts_block],
                ),
                RetrievedFact(
                    fact_id="FACT-002",
                    statement="GOOSE协议默认关闭，端点未说明。",
                    block_ids=[goose_block],
                ),
                RetrievedFact(
                    fact_id="FACT-003",
                    statement=(
                        "EMU300A支持IEC104协议，源设备为北向设备，目的设备为EMU300A，"
                        "目的端口为2418。"
                    ),
                    block_ids=[port_block],
                ),
            ],
        ),
        FieldExtractionResult(
            node_id=EvidenceTargetNode.CONTEXT,
            field_id=RetrievalField.SECURITY_FUNCTIONS,
            facts=[
                RetrievedFact(
                    fact_id="FACT-001",
                    statement="支持NTS安全对时。",
                    block_ids=[security_block],
                )
            ],
        ),
        FieldExtractionResult(
            node_id=EvidenceTargetNode.CONTEXT,
            field_id=RetrievalField.COMPONENTS,
            facts=[
                RetrievedFact(
                    fact_id="FACT-001",
                    statement="Logger5000集成五路以太网接口和快速调度端口。",
                    block_ids=[component_block],
                )
            ],
        ),
    )
    facts = NodeFactBundle(
        batches=batches,
        traces=(),
        retrieved_block_ids=frozenset(
            {nts_block, goose_block, port_block, security_block, component_block}
        ),
    )
    payload = _context().model_dump(mode="json")
    payload["functions"] = [
        {
            "function_id": "FUNC-001",
            "name": "NTS网络对时",
            "description": "安全对时能力 FACT-009。",
            "is_security_function": False,
            "evidence": [_evidence(security_block, "支持NTS安全对时。").model_dump(mode="json")],
        }
    ]
    payload["component_inventory"] = {
        "entries": [
            {
                "component_id": "COMP-001",
                "name": "Logger5000",
                "component_type": "firmware",
                "role": "内置数据采集器，提供物理接口和协议转换。",
                "is_third_party": False,
                "evidence": [
                    _evidence(component_block, "Logger5000集成五路以太网接口。").model_dump(
                        mode="json"
                    )
                ],
            }
        ]
    }
    payload["communication_matrix"] = {
        "entries": [
            {
                "flow_id": "FLOW-001",
                "source": "EMU300A",
                "destination": "NTS对时服务器",
                "protocol": "NTS",
                "evidence": [_evidence(nts_block, "4460 NTS 默认关闭").model_dump(mode="json")],
            },
            {
                "flow_id": "FLOW-002",
                "source": "EMU300A",
                "destination": "阳光云平台",
                "protocol": "GOOSE",
                "evidence": [_evidence(goose_block, "GOOSE协议默认关闭").model_dump(mode="json")],
            },
            {
                "flow_id": "FLOW-003",
                "source": "北向设备",
                "destination": "EMU300A",
                "protocol": "IEC104",
                "port": "TCP/2418",
                "evidence": [_evidence(port_block, "北向设备到EMU300A端口2418").model_dump(mode="json")],
            },
            {
                "flow_id": "FLOW-004",
                "source": "EMU300A",
                "destination": "站控系统",
                "protocol": "IEC104",
                "port": "TCP/2418",
                "evidence": [_evidence(port_block, "北向设备到EMU300A端口2418").model_dump(mode="json")],
            },
        ]
    }
    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(payload),
        _scope(),
        facts,
    )

    nts = next(flow for flow in draft.communication_matrix.entries if flow.protocol == "NTS")
    goose = next(flow for flow in draft.communication_matrix.entries if flow.protocol == "GOOSE")
    iec104 = [flow for flow in draft.communication_matrix.entries if flow.protocol == "IEC104"]
    assert nts.port == "4460"
    assert goose.destination == "未说明"
    assert len(iec104) == 1
    assert iec104[0].source == "北向设备"
    assert iec104[0].destination == "EMU300A"
    assert iec104[0].direction == "inbound"
    assert draft.functions[0].is_security_function is True
    assert "FACT-009" not in draft.functions[0].description
    assert draft.component_inventory.entries[0].component_type == "embedded_subsystem"


def test_communication_contract_separates_connection_business_direction_and_activation():
    block_id = "BLK-8888888888888888"
    facts = NodeFactBundle(
        batches=(
            FieldExtractionResult(
                node_id=EvidenceTargetNode.CONTEXT,
                field_id=RetrievalField.COMMUNICATIONS,
                facts=[
                    RetrievedFact(
                        fact_id="FACT-001",
                        statement=(
                            "源设备为Controller X100，目的设备为管理终端，"
                            "协议为SecureProto，目的端口为7443，默认关闭。"
                        ),
                        block_ids=[block_id],
                    )
                ],
            ),
        ),
        traces=(),
        retrieved_block_ids=frozenset({block_id}),
    )
    context_payload = _context().model_dump(mode="json")
    context_payload["product_name"] = "Controller X100"
    context_payload["communication_matrix"] = {
        "entries": [
            {
                "flow_id": "FLOW-001",
                "source": "Controller X100",
                "destination": "管理终端",
                "direction": "outbound",
                "direction_basis": "business_data_flow",
                "business_data_direction": "from_product",
                "activation_status": "enabled",
                "interface": "Ethernet",
                "protocol": "SecureProto",
                "port": "7443",
                "data_exchanged": ["固件包"],
                "encryption": "TLS",
                "authentication": "双向认证",
                "security_notes": ["通信可抵抗中间人攻击"],
                "evidence": [
                    _evidence(block_id, "SecureProto 7443 默认关闭").model_dump(
                        mode="json"
                    )
                ],
            }
        ]
    }
    scope = ScopeStatement(
        product_name="Controller X100",
        classification=ProductClassification(has_rdps=None),
        scope_description="Controller X100范围草稿。",
    )
    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(context_payload),
        scope,
        facts,
    )
    flow = draft.communication_matrix.entries[0]
    assert flow.direction == "outbound"
    assert flow.direction_basis == "documented_endpoints"
    assert flow.business_data_direction == "unknown"
    assert flow.activation_status == "disabled_by_default"
    assert flow.conditions
    assert flow.data_exchanged == []
    assert flow.encryption is None
    assert flow.authentication is None
    assert flow.interface is None
    assert flow.security_notes == []


def test_communication_repair_restores_explicit_endpoints_authentication_and_encryption():
    block_id = "BLK-8888888888888889"
    facts = NodeFactBundle(
        batches=(
            FieldExtractionResult(
                node_id=EvidenceTargetNode.CONTEXT,
                field_id=RetrievalField.COMMUNICATIONS,
                facts=[
                    RetrievedFact(
                        fact_id="FACT-001",
                        statement=(
                            "维护终端作为源设备，向Controller X100目的设备的8443端口发起"
                            "HTTPS连接，认证方式为用户名/密码，加密方式为TLS，该服务为默认访问方式。"
                        ),
                        block_ids=[block_id],
                    )
                ],
            ),
        ),
        traces=(),
        retrieved_block_ids=frozenset({block_id}),
    )
    payload = _context().model_dump(mode="json")
    payload["product_name"] = "Controller X100"
    payload["communication_matrix"] = {
        "entries": [
            {
                "flow_id": "FLOW-001",
                "source": "维护终端",
                "destination": "Controller X100",
                "protocol": "HTTPS",
                "port": "8443",
                "evidence": [
                    _evidence(block_id, "维护终端到Controller X100的HTTPS连接").model_dump(
                        mode="json"
                    )
                ],
            }
        ]
    }
    scope = ScopeStatement(
        product_name="Controller X100",
        classification=ProductClassification(has_rdps=None),
        scope_description="Controller X100范围草稿。",
    )

    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(payload),
        scope,
        facts,
    )
    flow = draft.communication_matrix.entries[0]
    assert flow.source == "维护终端"
    assert flow.destination == "Controller X100"
    assert flow.port == "8443"
    assert flow.direction == "inbound"
    assert flow.direction_basis == "documented_endpoints"
    assert flow.authentication == "用户名/密码"
    assert flow.encryption == "TLS"


def test_structured_communication_fact_survives_nonstandard_statement_wording():
    block_id = "BLK-8888888888888890"
    facts = NodeFactBundle(
        batches=(
            FieldExtractionResult(
                node_id=EvidenceTargetNode.CONTEXT,
                field_id=RetrievalField.COMMUNICATIONS,
                facts=[
                    RetrievedFact(
                        fact_id="FACT-001",
                        statement="通信表第四行给出该管理连接的完整参数。",
                        block_ids=[block_id],
                        attributes={
                            "source": "维护终端",
                            "destination": "Controller X100",
                            "protocol": "HTTPS",
                            "port": "8443",
                            "interface": "Ethernet",
                            "direction_basis": "documented_endpoints",
                            "business_data_direction": "to_product",
                            "activation_status": "disabled_by_default",
                            "authentication": "用户名/密码",
                            "encryption": "TLS",
                            "data_exchanged": ["管理配置"],
                            "conditions": ["管理员启用后可用"],
                        },
                    )
                ],
            ),
        ),
        traces=(),
        retrieved_block_ids=frozenset({block_id}),
    )
    payload = _context().model_dump(mode="json")
    payload["product_name"] = "Controller X100"
    payload["communication_matrix"] = {
        "entries": [
            {
                "flow_id": "FLOW-001",
                "source": "未知终端",
                "destination": "未知设备",
                "protocol": "HTTPS",
                "port": "8443",
                "authentication": "证书",
                "encryption": "未知",
                "evidence": [
                    _evidence(block_id, "通信表第四行").model_dump(mode="json")
                ],
            }
        ]
    }
    scope = ScopeStatement(
        product_name="Controller X100",
        classification=ProductClassification(has_rdps=None),
        scope_description="Controller X100范围草稿。",
    )

    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(payload), scope, facts
    )
    flow = draft.communication_matrix.entries[0]
    assert flow.source == "维护终端"
    assert flow.destination == "Controller X100"
    assert flow.direction == "inbound"
    assert flow.direction_basis == "documented_endpoints"
    assert flow.business_data_direction == "to_product"
    assert flow.activation_status == "disabled_by_default"
    assert flow.interface == "Ethernet"
    assert flow.authentication == "用户名/密码"
    assert flow.encryption == "TLS"
    assert flow.data_exchanged == ["管理配置"]
    assert flow.conditions == ["管理员启用后可用"]

    node2_context = _asset_candidate_context("systems_services", draft)
    carried_flow = node2_context["communication_endpoints"][0]
    assert carried_flow["source"] == "维护终端"
    assert carried_flow["destination"] == "Controller X100"
    assert carried_flow["authentication"] == "用户名/密码"
    assert carried_flow["encryption"] == "TLS"
    assert carried_flow["activation_status"] == "disabled_by_default"


def test_listener_exposure_does_not_become_business_or_connection_direction():
    block_id = "BLK-9999999999999999"
    facts = NodeFactBundle(
        batches=(
            FieldExtractionResult(
                node_id=EvidenceTargetNode.CONTEXT,
                field_id=RetrievalField.COMMUNICATIONS,
                facts=[
                    RetrievedFact(
                        fact_id="FACT-001",
                        statement="产品监听服务端口，协议为ProtoX；端点和业务数据方向未说明。",
                        block_ids=[block_id],
                    )
                ],
            ),
        ),
        traces=(),
        retrieved_block_ids=frozenset({block_id}),
    )
    payload = _context().model_dump(mode="json")
    payload["communication_matrix"] = {
        "entries": [
            {
                "flow_id": "FLOW-001",
                "source": "产品",
                "destination": "维护终端",
                "direction": "inbound",
                "business_data_direction": "to_product",
                "protocol": "ProtoX",
                "evidence": [
                    _evidence(block_id, "产品监听服务端口，协议为ProtoX").model_dump(
                        mode="json"
                    )
                ],
            }
        ]
    }
    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(payload),
        _scope(),
        facts,
    )
    flow = draft.communication_matrix.entries[0]
    assert flow.direction is None
    assert flow.direction_basis == "listener_exposure"
    assert flow.business_data_direction == "unknown"
    assert flow.destination == "未说明"


def test_component_scope_conflict_and_supplier_responsibility_stay_unknown():
    payload = _context().model_dump(mode="json")
    payload["component_inventory"] = {
        "entries": [
            {
                "component_id": "COMP-001",
                "name": "控制器X100",
                "component_type": "hardware",
                "scope_status": "confirmed",
                "role": "执行控制功能。",
                "is_third_party": False,
                "evidence": [],
            }
        ]
    }
    scope = ScopeStatement(
        product_name="产品A",
        classification=ProductClassification(has_rdps=None),
        scope_description="产品A范围草稿。",
        in_scope_components=["控制器X100：标准内置"],
        conditional_scope_components=["控制器X100：交付配置待确认"],
    )
    draft = _mark_product_context_as_draft(ProductContext.model_validate(payload), scope)
    component = draft.component_inventory.entries[0]
    assert component.scope_status == "unknown"
    assert component.is_third_party is None
    assert any("多个范围状态" in item for item in component.conditions)


def test_component_direct_delivery_evidence_prevents_false_unknown_downgrade():
    block_id = "BLK-9999999999999998"
    payload = _context().model_dump(mode="json")
    payload["component_inventory"] = {
        "entries": [
            {
                "component_id": "COMP-001",
                "name": "开关电源",
                "component_type": "hardware",
                "scope_status": "unknown",
                "conditions": ["Node0未确认该组件属于实际交付范围，需结合BOM/合同核实。"],
                "role": "提供电源。",
                "evidence": [
                    _evidence(
                        block_id,
                        "内含数据处理器、开关电源、防护模块、数字模块（可选）。",
                    ).model_dump(mode="json")
                ],
            }
        ]
    }

    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(payload),
        _scope(),
    )
    component = draft.component_inventory.entries[0]
    assert component.scope_status == "confirmed"
    assert component.conditions == []


def test_structured_component_fact_controls_delivery_status_without_keyword_parsing():
    block_id = "BLK-9999999999999997"
    facts = NodeFactBundle(
        batches=(
            FieldExtractionResult(
                node_id=EvidenceTargetNode.CONTEXT,
                field_id=RetrievalField.COMPONENTS,
                facts=[
                    RetrievedFact(
                        fact_id="FACT-001",
                        statement="组件表第三行记录Power Module A。",
                        block_ids=[block_id],
                        attributes={
                            "component_name": "Power Module A",
                            "component_type": "hardware",
                            "scope_status": "conditional",
                            "conditions": ["取决于订购BOM"],
                        },
                    )
                ],
            ),
        ),
        traces=(),
        retrieved_block_ids=frozenset({block_id}),
    )
    payload = _context().model_dump(mode="json")
    payload["component_inventory"] = {
        "entries": [
            {
                "component_id": "COMP-001",
                "name": "Power Module A",
                "component_type": "firmware",
                "scope_status": "confirmed",
                "role": "提供电源。",
                "evidence": [
                    _evidence(block_id, "组件表第三行").model_dump(mode="json")
                ],
            }
        ]
    }

    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(payload), _scope(), facts
    )
    component = draft.component_inventory.entries[0]
    assert component.component_type == "hardware"
    assert component.scope_status == "conditional"
    assert component.conditions == ["取决于订购BOM"]

    node2_context = _asset_candidate_context("systems_services", draft)
    carried_component = node2_context["components"][0]
    assert carried_component["component_type"] == "hardware"
    assert carried_component["scope_status"] == "conditional"
    assert carried_component["conditions"] == ["取决于订购BOM"]


def test_fact_attributes_are_rejected_outside_their_reviewed_field():
    with pytest.raises(ValueError, match="attributes are not allowed"):
        FieldExtractionResult(
            node_id=EvidenceTargetNode.ASSETS,
            field_id=RetrievalField.DATA_ASSETS,
            facts=[
                RetrievedFact(
                    fact_id="FACT-001",
                    statement="设备处理运行数据。",
                    block_ids=["BLK-9999999999999996"],
                    attributes={"source": "终端"},
                )
            ],
        )


def test_empty_optional_fact_attributes_are_canonicalized_as_missing():
    result = FieldExtractionResult(
        node_id=EvidenceTargetNode.CONTEXT,
        field_id=RetrievalField.COMPONENTS,
        facts=[
            RetrievedFact(
                fact_id="FACT-001",
                statement="组件表列出控制模块。",
                block_ids=["BLK-9999999999999995"],
                attributes={
                    "component_name": "控制模块",
                    "component_type": "hardware",
                    "scope_status": "unknown",
                    "conditions": [],
                },
            )
        ],
    )

    assert result.facts[0].attributes == {
        "component_name": "控制模块",
        "component_type": "hardware",
        "scope_status": "unknown",
    }

    with pytest.raises(ValueError, match="items must be non-empty"):
        FieldExtractionResult(
            node_id=EvidenceTargetNode.CONTEXT,
            field_id=RetrievalField.COMPONENTS,
            facts=[
                RetrievedFact(
                    fact_id="FACT-001",
                    statement="组件表列出控制模块。",
                    block_ids=["BLK-9999999999999995"],
                    attributes={"conditions": [""]},
                )
            ],
        )


def test_excel_exposes_separate_communication_semantics():
    payload = _context().model_dump(mode="json")
    payload["communication_matrix"] = {
        "entries": [
            {
                "flow_id": "FLOW-001",
                "source": "产品",
                "destination": "外部服务",
                "direction": "outbound",
                "direction_basis": "connection_initiation",
                "business_data_direction": "bidirectional",
                "activation_status": "conditional",
                "conditions": ["部署时配置"],
            }
        ]
    }
    workbook = _build_progress_workbook(
        {
            "scope": _scope(),
            "product_context": ProductContext.model_validate(payload),
            "status": "node_1_completed",
            "errors": [],
        },
        "contract-test",
        "build_product_context",
        "2026-09-17T00:00:00+00:00",
    )
    sheet = workbook["Node1 通信矩阵"]
    headers = [cell.value for cell in sheet[4]]
    assert headers[3:8] == [
        "连接方向",
        "方向依据",
        "业务数据方向",
        "启用状态",
        "适用条件",
    ]
    assert sheet.cell(row=5, column=4).value == "出站连接"
    assert sheet.cell(row=5, column=5).value == "连接发起关系"
    assert sheet.cell(row=5, column=6).value == "双向"
    assert sheet.cell(row=5, column=7).value == "条件项"


def test_direct_context_path_uses_evidence_quotes_for_communication_constraints():
    block_id = "BLK-AAAAAAAAAAAAAAAB"
    payload = _context().model_dump(mode="json")
    payload["communication_matrix"] = {
        "entries": [
            {
                "flow_id": "FLOW-001",
                "source": "产品",
                "destination": "外部服务",
                "protocol": "ProtoY",
                "encryption": "强加密",
                "authentication": "双向认证",
                "evidence": [
                    _evidence(
                        block_id,
                        "源设备为产品，目的设备为外部服务，协议为ProtoY。",
                    ).model_dump(mode="json")
                ],
            }
        ]
    }
    draft = _mark_product_context_as_draft(
        ProductContext.model_validate(payload),
        _scope(),
    )
    flow = draft.communication_matrix.entries[0]
    assert flow.direction_basis == "documented_endpoints"
    assert flow.encryption is None
    assert flow.authentication is None


def test_node0_review_diagnostics_are_not_sent_to_node1():
    payload = _scope_downstream_payload(_scope())
    assert "review_notes" not in payload
    assert payload["assumptions"] == ["实际交付 BOM 是什么？"]


def test_risk_acceptance_criteria_are_deterministic_and_non_blocking():
    criteria = build_risk_acceptance_criteria(_scope(), _context())
    assert criteria.policy_version == "policy-v1.0"
    assert criteria.aggregate_risk_considered is True
    assert criteria.evidence == []
    assert any("候选依赖" in factor for factor in criteria.product_factors)
    assert any("运维人员" in factor for factor in criteria.user_factors)
