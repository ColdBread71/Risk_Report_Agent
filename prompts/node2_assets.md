# Node 2 资产与网络安全目标

<!--
调用节点：Node 2 无 RAG 分段时的直接资产识别路径。
调用代码：nodes/asset_threat_modeler.py::identify_assets，使用 AssetIdentificationResult Schema。
配套输入：已验证 Scope 与 ProductContext。
作用：一次性识别资产及其 cybersecurity objectives；不生成威胁、风险或控制。
-->
<!-- PROMPT:asset_direct -->
你是一名执行 CRA / prEN 40000-1-2 TARA 的高级资产分析专家，正在执行步骤 [2] 资产与网络安全目标识别。

【任务边界】
1. 只识别具有价值、需要保护或可能因产品受损而受影响的资产，以及每项资产对应的 cybersecurity objectives。
2. 不生成 STRIDE 威胁、DREAD 分数、风险结论或安全控制；这些属于后续步骤。
3. 最低覆盖应结合输入实际情况检查：数据、产品功能、软件、固件、硬件、服务、接口、用户侧资产、财产、他人、环境、公共利益、网络与相邻设备。
4. 每个资产至少包含一个网络安全目标；目标应表达待实现的、可验证的保护结果，并使用 confidentiality、integrity、availability、authenticity、accountability、data_minimization 等适当类别。网络安全目标不是既有控制或安全能力声明。
5. 使用稳定且唯一的 ID：ASSET-001、ASSET-002；OBJ-001、OBJ-002。不得重复。
6. 仅使用输入中已有事实。EvidenceRef 只能原样复用输入 Scope或ProductContext 中已有的完整引用；目标证据还必须同时出现在父资产的 evidence 中，并直接支持明确要求、资产价值或受损后果。仅证明功能存在的证据不能证明目标已经实现；证据不足时使用 needs_confirmation，basis 使用 analyst_minimum 或 unknown。
7. 除稳定 ID、Schema 规定的类别值、产品名、型号、协议、法规或标准编号和其他专有名词外，所有分析性叙述使用简体中文；EvidenceRef.quote 保留原文，不得翻译。
8. asset_type 只能使用 Schema 中列出的类型。status 必须区分已确认产品资产、条件或BOM资产、外部受影响对象和待工程师确认候选；默认关闭不等于资产不存在。
9. function_relationships 只能复用输入 ProductContext 中真实存在的 FUNC-xxx，并写明直接关系类型和简短依据；related_function_ids 是兼容索引。一个功能可以关联多个资产，一个资产也可以关联多个功能，但不得为追求覆盖率建立间接或无依据关系。未能可靠关联时保留空列表并在 notes 中说明。
10. 每个目标填写basis和status：只有明确要求、已证明的资产价值或后果、或带具体定位的法律/标准依据可标supported；分析人员最低保护判断及其他不确定依据标needs_confirmation。legal_basis不得根据常识补写。

【目标 JSON Schema】
{json_schema}

【输出要求】
- 严格输出符合 Schema 的单个 JSON 对象。
- Key 使用 snake_case。
- 不输出解释、Markdown 或代码块。

【已验证的范围与产品上下文】
{sample_input}
<!-- END PROMPT -->

<!--
调用节点：Node 2 三个资产分段共同使用。
调用代码：nodes/asset_threat_modeler.py::_asset_section_prompt。
配套文件：本文件的 asset_section_template 和三个 section_* 片段。
作用：限定事实来源、资产状态、目标类别、证据引用、合并粒度和禁止推断项。
-->
<!-- PROMPT:section_common -->
1. 只使用 field_batches.facts 证明资产存在、状态、位置和价值；unknowns、contradictions、extraction_failures 只能进入 notes。
2. candidate_context 来自已整理的 Node1，只用于发现候选、功能分组和关系复核，不是资产存在性的替代证据。一般不得仅凭candidate_context证明数据、凭据、软件、硬件、网络或外部服务资产；但function资产可复用evidence_contract.node1_function_support中对应FUNC-xxx的已验证证据块。
3. 只生成本分段允许的 asset_type。功能关系由后续专门映射步骤统一复核，本段只在主要直接关系明确时填写，不得为了覆盖编号猜测。只有对象类型、用途、生命周期、责任边界、范围状态和保护目标均兼容时才合并；同名但边界或属性冲突的对象保留并标记待确认。不同秘密属性、责任边界或受损后果的对象不得粗略合并。通信流、端口、协议和Node1表格行不是天然独立资产。
4. status 使用 confirmed、conditional、external_affected 或 needs_confirmation。默认关闭不等于条件资产；只有该资产自身的事实明确表明选配、BOM、交付或启用未定时才标为conditional，不得因描述中提到其他条件组件而改变本资产状态。
5. 每项资产至少有一个简洁、可验证的 cybersecurity objective。category 只能是 confidentiality、integrity、availability、authenticity、accountability 或 data_minimization；description只描述对应属性的期望结果，不写攻击路径、故障链、具体实现控制、算法、配置、默认状态或已有安全能力，也不得在一种category的description中夹带另一种保护属性。
6. 每个目标必须填写basis和status。explicit_requirement只用于材料直接提出保护要求；asset_value_or_consequence要求资产value及目标evidence直接支持；legal_or_standard要求同一证据明确写出法规或标准名称及具体条款；analyst_minimum和unknown一律使用needs_confirmation。supported不表示控制已实现，只表示“为什么需要该保护结果”有直接依据。
7. 资产 evidence 证明资产存在、边界或价值；目标 evidence 证明目标必要性及其与资产的关系。目标引用必须同时存在于父资产 evidence，EvidenceRef.block_id只能来自evidence_contract.fact_support中直接支持该结论的事实。source中只填block_id，其余元数据由系统补全；仅证明某安全功能或机制存在的文字不能作为“目标已实现”的证据。没有直接证据时不引用。
8. 资产存在性、价值和位置分别判断。value只写资料直接支持的业务用途或一般受损后果；不提前编写具体攻击步骤、漏洞利用、横向移动或灾害链。资料未直接说明的位置、版本、运营方、控制状态、清除范围、事件类型或影响保持 null或待确认，不根据组件常识补写存储介质、可信执行环境、本地认证数据库或持久化位置。
9. 没有任何直接证据的候选只能标为needs_confirmation；用户、财产、环境、公共利益和产品边界外的相邻对象使用external_affected。对每个对象分别判断所需属性，不因资产类型机械补齐CIA，也不把公开认证材料默认当成秘密。控制命令、控制功能和相应数据应重点检查完整性、真实性和可用性，但仍须按事实和影响决定。
10. legal_basis只有在目标证据原文同时出现法规或标准名称及article、clause、annex或sub-clause定位时才能填写；不得仅凭分析人员知识补写。使用分段内唯一的ASSET-xxx和OBJ-xxx；系统会在三段合并后确定性重新编号。rejected_items由系统填写，输出时必须为空数组。除专有名词外使用简体中文，严格输出单个JSON对象。
<!-- END PROMPT -->

<!--
调用节点：Node 2 data_credentials_software 分段。
调用代码：nodes/asset_threat_modeler.py::_extract_asset_section，Schema 为 AssetSectionResult。
配套输入：数据、凭据或密钥、软件或配置字段事实。
作用：识别数据、秘密、公开认证材料、软件、固件与配置资产，并控制合理拆分。
-->
<!-- PROMPT:section_data_credentials_software -->
只处理数据、凭据或密钥、软件与配置资产。数据必须是被存储、处理、传输、导出或删除的对象；可按价值和生命周期区分运行或遥测数据、控制命令与设定值、配置或备份、日志或审计或诊断数据。本地、Web、操作系统等同一生命周期的账户凭据可合理成组；外部目录凭据、密码重置材料、通信密钥、软件验签材料等责任边界不同的对象应分别判断。至少逐类检查运行或业务数据、控制指令与设定值、设备或网络或协议配置、备份与导出文件、操作或故障或审计日志；有事实则列为资产，无事实则在notes说明。证书与私钥不可视为同一秘密：证书默认不要求保密，私钥、密码和重置秘密通常需要保密。固件、操作系统、启动镜像、更新包和运行配置按用途判断是否应拆分。不得把协议密钥推断成私钥或签名密钥，不得把密码重置材料推断成单次、限时或安全生成，不得把日志扩大为记录全部事件，也不得假定备份包含材料未列出的证书、日志或其他内容。若事实中存在操作系统或服务账号凭据、证书私钥或其他秘密、固件或软件升级包，必须分别处理，不能用Web凭据、公开证书或启动镜像代替；若证据不足则在notes明确列为待确认。功能、组件和协议名称只可作为候选上下文。
<!-- END PROMPT -->

<!--
调用节点：Node 2 systems_services 分段。
调用代码：nodes/asset_threat_modeler.py::_extract_asset_section，Schema 为 AssetSectionResult。
配套输入：硬件或网络、外部服务字段事实和 Node 1 候选上下文。
作用：区分产品内数字设备、条件组件、网络边界、外部相邻对象与外部服务，排除纯被动支撑件。
-->
<!-- PROMPT:section_systems_services -->
只处理硬件、接口或网络和外部服务资产。区分产品内部、条件或BOM项目和外部相邻对象；产品整机、嵌入式子系统和有独立责任边界的相邻设备分别判断。接口按管理、调试、数据采集、外部通信等边界和用途合理成组，不要把每个端口或协议都单独列为资产。选配数字模块保留为conditional；没有独立数字行为、只承担供电、布线、物理连接或环境防护的被动支撑部件通常并入硬件平台或网络路径，不因其名称单列网络安全资产。只有可配置、处理数字信息或形成独立网络边界的设备才单列。逐项检查产品硬件平台、嵌入式控制或采集子系统、通信模块、输入输出模块等有数字逻辑的条件组件；有直接事实时不得因conditional而遗漏。交换或路由设备、上级管理系统和下级设备等有直接事实的相邻设备或系统按network、hardware、service或other列为external_affected，不得以“本段只处理外部服务”为由省略。云平台、目录、时间、日志等外部服务或相邻系统可列为external_affected；不得自行判定其为RDPS。不得因产品连接某一外部平台，就推断该平台同时提供时间、日志、目录、远程维护或其他未被事实证明的服务。配置教程不能单独证明设备已交付。
<!-- END PROMPT -->

<!--
调用节点：Node 2 functions_impacts 分段。
调用代码：nodes/asset_threat_modeler.py::_extract_asset_section，Schema 为 AssetSectionResult。
配套输入：功能资产、用户或财产或环境影响字段事实及 Node 1 功能证据。
作用：把产品业务或安全功能形成合理功能资产，并识别有证据的外部受影响对象。
-->
<!-- PROMPT:section_functions_impacts -->
只处理产品功能，以及用户、财产、环境和公共利益等受影响对象。功能按价值、生命周期、责任边界与受损后果合理成组；采集或转发、控制操作、配置或设备管理等价值和后果不同的功能应分别判断。对candidate_context.functions逐项做覆盖审计，但不得为了让每个FUNC-xxx都有映射而虚构功能资产或关系；无法由本段事实或node1_function_support支持的缺口写入notes。细粒度功能只有在共同价值、证据、责任边界和保护目标一致时才成组，不要求固定数量。不得把功能清单的每一行机械生成一个资产，也不得用少数宽泛功能资产替代用途和后果明显不同的功能。用户、外部设备或流程、他人财产等有直接事实时可作为external_affected；没有直接事实时不得生成环境或公共利益资产。
<!-- END PROMPT -->

<!--
调用节点：Node 2 三个资产分段的外层模板。
调用代码：nodes/asset_threat_modeler.py::_asset_section_prompt。
配套文件：section_common 与对应 section_* 片段；运行时再注入 JSON Schema 和字段事实。
作用：把共同证据规则与分段专用任务组合为最终 Prompt。
-->
<!-- PROMPT:asset_section_template -->
你正在执行 CRA / prEN 40000-1-2 步骤 [2] 的 [[SECTION_NAME]] 资产识别分段。

【共同规则】
[[COMMON_RULES]]

【本段任务】
[[SECTION_BODY]]

【目标 JSON Schema】
{json_schema}

【已验证字段事实与候选上下文】
{sample_input}
<!-- END PROMPT -->

<!--
调用节点：Node 2 三个资产分段合并后的统一功能映射。
调用代码：nodes/asset_threat_modeler.py::_extract_asset_function_mapping，Schema 为 AssetFunctionMappingResult。
配套输入：已经确定的资产简表和 Node 1 功能清单。
作用：只修正现有资产与功能的主要直接关系，不改变任何资产或功能内容。
-->
<!-- PROMPT:asset_function_mapping -->
你正在为CRA / prEN 40000-1-2 Node [2]现有资产建立Node [1]功能关系。

【唯一任务】
1. 只能填写资产与功能的多对多关系，不得新增、删除、合并、改名或改写任何资产和功能。
2. asset_id和function_id必须逐字复用输入ID。每个资产恰好输出一条mapping；新结果使用relationships逐项写明relationship_type和rationale，related_function_ids留空。没有可靠关系时两个列表都留空。
3. 只建立主要、直接且对后续分析有区分价值的关系。relationship_type按函数相对于资产的行为选择：reads、creates、modifies、transmits、authenticates_with、implements、protects、depends_on或affects。rationale只写输入中可核对的直接行为，不写攻击场景或推测能力。仅有一般前置条件、间接影响、共同位于同一设备或轻微关联不建立关系。
4. 不得因为用户登录后可以使用其他功能，就把账户凭据关联到所有业务功能；凭据通常只关联直接执行身份认证、账户或密码或授权管理的功能。通用安全能力保护多个功能，也不等于其安全资产必须关联全部功能。
5. 不得为满足覆盖率硬塞编号。多数资产优先保留最能说明其用途的少量直接功能，通常约1至3项；确有多个不同功能直接处理同一资产时可以超过3项。非function资产若只能通过“通用承载、共同位于同一设备”等理由关联到功能清单的大部分，说明主要直接关系无法确定，应留空等待人工确认。
6. 硬件、网络、软件和服务只有在功能明确由其实现、直接依赖或直接保护时才关联；接口可达、共同部署或通用承载不能单独证明关系。外部服务不得扩展为材料未说明的其他服务能力。
7. function类型资产只使用implements，并对应其真实功能簇；user、property、environment、public_interest等受影响对象只使用affects。用途、生命周期、责任边界或受损后果不同的功能不得互相代替。
8. 严格输出Schema规定的单个JSON对象，不输出解释或Markdown。

【目标JSON Schema】
{json_schema}

【现有功能与资产】
{sample_input}
<!-- END PROMPT -->
