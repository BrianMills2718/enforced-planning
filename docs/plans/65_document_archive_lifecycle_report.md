# Plan #65: Report-Only Document Archive Lifecycle

**Status:** Complete (report-only; semantic eligibility and enforcement deferred)
**Type:** implementation
**Priority:** High
**phase_ref:** "Document lifecycle P2"
**goal_ref:** "relationship-lifecycle-visibility"
**adrs_referenced:** ["ADR-2026-07-14-document-lifecycle-and-archive-disposition"]
**Blocked By:** None
**Blocks:** Greer lifecycle calibration and archive integration

## Gap

**Current:** Relationship declarations explain edit coupling, but do not expose
whether an edge blocks, redirects, or merely records lineage during archival.

**Target:** A deterministic report enumerates documentation coverage and the
mechanical blockers that must be cleared before semantic archive review. It
must never declare a document archive-eligible.

**Why:** Reference presence currently risks becoming permanent active
retention, while simplistic cleanup risks stranding current authority or work.

## Research

- `project-meta/docs/ops/ADR-2026-07-14-document-lifecycle-and-archive-disposition.md`
  at merged revision `4985ba6` — accepted policy, domain model, and P2 boundary.
- `docs/designs/RELATIONSHIP_CONTEXT_CONTRACT.md` — existing relationship,
  context, obligation, and plan-lifecycle contracts.
- `enforced_planning/context_packet.py` — normalized explicit and legacy edge
  model to extend without conflating edit maintenance and archive effects.
- `enforced_planning/relationship_context.py` — exhaustive Git-backed artifact
  inventory and documentation classification.
- `enforced_planning/impact_obligations.py` — existing source-local plan status
  parser used rather than copying lifecycle status into the graph.
- `tests/test_context_packet.py`, `tests/test_relationship_context.py`, and
  `tests/test_impact_obligations.py` — current both-sign relationship controls.

**Modality:** Deductive. Allowed declarations, unsafe defaults, and report
states are predictable. The semantic conclusion that a document's meaning has
been promoted remains outside this deterministic compiler.

## Files Affected

- `docs/plans/65_document_archive_lifecycle_report.md` (create)
- `docs/designs/RELATIONSHIP_CONTEXT_CONTRACT.md` (modify)
- `enforced_planning/context_packet.py` (modify)
- `enforced_planning/archive_lifecycle.py` (create)
- `scripts/archive_lifecycle.py` (create)
- `tests/test_context_packet.py` (modify)
- `tests/test_archive_lifecycle.py` (create)

## Plan

| Step | What | Status |
|---|---|---|
| 1 | Record the report-only contract and negative controls | Complete |
| 2 | Expose explicit archive effects on normalized relationship edges | Complete |
| 3 | Compile exhaustive documentation coverage and candidate blockers | Complete |
| 4 | Verify focused and full suites, then adversarially audit the slice | Complete |
| 5 | Commit and publish the isolated branch | Complete — PR #6 |

## Acceptance Criteria

| Criterion | Pass condition | Evidence target | Current grade |
|---|---|---|---|
| AC-1 | `lineage_only` is visible but creates no mechanical blocker | schema-validated fixture plus test | A |
| AC-2 | `blocks_archive` produces a named blocker | negative-control test | A |
| AC-3 | `redirect_before_archive` produces a required redirect, not indefinite retention | both-sign test | A |
| AC-4 | missing semantic claim-promotion review stops at `semantic_review_required` | negative-control test | A |
| AC-5 | revision/hash authorization is not accepted or fabricated by this P2 report | output-schema test | A |
| AC-6 | missing or legacy archive effects normalize to `review_required`, never eligible | negative-control test | A |
| AC-7 | every Git-tracked narrative Markdown document is represented as declared or undeclared | exact-inventory test | A |
| AC-8 | repeated output is byte-deterministic and contains no absolute path or timestamp | deterministic-output test | A |

Verification commands:

```bash
pytest tests/test_context_packet.py tests/test_archive_lifecycle.py -q
pytest -q
ruff check enforced_planning/context_packet.py enforced_planning/archive_lifecycle.py scripts/archive_lifecycle.py tests/test_context_packet.py tests/test_archive_lifecycle.py
mypy enforced_planning/context_packet.py enforced_planning/archive_lifecycle.py
```

## Failure Modes

| Failure | Detection | Required response |
|---|---|---|
| Compiler infers semantic eligibility | report exposes `eligible`/approval field | remove it; end at semantic review |
| Legacy edge silently becomes safe | absent effect does not emit `review_required` | restore fail-safe default and test |
| Historical lineage blocks forever | lineage-only edge appears in blockers | separate lineage observations from blockers |
| Active dependency is hidden | blocking/redirect edge absent from candidate result | fix edge expansion and exact-path coverage |
| Registry copies source-local lifecycle | declaration embeds authoritative status | parse source status; keep unknown explicit |

`trace_evaluable: false # trivial-deterministic`

## Premade Decisions and Explicit Uncertainties

- P2 is visibility-only. Its most permissive state is
  `semantic_review_required`, never `eligible`.
- Exact repository-relative paths identify documents in P2. Stable identity
  across rename/archive remains deferred to archive integration.
- Every explicit edge may state `archive_effect`; absent and legacy effects
  normalize to `review_required`.
- Document declarations carry a role and purpose-bearing justification, while
  lifecycle is read from source-local document status when recognizable.
- Generated, vendored, fixture, and family-level declaration semantics remain
  deferred; P2 measures narrative Markdown coverage without hard enforcement.
- Plan-index reconciliation is intentionally deferred until the concurrent
  Plan 64 owner releases its plan-governance surface.

## Verification Notes

- Focused lifecycle, relationship, inventory, and obligation suite: 48 passed.
- Ruff: passed for all affected Python files.
- Mypy: passed for both affected compiler modules.
- Pre-landing review: passed after exposing valid declarations in the report,
  correcting broad-selector edge direction, rejecting circular justification
  anchors, naming the status scan limit, adding a CLI test, and advancing the
  additive context-packet contract to schema version 2.
- Real repository probe: 183 tracked narrative documents and zero declarations;
  completed Plan 63 correctly reports `blocked` because ownership is undeclared
  and its one legacy edge remains `review_required`.
- Full branch suite with the checkout on `PYTHONPATH`: 609 passed, 1 skipped,
  and 8 failures reproduced unchanged at base revision `ee92c37`. The baseline
  failures are confined to governed-repo audit fixtures and a retired
  sibling-worktree link convention; none of their source or tests is modified
  by this plan.
- Excluding those two baseline-failing test modules, the current branch passes
  595 tests with 1 skipped.
- The repository push-safety Make target could not resolve the project from the
  policy-compliant nested worktree, then failed parsing non-empty pretty JSON
  from `agent-memory`. The healthy exact-path Plan 65 claim and non-overlap with
  Plan 64 were verified directly before the normal push. The defect is recorded
  in `~/.claude/workflow_observations.md`; the canonical policy-friction log was
  not edited because another live claim owns it.

## Ongoing Maintenance Rule

Update this plan before continuing if implementation changes the report-only
boundary, files affected, acceptance criteria, or explicit uncertainties.
