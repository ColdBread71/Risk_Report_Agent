from types import SimpleNamespace

from openpyxl import Workbook
from pydantic import ValidationError
import pytest

from core.exporter import _write_assets
from core.workflow_status import (
    ASSET_IDENTIFICATION_COMPLETED,
    ASSET_IDENTIFICATION_FAILED,
    ASSET_IDENTIFICATION_PARTIAL_DRAFT,
    ASSET_IDENTIFICATION_TECHNICAL_INCOMPLETE,
    resolve_asset_identification_status,
)
from nodes import asset_threat_modeler, field_extractor
from nodes.field_extractor import NodeFactBundle
from nodes.asset_threat_modeler import (
    _apply_asset_function_mapping,
    _assemble_asset_sections,
    _asset_function_mapping_cache_inputs,
    _asset_section_cache_inputs,
    _asset_section_material,
    _function_coverage_notes,
    _load_asset_function_mapping_checkpoint,
    _load_asset_section_checkpoint,
    _normalize_asset_section_payload,
    _normalize_asset_function_links,
    _repair_asset_business_rules,
    _save_asset_function_mapping_checkpoint,
    _save_asset_section_checkpoint,
    _stable_sha256,
)
from schemas.common import AssessmentVerdict
from schemas.evidence_packet import EvidenceTargetNode
from schemas.product import (
    Asset,
    AssetFunctionMappingEntry,
    AssetFunctionMappingResult,
    AssetFunctionRelationship,
    AssetIdentificationResult,
    AssetSectionResult,
    ProductFunction,
)
from schemas.retrieval import (
    FieldExtractionResult,
    RetrievalField,
    RetrievalProfile,
    RetrievedFact,
)
from tools.retrieval_profiles import (
    get_retrieval_profile,
    get_targeted_anchor_groups,
)


def _asset_payload(**overrides):
    payload = {
        "asset_id": "ASSET-001",
        "name": "MPLC模块",
        "asset_type": "hardware",
        "status": "conditional",
        "related_function_ids": ["FUNC-001"],
        "description": "是否交付取决于合同或BOM。",
        "related_objectives": [
            {
                "objective_id": "OBJ-001",
                "description": "仅允许经授权的配置变更。",
                "category": "integrity",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _evidence_payload(quote="设备支持该对象。", block_id=None):
    payload = {
        "evidence_id": "EVD-001",
        "source": {
            "file_name": "manual.pdf",
            "file_path": "Project/manual.pdf",
            "file_type": "pdf",
        },
        "quote": quote,
        "evidence_level": "direct",
        "confidence": "high",
    }
    if block_id:
        payload["source"]["block_id"] = block_id
    return payload


def test_node2_profiles_are_bounded_and_field_specific():
    expected = {
        RetrievalField.DATA_ASSETS: (40, 24, "不把数据采集"),
        RetrievalField.CREDENTIALS_AND_KEYS: (48, 24, "证书不得与私钥"),
        RetrievalField.SOFTWARE_AND_CONFIGURATION: (44, 24, "软件对象、配置数据"),
        RetrievalField.HARDWARE_AND_NETWORK: (48, 24, "仅有配置或加固教程不能证明"),
        RetrievalField.EXTERNAL_SERVICES: (40, 20, "不得自行判定RDPS"),
        RetrievalField.FUNCTION_ASSETS: (48, 24, "独立业务价值或安全价值"),
        RetrievalField.USER_PROPERTY_ENVIRONMENT: (40, 20, "环境、动物、公共利益"),
    }
    for field_id, (max_blocks, max_facts, guidance_text) in expected.items():
        profile = get_retrieval_profile(EvidenceTargetNode.ASSETS, field_id)
        assert profile.max_blocks == max_blocks
        assert profile.max_facts == max_facts
        assert guidance_text in profile.extraction_guidance
        assert get_targeted_anchor_groups(EvidenceTargetNode.ASSETS, field_id)


def test_asset_contract_requires_reviewed_type_and_status():
    asset = Asset.model_validate(_asset_payload())
    assert asset.asset_type == "hardware"
    assert asset.status == "conditional"

    with pytest.raises(ValidationError):
        Asset.model_validate(_asset_payload(asset_type="security_asset"))
    with pytest.raises(ValidationError):
        Asset.model_validate(_asset_payload(status="enabled"))
    with pytest.raises(ValidationError):
        payload = _asset_payload()
        payload.pop("status")
        Asset.model_validate(payload)
    with pytest.raises(ValidationError):
        Asset.model_validate(
            _asset_payload(
                related_objectives=[
                    {
                        "objective_id": "OBJ-001",
                        "description": "使用未定义的目标类别。",
                        "category": "resilience",
                    }
                ]
            )
        )


def test_asset_section_payload_rejects_ambiguous_items_without_dropping_valid_peers():
    payload = {
        "assets": [
            _asset_payload(
                name="外部受影响系统",
                asset_type="external_affected",
                status="confirmed",
            ),
            _asset_payload(
                asset_id="ASSET-002",
                name="业务系统",
                asset_type="system",
                status="confirmed",
                related_objectives=[
                    {
                        "objective_id": "OBJ-002",
                        "description": "避免安全影响。",
                        "category": "safety",
                    }
                ],
            ),
            _asset_payload(
                asset_id="ASSET-003",
                name="设备管理功能",
                asset_type="function",
                status="confirmed",
                related_objectives=[
                    {
                        "objective_id": "OBJ-003",
                        "description": "保持管理操作完整。",
                        "category": "integrity",
                    }
                ],
            ),
        ],
        "assessment": "PASS",
    }

    normalized = _normalize_asset_section_payload(
        payload,
        section_name="functions_impacts",
    )
    result = AssetSectionResult.model_validate(normalized)

    assert [asset.asset_id for asset in result.assets] == ["ASSET-003"]
    assert result.assets[0].asset_type == "function"
    assert result.assessment == AssessmentVerdict.PARTIAL
    assert len(result.rejected_items) == 2
    assert all("asset_type" in reason for reason in result.rejected_items)
    assert "逐项校验隔离了2条" in result.notes


def test_asset_section_payload_isolates_invalid_children_and_keeps_asset():
    payload = {
        "assets": [
            _asset_payload(
                asset_type=" Hardware ",
                status=" Conditional ",
                related_objectives=[
                    {
                        "objective_id": "OBJ-001",
                        "description": "保持模块配置完整。",
                        "category": " Integrity ",
                    },
                    {
                        "objective_id": "OBJ-002",
                        "description": "无效目标。",
                        "category": "safety",
                    },
                ],
                function_relationships=[
                    {
                        "function_id": "FUNC-001",
                        "relationship_type": " Depends On ",
                        "rationale": "该功能直接依赖此模块。",
                    },
                    {
                        "function_id": "FUNC-001",
                        "relationship_type": "hosts",
                        "rationale": "非法关系。",
                    },
                ],
            )
        ],
        "assessment": "PASS",
        "rejected_items": ["模型不得写入此字段"],
    }

    result = AssetSectionResult.model_validate(
        _normalize_asset_section_payload(payload, section_name="systems_services")
    )

    assert len(result.assets) == 1
    assert result.assets[0].asset_type == "hardware"
    assert result.assets[0].status == "conditional"
    assert [item.objective_id for item in result.assets[0].related_objectives] == [
        "OBJ-001"
    ]
    assert len(result.assets[0].function_relationships) == 1
    assert result.assessment == AssessmentVerdict.PARTIAL
    assert len(result.rejected_items) == 2
    assert all("模型不得写入" not in reason for reason in result.rejected_items)


def test_asset_excel_exposes_localized_status_column():
    workbook = Workbook()
    workbook.remove(workbook.active)
    product_context = SimpleNamespace(
        functions=[SimpleNamespace(function_id="FUNC-001", name="南向设备接入")]
    )
    _write_assets(
        workbook,
        {
            "assets": [
                Asset.model_validate(
                    _asset_payload(
                        function_relationships=[
                            {
                                "function_id": "FUNC-001",
                                "relationship_type": "depends_on",
                                "rationale": "该功能直接依赖此模块。",
                            }
                        ],
                        related_objectives=[
                            {
                                "objective_id": "OBJ-001",
                                "description": "仅允许经授权的配置变更。",
                                "category": "integrity",
                            },
                            {
                                "objective_id": "OBJ-002",
                                "description": "确保该模块在需要时可用。",
                                "category": "availability",
                            },
                        ]
                    )
                )
            ],
            "product_context": product_context,
        },
    )
    sheet = workbook["Node2 资产与目标"]

    assert [sheet.cell(4, column).value for column in range(1, 17)] == [
        "资产编号",
        "资产名称",
        "资产类型",
        "资产状态",
        "关联功能编号",
        "关联功能名称",
        "功能关系与依据",
        "所在位置",
        "资产价值或受损后果",
        "资产说明",
        "目标编号",
        "目标类别",
        "目标依据类型",
        "目标支持状态",
        "网络安全目标",
        "目标法律与标准依据",
    ]
    assert sheet["C5"].value == "硬件"
    assert sheet["D5"].value == "条件项"
    assert sheet["E5"].value == "- FUNC-001"
    assert sheet["F5"].value == "- 南向设备接入"
    assert sheet["G5"].value == "- FUNC-001｜直接依赖｜该功能直接依赖此模块。"
    assert sheet.auto_filter.ref == "A4:P6"
    assert sheet["D5"].fill.fgColor.rgb.endswith("FFF2CC")
    merged_ranges = {str(cell_range) for cell_range in sheet.merged_cells.ranges}
    assert {f"{column}5:{column}6" for column in "ABCDEFGHIJ"} <= merged_ranges
    assert not any(cell_range.startswith(("K", "L", "M", "N", "O", "P")) for cell_range in merged_ranges)
    assert sheet["K5"].value == "OBJ-001"
    assert sheet["K6"].value == "OBJ-002"
    assert sheet["M5"].value == "待确认"
    assert sheet["N5"].value == "待工程师确认"


def test_asset_business_rules_downgrade_unsupported_claims_without_retry():
    asset = Asset.model_validate(
        _asset_payload(
            status="confirmed",
            location="eMMC持久化存储",
            related_objectives=[
                {
                    "objective_id": "OBJ-001",
                    "description": "通过TLS和加密存储保护该对象。",
                    "category": "confidentiality",
                }
            ],
        )
    )

    repaired, actions = _repair_asset_business_rules(asset)

    assert repaired.status == "needs_confirmation"
    assert repaired.location is None
    assert repaired.value is None
    assert "现有材料未提供可直接引用" in repaired.description
    assert repaired.related_objectives[0].description == "确保MPLC模块仅可被获授权主体访问或使用。"
    assert "无直接证据候选已降为待工程师确认" in actions
    assert "无直接证据候选的推测内容已清空" in actions
    assert "目标描述已规范为不声明控制实现的保护结果" in actions
    assert "无直接证据候选的位置已清空" in actions


def test_asset_business_rules_distinguish_certificate_status_and_external_impact():
    certificate = Asset.model_validate(
        _asset_payload(
            name="公开设备数字证书",
            asset_type="credential",
            status="confirmed",
            description="用于证明设备身份的公开证书。",
            evidence=[_evidence_payload("设备支持公开数字证书管理。")],
            related_objectives=[
                {
                    "objective_id": "OBJ-001",
                    "description": "保持证书内容秘密。",
                    "category": "confidentiality",
                }
            ],
        )
    )
    conditional = Asset.model_validate(
        _asset_payload(
            status="confirmed",
            evidence=[_evidence_payload("MPLC模块为选配件。")],
        )
    )
    operator = Asset.model_validate(
        _asset_payload(
            name="运维人员",
            asset_type="user",
            status="confirmed",
            description="可能受到产品网络安全事件影响的人员。",
            evidence=[_evidence_payload("运维人员通过Web界面管理设备。")],
        )
    )

    repaired_certificate, _ = _repair_asset_business_rules(certificate)
    repaired_conditional, _ = _repair_asset_business_rules(conditional)
    repaired_operator, _ = _repair_asset_business_rules(operator)

    assert repaired_certificate.related_objectives[0].category == "authenticity"
    assert repaired_conditional.status == "confirmed"
    assert repaired_operator.status == "external_affected"


def test_objective_evidence_cannot_backfill_missing_parent_asset_evidence():
    objective_evidence = _evidence_payload("材料只在目标中被引用。")
    asset = Asset.model_validate(
        _asset_payload(
            name="候选配置对象",
            asset_type="data",
            status="confirmed",
            evidence=[],
            related_objectives=[
                {
                    "objective_id": "OBJ-001",
                    "description": "保持候选配置对象完整。",
                    "category": "integrity",
                    "basis": "explicit_requirement",
                    "status": "supported",
                    "evidence": [objective_evidence],
                }
            ],
        )
    )

    repaired, actions = _repair_asset_business_rules(asset)

    assert repaired.status == "needs_confirmation"
    assert repaired.related_objectives[0].basis == "unknown"
    assert repaired.related_objectives[0].status == "needs_confirmation"
    assert repaired.related_objectives[0].evidence == []
    assert "无直接证据候选已降为待工程师确认" in actions
    assert "未同时支持父资产的目标证据已移除" in actions


def test_supported_objective_keeps_basis_but_never_claims_control_implementation():
    block_id = "BLK-CCCCCCCCCCCCCCCC"
    evidence = _evidence_payload(
        "配置错误会影响产品预期运行。",
        block_id=block_id,
    )
    asset = Asset.model_validate(
        _asset_payload(
            name="运行配置",
            asset_type="data",
            status="confirmed",
            value="配置错误会影响产品预期运行。",
            evidence=[evidence],
            related_objectives=[
                {
                    "objective_id": "OBJ-001",
                    "description": "必须部署特定防护机制并阻止所有未授权变更。",
                    "category": "integrity",
                    "basis": "asset_value_or_consequence",
                    "status": "supported",
                    "evidence": [evidence],
                }
            ],
        )
    )

    repaired, actions = _repair_asset_business_rules(asset)
    objective = repaired.related_objectives[0]

    assert objective.description == "确保运行配置不被未经授权地修改。"
    assert objective.basis == "asset_value_or_consequence"
    assert objective.status == "supported"
    assert len(objective.evidence) == 1
    assert "目标描述已规范为不声明控制实现的保护结果" in actions


def test_untraceable_legal_basis_is_removed_and_objective_is_downgraded():
    evidence = _evidence_payload("产品处理运行配置。", block_id="BLK-DDDDDDDDDDDDDDDD")
    asset = Asset.model_validate(
        _asset_payload(
            name="运行配置",
            asset_type="data",
            status="confirmed",
            evidence=[evidence],
            related_objectives=[
                {
                    "objective_id": "OBJ-001",
                    "description": "确保运行配置完整。",
                    "category": "integrity",
                    "basis": "legal_or_standard",
                    "status": "supported",
                    "legal_basis": [
                        {
                            "regulation": "Example Standard",
                            "clause": "5.2",
                        }
                    ],
                    "evidence": [evidence],
                }
            ],
        )
    )

    repaired, actions = _repair_asset_business_rules(asset)
    objective = repaired.related_objectives[0]

    assert objective.legal_basis == []
    assert objective.basis == "unknown"
    assert objective.status == "needs_confirmation"
    assert "缺少可追溯条款证据的法律或标准依据已移除" in actions


def test_traceable_legal_basis_can_support_objective_need_without_proving_control():
    evidence = _evidence_payload(
        "Example Standard clause 5.2 requires protection of configuration integrity.",
        block_id="BLK-EEEEEEEEEEEEEEEE",
    )
    asset = Asset.model_validate(
        _asset_payload(
            name="运行配置",
            asset_type="data",
            status="confirmed",
            evidence=[evidence],
            related_objectives=[
                {
                    "objective_id": "OBJ-001",
                    "description": "Example Standard已经通过某控制完全实现。",
                    "category": "integrity",
                    "basis": "legal_or_standard",
                    "status": "supported",
                    "legal_basis": [
                        {
                            "regulation": "Example Standard",
                            "clause": "5.2",
                        }
                    ],
                    "evidence": [evidence],
                }
            ],
        )
    )

    repaired, _actions = _repair_asset_business_rules(asset)
    objective = repaired.related_objectives[0]

    assert objective.description == "确保运行配置不被未经授权地修改。"
    assert objective.basis == "legal_or_standard"
    assert objective.status == "supported"
    assert len(objective.legal_basis) == 1


def test_unresolved_objective_basis_keeps_asset_inventory_partial():
    asset = Asset.model_validate(
        _asset_payload(
            name="运行数据",
            asset_type="data",
            status="confirmed",
            related_function_ids=[],
            evidence=[_evidence_payload("产品处理运行数据。")],
        )
    )

    result = _assemble_asset_sections(
        [
            (
                "data_credentials_software",
                AssetSectionResult(assets=[asset], assessment="PASS"),
            ),
            (
                "systems_services",
                AssetSectionResult(
                    assets=[],
                    assessment="PASS",
                    notes="材料未证明系统或服务资产。",
                ),
            ),
            (
                "functions_impacts",
                AssetSectionResult(
                    assets=[],
                    assessment="PASS",
                    notes="材料未证明功能或受影响对象。",
                ),
            ),
        ],
        section_failures=[],
        field_failures=(),
        product_functions=[],
        defer_function_coverage=True,
    )

    assert result.assessment == AssessmentVerdict.PARTIAL
    assert "网络安全目标依据待工程师确认" in (result.notes or "")


def test_passive_support_part_is_not_kept_as_independent_asset():
    passive = Asset.model_validate(
        _asset_payload(
            name="光纤终端盒",
            asset_type="hardware",
            status="confirmed",
            description="用于光纤线路接续和固定。",
            evidence=[_evidence_payload("光纤终端盒用于光纤线路接续和固定。")],
        )
    )
    managed = Asset.model_validate(
        _asset_payload(
            name="带远程管理功能的电源模块",
            asset_type="hardware",
            status="confirmed",
            description="支持远程管理功能。",
            evidence=[_evidence_payload("电源模块支持远程管理功能。")],
        )
    )

    assert asset_threat_modeler._is_passive_support_asset(passive)
    assert not asset_threat_modeler._is_passive_support_asset(managed)


def test_unsupported_attack_chain_is_removed_from_asset_value():
    asset = Asset.model_validate(
        _asset_payload(
            status="confirmed",
            value="攻击者可利用该对象进行横向移动。",
            evidence=[_evidence_payload("该模块用于采集现场设备数据。")],
        )
    )

    repaired, actions = _repair_asset_business_rules(asset)

    assert repaired.value is None
    assert "缺少原文支持的具体攻击或灾害链已清空" in actions


def test_overbroad_non_function_mapping_is_cleared_for_review():
    asset = Asset.model_validate(
        _asset_payload(
            name="通用通信接口组",
            asset_type="network",
            status="confirmed",
            evidence=[_evidence_payload("设备提供一组通信接口。")],
        )
    )
    result = AssetIdentificationResult(
        assets=[asset], assessment=AssessmentVerdict.PASS
    )
    functions = [
        SimpleNamespace(function_id=f"FUNC-{index:03d}", name=f"功能{index}")
        for index in range(1, 10)
    ]
    mapping = AssetFunctionMappingResult(
        mappings=[
            AssetFunctionMappingEntry(
                asset_id="ASSET-001",
                related_function_ids=[function.function_id for function in functions],
            )
        ]
    )

    corrected = _apply_asset_function_mapping(result, mapping, functions)

    assert corrected.assets[0].related_function_ids == []
    assert corrected.assessment == AssessmentVerdict.PARTIAL
    assert "过宽映射1项" in (corrected.notes or "")


def test_typed_function_relationship_is_preserved_and_indexes_function_id():
    asset = Asset.model_validate(
        _asset_payload(
            name="运行配置数据",
            asset_type="data",
            status="confirmed",
            related_function_ids=[],
            evidence=[_evidence_payload("设备允许修改运行配置数据。")],
        )
    )
    result = AssetIdentificationResult(
        assets=[asset], assessment=AssessmentVerdict.PASS
    )
    mapping = AssetFunctionMappingResult(
        mappings=[
            AssetFunctionMappingEntry(
                asset_id="ASSET-001",
                relationships=[
                    AssetFunctionRelationship(
                        function_id="FUNC-001",
                        relationship_type="modifies",
                        rationale="该功能直接修改运行配置数据。",
                    )
                ],
            )
        ]
    )

    corrected = _apply_asset_function_mapping(
        result,
        mapping,
        [SimpleNamespace(function_id="FUNC-001", name="配置管理")],
    )

    assert corrected.assets[0].related_function_ids == ["FUNC-001"]
    assert corrected.assets[0].function_relationships[0].relationship_type == "modifies"
    assert "缺少关系类型" not in (corrected.notes or "")


def test_incompatible_typed_relationship_is_removed_without_inventing_replacement():
    asset = Asset.model_validate(
        _asset_payload(
            name="身份验证功能",
            asset_type="function",
            status="confirmed",
            related_function_ids=[],
            evidence=[_evidence_payload("产品提供身份验证功能。")],
        )
    )
    result = AssetIdentificationResult(
        assets=[asset], assessment=AssessmentVerdict.PASS
    )
    mapping = AssetFunctionMappingResult(
        mappings=[
            AssetFunctionMappingEntry(
                asset_id="ASSET-001",
                relationships=[
                    AssetFunctionRelationship(
                        function_id="FUNC-001",
                        relationship_type="reads",
                        rationale="功能资产不应以读取关系代替实现关系。",
                    )
                ],
            )
        ]
    )

    corrected = _apply_asset_function_mapping(
        result,
        mapping,
        [SimpleNamespace(function_id="FUNC-001", name="身份验证")],
    )

    assert corrected.assets[0].related_function_ids == []
    assert corrected.assets[0].function_relationships == []
    assert "与资产对象类型不一致" in (corrected.notes or "")


def test_large_but_selective_non_function_mapping_is_preserved():
    asset = Asset.model_validate(
        _asset_payload(
            name="共享数据服务",
            asset_type="service",
            status="confirmed",
            evidence=[_evidence_payload("该服务供多个产品功能直接读写数据。")],
        )
    )
    result = AssetIdentificationResult(
        assets=[asset], assessment=AssessmentVerdict.PASS
    )
    functions = [
        SimpleNamespace(function_id=f"FUNC-{index:03d}", name=f"功能{index}")
        for index in range(1, 21)
    ]
    mapping = AssetFunctionMappingResult(
        mappings=[
            AssetFunctionMappingEntry(
                asset_id="ASSET-001",
                related_function_ids=[function.function_id for function in functions[:9]],
            )
        ]
    )

    corrected = _apply_asset_function_mapping(result, mapping, functions)

    assert corrected.assets[0].related_function_ids == [
        function.function_id for function in functions[:9]
    ]
    assert "过宽映射" not in (corrected.notes or "")


def test_asset_function_links_are_canonical_and_coverage_is_non_blocking():
    asset = Asset.model_validate(
        _asset_payload(
            related_function_ids=["FUNC-002", "FUNC-999", "FUNC-002"],
        )
    )
    normalized, actions = _normalize_asset_function_links(
        asset,
        function_order={"FUNC-001": 0, "FUNC-002": 1},
    )
    assert normalized.related_function_ids == ["FUNC-002"]
    assert "未知功能编号已移除" in actions
    assert "重复功能编号已合并" in actions

    function_asset = normalized.model_copy(
        update={"asset_type": "function", "related_function_ids": ["FUNC-001"]}
    )
    notes, incomplete = _function_coverage_notes(
        [normalized, function_asset],
        [
            SimpleNamespace(function_id="FUNC-001", name="登录功能"),
            SimpleNamespace(function_id="FUNC-002", name="更新功能"),
        ],
    )
    assert incomplete is True
    assert not any("尚未关联任何资产" in note for note in notes)
    assert any("FUNC-002 更新功能" in note for note in notes)


def test_function_section_can_reuse_validated_node1_function_evidence():
    block_id = "BLK-AAAAAAAAAAAAAAAA"
    function = ProductFunction(
        function_id="FUNC-001",
        name="登录功能",
        description="用户通过Web界面登录。",
        is_security_function=True,
        function_category="authentication",
        interfaces=["HTTPS"],
        limitations=[],
        evidence=[_evidence_payload("用户通过Web界面登录。", block_id=block_id)],
    )
    product_context = SimpleNamespace(
        product_name="EMU300A",
        functions=[function],
        communication_matrix=SimpleNamespace(entries=[]),
        iprfu=SimpleNamespace(model_dump=lambda **_kwargs: {}),
        user_description=SimpleNamespace(model_dump=lambda **_kwargs: {}),
        operational_environment=SimpleNamespace(
            integrated_systems=[],
            constraints=[],
        ),
    )
    scope = SimpleNamespace(
        product_name="EMU300A",
        product_version=None,
        scope_description="EMU300A",
        in_scope_components=[],
        conditional_scope_components=[],
        out_of_scope_components=[],
        assumptions=[],
        classification=SimpleNamespace(has_rdps=None),
    )
    facts = NodeFactBundle(batches=(), traces=(), retrieved_block_ids=frozenset())

    material, allowed = _asset_section_material(
        section_name="functions_impacts",
        scope=scope,
        product_context=product_context,
        facts=facts,
    )

    assert material["evidence_contract"]["node1_function_support"] == {
        "FUNC-001": [block_id]
    }
    assert block_id in allowed


def test_empty_asset_section_is_allowed_only_with_an_explanation():
    section = AssetSectionResult(assets=[], assessment="PARTIAL", notes="材料未提供该类资产。")
    assert section.assets == []
    with pytest.raises(ValidationError):
        AssetSectionResult(assets=[], assessment="PARTIAL")


def test_asset_section_cache_is_fingerprinted_and_round_trips(tmp_path):
    material = {"scope": {"product_name": "EMU300A"}, "field_batches": []}
    inputs = _asset_section_cache_inputs(
        section_name="data_credentials_software",
        source_packet_sha256="a" * 64,
        text_model="qwen-plus",
        material_payload=material,
    )
    changed = _asset_section_cache_inputs(
        section_name="data_credentials_software",
        source_packet_sha256="a" * 64,
        text_model="qwen-plus",
        material_payload={**material, "field_batches": [{"new": "fact"}]},
    )
    fingerprint = _stable_sha256(inputs)
    assert fingerprint != _stable_sha256(changed)

    path = tmp_path / "data_credentials_software.json"
    result = AssetSectionResult(
        assets=[Asset.model_validate(_asset_payload(asset_type="credential", status="confirmed"))],
        assessment="PARTIAL",
        notes="仍需工程师确认。",
    )
    _save_asset_section_checkpoint(
        path=path,
        cache_inputs=inputs,
        fingerprint=fingerprint,
        result=result,
    )
    assert _load_asset_section_checkpoint(path=path, fingerprint=fingerprint) == result
    assert _load_asset_section_checkpoint(path=path, fingerprint="different") is None


def test_asset_function_mapping_cache_is_fingerprinted_and_round_trips(tmp_path):
    material = {
        "functions": [{"function_id": "FUNC-001", "name": "登录"}],
        "assets": [{"asset_id": "ASSET-001", "name": "账户凭据"}],
    }
    inputs = _asset_function_mapping_cache_inputs(
        source_packet_sha256="a" * 64,
        text_model="qwen-plus",
        material_payload=material,
    )
    changed = _asset_function_mapping_cache_inputs(
        source_packet_sha256="a" * 64,
        text_model="qwen-plus",
        material_payload={**material, "assets": []},
    )
    fingerprint = _stable_sha256(inputs)
    assert fingerprint != _stable_sha256(changed)

    path = tmp_path / "function_mapping.json"
    mapping = AssetFunctionMappingResult(
        mappings=[
            AssetFunctionMappingEntry(
                asset_id="ASSET-001",
                related_function_ids=["FUNC-001"],
            )
        ]
    )
    _save_asset_function_mapping_checkpoint(
        path=path,
        cache_inputs=inputs,
        fingerprint=fingerprint,
        result=mapping,
    )
    assert _load_asset_function_mapping_checkpoint(
        path=path,
        fingerprint=fingerprint,
    ) == mapping
    assert _load_asset_function_mapping_checkpoint(
        path=path,
        fingerprint="different",
    ) is None


def test_focused_asset_function_mapping_replaces_wrong_section_guess_without_blocking():
    result = AssetIdentificationResult(
        assets=[
            Asset.model_validate(
                _asset_payload(
                    name="Syslog服务",
                    asset_type="service",
                    status="external_affected",
                    related_function_ids=["FUNC-001"],
                )
            ),
            Asset.model_validate(
                _asset_payload(
                    asset_id="ASSET-002",
                    name="待确认相邻对象",
                    asset_type="network",
                    status="needs_confirmation",
                    related_function_ids=["FUNC-999"],
                    related_objectives=[
                        {
                            "objective_id": "OBJ-002",
                            "description": "保持相邻对象可用。",
                            "category": "availability",
                        }
                    ],
                )
            ),
        ],
        assessment="PASS",
    )
    mapping = AssetFunctionMappingResult(
        mappings=[
            AssetFunctionMappingEntry(
                asset_id="ASSET-001",
                related_function_ids=["FUNC-002", "FUNC-999"],
            )
        ]
    )
    functions = [
        SimpleNamespace(function_id="FUNC-001", name="登录"),
        SimpleNamespace(function_id="FUNC-002", name="日志审计"),
    ]

    corrected = _apply_asset_function_mapping(result, mapping, functions)

    assert corrected.assets[0].related_function_ids == ["FUNC-002"]
    assert corrected.assets[1].related_function_ids == []
    assert corrected.assessment == AssessmentVerdict.PARTIAL
    assert "移除未知功能编号1项" in corrected.notes
    assert "保留未返回映射资产的临时关系1项" in corrected.notes
    assert "无可靠功能关系、留待人工确认的资产1项" in corrected.notes

    degraded = _apply_asset_function_mapping(result, None, functions)
    assert degraded.assets[0].related_function_ids == ["FUNC-001"]
    assert degraded.assets[1].related_function_ids == []
    assert degraded.assessment == AssessmentVerdict.PARTIAL
    assert "统一映射因技术错误未完成" in degraded.notes


def test_asset_sections_merge_deterministically_and_keep_partial_results():
    data_asset = Asset.model_validate(
        _asset_payload(
            asset_id="ASSET-009",
            name="本地账户凭据",
            asset_type="credential",
            status="confirmed",
        )
    )
    network_asset = Asset.model_validate(
        _asset_payload(
            asset_id="ASSET-001",
            name="北向网络",
            asset_type="network",
            status="external_affected",
            related_objectives=[
                {
                    "objective_id": "OBJ-001",
                    "description": "保持通信路径可用。",
                    "category": "availability",
                }
            ],
        )
    )
    sections = [
        (
            "data_credentials_software",
            AssetSectionResult(assets=[data_asset], assessment="PASS"),
        ),
        (
            "systems_services",
            AssetSectionResult(assets=[network_asset], assessment="PASS"),
        ),
    ]
    result = _assemble_asset_sections(
        sections,
        section_failures=["functions_impacts"],
        field_failures=((RetrievalField.USER_PROPERTY_ENVIRONMENT, "timeout"),),
        product_functions=[
            SimpleNamespace(function_id="FUNC-001", name="南向设备接入")
        ],
    )
    assert [asset.asset_id for asset in result.assets] == ["ASSET-001", "ASSET-002"]
    assert [
        objective.objective_id
        for asset in result.assets
        for objective in asset.related_objectives
    ] == ["OBJ-001", "OBJ-002"]
    assert result.assessment == AssessmentVerdict.PARTIAL
    assert "functions_impacts分段因技术错误未完成" in result.notes
    assert "user_property_environment字段因技术错误未完成" in result.notes


def test_same_boundary_duplicate_assets_merge_only_with_shared_evidence():
    block_id = "BLK-BBBBBBBBBBBBBBBB"
    concise = Asset.model_validate(
        _asset_payload(
            name="运行配置资产",
            asset_type="data",
            status="confirmed",
            description="设备处理运行配置。",
            evidence=[_evidence_payload("设备处理运行配置。", block_id=block_id)],
        )
    )
    expanded = Asset.model_validate(
        _asset_payload(
            asset_id="ASSET-007",
            name="运行配置资产",
            asset_type="data",
            status="confirmed",
            description="设备处理运行配置。该配置由管理功能修改。",
            evidence=[_evidence_payload("设备处理运行配置。", block_id=block_id)],
            related_objectives=[
                {
                    "objective_id": "OBJ-007",
                    "description": "确保运行配置在预期运行期间保持可用。",
                    "category": "availability",
                }
            ],
        )
    )

    result = _assemble_asset_sections(
        [
            (
                "data_credentials_software",
                AssetSectionResult(assets=[concise, expanded], assessment="PASS"),
            )
        ],
        section_failures=["systems_services", "functions_impacts"],
        field_failures=(),
        product_functions=[SimpleNamespace(function_id="FUNC-001", name="配置管理")],
        defer_function_coverage=True,
    )

    assert len(result.assets) == 1
    assert len(result.assets[0].related_objectives) == 2
    assert "证据相交的重复资产" in (result.notes or "")


def test_same_name_assets_with_conflicting_boundary_are_not_merged():
    evidence = [_evidence_payload("材料分别描述产品内对象和外部对象。")]
    inside = Asset.model_validate(
        _asset_payload(
            name="管理服务",
            asset_type="service",
            status="confirmed",
            description="产品内的管理服务。",
            evidence=evidence,
        )
    )
    outside = Asset.model_validate(
        _asset_payload(
            asset_id="ASSET-002",
            name="管理服务",
            asset_type="service",
            status="external_affected",
            description="产品外部的管理服务。",
            evidence=evidence,
            related_objectives=[
                {
                    "objective_id": "OBJ-002",
                    "description": "确保外部管理服务在预期期间可用。",
                    "category": "availability",
                }
            ],
        )
    )

    result = _assemble_asset_sections(
        [
            (
                "systems_services",
                AssetSectionResult(assets=[inside, outside], assessment="PASS"),
            )
        ],
        section_failures=["data_credentials_software", "functions_impacts"],
        field_failures=(),
        product_functions=[SimpleNamespace(function_id="FUNC-001", name="服务管理")],
        defer_function_coverage=True,
    )

    assert len(result.assets) == 2
    assert {asset.status for asset in result.assets} == {
        "confirmed",
        "external_affected",
    }
    assert "不足以安全合并" in (result.notes or "")


def test_component_scope_status_is_not_upgraded_by_asset_synthesis():
    candidate = Asset.model_validate(
        _asset_payload(
            name="可选数字模块",
            asset_type="hardware",
            status="confirmed",
            description="模块处理数字信息。",
            evidence=[_evidence_payload("该数字模块按订单选配。")],
        )
    )
    scope = SimpleNamespace(
        in_scope_components=[],
        conditional_scope_components=["可选数字模块"],
        out_of_scope_components=[],
    )
    product_context = SimpleNamespace(
        component_inventory=SimpleNamespace(
            entries=[
                SimpleNamespace(
                    name="可选数字模块",
                    scope_status="conditional",
                )
            ]
        )
    )

    result = _assemble_asset_sections(
        [
            (
                "systems_services",
                AssetSectionResult(assets=[candidate], assessment="PASS"),
            )
        ],
        section_failures=["data_credentials_software", "functions_impacts"],
        field_failures=(),
        product_functions=[SimpleNamespace(function_id="FUNC-001", name="数据处理")],
        defer_function_coverage=True,
        scope=scope,
        product_context=product_context,
    )

    assert result.assets[0].status == "conditional"
    assert "上游条件组件" in (result.notes or "")


def test_asset_without_objective_is_kept_with_neutral_partial_objective():
    credential_candidate = Asset.model_validate(
        _asset_payload(
            name="操作系统用户凭据",
            asset_type="credential",
            status="needs_confirmation",
            related_objectives=[],
        )
    )
    public_key_candidate = Asset.model_validate(
        _asset_payload(
            asset_id="ASSET-002",
            name="升级包数字签名验签公钥",
            asset_type="credential",
            status="needs_confirmation",
            related_objectives=[],
        )
    )
    result = _assemble_asset_sections(
        [
            (
                "data_credentials_software",
                AssetSectionResult(
                    assets=[credential_candidate, public_key_candidate],
                    assessment="PARTIAL",
                    notes="具体保护目标待工程师确认。",
                ),
            )
        ],
        section_failures=["systems_services", "functions_impacts"],
        field_failures=(),
        product_functions=[SimpleNamespace(function_id="FUNC-001", name="登录")],
        defer_function_coverage=True,
    )

    assert len(result.assets) == 2
    assert all(len(asset.related_objectives) == 1 for asset in result.assets)
    assert result.assets[0].related_objectives[0].category == "confidentiality"
    assert result.assets[1].related_objectives[0].category == "authenticity"
    assert result.assets[0].related_objectives[0].basis == "analyst_minimum"
    assert result.assets[0].related_objectives[0].status == "needs_confirmation"
    assert result.assessment == AssessmentVerdict.PARTIAL
    assert "缺少保护目标的资产已补充中性待确认目标2项" in result.notes


def test_node2_field_failure_degrades_only_that_field(monkeypatch, tmp_path):
    profiles = (
        RetrievalProfile(
            node_id=EvidenceTargetNode.ASSETS,
            field_id=RetrievalField.DATA_ASSETS,
            query="data",
        ),
        RetrievalProfile(
            node_id=EvidenceTargetNode.ASSETS,
            field_id=RetrievalField.CREDENTIALS_AND_KEYS,
            query="credentials",
        ),
    )
    monkeypatch.setattr(field_extractor, "get_profiles_for_node", lambda _node: profiles)
    monkeypatch.setattr(
        field_extractor,
        "load_vector_index",
        lambda **_kwargs: SimpleNamespace(directory=tmp_path / "index"),
    )
    monkeypatch.setattr(
        field_extractor,
        "DashScopeEmbeddingProvider",
        lambda **_kwargs: object(),
    )

    def fake_extract(*, profile, **_kwargs):
        if profile.field_id == RetrievalField.CREDENTIALS_AND_KEYS:
            raise RuntimeError("simulated timeout")
        result = FieldExtractionResult(
            node_id=EvidenceTargetNode.ASSETS,
            field_id=profile.field_id,
            facts=[
                RetrievedFact(
                    fact_id="FACT-001",
                    statement="设备处理运行数据。",
                    block_ids=["BLK-AAAAAAAAAAAAAAAA"],
                )
            ],
        )
        trace = SimpleNamespace(
            request=SimpleNamespace(field_id=profile.field_id),
            selected_count=1,
            selected_token_count=10,
        )
        return result, trace, frozenset({"BLK-AAAAAAAAAAAAAAAA"})

    monkeypatch.setattr(field_extractor, "_extract_profile_facts", fake_extract)
    scope = SimpleNamespace(packet=SimpleNamespace(project_id="project"))
    bundle = field_extractor.extract_node_facts(
        llm=object(),
        scope=scope,
        node_id=EvidenceTargetNode.ASSETS,
        config={
            "configurable": {
                "rag_index_dir": str(tmp_path / "index"),
                "workspace": str(tmp_path),
                "field_cache_policy": "reuse",
            }
        },
    )

    assert len(bundle.batches) == 2
    assert bundle.batches[0].facts
    assert bundle.batches[1].facts == []
    assert bundle.failures[0][0] == RetrievalField.CREDENTIALS_AND_KEYS
    assert bundle.prompt_payload({RetrievalField.CREDENTIALS_AND_KEYS})[
        "extraction_failures"
    ] == [{"field_id": "credentials_and_keys", "reason": "technical_failure"}]


def test_identify_assets_keeps_partial_snapshot_but_blocks_completion_on_technical_failure(monkeypatch):
    packet_ref = object()
    binding = SimpleNamespace(reference=packet_ref)
    monkeypatch.setattr(asset_threat_modeler, "get_llm", lambda: object())
    monkeypatch.setattr(asset_threat_modeler, "load_runtime_scope", lambda _config: binding)
    monkeypatch.setattr(
        asset_threat_modeler,
        "extract_node_facts",
        lambda **_kwargs: NodeFactBundle(
            batches=(),
            traces=(),
            retrieved_block_ids=frozenset(),
            failures=((RetrievalField.DATA_ASSETS, "Request timed out."),),
        ),
    )

    def fake_section(*, section_name, **_kwargs):
        if section_name == "functions_impacts":
            raise RuntimeError("simulated section failure")
        asset_type = "credential" if section_name == "data_credentials_software" else "network"
        status = "confirmed" if asset_type == "credential" else "external_affected"
        return AssetSectionResult(
            assets=[
                Asset.model_validate(
                    _asset_payload(
                        name=section_name,
                        asset_type=asset_type,
                        status=status,
                    )
                )
            ],
            assessment="PASS",
        )

    monkeypatch.setattr(asset_threat_modeler, "_extract_asset_section", fake_section)
    monkeypatch.setattr(
        asset_threat_modeler,
        "_extract_asset_function_mapping",
        lambda **_kwargs: AssetFunctionMappingResult(
            mappings=[
                AssetFunctionMappingEntry(
                    asset_id="ASSET-001",
                    related_function_ids=["FUNC-001"],
                ),
                AssetFunctionMappingEntry(
                    asset_id="ASSET-002",
                    related_function_ids=["FUNC-001"],
                ),
            ]
        ),
    )
    product_context = SimpleNamespace(
        functions=[SimpleNamespace(function_id="FUNC-001", name="南向设备接入")]
    )
    result = asset_threat_modeler.identify_assets(
        {
            "errors": [],
            "scope": object(),
            "product_context": product_context,
            "evidence_packet_ref": packet_ref,
        },
        {"configurable": {"rag_index_dir": "index"}},
    )

    assert result["status"] == "asset_identification_technical_incomplete"
    assert len(result["assets"]) == 2
    assert result["asset_assessment"] == AssessmentVerdict.PARTIAL
    assert "functions_impacts分段因技术错误未完成" in result["asset_notes"]
    assert any("functions_impacts" in error for error in result["errors"])
    assert any("data_assets" in error for error in result["errors"])
    assert asset_threat_modeler.route_after_assets(result) == "end"


def test_identify_assets_routes_business_partial_result_to_review(monkeypatch):
    partial = AssetIdentificationResult(
        assets=[Asset.model_validate(_asset_payload())],
        assessment=AssessmentVerdict.PARTIAL,
        notes="存在需人工确认的业务项。",
    )
    monkeypatch.setattr(asset_threat_modeler, "get_llm", lambda: object())
    monkeypatch.setattr(
        asset_threat_modeler,
        "extract_with_retry",
        lambda **_kwargs: partial,
    )
    monkeypatch.setattr(
        asset_threat_modeler,
        "_finalize_unsectioned_asset_result",
        lambda result, *_args, **_kwargs: result,
    )

    result = asset_threat_modeler.identify_assets(
        {
            "errors": [],
            "scope": SimpleNamespace(model_dump=lambda **_kwargs: {}),
            "product_context": SimpleNamespace(
                functions=[], model_dump=lambda **_kwargs: {"functions": []}
            ),
        },
        {"configurable": {}},
    )

    assert result["status"] == "asset_identification_partial_draft"
    assert result["asset_assessment"] == AssessmentVerdict.PARTIAL
    assert asset_threat_modeler.route_after_assets(result) == "review_assets"


def test_asset_status_contract_prevents_cross_layer_mismatches():
    asset = Asset.model_validate(_asset_payload())
    assert resolve_asset_identification_status(
        AssessmentVerdict.PASS, technical_incomplete=False, asset_count=1
    ) == ASSET_IDENTIFICATION_COMPLETED
    assert resolve_asset_identification_status(
        AssessmentVerdict.PARTIAL, technical_incomplete=False, asset_count=1
    ) == ASSET_IDENTIFICATION_PARTIAL_DRAFT
    assert resolve_asset_identification_status(
        AssessmentVerdict.PASS, technical_incomplete=True, asset_count=1
    ) == ASSET_IDENTIFICATION_TECHNICAL_INCOMPLETE
    assert resolve_asset_identification_status(
        AssessmentVerdict.FAIL, technical_incomplete=False, asset_count=1
    ) == ASSET_IDENTIFICATION_FAILED

    assert asset_threat_modeler.route_after_assets(
        {
            "assets": [asset],
            "asset_assessment": AssessmentVerdict.PARTIAL,
            "status": ASSET_IDENTIFICATION_COMPLETED,
        }
    ) == "end"
    assert asset_threat_modeler.route_after_assets(
        {
            "assets": [asset],
            "asset_assessment": AssessmentVerdict.PASS,
            "status": ASSET_IDENTIFICATION_PARTIAL_DRAFT,
        }
    ) == "end"


def test_item_isolation_flows_through_node2_assembly_and_review_route(monkeypatch):
    packet_ref = object()
    binding = SimpleNamespace(reference=packet_ref)
    monkeypatch.setattr(asset_threat_modeler, "get_llm", lambda: object())
    monkeypatch.setattr(asset_threat_modeler, "load_runtime_scope", lambda _config: binding)
    monkeypatch.setattr(
        asset_threat_modeler,
        "extract_node_facts",
        lambda **_kwargs: NodeFactBundle(
            batches=(), traces=(), retrieved_block_ids=frozenset(), failures=()
        ),
    )

    def fake_section(*, section_name, **_kwargs):
        if section_name != "data_credentials_software":
            return AssetSectionResult(
                assets=[], assessment="PASS", notes="无本类别直接证据。"
            )
        normalized = _normalize_asset_section_payload(
            {
                "assets": [
                    _asset_payload(asset_type="system"),
                    _asset_payload(
                        asset_id="ASSET-002",
                        name="管理密码",
                        asset_type="credential",
                        status="confirmed",
                        related_objectives=[
                            {
                                "objective_id": "OBJ-002",
                                "description": "仅向获授权主体披露管理密码。",
                                "category": "confidentiality",
                            }
                        ],
                    ),
                ],
                "assessment": "PASS",
            },
            section_name=section_name,
        )
        return AssetSectionResult.model_validate(normalized)

    monkeypatch.setattr(asset_threat_modeler, "_extract_asset_section", fake_section)
    monkeypatch.setattr(
        asset_threat_modeler,
        "_extract_asset_function_mapping",
        lambda **_kwargs: AssetFunctionMappingResult(
            mappings=[
                AssetFunctionMappingEntry(
                    asset_id="ASSET-001", related_function_ids=["FUNC-001"]
                )
            ]
        ),
    )
    product_context = SimpleNamespace(
        functions=[SimpleNamespace(function_id="FUNC-001", name="身份认证")]
    )

    result = asset_threat_modeler.identify_assets(
        {
            "errors": [],
            "scope": object(),
            "product_context": product_context,
            "evidence_packet_ref": packet_ref,
        },
        {"configurable": {"rag_index_dir": "index"}},
    )

    assert result["status"] == ASSET_IDENTIFICATION_PARTIAL_DRAFT
    assert [asset.name for asset in result["assets"]] == ["管理密码"]
    assert "asset_type不属于本分段允许枚举" in result["asset_notes"]
    assert asset_threat_modeler.route_after_assets(result) == "review_assets"
