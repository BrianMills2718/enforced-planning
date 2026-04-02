# Pattern #42: Planning Hierarchy and Operating Model

**Complexity:** High (framework-level)
**Prerequisites:** Pattern #15 (Plan Workflow), #28 (Question-Driven Planning),
#30 (Gap Analysis), #36 (Executable Journey Notebooks)

## Problem

The framework has multiple planning artifacts, but agents and humans still need a
clear answer to three questions:

1. what must be understood before planning begins?
2. what defines enduring system shape versus the next bounded slice?
3. what must exist before implementation starts?

If those answers are spread across patterns and onboarding docs, repos drift in
how they interpret plans, capabilities, notebooks, and tests.

## Solution

Use one canonical planning operating model and treat this pattern as the
hierarchy view of that model.

**Canonical source:** [`../PLANNING_OPERATING_MODEL.md`](../PLANNING_OPERATING_MODEL.md)

The key rule is that the planning model is a **partial-order dependency graph**,
not a rigid waterfall. Some artifacts are iterative or can be compressed, but
certain dependencies are non-negotiable.

## Canonical Dependency Order

```text
North Star / Thesis
    -> Questions / Investigation
    -> Current-State Assessment
    -> Gap Analysis
    -> Capabilities / Boundary Docs / PRD surfaces
    -> Roadmap / Phases
    -> Bounded Plan
    -> Journey Notebook (for non-trivial multi-stage work)
    -> Tests / Gates
    -> Code
    -> Observability / Runtime evidence
```

`ADRs` are cross-cutting. They can be introduced whenever a durable design
choice needs to be recorded.

## Artifact Roles

| Layer | Primary question | Why it exists |
|-------|------------------|---------------|
| North star / thesis | Why does this system exist? | Aligns choices to value and long-term direction |
| Questions / investigation | What must be verified before planning? | Prevents guessing |
| Current-state assessment | What really exists today? | Critical for legacy repos |
| Gap analysis | What delta matters now? | Forces plans to target explicit gaps |
| Capabilities / boundaries / PRD surfaces | What enduring capability or contract are we shaping? | Defines system shape before sequencing |
| Roadmap / phases | What major gates and sequence matter? | Orders high-level progress |
| Plan | What bounded slice are we executing now? | Defines concrete steps, tests, and acceptance criteria |
| Journey notebook | How does the slice work end to end? | Makes phase contracts inspectable |
| Tests / gates | What proves the slice is done? | Verification before implementation and at closeout |
| Code | What is the implementation? | Realizes the bounded slice |
| Observability | How do we see runtime truth? | Prevents blind operation and stale claims |

## Strict Dependencies

These are framework rules, not suggestions:

- No bounded plan without investigation or explicit unresolved questions.
- No bounded plan without current-vs-target framing.
- No cross-project plan without capability or boundary clarity.
- No implementation without declared tests and acceptance criteria.
- No closeout without verification evidence.

## Recommended Sequencing

These are the defaults unless the work is trivial enough to compress them
honestly:

- define capability/boundary surfaces before roadmap phases
- define tests before code and follow TDD where feasible
- use a journey notebook for non-trivial multi-stage work
- keep observability in the design, not as a later add-on

## Agent Read Order

Before starting work on Plan #N:

1. Read the thesis or root `CLAUDE.md`.
2. Read the relevant investigation/current-state/gap materials.
3. Read the capability or boundary docs if the work crosses subsystem or repo lines.
4. Read the roadmap or phase gate that the work serves.
5. Read the plan itself.
6. Check the journey notebook if the work is multi-stage.
7. Verify the declared tests/gates before writing code.

## Compression Rules

Compression is allowed only when it stays truthful.

Acceptable compression examples:
- a trivial local refactor may not need roadmap changes
- a single-file internal fix may not need a capability doc
- a tiny isolated slice may not need a journey notebook

Unacceptable compression examples:
- skipping investigation and calling it “obvious”
- treating a cross-project interface change as internal-only work
- writing code before defining verification
- letting the easiest current slice redefine the intended architecture

## Relationship to Other Patterns

| Pattern | Role |
|---------|------|
| [Pattern #15](15_plan-workflow.md) | Bounded plan structure and status workflow |
| [Pattern #28](28_question-driven-planning.md) | Investigation before planning |
| [Pattern #30](30_gap-analysis.md) | Current-vs-target framing |
| [Pattern #36](36_executable-journey-notebooks.md) | Executable end-to-end journey rendering |

## Anti-patterns

| Anti-pattern | Failure mode |
|-------------|--------------|
| Roadmap before capability/boundary clarity | Phases optimize the wrong architecture |
| Plan before investigation | Agents implement guesses |
| Tests after code as an afterthought | Verification becomes weak or performative |
| Notebook omitted for complex multi-stage work | End-to-end contracts stay vague |
| Observability deferred | Runtime regressions are discovered too late |

## Enforcement

The operating model is enforced indirectly through several framework layers:

- plan templates and validation
- question-driven planning and gap-analysis patterns
- notebook expectations for non-trivial multi-stage work
- required tests and acceptance gates
- repo-local observability and runtime validation

This pattern defines the hierarchy view. The canonical policy semantics live in
[`../PLANNING_OPERATING_MODEL.md`](../PLANNING_OPERATING_MODEL.md).
