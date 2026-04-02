# Plan #1: Capability and Boundary Requirement Enforcement in Plans

**Status:** Partially Complete (template done, enforcement tooling pending)
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** ecosystem-ops boundary audit, DIGIMON boundary audit

---

## Gap

**Current:** The plan template now has a Capabilities section and `check_plan_capabilities.py` exists, but the remaining backlog language is still framed around the older "Data Boundaries" wording. The unresolved work is not the section itself; it is truthful enforcement and documentation of capability/boundary clarity for cross-project plans.

**Target:** Cross-project plans must declare capability or boundary contracts before implementation, and the remaining tooling/docs should enforce that requirement using the current capability/boundary vocabulary.

**Why:** Without upfront capability/boundary definition, integration bugs are discovered at runtime. Autonomous agents implement cross-project features without a truthful contract for what is produced, consumed, or owned.

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

## Capabilities / Boundaries

> This plan does NOT cross project boundaries. It modifies the enforced-planning framework itself.

N/A — internal to enforced-planning.

---

## Plan

### Steps

1. Keep the existing Capabilities section in `templates/plan.md.template` as the canonical cross-project contract surface.
2. Keep `scripts/check_plan_capabilities.py` as the enforcement entrypoint for cross-project capability/boundary requirements.
3. Add any missing workflow or hook wiring needed so the requirement is not just template text.
4. Update pattern/docs so the requirement is described in current capability/boundary language.
5. Test: create a cross-project plan without capabilities/boundary clarity and verify the warning or strict mode behavior.

---

## Required Tests

### New Tests

| Test | What It Verifies |
|------|------------------|
| `test_capability_check_internal_plan` | Internal plans pass without a cross-project capabilities requirement |
| `test_capability_check_cross_project` | Cross-project plans without capability/boundary clarity get warning |
| `test_capability_check_with_section` | Plans with proper capability/boundary contract pass |

---

## Acceptance Criteria

- [x] Plan template has Capabilities section with Input/Output Schema, Producer, Consumer tables.
- [x] `check_plan_capabilities.py` correctly identifies cross-project plans (keyword heuristics, opt-out support).
- [x] Script warns (not blocks) on cross-project plans without Capabilities (`--strict` for CI).
- [ ] Workflow/pattern docs consistently describe the requirement in capability/boundary language.
- [ ] Existing plans in `enforced-planning` are truthfully aligned with the current capability/boundary model.

---

## Notes

Advisory for existing plans, mandatory for new. The enforcement gap that remains is no longer "add a boundaries section"; it is tightening workflow/docs/tooling so cross-project plans use the capability/boundary model truthfully and consistently.
