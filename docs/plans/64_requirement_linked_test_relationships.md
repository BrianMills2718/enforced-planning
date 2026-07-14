# Plan #64: Requirement-Linked Test Relationships

**Status:** Complete (report-only; enforcement deferred)
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
4. Optional declared requirements make requirements without reviewed test
   evidence reportable.
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
| 3 | Report-only `onto-canon6` high-risk pilot | Complete |
| 4 | Audit findings and enforcement disposition documented | Complete: remain report-only |

## Acceptance Criteria

| Criterion | Evidence | Pass condition |
|---|---|---|
| AC-1 compatibility | test | legacy `tests` edge parses and reports missing semantics without failing |
| AC-2 exact inventory | test | every authored Python test function/method is represented once |
| AC-3 semantic validation | positive + negative tests | enums and refs normalize; malformed values fail loud |
| AC-4 authority coverage | test | a declared requirement without reviewed test evidence and an unlinked test are reported |
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
  test-to-test rejection, source-local requirement authority, missing-evidence/mock-only/
  unit-only/missing-negative findings, mixed-proof closure, duplicate candidates,
  report-only scope, and deterministic workspace-neutral output.
- Combined auditor and narrow-installer tests: 34/34 pass.
- Focused Ruff and strict mypy pass; `scripts/self_test.py` passes.
- Full repository run: 610 passed, 1 skipped, 12 failed. The 12 failures are
  the pre-existing Plan 63 worktree/root-resolution baseline; none exercise or
  import the new auditor. This plan does not relabel that red baseline green.
- An early `onto-canon6` sample found 93 authored tests, 37 linked by three
  broad legacy edges, and 59 findings. The canonical Plan 63 base subsequently
  linked all 93 through broad suite edges, but still had 0 semantically complete
  edges. Both readouts are baseline visibility, not evidence of quality.

## Consumer Pilot Evidence

- `onto-canon6` commits `4797542` and `657b70c` install the portable auditor,
  preserve the broad legacy context edges, and add eight exact reviewed test
  edges for six Plan 0141 acceptance criteria.
- The committed JSON and Markdown reports record 93 authored tests in scope,
  93 linked by broad reviewed edges, eight linked by semantically complete
  edges, six requirements with reviewed test evidence, and 13 findings.
- The findings are intentionally unresolved visibility: all six requirement
  authorities are fixture-only; AC-6 and AC-9 lack a linked negative control;
  five broad legacy test edges lack evidence semantics.
- The selected semantic-authoring suites pass 57/57. The consumer documentation
  protocol and its compatibility repair pass 33/33; combined focused replay is
  90/90. Ruff and Markdown link checks pass.
- No tests were deleted, no consolidation was inferred from names, and no hard
  gate was enabled. A future enforcement decision requires reviewed expansion
  beyond this pilot plus a coverage report and negative controls.

## Concerns

- Static heuristics cannot prove tests are duplicates; duplicate findings are
  review candidates only.
- Test names and paths do not reliably reveal unit/integration level or runtime
  realism; reviewed declarations remain authoritative.
- Repositories without declared requirement IDs can measure test linkage but
  cannot claim requirement coverage completeness.
- “Linked” and “semantically linked” are intentionally separate metrics: a
  broad legacy suite edge is useful context, but cannot count as behavioral
  evidence until its authority and test semantics are reviewed.
- Post-merge audit found and repaired one false-evidence path: incomplete,
  unmatched, source-dangling, or undeclared-requirement edges could previously
  inflate the requirement-evidence count. Evidence eligibility now requires a
  complete edge, at least one authored-test match, declared requirement refs,
  and resolvable local requirement source files.
