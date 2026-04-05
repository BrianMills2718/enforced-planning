# Plan #26: Claim Session Auto-Hydration and Weak-Lane Remediation

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** truthful healthy-lane registry across governed repos

---

## Gap

**Current:** Plan #25 made the lane model explicit and added derived active-lane
rendering. The first real-workspace preview immediately exposed the next defect:
many live lanes are still `weak` only because their claims omit `session_id`.
That metadata is required by the v2 contract, but the shared claim-creation
surface still depends on every caller passing it manually.

**Target:** The canonical claim surface should:

1. auto-resolve `session_id` from the current runtime when possible
2. provide one explicit remediation command for older live claims that are
   missing `session_id`
3. document the remediation path in the operator guide

**Why:** A lane registry that says "weak" for avoidable metadata omissions is
useful as diagnosis, but it should not stay in that state once the framework can
mechanically fix the gap.

---

## Research

- `enforced_planning/coordination_claims.py`
- `scripts/check_coordination_claims.py`
- `tests/test_check_coordination_claims.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/25_lane-model-and-active-lane-registry.md`
- real registry preview from `python scripts/generate_active_work_registry.py --stdout-json`
- `ecosystem-ops/session_handoff.py`

---

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Auto-resolution | Resolve session IDs inside the canonical package module, not only in shell wrappers | Keeps all entrypoints consistent |
| Supported runtime envs | Start with `CODEX_THREAD_ID`, `CLAUDE_SESSION_ID`, `CLAUDE_CODE_SSE_PORT`, and `OPENCLAW_*` envs | Covers the current ecosystem tools without guessing beyond known surfaces |
| Remediation scope | Hydration requires at least `agent` + `project`; it only patches live claims with missing `session_id` | Avoids broad unsafe rewrites |
| Registry behavior | Keep weak-lane classification until claims are actually hydrated | Truthful before convenient |

---

## Files Affected

- `README.md`
- `ROADMAP.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/26_claim-session-auto-hydration-and-weak-lane-remediation.md`
- `docs/plans/CLAUDE.md`
- `enforced_planning/coordination_claims.py`
- `scripts/check_coordination_claims.py`
- `tests/test_check_coordination_claims.py`

---

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py tests/test_check_coordination_consistency.py` | Claim auto-resolution and hydration do not break the coordination stack |
| `python scripts/self_test.py --docs` | Touched docs remain internally consistent |

---

## Acceptance Criteria

- [x] New claim creation can auto-resolve `session_id` from the active runtime when possible
- [x] A safe hydration command exists for older live claims missing `session_id`
- [x] Focused coordination tests pass
- [x] Operator docs explain both automatic capture and explicit remediation
- [x] Real workspace claims can be re-rendered with fewer weak lanes after remediation

---

## Implementation Status

| Step | What | Status |
|---|---|---|
| 1 | Add runtime session auto-resolution to the canonical claim package | ✅ Complete |
| 2 | Add explicit hydration for older live claims missing `session_id` | ✅ Complete |
| 3 | Update operator docs to explain automatic capture and repair | ✅ Complete |
| 4 | Re-run the real active-work registry against live claims and confirm the weak-lane count drops | ✅ Complete |

---

## Verification

- `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py tests/test_check_coordination_consistency.py`
- `python scripts/self_test.py --docs`
- `python scripts/validate_plan.py --plan-file docs/plans/26_claim-session-auto-hydration-and-weak-lane-remediation.md --warn-only`
- `python scripts/check_coordination_claims.py --hydrate-session-ids --agent codex --project enforced-planning`
- `python scripts/check_coordination_claims.py --hydrate-session-ids --agent codex --project project-meta`
- `python scripts/check_coordination_claims.py --hydrate-session-ids --agent codex --project research_texts`
- `python scripts/check_coordination_claims.py --hydrate-session-ids --agent codex --project project-meta --scope remote-master-retirement`
- `python scripts/generate_active_work_registry.py --stdout-json`

Result: the real active-work registry now reports `overall_status=healthy`,
`weak_claim_count=0`.
