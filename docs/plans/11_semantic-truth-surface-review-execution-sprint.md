# Plan #11: Semantic Truth-Surface Review Execution Sprint

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** 7, 10
**Blocks:** first implementation slice of optional semantic truth-surface review

---

## Gap

**Current:** Plan #7 defines the semantic truth-surface review layer at a conceptual level, but the execution contract is still too loose for autonomous implementation. The main remaining ambiguity is operational: invocation mode, default reviewer backend, input surfaces, and how advisory semantic findings should coexist with deterministic findings.

**Target:** Define one bounded execution sprint for the first semantic-review slice so implementation can proceed without reopening the same architecture questions mid-flight.

**Why:** Plan #7 should not stay as a good idea with unresolved operational defaults. The next slice needs explicit decisions before code starts.

---

## References Reviewed

- `docs/plans/07_llm-semantic-truth-surface-review.md`
- `docs/plans/10_framework-truth-surface-and-onboarding-reconciliation.md`
- `PLANNING_OPERATING_MODEL.md`
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md`
- `scripts/check_truth_surface_drift.py`
- `scripts/render_truth_surface_status.py`

---

## Files Affected

- `docs/plans/07_llm-semantic-truth-surface-review.md`
- `docs/plans/11_semantic-truth-surface-review-execution-sprint.md`
- future implementation files under `scripts/`, `templates/`, `tests/`, and docs

---

## Plan

### Phase A — Semantic Review Contract Freeze

Success criteria:
- invocation mode is explicit
- input/output contract is explicit
- certainty semantics are explicit

Pre-made decisions:
- semantic review is opt-in, not automatic closeout behavior
- implementation will use shared `llm_client`, not a bespoke LLM caller
- output must be structured and advisory-only for the first slice

### Phase B — Input Surface Design

Success criteria:
- the review prompt consumes deterministic rendered status plus selected raw evidence paths
- the first slice does not require loading every raw truth surface in full
- the contract distinguishes summary context from evidence references

Pre-made decisions:
- primary input is rendered deterministic status
- supporting input is a bounded list of evidence snippets or file paths from validator findings
- raw whole-file review is deferred unless the pilot proves it is necessary

### Phase C — Runtime and Cost Policy

Success criteria:
- default model/config path is explicit
- cost ceiling behavior is explicit
- failure semantics are explicit

Pre-made decisions:
- model selection is configurable
- first default reviewer should be `gemini/gemini-2.5-flash`
- semantic review must require `task=`, `trace_id=`, and `max_budget=` through `llm_client`
- model/provider failure should fail loud, not silently skip review

### Phase D — Rendering and Promotion Policy

Success criteria:
- semantic findings render beside deterministic findings without collapsing certainty levels
- the framework records which semantic findings are candidates for deterministic promotion
- the handoff back into Plan #7 is explicit

Pre-made decisions:
- semantic findings keep a separate advisory section in rendered status
- repeated high-precision semantic classes are recorded for later deterministic promotion, not promoted automatically

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/...` | semantic review contract parse test | advisory findings can be parsed deterministically from structured output |
| `tests/...` | merged rendering test | deterministic and semantic findings render as separate certainty classes |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | framework integrity must stay green |
| `python -m pytest tests/ -q` | existing deterministic validator behavior cannot regress |

---

## Acceptance Criteria

- [x] Invocation mode, llm_client dependency, input shape, and default cost/model policy are explicit.
- [x] The first semantic-review slice is clearly advisory-only.
- [x] The rendering contract distinguishes deterministic findings from semantic findings.
- [x] Plan #7 can proceed without reopening these same operational questions.

---

## Measured Findings

- `scripts/review_truth_surface_semantic.py` now provides the first bounded semantic-review entrypoint.
- `scripts/truth_surface_semantic_models.py` holds the shared advisory output contract so renderer and reviewer can evolve without import cycles.
- `scripts/render_truth_surface_status.py` now accepts `--semantic-json` and keeps semantic findings in a separate advisory section.
- The installer now copies the semantic-review script, its shared model contract, and `prompts/truth_surface_semantic_review.yaml` into governed repos.
- Live smoke evidence from a temporary clean config produced an empty semantic review report and a merged rendered status with `Semantic Review: clean`.
