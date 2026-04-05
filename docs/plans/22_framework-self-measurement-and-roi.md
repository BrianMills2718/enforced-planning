# Plan #22: Framework Self-Measurement and ROI

**Status:** Complete
**Type:** design
**Priority:** Medium
**Blocked By:** #21
**Blocks:** [future] evidence-backed framework adoption claims

---

## Gap

**Current:** The framework talks about adoption, drift catch rate, and
ecosystem value, but it does not yet define one canonical metric set or how
those metrics will be gathered.

**Target:** The framework defines one bounded self-measurement model covering:

- adoption metrics
- drift-catch / prevention metrics
- semantic-review usefulness metrics
- upgrade / sync metrics
- evidence boundaries for ROI claims

**Why:** Without a defined metric model, claims about framework value remain
anecdotal and phase planning cannot be grounded in measured outcomes.

---

## References Reviewed

- `ROADMAP.md` - current Phase 8 self-measurement placeholder
- `README.md` - current value proposition
- `docs/plans/21_ecosystem-dashboard-and-status-surfaces.md` - dashboard/status dependency
- `docs/plans/12_cross-repo-plan-registry.md` - current cross-repo visibility baseline
- `docs/plans/18_truth-surface-semantic-review-convergence.md` - current semantic-review state

---

## Research Basis For This Slice

- `docs/plans/21_ecosystem-dashboard-and-status-surfaces.md` - status-surface dependency for metric exposure
- No additional research beyond References Reviewed.

---

## Capabilities

N/A - internal framework design slice; does NOT cross project boundaries or
create callable capability surfaces.

---

## Files Affected

- ROADMAP.md (modify)
- README.md (modify)
- docs/designs/FRAMEWORK_SELF_MEASUREMENT.md (create)
- docs/plans/22_framework-self-measurement-and-roi.md (modify)
- docs/plans/CLAUDE.md (modify if status changes)

---

## Plan

### Steps

1. Define the smallest metric set that would justify framework ROI claims.
2. Decide which metrics are deterministic vs advisory or agent-assisted.
3. Define the data sources and their trust boundaries.
4. Define what counts as "adoption" and what counts as "drift caught."
5. Make the metric model explicit before implementing collection or dashboards.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| metric/status surface tests | framework metric contract tests | Metrics can be computed from declared sources without inventing hidden state |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/22_framework-self-measurement-and-roi.md --warn-only` | Plan remains valid |

---

## Acceptance Criteria

- [x] The framework defines a canonical metric set for ROI and self-measurement
- [x] The design states data sources and trust boundaries for each metric
- [x] "Adoption" and "drift catch" are defined concretely
- [x] The plan depends explicitly on the dashboard/status surface
- [x] Declared checks pass

---

## Decision

Framework self-measurement should:

- reuse the canonical ecosystem-status surface rather than inventing a parallel
  metrics dashboard
- define adoption only as explicit-registry plus strict-governed-audit pass
- count drift as caught only when findings are recorded and later resolved or
  promoted
- separate deterministic operational metrics from advisory semantic/usefulness
  signals
- defer financial ROI and productivity claims until baseline instrumentation
  exists
