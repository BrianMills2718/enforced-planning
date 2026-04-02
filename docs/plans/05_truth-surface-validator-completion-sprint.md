# Plan #5: Truth-Surface Validator Completion Sprint

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** portable rollout guidance, project-meta runtime truth adoption

---

## Gap

**Current:** Plan #4 established the methodology, static-vs-runtime split, and a first validator slice, but the framework still lacks two critical execution surfaces:

1. checks that compare rollout/audit output against claimed tracker or adoption state
2. a generated current-state view derived from validator output so operators stop hand-maintaining drift-prone status prose

The framework also lacks an explicit sprint contract for finishing those slices continuously.

**Target:** `enforced-planning` has one active sprint tracker, one explicit multi-phase implementation plan for the remaining truth-surface work, and verified implementation for:
- consumed reservation path existence
- active work vs completed plan status
- tracker-pattern vs registry conflict rules
- audit-output parity checks
- generated current-state summary rendering
- example workflow wiring for repo-local adoption

**Why:** The framework now has enough design clarity to stop planning in the abstract and finish the portable implementation wedge. Without the remaining validator/rendering slices, the framework still depends on hand-maintained truth surfaces in exactly the area it is trying to govern.

---

## References Reviewed

- `CLAUDE.md`
- `PLANNING_OPERATING_MODEL.md`
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md`
- `docs/plans/04_truth-surface-drift-validation-and-enforcement.md`
- `docs/plans/CLAUDE.md`
- `scripts/check_truth_surface_drift.py`
- `templates/truth_surface_drift.yaml.example`
- `tests/test_truth_surface_drift.py`
- `~/projects/project-meta/docs/ops/AUTHORITATIVE_COORDINATION_ROLLOUT.md`
- `~/projects/project-meta/scripts/meta/audit_coordination_rollout.py`

---

## Files Affected

- `CLAUDE.md` (modify)
- `docs/plans/CLAUDE.md` (modify)
- `docs/plans/05_truth-surface-validator-completion-sprint.md` (create/maintain)
- `docs/ops/OVERNIGHT_SPRINT_2026_04_02_TRUTH_SURFACE.md` (create/maintain)
- `docs/ops/TRUTH_SURFACE_SPRINT_TODO.md` (create/maintain)
- `scripts/check_truth_surface_drift.py` (modify)
- `scripts/render_truth_surface_status.py` (create)
- `templates/truth_surface_drift.yaml.example` (modify)
- `tests/test_truth_surface_drift.py` (modify)
- `tests/test_render_truth_surface_status.py` (create)
- `README.md` / `GETTING_STARTED.md` / pattern docs if workflow wiring changes need documenting

---

## Plan

### Phase A — Sprint Contract and Truthful Entry Surface

Success criteria:
- root `CLAUDE.md` points to one active tracker
- the tracker defines ordered phases, success criteria, open uncertainties, rollback points, and next action
- this plan and the tracker agree about current phase

### Phase B — Audit-Output Parity Checks

Success criteria:
- validator supports audit-derived checks via config, not project-meta hardcoding
- tests cover at least one rollout/adoption parity mismatch
- config example shows how tracker/registry/audit surfaces compose

### Phase C — Generated Current-State Rendering

Success criteria:
- a renderer can emit a compact current-state summary from validator output
- tests verify deterministic rendering for non-empty and clean states
- docs explain that generated current-state surfaces should replace drift-prone prose where feasible

### Phase D — Workflow Wiring and Closeout

Success criteria:
- example wiring for repo-local use is documented or templated
- Plan #4 progress notes reflect what remains versus what shipped
- the tracker is updated to green or records the exact remaining bounded follow-on if a real blocker appears

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_truth_surface_drift.py` | `test_audit_claim_mismatch_fails` | Audit parity mismatch is detected |
| `tests/test_render_truth_surface_status.py` | `test_render_nonempty_summary` | Renderer summarizes findings deterministically |
| `tests/test_render_truth_surface_status.py` | `test_render_clean_summary` | Renderer handles clean state cleanly |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | Framework file/template integrity remains intact |
| `python -m pytest tests/ -q` | Existing framework behavior stays green |
| `ruff check scripts/ tests/` | New scripts remain lint-clean |

---

## Acceptance Criteria

- [ ] The repo has one explicit active sprint tracker for this work.
- [ ] Audit-output parity checks are implemented and tested.
- [ ] Generated current-state rendering is implemented and tested.
- [ ] Framework docs point operators to generated/runtime truth surfaces instead of hand-maintained status prose where applicable.
- [ ] The sprint leaves a truthful next phase rather than an implied one.

---

## Open Questions

- [ ] Should the current-state renderer consume raw validator JSON only, or also support direct surface inputs for convenience?
- [ ] Which workflow entrypoint should eventually host truth-surface validation by default: plan closeout, rollout closeout, or both?

---

## Notes

This plan is the bounded 24-hour execution sprint requested by the operator. It does not supersede Plan #4; it is the explicit execution wrapper around the remaining Plan #4 implementation work.
