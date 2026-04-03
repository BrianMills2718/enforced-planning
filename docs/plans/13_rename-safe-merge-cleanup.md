# Plan #13: Rename-Safe Merge Cleanup

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** truthful completion of merge-helper cleanup after branch rename

---

## Gap

**Current:** The shared `scripts/merge_pr.py` helper can merge a PR correctly, but
its local cleanup step is not rename-safe. It finds the real worktree path for a
branch, then delegates cleanup through `make worktree-remove BRANCH=...`, which
reconstructs the path from the final branch name. If the branch was renamed
before publication, cleanup can fail even though the real worktree path is known.

**Target:** The authoritative helper removes the local worktree by the actual
discovered path, with deterministic verification for the rename-safe case.

**Why:** Renaming a branch before publication is now a sanctioned workflow. The
shared merge helper must not leave orphaned worktrees just because the directory
name still reflects the pre-rename branch.

---

## References Reviewed

- `CLAUDE.md`
- `docs/plans/CLAUDE.md`
- `scripts/merge_pr.py`
- `scripts/worktree-coordination/safe_worktree_remove.py`
- `install.sh`
- `scripts/self_test.py`
- `tests/`

---

## Files Affected

- `CLAUDE.md`
- `docs/plans/13_rename-safe-merge-cleanup.md`
- `docs/plans/CLAUDE.md`
- `docs/ops/SPRINT_2026_04_03_RENAME_SAFE_MERGE_CLEANUP.md`
- `scripts/merge_pr.py`
- `tests/test_merge_pr.py`

---

## Plan

### Phase A — Freeze failure and local sprint authority

Success criteria:
- root `CLAUDE.md` points at this sprint
- the failure mode is frozen explicitly in this plan/sprint

### Phase B — Patch the authoritative helper

Success criteria:
- cleanup uses the discovered worktree path directly when a safe remover is available
- fallback behavior remains explicit and bounded

### Phase C — Add deterministic verification

Success criteria:
- automated tests cover the rename-safe cleanup case
- the pre-fix behavior would have failed the new test

### Phase D — Verify and close out

Success criteria:
- targeted tests and `scripts/self_test.py` pass
- the sprint records the exact consumer replay expectation for downstream repos

---

## Required Tests

| Test | Why |
|------|-----|
| `pytest -q tests/test_merge_pr.py` | Covers rename-safe cleanup behavior |
| `python scripts/self_test.py` | Ensures framework integrity after helper change |

---

## Acceptance Criteria

- [x] Root `CLAUDE.md` points to this sprint while it is active.
- [x] `scripts/merge_pr.py` removes by discovered worktree path when possible.
- [x] A deterministic rename-safe cleanup test exists and passes.
- [x] The sprint records the downstream replay expectation for governed consumers.

## Closeout

- `scripts/merge_pr.py` now prefers path-based cleanup through `safe_worktree_remove.py` when that helper exists, while keeping the older `make worktree-remove BRANCH=...` path as an explicit fallback when no safe remover is installed.
- `tests/test_merge_pr.py` adds deterministic verification for:
  - rename-safe cleanup through the discovered worktree path
  - explicit fallback to `make worktree-remove` when no safe remover exists
  - failure messaging that points operators at the path-based manual command
- Verification passed with:
  - `pytest -q tests/test_merge_pr.py`
  - `python -m py_compile scripts/merge_pr.py tests/test_merge_pr.py`
  - `ruff check scripts/merge_pr.py tests/test_merge_pr.py`
  - `python scripts/self_test.py`
- Downstream replay remains governed by `project-meta` Plan 71, starting with `llm_client`.
