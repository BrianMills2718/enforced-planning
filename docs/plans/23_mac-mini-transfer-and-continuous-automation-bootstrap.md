# Plan #23: Mac Mini Transfer and Continuous Automation Bootstrap

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** [future] Mac mini governed-repo rollout, [future] continuous overnight automation on macOS

---

## Gap

**Current:** `enforced-planning` now has a coherent installer, audit path, and
Phase 8 queue, but there is no one bounded plan for transferring the framework
and its governed-repo adoption model onto the Mac mini as the base for
continuous automation.

**Target:** The framework has:

- an explicit overnight sprint tracker for the next 24 hours
- a Mac mini bootstrap guide for framework transfer and first governed-repo rollout
- Phase 8 work queued and then executed as numbered plans rather than as a vague bucket
- source-repo policy surfaces that strongly encode continuous execution,
  worktree-first operation, and commit/rollback discipline

**Why:** The Mac mini move is not just a machine change. It is the handoff point
from interactive framework development to durable continuous automation.

---

## References Reviewed

- `ROADMAP.md` - current Phase 8 queue and follow-on work
- `docs/plans/CLAUDE.md` - current numbered plan registry
- `docs/plans/19_multi-tool-support-matrix-and-rollout.md` - support-tier planning slice
- `docs/plans/20_governed-repo-upgrade-automation.md` - upgrade-automation planning slice
- `docs/plans/21_ecosystem-dashboard-and-status-surfaces.md` - dashboard/status planning slice
- `docs/plans/22_framework-self-measurement-and-roi.md` - self-measurement planning slice
- `scripts/install_governed_repo.py` - canonical installer/upgrader
- `scripts/audit_governed_repo.py` - canonical mechanical audit path
- `CLAUDE.md` - current repo workflow guidance

---

## Research Basis For This Slice

- `docs/plans/17_governed-repo-installer-convergence.md` - installer authority decision
- `docs/plans/19_multi-tool-support-matrix-and-rollout.md` - support-tier queue
- `docs/plans/20_governed-repo-upgrade-automation.md` - upgrade-automation queue
- No additional research beyond References Reviewed.

---

## Capabilities

N/A - internal framework execution slice; does NOT cross project boundaries or
create callable capability surfaces.

---

## Files Affected

- CLAUDE.md (modify)
- ROADMAP.md (modify)
- docs/plans/CLAUDE.md (modify)
- docs/plans/23_mac-mini-transfer-and-continuous-automation-bootstrap.md (modify)
- docs/ops/SPRINT_2026_04_04_MAC_MINI_CONTINUOUS_AUTOMATION.md (create)
- docs/guides/MAC_MINI_CONTINUOUS_AUTOMATION_BOOTSTRAP.md (create)
- docs/plans/19_multi-tool-support-matrix-and-rollout.md (modify)
- docs/plans/20_governed-repo-upgrade-automation.md (modify)
- docs/plans/21_ecosystem-dashboard-and-status-surfaces.md (modify)
- docs/plans/22_framework-self-measurement-and-roi.md (modify)

---

## Plan

### Steps

1. Create an explicit 24-hour sprint tracker that sequences the overnight work.
2. Strengthen `CLAUDE.md` so continuous execution, worktree-first operation, and
   regular commits are first-class repo policy.
3. Create the Mac mini bootstrap guide covering:
   - framework repo transfer
   - environment bootstrap
   - first governed-repo install/audit/verify cycle
   - continuous automation launch boundary
4. Execute Plans #19-#22 as bounded Phase 8 design/implementation slices.
5. Update the queue and sprint tracker as each slice completes.
6. Close the umbrella plan only after the sprint tracker and Mac mini bootstrap
   surfaces are truthful.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `scripts/self_test.py` or successor | sprint/bootstrap doc assertions | Core queue and bootstrap surfaces remain present and coherent |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/23_mac-mini-transfer-and-continuous-automation-bootstrap.md --warn-only` | Plan remains valid |
| `python scripts/self_test.py` | Source-repo docs and installer contract remain coherent |
| `pytest -q tests/test_install_governed_repo.py tests/test_audit_governed_repo.py` | Mac mini bootstrap still rests on a verified installer/audit path |

---

## Acceptance Criteria

- [x] A 24-hour sprint tracker exists and sequences the overnight queue clearly
- [x] `CLAUDE.md` strongly encodes continuous execution, worktree-first operation, and commit discipline
- [x] A Mac mini bootstrap guide exists for framework transfer and first governed-repo rollout
- [x] Plans #19-#22 are executed or advanced truthfully within the sprint
- [x] Declared checks pass

---

## Decision

The overnight bootstrap slice should close with:

- a committed sprint tracker rather than an implicit chat queue
- a Mac mini guide that treats the first rollout as a controlled pilot, not a
  blind fleet migration
- explicit worktree-first and commit-first policy in `CLAUDE.md`
- Phase 8 design slices complete before the first real Mac mini pilot rollout
