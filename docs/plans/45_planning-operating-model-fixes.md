# Plan #45: Planning Operating Model Fixes (ADR-0010 Follow-Through)

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** PLANNING_OPERATING_MODEL.md has three stale/incomplete items:
1. New System Initialization (steps 1-12) does NOT include the memory recall step — only the Legacy Repo Bootstrap does
2. Non-Goals section still lists "runtime coordination state storage" and "tracker/registry drift validation" as non-goals, but both were fully implemented in Plans #24-42
3. "Relationship to Other Framework Artifacts" section doesn't reference ADR-0010, which is the most recent major architectural decision about how the operating model itself works

**Target:** All three fixed. The operating model is internally consistent with ADR-0010 and current implementation reality.

**Why:** Agents reading the operating model to understand planning requirements will miss the memory recall requirement for new-system initialization, and will see stale non-goals that no longer apply.

---

## References Reviewed

- `PLANNING_OPERATING_MODEL.md` — lines 156-172 (New System Init), lines 289-298 (Non-Goals), lines 276-287 (Relationship section)
- `adr/0010-agent-memory-as-planning-input.md` — ADR-0010 decisions
- `docs/plans/CLAUDE.md` — Plans #24-42 status (all complete: coordination state, tracker/registry)

---

## Research Basis For This Slice

No additional research needed. Fixes are direct consequences of ADR-0010 and completion of Plans #24-42.

---

## Plan

### Steps

1. Add memory recall instruction to New System Initialization step 1 (mirror what was already done to Legacy Bootstrap step 1)
2. Update Non-Goals: remove the two now-implemented items; replace with a truthful statement about what is still out of scope
3. Add ADR-0010 to Relationship to Other Framework Artifacts section

---

## Required Tests

`python scripts/self_test.py` must pass.

## Acceptance Criteria

- [ ] New System Initialization step 1 mentions agent-memory recall
- [ ] Non-Goals section no longer claims coordination state storage and tracker/registry are out of scope
- [ ] ADR-0010 referenced in Relationship section
- [ ] `self_test.py` passes
