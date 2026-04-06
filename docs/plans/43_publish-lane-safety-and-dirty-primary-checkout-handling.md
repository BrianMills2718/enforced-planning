# Plan #43: Publish-Lane Safety And Dirty Primary Checkout Handling

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** —
**Blocks:** Plan #44 downstream startup-mode adoption in repos with dirty primary checkouts

## Goal

Make publish-lane creation fail loud when the canonical primary checkout is not
safe to use as a control surface, instead of allowing ad hoc publish worktrees
that immediately enter split-brain-like or otherwise ambiguous state.

## Why This Phase Exists

Two live coordination slices exposed the same failure mode:

1. a publish worktree created from a repo with dirty or conflicted primary state
   can come up with mass deleted/untracked entries instead of a clean checkout
2. the operator only discovers that after the lane already exists
3. the fallback becomes improvisational instead of sanctioned

That is exactly the kind of workflow ambiguity the coordination layer is meant
to eliminate.

## Research

Reviewed before implementation:

- `scripts/worktree-coordination/create_worktree.py`
- `scripts/merge_pr.py`
- `docs/plans/42_atomic-closeout-and-claimed-worktree-removal.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- live failure reproduced on 2026-04-05 while creating a publish worktree for
  `enforced-planning` and while attempting to land the `ecosystem-ops`
  startup-brief truthfulness branch

## Scope

### In Scope

- deterministic preflight for publish-lane creation
- explicit block when the canonical main checkout is dirty or unmerged
- dedicated publish-worktree helper on top of the shared create-worktree wrapper
- tests for dirty-primary detection
- operator/docs updates that freeze the next coordination execution order

### Out Of Scope

- automatically cleaning or stashing another lane's root-checkout dirt
- solving every possible git/worktree corruption mode
- downstream repo adoption of a publish target in this same slice

## Pre-Made Decisions

| Topic | Decision | Why |
|---|---|---|
| Publish-lane precondition | canonical main checkout must be clean | shared-state landing should not start from already ambiguous root state |
| Failure behavior | fail loud before `git worktree add` | prevents creation of misleading publish worktrees |
| Scope of helper | wrapper around `create_worktree.py`, not a second worktree engine | keep one implementation path |
| Dirty-root response | block and document, do not auto-clean | avoids destroying another lane's local state |
| Execution order after this plan | Plan #43 → Plan #44 → Plan #35 | freeze the next-chain queue explicitly |

## Files Expected

- `scripts/worktree-coordination/create_worktree.py`
- `scripts/worktree-coordination/create_publish_worktree.py`
- `tests/test_create_worktree.py`
- `CLAUDE.md`
- `ROADMAP.md`
- `docs/plans/CLAUDE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/ops/SPRINT_2026_04_05_COORDINATION_NEXT_CHAIN.md`

## Acceptance Criteria

- publish-worktree creation can require a clean canonical main checkout
- dirty or unmerged primary checkout blocks publish-lane creation before a new
  worktree is created
- a dedicated helper exists for publish-worktree creation
- focused tests cover the new preflight
- repo-level execution surfaces document the post-Plan-42 queue clearly

## Verification

```bash
PYTHONPATH=. pytest -q tests/test_create_worktree.py tests/test_merge_pr.py
python -m py_compile scripts/worktree-coordination/create_worktree.py scripts/worktree-coordination/create_publish_worktree.py
python scripts/self_test.py --docs
python scripts/check_markdown_links.py CLAUDE.md ROADMAP.md docs/plans/CLAUDE.md docs/plans/43_publish-lane-safety-and-dirty-primary-checkout-handling.md docs/plans/44_interactive-startup-mode-and-session-owned-surface-policy.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/ops/SPRINT_2026_04_05_COORDINATION_NEXT_CHAIN.md
```

## Failure Modes

| Failure mode | Detection | Response |
|---|---|---|
| publish helper still creates a lane from dirty primary state | focused test or live preflight failure | keep blocking before creation |
| helper blocks clean repos incorrectly | temp-repo happy-path test fails | narrow preflight to actual dirty/unmerged state |
| next queue drifts back into chat-only state | docs/index/CLAUDE mismatch | keep sprint order in repo surfaces, not conversation only |
