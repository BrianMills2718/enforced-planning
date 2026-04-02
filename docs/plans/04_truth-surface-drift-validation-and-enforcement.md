# Plan #4: Truth-Surface Drift Validation and Enforcement

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** project-meta rollout hardening, authoritative coordination closeout

---

## Gap

**Current:** Repo trackers, TODOs, plan indexes, runtime coordination registries,
reservations, worktree state, and canonical-root landing state can drift apart
during live execution. Existing linkage machinery validates static doc/code
alignment, but not live execution truth across those mutable surfaces.

**Target:** The framework provides a truth-surface drift validator and clear
enforcement points for:
- tracker vs registry consistency
- reservation vs plan-file existence
- worktree progress vs parent tracker state
- rollout claims vs canonical-root audit state

**Why:** The current coordination regressions are operational, not just
documentation-based. Without runtime truth-surface validation, the ecosystem can
claim authoritative coordination while its current-state surfaces contradict one
another.

---

## References Reviewed

- `docs/plans/02_canonical-planning-operating-model.md`
- `docs/plans/03_static-planning-graph-and-runtime-truth-surface-split.md`
- `~/projects/project-meta/docs/ops/AUTHORITATIVE_COORDINATION_ROLLOUT.md`
- `~/projects/project-meta/docs/ops/OVERNIGHT_SPRINT_2026_04_02_COORDINATION_WAVE9.md`
- `~/projects/project-meta/docs/ops/AUTHORITATIVE_COORDINATION_WAVE9_TODO.md`
- `~/projects/project-meta/scripts/meta/audit_coordination_rollout.py`
- `~/projects/project-meta/scripts/meta/plan_reservations.py`

---

## Files Affected

- `scripts/check_truth_surface_drift.py` (create)
- `hooks/` or installer surfaces (modify, if enforcement is added)
- validation docs and examples (modify)

---

## Plan

### Steps

1. Define machine-readable truth surfaces and invariants.
2. Implement a validator that emits advisory and failing severities.
3. Wire the validator into closeout/rollout workflows after advisory proving.
4. Generate a compact current-state surface from the validator/audit outputs so
   operators stop hand-maintaining drift-prone status docs.

### Progress Notes

- Implemented first portable validator slice in `scripts/check_truth_surface_drift.py`.
- First slice covers consumed-reservation path existence, active-work references
  to completed plans, and explicit tracker-pattern/registry conflict rules.
- Second slice adds config-driven audit claim parity rules for comparing claimed
  text state against measured audit output.
- Third slice adds `scripts/render_truth_surface_status.py` so validator findings
  can be rendered into a deterministic current-state summary.
- Workflow wiring and rollout-facing closeout guidance remain open.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_truth_surface_drift.py` | `test_missing_plan_file_for_consumed_reservation_fails` | Missing plan targets are hard failures |
| `tests/test_truth_surface_drift.py` | `test_active_tracker_step_already_done_warns_or_fails` | Tracker drift is detected |
| `tests/test_truth_surface_drift.py` | `test_canonical_adoption_claim_requires_canonical_audit` | Rollout docs cannot overclaim adoption |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python -m pytest tests/ -q` | Existing framework validation stays green |

---

## Acceptance Criteria

- [x] Runtime truth-surface invariants are explicit and testable.
- [x] The validator distinguishes static-graph drift from runtime-state drift.
- [x] The first rollout/current-state surface can be derived from validator or
      audit output rather than hand-maintained prose alone.

---

## Open Questions

- [x] Which enforcement points should stay advisory first, and for how long,
      before hard-failing?
      - Resolved for first slice: keep repo-local wiring advisory by default until real governed repos adopt the config.
- [x] Should reservation and claim storage stay file-based for the first validator
      slice, or move to SQLite first?
      - Resolved for first slice: keep file-based storage; revisit SQLite when coordination moves beyond single-host scope.
