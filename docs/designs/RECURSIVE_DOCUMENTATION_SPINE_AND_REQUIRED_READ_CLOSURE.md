# Design: Recursive Documentation Spine And Required-Read Closure

**Status:** Design draft
**Date:** 2026-04-12
**Depends on:** `PLANNING_OPERATING_MODEL.md`, `adr/0009-doc-authority-governance-and-enforcement.md`

## Problem

The framework already has three important pieces:

- a planning hierarchy with current state, target state, and gap analysis
- concern-level documentation authority
- file-to-doc and file-to-ADR read-gating

What it does not yet have is a **recursive abstraction spine** that makes the
big picture mandatory when working on a specific leaf.

Current failure mode:

1. the repo accumulates many useful docs
2. leaf plans and specs get more precise
3. the top-level system story becomes easier to miss during implementation
4. agents satisfy local doc-coupling rules while still missing the intended
   subsystem and repo-level framing

This is a documentation-shape problem, not just a missing-doc problem.

## Goals

- preserve one small top-level execution brief for the repo
- support recursive abstraction rather than hand-maintained fixed tiers
- require edits to load the leaf spec plus its ancestor chain
- make extra required reading explicit and justified, not implicit in every
  cross-link
- turn target-state, current-state, and gap-summary surfaces into first-class
  authority concerns
- keep mandatory context bounded through role-based budgets

## Non-Goals

- replace ADR governance
- replace source/doc coupling
- require every repo to use a large multi-file doc tree
- force all repos into the same directory structure
- solve prose quality or stylistic editing

## Design Constraints From Existing Framework Decisions

1. The first implementation slice must remain compatible with
   [ADR-0009](../../adr/0009-doc-authority-governance-and-enforcement.md) and
   [Plan #41](../plans/41_doc-authority-governance-and-enforcement.md):
   the first implementation should extend the dedicated doc-authority config,
   not merge directly into `relationships.yaml`.
2. The planning operating model already requires current-state assessment, gap
   analysis, and north-star definition. The new design should make those
   surfaces more enforceable, not invent a parallel planning hierarchy.
3. Small repos must be able to compress roles truthfully into one document.

## Core Idea

Every governed repo gets one **documentation spine**:

- one root execution brief
- every authority-bearing doc has exactly one `primary_parent`, except the root
- code or code scopes point to one `primary_spec`
- required reading is the `primary_spec` plus its ancestor chain, plus explicit
  extra required context

This gives:

- progressive disclosure for humans
- deterministic read closure for agents
- bounded context budgets

## Model

### 1. Root Execution Brief

Every non-trivial governed repo should have one canonical root execution brief.

Its job is to answer only:

- what the repo is for
- what the current execution gate is
- what workstreams are active
- what the top current risks are
- where the next-lower-level docs live

This is the root of the primary documentation spine. It should be cheap to read
in one pass.

### 2. Recursive Primary-Parent Tree

Each authority-bearing doc may have:

- exactly one `primary_parent`
- any number of advisory `related` links

Depth is derived from the parent chain. The system does **not** require
hand-maintained fixed tiers. "Tier" is only a computed view of depth and role.

This avoids graph explosion:

- ancestry is mandatory
- cross-links are not mandatory unless explicitly marked otherwise

### 3. Code-Surface Mapping

Each managed code surface gets one `primary_spec`.

That can be:

- one file
- one glob/pattern
- one declared subsystem scope

The `primary_spec` is the leaf documentation entrypoint for that code surface.

### 4. Edge Types

The design uses these edge semantics:

| Edge | Meaning | Required by default |
|------|---------|---------------------|
| `primary_parent` | Parent in the abstraction spine | yes |
| `primary_spec` | Leaf doc a code surface is governed by | yes |
| `governed_by` | ADR/policy docs that constrain implementation | yes |
| `required_context` | Additional mandatory read not captured by ancestry | yes, when present |
| `related` | Helpful cross-link or neighboring context | no |
| `supersedes` | Lifecycle relationship for old vs new docs | yes for governed authority transitions |

`required_context` must always include:

- `path`
- `reason`

It may optionally include:

- `when` — for example `all`, `behavior_change`, `schema_change`,
  `interface_change`, `design_only`

### 5. Required-Read Closure

For an edit to a managed code surface, the required-read closure is:

1. repo defaults such as `CLAUDE.md`
2. governing ADRs/policies
3. the code surface's `primary_spec`
4. the full `primary_parent` chain from that spec to the root execution brief
5. any `required_context` edges triggered by the current work type

`related` docs are advisory only.

This rule answers the exact failure mode that prompted this design:

- editing `x.py` requires the leaf spec
- and the subsystem summary
- and the repo-level execution brief

not just the leaf doc in isolation.

### 6. Required Concerns

For non-trivial repos, the framework should require these concerns to exist in
the documentation spine:

- `execution_brief`
- `north_star`
- `current_state`
- `gap_summary`
- `roadmap`
- `active_plan_index`

Important: these are **concerns**, not necessarily six different files.

Allowed compression:

- a small repo may satisfy `execution_brief`, `north_star`, `current_state`, and
  `roadmap` in one file
- a larger repo may split those into separate child docs beneath the execution
  brief

The validator should enforce concern coverage, not a rigid file count.

### 7. Role-Based Budgets

Budgets should be based primarily on **role**, not raw depth.

Rationale:

- higher-abstraction docs have higher fan-in and must stay cheap to reread
- deeper docs may need more detail, but only within their narrower scope
- investigative/report surfaces can be long if they begin with a compact summary

Suggested default budgets:

| Role | Budget |
|------|--------|
| `execution_brief` | max 1200 words |
| `north_star` / `current_state` / `gap_summary` / `roadmap` / subsystem summary | max 2000 words |
| `plan` / `adr` / spec doc | max 3500 words |
| `investigation` / `report` | unbounded body, but must start with a summary block of <= 300 words |

These are defaults, not absolutes. Repos may override them in config.

### 8. Required-Read Budget

The framework should also bound the **mandatory closure**, not just individual
doc sizes.

Suggested defaults:

- `max_required_read_docs: 7`
- `max_required_read_words: 8000`

If a file's mandatory closure exceeds that, the documentation structure is
likely wrong:

- too many explicit required reads
- ancestry chain too deep
- summaries too large

Version 1 should warn. Later rollouts may block fully adopted repos.

## Proposed Config Extension

Extend the dedicated authority config described in
`docs/reference/DOC_AUTHORITY_SCHEMA.md`.

Suggested v1 shape:

```yaml
schema_version: 2

doc_spine:
  root_doc: docs/EXECUTION_BRIEF.md
  required_concerns:
    - execution_brief
    - north_star
    - current_state
    - gap_summary
    - roadmap
    - active_plan_index
  max_required_read_docs: 7
  max_required_read_words: 8000

role_budgets:
  execution_brief:
    max_words: 1200
  summary:
    max_words: 2000
  plan:
    max_words: 3500
  investigation:
    summary_max_words: 300

docs:
  - path: docs/EXECUTION_BRIEF.md
    authority: canonical
    doc_status: active
    concerns: [execution_brief, north_star]
    role: execution_brief
    primary_parent: null

  - path: docs/architecture/current.md
    authority: canonical
    doc_status: active
    concerns: [current_state]
    role: summary
    primary_parent: docs/EXECUTION_BRIEF.md

  - path: docs/architecture/gaps.md
    authority: canonical
    doc_status: active
    concerns: [gap_summary]
    role: summary
    primary_parent: docs/EXECUTION_BRIEF.md

  - path: docs/plans/22_example.md
    authority: working
    doc_status: active
    concerns: []
    role: plan
    primary_parent: docs/architecture/gaps.md
    required_context:
      - path: adr/0007-example.md
        reason: governs the boundary this plan changes
        when: behavior_change

code_scopes:
  - patterns: ["src/payments/**"]
    primary_spec: docs/architecture/current.md
    governed_by: ["adr/0007-example.md"]
```

## Validator Rules

### Structural Rules

- exactly one active canonical root execution brief per repo
- every authority-bearing doc except the root has exactly one `primary_parent`
- no cycles in the `primary_parent` graph
- every `primary_parent` chain resolves to the root execution brief
- every managed code scope has exactly one `primary_spec`
- every `required_context` edge includes a non-empty `reason`

### Concern-Coverage Rules

- required concerns must exist
- multiple concerns may map to the same file
- one file may satisfy multiple required concerns if it remains within role
  budget

### Budget Rules

- role-size budget violations: warning in v1
- required-read closure over budget: warning in v1
- blocking later only for repos that explicitly adopt the stricter stage

### Plan-Validation Rules

For files covered by architecture/spine metadata, bounded plans should cite the
relevant governed docs through one of these paths:

- direct citation of the leaf spec and explicit current/target/gap docs
- or direct citation of the leaf spec plus its machine-resolved ancestor chain

The validator should accept either, but it should not allow plans to ignore the
current/target/gap surfaces entirely when they are declared for that code area.

## Read-Gating Integration

`file_context.py` or its successor should compute:

- repo defaults
- governing ADRs
- `primary_spec`
- ancestor chain to the root
- triggered `required_context` docs
- advisory `related` docs separately

The hook should then enforce:

- ancestry and governance must be read
- triggered required context must be read
- related docs are suggested but not required

## Relationship to Existing Framework Pieces

| Existing piece | Role after this design |
|----------------|------------------------|
| `PLANNING_OPERATING_MODEL.md` | still defines the artifact hierarchy; this design makes the repo-local doc spine enforceable |
| doc-authority config | becomes the host for recursive spine metadata in the first implementation |
| `relationships.yaml` | still handles couplings/governance; possible later merger remains open |
| `file_context.py` | becomes the execution engine for ancestry closure |
| plan validation | gains stronger required-read validation based on spine metadata |
| doc-authority validator | gains concern coverage and root/ancestry checks |

## Rollout

### Stage 1: Advisory Metadata

- repos declare root execution brief
- repos add `primary_parent` and `primary_spec` for the most important surfaces
- validator warns on missing ancestry or missing required concerns

### Stage 2: Structural Blocking

- block cycles
- block missing root
- block missing `primary_spec` for managed scopes
- block malformed `required_context`

### Stage 3: Concern Coverage

- require `north_star`, `current_state`, `gap_summary`, `roadmap`, and
  `active_plan_index` concerns for non-trivial repos
- allow one file to satisfy multiple concerns

### Stage 4: Read-Closure Enforcement

- read-gating requires the full ancestor chain
- required-read budget warnings appear

### Stage 5: Tightened Budgets

- selected repos may opt into blocking size/read-budget enforcement once their
  spine is stable

## Why This Should Stay Mostly Custom

Off-the-shelf tools help with:

- markdown link validation
- frontmatter parsing
- pre-commit/CI execution

But the actual model remains repo-governance-specific:

- recursive abstraction ancestry
- concern coverage
- code-surface-to-primary-spec mapping
- required-read closure

This is not a generic docs lint problem.

## Migration Example

For a repo like DIGIMON:

- `START_HERE.md` or a new execution brief becomes the root
- `CURRENT_STATUS.md`, roadmap, and authority map become required concerns
- subsystem docs become children beneath the brief
- benchmark controller files map to benchmark-lane plans/specs
- editing controller code requires the leaf plan/spec plus the benchmark-lane
  summary plus the root brief

That is the intended operator experience: specific context without losing the
repo story.

## Open Questions

1. Should the first implementation store per-doc metadata entirely in config, or
   should it require frontmatter immediately?
2. Should plan validation accept ancestry-derived current/target/gap coverage, or
   require explicit citations for human readability?
3. Should `required_context.when` be a fixed enum in v1 or an open string with a
   small recommended vocabulary?

These do not block the design.
