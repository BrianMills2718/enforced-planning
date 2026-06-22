# Plan #57: Plan Status Index Parser Compatibility

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9"
**goal_ref:** "planning-enforcement-maintenance"
**adrs_referenced:** []
**research_citations:** []
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** `python scripts/sync_plan_status.py --check` reported every plan
file as missing from the index even though `docs/plans/CLAUDE.md` was visibly
populated. The parser still looked for an old `## Gap Summary` heading, while
the current index starts with `# Implementation Plans` and places the table
after a short intro paragraph.

**Target:** The status sync parser locates the plan index table by Markdown
table headers (`#` and `Status`) rather than by a historical surrounding
heading. It remains compatible with the older `## Gap Summary` fixture format.

**Why:** Plan status sync is an enforcement surface. A stale parser creates
false-positive drift reports, which makes agents less likely to trust the
planning checks.

---

## References Reviewed

- `scripts/sync_plan_status.py` - source status sync parser and CLI
- `scripts/meta/sync_plan_status.py` - installed-copy status sync parser and CLI
- `tests/test_sync_plan_status.py` - existing parser coverage
- `docs/plans/CLAUDE.md` - current plan index table format
- `docs/plans/56_modality-aware-planning-protocol.md` - originating limitation note

---

## Research Basis For This Slice

No additional research beyond References Reviewed.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Parser compatibility | Deductive / plan-first | The failure mode and expected behavior are concrete and reproducible. | Add a structural table parser and regression tests for old and current formats. |
| Installed-copy parity | Deductive / plan-first | `scripts/meta/sync_plan_status.py` is meant to mirror the source script. | Apply the same parser change to both files and compile both. |

**Exploratory readout:** Not applicable; this is a deterministic enforcement
bug.

**Step-down path:** If status sync fails again, inspect the concrete index
table header and add a parser fixture before changing CLI behavior.

---

## Files Affected

- docs/plans/56_modality-aware-planning-protocol.md (modify)
- docs/plans/57_plan-status-index-parser-compatibility.md (create)
- docs/plans/CLAUDE.md (modify)
- scripts/meta/sync_plan_status.py (modify)
- scripts/sync_plan_status.py (modify)
- tests/test_sync_plan_status.py (modify)

---

## Plan

### Steps

1. Replace the heading-anchored index parser with a Markdown table parser keyed
   by `#` and `Status` header cells.
2. Preserve legacy `## Gap Summary` fixture compatibility.
3. Add a regression fixture for the current `# Implementation Plans` index.
4. Apply the same parser logic to the installed-copy script.
5. Run focused tests, real `--check`, compile checks, and framework self-test.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_sync_plan_status.py` | `test_parse_index_table_current_implementation_plans_format` | The current `docs/plans/CLAUDE.md` table shape parses by headers, without `## Gap Summary`. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `pytest -q tests/test_sync_plan_status.py` | Parser regressions stay covered. |
| `python scripts/sync_plan_status.py --check` | The real repo plan index now checks cleanly. |
| `python -m py_compile scripts/sync_plan_status.py scripts/meta/sync_plan_status.py` | Both source and installed-copy scripts compile. |
| `python scripts/self_test.py` | Framework-level validation remains green. |

---

## Acceptance Criteria

> Feature-level criteria:
- [x] `parse_index_table()` supports the current `# Implementation Plans` table.
- [x] `parse_index_table()` still supports the older `## Gap Summary` fixture.
- [x] `python scripts/sync_plan_status.py --check` passes in the real repo.
- [x] Source and installed-copy sync scripts remain aligned.

> Process criteria:
- [x] Focused tests pass.
- [x] Framework self-test passes.
- [x] Docs/plans updated.

---

## Verification Results

- `pytest -q tests/test_sync_plan_status.py` - passed
- `python scripts/sync_plan_status.py --check` - passed
- `python -m py_compile scripts/sync_plan_status.py scripts/meta/sync_plan_status.py` - passed
- `cmp -s scripts/sync_plan_status.py scripts/meta/sync_plan_status.py` - passed
- `ruff check scripts/sync_plan_status.py scripts/meta/sync_plan_status.py tests/test_sync_plan_status.py` - passed
- `python scripts/validate_plan.py --plan-file docs/plans/57_plan-status-index-parser-compatibility.md --warn-only` - passed
- `python scripts/self_test.py` - passed

---

## Notes

This deliberately does not add Modality Assessment enforcement. It only fixes
the stale plan-index parser discovered while verifying Plan #56.
