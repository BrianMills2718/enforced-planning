# Plan-status-transition guard wiring: canonical-checkout verification

**Date**: 2026-09-09
**Verified by**: Claude Code (claude-sonnet-5)
**Context**: unplanned maintenance following PR #422 (promoted
`check_plan_status_transitions.py` hook wiring from `project-meta` to the
canonical `hooks/git/pre-commit`/`hooks/git/post-commit` templates)

## Why this file exists

A git worktree runs the *canonical* checkout's hooks (`core.hooksPath` is an
absolute/relative path resolved against the common `.git` dir), not its own
copy of `hooks/git/*` -- so PR #422 could not be tested for real by committing
inside the worktree lane that authored it. That PR's own test plan explicitly
called for a second pass: commit something small from the canonical,
non-worktree `~/code/enforced-planning` checkout after merge, and confirm the
new wiring actually fires there.

## What was verified

- Confirmed `git config core.hooksPath` in the canonical checkout resolves to
  `hooks/git` -- i.e. this checkout's live pre-commit/post-commit hooks are
  exactly the files PR #422 changed, not a copy.
- This commit itself (adding this evidence file) is the real-world exercise:
  the pre-commit hook's new section 7b (`check_plan_status_transitions.py`
  staged-mode check) and the post-commit hook's new worktree-mode warn-only
  check both ran as part of committing this file, from the canonical checkout.
- `check_plan_status_transitions.py` does not exist anywhere in this repo, so
  both `find_script()` (pre-commit) and the post-commit for-loop correctly
  resolved to empty and the new checks were a silent no-op -- exactly the
  behavior PR #422 claimed ("safe to land broadly").
- No commit-time or post-commit error, warning, or unexpected output was
  attributable to the new sections; the hook's usual output (locked-couplings,
  doc-coupling, reachability, branch-divergence, unpushed-commit reminder)
  ran unchanged.

**Status**: ✅ PASS -- the promoted wiring is live in the canonical checkout
and behaves as a no-op here, as designed.
