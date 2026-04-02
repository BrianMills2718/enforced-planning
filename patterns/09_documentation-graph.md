# Pattern: Documentation Graph

## Problem

Repositories need a machine-readable graph that answers static governance
questions such as:

- what docs must be read before editing a file?
- what docs may need updating when a file changes?
- what architecture or boundary docs govern a plan or subsystem?
- what generated surfaces must stay in sync with source artifacts?

At the same time, the ecosystem also has runtime coordination facts:
- active claims
- reservations
- worktree state
- rollout landing state
- tracker progress

These are not the same kind of truth. Mixing them into one graph makes the
result too overloaded and hard to reason about.

## Solution

Use a **static documentation/planning graph** for durable relationships and keep
**runtime coordination state** in separate stores.

Canonical references:
- [`../PLANNING_OPERATING_MODEL.md`](../PLANNING_OPERATING_MODEL.md) — defines the planning artifact dependency model
- [`../STATIC_GRAPH_AND_RUNTIME_TRUTH.md`](../STATIC_GRAPH_AND_RUNTIME_TRUTH.md) — defines the static-vs-runtime split

## What This Pattern Owns

This pattern owns the static graph, usually in `scripts/relationships.yaml`.

It should cover:
- required-reading defaults
- source-to-doc update couplings
- architecture / boundary / PRD authority links
- plan / notebook / evidence alignment links
- generated-surface sync checks
- optional file-scope policy

It should not store:
- active claims or sessions
- plan reservations as live state
- current worktree status
- tracker progress markers
- canonical-root landing state

## Canonical Shape

```yaml
version: 2

required_reading:
  defaults:
    - CLAUDE.md

adrs: {}
governance: []
couplings: []
architecture: []
notebook_links: []
capability_surfaces: []
verify_sync: []
```

Repos can adopt a smaller subset, but the graph should stay static and durable.

## Relationship to Other Patterns

| Pattern | Relationship |
|---------|--------------|
| [Plan Workflow](15_plan-workflow.md) | Plans cite the docs this graph routes them to |
| [Question-Driven Planning](28_question-driven-planning.md) | Investigation produces the evidence that plans then cite |
| [Gap Analysis](30_gap-analysis.md) | Plans link current vs target state against docs routed by this graph |
| [Executable Journey Notebooks](36_executable-journey-notebooks.md) | Notebook links can be represented as static alignment edges |
| [Planning Hierarchy](42_planning-hierarchy.md) | The graph supports the artifact model; it does not replace it |

## Validation Model

This pattern supports validators such as:
- required-reading gates
- doc-code coupling checks
- plan validation against governing docs
- generated-surface sync checks

Runtime truth-surface drift validation is a separate layer.

## Transitional Guidance

Older repos may still use narrower templates such as `doc_coupling.yaml.example`
or minimal `relationships.yaml` scaffolds. New repos should prefer the canonical
`relationships.yaml.example` scaffold and keep runtime state elsewhere.
