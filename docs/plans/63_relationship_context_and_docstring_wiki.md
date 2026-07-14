# Plan #63: Relationship Context and Docstring Wiki

**Status:** In Progress
**Type:** design + implementation
**Priority:** Critical
**phase_ref:** "portable documentation governance"
**goal_ref:** "ecosystem-context-integrity"
**Blocked By:** None
**Blocks:** governed-repo plan freshness and exhaustive relationship enforcement

`trace_evaluable: false # infrastructure-only`

## Goal

Implement the reusable compiler and enforcement surfaces for the accepted
context-docstring policy: exhaustive tracked-file representation, actual
docstring summaries, bounded relationship context, post-edit reconciliation,
plan lifecycle freshness, and a generated docstring wiki.

## Research Reviewed

- `docs/designs/RELATIONSHIPS_V2_DESIGN.md` — inference plus reviewed declarations.
- `enforced_planning/file_context.py` — current file-level relationship resolver.
- `patterns/09_documentation-graph.md` — static versus runtime truth boundary.
- `patterns/10_doc-code-coupling.md` — current file-level limitations.
- `project-meta/docs/ops/ADR-2026-07-14-context-docstrings-and-exhaustive-relationships.md` — ownership and lifecycle decision.

## Requirements

1. Every Git-tracked file appears in the inventory exactly once.
2. Python meaning comes from actual docstrings and signatures, extracted
   statically without importing target code.
3. Markdown meaning comes from actual title/semantic sections, not copied YAML.
4. Missing context is explicit and measurable.
5. Later relationship context is bounded, deterministic, and provenance-bearing.
6. Changed edges create typed reconciliation obligations.
7. Active plans remain living; completed plans remain historical.
8. Generated wiki output is derivative and sync-checkable.

## Boundary And Data Flow

```text
git ls-files + source files + relationships.yaml
                  |
                  v
       static inventory/compiler
        |         |          |
        v         v          v
 coverage     context     impact obligations
 report       packet      + dispositions
        \         |          /
         \        v         /
          generated docstring wiki
```

Runtime claims and sessions are intentionally outside this graph.

## Contracts

`ArtifactRecord`, `SymbolRecord`, and `InventoryReport` are defined in
`docs/designs/RELATIONSHIP_CONTEXT_CONTRACT.md`. Later slices add
`RelationshipEdge`, `ContextPacket`, `ImpactObligation`, and
`ReconciliationDisposition` without weakening the inventory contract.

## Capability Dependency Graph

```text
C1 tracked inventory
 + C2 source summary extraction
          |
          v
C3 relationship resolution --> C4 bounded context packet
          |
          v
C5 changed-node impact --> C6 reconciliation dispositions
          |
          v
C7 plan lifecycle freshness
          |
          v
C8 generated wiki + consumer rollout
```

## Risk-Ordered Slices

| Slice | Outcome | Status |
|---|---|---|
| 0 | Contract and policy ownership fixed | Complete |
| 1 | Read-only exact tracked-file inventory and actual-summary extraction | Complete |
| 2 | Relationship schema extension and bounded `ContextPacket` | Not started |
| 3 | Changed-node impact obligations and audited dispositions | Not started |
| 4 | Active/completed plan lifecycle freshness with negative controls | Not started |
| 5 | Deterministic CLI/JSON docstring wiki and sync check | Not started |
| 6 | Installer/hook adapters and report-only `onto-canon6` pilot | Not started |
| 7 | Evidence review and calibrated new-debt enforcement | Not started |

## Slice 1 Acceptance Criteria

| Criterion | Evidence class | Pass condition |
|---|---|---|
| AC-1 exact tracked coverage | source + test | output path set equals `git ls-files` fixture path set |
| AC-2 real Python docstrings | source + test | module/class/public function summaries and qualified names match fixture source |
| AC-3 no code execution | negative-control test | inventory succeeds when target module raises at import time |
| AC-4 explicit missing coverage | test | missing module/public symbol docstrings emit stable diagnostics |
| AC-5 Markdown summaries | test | semantic heading wins; first-paragraph fallback is labeled |
| AC-6 deterministic output | test | repeated JSON output is byte-identical and contains no absolute root/time |
| AC-7 fail loud | negative-control test | non-Git root and invalid Python produce explicit typed diagnostics/errors |

**Slice 1 evidence (2026-07-14):** `python -m pytest
tests/test_relationship_context.py -q` passes 6/6; focused Ruff and strict mypy
pass. A live self-inventory exactly matched all 418 `git ls-files` paths,
extracted 342 artifact summaries, and reported 287 missing Python docstrings
without enforcing them. Repository-wide gates remain independently red on the
documented MP-015 (12 pre-existing pytest failures) and MP-017 (123 pre-existing
Ruff findings) baselines; this slice adds zero Ruff findings and five passing
tests.

## Later Acceptance Criteria

- Context packet budgets and provenance pass deterministic tests.
- Changing linked code produces an unresolved obligation negative control.
- `verified_unchanged` requires a non-empty reason and source revision.
- Active plan drift fails; completed plan history is not forced to mutate.
- Generated wiki hand edits and stale output fail sync checks.
- Consumer rollout remains report-only until coverage and false-positive
  evidence is reviewed.

## Failure Modes

| Failure | Detection | Recovery |
|---|---|---|
| importer side effects | test module raises if imported | retain AST-only extraction |
| binary/odd filename omitted | exact Git path-set test fails | fix NUL-safe inventory; never skip silently |
| copied summary becomes authority | schema contains free-form summary field | reject declaration; extract from source |
| context exceeds budget | packet metrics fail | rank and truncate with explicit omitted count |
| irrelevant obligations dominate | repeated dispositions show false edges | correct selectors/inference before enforcement |
| completed plans rewritten | lifecycle negative control | require successor/current-state disposition |

## Concerns

- Python annotations can be syntactically complex; signature rendering is
  descriptive context, not executable source regeneration.
- Markdown has heterogeneous headings; missing summaries must remain visible.
- Exhaustive inventory includes files that should not require prose. Artifact
  classification and exclusions must be explicit before coverage is graded.
- Hooks differ by client; the CLI/JSON contract is the portable authority.

## Stop Conditions

1. Do not enable hard enforcement before a report-only consumer pilot.
2. Do not execute target code to obtain summaries.
3. Do not store runtime coordination state in `relationships.yaml`.
4. Do not duplicate source summaries in generated or declared authority.
