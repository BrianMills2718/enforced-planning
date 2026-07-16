# Plan #102: Plan Status Projection Repair

**Status:** Complete
**Type:** implementation
**Priority:** Low
**Landscape disposition:** exempt-trivial
**Blocked By:** None
**Blocks:** None

## Gap

**Current:** `parse_plan_status()` projects canonical `**Status:** Working plan`
metadata as `* Working plan` because its regular expression consumes only one of
the closing emphasis markers.

**Target:** Bold and plain status metadata return the exact status value without
Markdown punctuation.

**Why:** Cross-repo validators and agents should not receive malformed status
values from otherwise canonical plan headers.

## References Reviewed

- `enforced_planning/plan_validation.py` - current status parser
- `tests/test_validate_plan.py` - validator regression coverage
- Inside Success `plan/OWNED_REASONING_SYSTEM_BUILD_PLAN.md` - real dogfood input that exposed the defect
- `EXECUTION_BRIEF.md` - repository execution authority
- `PLANNING_OPERATING_MODEL.md` - canonical planning method
- `docs/overview/CURRENT_STATE.md` - current framework state
- `docs/overview/GAP_SUMMARY.md` - current framework gaps
- `docs/designs/RECURSIVE_DOCUMENTATION_SPINE_AND_REQUIRED_READ_CLOSURE.md` - validator documentation closure design
- `docs/plans/41_doc-authority-governance-and-enforcement.md` - document authority plan
- `docs/plans/54_recursive-documentation-spine-and-required-read-closure.md` - recursive closure design plan
- `docs/plans/55_enforced-planning_recursive_doc_spine_dogfood.md` - framework dogfood plan
- `adr/0009-doc-authority-governance-and-enforcement.md` - document authority decision
- `adr/0010-agent-memory-as-planning-input.md` - planning-input provenance decision

## Landscape And Prior Art

**Reason:** This is a local deterministic parser bug with an enumerable expected
value, no dependency choice, and no architecture or build-versus-adopt decision.

## Acceptance Criteria

| ID | Criterion | Evidence | Target grade |
|----|-----------|----------|--------------|
| C102-1 | Bold `Status` metadata returns `Working plan` exactly. | regression test | A |
| C102-2 | Existing plain and single-emphasis status forms remain supported. | focused tests | A |
| C102-3 | Plan 102 validates with the reasoned trivial exemption and no warnings. | validator JSON | A |

## Files Affected

- `docs/plans/102_plan_status_projection.md`
- `docs/plans/CLAUDE.md`
- `enforced_planning/plan_validation.py`
- `tests/test_validate_plan.py`

## Required Tests

- Add direct both-sign status-parser assertions.
- Run `pytest -q tests/test_validate_plan.py`.
- Run Ruff and strict mypy on the changed module.
- Run `python scripts/self_test.py`.

## Completion Record

- C102-1: **A** - direct regression test returns `Working plan` exactly.
- C102-2: **A** - bold-label, single-emphasis, and plain forms pass in the same test.
- C102-3: **A** - Plan 102 returns `exempt-trivial`, no warnings, no missing
  sections, and no missing strict documentation.
- Verification: 19 focused tests, Ruff, strict mypy with imports skipped,
  framework self-test, and `git diff --check` pass.
