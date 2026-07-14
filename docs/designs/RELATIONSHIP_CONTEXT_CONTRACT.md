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
identity. Symbol scope is the module, classes, and direct module/class
functions or methods, including private callables. Their real docstrings appear
in generated navigation. Undocumented private helpers do not count toward
public-docstring coverage; representation and mandatory coverage are separate.

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

## Plan Lifecycle Extension (Slice 4)

For `planned_by` edges, the compiler reads the target plan's declared
`Status` field. Active/planned plans changed in the same comparison satisfy
normally. Completed, superseded, and archived plans are historical: changing
their file does not automatically satisfy a new implementation obligation.
They require an exact-review disposition or a tracked documentation successor
such as a new plan or current-state authority. A plan with no recognized status
also cannot auto-satisfy. This keeps living plans current without rewriting
completed execution history into present truth.

## Generated Docstring Wiki (Slice 5)

The Markdown wiki lists every tracked artifact under its governance
classification, then includes source-derived artifact summaries, documented
Python symbols, signatures, lines, and coverage finding codes. The renderer
supports write and byte-for-byte check modes. Generated output remains under
the repository's configured generated-artifact policy; in this source repo
`generated/` is ignored, so the compiler/check are committed while the 272 KB
projection is regenerated locally rather than forced into documentation
history.

## Hook And Consumer Rollout (Slices 6-7)

The governed-repo installer copies the compiler modules and CLIs into the
consumer and exposes inventory, packet, impact, and wiki Make targets. The
`PreToolUse` edit hook composes required-reading output with a bounded context
packet. It uses the repository virtualenv when present and reports packet
failures in context without blocking edits during visibility-first rollout.
Before writing hook support, the installer probes the exact interpreter the
hook will select (`.venv/bin/python`, otherwise `python3`) for the declared
PyYAML runtime dependency. Framework-host packages cannot satisfy that check
on behalf of the consumer.

New-file `Write` requests are represented by a path-derived target with an
explicit `target-untracked-new-file` diagnostic. This mode can match file-level
selectors but cannot claim a Python symbol before parseable source exists.

The first `onto-canon6` pilot proved plan-level context and deterministic wiki
generation, while also proving that strict maintenance enforcement would be
premature: the consumer declares no code couplings and has substantial
unclassified docstring debt. The static contracts are complete; consumer hard
gates remain a separate evidence-gated rollout decision.

The shell hook adapter is currently Claude Code-specific. The CLI/JSON
contract is client-neutral and agent-drivable, but Codex automatic pre-edit
injection remains a separate adapter rather than an implied capability.
