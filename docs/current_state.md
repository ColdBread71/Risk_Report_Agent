# 当前状态

更新：2026-09-18。日常入口：[docs/README.md](README.md)。业务权威仅为根目录 CRA_TARA_workflow_prEN40000.md。

## 当前目标

先得到可供业务同事审阅的 Node0–2：产品范围、产品理解、尽量完整的资产及保护目标。v6 已完成首次整轮评审；下一版按 Node0 → Node1 → Node2 分阶段修改、运行和检查，每个节点只生成一次正常结果，再做一次完整独立对比。不使用模型自评循环决定是否重跑。

## 实际产物

- 旧整轮：output/a24-rag-qwenplus-v4-zh/report.json 和 report.xlsx。证据包 v1，4 个结构化功能、3 个组件、12 条通信、7 项资产、13 项目标。未通过业务评审。
- 较新单节点：output/node0-v5-qwenplus-20260914-01/。已真实运行，scope v5 / field prompt 2.2 / profile 1.1，证据包 v2；Node0 completed，checked_usable=false。不是整轮，不可与旧 v4 拼接。
- 当前整轮：output/emu-node012-v6/。Node0–2 已完成并停在资产人工审阅点；独立评审发现 5 组关键问题，详见 docs/review/emu-node012-v6/review.md。
- 真实原材料：legacy_baseline/Project/阳光EMU项目。根目录目前没有Project。

## 当前实现

- main.py 默认 --mode assets；独立 Node0 → Node1 → Node2 → 人工审阅点。没有资产批准就不进入Node3。
- PDF解析、证据包、RAG索引及20个字段提取主题已存在。RAG模式允许Node2引用本节点检索事实及合法上游证据；静态模式只复用上游证据。
- 整轮运行继续输出 output/<run-id>/report.json、report.xlsx、run_manifest.json，且要求新 run-id。单节点现可在已有版本目录依次追加 node0、node1、node2 JSON/Excel，不覆盖原 report。
- 整轮字段事实保存在 project_artifacts/<project_id>/runs/<run-id>/field_facts/；分步运行按 `stages/node_<n>/field_facts/` 隔离，不增加跨版本缓存复用。
- 整轮使用 run_manifest；分步运行使用独立 stage_manifest，逐节点记录代码/规则版本、模型、证据包、产物哈希和上游哈希。旧版无法追补真实代码指纹。
- Excel有自动换行、按中英文长度估算的显式行高；超长内容仍受Excel单行高度限制。
- 单节点 `--node` 已改为同目录阶段链路：Node1 读取 node0，Node2 读取 node1，并校验身份和哈希。Node0 模型自评已移除；Node1/2 仍有既有模型完整性字段和有界校验重试，不视为人工验收。
- Embedding 已形成独立基础设施边界：OpenAI兼容客户端显式设置60秒超时并关闭SDK隐藏重试，provider只对超时、连接、429及指定5xx做最多3次可见尝试；确定性错误立即失败。查询向量按端点、模型、维度和query指纹持久化在对应FAISS索引的`query_embeddings/`下，字段`refresh`不再强制重复远程embedding。
- 2026-09-18真实最小探针仅调用embedding、未运行节点或文本LLM：Node2七类固定query全部首轮成功，远程耗时约0.17–0.97秒；同query缓存复用约0.001秒。这支持v7超时属于瞬时外部延迟而非特定query的确定性错误，但不代表服务以后不会再次波动。
- 字段事实Prompt/契约版本为`2.5`，Node1上下文规则为`v7.4`。仅communications和components事实增加受控attributes：通信保存端点、协议、端口、接口、方向语义、启用状态、认证、加密和数据；组件保存名称、类型、范围状态和条件。下游优先使用这些结构化值，旧自然语言解析仅作为历史缓存兼容回退。其余字段、节点、Excel和状态结构未扩展。
- Node2资产规则为`v2.7`。分段结果按资产、目标和功能关系逐项校验：非法子项只隔离自身，合法同段资产继续保留；`system`等含糊类型或错位状态不再被代码猜成另一种业务含义。系统生成简短拒绝原因并把分段标为PARTIAL。Node1结构化通信进入Node2候选上下文时保留端点、方向、启用状态、认证、加密和交换数据；组件类型、范围状态和条件也保持不变，但候选上下文仍不能替代Node2直接事实证据。
- Node2状态现区分四类结果：PASS为`asset_identification_completed`；有资产但仍需业务确认的PARTIAL为`asset_identification_partial_draft`，可导出并进入人工复核；必需字段或分段技术失败为`asset_identification_technical_incomplete`，只保留诊断快照；无有效清单为failed。路由、正式审核包和阶段清单使用同一组状态定义。
- v8首次整轮运行在Node1组件字段失败：模型连续输出空`conditions`，而可选属性Schema与后置非空校验矛盾。现将null/空列表规范化为“未提供”，非空值仍严格校验。新增`--reuse-failed-run`，只读复用另一失败整轮中项目、证据包、模式和完整字段指纹均匹配的检查点；源运行不修改，新运行仍使用新run-id。v8现有9个检查点已全部通过当前指纹核对。

## 本次整理

旧输出和 optimization_results 已核对归档；清理后保留的 v4、Node0 v5 及随后生成的 v6 均在 output。原始业务 JSON 未修改，旧 Excel 只调整排版。归档：archive/before_cleanup_20260914.zip。
没有删客户资料、证据包、解析结果、索引、业务指导，也没有推倒重构生成代码。
新增独立对比prompt：docs/review/compare_prompt.md。初步盘点：docs/review/20260914-baseline/review.md，不是完整业务对比。

## 下一步

首轮完整评审已完成：docs/review/emu-node012-v6/review.md，结论为修复明确关键问题后再交业务同事评审。开发计划见 docs/review/emu-node012-v6/optimization_plan.md。
v7回退后的四步通用修复已完成离线收口。v8首次验证暴露的可选属性契约冲突及失败运行复用问题也已修复。下一步以新run-id复用v8中9个匹配检查点继续一次Node0–2验证，核对技术完整性、主要资产族、通信保真和状态一致性；通过后转入第二项目。
Node3尚未运行；Node4–8尚未实现为可执行流程。方法量表仍待后续确认，当前不是完整TARA报告。
