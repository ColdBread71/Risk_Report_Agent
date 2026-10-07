# 字段事实整理要求

<!--
调用节点：Node 0–2 中没有专用整理要求的普通字段。
调用代码：tools/retrieval_profiles.py::_profile，经 nodes/field_extractor.py 注入 field_fact Prompt。
作用：提供最小通用原子事实整理规则。
-->
<!-- PROMPT:generic -->
逐条保留与本字段直接相关的原子事实；未知信息写入 unknowns。
<!-- END PROMPT -->

<!--
调用节点：Node 1 functions 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：逐项保留业务功能与安全功能，防止摘要吞并。
-->
<!-- PROMPT:context_functions -->
按可独立描述的业务功能或安全功能逐条提取，保留输入、输出、使用接口和适用条件；不要用一条总述代替多项功能，也不要把数据、组件或操作步骤当作功能。
<!-- END PROMPT -->

<!--
调用节点：Node 1 components 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：区分组件层级并保留交付或选配状态。
-->
<!-- PROMPT:context_components -->
只提取硬件、嵌入式子系统、固件、软件、操作系统、服务或外部设备。安全功能、升级动作、配置步骤和数据不是组件，不得作为组件事实。设备与其固件分别记录；标准内置、选配、外置、仅有配置教程或交付状态未知必须逐字保留，配置教程本身不能证明该设备属于本次交付。每条组件fact在attributes中只填写component_name、component_type、scope_status、conditions；scope_status只能是confirmed、conditional、external、unknown，conditions仅在材料明确给出条件时填写，否则不输出该键。
<!-- END PROMPT -->

<!--
调用节点：Node 1 communications 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：保持通信表格端点、协议、端口、接口和状态的行列关系。
-->
<!-- PROMPT:context_communications -->
按源设备、目的设备、协议、端口、接口、连接发起或监听角色、业务数据方向和默认启用状态逐条保留；明确区分端口监听/连接方向与业务载荷流向，材料只证明其中一种时另一种写未知。端口矩阵每条事实必须明确保留表格中的源设备和目的设备，同一行协议与端口不得拆散。跨页或拆块表格只有在表头、行列关系和相邻块能够明确拼接时才组合。不同段落同时出现多个外部系统时，只采用通信行明确写出的端点，不按邻近文字猜测目的端。日志、时间、目录及其他服务只记录材料明确给出的服务地址、协议和端口；交换数据、认证、加密、端口、传输层、源或目的未说明时明确写未知，不得按协议名称、知名端口或惯例补全。每条通信fact在attributes中按证据填写source、destination、protocol、port、interface、authentication、encryption、data_exchanged、conditions；direction_basis只能是documented_endpoints、connection_initiation、listener_exposure、business_data_flow、unknown，business_data_direction只能是to_product、from_product、bidirectional、unknown，activation_status只能是enabled、disabled_by_default、conditional、unknown。未说明的普通值使用null，未说明的枚举使用unknown。
<!-- END PROMPT -->

<!--
调用节点：Node 1 security_functions 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：分开提取安全能力，并禁止补写未说明的效果和范围。
-->
<!-- PROMPT:context_security_functions -->
按安全登录、用户或密码、权限、协议配置、证书或密钥、安全启动、安全存储、安全通信、安全时间同步、日志、恢复和安全更新等独立能力逐条提取；严格区分功能存在、默认状态、可选配置和仅供用户参考的部署建议。每条功能事实必须引用包含功能名称或说明的正文或表格block，禁止引用章节标题或页眉；更新、恢复出厂和日志功能不得补写原文未说明的校验、回滚、清除范围或事件类型。
<!-- END PROMPT -->

<!--
调用节点：Node 2 data_assets 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：只抽取数据对象，不把处理数据的功能误写成数据。
-->
<!-- PROMPT:asset_data -->
只提取被产品存储、处理、传输、导出或删除的数据对象，不把数据采集、协议转换、业务控制等功能本身写成数据。分别保留运行或遥测或状态数据、控制与操作指令、业务设定值、配置与备份、日志与审计、故障或调试数据和网络拓扑信息；类型、位置、保留期限或清除范围未说明时保持未知。
<!-- END PROMPT -->

<!--
调用节点：Node 2 credentials_and_keys 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：区分账号、重置材料、证书、私钥、协议密钥和访问材料。
-->
<!-- PROMPT:asset_credentials -->
逐项区分本地、Web、操作系统和外部目录账号凭据，设备标识，密码重置校验材料，证书及对应私钥，协议密钥，软件验签公钥，日志或备份导出密码和远程维护访问信息。证书不得与私钥混称为秘密；操作步骤只证明材料存在，不补写算法、有效期、存储位置或传递机制。
<!-- END PROMPT -->

<!--
调用节点：Node 2 software_and_configuration 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：区分软件对象、配置数据与升级动作。
-->
<!-- PROMPT:asset_software_configuration -->
分别提取固件或操作系统或启动镜像、升级包及升级输入、设备与网络配置、协议与端口配置、业务或控制参数、安全策略与权限配置、证书配置和备份文件。软件对象、配置数据和升级动作不得混为一条；未说明的版本、镜像组成、存储介质和校验能力保持未知。
<!-- END PROMPT -->

<!--
调用节点：Node 2 hardware_and_network 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：区分产品硬件、数字模块、接口、网络边界、相邻设备与被动支撑件。
-->
<!-- PROMPT:asset_hardware_network -->
区分产品整机、嵌入式子系统、具有数字逻辑的模块、明确的物理或管理或调试接口、内部或外部网络和相邻设备。任何模块、交换或路由设备、接口转换设备都必须保留标准内置、选配、外置或BOM待确认限定；仅有配置或加固教程不能证明设备已交付。没有独立数字行为的被动支撑部件仅记录存在，不夸大为独立网络安全资产。
<!-- END PROMPT -->

<!--
调用节点：Node 2 external_services 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：提取外部服务及其数据关系、状态、授权和责任缺口。
-->
<!-- PROMPT:asset_external_services -->
分别提取云平台、第三方平台、远程维护、远程升级、时间、日志、目录等外部服务及其明确的数据关系、授权条件、默认状态和依赖。外部系统不是产品组件仍可作为相邻或受影响对象；不得自行判定RDPS、运营方、责任边界或断网降级行为。
<!-- END PROMPT -->

<!--
调用节点：Node 2 function_assets 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：按独立业务价值或安全价值提取功能簇。
-->
<!-- PROMPT:asset_functions -->
按具有独立业务价值或安全价值的功能簇提取：数据采集或转发、业务控制、设备配置管理、身份与权限、证书密钥、安全通信、安全启动或存储或更新、日志审计、时间同步、恢复出厂和远程维护。不要把菜单点击步骤、数据、协议端口或组件名称单独当成功能；保留默认关闭、授权和适用组件等条件。
<!-- END PROMPT -->

<!--
调用节点：Node 2 user_property_environment 字段事实抽取。
调用代码：tools/retrieval_profiles.py，最终由 nodes/field_extractor.py 调用。
作用：只提取材料支持的人员、财产、业务运行、环境和公共利益影响对象。
-->
<!-- PROMPT:asset_impacts -->
提取因产品网络安全受损而可能受影响的人员、相邻业务设备或系统、业务运行或连续性、人身和财产对象。环境、动物、公共利益等只有在材料直接支持时才记录；不要把安全建议、机柜或网络安全设备本身误写成受影响资产。
<!-- END PROMPT -->
