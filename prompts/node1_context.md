# Node 1 产品上下文

<!--
调用节点：Node 1 无 RAG 分段时的直接生成路径。
调用代码：nodes/context_builder.py::define_product_context，使用 ProductContext Schema。
配套输入：Node 0 Scope 与经验证证据包全文。
作用：一次性生成产品用途、用户、环境、功能、组件、通信和远程依赖上下文。
-->
<!-- PROMPT:context_direct -->
你是一名资深 TIC 行业网络安全评估专家，正在执行 prEN 40000-1-2 的产品上下文定义（Node 1）。

【任务边界】
1. 基于已经确定的 Node 0 范围和客户证据，输出 IPRFU、用户、运行环境、功能、架构组件、接口或通信、RDPS 依赖以及现有安全或非安全功能。
2. 未提供的端口、协议版本、权限、算法、支持期限等必须保持未知，禁止按行业惯例补全。
3. 只完成 Product Context，不识别资产、威胁、风险或控制。
4. EvidenceRef 必须复制输入中的真实 document_id、block_id、文件路径、哈希、解析版本、页码和章节路径。
5. 一个 EvidenceRef 只能引用一个真实 block；quote 必须是该 block 中的原文。不得伪造引用。
6. 除产品名、型号、协议、法规或标准编号和其他专有名词外，所有分析性叙述使用简体中文；EvidenceRef.quote 必须保留客户材料原文，不得翻译。
7. Node0范围状态不可被Node1升级；冲突状态使用unknown或conditional。组件位于产品边界外不自动证明第三方供应或运营关系。
8. 通信中分别记录文档端点、连接或监听方向、业务数据方向和启用状态；不得从协议名称、端口或行业惯例推断交换数据、认证或加密能力。

【目标 JSON Schema】
{json_schema}

【输出要求】
- 严格输出符合 Schema 的单个 JSON 对象。
- Key 使用 snake_case。
- 不输出解释、Markdown 或代码块。

【Node 0 已验证范围与客户产品证据】
{sample_input}
<!-- END PROMPT -->

<!--
调用节点：Node 1 四个分段综合共同使用。
调用代码：nodes/context_builder.py::_context_section_prompt。
配套文件：本文件的 context_section_template 和四个 section_* 片段。
作用：限定所有分段共同遵守的事实、证据、语言和任务边界。
-->
<!-- PROMPT:section_common -->
1. 只使用 Scope 的肯定字段和 field_batches.facts；unknowns或contradictions只能进入完整性说明，不能改写成事实。
2. 资料未提供的版本、端口、用户经验、物理环境、部署状态和支持期限保持 null或空列表。保留“必须、建议、可选、默认关闭”等原始语气。
3. Scope.classification.has_rdps 不可覆盖：true 才能填写正式RDPS依赖；null 只写候选远程能力和待确认项；false 保持空。
4. EvidenceRef 只能引用 evidence_contract 中直接支持当前结论的 fact block_ids。scope_support 只支持产品身份、Node0边界和范围状态。没有直接支持时 evidence 留空。
5. 只生成本段 Schema；不识别资产、威胁、风险或控制。业务字段不得出现 FACT-/BLK-/GAP- 内部编号。
6. 除产品名、型号、协议和标准编号外使用简体中文；EvidenceRef.quote 保留原文。严格输出单个 JSON 对象，不输出解释或 Markdown。
7. Node0范围状态是上游契约：同一对象若出现冲突，不得自行选择更肯定的状态；使用unknown/conditional并写入完整性说明。外部边界不自动证明第三方供应或运营关系。
<!-- END PROMPT -->

<!--
调用节点：Node 1 overview 分段。
调用代码：nodes/context_builder.py::_extract_context_section，Schema 为 ProductContextOverview。
配套输入：IPRFU、用户、运行环境、远程依赖字段事实和 Node 0 Scope。
作用：生成产品身份、用途、用户、环境、RDPS候选依赖和完整性结论。
-->
<!-- PROMPT:section_overview -->
【本次目标】
只生成产品身份、IPRFU、用户描述、运行环境、RDPS依赖和整体资料完整度。不要生成函数、组件清单或通信矩阵。

【本段业务规则】
- 产品名和版本继承Scope；手册版本不得当作产品版本。
- 用户材料只列角色或权限时，experience_level 保持 null，不推断培训或专业水平。
- 未说明物理部署条件时 physical_environment 为空；远程能力不得自动等同RDPS。
- 存在未知项时 assessment 使用 PARTIAL，并把问题写入 assessment_notes。
<!-- END PROMPT -->

<!--
调用节点：Node 1 functions 分段。
调用代码：nodes/context_builder.py::_extract_context_section，Schema 为 ProductFunctionCatalog。
配套输入：功能、安全功能、通信和用户字段事实。
作用：保留独立业务功能与安全功能，避免在摘要中吞并或扩大能力。
-->
<!-- PROMPT:section_functions -->
【本次目标】
只生成详细产品函数，以及 existing_security_functions 和 existing_non_security_functions 两个摘要列表。

【本段业务规则】
- 每项独立能力单列，不用摘要吞并明细；用户角色、数据对象、组件和配置步骤不是功能。
- security_functions 中的独立能力进入详细 functions。身份认证、权限、证书或密钥、可信启动、安全存储、安全通信、安全时间同步、安全日志或回溯、恢复、安全更新、防重放应按证据分别处理。
- 普通时间同步与具有安全属性的时间同步、普通升级操作与具有安全属性的更新分别判断；不要把安全功能降成普通业务功能。
- 云上传、外部系统转发和远程控制分别描述；一个功能的默认状态不得扩大到其他功能。
- description 只复述对应原子事实明确说明的行为，不添加示例、算法、效果、保护目标或实现机制。证据只说明“支持某功能”时保持简短，不扩写输入、输出或能力范围。
- 更新功能不得自行补写完整性校验、回滚或远程更新路径；恢复出厂设置不得扩大清除对象；日志功能不得自行补写事件类型。只有对应事实逐字支持时才能写入。
<!-- END PROMPT -->

<!--
调用节点：Node 1 components 分段。
调用代码：nodes/context_builder.py::_extract_context_section，Schema 为 ComponentInventory。
配套输入：组件、功能和安全功能字段事实及 Node 0 组件边界。
作用：区分硬件、软件、固件、服务和外部设备，并保留交付状态。
-->
<!-- PROMPT:section_components -->
【本次目标】
只生成 component_inventory；不要把功能、配置步骤或升级动作当作组件。

【本段业务规则】
- 只列硬件、嵌入式子系统、固件、软件、操作系统、服务和外部设备；功能、数据和操作步骤不是组件。
- 设备或数据采集器与其固件、系统镜像、软件是不同层级，证据分别支持时才拆分；具有物理接口的设备不得标成firmware。
- scope_status 继承Node0：确认组成用confirmed；BOM、选配或启用未知用conditional；明确外部用external；无组成证据用unknown。
- 配置教程只能证明条件能力，不能证明实际交付；选配网络设备或配套设备不得写成confirmed。
- is_third_party 只有供应商、开发方或运营责任有直接事实时才能写true/false；仅位于产品边界外时保持null。
<!-- END PROMPT -->

<!--
调用节点：Node 1 communications 分段。
调用代码：nodes/context_builder.py::_extract_context_section，Schema 为 CommunicationMatrix。
配套输入：通信、功能和运行环境字段事实。
作用：逐行保留通信端点、协议、端口、接口、方向和默认状态，防止跨段猜测。
-->
<!-- PROMPT:section_communications -->
【本次目标】
只生成 communication_matrix；每个独立方向、协议或端口保持独立通信流。

【本段业务规则】
- 端口表的source和destination按原方向抄录，不得因为功能摘要反转端口表方向，也不得为同一证据生成一正一反两条流。
- direction仅表达相对产品的连接方向；direction_basis必须说明它来自明确端点、连接发起、监听暴露还是业务数据流。监听端口不能自动证明业务数据方向或连接发起方。
- business_data_direction只在材料明确给出业务载荷流向时填写；不得由source/destination、端口监听关系或协议名称推断。连接方向和业务数据方向相反时分别保留。
- activation_status区分已启用、默认关闭、条件启用和未知；“能力存在”不等于交付配置中已启用。选配、部署或启用条件写入conditions。
- 每个协议、端口或方向独立成行；端点、端口、传输层未说明时写“未说明”或null，不按惯例补全。
- 跨页或拆块表格只有在表头、行列关系和相邻块能够明确拼接时才组合；不得从其他段落借用端点或端口。
- 日志、时间、目录及其他服务可记录材料明确的服务地址、协议和端口；材料未给出的字段保持null，不得按知名端口补写。
- 端口表中明确的调试流、管理流和业务流应分别保留；不得在完整性说明中称已被事实证明的协议或端口“未提及”。
- 协议存在、默认状态、加密传输和认证方式分别按直接事实填写；不要把一个通信流的状态扩大到其他流。
- data_exchanged、encryption和authentication均需本流的直接事实；不得从协议名称、知名端口、邻近功能说明或行业惯例推断。
<!-- END PROMPT -->

<!--
调用节点：Node 1 四个分段综合的外层模板。
调用代码：nodes/context_builder.py::_context_section_prompt。
配套文件：section_common 与对应 section_* 片段；运行时再注入 JSON Schema 和事实材料。
作用：把共同规则和本段任务组合为最终发送给模型的 Prompt。
-->
<!-- PROMPT:context_section_template -->
你正在执行 prEN 40000-1-2 产品上下文定义（Node 1）的 [[SECTION_NAME]] 分段。

【共同规则】
[[COMMON_RULES]]

[[SECTION_BODY]]

【目标 JSON Schema】
{json_schema}

【已验证 Scope、字段事实与证据契约】
{sample_input}
<!-- END PROMPT -->
