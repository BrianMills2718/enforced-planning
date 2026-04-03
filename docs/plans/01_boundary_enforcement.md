# Plan #1: Capabilities Enforcement in Plan Template

**Status:** Partially Complete (template done, pre-commit hook pending)
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** [future] ecosystem-ops capability audit, [future] DIGIMON capability audit

---

## Gap

**Current:** The plan template has a Capabilities section but no pre-commit hook enforces its presence. Plans that create or consume cross-project capabilities can omit the Capabilities table upfront.

**Target:** Plans that create or modify callable cross-project capabilities MUST declare their input/output schemas, producers, and consumers before implementation. The `check_plan_capabilities.py` script enforces this; a pre-commit hook warns on missing Capabilities sections for cross-project plans.

**Why:** Without upfront capability definition, integration bugs are discovered at runtime. Autonomous agents implement features without knowing what format downstream consumers expect.

---

## References Reviewed

- `templates/plan.md.template` — current plan template (no boundaries section)
- `patterns/15_plan-workflow.md` — plan workflow pattern
- `~/projects/data_contracts/` — @boundary decorator and BoundaryModel
- `~/projects/PROJECTS_DEFERRED/enforced_boundary_planning.md` — design doc with full specification

---

## Files Affected

- `templates/plan.md.template` (done — Capabilities section added)
- `scripts/check_plan_capabilities.py` (done — validation script exists)
- `hooks/claude/pre-commit-plan-boundaries.sh` (pending — hook script not yet created)
- `patterns/15_plan-workflow.md` (pending — reference to Capabilities requirement)

---

## Data Boundaries

> This plan does NOT cross project boundaries. It modifies the enforced-planning framework itself.

N/A — internal to enforced-planning.

---

## Plan

### Steps

1. ~~Add Capabilities section to `templates/plan.md.template`~~ ✅ Done
2. ~~Create `scripts/check_plan_capabilities.py`~~ ✅ Done (replaced `check_plan_boundaries.py`)
3. Create hook script for pre-commit Capabilities checking (pending)
4. Update pattern 15 to reference the Capabilities requirement (pending)
5. Test: create a cross-project plan without Capabilities, verify it warns (pending)

---

## Required Tests

### New Tests

| Test | What It Verifies |
|------|------------------|
| `test_boundary_check_internal_plan` | Internal plans pass without boundaries section |
| `test_boundary_check_cross_project` | Cross-project plans without boundaries section get warning |
| `test_boundary_check_with_section` | Plans with proper boundaries section pass |

---

## Acceptance Criteria

- [x] Plan template has Capabilities section (formerly "Data Boundaries") with Input/Output Schema, Producer, Consumer tables
- [x] `check_plan_capabilities.py` correctly identifies cross-project plans (keyword heuristics, opt-out support)
- [x] Script warns (not blocks) on cross-project plans without Capabilities (`--strict` for CI)
- [ ] Pattern 15 references boundary requirement
- [ ] Existing plans in enforced-planning are not broken by the change

---

## Notes

Advisory for existing plans, mandatory for new. The 33 already-registered contracts in the ecosystem validate that the boundary pattern works — this plan just enforces it at planning time.
