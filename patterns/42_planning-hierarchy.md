# Pattern #42: Planning Hierarchy — From Thesis to Cell

**Complexity:** High (framework-level)
**Prerequisites:** Pattern #07 (ADR), #13 (Acceptance Gates), #15 (Plan Workflow), #27 (Conceptual Modeling), #36 (Executable Journey Notebooks)

## Problem

The ecosystem has many planning artifact types (thesis, ROADMAP, PRDs, ADRs, plans, notebooks, acceptance gates, data contracts) but no documented hierarchy showing how they relate. Agents create plans without referencing the thesis. PRDs exist without linking to ADRs. Notebooks don't reference plans. Each artifact type works in isolation.

For autonomous agents, this is critical: an agent needs to know **which artifacts to read before starting work** and **which artifacts to produce after completing work**. Without a clear hierarchy, agents skip steps or produce artifacts at the wrong level.

## Solution

Define a strict hierarchy of planning artifacts, from most strategic to most tactical. Each level references the one above and produces artifacts consumed by the one below.

## The Hierarchy

```
Level 0: THESIS / NORTH STAR
    "What are we building and why does it matter?"
    ↓ decomposes into
Level 1: ROADMAP / PHASES
    "What are the major milestones and gates?"
    ↓ decomposes into
Level 2: PRD / FEATURE SPECS
    "What exactly does this capability do?"
    ↓ decisions recorded as
Level 2.5: ADRs
    "What did we decide and why?"
    ↓ decomposes into
Level 3: PLANS
    "What steps, in what order, with what acceptance criteria?"
    ↓ specifies boundaries in
Level 3.5: CAPABILITIES (in plan template)
    "What typed data crosses project lines?"
    ↓ concretized as
Level 4: JOURNEY NOTEBOOKS
    "Show me the end-to-end data flow as executable pseudocode"
    ↓ validated by
Level 4.5: SCHEMA VALIDATION CELLS
    "Do the Pydantic schemas between steps actually align?"
    ↓ implemented as
Level 5: CODE + @boundary + @tool
    "The real implementation with runtime contract enforcement"
    ↓ verified by
Level 6: TESTS + ACCEPTANCE GATES
    "Proof that it works"
    ↓ observed by
Level 7: DASHBOARD + OBSERVABILITY
    "Continuous visibility into what's running, what's broken, what's stale"
```

## Artifact Types at Each Level

### Level 0: Thesis / North Star

**What:** One document stating the vision, the value proposition, and why this exists.

**Where it lives:**
- `project-meta/vision/FRAMEWORK.md` — timeless architecture
- `project-meta/vision/AUTONOMOUS_ECOSYSTEM_NORTH_STAR.md` — the thesis
- Per-project: root section of CLAUDE.md ("What is this project?")

**Who reads it:** Humans (for alignment), agents (for context on why work matters).

**Key question it answers:** "If an agent is choosing between two approaches, which one aligns with the thesis?"

### Level 1: Roadmap / Phases

**What:** Ordered phases with goals, gates, and step tables. Each phase has concrete acceptance criteria for the gate.

**Where it lives:**
- `project-meta/vision/ROADMAP.md` — ecosystem-wide
- Per-project: `ROADMAP.md` or similar

**References:** Level 0 (thesis explains why these phases matter)

**Key question it answers:** "What must be true before we move to the next phase?"

### Level 2: PRD / Feature Specs / Boundary Docs

**What:** Detailed specification of a capability, boundary, or convergence point. Defines what the system does, not how.

**Where it lives:**
- `project-meta/vision/*_BOUNDARY_V0.md` — boundary ownership docs
- `project-meta/vision/*_CONVERGENCE.md` — cross-project data flow specs
- `AUTONOMOUS_SYSTEM_PRD.md` — full PRD

**References:** Level 1 (which phase this enables)

**Key question it answers:** "What exactly does this capability produce, consume, and guarantee?"

### Level 2.5: ADRs (Architecture Decision Records)

**What:** Decisions made during design, with context, alternatives considered, and rationale. Immutable once ratified.

**Where it lives:**
- `docs/adr/` or `adr/` per project
- `enforced-planning/adr/` for framework-level decisions

**References:** Level 2 (which spec prompted this decision)

**Key question it answers:** "Why did we choose X over Y, and under what conditions would we revisit?"

### Level 3: Plans

**What:** Concrete implementation plans with steps, acceptance criteria, blocked-by/blocks, files affected.

**Where it lives:**
- `docs/plans/` per project
- Follows `plan.md.template`

**References:** Level 2/2.5 (which spec and decisions this implements)

**Required sections:** Status, Type, Priority, Blocked By, Blocks, Gap, References Reviewed, Files Affected, **Capabilities** (if cross-project), Steps, Required Tests, Acceptance Criteria

### Level 3.5: Capabilities (in plan template)

**What:** The Capabilities table in the plan template. Declares what typed data crosses project lines — each capability names its input/output Pydantic schemas, producer, consumer(s), and cost tier.

> Previously called "Data Boundaries". The template section is named "Capabilities" because a capability IS a tool IS a boundary IS a notebook cell — one definition, four views.

**Where it lives:** Inside each plan file (Level 3), `## Capabilities` section

**References:** Level 2 (boundary specs define the contracts)

**Key question it answers:** "What Pydantic model does step N produce, and does the consumer's schema match?"

### Level 4: Journey Notebooks

**What:** Executable pseudocode showing end-to-end data flow. Each cell crosses a boundary with a visible schema. Starts as pseudocode, becomes real code.

**Where it lives:**
- `notebooks/` per project
- One notebook per user journey

**References:** Level 3 (each cell links to a plan step), Level 3.5 (schemas from Capabilities table)

**Key question it answers:** "Show me the data flowing through the system, step by step, with types."

### Level 4.5: Schema Validation Cells

**What:** Cells within notebooks that validate producer/consumer schema compatibility. Run in Phase 2 before implementation.

**Where it lives:** Inside journey notebooks (Level 4)

**References:** Level 3.5 (validates the declared capabilities/boundaries)

**Key question it answers:** "Do the schemas actually align, or will this break at integration time?"

### Level 5: Code + @boundary + @tool

**What:** The implementation. Functions decorated with `@boundary` for contract enforcement and `@tool` for observability.

**Where it lives:** Source code in each project

**References:** Level 3 (implements the plan steps), Level 4 (matches what the notebook specified)

### Level 6: Tests + Acceptance Gates

**What:** Automated proof that the implementation meets the plan's acceptance criteria.

**Where it lives:**
- `tests/` per project
- Acceptance gate YAML files (Pattern #13)

**References:** Level 3 (tests verify acceptance criteria), Level 4 (notebook is the integration test)

### Level 7: Dashboard + Observability

**What:** Continuous visibility. Plan graph, contract status, tool registry, anomaly detection, agent activity.

**Where it lives:**
- `ecosystem-ops/` — data layer
- Dashboard at localhost:8501 — human view

**References:** All levels (aggregates state from plans, contracts, tools, tests)

## How an Agent Uses the Hierarchy

Before starting work on Plan #N:

1. **Read Level 0** — understand the thesis (CLAUDE.md root)
2. **Read Level 1** — which ROADMAP phase does this plan serve?
3. **Read Level 2/2.5** — any boundary specs or ADRs relevant?
4. **Read Level 3** — the plan itself (steps, criteria, capabilities)
5. **Check Level 4** — is there a journey notebook? Check execution modes.
6. **Run Level 4.5** — do schema validation cells pass?
7. **Implement Level 5** — write code with `@boundary` decorators
8. **Verify Level 6** — run tests, check acceptance criteria
9. **Observe Level 7** — verify dashboard reflects the change

After completing work:

1. **Update Level 3** — mark plan steps as done
2. **Update Level 4** — replace pseudocode cells with real code
3. **Update Level 7** — run `make consistency` to verify contracts

## Anti-patterns

| Anti-pattern | What goes wrong |
|-------------|-----------------|
| Skip Level 3 (no plan) | Agent implements without criteria — can't verify success |
| Skip Level 3.5 (no boundaries) | Integration breaks because schemas weren't negotiated |
| Skip Level 4 (no notebook) | Human reviewer can't understand the end-to-end flow |
| Skip Level 4.5 (no schema validation) | Contract mismatches discovered at runtime, not planning time |
| Create Level 5 before Level 3 (code before plan) | Work may be misaligned with thesis/roadmap |
| Create Level 4 as governance assertions | Notebook checks file existence instead of showing data flow |

## Enforcement

| Level | How enforced |
|-------|-------------|
| 0-1 | Manual (human writes thesis/roadmap) |
| 2-2.5 | Pre-commit: ADR governance (Pattern #08) |
| 3 | Pre-commit: plan validation (Pattern #23) |
| 3.5 | Pre-commit: boundary check (`check_plan_boundaries.py`) |
| 4 | Manual (notebook-planning skill encourages) |
| 4.5 | Notebook execution (cells either pass or fail) |
| 5 | Runtime: `@boundary` raises ContractViolation |
| 6 | CI: tests must pass |
| 7 | Cron: daily pipeline runs automatically |

## Relationship to Other Patterns

| Pattern | Role in hierarchy |
|---------|------------------|
| #07 (ADR) | Level 2.5 — records decisions |
| #13 (Acceptance Gates) | Level 6 — formal verification |
| #15 (Plan Workflow) | Level 3 — plan structure |
| #27 (Conceptual Modeling) | Level 2 — domain model definition |
| #28 (Question-Driven Planning) | Level 3 — investigation before planning |
| #29 (Uncertainty Tracking) | Level 3 — tracking unknowns |
| #36 (Journey Notebooks) | Level 4 — executable specifications |
| Data Contracts | Level 3.5 + 5 — schema definition + runtime enforcement |
