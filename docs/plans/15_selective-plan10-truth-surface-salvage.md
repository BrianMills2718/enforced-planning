# Plan #15: Selective Plan-10 Truth-Surface Salvage

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** truthful salvage of still-useful `plan-10-framework-reconciliation` work

---

## Gap

**Current:** `plan-10-framework-reconciliation` is far behind current `main`
and cannot be merged directly. But it still contains two coherent, still-useful
truth-surface features that are not on current `main`:

1. lineage-aware consumed-reservation validation
2. optional semantic truth-surface review with structured advisory output

The branch also contains stale sprint pointers, deleted-current-state churn, and
historical numbered plan files that now conflict with current `main` numbering.

**Target:** Salvage only the still-valid truth-surface features into current
`main`, with fresh tests and current documentation, while explicitly skipping:

- stale sprint bookkeeping
- root `CLAUDE.md` sprint rewrites
- conflicting historical numbered plan docs from the old branch
- any broad branch-wide deletions or reversions

**Why:** The value in `plan-10` is real, but the branch itself is no longer a
safe merge unit. Selective salvage keeps the working features and discards the
stale branch history that would corrupt current governance surfaces.

---

## References Reviewed

- `README.md` - current truth-surface workflow docs
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md` - current deterministic vs semantic split
- `docs/plans/07_llm-semantic-truth-surface-review.md` - original semantic review target
- `scripts/check_truth_surface_drift.py` - current deterministic validator
- `scripts/render_truth_surface_status.py` - current renderer
- `tests/test_truth_surface_drift.py` - current deterministic validator tests
- `tests/test_render_truth_surface_status.py` - current renderer tests

---

## Research Basis For This Slice

- `~/projects/investigations/cross-project/2026-04-04-enforced-planning-research-methodology-review.md` - current methodology review that reinforced the need for durable evidence and advisory semantic review
- `plan-10-framework-reconciliation` branch commit `9f22345` - bounded lineage-aware truth-surface validation changes worth salvaging
- `plan-10-framework-reconciliation` branch commit `e6ecd7f` - bounded semantic truth-surface review bundle worth salvaging
- `docs/plans/07_llm-semantic-truth-surface-review.md` - canonical prior plan for the semantic review layer, confirming the feature belongs in the framework

---

## Files Affected

- `README.md` (modify)
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md` (modify)
- `templates/truth_surface_drift.yaml.example` (modify)
- `scripts/check_truth_surface_drift.py` (modify)
- `scripts/render_truth_surface_status.py` (modify)
- `scripts/review_truth_surface_semantic.py` (create)
- `scripts/truth_surface_semantic_models.py` (create)
- `prompts/truth_surface_semantic_review.yaml` (create)
- `tests/test_truth_surface_drift.py` (modify)
- `tests/test_render_truth_surface_status.py` (modify)
- `tests/test_semantic_truth_surface_review.py` (create)
- `docs/plans/15_selective-plan10-truth-surface-salvage.md` (modify)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

### Steps

1. Port the lineage-aware consumed-reservation logic into
   `check_truth_surface_drift.py` with current-style tests.
2. Update the truth-surface config template and static-truth docs so the new
   lineage behavior is visible and configurable.
3. Port the semantic review bundle as an optional advisory layer:
   prompt, models, review entrypoint, renderer support, and tests.
4. Update `README.md` minimally so the truth-surface workflow matches the
   implemented tools.
5. Verify the deterministic validator, semantic renderer, and semantic review
   helper tests.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_truth_surface_drift.py` | `test_historical_unlanded_consumed_reservation_warns_by_default` | Historical-unlanded reservations degrade to hygiene warnings rather than hard local failures |
| `tests/test_truth_surface_drift.py` | `test_relative_landed_plan_file_resolves_against_canonical_repo_root` | Relative landed plan files resolve from the canonical repo root instead of transient worktree paths |
| `tests/test_semantic_truth_surface_review.py` | `test_build_semantic_review_context_collects_bounded_surfaces` | Semantic review context is bounded and evidence-driven |
| `tests/test_render_truth_surface_status.py` | `test_render_with_semantic_findings_keeps_certainty_split` | Deterministic and semantic findings render together without collapsing certainty classes |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `pytest -q tests/test_truth_surface_drift.py tests/test_render_truth_surface_status.py tests/test_semantic_truth_surface_review.py` | Core salvage surface must work together |
| `python -m py_compile scripts/check_truth_surface_drift.py scripts/render_truth_surface_status.py scripts/review_truth_surface_semantic.py scripts/truth_surface_semantic_models.py` | CLI and import surfaces remain syntactically valid |

---

## Acceptance Criteria

- [x] `check_truth_surface_drift.py` distinguishes canonical landed lineage from `historical-unlanded` hygiene state
- [x] Relative consumed reservation plan paths resolve against canonical repo roots where possible
- [x] `templates/truth_surface_drift.yaml.example` documents the lineage-aware severity knob
- [x] `scripts/review_truth_surface_semantic.py` exists as an optional advisory entrypoint with structured output
- [x] `scripts/render_truth_surface_status.py` can merge semantic findings while preserving deterministic certainty levels
- [x] `README.md` and `STATIC_GRAPH_AND_RUNTIME_TRUTH.md` truthfully describe the hybrid deterministic + advisory model
- [x] No stale `plan-10` sprint pointers or conflicting branch-local plan numbering are replayed onto `main`
- [x] Declared tests pass

## Verification

- `pytest -q tests/test_truth_surface_drift.py tests/test_render_truth_surface_status.py tests/test_semantic_truth_surface_review.py`
- `python -m py_compile scripts/check_truth_surface_drift.py scripts/render_truth_surface_status.py scripts/review_truth_surface_semantic.py scripts/truth_surface_semantic_models.py`

---

## Notes

- Historical branch plan docs `11_semantic-truth-surface-review-execution-sprint.md`
  and `12_consumed-reservation-hygiene-and-plan-lineage.md` are evidence sources,
  not replay targets. Their plan numbers conflict with current canonical plan
  numbering on `main`.
- This slice is intentionally a salvage pass, not a historical reconstruction.
