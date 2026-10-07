from __future__ import annotations

from pydantic import BaseModel, Field


class ProductBasicInfo(BaseModel):
    product_name: str | None = Field(
        default=None,
        description="材料中出现的产品正式名称。优先取封面、扉页、产品介绍中的正式名称；如果有多个叫法，选最稳定、最正式的名称。",
    )
    product_summary: str | None = Field(
        default=None,
        description="对产品用途、定位或核心特征的简要概述。只保留明确可确认的简介内容，不扩写宣传语。",
    )
    product_type: str | None = Field(
        default=None,
        description="产品所属类别或类型。优先取文档中明确写出的分类；没有明确分类时可留空。",
    )
    product_model: str | None = Field(
        default=None,
        description="产品型号或规格型号。仅在资料中明确出现时提取，不根据命名习惯推断。",
    )
    product_software_version: str | None = Field(
        default=None,
        description="产品的软件版本号。仅提取资料中明确给出的版本信息。",
    )
    product_hardware_version: str | None = Field(
        default=None,
        description="产品的硬件版本号或硬件型号信息。仅在资料中明确存在时提取，无法确认时留空。",
    )


class IntendedAndForeseeableUse(BaseModel):
    intended_use: str | None = Field(
        default=None,
        description="产品设计上的主要用途。优先提取产品说明、产品简介或用途描述中的明确表述。",
    )
    foreseeable_use: list[str] = Field(
        default_factory=list,
        description="在正常使用之外，仍可合理预见的使用方式或误用方式。只记录材料中明确提示或可直接支持的内容，不做自由联想。",
    )
    usage_scenarios: list[str] = Field(
        default_factory=list,
        description="产品适用的典型业务场景或使用场景。以文档明确描述为准；如果只有笼统表达，可保守归纳为场景短语。",
    )


class CommunicationEnvironment(BaseModel):
    communication_environment_description: str | None = Field(
        default=None,
        description="对产品所处通信环境的总体说明。优先保留能说明系统运行边界、网络位置或连接关系的内容。",
    )
    deployment_mode: list[str] = Field(
        default_factory=list,
        description="产品的部署形态，如本地、云端、边缘、单机、分布式等。只记录资料中明确提到的部署方式，不推断架构。",
    )
    runtime_environment: list[str] = Field(
        default_factory=list,
        description="产品运行所依赖的操作系统、平台、网络或基础设施环境。仅在材料明确说明时抽取。",
    )
    network_boundary: list[str] = Field(
        default_factory=list,
        description="产品对外通信所形成的网络边界或访问边界。侧重可见边界与外部连接关系；没有清晰边界时可留空。",
    )
    trust_boundary: list[str] = Field(
        default_factory=list,
        description="系统内部与外部、可信与非可信区域之间的边界。只有在材料能支持时才提取；不强制从普通宣传资料中推断。",
    )
    southbound_communication: list[str] = Field(
        default_factory=list,
        description="面向下层设备、终端或底层单元的通信说明。仅当产品存在明确南向结构时使用；否则留空。",
    )
    northbound_communication: list[str] = Field(
        default_factory=list,
        description="面向上位系统、平台、云端或管理端的通信说明。仅当产品存在明确北向结构时使用；否则留空。",
    )


class CommunicationMatrix(BaseModel):
    communication_matrix: str | None = Field(
        default=None,
        description="产品通信关系的总表或总览。作为一个整体结构保留，通常允许人工补录。",
    )
    communication_targets: list[str] = Field(
        default_factory=list,
        description="与产品发生通信的外部对象、系统或设备。提取明确出现的通信对象，不自行扩展对象列表。",
    )
    communication_protocols: list[str] = Field(
        default_factory=list,
        description="产品使用的通信协议或接口协议。仅记录材料中明确给出的协议名称。",
    )
    interface_types: list[str] = Field(
        default_factory=list,
        description="产品对外接口的类型，如 API、串口、Web、消息接口等。以材料明确描述为准，无法确认时留空。",
    )
    data_flows: list[str] = Field(
        default_factory=list,
        description="数据在产品与外部对象之间的流转方向和关系。只抽取明确的数据流描述，不做流程重构。",
    )


class SecurityFunctionScenarios(BaseModel):
    function_scenario_descriptions: list[str] = Field(
        default_factory=list,
        description="产品功能在具体使用场景中的描述。优先保留能对应到实际功能或业务流程的描述。",
    )
    core_functions: list[str] = Field(
        default_factory=list,
        description="产品最主要、最核心的功能集合。只保留明确可确认的核心功能项。",
    )
    security_related_functions: list[str] = Field(
        default_factory=list,
        description="与安全、认证、审计、访问控制、加密等相关的功能。只提取与安全分析直接相关的功能，不把普通业务功能混入其中。",
    )
    management_functions: list[str] = Field(
        default_factory=list,
        description="用于配置、运维、管理、维护的功能。若资料未明确区分管理功能，可留空或只做保守归类。",
    )
    known_limitations: list[str] = Field(
        default_factory=list,
        description="产品能力范围、边界条件或明确限制。优先记录文档明确声明的限制，不做推断。",
    )


class DigitalComponents(BaseModel):
    product_components: list[str] = Field(
        default_factory=list,
        description="产品整体组成说明。优先保留材料中明确给出的组成结构。",
    )
    digital_components: list[str] = Field(
        default_factory=list,
        description="产品中的软件、固件、平台、服务等数字化组成部分。仅在材料明确描述时提取，不能凭经验补全。",
    )
    modules: list[str] = Field(
        default_factory=list,
        description="产品内部功能模块或逻辑模块划分。若材料没有模块图或结构图，可留空。",
    )
    external_dependencies: list[str] = Field(
        default_factory=list,
        description="产品运行或功能实现依赖的外部系统、组件或服务。只记录明确出现的依赖关系，不推断隐含依赖。",
    )


class ContextDraft(BaseModel):
    update_thoughts: str | None = Field(
        default=None,
        description="【必填】在修改任何信息前，先详细陈述你的更新理由。如果本章没有比历史数据更好的信息，请明确写出'本章无高价值信息，保留全部原有数据'。",
    )
    basic_info: ProductBasicInfo = Field(default_factory=ProductBasicInfo)
    use_cases: IntendedAndForeseeableUse = Field(default_factory=IntendedAndForeseeableUse)
    environment: CommunicationEnvironment = Field(default_factory=CommunicationEnvironment)
    matrix: CommunicationMatrix = Field(default_factory=CommunicationMatrix)
    security_functions: SecurityFunctionScenarios = Field(default_factory=SecurityFunctionScenarios)
    components: DigitalComponents = Field(default_factory=DigitalComponents)
    open_questions: list[str] = Field(default_factory=list, description="待确认项。")
    missing_items_note: list[str] = Field(default_factory=list, description="确实找不到的缺失项说明。")


class ChapterExtractionResult(BaseModel):
    chapter_summary: str = Field(
        default="",
        description="本章内容的简要总结。",
    )
    key_facts: list[str] = Field(
        default_factory=list,
        description="本章中重要的高价值安全/产品信息提取（作为备用参考兜底）。",
    )
    chapter_context: ContextDraft = Field(
        default_factory=ContextDraft,
        description="仅基于本章内容提取的局部 Context。必须输出 Schema 定义的所有字段，若本章无相关信息，严格留空（null 或空列表），绝不允许瞎编。",
    )
