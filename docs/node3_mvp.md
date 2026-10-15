# Node3 STRIDE 候选威胁草稿

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
