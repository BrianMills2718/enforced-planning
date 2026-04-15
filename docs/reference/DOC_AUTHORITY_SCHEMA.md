# Reference: Document Authority Schema

## Purpose

This schema defines the machine-readable documentation-authority contract for a
governed repo.

It has two layers:

- indexed authority surfaces for deterministic drift checks such as plan indexes
- an optional recursive documentation spine for bounded ancestry and required
  read closure

The goal is to make documentation authority explicit and validatable without
turning git into a full document-management system.

## Schema Versions

### Schema v1

Schema v1 supports indexed authority surfaces only.

Example:

```yaml
schema_version: 1
indexed_authority_surfaces:
  - concern: active-plan-index
    kind: plan_index
    authority_surface: docs/plans/CLAUDE.md
    source_glob: docs/plans/[0-9]*_*.md
    resolution_mode: manual
```

### Schema v2

Schema v2 keeps the indexed authority surface rules and adds the bounded
recursive documentation spine.

Example:

```yaml
schema_version: 2
indexed_authority_surfaces:
  - concern: active-plan-index
    kind: plan_index
    authority_surface: docs/plans/CLAUDE.md
    source_glob: docs/plans/[0-9]*_*.md
    resolution_mode: manual

doc_spine:
  root_doc: EXECUTION_BRIEF.md
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

docs:
  - path: EXECUTION_BRIEF.md
    authority: canonical
    doc_status: active
    concerns: [execution_brief]
    role: execution_brief
    primary_parent: null

  - path: docs/overview/GAP_SUMMARY.md
    authority: canonical
    doc_status: active
    concerns: [gap_summary]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
    required_context:
      - path: docs/overview/CURRENT_STATE.md
        reason: Gap summaries are only meaningful when read against current state.

  - path: docs/plans/55_example.md
    authority: canonical
    doc_status: active
    concerns: []
    role: plan
    primary_parent: docs/overview/GAP_SUMMARY.md
    governed_by:
      - adr/0009-doc-authority-governance-and-enforcement.md

code_surfaces:
  - paths:
      - enforced_planning/doc_authority.py
      - tests/test_validate_doc_authority.py
    primary_spec: docs/plans/55_example.md
```

## Indexed Authority Surfaces

These rules validate summary or index files against their authoritative artifact
sets.

### Fields

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `concern` | string | yes | Concern name for one indexed surface |
| `kind` | enum | yes | `plan_index` in the current implementation |
| `authority_surface` | path | yes | Canonical index or summary surface |
| `source_glob` | glob | yes | Authoritative artifact set that the surface must index |
| `resolution_mode` | enum | yes | `manual` or `generated` |

## Recursive Doc Spine

The doc spine models progressive disclosure.

### `doc_spine`

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `root_doc` | path | yes for v2 | Root execution brief for the repo |
| `required_concerns` | list[str] | yes for v2 | Concerns that must exist somewhere in the active spine |
| `max_required_read_docs` | int | no | Warning threshold for total mandatory docs in one code-surface closure |
| `max_required_read_words` | int | no | Warning threshold for total mandatory words in one code-surface closure |

### `role_budgets`

Per-role document size budgets.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `max_words` | int | optional | Max allowed words for docs with this role |
| `summary_max_words` | int | optional | Optional summary-block limit for long-form roles |

### `docs`

Authority-bearing docs in the recursive spine.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `path` | path | yes | Repo-relative document path |
| `authority` | enum | yes | `canonical`, `derived`, `working`, or `historical` |
| `doc_status` | enum | yes | `active`, `superseded`, or `archived` |
| `concerns` | list[str] | yes | Concerns satisfied by this doc; may be empty for leaf plan/spec docs |
| `role` | string | yes | Role used for size-budget validation |
| `primary_parent` | path or null | yes | Parent doc in the abstraction spine; `null` only for the root doc |
| `governed_by` | list[path] | no | ADR or policy docs that govern this doc |
| `required_context` | list[mapping] | no | Additional mandatory reads not captured by ancestry |

### `required_context` entry

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `path` | path | yes | Mandatory extra read |
| `reason` | string | yes | Why the extra read is required |
| `when` | string | no | Optional work-type selector such as `behavior_change` |

### `code_surfaces`

Bounded file or glob sets that map code changes to one leaf spec.

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `paths` | list[path/glob] | yes | Managed code-surface paths |
| `primary_spec` | path | yes | Leaf doc the code surface is governed by |

## Validation Semantics

### Structural failures

The current implementation blocks on:

- missing `root_doc`
- missing required concerns
- missing authority docs
- non-root docs without `primary_parent`
- root docs with `primary_parent`
- unknown `primary_parent`
- ancestry cycles
- missing `required_context.reason`
- missing `required_context.path`
- missing `governed_by` paths
- code surfaces whose `primary_spec` does not exist in `docs`
- existing indexed-surface failures such as plan-index drift and missing
  reconciliation obligations

### Warning-only checks in v2

The current implementation warns on:

- role budget overages
- required-read doc count overages
- required-read word count overages

## Reconciliation Obligations

Open obligations live under:

- `~/.claude/coordination/authority_obligations/*.yaml`

They are used for indexed authority drift when the authoritative artifact lands
before the separately claimed authority surface can be updated.

Example:

```yaml
obligation_id: enforced-planning-abc123def456
project: enforced-planning
concern: active-plan-index
authority_surface: docs/plans/CLAUDE.md
artifact_path: docs/plans/41_doc-authority-governance-and-enforcement.md
required_action: add Plan #41 to docs/plans/CLAUDE.md
created_by_agent: codex
created_by_scope: authority-drift-reconciliation-gates
plan_ref: Plan #41
owner_scope: plan-index-maintenance
status: open
created_at: 2026-04-05T00:00:00+00:00
resolved_at: null
notes: optional
```

## Failure Codes

Representative deterministic failure codes:

- `required_concern_missing`
- `duplicate_active_canonical_concern`
- `root_doc_missing`
- `root_doc_has_parent`
- `doc_spine_orphan_doc`
- `doc_spine_missing_primary_parent`
- `doc_spine_cycle`
- `required_context_missing_reason`
- `required_context_path_missing`
- `governed_by_path_missing`
- `code_surface_primary_spec_missing`
- `role_budget_exceeded`
- `required_read_budget_exceeded`
- `authority_surface_missing_artifact`
- `authority_surface_status_mismatch`
- `missing_reconciliation_obligation`
- `unowned_authority_drift`
- `generated_authority_surface_requires_regeneration`

## Notes

- Paths remain repo-relative.
- Validation should fail loudly on malformed config or malformed authority
  structure.
- The first recursive-spine implementation remains in `scripts/doc_authority.yaml`.
  It does not yet merge into `relationships.yaml`.
