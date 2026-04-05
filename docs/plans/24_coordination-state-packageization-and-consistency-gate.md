# Plan #24: Coordination-State Packageization and Consistency Gate

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** [future] truthful stale-worktree cleanup and broader governed-repo coordination convergence

---

## Gap

**Current:** The framework already had a newer v2 claim model under
`~/.claude/coordination/claims/`, but the coordination implementation was still
split across script-only surfaces and older compatibility paths. The framework
lacked one importable package boundary for:

- live claim parsing and validation
- active-work registry generation
- git-worktree consistency checking against the live claim surface

**Target:** `enforced-planning` owns one package-backed coordination-state
implementation with thin CLI wrappers:

- `enforced_planning.coordination_claims`
- `enforced_planning.active_work_registry`
- `enforced_planning.coordination_consistency`

and one explicit proof command:

- `python scripts/check_coordination_consistency.py ...`

**Why:** Continuous multi-worktree execution is not trustworthy if agents cannot
mechanically answer:

1. what the live claims are,
2. what linked worktrees actually exist,
3. whether the generated readable registry matches the canonical live state.

---

## References Reviewed

- `scripts/check_coordination_claims.py`
- `scripts/generate_active_work_registry.py`
- `scripts/worktree-coordination/create_worktree.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_generate_active_work_registry.py`
- `../project-meta/docs/plans/93_wave5-coordination-state-convergence-and-consistency-gate.md`

---

## Research Basis For This Slice

- `../project-meta/docs/plans/62_coordination-claims-v2-and-active-work-registry.md`
- `../project-meta/docs/plans/93_wave5-coordination-state-convergence-and-consistency-gate.md`
- local proof runs against active-stack repos in the shared workspace

---

## Capabilities

N/A - internal framework implementation slice; no new user-facing governed-repo
capability beyond the coordination proof CLI.

---

## Files Affected

- `enforced_planning/coordination_claims.py` (create)
- `enforced_planning/active_work_registry.py` (create)
- `enforced_planning/coordination_consistency.py` (create)
- `scripts/check_coordination_claims.py` (modify)
- `scripts/generate_active_work_registry.py` (modify)
- `scripts/check_coordination_consistency.py` (create)
- `tests/test_check_coordination_claims.py` (modify)
- `tests/test_generate_active_work_registry.py` (modify)
- `tests/test_check_coordination_consistency.py` (create)
- `docs/plans/24_coordination-state-packageization-and-consistency-gate.md` (create)
- `docs/plans/CLAUDE.md` (modify)

---

## Plan

### Steps

| Step | What | Status |
|------|------|--------|
| 1 | Move coordination-claim logic into an importable package module | ✅ Complete |
| 2 | Move active-work registry generation into an importable package module | ✅ Complete |
| 3 | Add a consistency checker that compares live claims, generated registry state, and linked git worktrees | ✅ Complete |
| 4 | Reduce repo-root scripts to thin wrappers around the package modules | ✅ Complete |
| 5 | Prove the new surfaces with focused tests and a real workspace consistency run | ✅ Complete |

---

## Required Tests

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py tests/test_check_coordination_consistency.py` | Proves the package-backed coordination surfaces and consistency CLI |

### Real-Workspace Proof

| Command | What It Verifies |
|---------|------------------|
| `PYTHONPATH=. python scripts/check_coordination_consistency.py --workspace-root /home/brian/projects --repo project-meta --repo enforced-planning --repo moltbot --repo ecosystem-ops --repo prompt_eval --repo llm_client` | The proof command detects hard drift and reports warning-only historical unclaimed worktrees separately |

---

## Acceptance Criteria

- [x] Coordination claims are implemented in `enforced_planning.coordination_claims`
- [x] Active-work registry generation is implemented in `enforced_planning.active_work_registry`
- [x] A package-backed consistency checker exists at `enforced_planning.coordination_consistency`
- [x] Root scripts are thin wrappers, not script-loaded logic
- [x] Focused coordination tests pass
- [x] The real workspace consistency command exits cleanly on hard issues and reports historical warning-only debt separately

---

## Notes

- This slice is intentionally narrow. It packageizes the coordination state and
  proves consistency; it does **not** auto-clean historical unclaimed worktrees.
- The real-workspace proof currently reports warning-only `worktree-unclaimed`
  debt across historical worktrees. That is a follow-on cleanup wave, not a
  failure of this packageization slice.
- The driving cross-repo execution contract for this work was
  `project-meta` Plan #93. This local plan exists to keep `enforced-planning`
  truthful about the implementation it now owns.
