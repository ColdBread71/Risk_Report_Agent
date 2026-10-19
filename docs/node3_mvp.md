# Node3 STRIDE 候选威胁草稿

## 2026-10-19 三视角版本（当前入口）

规则版本 `node3_threat_rules.v2`。Node0–2 和业务指导不修改，最终 `ThreatAssessment` / `ThreatScenario` 接口保留。以下命令在项目根目录、已激活的 RiskAnalysis 环境执行；只有用户手动运行才产生真实模型请求。

```powershell
python main.py --node 3 --upstream-report output/emu-node2-resume-qwen38max-20261019-01-export-fix/report.json --allow-unreviewed-draft --evidence-packet project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json --run-id emu-node3-batched-qwen38max-20261019-01
```

正常3次请求，视角为“身份与管理”“通信与业务运行”“生命周期与本地维护”。它们适用于不同数字产品，不预设协议、设备或物理接口必然存在。同一资产和完整多步骤攻击链可以跨视角涉及；以是否能在明确条件下独立评估风险决定粒度，不按入口/步骤数量硬拆，也没有固定场景数量或STRIDE配额。

三个视角共享完整的紧凑产品上下文、52项资产及93项目标索引，保留启用条件和范围状态。证据按来源块和原始摘录去重，不做易漏项的产品专属资产分类；不同摘录保留，原文不改写。模型只返回来源块ID，程序恢复输入中原始引用并清除新威胁引用的人工确认标记。输入资料完整不等于结论必然正确；合法引用不能证明漏洞存在或支持关系充分。

新目录 `output/emu-node3-batched-qwen38max-20261019-01/`：

- `report.json` / `report.xlsx`：既有机器/人工可读接口，统一的威胁编号、完整原资产/目标、引用、依据、前提、确认问题；Excel证据列同时显示块ID。`scores=[]`，保持未审核身份，不执行Node4。
- `node3_batches/identity_management.json`、`communications_operations.json`、`lifecycle_local.json`：仅保存通过校验的完整批次，含模型、来源快照、证据包、输入、Prompt、Schema指纹及结果哈希。
- `node3_batches/batch_index.json`：每批 pending/succeeded/reused/failed 状态、覆盖说明及最终威胁到原批次/本地编号的追溯关系。只合并分析内容完全相同的候选，条件或链条不同的近似场景保留，供人工避免重复评分。
- `run_manifest.json`：输入来源、代码规则、输出及批次文件哈希；`diagnostics/`：已有逐次请求诊断。

每批最多两次结构化校验尝试，正常3次、最多6次应用层调用。Node3同步客户端显式设置连接30秒、读取等待1800秒、SDK重试0；请求异常立即停止，不自动重发，JSON/语义校验失败才允许一次纠错。读取等待超时不是严格的整请求墙钟截止。技术失败时不发布正常完成状态，已完成批次保留；全空批次也不会伪装成已得到威胁清单。

**失败后简单复用**：保持原目录只读，换新run-id，明确指定前一次三视角运行。以下仍是一行命令：

```powershell
python main.py --node 3 --upstream-report output/emu-node2-resume-qwen38max-20261019-01-export-fix/report.json --allow-unreviewed-draft --evidence-packet project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json --run-id emu-node3-batched-qwen38max-20261019-02 --reuse-node3-batches emu-node3-batched-qwen38max-20261019-01
```

先检查全部已有批次，再调用未完成部分。模型、输入、证据包、规则、Prompt或Schema不同，或者结果哈希损坏，直接阻断，不静默重新生成高成本请求；缺少批次允许生成。旧版单次调用的6条/16条清单没有三视角检查点，不能作为本开关的复用来源。三个成功批次均可用时，新的运行只重建整合与导出，不调用模型。无需新建跨项目缓存或审核平台。

本轮只完成离线程序验证；尚未执行新版真实模型。以最新版52项资产及93项目标和缓存的本地tokenizer测得：三个Prompt约60522/60532/60539输入token，总计181593；旧版同方法估算213820。此结果仅说明输入预算，推理/输出token可能增加，不代表总费用必然下降。新请求仍需用户手动执行，评审应检查攻击机制、边界、损失条件和证据关联，不以条数变多作为成功。

以下保留第一版MVP的历史运行说明，以本节为准。

Node3 接收保存的 Product Context、资产和保护目标，生成未审核候选威胁。不会重新运行 Node0–2，也不会执行 Node4 或评分。业务指导文件及源基线只读。

## 运行

在项目根目录、已激活的 RiskAnalysis 环境执行（有真实 LLM 请求和费用）：

```powershell
python main.py --node 3 --upstream-report output/emu-node012-local-fixes-20261014-01/report.json --allow-unreviewed-draft --evidence-packet project_artifacts/yangguang_emu/evidence_packets/node_0_3_v2.json --run-id emu-node3-draft-20261015-01
```

必须使用新的 run-id。省略 `--allow-unreviewed-draft` 会直接拒绝，不会询问或伪造人工批准。支持 `node_0_2_review.v2` 审核 JSON 或 `workflow_progress.v2` Node2 阶段快照；只接受状态一致且有资产和目标的可审阅草稿。技术不完整的输入需要先由用户处理，本入口不会修复上游。

沿用当前配置的文本模型。本地配置为 qwen-plus；不会使用 RAG 或 embedding。整个产品上下文及资产一起生成，一次正常请求，只有现有结构化提取的至多三次技术纠错重试。较小上下文模型可能在请求前被既有预算检查阻断；不截断事实或自动换模型。输入来源为本地报告和证据包，无需访问网上标准。

## 输出和衔接

新目录 `output/emu-node3-draft-20261015-01/`：

- `report.json`：沿用 `workflow_progress.v2`。候选清单位于 `state.threat_assessment.threats`；每条有稳定 `threat_id`、STRIDE、完整原资产/目标、原因、路径、分析依据、引用、假设和确认问题。
- `report.xlsx`：新增“Node3 STRIDE 威胁”工作表；“方法与准则”展示覆盖缺口和草稿说明，“证据追溯”保留引用位置。
- `run_manifest.json`：上游文件路径/哈希、证据包身份、模型、规则/代码指纹、输出哈希及未审核身份。
- `diagnostics/`：现有结构化提取诊断，包含客户内容，不应作为脱敏日志对外分享。失败时查看其中失败阶段和相关错误。

`state.asset_review_approved=false`；`state.status=threat_modeling_draft`；`state.threat_assessment.review_status=unreviewed_draft`；`scores=[]`。Node4 后续可以通过 `ThreatAssessment.model_validate(payload["state"]["threat_assessment"])` 读取既有完整场景结构并按 threat_id 关联评分，但本轮没有实现或触发 Node4。后续节点必须保留该草稿身份，不能把技术成功当成正式审核完成。

没有威胁的资产列入 `uncovered_asset_ids`，需要人工判断不适用还是遗漏。不会为了让程序通过而机械补齐每资产或每类别。草稿入口的 assessment 最高为 PARTIAL（模型声明 FAIL 时保留），与“所有资产均有充分威胁考虑”的业务充分性要求保持区分。正式 `--mode full` 继续要求先人工批准资产；本入口不改变该流程。

上游资产/目标逐字段保留，包括历史证据局部标记；这些标记不代表本次资产清单获批。新威胁引用不继承模型自填的人工确认。合法引用只证明来源可追溯，并不证明假设真实、漏洞存在或引用语义充分。

## 最小检查方式

本轮完成的离线验证命令：

```powershell
python -m pytest tests/test_node3_rules.py tests/test_output_layout.py tests/test_extraction_contract.py -q --tb=short
```

共 91 项通过。Node3 集成测试从指定基线加载 29 项资产、35 项目标，使用 9 条**手写模拟响应**验证调用链及输出，不调用真实模型；覆盖六类 STRIDE 是该测试样例的设计，不是生产约束。相关产物在 `tmp/node3-mvp/pytest/`，仅用于测试。模拟响应无法证明真实模型威胁质量。

真实运行后至少检查：

- Web/维护、更新信任、身份权限、南北向通信、云交互、日志和可用性等实际攻击面是否有合理分析；缺口是否披露。
- 场景是否能说明“谁、通过什么入口和条件、破坏什么机制、造成什么后果”，而非仅有 STRIDE 名称或资产名称。
- 每条目标归属是否合理；条件资产和外部资产是否越界；物理安全后果是否有清楚的网络攻击影响链。
- 未知实现是否条件化；是否捏造端口、默认口令、CVE 或已证实漏洞；证据是否支持分析依据。

目前没有正式业务资产批准，也没有真实 Node3 LLM 结果或业务验收。首次实际生成后的遗漏、重复、条件不准确仍需要工程师修订。
