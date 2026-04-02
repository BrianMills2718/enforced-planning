# Plan #7: LLM Semantic Truth-Surface Review Layer

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** 6
**Blocks:** semantic truth-surface review beyond deterministic rules

---

## Gap

**Current:** The framework now has a deterministic truth-surface validator and
renderer. That is enough for exact contradictions, but not for semantic drift
such as stale prose, misleading summaries, or cross-document disagreement that
does not reduce cleanly to one machine-readable field.

**Target:** Add an optional LLM/agent review layer that reads the same
truth-surface inputs, produces advisory semantic-drift findings, and records
which findings are stable enough to promote into deterministic checks later.

**Why:** Some of the most important coordination failures are not pure data
parity problems. Without a semantic review layer, the framework will still miss
high-impact drift that humans notice quickly but exact rules cannot express
cheaply or robustly.

---

## References Reviewed

- `PLANNING_OPERATING_MODEL.md`
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md`
- `README.md`
- `docs/plans/04_truth-surface-drift-validation-and-enforcement.md`
- `docs/plans/05_truth-surface-validator-completion-sprint.md`
- `docs/plans/06_governed-repo-truth-surface-adoption-pilot.md`
- `scripts/check_truth_surface_drift.py`
- `scripts/render_truth_surface_status.py`

---

## Files Affected

- `scripts/` LLM semantic review entrypoint(s)
- `templates/` semantic-review config scaffold if needed
- `docs/` workflow guidance and policy docs
- optional governed-repo pilot surfaces if adoption evidence is needed

---

## Plan

### Steps

1. Use Plan #6 pilot evidence to enumerate semantic drift cases that the
   deterministic validator cannot capture well.
2. Define the contract for an optional LLM review layer:
   inputs, outputs, severity model, and evidence requirements.
3. Decide which findings remain advisory and which repeated high-precision
   classes can later be promoted into deterministic rules.
4. Implement one bounded review entrypoint that summarizes truth surfaces for an
   LLM/agent and returns structured findings.
5. Add a renderer or integration point so semantic findings can appear beside
   deterministic findings without pretending they have the same certainty.
6. Document default workflow guidance for when to run semantic review and when
   to rely on deterministic checks only.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/...` | semantic review contract test | Structured review output is parsed and classified consistently |
| `tests/...` | deterministic + semantic merge test | Mixed findings render without collapsing certainty levels |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | Framework file/template integrity remains intact |
| `python -m pytest tests/ -q` | Existing validator behavior stays green |

---

## Acceptance Criteria

- [x] The framework documents a clear hybrid model: deterministic first, optional
      LLM review second.
- [x] One bounded semantic review entrypoint exists with structured output and
      explicit advisory semantics.
- [x] The implementation records which semantic findings are candidates for later
      deterministic promotion.
- [x] Docs explain when semantic review is worth the cost and when exact checks
      are sufficient.

---

## Measured Findings

- The first semantic-review slice now exists in `scripts/review_truth_surface_semantic.py` and uses shared `llm_client` structured output with explicit `task=`, `trace_id=`, and `max_budget=` metadata.
- Semantic findings remain advisory-only and render in a separate section beside deterministic findings through `scripts/render_truth_surface_status.py --semantic-json ...`.
- The prompt contract now prefers deterministic rendered status plus a bounded evidence bundle over full raw truth-surface files.
- A live smoke review succeeded from the repo root with `gemini/gemini-2.5-flash`, returned an empty advisory findings set on a clean sample config, and produced a merged rendered status.
- One environment nuance remains important: running bare `python -c "from llm_client import ..."` from `/home/brian/projects` can still resolve the source repo as a namespace package. Repo-local execution from the governed repo root works correctly after installing shared `llm_client`.

## Open Questions

- [x] Should semantic review run only on demand, or as an opt-in closeout step
      for coordination-heavy repos?
      - Resolved in the first slice: on demand / opt-in only. It is not automatic closeout behavior.
- [x] Which model/provider should be the default reviewer, and how should cost
      ceilings be enforced?
      - Resolved in the first slice: default to configurable `gemini/gemini-2.5-flash` with an explicit `--max-budget` ceiling passed through `llm_client`.
- [x] How should the review prompt consume truth surfaces: raw files, rendered
      summaries, or both?
      - Resolved in the first slice: deterministic rendered status first, plus a bounded evidence bundle of selected surface excerpts.
- [x] Which finding classes should remain permanently advisory because they are
      too interpretive for hard enforcement?
      - Resolved in the first slice: stale prose, missing updates, and broader compendiousness concerns remain advisory until repeated evidence justifies deterministic promotion.
