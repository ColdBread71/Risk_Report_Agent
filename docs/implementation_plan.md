# Implementation Plan

## 长期路线 v0.5（当前迭代方式以 docs/README.md 为准）

### 1. Project target

Build an industrial CRA/prEN 40000 TARA review agent that accepts customer product material, maintains source evidence, executes the complete Node [0]-[8] workflow, supports mandatory human decisions, and exports auditable business deliverables.

Business workflow source of truth: `CRA_TARA_workflow_prEN40000.md`.  
Engineering constraints: `docs/project_contract.md`.

The current delivery priority is a usable real-data Node [0]-[2] slice. This priority controls implementation order but does not shorten the full project scope.

### 2. Architecture boundaries

- `schemas/`: strict Pydantic domain contracts and cross-object invariants.
- `core/state.py`: LangGraph runtime state and flow-control fields only.
- `nodes/`: workflow orchestration, structured LLM calls, validation/retry, and HITL.
- `tools/`: parsing, indexing, retrieval, deterministic calculation, and export.
- `core/policy.py`: versioned §6.3 method, DREAD scales, thresholds, acceptance rules, and treatment priority.
- `output/`: generated reports and traces; `rag_index/`: rebuildable local indexes.
- Expert workbooks remain external human references and never enter model input.

### 3. Complete business workflow

1. Node [0] freezes legal and product scope: PDE/RDPS status, classification, applicable CRA boundaries, overlaps, assumptions, and evidence.
2. Node [1] produces Product Context and freezes the risk method plus acceptance criteria before assessment begins. It covers IPRFU, functions, environment, architecture/components/interfaces, users, RDPS dependencies, existing functions, STRIDE/DREAD method, thresholds, and policy version.
3. Node [2] produces assets together with cybersecurity objectives. It must cover the minimum §6.4.2 asset categories and stop for mandatory human approval.
4. Node [3] produces evidence-backed STRIDE threat scenarios against approved canonical asset/objective IDs. Every approved asset requires sufficient threat consideration.
5. Node [4] performs DREAD estimation and explicitly derives likelihood, magnitude, and combined risk. Damage must address health/safety, adjacent devices/networks, and attack scalability.
6. Node [5] evaluates results against the criteria frozen in Node [1]. Existing risk is not accepted by default; this node stops for mandatory human risk review.
7. Node [6] selects Avoid → Mitigate → Accept → Transfer, maps prEN 40000-1-4 and applicable vertical controls, maps customer capabilities, and records gaps. Mitigation must return affected items through Node [4]/[5] for reassessment.
8. Node [7] records residual risk, stakeholder/user communication, Annex II content, and Annex VII technical-document evidence.
9. Node [8] closes the analysis with the CRA Annex I applicability matrix, clause justification, threats, controls, existing capability, gaps, and evidence.

Target graph shape:

`[0] -> [1] -> [2] -> HITL -> [3] -> [4] -> [5] -> HITL -> [6] -> ([4]/[5] reassessment when required) -> [7] -> [8]`

### 4. Evidence and RAG strategy

RAG is reusable production infrastructure, not a one-off evaluation exercise.

- Retain the existing deterministic PDF page/section/block corpus and source-hash validation.
- Maintain separate provenance domains for customer product material and regulatory/standard material; retrieval may combine them but citations must not blur their roles.
- Reuse unchanged parsed blocks and persisted embeddings. Source or parser hash changes create a new index version.
- Build DashScope embeddings with local FAISS under `rag_index/<project_id>/`.
- Persist query vectors under their matching index using provider/model/dimension/query identities; use explicit provider timeouts, visible bounded retries for transient failures, and no business-node retry wrappers.
- Retrieve with node-specific queries plus document, source-domain, chapter, page, and block metadata filters.
- Materialize retrieved evidence through the existing EvidencePacket/SourceRef boundary with a fixed token budget, deduplication, and resolvable citations.
- Keep the approved static evidence packet as the bootstrap baseline and controlled fallback.
- Defer reranking, generalized OCR, and advanced retrieval evaluation until observed failures justify them.

### 5. Delivery stages

Each stage is separately reviewed. Completing one stage does not authorize bulk implementation of later stages.

#### Stage A - Real input to approved assets (CURRENT)

A1. Complete the static-packet Node [0]-[2] path:

Progress: A1.1-A1.3 are COMPLETED. The A1.4 real run is COMPLETED technically and remains REVIEW REQUIRED for business acceptance.

- A1.1: define and enforce the evidence-packet input/citation trust boundary;
- A1.2: separate Node [0]/[1] and freeze the method plus acceptance criteria;
- A1.3: add the asset-only CLI boundary, Node [0]-[2] JSON/Excel review package, and Node [2] upstream-evidence subset validation;
- A1.4: perform one explicitly authorized real-LLM Node [0]-[2] run from the approved static packet, then review asset categories, granularity, objectives, unknowns, and citations. The first baseline produced 10 assets and 19 objectives but is not approved: asset granularity and per-field evidence selection require remediation.

A2. Build basic RAG v0:

- A2.0 COMPLETED: preserve provider errors, reject oversized prompts before any external call, and log the model-specific estimate, safe budget, provider limit, and excess;
- A2.1 COMPLETED OFFLINE: define strict Node [0]-[2] field profiles, build/reuse a source-and-scope-bound local FAISS index, retrieve intact blocks under a fixed token budget, and materialize an auditable EvidencePacket plus retrieval trace;
- A2.2 COMPLETED: use DashScope `text-embedding-v4` at 1,024 dimensions to build the real 1,041-block approved-scope index, then inspect representative identity, communication, security-function, credential, upgrade, and remote-maintenance retrievals;
- A2.3 COMPLETED OFFLINE: wire the 20 field profiles into Node [0]-[2] as bounded retrieval -> atomic fact extraction -> node synthesis. Keep this as internal node tooling, preserve the existing graph and static fallback, and stop at the Node [2] HITL boundary;
- A2.4 COMPLETED TECHNICALLY / REVIEW REQUIRED: after deterministic evidence-envelope repair and incremental node/field persistence, a controlled `qwen-plus` retrieval run reused 20 validated field checkpoints and completed Node [0]-[2]. Its Chinese review package is ready for business comparison; Node [2] remains unapproved and Node [3] was not executed.
- A2.5 COMPLETED: isolate the embedding reliability boundary, disable opaque SDK retries, classify provider failures, log attempt latency/status/request ID without query text, and persist query vectors inside the matching FAISS index. Offline tests and a seven-query Node [2] probe passed; no workflow node or text LLM was run.
- A2.6 COMPLETED OFFLINE: add one small field-fact attribute map for communication and component values that must survive synthesis. Downstream logic consumes those reviewed values before legacy prose fallback; the other field types and graph remain unchanged. Existing v7 fact caches still validate, and the full offline suite passes without running a node.
- A2.7 COMPLETED OFFLINE: make Node [2] item validation and completion semantics failure-safe. One invalid asset, objective, or function relationship is isolated without losing valid peers; ambiguous domain enums are not guessed. PASS, reviewable PARTIAL drafts, technical incompleteness, and total failure now route and export consistently. No workflow node was run.
- A2.8 COMPLETED OFFLINE: close the contracts across A2.5-A2.7 instead of adding another local recovery rule. Node1's structured communication/component values are verified at the Node2 candidate-context boundary, including authentication and encryption that were previously dropped. One shared resolver now binds asset count, assessment, technical completeness, review routing, export, and artifact validation to a single status meaning. Cross-layer and full regression tests pass without running a node.
- A2.9 COMPLETED AFTER V8 FAILURE: canonicalize null or empty optional structured list attributes as absent before strict fact validation, while continuing to reject malformed non-empty content and unapproved keys. Add explicit failed-run checkpoint reuse across distinct run IDs, guarded by project, evidence-packet, mode, failure-status, and full cache fingerprints. The failed source remains unchanged.

Stage gate: colleagues can repeatedly generate, inspect, amend, and approve an evidence-linked asset inventory without invoking Node [3].

#### Stage B - Threat identification and risk estimation

B1. Run and refine Node [3] only against approved Node [2] assets.  
B2. Freeze the Node [4] DREAD contract against the Node [1] policy, then implement and verify Node [4].

Stage gate: threat coverage, foreign keys, citations, likelihood, magnitude, combined risk, and safety/scalability rationales are valid.

#### Stage C - Risk decision and secure design

C1. Implement Node [5] evaluation and its mandatory HITL checkpoint.  
C2. Implement Node [6] treatment, control mapping, existing-capability mapping, gap analysis, and reassessment routing.

Stage gate: every evaluated risk has an explicit disposition; Accept/Transfer are justified; Mitigate items complete reassessment.

#### Stage D - Regulatory closure

D1. Implement Node [7] residual-risk register, communications, and technical-document sections.  
D2. Implement Node [8] Annex I applicability matrix and end-to-end trace closure.

Stage gate: all applicable requirements, decisions, controls, gaps, residual risks, and source/legal references are traceable.

#### Stage E - Productization and release

- durable checkpoint persistence and resumable HITL;
- review UI and evidence navigation;
- final Excel/Trace assembly with stable output contracts;
- operational logging, configuration, failure recovery, and run manifests;
- full 阳光 EMU acceptance run;
- second customer project as the blind validation set;
- packaging, user guidance, and release checklist.

### 6. Verification rules

- Validate every LLM boundary with strict Pydantic models and bounded retry.
- Enforce canonical IDs and foreign keys between nodes.
- Reject fabricated or unresolved evidence references.
- Never execute Node [3] before Node [2] approval or complete Node [6] before Node [5] approval.
- Keep calculation and policy rules deterministic outside prompts where possible.
- Review business quality one layer at a time; do not require generation of unfinished downstream nodes.
- Persist each successful field extraction immediately and write JSON/Excel progress snapshots after every completed or failed business node; a later failure must not erase earlier validated output.
- Update `docs/current_state.md` and `docs/decision_log.md` after every accepted stage or architecture change.

### 7. Model routing

- sol-high: regulatory interpretation, workflow/field contracts, policy, acceptance criteria, and business adjudication.
- Terra high/medium: approved implementation, refactoring, parsers, retrieval, exporters, and graph plumbing.
- sol-medium: controlled LLM runs, routine review, and verification.

### 8. 当前下一步（2026-09-14）

先用当前代码与v2证据包完整生成Node0–2一次，再按docs/review/compare_prompt.md独立对比。对比完成后制定3–5项修复计划，不再要求每个节点先由agent业务自评通过。
不运行Node3，不扩展新评估框架，不整体重构。输出目录与版本规则以docs/README.md为准。

### 9. Plan history

- Plan v0.2 established the initial architecture and vertical-slice strategy; SUPERSEDED.
- Plan v0.3 introduced the temporary R1-R7 readiness track; SUPERSEDED.
- Plan v0.4 restored milestone-first delivery through Node [4]; SUPERSEDED by this complete Node [0]-[8] roadmap.
- R2/R3 parser and evidence-packet outputs remain reusable foundations. R4 evaluation-only code/artifacts are retired; R5-R7 were not implemented.
