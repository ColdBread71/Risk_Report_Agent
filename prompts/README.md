# 生产 Prompt 审阅入口

本目录保存工作流实际发送给文本模型的 Prompt。每个 Prompt 正文前都有业务审阅注释，说明调用节点、调用代码、输入和作用；注释位于 `PROMPT` 标记之外，不会发送给模型。

| 文件 | 节点与用途 | 调用代码 |
|---|---|---|
| `field_fact_extraction.md` | Node 0–2 共用的字段事实抽取 | `nodes/field_extractor.py` |
| `retrieval_guidance.md` | 注入字段事实 Prompt 的各字段专用整理要求 | `tools/retrieval_profiles.py` → `nodes/field_extractor.py` |
| `node0_scope.md` | Node 0 范围直接生成与字段事实综合 | `nodes/context_builder.py` |
| `node1_context.md` | Node 1 产品上下文直接生成与四段综合 | `nodes/context_builder.py` |
| `node2_assets.md` | Node 2 资产直接生成、三段综合与资产—功能映射 | `nodes/asset_threat_modeler.py` |
| `node3_threats.md` | Node 3 STRIDE 威胁生成 | `nodes/asset_threat_modeler.py` |

`tools/retrieval_profiles.py` 保存检索查询、容量和定向锚点。这些内容决定给字段事实 Prompt 提供哪些证据，但本身不发送给文本模型；发送给文本模型的字段整理要求已放在`retrieval_guidance.md`。生产 Prompt 和检索规则均受 `tests/test_rule_generality.py` 的参考项目专有词扫描约束。

编辑规则：

1. 只修改 `<!-- PROMPT:name -->` 与 `<!-- END PROMPT -->` 之间的正文，才能改变模型输入。
2. 保留 `{json_schema}`、`{sample_input}` 等运行时占位符。
3. 不写入任何客户项目的产品名、型号、专有平台、专用组件、协议、接口、端口或当前结果数量。
4. 示例使用“产品A”“模块A”“外部平台”等中性名称。
