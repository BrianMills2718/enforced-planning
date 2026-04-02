# Static Graph and Runtime Truth

This document defines the architectural split between:

1. the **static planning/governance graph**
2. the **runtime coordination state**
3. the **validator layer** that checks agreement between them

This split exists so `relationships.yaml` can stay legible and durable while the
framework still validates live execution truth.

## Why This Split Exists

Two different kinds of facts live in the planning system:

- **static facts**
  - which docs govern which files
  - which docs must be reviewed when a source file changes
  - which capability or boundary docs are authoritative for a plan
  - which notebook, plan, and generated surface must remain aligned

- **runtime facts**
  - which worktree is active
  - which agent/session owns a claim
  - which plan number is reserved or consumed
  - whether a rollout has landed in canonical root
  - whether a tracker’s next step is already stale

Trying to store both classes of facts in the same YAML graph makes the graph too
opaque, too mutable, and too easy to drift.

## The Three-Layer Model

### 1. Static planning/governance graph

Canonical home: `relationships.yaml`

This layer answers:
- what must be read before editing?
- what documentation may need updating after changes?
- what architecture/capability/boundary docs govern a plan or file?
- what machine-generated surfaces have a `verify_sync` command?

Recommended edge classes:

- `adrs`
  - ADR metadata referenced by governance edges
- `governance`
  - source or surface -> ADR / governing docs / required reading
- `couplings`
  - source -> docs that must be reviewed or updated when the source changes
- `architecture`
  - source or plan -> architecture / boundary / PRD surfaces
- `plan_dependencies`
  - plan surfaces -> canonical methodology, templates, or roadmap docs
- `capability_surfaces`
  - capabilities -> boundary docs / schema docs / producers / consumers
- `notebook_links`
  - plan/notebook/evidence alignment edges
- `verify_sync`
  - command-backed generated surfaces
- `file_scope`
  - optional policy for managed vs unmanaged files

This layer should remain mostly repo-local and git-tracked.

### 2. Runtime coordination state

Canonical homes:
- active-work registry
- plan reservation store
- rollout audit output
- repo/worktree inspection

This layer answers:
- who is working on what now?
- which plan numbers are reserved or consumed now?
- which worktree or branch is active now?
- what canonical-root landing state exists now?
- what tracker is current now?

This layer is intentionally mutable and should not be forced into the static
relationship graph.

### 3. Truth-surface validator

Canonical role: compare static declarations and runtime facts.

Generated current-state surfaces should be rendered from validator or audit
output where feasible, rather than maintained as freehand prose.

This layer answers:
- does the active tracker reflect actual runtime progress?
- does a consumed reservation point to a real plan file?
- does a rollout doc claim canonical adoption when the audit disagrees?
- does a parent tracker still say “create worktree” when a claimed worktree
  already exists?

The validator consumes both layers but should not redefine them.

## Deterministic vs LLM Review

The truth-surface validator is intentionally **deterministic first**.

It is the right layer for:
- file existence
- plan-status parity
- tracker pattern vs registry contradictions
- claimed state vs measured audit state

These checks should remain programmatic because they need high-confidence,
repeatable failure semantics and should be eligible for hard enforcement.

Some drift is still too semantic or too cross-cutting for exact rules alone:
- a tracker is technically parseable but misleading or stale in prose
- multiple summaries disagree without sharing one exact machine-readable field
- a plan/TODO/roadmap set is individually valid but collectively no longer
  compendious

Those cases should be handled by an **optional LLM/agent review layer** that
reads the same truth surfaces and emits advisory findings. The framework should
use a hybrid model:

1. deterministic validator for exact contradictions and hard failures
2. optional LLM semantic review for ambiguity, misleading prose, and missing
   updates that static rules cannot enumerate cleanly
3. promotion path from repeated high-precision LLM findings into new
   deterministic checks when the pattern becomes stable

The LLM layer should complement the validator, not replace it.

## What Belongs in `relationships.yaml`

Belongs there:
- required reading defaults
- source-to-doc update couplings
- architecture/boundary/PRD authority links
- plan/notebook/evidence alignment links
- generated-surface sync commands
- file-scope policy

Does **not** belong there:
- active claims
- active sessions
- current worktree paths in use
- consumed reservations as live state
- canonical-root dirt state
- “current step” execution markers

## Recommended Static Graph Shape

```yaml
version: 2

required_reading:
  defaults:
    - CLAUDE.md

governance:
  - sources:
      - "scripts/meta/install_governed_repo.py"
    docs:
      - "docs/ops/GOVERNED_REPO_CONTRACT.md"
      - "PLANNING_OPERATING_MODEL.md"
    description: "Installer changes must honor the canonical operating model"

couplings:
  - sources:
      - "patterns/15_plan-workflow.md"
    docs:
      - "PLANNING_OPERATING_MODEL.md"
    description: "Plan workflow must stay aligned with the canonical model"

architecture:
  - sources:
      - "docs/plans/*.md"
    docs:
      - "PLANNING_OPERATING_MODEL.md"
    description: "Plans must align with the canonical methodology"

capability_surfaces:
  - capability: "shared_run_progress"
    docs:
      - "docs/SHARED_RUN_PROGRESS_BOUNDARY.md"
    producers:
      - "llm_client"
    consumers:
      - "Digimon_for_KG_application"

notebook_links:
  - plan: "docs/plans/24_shared_run_progress_integration_for_graph_builds.md"
    notebooks:
      - "notebooks/00_graph_build_journey.ipynb"
    evidence:
      - "evidence/graph_build_smoke.json"

verify_sync:
  - docs:
      - "generated/agent_docs/**/*.md"
    command: "python scripts/check_agent_docs_sync.py --check"
```

The exact schema can evolve, but the category split should remain.

## Relationship to the Planning Operating Model

The planning operating model defines the artifact dependency graph.
The static graph defines which files/docs/surfaces govern or align with each
other inside that model.

Examples:
- the operating model says plans depend on investigation and gap analysis
- the static graph can say `patterns/15_plan-workflow.md` must stay aligned with
  `PLANNING_OPERATING_MODEL.md`
- the runtime validator can then check whether the *active* tracker and plan
  state still match reality

## Transitional Rule

Existing repos may still use a smaller `relationships.yaml` with sections like:
- `adrs`
- `governance`
- `couplings`
- `architecture`
- `file_scope`

That is acceptable. The framework should expand these conservatively rather than
forcing all repos into an over-specified schema at once.

## Non-Goals

This document does not define the validator implementation itself. That belongs
to the truth-surface drift validation plan.
