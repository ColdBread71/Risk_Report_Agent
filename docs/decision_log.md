# Decision Log

当前迭代约定以 DEC-025 和 docs/README.md 为准。下方历史条目保留来由，不代表当前仍要逐节点业务审批或使用旧输出目录。

This file is append-only. Do not delete historical decisions. When a new decision replaces an old one, mark the old record SUPERSEDED.

## DEC-001

- Status: ACTIVE
- Topic: Legacy isolation
- Decision: Move the old project code, prompts, documents, outputs, templates, and dependencies into legacy_baseline.
- Reason: Build the new project from a clean root instead of repeatedly modifying old business logic.
- Impact: Batch 0-A performs the archive. New code must not import legacy business logic.

## DEC-002

- Status: ACTIVE
- Topic: Domain model location
- Decision: Split Pydantic domain models into schemas. Keep core/state.py for LangGraph workflow state only.
- Reason: The 9-step workflow will contain many models; domain-based separation preserves cohesion.
- Impact: Organize later schemas by evidence, legal, product, threat, risk, treatment, and reporting domains.

## DEC-003

- Status: ACTIVE
- Topic: Risk policy management
- Decision: Add core/policy.py to centralize section 6.3 methodology, acceptance criteria, thresholds, and treatment priority.
- Reason: Legal constraints must be validated, versioned, and audited instead of relying only on prompts.
- Impact: Scoring, evaluation, and treatment nodes must reference the same Policy version.

## DEC-004

- Status: ACTIVE
- Topic: RAG index
- Decision: Use DashScope Embedding with local FAISS.
- Reason: Keep source material, index data, and citations under local project control.
- Impact: The vector index is a runtime build artifact under rag_index and is separate from knowledge_base.

## DEC-005

- Status: ACTIVE
- Topic: Delivery cadence
- Decision: Implement in small batches. Verify and update project state after each batch before starting the next.
- Reason: Reduce refactoring risk and prevent multiple unconfirmed designs from being mixed.
- Impact: Batch 0-D is completed. Batch 0-E is next.

## DEC-006

- Status: ACTIVE
- Topic: MVP vertical-slice strategy
- Decision: Replace the original waterfall plan with a vertical slice focused first on Node [0] legal/product scope and Node [1] TOE Context.
- Validation target: Given test input, produce Pydantic-valid ScopeStatement and ProductContext objects and place them into LangGraph State.
- Out of scope: Threat assessment nodes, later risk analysis, and Excel exporter mapping until this slice is stable.
- Reason: Validate the complete input-to-state path and extraction quality before expanding the workflow.
- Impact: Batch 0-E defines the static WorkflowPolicy; Batch 0-F defines the Node [0]/[1] core schemas; later batches implement the vertical data flow and only then continue to later nodes.

## DEC-006B

- Status: ACTIVE
- Topic: First baseline output target
- Decision: Use legacy_baseline/Project/阳光EMU项目/产品安全风险与安全需求分析-20260727.xlsx as the first baseline output target.
- Output scope: The first baseline output includes TOE Context, TARA & Rational, and TARA methodology.
- Traceability: Traceability is a separate Trace file or Trace sheet, not implicitly mixed into the business output.
- Domain model boundary: Existing Pydantic schemas remain workflow-internal domain objects.
- Assembly approach: A later output aggregation layer will assemble step results into the baseline spreadsheet fields.
- Reason: Separate workflow contracts from the externally recognizable baseline report format and preserve a stable comparison target.
- Constraints: This decision does not add schemas, implement an exporter, or alter the legacy baseline file in this batch.
- History note: This record was originally assigned the duplicate identifier DEC-006; the suffix was added later to preserve unique references without changing the decision content.
## DEC-007

- Status: ACTIVE
- Topic: Output scope refinement (methodology is a rule layer, not an output sheet)
- Decision: Refines DEC-006B. Final deliverables are TOE Context and TARA & Rational only, plus a separate Trace file/sheet added later. TARA methodology is not a business output: it belongs to the rule layer together with regulations, standards, and acceptance criteria, centralized in core/policy.py, and is referenced but never generated as a workflow result or stored in workflow state.
- Reason: Mixing rules with results makes the target model ambiguous. Rules are constants consumed by nodes and the exporter, not deliverables.
- Impact: trace_table.md classifies TOE Context and TARA & Rational as outputs and methodology as rule layer. Batch implementation order is unchanged.
- Note: The workbook referenced in DEC-006B has since been parsed (all sheets extracted and read); its headers are the provisional baseline for field mapping. DEC-006B's "cannot be validated" note is outdated and superseded by this line.

## DEC-008

- Status: ACTIVE
- Topic: Four-layer boundary
- Decision: Enforce four layers. Schema defines Pydantic data only. State carries schema instances between LangGraph nodes plus flow control. Params stay inside node functions and never enter state or Excel. Exporter maps terminal state to Excel and owns headers, join, and format. Methodology lives in core/policy.py and never enters state.
- Reason: Coupling Schema/State/Params with the Excel view made the design unreadable and blocked incremental development.
- Impact: Nodes produce domain objects, exporter reads terminal state only; no temporary values are persisted as formal state.

## DEC-009

- Status: ACTIVE
- Topic: MVP Python environment
- Decision: Use the existing `RiskAnalysis` conda environment for the current MVP.
- Evidence: Python 3.11.15, Pydantic 2.13.4, LangGraph 1.2.10, and LangChain Core 1.5.3 are installed; the MVP graph smoke test passed.
- Dependency policy: Current runtime dependencies are declared in the root `requirements.txt`. FAISS, DashScope, Streamlit, and Excel dependencies remain planned or optional until their batches begin.

## DEC-010

- Status: ACTIVE
- Topic: Asset and threat modelling slice boundaries
- Decision: Keep step [2] asset identification and step [3] STRIDE threat identification as separate LangGraph nodes. Step [2] produces validated assets with cybersecurity objectives, then pauses at a mandatory human approval interrupt before step [3]. Step [3] produces threat scenarios only; DREAD scoring remains exclusively in step [4].
- Flow: `build_context -> identify_assets -> review_assets -> model_threats -> END`, with conditional termination when required upstream data is unavailable or the asset review is rejected.
- State impact: Extend the runtime state with assets, asset assessment metadata, asset review outcome, and threat assessment.
- Reason: Preserve the normative 9-step workflow, enforce the project-contract HITL gate at step [2], and prevent unapproved assets or premature DREAD values from entering threat analysis.
- Constraint: The current in-memory checkpointer supports the CLI/MVP review cycle only; durable cross-process resume remains a later persistence batch.

## DEC-011

- Status: SUPERSEDED by DEC-015
- Topic: Real-data evaluation before Node [4] and before full RAG
- Decision: Insert a Node [4] Readiness Track between the implemented Node [0]-[3] slice and Node [4]. The track uses the 阳光 EMU project to build a reusable page-and-section document corpus, a manually curated evidence packet, a normalized expert-workbook benchmark, and an evidence-backed evaluation of Node [2]/[3].
- Input strategy: Preserve each source file as read-only. Derive immutable JSON blocks keyed by source SHA-256. Each block retains document identity, physical page, printed page label when available, section path, content type, extraction method, and review status. A manually approved evidence packet selects block IDs for the first controlled trial.
- Retrieval strategy: Do not build embeddings, FAISS, reranking, or generalized OCR yet. Use deterministic page/section lookup and explicit evidence-packet selection so extraction/model failures can be separated from retrieval failures. Add RAG only when the controlled evaluation demonstrates a retrieval problem.
- Benchmark strategy: Treat the expert Excel workbook as evaluation target data, never as product-input evidence. Normalize packed asset cells into atomic asset candidates, D-I columns into cybersecurity-objective labels, and J into multi-label STRIDE annotations while retaining workbook/sheet/row provenance and ambiguity notes.
- Validation strategy: Structural gates remain non-negotiable: valid schemas, canonical IDs, complete foreign keys, no fabricated citations, and no Node [3] execution without asset approval. Business quality is assessed through asset-category coverage, objective coverage, semantic threat coverage, STRIDE coverage, attack-path support, and unsupported-claim review.
- Node [4] gate: Node [4] implementation cannot start until the evaluation failure taxonomy is reviewed, Node [2]/[3] remediation is accepted, threat-scenario granularity is decided, and `core/policy.py` plus the Node [4] DREAD input/output contract are frozen against the trusted workflow and approved methodology.
- Model routing: Use sol-high for business methodology, field mapping, evaluation adjudication, and Node [4] policy decisions. Use Terra high/medium for parser, adapters, deterministic plumbing, and approved fixes. Use sol-medium for controlled runs, routine analysis, and verification.
- Reason: A direct `main.py` run proves technical connectivity only, while full RAG without a benchmark makes parser, retrieval, prompt, schema, and model errors indistinguishable.
- Impact: Plan v0.2 is superseded by Plan v0.3. Historical identifier `Batch 4-B` remains only for traceability; execution is divided into seven sequential, independently reviewed readiness steps.

## DEC-012

- Status: SUPERSEDED by DEC-015
- Topic: R1 evaluation contract approval
- Decision: Approve `docs/evaluation_contract.md` v1.0, including the `project_artifacts/<project_id>` boundary, page/section/block locators, row-level handling of workbook D-I attributes, golden scenario-family plus multi-label STRIDE comparison, and baseline-first evaluation without an arbitrary aggregate score.
- Reason: These rules preserve product-evidence isolation, avoid false asset-objective assignments, and allow the existing single-category runtime threats to be compared with multi-category expert rows without forcing row-level equivalence.
- Impact: R1 is complete and R2 PDF page/section extraction is authorized. R3-R7 remain gated.

## DEC-013

- Status: ACTIVE
- Topic: R2 reusable PDF corpus approval
- Decision: Approve parser version `1.5.0` and the generated 阳光 EMU corpus as the fixed source corpus for R3 evidence-packet selection.
- Evidence: Four source PDFs produce 335 pages, 487 section files, 4,607 source-addressable blocks, and 94 structured tables; corpus validation and deterministic rerun checks pass with no review-required pages.
- Identity rule: Evidence packets must bind to the manifest, source hashes, parser version, and parser-version-bound block IDs. A later parser/source change requires a new packet version or regeneration, never silent reuse.
- Impact: R2 is complete and R3 only is authorized. R4-R7 remain gated.

## DEC-014

- Status: ACTIVE
- Topic: R3 evidence-packet approval
- Decision: Approve `yangguang_emu_node_0_3` packet v1 as the controlled product-evidence input for the first real Node [0]-[3] run.
- Scope: The packet contains the EMU300A general manual, the cybersecurity manual, and selected Logger5000 evidence. Logger4000 remains excluded pending delivered-configuration confirmation.
- Constraints: Preserve the five recorded gaps, source hashes, parser version, block identities, and compact prompt projection. The expert workbook remains isolated from all LLM input.
- Impact: R3 is complete and R4 golden-workbook adaptation only is authorized. R5-R7 remain gated.

## DEC-015

- Status: SUPERSEDED by DEC-016
- Topic: Milestone-first real-data delivery and basic RAG timing
- Decision: Replace the R1-R7 readiness track with Plan v0.4. The immediate product target is a usable real-data Node [0]-[2] slice that stops after producing an evidence-linked asset inventory for human review.
- Reuse: Retain the approved R2 PDF corpus and R3 evidence-packet tooling. R2 blocks are the future embedding units; the R3 packet and SourceRef contracts are the shared output boundary for manual selection and RAG retrieval.
- Retirement: Remove the R4 evaluation-only schemas, adapter, configuration, and generated golden data. Automated workbook normalization is deferred; the expert workbook remains a human reference and never model input. R5-R7 are cancelled without implementation.
- Sequence: M1 runs Node [0]-[2] from the static packet; M2 builds source-hash-versioned DashScope Embedding plus local FAISS RAG v0 and reruns Node [0]-[2]; M3 validates Node [3] only after asset approval; M4 then freezes and implements Node [4].
- Model routing: Use sol-high for business rules and field decisions, Terra high/medium for implementation, and sol-medium for controlled runs and verification.
- Supersession: This decision supersedes DEC-011, DEC-012, and the R4-only authorization/gating impact of DEC-014. DEC-013 and the approved evidence content of DEC-014 remain active. The duplicated DEC-014 block is a clerical duplicate and adds no second decision.
- Reason: The former evaluation track delayed a directly usable asset-inventory slice and created temporary code before the product workflow was complete. The new order validates each generated business layer separately and introduces basic RAG while its output can still be checked cheaply.

## DEC-014-DUPLICATE

- Status: DUPLICATE RECORD
- Topic: R3 evidence-packet approval
- Decision: Approve `yangguang_emu_node_0_3` packet v1 as the controlled product-evidence input for the first real Node [0]-[3] run.
- Scope: The packet contains the EMU300A general manual, the cybersecurity manual, and selected Logger5000 evidence. Logger4000 remains excluded pending delivered-configuration confirmation.
- Constraints: Preserve the five recorded gaps, source hashes, parser version, block identities, and compact prompt projection. The expert workbook remains isolated from all LLM input.
- Impact: None. This block is retained only because the decision log is append-only; the active DEC-014 record appears above.

## DEC-016

- Status: ACTIVE
- Topic: Complete Node [0]-[8] roadmap with staged real-data delivery
- Decision: Adopt Plan v0.5 as the complete implementation roadmap. `CRA_TARA_workflow_prEN40000.md` remains the business source of truth, and the project scope ends only after Node [0]-[8] plus productization and end-to-end validation are complete.
- Current priority: Deliver a usable real-data Node [0]-[2] slice first. This is an implementation checkpoint, not a reduction of business scope.
- Workflow invariants: Node [1] freezes the assessment method and acceptance criteria before Node [3]/[4]; Node [2] and Node [5] require HITL; Node [4] owns likelihood, magnitude, and combined risk; Node [6] mitigation routes affected risks through Node [4]/[5] reassessment before Node [7].
- RAG architecture: Reuse source-hash-versioned page/section/block artifacts and the EvidencePacket/SourceRef boundary. Maintain distinct customer-product and regulatory/standard provenance domains. Use DashScope embeddings with a persisted local FAISS index; add reranking or generalized OCR only when observed failures justify them.
- Delivery stages: Stage A covers real Node [0]-[2] and basic RAG; Stage B covers Node [3]-[4]; Stage C covers Node [5]-[6]; Stage D covers Node [7]-[8]; Stage E completes persistence, UI, reporting/trace, acceptance, and blind validation.
- Evaluation policy: Review one generated business layer at a time. Expert workbooks remain human references and never model input; automated golden normalization is deferred unless repeated manual comparison becomes a demonstrated bottleneck.
- Model routing: Use sol-high for regulatory/business contracts and adjudication, Terra high/medium for approved implementation, and sol-medium for controlled runs and verification.
- Supersession: This decision supersedes DEC-015 only where Plan v0.4 stopped at Node [4]. DEC-015's R2/R3 reuse, R4 retirement, and milestone-first delivery decisions remain incorporated into Plan v0.5.

## DEC-017

- Status: ACTIVE
- Topic: Independent Node [0]/[1] and evidence-bound Node [1] policy output
- Decision: Replace the combined context-builder graph node with independent `define_scope` and `build_product_context` nodes. Both load the same validated evidence packet from runtime configuration; only an immutable EvidencePacketRef enters workflow State.
- Node [1] output: Store ProductContext, a deterministic RiskMethodology snapshot from `core/policy.py`, and product-specific RiskAcceptanceCriteria. The DREAD numeric scale remains `pending_approval`, so Node [4] cannot execute until its later policy gate freezes that scale.
- Evidence gate: Model-produced EvidenceRef values must resolve exactly to the approved packet's document/block, source path/hash, parser version, page, section, and quoted text. Invalid references enter bounded validation retry and never reach State.
- Reason: Preserve one-node-per-business-step architecture, make §6.3 decisions explicit before downstream analysis, and prevent large source blocks or filesystem paths from polluting checkpoint State.
- Verification: Offline fake-model execution passed Node [0] and Node [1], checkpoint serialization, route gating, citation retry, and missing-packet fail-closed checks. No real LLM was called.

## DEC-018

- Status: ACTIVE
- Topic: Node [0]-[2] execution and review-output boundary
- Decision: Make `assets` the default CLI mode. It invokes the graph once, stops at the existing Node [2] interrupt, exports a versioned JSON review contract plus a human-readable Excel view, and never resumes the interrupt or enters Node [3]. Retain `full` mode for the existing explicit APPROVE path.
- Output boundary: Store each run under `output/<project_id>/<run_id>/`. The review package contains Scope, ProductContext, the Node [1] methodology/criteria snapshot, assets/objectives, review status, errors, and a deduplicated evidence trace. It is a presentation mapping and does not add report artifacts to LangGraph State.
- Evidence gate: Node [2] may use no EvidenceRef outside the exact references already validated in Node [0]/[1]. Missing evidence remains explicit; invented or altered references fail bounded extraction retry.
- Verification: Offline fake-model execution reached the Node [2] interrupt with exactly four extraction calls, produced JSON and a seven-sheet Excel workbook, rejected a modified citation, exposed enum values without class prefixes, and made no Node [3] call. No real LLM was called.

## DEC-019

- Status: ACTIVE
- Topic: Deterministic evidence materialization at LLM boundaries
- Decision: Treat a model-produced `block_id` as a selection request, not trusted source metadata. Resolve file identity, path, type, hash, parser version, document ID, page, printed-page label, and section path from the validated EvidencePacket. Preserve a quote only when it is a normalized verbatim substring of that block; otherwise set it to null and add an audit note. Unknown blocks still fail validation and retry.
- Downstream rule: Risk criteria and Node [2] assets may only reuse exact references already validated in Scope/ProductContext. Canonicalization cannot introduce a new packet block downstream.
- Reason: The first A1.4 attempts showed that a deterministic text model repeatedly paraphrased quotes or malformed copied IDs. Asking the model to reproduce trusted metadata made valid extraction depend on transcription accuracy without adding security.
- Verification: Offline checks confirmed that fabricated metadata is replaced from the packet, non-verbatim quotes are disclosed and removed, unknown references remain invalid, and downstream references remain an upstream subset.
- A1.4 result: The final real run completed all four Node [0]-[2] extractions on their first attempts, reached the mandatory Node [2] interrupt, exported the review package, and did not execute Node [3]. Business acceptance remains pending because asset granularity and evidence precision require remediation.

## DEC-020

- Status: ACTIVE
- Topic: Node/field-level retrieval and approved-scope vector index
- Decision: Add strict retrieval profiles for 20 Node [0]-[2] fields and a reusable FAISS cosine-retrieval tool. The tool ranks existing parsed blocks, optionally expands same-section neighbors, retains only complete blocks under a fixed token budget, and materializes the result through the existing EvidencePacket contract with a separate retrieval trace.
- Scope boundary: Build each index only from blocks in an explicitly validated evidence packet. Bind index identity to the corpus manifest, parser version, scope-packet hash, embedding model/dimensions, and embedding-text version. This prevents excluded documents such as Logger4000 from entering the active retrieval index merely because they exist in the project corpus.
- Integrity: Revalidate source-file, manifest, FAISS-file, index-directory, and block identities on reuse. A changed source, parser, packet scope, model, dimensions, or embedding text format creates a different index identity or fails closed.
- Workflow impact: Retrieval remains a tool and is not yet wired into LangGraph State or Node generation. Node [0]-[2] schemas, routing, HITL boundaries, and the static packet fallback remain unchanged.
- Verification: A local deterministic embedding double indexed and reloaded all 1,041 approved blocks, reused the index without re-embedding, enforced an 800-token packet budget, excluded out-of-scope corpus blocks, wrote a packet/trace pair, and passed the existing packet/source validator. No customer text was sent to an external embedding service.

## DEC-021

- Status: ACTIVE
- Topic: Real embedding configuration and field-retrieval execution inside Node [0]-[2]
- Decision: Use DashScope `text-embedding-v4` with 1,024 output dimensions and batches of at most 10. The persisted approved-scope index is `IDX-6BB44D1996D16BD9` with 1,041 blocks. Node [0]-[2] each run their stable field profiles as bounded retrieval -> atomic fact extraction -> one node-level synthesis; this is internal node tooling and does not add business nodes or fields to LangGraph State.
- Evidence boundary: Each field fact may cite only blocks in its retrieved packet. Node synthesis may cite those canonical retrieved blocks plus valid upstream citations. This narrowly supersedes DEC-019's Node [2] upstream-only citation rule when the explicit RAG path is enabled; the static fallback retains that rule. Unknown, altered, out-of-packet, or out-of-scope block identities fail validation.
- Runtime boundary: `--rag-index` explicitly enables retrieval. Without it, the approved static packet path remains available. The Node [2] human interrupt and the prohibition on Node [3] before approval are unchanged.
- Verification: The real index was built from the authorized approved packet and representative identity, communication, security-function, credential, upgrade, and remote-maintenance queries were inspected. Offline orchestration exercised all 20 field extractions and three syntheses under the `qwen-max` preflight budget. A separate graph-level fallback check completed Node [0]-[2], reached the interrupt with 10 assets, and made no Node [3] call. The controlled real `qwen-max` RAG run remains A2.4.

## DEC-022

- Status: ACTIVE
- Topic: Incremental run persistence and deterministic EvidenceRef envelope completion
- Decision: Stream LangGraph node updates in the CLI and atomically persist the latest JSON/Excel state plus a node-specific snapshot after every completed or failed business node. Persist every successful field-fact extraction separately under the run directory; an explicit reusable `--run-id` allows matching field checkpoints to be reused after a retry.
- State boundary: Progress files remain presentation/runtime artifacts under `output/<project_id>/<run_id>/progress/`; paths, field facts, and raw evidence blocks do not enter `TaraState`.
- Evidence repair: When a model selects a valid packet `block_id`, deterministically materialize both canonical SourceRef metadata and missing required EvidenceRef envelope fields. Model-authored values are not allowed to weaken block identity or source validation.
- Reason: The first A2.4 run completed Node [0] and all eight Node [1] field extractions but ProductContext retries omitted required envelope fields. The earlier invoke-then-export CLI retained nothing after the Node [1] failure.
- Verification: Offline success and forced-failure graph runs confirmed node-specific JSON/Excel snapshots, retention of Node [0] after Node [1] failure, field-checkpoint round-trip validation, full error logging, and no Node [3] execution before approval.

## DEC-023





- Status: ACTIVE
- Topic: Chinese Node [0]-[2] business-review presentation and completed A2.4 run
- Decision: Keep canonical JSON Schema keys and enum values unchanged, but localize the Excel presentation layer to Chinese. Separate Node [0] and Node [1], expand nested fields into explicit rows/columns, order generated business results before methodology/criteria, and place the deduplicated evidence trace last. Preserve original-language evidence quotes and technical identifiers.
- Runtime result: The controlled `qwen-plus` RAG run reused 20 validated field checkpoints bound to the same evidence/index scope, then completed the four synthesis calls for Node [0], Node [1], acceptance criteria, and Node [2]. It stopped at the mandatory Node [2] review boundary with 7 assets, 13 related objectives, 43 evidence-trace entries, and no runtime errors.
- Verification: The eight-sheet workbook was imported and rendered sheet by sheet; sheet order, Chinese headers, `A5` freeze panes, canonical JSON `PARTIAL` assessment, and absence of formula errors were confirmed. Business acceptance remains pending and Node [3] was not executed.

## DEC-024

2026-09-14：从工作电脑实际未修复基线重新处理 Node0。单节点输出均默认未检查；两次真实运行未通过业务核查，不登记上游。当前 v4 要求字段事实逐条提供可匹配原文，引用可解析不代表语义正确。后续真实运行由用户执行；Node1/2 尚待验证，Node3 不运行。

## DEC-025

- 日期：2026-09-14。来源：用户要求先交付Node0–2可读结果、整轮后独立对比、精简文件、避免单节点反复自评。
- 当前迭代单位改为Node0–2整轮：生成一次、独立对比、集中修3–5项、同事评审。单节点工具保留排障用，不强迫每个节点登记业务可用后才能运行整轮。业务指导要求的Node2人工确认仍保留，不能据此进入未批准的Node3。
- output改为output/<run-id>/report.json、report.xlsx、run_manifest.json；同轮累积更新report，不再复制latest和各节点Excel。字段缓存位于project_artifacts/<project_id>/runs/<run-id>/field_facts。覆盖DEC-018/022旧的输出位置和同名run-id复用约定。
- 所有新运行使用新run-id，manifest覆盖整轮与单节点，包含代码指纹、规则版本、模型、证据包和索引。旧v4只能登记未知代码身份，不能伪造指纹。原始旧产物已归档。
- 本轮不改业务生成提示词、模型自评策略、Schema或检索策略。保留现有架构，详细改进计划等docs/review/<版本>/review.md。
- 本轮验证：9项离线pytest通过；保留的两份业务JSON与归档逐字节一致；Excel内容、合并区域、冻结窗格经核对保留，空文本单元格由工具规范化为空字符串，视觉仍为空。排版检查未运行真实LLM或embedding。

## DEC-026

- Status: ACTIVE
- Date: 2026-09-18
- Topic: Observable and cache-backed embedding reliability boundary
- Decision: Move timeout and retry ownership out of field extraction into the embedding provider. Configure the OpenAI-compatible client with an explicit timeout and `max_retries=0`, then perform at most three visible attempts only for timeout, connection, 429, 408/409, and selected 5xx failures. Deterministic authentication, request, dimension, and response-contract errors fail immediately.
- Cache boundary: Persist query vectors below the exact FAISS index directory. Cache identity includes provider endpoint hash, model, dimensions, and query hash; raw query text is not stored. Field-fact `refresh` controls text extraction only and does not invalidate a mathematically unchanged query vector.
- Observability: Log model, batch size, query/batch hash, attempt, elapsed time, error class, status, and request ID without logging credentials or query text. Invalid cache entries are ignored and atomically replaced after a successful provider response.
- Reason: The v7 run lost three Node2 fields before retrieval completed. Logs locate the immediate failure at remote query embedding, but prior code exposed neither SDK attempts nor typed provider errors and performed remote embedding even when field facts were reusable. Retrying in the business field layer would duplicate policy and could retry deterministic retrieval errors.
- Verification: Six provider-boundary tests cover transient retry, exhausted retry, permanent failure, persistent cache reuse, corrupt-cache replacement, and explicit SDK configuration. The full offline suite passes. A standalone probe of all seven Node2 queries used the existing approved index, made no node or text-LLM call, and completed all remote misses on the first attempt; immediate reuse hit the persistent cache.

## DEC-027

- Status: ACTIVE
- Date: 2026-09-18
- Topic: Minimal structured fact handoff for communication and component fidelity
- Decision: Keep the existing `RetrievedFact` statement and evidence contract, and add one optional, field-validated `attributes` map. Only Node1 communications and components may populate it. Communication keys cover endpoints, protocol, port, interface, direction semantics, activation, authentication, encryption, exchanged data, and conditions; component keys cover name, type, scope status, and conditions.
- Consumption: Node1 deterministic repair prefers same-block structured attributes and falls back to the existing conservative statement parser only for historical or missing attributes. Node0 scope evidence keeps precedence over a component fact when it provides an explicit or conflicting boundary status.
- Simplicity boundary: Do not introduce a knowledge graph, generic subject-predicate-object engine, per-field class hierarchy, or new workflow node. Other 18 retrieval fields remain unchanged. The attribute map accepts only reviewed keys and enum values, so it cannot become an unbounded side channel.
- Reason: v7 field facts contained correct table relationships, but later code reparsed generated Chinese sentences and lost endpoints, authentication, encryption, and delivery status when phrasing changed. Preserving a few high-value values at the fact boundary removes that avoidable translation step while retaining readable statements and backward compatibility.
- Verification: New tests show structured communication values survive nonstandard statement wording, component type/status survive without delivery keywords, and attributes are rejected outside the reviewed fields. All 17 existing v7 field caches validate under the additive schema. The full 90-test offline suite passes; no node or external model was run.

## DEC-028

- Status: ACTIVE
- Date: 2026-09-18
- Topic: Node [2] item isolation and truthful completion states
- Decision: Validate each generated asset, cybersecurity objective, and typed function relationship independently before validating the section. Reject an invalid item with a bounded system diagnostic while retaining valid peers. Normalize only spelling-level enum form; do not infer that an ambiguous domain value such as `system` means `other`, or that a status written in the type field expresses an intended asset type.
- Status contract: `asset_identification_completed` is reserved for a PASS result with no required technical failure. A business-PARTIAL inventory with valid assets is `asset_identification_partial_draft` and may be exported for human review. A required field or section failure is `asset_identification_technical_incomplete` and remains a diagnostic snapshot. No valid inventory remains failed. Routing, exporters, CLI success, and staged manifests consume the same shared reviewable-status set.
- Simplicity boundary: Reuse Pydantic item schemas and the existing deterministic fallback objective. Do not add a second generation path, model self-repair loop, project-specific alias table, or exception channel for each observed typo.
- Verification: Tests cover ambiguous asset rejection with valid-peer retention, invalid child isolation, model-injected diagnostic removal, business-PARTIAL review routing/export/manifest selection, and technical-incomplete blocking. The full 93-test offline suite passes; no workflow node, embedding request, or text-model request was run.

## DEC-029

- Status: ACTIVE
- Date: 2026-09-18
- Topic: Cross-layer closure for the v7 recovery changes
- Decision: Finish the recovery work with contract integration, not another project-specific generation rule. Preserve Node1's repaired communication authentication and encryption together with endpoints, direction semantics, activation, conditions, and exchanged data in the compact Node2 candidate context. Preserve structured component type, scope status, and conditions through the same boundary. Candidate context remains non-evidentiary and cannot replace Node2 field facts.
- Workflow invariant: Derive the Node2 status in one shared function from valid asset count, assessment, and required technical completeness. The review route, review-package builder, and published-artifact validator reject any status/assessment mismatch. PASS maps only to completed, PARTIAL only to a reviewable partial draft, required technical failure to technical incomplete, and FAIL or an empty inventory to failed.
- Reason: The first three repairs were individually correct but could still be weakened at their boundaries: authentication/encryption were dropped by Node2's compact flow handoff, and status strings could be checked independently of the assessment they claimed to describe. These were integration defects, not reasons for more LLM retries or more asset aliases.
- Verification: Cross-layer tests prove structured Node1 communication/component values reach Node2 candidate material, item rejection survives deterministic assembly into a reviewable PARTIAL result, and inconsistent state or published JSON is blocked. The full 95-test offline suite passes; no workflow node or external service was called.

## DEC-030

- Status: ACTIVE
- Date: 2026-09-18
- Topic: Optional fact-value canonicalization and safe reuse after a failed full run
- Decision: Treat null and empty lists in optional structured list attributes as absence before strict `FieldExtractionResult` validation. Continue to reject empty strings, malformed non-empty lists, unsupported enum values, and attributes outside the reviewed field contract. This resolves a Schema/validator contradiction rather than weakening business validation.
- Retry boundary: Add `--reuse-failed-run` for a new full-run ID. The source must be a failed or technically incomplete full run with the same project, evidence packet, and requested mode. Only field checkpoints whose retrieval packet, index, text model, profile, prompt, and Schema fingerprints still match are copied into the new run after validation. The failed output and cache remain unchanged; `refresh` and single-node use are rejected.
- Reason: The first v8 validation completed Node0 and four Node1 fields, then the component fact model repeatedly emitted an empty optional `conditions` list permitted by the broad JSON Schema but rejected by the post-validator. A new run ID previously made the successfully persisted checkpoints unreachable, defeating failure recovery.
- Verification: Null/empty optional attributes canonicalize to omission while malformed content still fails. Failed-run identity mismatch is rejected. All nine v8 checkpoints match the current field Schema fingerprint, and the real v8 manifest/evidence identity resolves read-only for a v9 target. The full 97-test suite and static compilation pass; no external call or business node was run during the fix.
