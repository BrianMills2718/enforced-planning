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
2. **Research should compound, not reset.** Dated investigations answer a
   specific question; topic research syntheses preserve reusable conclusions so
   future ADRs and plans can build on them.
3. **Gap-driven planning.** Plans implement an explicit delta between current
   state and target state.
4. **Capabilities and boundaries define enduring shape.** The reusable
   capability or boundary contract comes before roadmap sequencing because it
   determines what the system is trying to become.
5. **Roadmaps sequence validated gaps.** Phases exist to order major gates once
   the enduring shape is clear enough.
6. **Plans are bounded execution contracts.** They pre-make local decisions,
   define tests, and state acceptance criteria.
7. **Journey notebooks concretize phase contracts.** For non-trivial multi-stage
   work, the notebook renders the end-to-end journey as executable phase
   sections.
8. **Tests and gates are pre-code artifacts.** They should be defined before
   implementation and follow TDD where feasible.
9. **Observability is part of the contract.** It is not a postscript. Long-lived
   or production-facing work is incomplete without a visibility surface.
10. **ADRs are cross-cutting decisions, not just another linear level.** They
   record durable choices whenever a capability, boundary, roadmap, or plan
   needs one, and they must record the research basis behind the choice or say
   explicitly that research was skipped.

## The Model

This is a **partial-order dependency graph**, not a rigid one-pass waterfall.
Some artifacts are iterative, and some can be developed in parallel. What
matters is the dependency structure.

### Dependency Order

```text
North Star / Thesis
    -> Questions
    -> Investigation Memos
    -> Topic Research Syntheses
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
| Questions | What do we need to verify first? | Investigation | Surface unknowns before planning |
| Investigation memos | What did we learn when we looked? | ADR or plan | Dated, question-specific, usually immutable |
| Topic research syntheses | What reusable conclusions already exist on this topic? | ADR, capability doc, or plan | Living topic memory; links investigations, prior art, and freshness triggers |
| Current-state assessment | What exists now? | Gap analysis | Critical for legacy repos. Must include agent-memory recall for repos with prior session history (ADR-0010). |
| Gap analysis | What delta matters now? | Roadmap or plan | Can be repeated throughout project life |
| Capabilities / boundary docs / PRD surfaces | What enduring capability or contract are we shaping? | Roadmap | Cross-project work should define this early |
| Roadmap / phases | What major gates and sequence matter? | Plan | Can be lightweight in small repos |
| ADRs | What durable design choice did we make? | Implementation of affected change | Cross-cutting; must include research basis or explicit skip |
| Plan | What bounded slice are we executing now? | Code | Must define acceptance criteria, required tests, and the research basis for the slice when the work is non-trivial |
| Journey notebook | How does the slice work end-to-end? | Proof for non-trivial multi-stage work | Required when phases/interfaces are easy to hand-wave |
| Tests / gates | What counts as pass/fail? | Code | Should be predeclared and preferably written first |
| Code | What is the implementation? | Closeout | Must follow the plan/notebook/contracts |
| Observability | How do we see behavior and drift? | Operational use / long-running execution | Required for runtime confidence |

## What Is Strict vs. What Is Recommended

### Strict dependencies

These are hard ordering rules:

- No bounded plan without prior investigation or explicit unresolved questions.
- No non-trivial ADR without a research basis section or explicit research skip.
- No bounded plan without current vs target framing.
- No cross-project plan without capability or boundary clarity.
- No design, cross-project, or externally-informed plan without a declared
  research basis for the slice or explicit research skip.
- No implementation without declared required tests and acceptance criteria.
- No closeout without verification evidence.
- **No current-state assessment without a memory recall step.** For any project
  with prior session history, run `agent-memory recall '{topic}' --project
  {project}` (or equivalent MCP call) before writing the assessment. Undiscovered
  operational findings from prior sessions are a correctness risk, not a
  convenience. (ADR-0010)

### Recommended sequencing

These are defaults that can be compressed for trivial work:

- Define or refine the north star before expanding roadmap detail.
- Write or refresh the relevant topic research synthesis before creating ADRs for
  cross-project or externally-informed work.
- Write capability/boundary surfaces before phase sequencing.
- Create a journey notebook before coding when the work has multiple real
  interfaces or stages.
- Write tests before code whenever feasible; at minimum, define them before code.
- Start topic freshness metadata as advisory. Add blocking enforcement only
  after the repo has enough stable topic research to validate it meaningfully.

### LLM System Design: Pattern-First Sizing

When designing any LLM-based system, identify which composable pattern it is
**before** designing its implementation. Start at the simplest pattern that could
address the problem; add complexity only when you have measured that the simpler
pattern is insufficient.

**Anthropic's six patterns (from "Building Effective Agents", Dec 2024),
ordered simplest to most complex:**

1. **Augmented LLM** — single call with retrieval, tools, memory
2. **Prompt chaining** — sequence of calls, each processing the previous output
3. **Routing** — classify input, dispatch to specialized handler
4. **Parallelization** — independent subtasks run concurrently, outputs aggregated
5. **Orchestrator-workers** — central LLM dynamically delegates to worker LLMs
6. **Evaluator-optimizer** — generator + evaluator in a feedback loop

Most systems that feel like they need an "orchestrator" are actually prompt
chaining (2) or routing (3). Most "evaluation" systems are evaluator-optimizer (6).
The right pattern usually needs 50–200 lines of code, not a framework.

**Ecosystem shared infra by pattern:**

| Pattern | Shared infra |
|---------|-------------|
| Augmented LLM | `llm_client` |
| Prompt chaining | `llm_client` directly |
| Routing | (none yet — hand-roll) |
| Parallelization | (none yet — asyncio directly) |
| Orchestrator-workers | OpenClaw (heavy) |
| Evaluator-optimizer | `agentic_scaffolding/pipeline/` (Plan 0001) |

## New System Initialization

For a new system or major new subsystem, use this order:

1. Define the north star.
2. List and investigate critical questions.
3. Write the investigation memo(s) that answer those questions.
4. Write or refresh the relevant topic research synthesis when conclusions
   should compound beyond the current task.
5. Describe the desired capabilities and boundaries.
6. Record ADRs for major architectural choices.
7. Create the roadmap and phase gates.
8. Write the first bounded plan.
9. Create the journey notebook if the slice is multi-stage.
10. Define tests/gates.
11. Implement code.
12. Add observability and evidence collection.

## Legacy Repo Bootstrap

For an existing repo, bootstrap in this order:

1. Investigate the current implementation and documentation. **Run `agent-memory
   recall '{topic}' --project {project}` first** — prior session findings are
   source material, not noise.
2. Write the investigation memo(s) that preserve what was learned.
3. Write a current-state assessment (requires memory recall — see Strict
   Dependencies).
4. Define the north-star or intended target model.
5. Run gap analysis against current vs target.
6. Write or refresh the relevant topic research synthesis when the findings
   should be reusable outside the immediate task.
7. Write capability/boundary docs for the enduring surfaces that matter.
8. Derive or refresh the roadmap.
9. Write the first bounded plan against the highest-value gap.
10. Create the notebook/tests/gates for that slice.
11. Implement and verify.

This bootstrap order matters because legacy repos often fail when agents plan
against aspirational architecture without assessing the actual current state.

## Relationship Between Investigations, Topic Research, ADRs, Plans, and Notebooks

- **Investigation memos** capture what was learned in a dated question-driven
  pass.
- **Topic research syntheses** preserve reusable conclusions, related
  investigations, and freshness triggers for a domain.
- **ADRs** record the durable choice and point back to the evidence base.
- **Capabilities** describe enduring reusable value and typed exchange surfaces.
- **Boundary docs** describe ownership and contract edges between components or
  repos.
- **Plans** describe the next bounded change against those surfaces.
- **Journey notebooks** render the bounded change end-to-end so humans and
  agents can inspect the real phase contracts.

A good rule of thumb:

- If the question is “what did we learn while investigating?” use an
  investigation memo.
- If the question is “what should future work reuse on this topic?” use a topic
  research synthesis.
- If the question is “what durable choice did we make?” use an ADR.
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

### When Is a Journey Notebook Required?

A journey notebook is **required** when ALL of the following are true:
- Implementation spans ≥ 2 distinct phases or stages (e.g., parse → validate → store)
- AND at least one of:
  - ≥ 2 scripts or modules are being created or significantly modified
  - Work crosses a subsystem or repo boundary
  - The phase sequence has non-obvious dependencies between outputs (output of phase N
    is input to phase N+1 in a way that isn't self-evident from the plan)

A journey notebook is **optional but recommended** when:
- Work is a single linear script with clear input/output
- Implementation is a straightforward extension of an existing pattern

A journey notebook is **never required** when:
- The trivial exemption applies (≤ 20 lines, no new APIs)
- Single-file fix with a clear, self-contained acceptance criterion

## Relationship to Other Framework Artifacts

- `patterns/28_question-driven-planning.md` defines investigation discipline.
- `patterns/43_topic-research-synthesis.md` defines how research compounds over
  time beyond one investigation.
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
