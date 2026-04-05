# Plan #18: Truth-Surface Semantic Review Convergence

**Status:** Complete
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** #16

---

## Gap

**Current:** The framework now has two semantic-review implementations:

- `scripts/review_truth_surfaces.py`
- `scripts/review_truth_surface_semantic.py`

They differ in scope, inputs, output models, default models, docs, tests, and
Makefile wiring. The roadmap and docs do not define which one is canonical.

**Target:** The framework has one canonical semantic-review entrypoint, one
structured output contract, one Makefile path, and one relationship to
deterministic truth-surface validation and promotion-to-deterministic tooling.

**Why:** A duplicated semantic-review layer makes the framework harder to adopt,
harder to document, and harder to reason about when promoting advisory findings
into deterministic checks.

---

## References Reviewed

- `scripts/review_truth_surfaces.py` - legacy repo-wide semantic review path
- `scripts/review_truth_surface_semantic.py` - newer config-driven semantic review path
- `scripts/truth_surface_semantic_models.py` - new advisory schema contract
- `scripts/render_truth_surface_status.py` - current renderer integration
- `scripts/promote_to_deterministic.py` - legacy promotion flow
- `prompts/review_truth_surfaces.yaml` - legacy prompt
- `prompts/truth_surface_semantic_review.yaml` - new prompt
- `tests/test_review_truth_surfaces.py` - legacy coverage
- `tests/test_semantic_truth_surface_review.py` - new coverage
- `ROADMAP.md` - current roadmap/status claims about semantic review
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md` - current deterministic-vs-semantic doctrine

---

## Research Basis For This Slice

- `docs/designs/DOCUMENTATION_SURFACE_ARCHITECTURE.md` - establishes the need for one canonical semantic-review path in the product surface
- No additional research beyond References Reviewed.

---

## Files Affected

- scripts/review_truth_surfaces.py (modify or deprecate)
- scripts/review_truth_surface_semantic.py (modify)
- scripts/truth_surface_semantic_models.py (modify if needed)
- scripts/render_truth_surface_status.py (modify)
- scripts/promote_to_deterministic.py (modify if needed)
- prompts/review_truth_surfaces.yaml (remove)
- prompts/truth_surface_semantic_review.yaml (modify)
- Makefile (modify)
- tests/test_review_truth_surfaces.py (modify or remove)
- tests/test_semantic_truth_surface_review.py (modify)
- tests/test_promote_to_deterministic.py (modify)
- ROADMAP.md (modify)
- README.md (modify)
- STATIC_GRAPH_AND_RUNTIME_TRUTH.md (modify)
- ISSUES.md (modify)
- docs/plans/18_truth-surface-semantic-review-convergence.md (modify)
- docs/plans/CLAUDE.md (modify)

---

## Plan

### Steps

1. Compare the legacy repo-wide review path and the newer config-driven path by contract:
   inputs, outputs, renderer integration, promotion flow, and consumer installability.
2. Choose one canonical entrypoint and one output schema.
3. Define how the promotion-to-deterministic workflow consumes canonical findings.
4. Remove or explicitly deprecate the non-canonical path.
5. Update Makefile targets, roadmap/status docs, and tests to the canonical path.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_render_truth_surface_status.py` | canonical semantic payload merge tests | Rendered status consumes the canonical semantic-review output model only |
| `tests/test_semantic_truth_surface_review.py` or successor | canonical review contract tests | The surviving semantic-review entrypoint builds bounded context and parses structured output |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/18_truth-surface-semantic-review-convergence.md --warn-only` | Plan remains valid |
| `pytest -q tests/test_render_truth_surface_status.py tests/test_semantic_truth_surface_review.py tests/test_review_truth_surfaces.py tests/test_promote_to_deterministic.py` | Canonical semantic-review path, compatibility wrapper, renderer, and promotion flow remain aligned |
| `python -m py_compile scripts/review_truth_surfaces.py scripts/review_truth_surface_semantic.py scripts/truth_surface_semantic_models.py scripts/render_truth_surface_status.py scripts/promote_to_deterministic.py` | Semantic-review surface remains syntactically valid during convergence |

---

## Acceptance Criteria

- [x] One semantic-review entrypoint is canonical
- [x] One structured semantic-review output schema is canonical
- [x] Makefile and docs point to the same semantic-review path
- [x] The relationship between semantic review and promotion-to-deterministic is explicit
- [x] The deprecated or replaced path is removed or clearly scoped as legacy
- [x] Declared checks pass

---

## Decision

The config-driven path is canonical:

- `scripts/review_truth_surface_semantic.py --config ...`
- latest payload written to `semantic_truth_surface_review.json`
- append-only review history written to `semantic_truth_surface_review_history.json`
- `promote_to_deterministic.py` reads the canonical history format

`scripts/review_truth_surfaces.py` now remains only as a deprecated
compatibility wrapper for callers still passing `--repo`.
