# Plan #42: Atomic Closeout And Claimed Worktree Removal

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** Plans #31, #37, and #38
**Blocks:** truthful claimed-lane cleanup and crash-safe closeout recovery

## Gap

The sanctioned worktree lifecycle still split logical finish from physical
cleanup:

- `session-finish` could release the claim first
- `safe_worktree_remove.py` or `git worktree remove` could run later
- `merge_pr.py` could release claims before cleanup

That left a real race. If cleanup and release were separated or interrupted,
the repo could end up with stale claims, missing worktrees, or closeout that
depended on command order instead of one canonical lifecycle.

## Desired Outcome

Claim release, worktree cleanup, and local branch cleanup happen through one
sanctioned closeout operation rather than a manual sequence.

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Canonical command | Add `session-close` as the explicit claimed-lane closeout command | Makes the atomic lifecycle visible |
| Existing finish command | Keep `session-finish` for logical finish/handoff only | Avoids overloading one command with two meanings |
| Make target | `worktree-remove` delegates to `session-close` | Keeps the familiar repo entrypoint while fixing semantics |
| Merge integration | `merge_pr.py` prefers `session_close.py` when available | Prevents pre-release drift during PR cleanup |
| Failure tolerance | Closeout is idempotent for already-missing worktree/branch state | Allows rerunning partially completed cleanup |
| Safety | Dirty worktrees and unresolved authority obligations still fail loud | Cleanup should not bypass correctness gates |

## Files Expected

- `enforced_planning/session_lifecycle.py`
- `scripts/session_close.py`
- `scripts/session_finish.py`
- `scripts/worktree-coordination/safe_worktree_remove.py`
- `scripts/merge_pr.py`
- `scripts/install_governed_repo.py`
- `templates/Makefile.worktree.block.template`
- `tests/test_session_cli.py`
- `tests/test_install_governed_repo.py`
- `tests/test_audit_governed_repo.py`

## Acceptance Criteria

1. Claimed-lane closeout is available as one sanctioned command that removes
   the worktree, deletes the local branch, and releases the claim together.
2. `worktree-remove` no longer depends on a separate manual `session-finish`
   plus cleanup sequence.
3. Rerunning closeout after partial cleanup can still release the claim
   cleanly when the worktree or branch is already gone.
4. Installer and governed-repo audit surfaces include the new closeout command.
5. Operator docs explicitly forbid splitting claim release from claimed
   worktree cleanup.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_session_cli.py tests/test_install_governed_repo.py tests/test_audit_governed_repo.py` | Atomic closeout, installer propagation, and audit expectations agree |
| `python -m py_compile enforced_planning/session_lifecycle.py scripts/session_close.py scripts/merge_pr.py` | The new sanctioned closeout path is syntactically valid |

## Failure Modes And Recovery

| Failure Mode | Expected Handling |
|---|---|
| Worktree still dirty | fail loud; commit or stash before closeout |
| Authority obligations still open | fail loud; do not release the lane |
| Worktree already missing | treat as partial cleanup and continue releasing the claim |
| Branch already deleted | treat as partial cleanup and continue releasing the claim |
| Shell cwd is inside the target worktree | fail loud and require running closeout from the root-anchored control session |

## Outcome

Implemented on 2026-04-05:

- `session-close` is now the canonical claimed-lane closeout command
- `worktree-remove` delegates to `session-close`
- `merge_pr.py` prefers the canonical closeout path instead of releasing claims
  before cleanup
- installer and audit surfaces now expect the sanctioned closeout command
