# Trace 表 — 只保留边界和映射主线

## 0. 四层边界

| 层 | 作用 | 进 State | 进 Excel | 备注 |
|---|---|---|---|---|
| Schema | 只定义数据结构和校验 | 是，作为阶段产物 | 由 Exporter 选取 | 不关心表头 |
| State | LangGraph 运行时容器 | 是 | 终态会被导出 | 只放 schema 实例 + 流程控制 |
| Params | 节点内部临时变量 | 否 | 否 | 阈值、中间评分、RAG 结果、原始 LLM 输出 |
| Exporter | 终态映射到 Excel | 否 | 是 | 负责表头、列顺序、拼接、格式 |
| Methodology | 规则常量/政策 | 否 | 仅被引用 | 存在于 `core/policy.py`，不是业务输出 |

## 1. 最终输出

| 最终文件 | Sheet | 来源层 | 状态 |
|---|---|---|---|
| TOE Context | TOE Context | Schema / State / Params → Exporter | 进行中 |
| TARA & Rational | TARA & Rational | Schema / State / Params → Exporter | 进行中 |
| Trace | 独立 sheet/文件 | AuditTrace / Evidence / node_history | 后续 |

## 1. 规则层

| 名称 | 位置 | 作用 |
|---|---|---|
| Methodology / policy | `core/policy.py` | 打分、接受准则、处置规则、阈值 |
| 法规/标准依据 | `docs/` + 证据来源 | 约束 workflow 与 exporter，但不作为输出 sheet |

## 2. TOE Context 的字段归属

| 区域 | 最终输出内容 | Schema 文件 | State 容器 | Params | 备注 |
|---|---|---|---|---|---|
| 产品基本信息 | 产品类型、型号、硬件版本、软件版本、版本号规则 | `legal.py`：`ScopeStatement`；`product.py`：`ProductContext` | `scope`、`product_context` | 可能有版本解析参数 | 当前可输出，仍需人工整理部分文本 |
| 目标用户 | 目标用户群体 | `product.py`：`UserDescription` | `product_context` | 无 | 已有 |
| 预期用途 | IPRFU、可预见使用 | `product.py`：`IPRFU` | `product_context` | 无 | 已有 |
| 通信环境 | 南北向环境说明 | `product.py`：`OperationalEnvironment`、`ArchitectureOverview` | `product_context` | 少量拼接参数 | 已有 |
| 通信矩阵 | 源设备/端口/目的设备/端口/协议/认证/加密/用途/等级 | **待建** `product.py`：`CommunicationMatrix` | `product_context` 或独立容器 | 无 | 当前最明显缺口 |
| 网络安全功能 | 功能场景清单 | `product.py`：`ProductFunction` + `existing_security_functions` | `product_context` | 无 | 已有 |
| 数字组件 | Logger/PID-ISO/IO板/PLC 等 | **待建** `product.py`：`ComponentInventory` | `product_context` 或独立容器 | 无 | 当前缺口 |
| 产品组成 | Component/Version/Description/Remarks | **待建** `product.py`：`ComponentInventory` | 同上 | 无 | 与数字组件同类 |

## 3. TARA & Rational 的字段归属

| 区域 | 最终输出内容 | 主要 schema | State 容器 | Params | 备注 |
|---|---|---|---|---|---|
| A-B | 影响的产品功能 / 功能描述 | `product.py`：`ProductFunction`、`ProductContext` | `product_context` | 拼接/归并参数 | 由产品上下文汇总 |
| C | 资产列表 | `product.py`：`Asset` | `assets` | 拼接参数 | 已有 |
| D-I | 六类网络安全属性 | `product.py`：`CybersecurityObjective` | `assets` + `threat_assessment` 前置数据 | bool 转换参数 | 由导出层转 `x` |
| J-N | STRIDE、损害场景、威胁场景、攻击路径、攻击向量 | `threat.py`：`ThreatScenario` | `threat_assessment` | 派生参数 | 已有主结构，向导出层拼接 |
| O-AA | DREAD 五维 + 可能性/严重性/风险值 | `threat.py`：`DreadScore` | `threat_assessment` | 评分公式、阈值 | 已有 |
| AB | 综合风险值 | `risk.py`：`EvaluatedRisk` + `RiskRegister`；`core/policy.py`：`WorkflowPolicy` | `risk_register` | policy 阈值 | 由规则层判定 |
| AC-AD | 处置决策 / 网络安全需求 | `treatment.py`：`RiskTreatmentDecision`、`SecureDesignMapping` | `treatment_register` | 控制映射参数 | 已有主结构，需求需要汇总 |
| AE-AR | 缓解后 DREAD 与综合风险值 | **待补** `treatment.py`：`residual_dread: DreadScore` | `treatment_register` | 重评公式、阈值 | 当前缺口 |
| AS | 62443-4-2 SL-2 要求 | `treatment.py`：`SecureDesignMapping` + `evidence.py`：`LegalBasis` | `treatment_register`、`audit_trace` | 条款拼接 | 导出层文本化 |
| AT | CRA Requirements mapping | `evidence.py`：`LegalBasis` | `audit_trace` | 条款号与引用 | 导出层文本化 |

## 4. 现在哪些是“最终输出”，哪些是“中间产物”

### 最终输出

- `TOE Context`：产品信息、用户、用途、环境、功能、组件。
- `TARA & Rational`：资产、威胁、DREAD、风险、处置、残余风险、标准映射。

### 中间产物

- 节点内部计算用的阈值、临时评分、检索结果、原始 LLM 输出。
- 这些只进 `Params`，不进 `State`，不进 Excel。

### State 中的内容

- `scope`
- `product_context`
- `assets`
- `acceptance_criteria`
- `threat_assessment`
- `risk_register`
- `treatment_register`
- `audit_trace`
- `report_summary`
- `metadata`、`node_history`、`review_requests`、`assessments`

## 5. 当前缺口

| 缺口 | 归属 | 说明 |
|---|---|---|
| `CommunicationMatrix` | TOE Context | 通信矩阵单独成型更清楚 |
| `ComponentInventory` | TOE Context | 数字组件与产品组成统一管理 |
| `residual_dread: DreadScore` | TARA & Rational | 缓解后五维评分目前缺 |
| 中文 `Field(title=...)` | 导出层 | 由 exporter 补，不进业务模型 |
| Trace 细化 | 未来 | 先保留最小溯源，后续再扩 |

## 6. 设计思路

业务概念 → 领域对象 → Pydantic 模型 → workflow state → exporter → Excel。

- `legal.py`：范围、分类、法规依据。
- `product.py`：产品上下文、功能、资产、目标用户。
- `threat.py`：威胁场景与 DREAD。
- `risk.py`：接受准则与风险判定。
- `treatment.py`：处置、残余风险、安全设计映射。
- `evidence.py`：证据、来源、法律依据。
- `reporting.py`：报告汇总和审计追踪。
- `workflow.py`：LangGraph state 和流程控制。

对应关系：

- `TOE Context`：`legal.py` + `product.py`。
- `TARA & Rational`：`product.py` + `threat.py` + `risk.py` + `treatment.py`。
- `Trace`：`evidence.py` + `reporting.py`。
- `Methodology / policy`：`core/policy.py`，不属于输出 sheet。

## 7. 以后看文件的顺序

1. 先看第 0 节，确认层边界。
2. 再看第 1 节，确认规则层。
3. 再看第 2、3 节，确认某个字段属于哪个输出区域。
4. 最后才翻 schema 文件。
