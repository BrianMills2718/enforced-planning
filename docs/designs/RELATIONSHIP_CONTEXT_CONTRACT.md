# Relationship Context Contract

**Status:** Accepted for visibility-first implementation
**Policy:** `project-meta/docs/ops/ADR-2026-07-14-context-docstrings-and-exhaustive-relationships.md`
**Plan:** #63

## Goal

Compile every Git-tracked artifact into a deterministic inventory and extract
its source-local semantic summary without importing or executing repository
code. This is the foundation for bounded edit context, reconciliation
obligations, plan freshness, and a generated docstring wiki.

## Boundary

Inputs:

- a Git repository root;
- tracked paths from `git ls-files -z`;
- source bytes at the working-tree revision; and
- later, reviewed relationship declarations from `scripts/relationships.yaml`.

Outputs:

- typed in-process records;
- deterministic JSON for agents and later renderers; and
- explicit diagnostics for missing or invalid summaries.

The compiler never imports target modules, mutates source, invents summaries,
or treats generated output as authority.

## Domain Model

### `ArtifactRecord`

| Field | Contract |
|---|---|
| `path` | normalized repository-relative tracked path; stable file identity |
| `format` | `python`, `markdown`, `text`, `data`, `binary`, or `other` |
| `classification` | `source`, `test`, `documentation`, `generated`, `vendored`, `fixture`, `archive`, or `other` |
| `working_tree_state` | `present`, `missing`, or `symlink`; deleted tracked files remain represented |
| `summary` | source-extracted compact summary or `null` |
| `summary_source` | exact source construct, never free-form registry prose |
| `symbols` | statically extracted Python symbol records |
| `diagnostics` | actionable coverage/parse findings |

### `SymbolRecord`

Stable identity is `<path>::<qualified_name>`. Line numbers are provenance, not
identity. Initial symbol scope is module, classes, and public functions/methods.
Private symbols remain discoverable later but do not count toward public
docstring coverage in Slice 1.

### `InventoryReport`

Contains repository-relative records sorted by path, exact tracked count,
summary coverage counts, diagnostics, and schema version. The tracked path set
must equal `git ls-files`; omissions are a compiler defect.

## Summary Extraction

### Python

Parse with `ast.parse` only. Extract:

- module docstring;
- class docstrings;
- public function and method docstrings;
- signatures reconstructed from AST arguments/annotations; and
- source line provenance.

The artifact summary is the module docstring's first paragraph. Missing module
or public-symbol docstrings are diagnostics, not synthesized prose.

### Markdown

Extract the first H1 title, then the first non-empty content from the first
configured semantic heading present:

`Purpose`, `Decision`, `Status`, `Outcome`, `Goal`, `Gap`, `Summary`.

If none exists, use the first prose paragraph after the title and metadata.
This is a source-derived fallback and is labeled `markdown:first-paragraph`.

### Other artifacts

Classify them and report `summary-not-applicable` or `summary-missing`
according to configured policy. Slice 1 does not parse arbitrary formats.

## Determinism

- paths are byte-safe from NUL-delimited Git output and sorted lexically;
- JSON keys are sorted and non-ASCII/invalid path bytes are escaped safely;
- output contains no wall-clock timestamp or absolute repository path;
- line endings are normalized only in parsed text, never written back; and
- diagnostics have stable codes and ordering.

## Backward Verification

Given one output record:

1. `path` must appear in `git ls-files`;
2. each summary must identify a source construct;
3. each symbol must resolve in the AST at its recorded qualified name;
4. line provenance must point to the defining node; and
5. aggregate counts must recompute from records.

Failure at any step is explicit; no record is silently dropped.

## Slice Boundaries

Slice 1 emits inventory and summaries only. It does **not** yet:

- interpret relationship edges;
- inject context through hooks;
- create post-edit obligations;
- enforce plan freshness; or
- render HTML/MediaWiki.

Those depend on proving this source inventory is exhaustive and stable.

## Context Packet Extension (Slice 2)

`ContextPacket` joins inventory records to reviewed `relationships` edges and
the existing `couplings`, `governance`, `architecture`, and
`required_reading` sections. Explicit edges use:

```yaml
relationships:
  - source: src/service.py::authorize
    target: docs/requirements.md
    relation: implements
    reason: The symbol implements the governed-request requirement.
    maintenance: reconcile
```

`source`/`target` accept a selector or list of selectors. Selectors are
repository-relative globs with optional `::qualified.symbol` suffixes.
`relationships.yaml` may not contain summary prose; the packet resolves every
summary from the selected source artifact. Packets always include the target,
rank declared semantic neighbors before legacy edges, enforce configurable
item/character budgets, and report unresolved or omitted context.

## Impact Obligation Extension (Slice 3)

A changed source path matching an outgoing edge with maintenance
`reconcile`, `regenerate`, or `block` creates one deterministic
`ImpactObligation` per resolved target. `lineage_only` edges remain context but
create no obligation.

An obligation is satisfied when the linked target changed in the same Git
comparison or a reviewed disposition is valid:

- `verified_unchanged` requires a substantive reason and exact review
  fingerprint;
- `superseded` additionally requires a tracked successor authority; or
- `blocked` preserves explicit unresolved debt and keeps strict mode red.

The review fingerprint hashes `HEAD`, comparison base, staged/working-tree
mode, and the exact binary diff. It therefore changes when an uncommitted edit
changes even if `HEAD` does not. Timestamp-only, stale-revision, duplicate-id,
unknown-status, and untracked-successor dispositions fail loudly.
