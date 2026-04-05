# Plan #31: Session CLI And Governed-Repo Entrypoint Enforcement

**Status:** 📋 Planned
**Type:** implementation
**Priority:** High
**Blocked By:** Plans #29 and #30
**Blocks:** mandatory session-start/session-finish discipline in governed repos

## Gap

Even with claims and heartbeats, governed repos still allow execution without a
declared session contract. That leaves repo/worktree/plan intent implicit and
hard to recover after compaction or handoff.

## Desired Outcome

Governed repos get one sanctioned session lifecycle:

- `session-start`
- `session-heartbeat`
- `session-status`
- `session-finish`

and the sanctioned worktree/finish flows can require those surfaces when the
repo opts in.

## Decisions Pre-Made

- Enforcement lives in shared infrastructure, not per-project ad hoc scripts.
- `make worktree` remains the worktree entrypoint; session bootstrap becomes a
  required adjacent step or integrated wrapper, not a parallel tribal process.
- Finish flows must refuse to clear a lane without commit/stash/handoff state.

## Acceptance Criteria

1. Canonical CLI entrypoints exist for session lifecycle management.
2. Governed repos can install or sync the lifecycle entrypoints.
3. The sanctioned repo interface can require a live session contract.
4. Finish/cleanup flows integrate with session closeout.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_session_cli.py tests/test_install_governed_repo.py tests/test_audit_governed_repo.py` | Session lifecycle CLI and governed-repo enforcement work together |

