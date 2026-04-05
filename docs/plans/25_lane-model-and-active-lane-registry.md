# Plan #25: Lane Model and Active-Lane Registry

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** clearer cross-project coordination operation, future stale-lane cleanup automation

---

## Gap

**Current:** The framework has canonical live claims, a readable active-work
registry, sanctioned worktree guidance, and consistency checks. What it does
not yet have is one explicit shared definition of a **lane**. In practice,
humans ask "what lane is active?", but the live coordination surface renders
claims, not lanes. The term appears in plans and trackers, but its relationship
to plans, claims, branches, worktrees, and trackers is still partly implicit.

There is also one concrete truth-surface drift item in this repo:

- Plan #24 exists on disk and is complete, but `docs/plans/CLAUDE.md` and
  `ROADMAP.md` do not currently expose it.

**Target:** `enforced-planning` should define the lane model canonically and
surface it mechanically:

1. the operator guide defines a lane unambiguously
2. the active-work registry renders derived **active lanes** in addition to raw
   claims
3. the registry makes clear that claims remain canonical and lanes are derived
4. the local plan index and roadmap truthfully include Plan #24 and this new
   lane-model slice

**Why:** The coordination system should answer one bounded operator question
without requiring raw YAML inspection:

> what work is active right now, where is it happening, and who owns it?

---

## References Reviewed

- `README.md`
- `CLAUDE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/CLAUDE.md`
- `ROADMAP.md`
- `docs/plans/24_coordination-state-packageization-and-consistency-gate.md`
- `enforced_planning/active_work_registry.py`
- `enforced_planning/coordination_claims.py`
- `tests/test_generate_active_work_registry.py`
- `../project-meta/ISSUES.md` (`ISSUE-008`)
- `../project-meta/docs/plans/90_coordination-hardening-and-graph-explicitification.md`

---

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Canonical truth | Claims stay canonical; lanes remain derived | Avoids inventing a second mutable coordination source |
| Lane grouping | Group by concrete execution metadata first: project + plan + branch + worktree | Matches the operator’s mental model of one bounded worktree slice |
| Weak legacy claims | Claims without branch/worktree fall back to scope-level lane grouping | Keeps older/broader claims visible without incorrectly merging them |
| Surface shape | Keep the existing active-work registry file names and add lane summaries inside them | Improves operator clarity without creating yet another top-level truth surface |
| Scope | Fix Plan #24 indexing drift inside this slice | Same coordination/documentation boundary; cheap truthful cleanup |

---

## Files Affected

- `README.md`
- `CLAUDE.md`
- `ROADMAP.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/24_coordination-state-packageization-and-consistency-gate.md`
- `docs/plans/25_lane-model-and-active-lane-registry.md`
- `docs/plans/CLAUDE.md`
- `enforced_planning/active_work_registry.py`
- `tests/test_generate_active_work_registry.py`

---

## Plan

### Steps

| Step | What | Status |
|---|---|---|
| 1 | Define the lane model and claim/lane relationship canonically in operator docs | ✅ Complete |
| 2 | Add derived lane summaries to the active-work registry JSON and markdown outputs | ✅ Complete |
| 3 | Prove the registry behavior with focused tests | ✅ Complete |
| 4 | Repair local planning truth surfaces so Plans #24 and #25 appear truthfully in the index and roadmap | ✅ Complete |

---

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_generate_active_work_registry.py` | Derived lane summaries and markdown rendering stay correct |
| `python scripts/self_test.py --docs` | Framework docs remain internally consistent |
| `python scripts/check_markdown_links.py README.md CLAUDE.md ROADMAP.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/plans/24_coordination-state-packageization-and-consistency-gate.md docs/plans/25_lane-model-and-active-lane-registry.md docs/plans/CLAUDE.md` | Touched docs resolve cleanly |

---

## Acceptance Criteria

- [x] The operator guide defines a lane and states that claims remain canonical
- [x] The active-work registry payload exposes both `claims` and derived `lanes`
- [x] The active-work registry markdown has a clear `Active Lanes` section
- [x] Focused registry tests pass
- [x] `docs/plans/CLAUDE.md` truthfully lists Plan #24 and Plan #25
- [x] `ROADMAP.md` no longer hides Plan #24 from the forward/backward status story

---

## Notes

- This slice intentionally does **not** introduce a new lane persistence layer.
  If a future system needs first-class lane files, that should be a separate
  bounded plan after the derived model proves useful.
- This slice also does **not** resolve broader raw-Codex-vs-Claude parity. It
  improves coordination clarity at the shared-framework layer so future parity
  work can build on one stable vocabulary.
- Real-workspace preview after landing this slice showed that most current live
  lanes are still `weak` because older claims omitted `session_id`. The next
  highest-value follow-on is claim-hydration / weak-lane cleanup, not another
  terminology rewrite.
