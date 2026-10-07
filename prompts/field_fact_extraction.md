# 字段级原子事实抽取

<!--
调用节点：Node 0、Node 1、Node 2 的所有字段抽取步骤。
调用代码：nodes/field_extractor.py::_field_prompt_template / extract_node_facts。
配套输入：tools/retrieval_profiles.py 生成的 RetrievalProfile、RAG 检索块、FieldExtractionResult Schema。
作用：把检索证据压缩为可追溯原子事实、未知项和冲突；不做节点级业务结论。
-->
<!-- PROMPT:field_fact -->
你正在为 CRA / prEN 40000 TARA 工作流的 {node_field} 提取原子事实。

【任务边界】
1. 只记录输入证据逐字支持的事实，不生成最终 Scope、ProductContext、资产、威胁、风险或控制。
2. 每条 fact 只表达一个事实，并列出直接支持它的真实 block_id。block_id 所在文本必须直接支持该事实，不得引用相邻章节标题代替正文或表格。最多输出 {max_facts} 条事实；证据未说明的必要信息写入 unknowns。
3. 不得创建输入中不存在的 block_id，不得根据行业惯例补全未知信息。
4. 原子事实必须保留证据中的限定词，包括“选配、可选、适用于、若启用、取决于合同/BOM/现场配置”。不得把产品能力改写成客户已装机或已启用状态。
5. 安全配置教程或操作步骤只证明该对象或能力被手册覆盖，不单独证明它是标准内置组件、实际交付配置或当前已启用功能。
6. 对云平台、远程升级、数据上传等事实，只记录证据明确说明的能力、运营方和依赖；不得自行判定 CRA RDPS。缺少“远程方案是否为产品功能所必需”等信息时写入 unknowns。
7. 证据含糊、可选或依赖合同配置时设置 is_uncertain=true，并在 unknowns 中记录待确认项。
8. 若不同证据存在冲突，分别保留事实并在 contradictions 中说明。
9. 除产品名、型号、协议、法规/标准编号和其他专有名词外，fact、unknowns 和 contradictions 使用简体中文；不得翻译或改写证据中的专有标识。
10. attributes 只用于本字段整理要求明确列出的结构化值，且必须由该fact的同一组block_ids直接支持；其他字段保持空对象。未知值使用null或规定的unknown，不得推断。

【本字段整理要求】
{extraction_guidance}

【目标 JSON Schema】
{json_schema}

【输出要求】
- node_id 和 field_id 必须与任务完全一致。
- fact_id 使用 FACT-001、FACT-002 等批内唯一编号。
- 严格输出单个 JSON 对象，不输出 Markdown 或解释。

【字段任务与检索证据】
{sample_input}
<!-- END PROMPT -->
