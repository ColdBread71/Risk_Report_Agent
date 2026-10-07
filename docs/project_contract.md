# Project Contract

Status: ACTIVE
Version: v1.0

## Goal

Build a CRA and prEN 40000 TARA review agent with legal mapping, evidence traceability, structured risk analysis, human review, and auditable outputs.

## Non-negotiable constraints

1. LangGraph is the workflow backbone. Implement independent nodes for steps [0] through [8].
2. All workflow state and domain objects require strict Pydantic validation.
3. Tools perform parsing, retrieval, calculation, and export. Nodes orchestrate workflow logic.
4. Use STRIDE for threat identification and DREAD for risk estimation.
5. Risk estimation must explicitly contain likelihood, magnitude, and combined risk.
6. DREAD Damage must cover user health and safety, adjacent devices/networks, and attack scalability.
7. Risk acceptance criteria and the risk methodology are frozen in step [1], before step [4].
8. A risk is not accepted by default when risk exists. Treatment priority: Avoid -> Mitigate -> Accept -> Transfer.
9. Mitigation requires reassessment. Accept and Transfer require written justification.
10. Important conclusions must link to legal/standard references and source evidence.
11. Step [2] asset confirmation and step [5] risk evaluation require Human-in-the-loop checkpoints.
12. Every step produces machine-readable and human-readable output with audit traceability.
13. Legacy code is isolated under legacy_baseline. New code must not reuse legacy business logic directly.
14. knowledge_base is read-only source material. Runtime output goes to output. RAG indexes go to rag_index.

## Source of truth

The business workflow is defined by CRA_TARA_workflow_prEN40000.md. Any change to that file requires an impact review for schemas, policy, nodes, prompts, and tests.

## Confirmed technical decisions

- Domain models live in schemas. core/state.py manages workflow state only.
- core/policy.py manages prEN 40000-1-2 section 6.3 methodology, scales, thresholds, and treatment rules.
- RAG uses DashScope Embedding with local FAISS.
- Remote embedding calls are isolated behind one provider boundary. Query vectors are cached under the matching persisted index; timeout, bounded retry, and error classification are configured there rather than in business nodes.
- Field facts remain simple evidence-backed statements. Only communication and component facts carry a small reviewed attribute map for values that downstream business objects must preserve; other fields do not gain parallel schemas or rule channels.
- Node [2] validates generated assets and their child records item by item. Invalid or ambiguous items are rejected with diagnostics rather than guessed or allowed to discard valid peers. PASS, reviewable business partial, technical incomplete, and failed states remain distinct across routing, export, and manifests.
- The new project is built from a clean root; do not modify the old src tree.
- Work is delivered in small batches. Each batch is verified before the next batch starts.
- Every completed batch must update docs/current_state.md before the task is closed.
- Any architecture, scope, methodology, or workflow change must update docs/decision_log.md and, when applicable, docs/implementation_plan.md.
- The final batch checklist is: inspect current state, implement, verify, update project docs, then report completion.
