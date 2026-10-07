# Context 规范

## 1. 目的

本文档定义第一阶段的 `TOE / Context` 抽取模板。

目标不是强行追求完整，而是生成一个稳定、可复用、可追溯的产品画像，后续可以映射到 Excel 的 `toe scope` 表。

## 2. 支持的输入范围

第一版优先处理以下材料：

- 产品介绍 / 产品宣传册
- 用户手册
- 技术手册 / 技术说明
- 架构图
- 部署 / 集成说明
- 接口或通信说明

第一版不应试图一次性解决所有噪声输入。
装饰性宣传页、重复图片、无关营销内容，只要不包含技术事实，就可以忽略。

## 3. 输出契约

抽取阶段输出 `ProductProfile`。

默认规则：

- 字段找不到时，返回 `null` 或空列表
- 不编造缺失事实
- 尽量为每个抽取结果保留证据

## 4. 命名规则

每个字段都应具备：

- `name`：代码和 Prompt 使用的英文标识
- `Chinese name`：Excel 和人工阅读使用的中文名称
- `description`：字段含义
- `level`：1 / 2 / 3 级字段
- `rule`：抽取约束或说明
- `example`：如有必要可补充示例

命名原则：

- 同一个概念只保留一个稳定的英文名
- Excel 里已有中文名称就尽量沿用
- 如果模板里没有现成名称，就我们自己定一个并冻结
- 历史项目里可能有别名，但工作流里只使用一个规范名称

## 5. 字段树草案

下面是与现有成品 Excel 的 `toe scope` 结构对齐的第一版字段字典。目标是尽量贴近工作簿结构，避免过度设计。

### 5.0 字段字典格式

下面每个字段都遵循同样的格式：
- `name`：英文标识
- `Chinese name`：中文标签
- `description`：字段含义
- `rule`：抽取约束或说明

### 5.1 产品基本信息 / `product_basic_info`

这一部分描述产品和项目的基础身份信息。

- `product_name` / 产品名称
  - description：材料中出现的产品正式名称。
  - rule：优先取封面、扉页、产品介绍中的正式名称；如果有多个叫法，选最稳定、最正式的名称。
- `product_summary` / 产品简介
  - description：对产品用途、定位或核心特征的简要概述。
  - rule：只保留明确可确认的简介内容，不扩写宣传语。
- `product_type` / 产品类型
  - description：产品所属类别或类型。
  - rule：优先取文档中明确写出的分类；没有明确分类时可留空。
- `product_model` / 产品型号
  - description：产品型号或规格型号。
  - rule：仅在资料中明确出现时提取，不根据命名习惯推断。
- `product_software_version` / 产品软件版本
  - description：产品的软件版本号。
  - rule：仅提取资料中明确给出的版本信息。
- `product_hardware_version` / 产品硬件版本
  - description：产品的硬件版本号或硬件型号信息。
  - rule：仅在资料中明确存在时提取，无法确认时留空。

### 5.2 产品预期用途以及合理可预见的使用 / `intended_and_foreseeable_use`

这一部分描述产品“是做什么的、怎么被正常使用、可能被如何误用”，重点是用途和使用方式，不强调通信细节。

- `intended_use` / 预期用途
  - description：产品设计上的主要用途。
  - rule：优先提取产品说明、产品简介或用途描述中的明确表述。
- `foreseeable_use` / 合理可预见的使用
  - description：在正常使用之外，仍可合理预见的使用方式或误用方式。
  - rule：只记录材料中明确提示或可直接支持的内容，不做自由联想。
- `usage_scenarios` / 适用场景
  - description：产品适用的典型业务场景或使用场景。
  - rule：以文档明确描述为准；如果只有笼统表达，可保守归纳为场景短语。

### 5.3 产品通信环境或南北向环境说明 / `communication_environment`

这一部分描述产品的通信对象、运行环境和边界关系；南向 / 北向只是可选展开项，不作为强制结构。

- `communication_environment_description` / 通信环境说明
  - description：对产品所处通信环境的总体说明。
  - rule：优先保留能说明系统运行边界、网络位置或连接关系的内容。
- `deployment_mode` / 部署方式
  - description：产品的部署形态，如本地、云端、边缘、单机、分布式等。
  - rule：只记录资料中明确提到的部署方式，不推断架构。
- `runtime_environment` / 运行环境
  - description：产品运行所依赖的操作系统、平台、网络或基础设施环境。
  - rule：仅在材料明确说明时抽取。
- `network_boundary` / 网络边界
  - description：产品对外通信所形成的网络边界或访问边界。
  - rule：侧重可见边界与外部连接关系；没有清晰边界时可留空。
- `trust_boundary` / 信任边界
  - description：系统内部与外部、可信与非可信区域之间的边界。
  - rule：只有在材料能支持时才提取；不强制从普通宣传资料中推断。
- `southbound_communication` / 南向通信
  - description：面向下层设备、终端或底层单元的通信说明。
  - rule：仅当产品存在明确南向结构时使用；否则留空。
- `northbound_communication` / 北向通信
  - description：面向上位系统、平台、云端或管理端的通信说明。
  - rule：仅当产品存在明确北向结构时使用；否则留空。

### 5.4 产品通讯矩阵 / `communication_matrix`

这一部分承载产品的通信关系总览，通常是一个需要人工补录或半自动整理的结构化块。

- `communication_matrix` / 通信矩阵
  - description：产品通信关系的总表或总览。
  - rule：作为一个整体结构保留，通常允许人工补录。
- `communication_targets` / 通信对象
  - description：与产品发生通信的外部对象、系统或设备。
  - rule：提取明确出现的通信对象，不自行扩展对象列表。
- `communication_protocols` / 通信协议
  - description：产品使用的通信协议或接口协议。
  - rule：仅记录材料中明确给出的协议名称。
- `interface_types` / 接口类型
  - description：产品对外接口的类型，如 API、串口、Web、消息接口等。
  - rule：以材料明确描述为准，无法确认时留空。
- `data_flows` / 数据流转
  - description：数据在产品与外部对象之间的流转方向和关系。
  - rule：只抽取明确的数据流描述，不做流程重构。

### 5.5 产品功能场景描述（涉及网络安全的功能清单） / `security_function_scenarios`

这一部分描述产品的功能和与网络安全相关的场景，为后续 TARA 风险识别提供输入。

- `function_scenario_descriptions` / 功能场景描述
  - description：产品功能在具体使用场景中的描述。
  - rule：优先保留能对应到实际功能或业务流程的描述。
- `core_functions` / 核心功能
  - description：产品最主要、最核心的功能集合。
  - rule：只保留明确可确认的核心功能项。
- `security_related_functions` / 网络安全相关功能
  - description：与安全、认证、审计、访问控制、加密等相关的功能。
  - rule：只提取与安全分析直接相关的功能，不把普通业务功能混入其中。
- `management_functions` / 管理功能
  - description：用于配置、运维、管理、维护的功能。
  - rule：若资料未明确区分管理功能，可留空或只做保守归类。
- `known_limitations` / 已知限制
  - description：产品能力范围、边界条件或明确限制。
  - rule：优先记录文档明确声明的限制，不做推断。

### 5.6 产品构成（数字组件） / `digital_components`

这一部分描述产品的组成结构，重点关注数字系统、软件模块和外部依赖。

- `product_components` / 产品构成
  - description：产品整体组成说明。
  - rule：优先保留材料中明确给出的组成结构。
- `digital_components` / 数字组件
  - description：产品中的软件、固件、平台、服务等数字化组成部分。
  - rule：仅在材料明确描述时提取，不能凭经验补全。
- `modules` / 模块划分
  - description：产品内部功能模块或逻辑模块划分。
  - rule：若材料没有模块图或结构图，可留空。
- `external_dependencies` / 外部依赖
  - description：产品运行或功能实现依赖的外部系统、组件或服务。
  - rule：只记录明确出现的依赖关系，不推断隐含依赖。

### 5.7 Open items

- `open_questions` / 待确认项
- `manual_fill_items` / 人工补录项
- `missing_items_note` / 缺失项说明

## 6. 字段筛选规则

- 字段集合要尽量贴近现有 Excel 表结构。
- 只有在反复出现或明显有助于后续 TARA 分析时，才新增子字段。
- 通信矩阵第一版先作为一个大块，不要过度拆分。
- 如果某个概念在不同项目中不稳定，就不要过早提升为一级字段。
- 对于客户材料里经常缺失的字段，允许输出空值，不要强迫抽取。

## 7. 抽取规则

- 抽取器应优先提取技术事实，而不是营销话术。
- 长篇宣传资料可以作为输入，但只保留稳定的技术部分。
- 只有在图片中存在可确认的技术信息时才抽取。
- 如果多个片段支持同一结论，要保留证据链，但不要超出原始片段支持范围。
- 宁可返回稀疏但正确的画像，也不要返回填满但带推测的画像。

## 8. 模板映射说明

本文档描述的是逻辑字段系统。
最终的 Excel `toe scope` 表可以由这些字段映射得到，但表格布局本身由复制出来的模板单独维护。
