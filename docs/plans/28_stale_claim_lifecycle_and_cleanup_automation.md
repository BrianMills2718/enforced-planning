# Plan #28: Stale Claim Lifecycle And Cleanup Automation

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** truthful cleanup automation for lane claims after branches land or worktrees disappear

---

## Gap

The claim-v2 runtime distinguishes `healthy` and `weak` claims, but it still
has no first-class concept of a **stale** live claim. Operators can see an
expired claim after TTL pruning, but they cannot mechanically distinguish these
common post-merge/post-cleanup failure modes:

- worktree path is gone but the claim still says `active`
- branch ref is gone but the claim still says `active`
- branch still exists locally but has already landed on the default branch

That leaves stale-claim cleanup subjective and manual. The shared lane registry
also cannot tell the difference between “live but weak” and “no longer truthful
as an active lane.”

## Desired Outcome

The canonical coordination package can diagnose stale live claims, surface them
in the active-work registry, and provide one bounded cleanup command that prunes
claims only when the stale condition is mechanically provable.

---

## Research

- `enforced_planning/coordination_claims.py`
- `enforced_planning/active_work_registry.py`
- `scripts/check_coordination_claims.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_generate_active_work_registry.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `ROADMAP.md`
- live registry snapshot from `python scripts/generate_active_work_registry.py --stdout-json`

---

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Stale definition | A live claim is stale when one or more mechanically provable lifecycle issues exist | Keeps cleanup objective |
| Initial stale issues | `missing_worktree_on_disk`, `missing_branch_ref`, `branch_merged_to_default` | These are actionable and checkable without LLM judgment |
| Repo resolution | Resolve repo roots from the claim worktree path and the `*_worktrees` sibling convention | Works across current governed-repo layouts without hardcoding per-project tables |
| Registry status | `stale` outranks `weak`, `attention`, and `warning` in claim/lane rendering | Stale means the lane state is no longer truthful |
| Cleanup command | Add explicit `--prune-stale`; do not silently fold stale cleanup into `--prune` | Expiry and stale lifecycle are different operator actions |

---

## Files Affected

- `ROADMAP.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/28_stale_claim_lifecycle_and_cleanup_automation.md`
- `docs/plans/CLAUDE.md`
- `enforced_planning/active_work_registry.py`
- `enforced_planning/coordination_claims.py`
- `scripts/check_coordination_claims.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_generate_active_work_registry.py`

---

## Acceptance Criteria

1. The coordination package exposes lifecycle diagnostics for live claims in
   addition to the existing missing-metadata health diagnostics.
2. The registry marks stale claims and lanes explicitly and reports a
   `stale_claim_count` in its health summary.
3. The CLI provides `--prune-stale` and only removes claims whose stale state is
   mechanically proven by the lifecycle checks.
4. Focused coordination tests cover at least:
   - missing worktree on disk
   - missing branch ref
   - branch merged to default branch
   - stale pruning
5. Operator docs explain what “stale” means and when to use `--prune-stale`.

---

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py` | Lifecycle diagnostics and stale pruning behave correctly |
| `python scripts/self_test.py --docs` | Touched docs and plans stay coherent |
| `python scripts/check_markdown_links.py ROADMAP.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/plans/CLAUDE.md docs/plans/28_stale_claim_lifecycle_and_cleanup_automation.md` | Touched docs link cleanly |

## Verification

- `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py`
- `python scripts/self_test.py --docs`
- `python scripts/check_markdown_links.py ROADMAP.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/plans/CLAUDE.md docs/plans/28_stale_claim_lifecycle_and_cleanup_automation.md`
- `python scripts/validate_plan.py --plan-file docs/plans/28_stale_claim_lifecycle_and_cleanup_automation.md --warn-only`
- `python scripts/generate_active_work_registry.py --stdout-json`

## Completion

- [x] Stale lifecycle diagnostics exist in the canonical package
- [x] Registry renders stale claims/lanes distinctly
- [x] `--prune-stale` removes only mechanically stale claims
- [x] Focused coordination tests pass
- [x] Operator docs explain the cleanup path
