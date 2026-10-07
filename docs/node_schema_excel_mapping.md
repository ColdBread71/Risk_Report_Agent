# Node Schema 与 Excel 字段映射（当前实现）

第一次阅读先看 [docs/README.md](README.md)。本文用于按需查字段，不是必须学完的教程。更新：2026-09-14。

版本：v1.5  
基线日期：2026-09-17  
适用范围：当前已实现的 Node [0]-[3]；重点用于审阅 Node [0]-[2] 第一版成果。

## 1. 先理解三层数据

| 层次 | 用途 | 是否是正式业务结果 | 保存位置 |
|---|---|---:|---|
| RAG 字段事实 | 针对一个小主题检索少量原文块，再提炼原子事实、未知项和矛盾 | 否，是 Node 的内部输入 | `project_artifacts/<项目>/runs/<版本>/field_facts/node_x/*.json` |
| Pydantic Node Schema | 把多批字段事实综合成一个经过结构、语义和证据校验的 Node 结果 | 是 | `output/<版本>/report.json` |
| Excel 审阅视图 | 把正式 Schema 中适合人工检查的字段排成表格 | 是，但不是全部 JSON 字段的完整镜像 | `output/<版本>/report.xlsx` |

当前 RAG 路径不是“一个小批次生成一列 Excel”。它先完成多个窄主题事实抽取，再由一次 Node 综合请求生成正式 Schema。只有通过校验的 Node 结果才进入 Excel。

`report.xlsx` 是资产批准前的审阅包，不是完整 TARA 报告。当前完整报告导出器只覆盖到 Node [3]；Node [4]-[8] 尚未进入可执行图，因此本文不为它们虚构字段或 Excel 映射。

### 1.1 语言规则

| 内容类型 | Excel 显示规则 |
|---|---|
| Sheet 名、标题、字段名、说明 | 使用简体中文 |
| 布尔值、完整性结论、常见资产/目标/功能类别 | 在展示层映射为中文 |
| 新生成的分析性叙述 | 使用简体中文 |
| 产品名、型号、协议、法规/标准编号、稳定 ID | 保留正式写法，不强制翻译 |
| `EvidenceRef.quote` 客户原文 | 保留原始语言，不翻译、不改写 |

旧 JSON 中已经生成的英文分析内容不会由展示层擅自翻译；重新执行 Node 综合后才会按新的中文生成规则输出。事后机器翻译可能改变含义或证据对应关系，因此不作为正式数据链路。

## 2. 当前工作流与 Excel 工作表

| 顺序 | 流程位置 | 正式输出 | Excel 工作表 |
|---:|---|---|---|
| 1 | Node [0] | `ScopeStatement` | `Node0 范围定界` |
| 2 | Node [1] | `ProductContext` | `Node1 产品概况`、`Node1 产品功能`、`Node1 组件清单`、`Node1 通信矩阵` |
| 3 | Node [2] | `AssetIdentificationResult` 拆入 State | `Node2 资产与目标` |
| 4 | Node [3] | `ThreatAssessment` | `Node3 STRIDE 威胁`；资产审阅模式不生成 |
| 5 | 支撑信息 | `RiskMethodology`、`RiskAcceptanceCriteria`、节点结论 | `方法与准则` |
| 6 | 支撑信息 | 各 Node 的 `EvidenceRef` | `证据追溯`，固定放在最后 |

所有工作表按“业务生成结果在前、方法和证据在后”排列。表格中的“仅 JSON”表示 Schema 中真实存在，但当前 Excel 审阅视图没有直接展示；这不代表字段未生成。

Excel 不允许 Sheet 名包含 `[` 或 `]`，所以实际页签使用 `Node0`、`Node1`、`Node2`、`Node3`。下文详细映射中的 `[0]`、`[1]`、`[2]`、`[3]` 是相同 Node 的业务简写，箭头末端的中文字段名均为 Excel 中的实际名称。

## 3. Node [0]：法律与产品范围

### 3.1 产品基础档案

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `scope.product_name` | 客户材料中的正式产品名称，不允许推测或改名 | `[0] 范围定界` → `产品基础` → `产品名称` |
| `scope.product_version` | 产品、硬件或软件版本；材料未给出时为 null | `[0] 范围定界` → `产品基础` → `产品版本`；null 显示“待产品/BOM确认” |

### 3.2 CRA 身份与合规属性

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `scope.classification.is_pde` | 是否属于 CRA 的 product with digital elements；未完成法律适用性判断时为 null | `[0] 范围定界` → `CRA 属性` → `是否属于含数字元素产品（PDE）`；显示是/否/待确认 |
| `scope.classification.classification` | `Default`、`Important` 或 `Critical`；依据不足时为 null | `[0] 范围定界` → `CRA 属性` → `产品分类`；null 显示“待法规/业务确认” |
| `scope.classification.has_rdps` | 是/否/待确认；材料不足时为null，不等于否 | `[0] 范围定界` → `CRA 属性` → `是否包含远程数据处理方案（RDPS）` |
| `scope.classification.rdps_description` | RDPS 运营方、交换数据、信任/认证关系和降级模式 | `[0] 范围定界` → `CRA 属性` → `远程数据处理方案说明` |
| `scope.classification.applicable_annex` | 有合格法律依据时记录适用的 CRA Annex III/IV；未判断时为 null | `[0] 范围定界` → `CRA 属性` → `适用附件`；null 显示“待法规/业务确认” |
| `scope.classification.overlapping_regulations` | 叠加适用的其他欧盟法规；null 表示未评估，空列表表示已确认没有 | `[0] 范围定界` → `CRA 属性` → `可能叠加的其他法规`；null 显示“待法规/业务确认” |

### 3.3 评估范围边界

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `scope.scope_description` | 本次评估覆盖的产品、数字组件、RDPS 和边界摘要 | `[0] 范围定界` → `评估边界` → `范围说明` |
| `scope.in_scope_components` | 纳入评估的组件、接口、服务和依赖 | `[0] 范围定界` → `评估边界` → `范围内组件、接口与服务` |
| `scope.conditional_scope_components` | 选配、合同或启用条件决定的范围项 | `[0] 范围定界` → `评估边界` → `条件适用的组件、接口与服务` |
| `scope.out_of_scope_components` | 排除项及已知排除理由 | `[0] 范围定界` → `评估边界` → `范围外项目及理由` |

### 3.4 法律依据与假设

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `scope.assumptions` | 界定范围所需、仍待客户或法规同事确认的问题/前提；生成时最多5项 | `[0] 范围定界` → `依据与假设` → `待确认问题/假设` |
| `scope.legal_basis[]` | 结构化法规/标准依据：regulation、article、clause、annex 等；客户手册不能代替法律依据 | `[0] 范围定界` → `依据与假设` → `法律与标准依据`；空列表显示“待法规依据确认” |

### 3.5 结论、完整性与证据

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| 展示层派生值（不写回 Schema） | 根据产品版本、PDE、分类、RDPS、附件、叠加法规、法律依据和条件组件的未决状态，提示范围能否冻结 | `[0] 范围定界` → `范围状态` → `Node0 范围冻结状态`、`阻塞冻结的待确认项` |
| `scope.evidence[]` | 支撑范围结论的真实文件、页码、章节、块和原文引用 | `证据追溯` |

Node [0] 当前通过 5 个内部检索主题准备事实：`product_identity`、`intended_purpose`、`scope_boundary`、`remote_services`、`classification_inputs`。它们不直接对应 Excel 列。

## 4. Node [1]：产品上下文、方法和接受准则

### 4.1 产品标识与 IPRFU

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `product_context.product_name` | 与 Node [0] 保持一致的正式产品名 | `[1] 产品概况` → `产品基础` → `产品名称` |
| `product_context.product_version` | 产品版本；材料未给出时为空 | `[1] 产品概况` → `产品基础` → `产品版本` |
| `iprfu.intended_purpose` | 制造商声明的预期用途 | `[1] 产品概况` → `预期用途与可预见使用` → `预期用途` |
| `iprfu.reasonably_foreseeable_use` | 合理可预见使用或误用情景 | `[1] 产品概况` → `预期用途与可预见使用` → `合理可预见使用或误用` |
| `iprfu.health_safety_considerations` | 网络事件对健康、安全、财产、环境或公共利益的影响 | `[1] 产品概况` → `预期用途与可预见使用` → `健康与安全考虑` |
| `iprfu.accessibility_considerations` | 安全安装、认证、操作、维护或退役中的可访问性约束 | `[1] 产品概况` → `预期用途与可预见使用` → `可访问性考虑` |
| `iprfu.support_period` | 客户材料明确给出的支持期限或停止支持信息 | `[1] 产品概况` → `预期用途与可预见使用` → `支持期限` |
| `iprfu.evidence[]` | 上述结论的证据 | `证据追溯` |

### 4.2 用户描述

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `user_description.user_types` | 最终用户、管理员、维护者、安装者、集成商等 | `[1] 产品概况` → `用户` → `用户类型` |
| `user_description.experience_level` | 预期网络安全知识、培训与操作能力 | `[1] 产品概况` → `用户` → `经验与能力` |
| `user_description.vulnerable_groups` | 有依据的弱势或无障碍相关群体 | `[1] 产品概况` → `用户` → `弱势或无障碍相关群体` |
| `user_description.is_component` | 产品是否作为组件集成到其他产品/系统 | `[1] 产品概况` → `用户` → `是否作为组件集成` |
| `user_description.rdps_dependence` | 用户或集成商对 RDPS 的依赖 | `[1] 产品概况` → `用户` → `用户对远程服务的依赖` |
| `user_description.responsibilities` | 客户材料明确分配给用户、运营方或集成商的责任 | `[1] 产品概况` → `用户` → `用户、运营方或集成商责任` |
| `user_description.evidence[]` | 上述结论的证据 | `证据追溯` |

### 4.3 运行环境

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `operational_environment.description` | 产品部署和运行方式的总体描述 | `[1] 产品概况` → `运行环境` → `总体说明` |
| `networks` | 本地、工业、云、蜂窝、无线或互联网网络 | `[1] 产品概况` → `运行环境` → `相关网络` |
| `integrated_systems` | 与产品集成的设备、平台和服务 | `[1] 产品概况` → `运行环境` → `集成系统` |
| `physical_environment` | 室内外、环境暴露和物理访问条件 | `[1] 产品概况` → `运行环境` → `物理环境` |
| `network_boundaries` | 网络或信任边界及其接口/控制 | `[1] 产品概况` → `运行环境` → `网络与信任边界` |
| `constraints` | 连接性、可用性、安全、监管或第三方约束 | `[1] 产品概况` → `运行环境` → `运行约束` |
| `rdps_dependency_map` | RDPS 运营、数据交换、认证、可用性和降级模式摘要 | `[1] 产品概况` → `运行环境` → `远程服务依赖关系` |
| `evidence[]` | 上述结论的证据 | `证据追溯` |

### 4.4 产品功能

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `functions[].function_id` | 当前上下文内唯一的功能 ID | `[1] 产品功能` → `功能编号` |
| `name` | 功能名称 | `[1] 产品功能` → `功能名称` |
| `function_category` | 数据采集、通信、配置、认证、更新、日志等类别 | `[1] 产品功能` → `功能类别` |
| `is_security_function` | 是否直接提供或强制执行网络安全保护 | `[1] 产品功能` → `是否安全功能` |
| `interfaces` | 该功能使用或暴露的接口 | `[1] 产品功能` → `相关接口` |
| `rdps_dependencies` | 该功能依赖的远程服务 | `[1] 产品功能` → `远程服务依赖` |
| `description` | 可观察行为、输入输出、用户和组件 | `[1] 产品功能` → `功能说明` |
| `limitations` | 已知限制、排除和使用条件 | `[1] 产品功能` → `限制与条件` |
| `evidence[]` | 功能证据 | `证据追溯` |

### 4.5 组件清单

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `component_inventory.entries[].component_id` | 当前上下文内唯一的组件 ID | `[1] 组件清单` → `组件编号` |
| `name` | 组件名称 | `[1] 组件清单` → `组件名称` |
| `component_type` | 硬件、固件、软件、服务、库、操作系统等类型 | `[1] 组件清单` → `组件类型` |
| `role` | 组件在产品/安全功能中的作用 | `[1] 组件清单` → `作用` |
| `interfaces` | 与 TOE 或外部系统相连的接口 | `[1] 组件清单` → `相关接口` |
| `version`、`supplier`、`is_third_party`、`support_period` | 版本、供应方、第三方属性和支持期限；第三方责任没有直接证据时 `is_third_party=null`，产品边界外不自动等于第三方 | `[1] 组件清单` → `版本或型号`、`供应方或运营方`、`是否第三方`、`支持期限` |
| `evidence[]` | 组件证据 | `证据追溯` |
| `component_inventory.completeness_notes` | SBOM、版本、供应方等清单缺口 | `[1] 产品概况` → `清单完整性` → `组件清单说明` |

### 4.6 通信矩阵

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `communication_matrix.entries[].flow_id` | 唯一通信流 ID | `[1] 通信矩阵` → `通信流编号` |
| `source`、`destination` | 通信源与目的端 | `[1] 通信矩阵` → `源端`、`目的端` |
| `direction` | 相对产品的连接方向；只有文档端点或连接角色足以证明时才填写 | `[1] 通信矩阵` → `连接方向` |
| `direction_basis` | 方向依据：文档端点、连接发起、监听/端口暴露、业务数据流或未知；监听关系不自动等于业务方向 | `[1] 通信矩阵` → `方向依据` |
| `business_data_direction` | 业务载荷流向：流向产品、由产品发出、双向或未知；与连接方向分开记录 | `[1] 通信矩阵` → `业务数据方向` |
| `activation_status`、`conditions` | 已启用、默认关闭、条件启用或未知，以及对应配置/部署条件；能力存在不等于当前配置已启用 | `[1] 通信矩阵` → `启用状态`、`适用条件` |
| `interface` | Ethernet、RS485、USB、蜂窝、API、Web 等接口 | `[1] 通信矩阵` → `接口` |
| `protocol`、`port` | 有证据的协议与端口 | `[1] 通信矩阵` → `协议`、`端口` |
| `data_exchanged` | 交换的数据、命令、凭据、配置、遥测或更新 | `[1] 通信矩阵` → `交换数据` |
| `encryption` | 材料明确说明的加密机制和范围 | `[1] 通信矩阵` → `加密机制` |
| `authentication`、`security_notes` | 认证机制与通信安全观察 | `[1] 通信矩阵` → `认证机制`、`安全说明` |
| `evidence[]` | 通信流证据 | `证据追溯` |
| `communication_matrix.completeness_notes` | 缺失图纸、方向、协议等覆盖限制 | `[1] 产品概况` → `清单完整性` → `通信矩阵说明` |

### 4.7 汇总、完整性与证据

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `existing_security_functions` | 客户材料已经证明存在的安全功能摘要 | `[1] 产品概况` → `已有能力` → `已有安全功能` |
| `existing_non_security_functions` | 已证明存在的普通产品功能摘要 | `[1] 产品概况` → `已有能力` → `已有非安全功能` |
| `rdps_dependencies` | 全部 RDPS 依赖的汇总 | `[1] 产品概况` → `已有能力` → `远程服务依赖汇总` |
| `assessment` | Product Context 完整性判决 | `[1] 产品概况` → `完整性结论` → `评估结论` |
| `assessment_notes` | Product Context 缺口和待确认事项 | `[1] 产品概况` → `完整性结论` → `结论说明` |
| `product_context.evidence[]` | Product Context 聚合层证据 | `证据追溯` |

### 4.8 固定风险方法

`RiskMethodology` 由 `core/policy.py` 确定性生成，不由模型自由决定。

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `policy_version` | 当前方法规则版本 | `方法与准则` → `固定风险方法` → `规则版本` |
| `threat_modelling_method` | 固定为 STRIDE | `方法与准则` → `固定风险方法` → `威胁建模方法` |
| `risk_estimation_method` | 固定为 DREAD | `方法与准则` → `固定风险方法` → `风险估计方法` |
| `statutory_risk_factors`、`risk_combination_rule` | 法定因子 likelihood/magnitude 与组合规则 | `方法与准则` → `固定风险方法` → `法定风险因子`、`风险组合规则` |
| `likelihood_dimensions`、`magnitude_dimensions` | DREAD 五维如何分配到两类法定因子 | `方法与准则` → `固定风险方法` → `可能性维度`、`影响程度维度` |
| `damage_required_coverage` | Damage 必须考虑的安全、邻接设备/网络和规模化影响 | `方法与准则` → `固定风险方法` → `损害评估必查范围` |
| `risk_acceptance_rule`、`treatment_priority` | 默认不接受现存风险及 Avoid→Mitigate→Accept→Transfer 顺序 | `方法与准则` → `固定风险方法` → `风险接受规则`、`风险处置优先级` |
| `node_4_scale_status`、`source_references` | Node [4] 量表是否冻结及方法依据 | `方法与准则` → `固定风险方法` → `Node [4] 量表状态`、`方法依据` |

### 4.9 产品特定风险接受准则

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `policy_version` | 必须与固定方法版本一致 | `方法与准则` → `产品特定接受准则` → `规则版本` |
| `regulatory_factors` | 与本产品相关的监管因素 | `方法与准则` → `产品特定接受准则` → `监管因素` |
| `contractual_factors` | 合同、客户或供应链责任因素；未知时为空 | `方法与准则` → `产品特定接受准则` → `合同与供应链因素` |
| `risk_nature_factors` | 已知风险性质 | `方法与准则` → `产品特定接受准则` → `风险性质因素` |
| `user_factors` | 用户类型和能力因素 | `方法与准则` → `产品特定接受准则` → `用户因素` |
| `product_factors` | 产品用途、环境、功能和依赖因素 | `方法与准则` → `产品特定接受准则` → `产品因素` |
| `state_of_art_factors` | 有依据的技术现状和社会价值因素 | `方法与准则` → `产品特定接受准则` → `技术现状与社会价值因素` |
| `aggregate_risk_considered` | 是否考虑风险聚合；必须为 true | `方法与准则` → `产品特定接受准则` → `是否考虑聚合风险` |
| `evidence[]` | 只能复用 Node [0]/[1] 已验证证据 | `证据追溯` |

Node [1] 当前通过 8 个内部检索主题准备事实：`iprfu`、`users`、`operational_environment`、`functions`、`components`、`communications`、`security_functions`、`rdps_dependencies`。它们不直接对应 Excel 列。

## 5. Node [2]：资产与网络安全目标

### 5.1 资产

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `assets[].asset_id` | 当前资产清单内唯一且稳定的 `ASSET-xxx` | `[2] 资产与目标` → `资产编号` |
| `name` | 被保护价值对象的名称 | `[2] 资产与目标` → `资产名称` |
| `asset_type` | data、credential、software、hardware、network、service、function、user、property、environment、public_interest 或 other | `[2] 资产与目标` → `资产类型` |
| `status` | confirmed、conditional、external_affected 或 needs_confirmation；默认关闭不等于条件资产；这是工程审阅状态，不是风险评级 | `[2] 资产与目标` → `资产状态`；四种状态使用浅色提示并可直接筛选 |
| `related_function_ids[]` | 兼容索引：与该资产存在直接关系的Node1功能编号；有类型化关系时由 `function_relationships[]` 派生 | `[2] 资产与目标` → `关联功能编号`、`关联功能名称` |
| `function_relationships[]` | 类型化直接关系，包含 `function_id`、`relationship_type` 和简短 `rationale`；关系类型限定为读取、产生、修改、传输、用于认证、实现、保护、直接依赖或受影响 | `[2] 资产与目标` → `功能关系与依据` |
| `location` | 资产存储、处理、运行或暴露的位置 | `[2] 资产与目标` → `所在位置` |
| `value` | 资产价值或受损后果 | `[2] 资产与目标` → `资产价值或受损后果` |
| `description` | 资产的边界、作用和受影响对象 | `[2] 资产与目标` → `资产说明` |
| `evidence[]` | 资产存在及其属性的证据 | `证据追溯` |

### 5.2 每项资产的网络安全目标

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `related_objectives[].objective_id` | 全资产范围唯一且稳定的 `OBJ-xxx` | `[2] 资产与目标` → `目标编号` |
| `category` | 固定为 confidentiality、integrity、availability、authenticity、accountability、data_minimization 之一 | `[2] 资产与目标` → `目标类别` |
| `basis` | 目标必要性的依据：explicit_requirement、asset_value_or_consequence、legal_or_standard、analyst_minimum 或 unknown；不表示控制已实现 | `[2] 资产与目标` → `目标依据类型` |
| `status` | supported 表示目标必要性有可追溯依据；needs_confirmation 表示分析最低判断、依据未知或证据不足 | `[2] 资产与目标` → `目标支持状态` |
| `description` | 对该资产需要实现的、可验证的保护结果 | `[2] 资产与目标` → `网络安全目标` |
| `legal_basis[]` | 该目标对应的法规或标准依据 | `[2] 资产与目标` → `目标法律与标准依据` |
| `evidence[]` | 该目标的事实证据 | `证据追溯` |

同一资产有多个目标时，Excel 仍为每个“资产—目标”关系各写一行；资产编号至资产说明这 10 列在相邻目标行中纵向合并，目标编号、类别、依据类型、支持状态、保护结果及法律/标准依据保持逐行独立。JSON 中每项资产仍只保存一次，Excel 的合并仅用于阅读，不改变数据关系。

### 5.3 节点结论与审批状态

| State/Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `asset_assessment` | 资产及目标覆盖完整性：PASS/PARTIAL/FAIL | `方法与准则` → `Node [2] 结论` → `资产识别完整性` |
| `asset_notes` | 缺失类别、证据不足和待复核内容 | `方法与准则` → `Node [2] 结论` → `资产识别说明` |
| `asset_review_approved` | 人工是否明确批准完整资产清单 | `方法与准则` → `Node [2] 人工审批` → `是否已批准` |
| `asset_review_notes` | 审批人的备注 | `方法与准则` → `Node [2] 人工审批` → `审批备注` |

正式 Node0–2 审核 JSON 还包含 `review_summary`，记录唯一资产数、目标数、supported/needs_confirmation 目标数、类型化功能关系数以及 conditional、external_affected、needs_confirmation 资产数。它是便于复核的确定性汇总，不是新的业务判断。

审核包发布前会自动重新加载 JSON Schema 和 Excel，核对必需工作表、Node2 表头、资产/目标 ID 顺序、汇总计数、功能 ID 引用、类型化关系与兼容索引、目标证据是否属于父资产，以及 supported 目标是否具备相应依据。任一不一致都会使导出失败并清理临时文件，不会用不一致产物覆盖正式 JSON/Excel。

Node [2] 当前通过 7 个内部检索主题准备事实：`data_assets`、`credentials_and_keys`、`software_and_configuration`、`hardware_and_network`、`external_services`、`function_assets`、`user_property_environment`。这些是为了防止遗漏而设置的工程检索主题，不是 CRA 规定的固定七类资产，也不是七张业务表；最终资产按价值、生命周期、责任边界和保护目标决定是否合并或拆分。

最终综合分为三个内部缓存段：数据/凭据/软件，硬件/网络/外部服务，功能/用户/财产及其他受影响对象。三个分段使用统一 Schema，完成后由代码重新分配全局 `ASSET-xxx` 与 `OBJ-xxx`。同名候选只有在对象类型、范围状态一致、证据相交且说明、位置和价值不冲突时才确定性合并；其余同名候选保留并提示人工确认。随后用一次独立的精简综合只校正现有资产与Node1功能的多对多关系；它不能新增、删除、合并或改写资产。最终仍写入同一张 `Node2 资产与目标` 表。单个分段或功能映射技术失败只使总体结论降为 PARTIAL，并保留其他已经形成的资产和临时关系。

合并后会执行一次不调用模型的保守纠错：只有父资产自身的 `evidence[]` 能证明资产存在，目标证据或其他嵌套证据不能反向补足资产证据；无直接资产证据的候选降为`needs_confirmation`，并将无依据的描述、价值和位置改为中性待确认内容。产品边界外的人员和财产等对象标为`external_affected`；明确为公开认证材料的对象不默认生成保密目标或借未单列私钥描述自身价值。所有目标描述按类别规范为单一保护结果，删除攻击路径、故障链和具体控制实现断言；同一类别因此产生的重复目标会合并。

目标的 `supported` 只表示“为什么需要该保护结果”有可追溯依据，不表示加密、认证、防重放、不可删除、回滚保护、清除范围或其他控制已经存在或有效。目标证据必须同时属于父资产证据：explicit_requirement需要直接要求证据，asset_value_or_consequence还要求资产价值或后果字段有直接支持，legal_or_standard还要求证据原文包含法规或标准名称及具体条款定位。analyst_minimum、unknown、范围待确认或证据不足的目标一律保留为`needs_confirmation`。无法由原文定位支持的 `legal_basis` 会被清除。资产状态不再因为描述中提到某个选配子组件而整体改写，选配/BOM状态应来自该资产自身的范围事实和综合判断。纠错只减少错误断言，不会因缺少材料阻止Excel生成或触发模型反复运行。

若模型识别出资产但没有给出保护目标，合并代码不会删除资产或终止整个Node2，而是补充一项 `basis=analyst_minimum`、`status=needs_confirmation` 的中性最低目标，并把总体结论保持为PARTIAL。普通秘密凭据默认使用保密性，明确的公开认证材料使用真实性；该目标是供人工继续处理的占位判断，不表示材料已经证明完整CIA要求。

资产数不要求大于或等于Node1功能数。细粒度功能可以共同映射到一个功能资产，同一功能也可以关联凭据、数据、软件、硬件、接口和外部对象等多个资产。独立映射要求关系类型和简短依据，不会为满足覆盖率硬塞编号；没有可靠关系的资产可以留空待人工确认。功能资产只接受 `implements`，用户、财产、环境和公共利益等受影响对象只接受 `affects`。未关联任何资产或未由功能资产覆盖的Node1功能会按编号和名称写入Node2说明并使结论为PARTIAL，不会因此重试或阻止Excel生成。

## 6. Node [3]：STRIDE 威胁场景（当前已实现但本轮未运行）

### 6.1 威胁场景

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `threats[].threat_id` | 唯一且稳定的 `THREAT-xxx` | `[3] STRIDE 威胁` → `威胁编号` |
| `stride_category` | STRIDE 六类之一 | `[3] STRIDE 威胁` → `STRIDE 类别` |
| `title` | 威胁简短名称 | `[3] STRIDE 威胁` → `威胁名称` |
| `targeted_assets[]` | 目标资产；必须引用已批准的完整资产对象 | `[3] STRIDE 威胁` → `目标资产编号` |
| `compromised_objectives[]` | 被破坏目标；必须属于已批准资产 | `[3] STRIDE 威胁` → `受损安全目标编号` |
| `cause_of_compromise` | 目标被破坏的原因 | `[3] STRIDE 威胁` → `受损原因` |
| `threat_actor`、`attack_path` | 威胁来源、前提和攻击路径 | `[3] STRIDE 威胁` → `威胁来源或攻击者`、`攻击路径或前提` |
| `known_vulnerabilities` | 有依据的已知可利用漏洞 | `[3] STRIDE 威胁` → `已知可利用漏洞` |
| `description` | 完整威胁场景描述 | `[3] STRIDE 威胁` → `威胁场景说明` |
| `confidence` | 对场景的置信等级 | `[3] STRIDE 威胁` → `置信度` |
| `evidence[]` | 威胁场景证据 | `证据追溯` |

### 6.2 节点结论

| Schema 字段 | 业务含义 | Excel 对应 |
|---|---|---|
| `threat_assessment.assessment` | 已批准资产的威胁覆盖是否充分 | `方法与准则` → `Node [3] 结论` → `威胁覆盖完整性` |
| `threat_assessment.notes` | 覆盖缺口、未知路径和证据限制 | `方法与准则` → `Node [3] 结论` → `威胁建模说明` |
| `threat_assessment.scores` | 当前固定为空；DREAD 评分属于 Node [4] | 不导出 |

## 7. 证据追溯怎么读

| Excel 列 | 含义 |
|---|---|
| `证据编号` | 该条引用的标识，不等于资产或功能编号 |
| `用于哪些字段` | 引用被哪些 Schema 路径使用，例如 `assets[0].evidence[0]` |
| `文档编号` / `文本块编号` | 解析语料中的稳定文档和文本块标识 |
| `文件名` / `PDF 物理页码` / `文档印刷页码` / `章节路径` | 回到客户原始材料的位置锚点 |
| `原文引用` | 引用原文；新版无逐字引文时可补入规范块全文并注明。旧v4可能为空。全文存在不代表支持结论 |
| `证据等级` / `置信度` | 证据强度与置信等级 |
| `检索方式` / `是否人工确认` / `备注` | 检索来源、是否人工确认及补充说明 |

证据包和证据追溯表的作用不是生成额外 TARA 内容，而是让审阅者能回答：“这个结论来自哪份客户文件的哪一页、哪一节、哪段原文？”

## 8. 当前人工审批实际行为

`--mode assets` 是本阶段默认模式：图运行到 Node [2] 后触发 LangGraph interrupt，程序导出 `report.json/.xlsx` 并正常退出。它不会弹出窗口，也不会让你在 Excel 里点击按钮；日志中的“未批准资产”只是说明系统刻意没有伪造人工决定。

`--mode full` 才会在支持交互的终端中打印资产并等待键盘输入。只有输入完全一致的大写 `APPROVE`，再填写可选备注，图才会恢复并进入 Node [3]。输入其他内容视为拒绝；终端不可交互时保持在审批点。

当前 checkpointer 是内存型，审批并不是跨进程、跨天的持久待办，也没有 Streamlit/网页审批界面。可恢复审批和审阅 UI 属于后续产品化工作。

## 9. 本阶段建议审阅顺序

1. 先看 `[0] 范围定界`：产品身份、CRA 属性和评估边界是否正确。
2. 再看 `[1] 产品概况` 及三个明细表：用途、用户、环境、功能、组件和通信是否忠于材料。
3. 再看 `[2] 资产与目标`：资产粒度是否合适，每项资产是否真有价值，每项目标是否明确可验证。
4. 然后看 `方法与准则`：理解生成所遵循的方法、完整性结论和人工审批状态。
5. 最后用 `证据追溯` 抽查关键结论能否回到正确文件、页码、章节和原文。
6. 业务同事认可并修正 Node [0]-[2] 后，再明确批准资产并开始 Node [3] 真实运行。

## 10. 实现依据

本映射按当前代码编写：`schemas/legal.py`、`schemas/product.py`、`schemas/methodology.py`、`schemas/risk.py`、`schemas/threat.py`、`core/state.py`、`nodes/context_builder.py`、`nodes/asset_threat_modeler.py`、`core/exporter.py`、`main.py`及`prompts/`中的生产Prompt。业务流程顺序以根目录 `CRA_TARA_workflow_prEN40000.md` 为准。
## 11. 如何理解结果与排版

Node0没有模型自评和结论说明。Node1/2的完整性结论仍是模型生成，不是业务同事批准，也不是资产覆盖率。
Node2按资产与目标关系展开，一项资产有多个目标会显示多行；共同资产字段纵向合并，按唯一ASSET ID计数。
report.json是事实数据来源，Excel是阅读视图。每个版本的run_manifest.json用于区分整轮/单节点、代码、模型和证据包；排版更新不算新一轮生成。
运行中或失败时report是workflow_progress阶段快照；整轮成功时是node_0_2_review审核包。检查schema_version和状态，不仅看文件名。
Excel保留换行并写入显式行高，避免打开后仍是默认行高。超长原文受Excel单行约409磅上限限制，必要时从编辑栏或JSON/PDF读完整文本；不通过删减内容换取好看。
