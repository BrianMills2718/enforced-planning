# Plan #1: Add Data Boundary Enforcement to Plan Template

**Status:** Partially Complete (template done, enforcement tooling pending)
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** ecosystem-ops boundary audit, DIGIMON boundary audit

---

## Gap

**Current:** The plan template has no Data Boundaries section. Plans that cross project boundaries don't declare their contracts upfront. Boundaries are defined retroactively (or not at all).

**Target:** Plans that create or consume cross-project data MUST declare boundary contracts before implementation. The template enforces this. A pre-commit hook warns on missing boundaries.

**Why:** Without upfront boundary definition, integration bugs are discovered at runtime. Autonomous agents implement features without knowing what format downstream consumers expect.

---

## References Reviewed

- `templates/plan.md.template` — current plan template (no boundaries section)
- `patterns/15_plan-workflow.md` — plan workflow pattern
- `~/projects/data_contracts/` — @boundary decorator and BoundaryModel
- `~/projects/PROJECTS_DEFERRED/enforced_boundary_planning.md` — design doc with full specification

---

## Files Affected

- `templates/plan.md.template` (modify — add Data Boundaries section)
- `scripts/check_plan_boundaries.py` (create — validation script)
- `hooks/claude/pre-commit-plan-boundaries.sh` (create — hook script)
- `patterns/15_plan-workflow.md` (modify — reference boundary requirement)

---

## Data Boundaries

> This plan does NOT cross project boundaries. It modifies the enforced-planning framework itself.

N/A — internal to enforced-planning.

---

## Plan

### Steps

1. Add Data Boundaries section to `templates/plan.md.template`
2. Create `scripts/check_plan_boundaries.py` — validates boundary section exists for cross-project plans
3. Create hook script for pre-commit boundary checking
4. Update pattern 15 to reference the boundary requirement
5. Test: create a cross-project plan without boundaries, verify it warns

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
