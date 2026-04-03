# Planning Operating Model

> **Canonical source.** This document defines the authoritative planning hierarchy
> for the enforced-planning framework. Pattern 42 (planning-hierarchy) and Pattern 15
> (plan-workflow) are compressed views of this document. GETTING_STARTED.md is the
> adoption guide. When any of them conflict with this document, **this document wins.**

## Purpose

`enforced-planning` is not just “write a plan before coding.” It is a planning
operating model for autonomous and human-guided development. The model must tell
an agent:

- what to understand before planning
- what artifacts define enduring system shape
- what artifacts define the next bounded slice
- what must exist before code starts
- what proves the slice is done

## Core Principles

1. **Question-driven before planning.** Unknowns are surfaced and investigated
   before committing to an implementation plan.
2. **Gap-driven planning.** Plans implement an explicit delta between current
   state and target state.
3. **Capabilities and boundaries define enduring shape.** The reusable
   capability or boundary contract comes before roadmap sequencing because it
   determines what the system is trying to become.
4. **Roadmaps sequence validated gaps.** Phases exist to order major gates once
   the enduring shape is clear enough.
5. **Plans are bounded execution contracts.** They pre-make local decisions,
   define tests, and state acceptance criteria.
6. **Journey notebooks concretize phase contracts.** For non-trivial multi-stage
   work, the notebook renders the end-to-end journey as executable phase
   sections.
7. **Tests and gates are pre-code artifacts.** They should be defined before
   implementation and follow TDD where feasible.
8. **Observability is part of the contract.** It is not a postscript. Long-lived
   or production-facing work is incomplete without a visibility surface.
9. **ADRs are cross-cutting decisions, not just another linear level.** They
   record durable choices whenever a capability, boundary, roadmap, or plan
   needs one.

## The Model

This is a **partial-order dependency graph**, not a rigid one-pass waterfall.
Some artifacts are iterative, and some can be developed in parallel. What
matters is the dependency structure.

### Dependency Order

```text
North Star / Thesis
    -> Questions / Investigation
    -> Current-State Assessment
    -> Gap Analysis
    -> Capabilities / Boundary Docs / PRD surfaces
    -> Roadmap / Phases
    -> Bounded Plan
    -> Journey Notebook (when the work is non-trivial and multi-stage)
    -> Tests / Gates
    -> Code
    -> Observability / Runtime evidence
```

`ADRs` cut across this flow. An ADR can be introduced after investigation,
during capability definition, during roadmap design, or during plan shaping,
provided it records a durable architectural choice.

## Artifact Roles

| Artifact | Primary question | Must exist before | Notes |
|----------|------------------|-------------------|-------|
| North star / thesis | Why does this system exist? | Roadmap | May be brief in small repos; still must exist |
| Questions / investigation | What do we need to verify first? | Plan | Uses code reading, experiments, or human answers |
| Current-state assessment | What exists now? | Gap analysis | Critical for legacy repos |
| Gap analysis | What delta matters now? | Roadmap or plan | Can be repeated throughout project life |
| Capabilities / boundary docs / PRD surfaces | What enduring capability or contract are we shaping? | Roadmap | Cross-project work should define this early |
| Roadmap / phases | What major gates and sequence matter? | Plan | Can be lightweight in small repos |
| ADRs | What durable design choice did we make? | Implementation of affected change | Cross-cutting |
| Plan | What bounded slice are we executing now? | Code | Must define acceptance criteria and required tests |
| Journey notebook | How does the slice work end-to-end? | Proof for non-trivial multi-stage work | Required when phases/interfaces are easy to hand-wave |
| Tests / gates | What counts as pass/fail? | Code | Should be predeclared and preferably written first |
| Code | What is the implementation? | Closeout | Must follow the plan/notebook/contracts |
| Observability | How do we see behavior and drift? | Operational use / long-running execution | Required for runtime confidence |

## What Is Strict vs. What Is Recommended

### Strict dependencies

These are hard ordering rules:

- No bounded plan without prior investigation or explicit unresolved questions.
- No bounded plan without current vs target framing.
- No cross-project plan without capability or boundary clarity.
- No implementation without declared required tests and acceptance criteria.
- No closeout without verification evidence.

### Recommended sequencing

These are defaults that can be compressed for trivial work:

- Define or refine the north star before expanding roadmap detail.
- Write capability/boundary surfaces before phase sequencing.
- Create a journey notebook before coding when the work has multiple real
  interfaces or stages.
- Write tests before code whenever feasible; at minimum, define them before code.

## New System Initialization

For a new system or major new subsystem, use this order:

1. Define the north star.
2. List and investigate critical questions.
3. Describe the desired capabilities and boundaries.
4. Record ADRs for major architectural choices.
5. Create the roadmap and phase gates.
6. Write the first bounded plan.
7. Create the journey notebook if the slice is multi-stage.
8. Define tests/gates.
9. Implement code.
10. Add observability and evidence collection.

## Legacy Repo Bootstrap

For an existing repo, bootstrap in this order:

1. Investigate the current implementation and documentation.
2. Write a current-state assessment.
3. Define the north-star or intended target model.
4. Run gap analysis against current vs target.
5. Write capability/boundary docs for the enduring surfaces that matter.
6. Derive or refresh the roadmap.
7. Write the first bounded plan against the highest-value gap.
8. Create the notebook/tests/gates for that slice.
9. Implement and verify.

This bootstrap order matters because legacy repos often fail when agents plan
against aspirational architecture without assessing the actual current state.

## Relationship Between Plans, Capabilities, Boundaries, and Notebooks

- **Capabilities** describe enduring reusable value and typed exchange surfaces.
- **Boundary docs** describe ownership and contract edges between components or
  repos.
- **Plans** describe the next bounded change against those surfaces.
- **Journey notebooks** render the bounded change end-to-end so humans and
  agents can inspect the real phase contracts.

A good rule of thumb:

- If the question is “what is this thing for the ecosystem?” use a capability
  or boundary doc.
- If the question is “what are we changing this week?” use a plan.
- If the question is “show me the end-to-end flow and artifacts” use a journey
  notebook.

## TDD and Verification Position

`enforced-planning` treats tests and gates as planning artifacts, not just code
artifacts.

That means:

- required tests belong in the plan before implementation starts
- journey notebooks should state phase-level acceptance conditions before live
  code is written
- acceptance gates define what “done” means at feature level
- writing tests first is the default expectation where feasible

Not every task can be fully test-first in practice, but no task should start
implementation without a declared verification strategy.

## Compression Rules

Small or trivial work can compress layers, but the compression must stay
truthful:

- a tiny internal refactor may not need a roadmap update
- a trivial local plan may not need a journey notebook
- a local implementation may not need a separate capability doc

Compression is allowed only when it does not hide a real cross-project,
multi-stage, or architectural concern.

## Relationship to Other Framework Artifacts

- `patterns/28_question-driven-planning.md` defines investigation discipline.
- `patterns/30_gap-analysis.md` defines current-vs-target framing.
- `patterns/15_plan-workflow.md` defines bounded plan structure.
- `patterns/36_executable-journey-notebooks.md` defines notebook execution
  modes and alignment.
- `patterns/42_planning-hierarchy.md` is the hierarchy pattern view of this
  operating model.
- `templates/plan.md.template` is the bounded-plan scaffold derived from this
  operating model.

## Non-Goals

This document does not define:

- runtime coordination state storage
- tracker/registry drift validation
- `relationships.yaml` schema details

Those belong in follow-on design and implementation plans once the planning
operating model itself is canonical.
