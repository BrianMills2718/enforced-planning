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
required_concerns:
  - product-story
  - roadmap
  - active-plan-index

canonical_map:
  product-story: README.md
  roadmap: ROADMAP.md
  active-plan-index: docs/plans/CLAUDE.md

singleton_concerns:
  - active-handoff
  - benchmark-status

allow_multi_canonical: []

derived_require_source_ref: true
```

### Fields

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `required_concerns` | list[str] | no | Concerns that must exist in this repo |
| `canonical_map` | mapping | recommended | Expected canonical file for each concern |
| `singleton_concerns` | list[str] | recommended | Concerns that must have exactly one active canonical doc |
| `allow_multi_canonical` | list[str] | optional | Explicit exceptions |
| `derived_require_source_ref` | bool | optional | Whether derived docs must declare `canonical_source` |

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
