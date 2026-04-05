# Pattern #42: Planning Hierarchy and Operating Model

**Complexity:** High (framework-level)
**Prerequisites:** Pattern #15 (Plan Workflow), #28 (Question-Driven Planning),
#30 (Gap Analysis), #36 (Executable Journey Notebooks)

> **Full detail:** [`../PLANNING_OPERATING_MODEL.md`](../PLANNING_OPERATING_MODEL.md)
> is the canonical source. This pattern is a compressed reference view.
> When they conflict, the POM wins.

## One-line Summary Per Layer

The planning model is a **partial-order dependency graph**, not a waterfall.
Certain dependencies are non-negotiable; others can be compressed for trivial work.

| Layer | Primary question |
|-------|-----------------|
| North star / thesis | Why does this system exist? |
| Questions | What must be verified before planning? |
| Investigation memos | What did we learn when we looked? |
| Topic research syntheses | What reusable conclusions should future work start from? |
| Current-state assessment | What really exists today? |
| Gap analysis | What delta matters now? |
| Capabilities / boundaries | What enduring contract are we shaping? |
| Roadmap / phases | What major gates and sequence matter? |
| ADRs | What durable choice did we make, and what research supported it? |
| Plan | What bounded slice are we executing now? |
| Journey notebook | How does the slice work end to end? |
| Tests / gates | What proves the slice is done? |
| Code | What is the implementation? |
| Observability | How do we see runtime truth? |

## Non-negotiable Dependencies

- No plan without investigation or explicit unresolved questions
- No non-trivial ADR without a research basis or explicit research skip
- No plan without current-vs-target framing
- No cross-project plan without capability/boundary clarity
- No implementation without declared tests and acceptance criteria
- No closeout without verification evidence

## Relationship to Other Patterns

| Pattern | Role |
|---------|------|
| [Pattern #15](15_plan-workflow.md) | Bounded plan structure and status workflow |
| [Pattern #28](28_question-driven-planning.md) | Investigation before planning |
| [Pattern #43](43_topic-research-synthesis.md) | Durable topic-level research reuse |
| [Pattern #30](30_gap-analysis.md) | Current-vs-target framing |
| [Pattern #36](36_executable-journey-notebooks.md) | Executable end-to-end journey rendering |

For compression rules, agent read order, anti-patterns, and policy semantics, see
[`PLANNING_OPERATING_MODEL.md`](../PLANNING_OPERATING_MODEL.md).
