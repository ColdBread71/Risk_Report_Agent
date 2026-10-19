# 当前状态

更新：2026-10-19。日常入口：[docs/README.md](README.md)。业务权威仅为根目录 CRA_TARA_workflow_prEN40000.md。

## Node0–2 中断恢复及导出修复（2026-10-19）

- 原运行 `emu-node012-qwen38max-20261015-01` 停在 Node1 快照及20项成功字段检查点。已只读校验模型 `qwen3.8-max-0902`、证据包、检索材料及当前字段输入指纹。一次性接续脚本位于 `tmp/resume_emu_node2.py`；用户手动运行后，三个资产综合和功能映射全部成功，结果保存在 `output/emu-node2-resume-qwen38max-20261019-01/`。未重新运行 Node0–1，也未重新调用字段提取或 embedding。
- 末尾审核包导出因 `OBJ-041` 的父资产待确认而目标仍为 supported 被拒绝。实际还涉及同资产的 `OBJ-042`；4次模型请求结果均已保存，不需要重跑。原因是现有目标修正规则先执行，之后范围对齐又把核心交换机 `ASSET-028` 降为 needs_confirmation，未同步子目标。现仅在范围对齐后同步 supported 子目标为 needs_confirmation，使其符合已有导出不变量，不更改范围判定、目标内容、依据或证据，不放宽导出校验。新增回归覆盖首次降级、已经待确认的父资产及重复处理无变化。
- 已从保存快照离线恢复审核包，输出独立目录 `output/emu-node2-resume-qwen38max-20261019-01-export-fix/`，包含 `report.json`、`report.xlsx` 和 `run_manifest.json`。共52项资产、93项目标、86条类型化功能关联；目标74项supported、19项needs_confirmation。唯一资产数据变化为 OBJ-041/042 两个支持状态，另有恢复说明及新运行溯源。JSON/Excel一致性及来源校验通过；原运行文件、原恢复快照、四个成功分段/映射缓存、业务指南哈希未变。恢复导出新增LLM/embedding调用均为0。
- 一次性离线恢复脚本为 `tmp/finalize_emu_node2_export.py`；它拒绝网络调用及覆盖已有新目录。本次已执行成功，用户无需再运行任何LLM接续命令。结果仍为未批准的 PARTIAL 资产草稿，数量及技术成功不代表业务完整性或质量验收。未执行Node3、未提交或推送Git。
- 验证：Node2规则与共享输出两组共53项通过，包括新增的2项范围/目标状态同步回归。首次组合测试因沙箱系统临时目录不可创建而有15项fixture错误；指定项目内 `tmp/node2-export-fix-pytest/` 后全部通过，未调整依赖或业务规则。结果导出另已在禁网条件下实际完成，并核对原产物哈希未变。
- 旧接续脚本在业务源码修复后会如实触发源码指纹保护。为避免用户重复执行时误以为需要重跑，脚本现优先校验对应 `-export-fix` 审核包的来源身份、文件哈希和JSON/Excel一致性；已完成则显示52项资产、93项目标及路径并成功退出，不创建新运行或调用模型。真实生成路径仍保留原源码指纹保护，未关闭检查。使用禁网和强制拒绝LLM入口验证原 `--execute` 命令成功退出，各原结果文件哈希不变。

## 本轮 Node3 最小可运行版本（2026-10-15）

本节为最新状态；下方 Node0–2 记录保留为历史。Node3 已完成开发和离线验证，尚无真实 LLM 运行或业务专家验收。Node4–8 未开发，未 commit/push。运行说明见 [node3_mvp.md](node3_mvp.md)。

- 复用现有 STRIDE 分类、结构化提取及其有界技术重试、来源校验、LangGraph、运行清单和 JSON/Excel 导出。新增 `--node 3 --upstream-report ... --allow-unreviewed-draft`，只读加载已保存且技术完整的 Node2 审核草稿或阶段快照，在全新的 run-id 中运行；不运行 Node0–2，不需要 embedding 或新缓存。
- 正式 `--mode full` 的资产人工审批点及路由保留。开发开关通过独立 Node3 图的运行配置启用，不写入伪造的批准状态；输出始终保留 `asset_review_approved=false`、`threat_modeling_draft` 和 `review_status=unreviewed_draft`。草稿入口拒绝技术不完整、无有效资产、缺少目标、证据包身份不符及覆盖既有目录。正式批准路径完成 Node3 后也保存最新 JSON/Excel 快照。
- 模型返回紧凑的资产/目标 ID，代码检查存在性、唯一性和归属后恢复完整上游对象；不让模型重写资产。保留场景、STRIDE、原因、攻击者与路径，增加分析依据、待确认前提和人工确认问题。新威胁引用只允许复用本次输入引用，绑定真实文档/块；模型人工确认标记被清除。引用合法不等于语义充分；上游历史证据标记保留其原始值，也不构成资产审批。
- 不再以“每资产至少一条威胁”作为生成失败条件。记录 `uncovered_asset_ids` 并降为 PARTIAL；不强制每类 STRIDE 都有场景。业务指南要求的充分性仍待人工评审，本轮草稿不是其充分性判定或正式 TARA。未知认证、加密、访问控制等通过 Prompt 要求条件化，代码不能证明所有自然语言结论真实。
- 离线验证：Node3、共享导出、结构化提取三组共 91 项通过。使用指定最新基线的 29 项资产和 35 项目标，注入 9 条手写模拟响应，经真实 CLI、图、提取校验和 JSON/Excel 保存，检查关联、6 类 STRIDE、缺口清单、空评分、草稿身份、来源及输出指纹；覆盖未知/跨资产 ID、重复 ID、伪造/未输入引用、运行时身份不符及无开关阻断。模拟内容仅用于验证程序，不能证明真实模型覆盖或业务质量。指南和基线 JSON/Excel/manifest 哈希未变。测试禁用网络与 DNS；tokenizer 词表未缓存，离线用 UTF-8 字节数作为保守 token 上界，未下载词表。日志及模拟产物仅在 `tmp/node3-mvp/`。
- 本机未激活环境时首次组合测试遇到 FAISS DLL 初始化失败；为测试进程补齐既有 RiskAnalysis 的库路径后通过，未修改依赖或环境配置。真实运行请在已激活的 RiskAnalysis 环境执行。当前配置为 qwen-plus；模拟输入的 UTF-8 字节上界低于其现有输入预算，不保证较小上下文模型可容纳。

本轮到 Node3 停止。真实 LLM 命令由用户手动执行；检查候选场景是否有实质因果链、主要入口是否遗漏、假设是否冒充事实，以及关联是否合理，不能仅凭脚本返回 0 判断业务质量。

## 本轮 Node0–2 局部修复（2026-10-14）

本节为最新执行事实；下方保留历史开发记录。本轮仅修复三处明确错误及相关验证，未开发 Node3 及后续链路，未改业务指南、CLI、人工审批流程或缓存框架，未调用真实 LLM，未 commit/push。

- 对照基线为 `output/emu-node012-current-baseline-03/`，其状态仍为 `asset_identification_partial_draft`、等待人工审阅，未经过业务验收。修复前 Node0/1/2 关键规则和证据处理源码哈希与该基线 manifest 一致。
- 范围误合并：Node0不再仅凭共同协议/型号合并对象，Node1也不再按名称子串或型号串继承范围状态。保留有意义的括号限定，只忽略少量明确的范围状态注释；真正同对象的冲突仍提示，并保留冲突双方说明。回放中RS485接口保持在范围内、对应线缆保持排除。Node1的RS485端子、交流熔丝盒、接地端子回到现有组件事实给出的confirmed，路由器回到external；其余组件状态、条件和真实冲突提示未变。这些业务状态不代表人工批准。
- 人工确认：模型新响应及Node1/2模型分段缓存不能保留自行填写的`is_human_confirmed=true`。只在明确的模型入口清除权威标记，不改历史文件；通用证据校验和规范上游记录复制仍保留已有确认，资产整体审批保持独立。回放去除了Node1中79处模型确认标记；小样例验证可信上游记录不会被模型覆盖或通用校验清除。旧基线中的true未被追认为可信人工记录。
- 目标证据：取消Node2及导出审核包中“必须与父资产同块/附在父资产上”的限制。保留来源绑定、允许引用范围、对象关联和格式检查；父资产缺证据仍待确认。独立段落证据保留供复核，不自动接受其支持关系；引用非空也不能将原本needs_confirmation升为supported。回放恢复7项资产的8个目标引用，均保持needs_confirmation；依据类型保留为模型声明的类型，不代表其语义已获证明。
- 离线验证：六组相关测试共174项通过，覆盖Node0/1/2规则、模型输出契约、规则通用性和输出一致性；最后加强的回放/导出断言另经定向复测通过。执行时阻断网络及DNS。回放使用当前基线保存的成功响应和字段事实，重新执行局部规则、引用校验和JSON/Excel导出；27项资产、36项目标、29条类型化功能关联保留，除预期修复字段及系统说明外，其余产品上下文和资产字段一致。基线JSON/Excel、manifest、诊断文件和业务指南哈希未变。测试产物仅写入`tmp/`。
- 尚未证明：没有新的真实LLM整轮运行，也没有业务验收。证据包内合法引用不保证语义充分；RS485端子、交流熔丝盒、接地端子的既有组件事实引用仍落在章节标题块，本轮没有扩展成事实提取/语义审核重构。仍保留的模型supported也不等于人工确认。独立引用的待确认策略有意保守，本轮不建立自动充分性判定系统。

本轮规则版本：Scope `v7.3`、Context `v7.5`、Asset `v2.8`；字段事实与检索规则未改。修复与离线验证完成后停止。需要真实整轮验证时，由用户在项目根目录、已激活的RiskAnalysis环境手动运行以下命令（新run-id，不覆盖基线）：

```powershell
python main.py --mode assets --evidence-packet project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json --rag-index rag_index/yangguang_emu/IDX-3B116ADDF3BB03CC --cache-policy refresh --run-id emu-node012-local-fixes-20261014-01
```

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
