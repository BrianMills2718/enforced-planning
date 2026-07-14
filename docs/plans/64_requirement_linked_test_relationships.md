# Plan #64: Requirement-Linked Test Relationships

**Status:** In Progress
**Type:** implementation + report-only consumer pilot
**Priority:** High
**phase_ref:** "portable documentation governance"
**goal_ref:** "ecosystem-context-integrity"
**Blocked By:** None
**Blocks:** evidence-based test-suite consolidation and calibrated new-test linkage gates

`trace_evaluable: false # deterministic governance tooling`

## Goal

Extend the portable relationship graph so test quality is evaluated through
behavioral authority, risk, test level, polarity, and execution realism rather
than aggregate test count. Produce a deterministic report-only audit and pilot
it on selected high-risk `onto-canon6` boundaries without deleting tests or
enabling hard enforcement.

## Requirements

1. Existing file-level `tests` edges remain valid and become findings when
   semantic fields are absent; rollout cannot break current consumers.
2. Reviewed test edges may bind a whole cohesive test file or one test symbol.
3. Test semantics include requirement references, implementation boundary,
   level, polarity, realism, failure modes, and risk level.
4. Optional declared requirements make unproved requirements reportable.
5. Reports identify unlinked tests, incomplete edges, mock-only authority,
   high-risk boundaries without negative controls, unit-only authority, and
   likely duplicate semantic edge clusters.
6. Output is deterministic JSON and human-readable Markdown with no timestamps
   or absolute workspace paths.
7. The initial `onto-canon6` pilot is report-only and covers selected high-risk
   pipeline, governance, export, and semantic-authoring boundaries.

## Non-Goals

- Deleting or consolidating tests.
- Requiring one YAML entry per test function.
- Inferring that an ADR is a behavioral requirement.
- Treating mocked or fixture tests as useless; they are classified, not banned.
- Enabling a repository-wide hard gate.

## Risk-Ordered Slices

| Slice | Outcome | Status |
|---|---|---|
| 0 | Policy and compatibility contract reflected in this plan | Complete |
| 1 | Typed parser, inventory, deterministic audit, and both-sign tests | Complete |
| 2 | Template/schema example and portable CLI/Make surface | Complete |
| 3 | Report-only `onto-canon6` high-risk pilot | In Progress |
| 4 | Audit findings, consolidation candidates, and enforcement disposition documented | Planned |

## Acceptance Criteria

| Criterion | Evidence | Pass condition |
|---|---|---|
| AC-1 compatibility | test | legacy `tests` edge parses and reports missing semantics without failing |
| AC-2 exact inventory | test | every authored Python test function/method is represented once |
| AC-3 semantic validation | positive + negative tests | enums and refs normalize; malformed values fail loud |
| AC-4 authority coverage | test | declared unproved requirement and unlinked test are reported |
| AC-5 risk coverage | test | mock-only, unit-only, and high-risk-without-negative conditions are reported |
| AC-6 duplicate signal | test | repeated equivalent semantic edges produce a bounded candidate finding, not automatic deletion |
| AC-7 determinism | test | repeated JSON/Markdown outputs are byte-identical and workspace-neutral |
| AC-8 consumer evidence | observed report | selected `onto-canon6` boundaries produce a committed report with limitations |

## Stop Conditions

1. Do not delete a test based on this audit.
2. Do not hard-fail legacy missing metadata.
3. Do not require symbol-level declarations when one cohesive file-level edge
   truthfully describes the suite.
4. Stop and revise the schema if the pilot cannot distinguish behavioral
   authority from ADR decision lineage.

## Slice 1-2 Evidence

- `tests/test_test_relationships.py`: 14/14 pass, covering legacy incomplete
  edges, exact file/symbol selection, reversed legacy direction, enum failures,
  test-to-test rejection, source-local requirement authority, unproved/mock-only/
  unit-only/missing-negative findings, mixed-proof closure, duplicate candidates,
  report-only scope, and deterministic workspace-neutral output.
- Combined auditor and narrow-installer tests: 33/33 pass.
- Focused Ruff and strict mypy pass; `scripts/self_test.py` passes.
- Full repository run: 610 passed, 1 skipped, 12 failed. The 12 failures are
  the pre-existing Plan 63 worktree/root-resolution baseline; none exercise or
  import the new auditor. This plan does not relabel that red baseline green.
- Initial unmodified `onto-canon6` high-risk sample: 93 authored tests, 37
  linked by three legacy file edges, and 59 findings. This is baseline
  visibility only; reviewed semantic edges and the final pilot report remain
  Slice 3 work.

## Concerns

- Static heuristics cannot prove tests are duplicates; duplicate findings are
  review candidates only.
- Test names and paths do not reliably reveal unit/integration level or runtime
  realism; reviewed declarations remain authoritative.
- Repositories without declared requirement IDs can measure test linkage but
  cannot claim requirement coverage completeness.
