# Gap Summary

## Highest-Value Gap

The framework can define a recursive documentation spine, but it does not yet
use that spine itself.

This creates a credibility and usability gap:

- downstream repos would be asked to adopt a model the framework has not proven
- validators and read-gating still operate on local couplings without the full
  abstraction ancestry
- the big picture can still be lost when working from a leaf implementation doc

## Target State

The target state for the current slice is:

- one root execution brief for this repo
- durable `north_star`, `current_state`, `gap_summary`, `roadmap`, and
  `active_plan_index` concerns
- machine-readable doc-spine ancestry in `scripts/doc_authority.yaml`
- authority validation for concern coverage, ancestry integrity, and bounded
  required-read budgets
- file context and plan validation that require leaf spec plus ancestor chain
  for the managed dogfood surfaces

## Active Slice

[Plan #55](../plans/55_enforced-planning_recursive_doc_spine_dogfood.md) is the
current bounded slice that closes this gap.

Its scope is intentionally narrow:

- documentation-governance subsystem
- authority config and validator
- file-context/read-gating surface
- plan validation surface

It is not a full-repo migration.
