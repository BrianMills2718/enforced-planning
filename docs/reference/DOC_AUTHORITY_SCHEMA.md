# Reference: Document Authority Schema v0

## Purpose

This schema describes the minimum portable metadata and repo config needed for
documentation authority governance.

It is intentionally small. The goal is to make authority explicit and
validatable, not to invent a large doc CMS inside git.

## Per-Document Metadata

Recommended YAML frontmatter:

```yaml
authority: canonical
concern: benchmark-status
doc_status: active
supersedes: []
superseded_by: null
canonical_source: null
last_verified_against:
  - results/MuSiQue_latest.json
```

### Fields

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `authority` | enum | yes | `canonical`, `derived`, `working`, or `historical` |
| `concern` | string | yes for authority-bearing docs | Concern this doc belongs to |
| `doc_status` | enum | yes | `active`, `superseded`, or `archived` |
| `supersedes` | list[str] | no | Older docs intentionally replaced by this doc |
| `superseded_by` | string or null | no | Newer doc that replaces this one |
| `canonical_source` | string or null | required for derived docs | Path to upstream canonical doc |
| `last_verified_against` | list[str] | optional | Artifacts, code surfaces, or configs used to verify the doc |

## Repo Config

Suggested file: `scripts/doc_authority.yaml`

```yaml
schema_version: 1
indexed_authority_surfaces:
  - concern: active-plan-index
    kind: plan_index
    authority_surface: docs/plans/CLAUDE.md
    source_glob: docs/plans/[0-9]*_*.md
    resolution_mode: manual
```

### Fields

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `schema_version` | int | yes | Config schema version |
| `indexed_authority_surfaces` | list[mapping] | yes for v0 | Indexed authority surfaces to validate deterministically |
| `concern` | string | yes | Concern name for one indexed surface |
| `kind` | enum | yes | `plan_index` in v0 |
| `authority_surface` | path | yes | Canonical index/governance surface |
| `source_glob` | glob | yes | Authoritative artifact set that the surface must index |
| `resolution_mode` | enum | yes | `manual` or `generated`; generated surfaces should be regenerated rather than assigned durable debt |

Later schema additions may restore broader concern maps, singleton rules, and
per-doc metadata enforcement without changing the obligation model.

## Default Rules

Unless the repo config overrides them:

- each concern may have at most one active canonical doc
- `historical` docs should not be `active`
- `derived` docs should not be canonical for a singleton concern
- `working` docs are never source-of-truth

## Failure Codes

Suggested deterministic failure codes:

| Code | Meaning |
|------|---------|
| `duplicate_active_canonical_concern` | More than one active canonical doc for a concern |
| `canonical_map_mismatch` | Config says one file is canonical but doc metadata disagrees |
| `active_doc_marked_superseded` | Active doc has incompatible lifecycle metadata |
| `duplicate_active_handoff` | More than one active handoff-like concern |
| `derived_missing_canonical_source` | Derived doc lacks upstream canonical pointer |
| `required_concern_missing` | Repo config requires a concern with no matching active canonical doc |
| `authority_surface_missing_artifact` | Indexed authority surface is missing a landed authoritative artifact |
| `authority_surface_status_mismatch` | Indexed authority surface disagrees with the authoritative artifact status |
| `missing_reconciliation_obligation` | Authority surface owner exists but drift was not recorded formally |
| `unowned_authority_drift` | Drift exists and no active lane owns the authority surface |
| `generated_authority_surface_requires_regeneration` | Generated authority surface drift must be fixed by regeneration |

## Reconciliation Obligations

Open obligations live under:

- `~/.claude/coordination/authority_obligations/*.yaml`

v0 obligation fields:

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

Owning lanes must resolve or clear the relevant obligations before
`session-finish` can complete cleanly.

## Migration Guidance

Phase-in order:

1. add metadata only to canonical docs
2. declare a small concern map
3. validate in warn-only mode
4. enforce singleton concerns
5. expand to derived and historical docs

## Notes

- This schema is intentionally compatible with later integration into
  `relationships.yaml`, but that merge is not assumed in v0.
- Paths should remain repo-relative.
- Validation should fail loudly on malformed metadata rather than silently
  treating the doc as ungoverned.
