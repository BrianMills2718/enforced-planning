# Plan #1: Capabilities Enforcement in Plan Template

**Status:** Complete
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
- `hooks/git/pre-commit` (done — strict capabilities check wired for staged plan files)
- `patterns/15_plan-workflow.md` (done — references Capabilities requirement)

---

## Data Boundaries

> This plan does NOT cross project boundaries. It modifies the enforced-planning framework itself.

N/A — internal to enforced-planning.

---

## Plan

### Steps

1. ~~Add Capabilities section to `templates/plan.md.template`~~ ✅ Done
2. ~~Create `scripts/check_plan_capabilities.py`~~ ✅ Done (replaced `check_plan_boundaries.py`)
3. Wire capabilities enforcement into `hooks/git/pre-commit` so staged plan files are checked. ✅ Done
4. Update Pattern 15 to reference the Capabilities requirement. ✅ Done
5. Verify existing plan surfaces remain clean under the checker. ✅ Done

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
- [x] Pattern 15 references boundary requirement
- [x] Existing plans in enforced-planning are not broken by the change

---

## Notes

Advisory for existing completed plans, mandatory for new or in-progress cross-project plans. The check now exists in three places:

- `templates/plan.md.template` defines the Capabilities section
- `scripts/check_plan_capabilities.py` validates it
- `hooks/git/pre-commit` runs the checker on staged plan files
