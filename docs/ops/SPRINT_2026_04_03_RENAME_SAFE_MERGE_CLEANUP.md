# Sprint — 2026-04-03 Rename-Safe Merge Cleanup

Active plan: `docs/plans/13_rename-safe-merge-cleanup.md`

## Mission

Make the shared `merge_pr.py` cleanup path rename-safe by removing local
worktrees through the discovered path rather than reconstructing a path from the
branch name.

## Acceptance Criteria

- [x] Phase A complete: sprint authority and failure freeze are truthful.
- [x] Phase B complete: authoritative helper is patched.
- [x] Phase C complete: deterministic verification exists and passes.
- [x] Phase D complete: self-test and downstream replay expectation are recorded.

## Phase Stack

### Phase A — Freeze and authority
Status: COMPLETE

### Phase B — Patch helper
Status: COMPLETE

### Phase C — Add verification
Status: COMPLETE

### Phase D — Verify and close out
Status: COMPLETE

## Progress Log

- start: opened Plan 13 from the Plan 71 cross-repo sprint after reproducing the rename-sensitive cleanup failure during `llm_client` PR merge
- phase-b: patched `scripts/merge_pr.py` so cleanup uses `safe_worktree_remove.py` with the discovered worktree path when that helper exists
- phase-c: added `tests/test_merge_pr.py` covering rename-safe cleanup, bounded fallback, and failure messaging
- phase-d: verification passed (`pytest -q tests/test_merge_pr.py`, `py_compile`, `ruff`, and `python scripts/self_test.py`); downstream replay remains owned by `project-meta` Plan 71
