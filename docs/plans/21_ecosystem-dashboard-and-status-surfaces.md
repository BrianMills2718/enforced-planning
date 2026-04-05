# Plan #21: Ecosystem Dashboard and Status Surfaces

**Status:** Planned
**Type:** design
**Priority:** Medium
**Blocked By:** None
**Blocks:** [future] ecosystem operator visibility

---

## Gap

**Current:** The framework has several visibility pieces (`make plan-registry`,
dependency map outputs, roadmap, issue tracker), but no one canonical operator
surface that answers "what is the state of the governed-repo ecosystem?"

**Target:** The framework defines one bounded dashboard/status-surface design
covering:

- plan queue visibility
- governed-repo adoption status
- dependency and coupling visibility
- semantic-review / drift visibility
- upgrade and version visibility

**Why:** Ecosystem operators need one place to start. Right now the visibility
story is split across multiple outputs and docs.

---

## References Reviewed

- `ROADMAP.md` - current Phase 6 and Phase 8 visibility claims
- `docs/plans/12_cross-repo-plan-registry.md` - current plan-registry surface
- `docs/plans/15_selective-plan10-truth-surface-salvage.md` - truth-surface visibility salvage
- `README.md` - current operator-facing top-level positioning
- `ISSUES.md` - current issue-tracker role

---

## Research Basis For This Slice

- `docs/plans/12_cross-repo-plan-registry.md` - existing cross-repo plan visibility baseline
- `docs/plans/15_selective-plan10-truth-surface-salvage.md` - existing truth-surface visibility baseline
- No additional research beyond References Reviewed.

---

## Capabilities

N/A - internal framework design slice; does NOT cross project boundaries or
create callable capability surfaces.

---

## Files Affected

- ROADMAP.md (modify)
- README.md (modify)
- docs/designs/ECOSYSTEM_DASHBOARD_STATUS_SURFACES.md (create)
- docs/plans/21_ecosystem-dashboard-and-status-surfaces.md (modify)
- docs/plans/CLAUDE.md (modify if status changes)

---

## Plan

### Steps

1. Define the operator questions the dashboard/status surfaces must answer.
2. Inventory which current outputs already exist and which are missing.
3. Decide what belongs in:
   - a dashboard
   - a CLI/status command
   - docs-only status surfaces
4. Define the minimum viable surface for the first implementation slice.
5. Define how later metrics and upgrade status plug into the same operator view.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| dashboard/status surface tests | operator visibility contract tests | The chosen status surface exposes the required cross-repo signals |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/21_ecosystem-dashboard-and-status-surfaces.md --warn-only` | Plan remains valid |

---

## Acceptance Criteria

- [ ] The framework defines one canonical operator-facing status surface
- [ ] The design states which existing outputs are reused vs replaced
- [ ] The minimum viable dashboard/status slice is explicit
- [ ] The roadmap points to a numbered dashboard/status plan
- [ ] Declared checks pass
