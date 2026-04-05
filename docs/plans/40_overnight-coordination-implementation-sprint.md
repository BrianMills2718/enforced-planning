# Plan #40: Overnight Coordination Implementation Sprint

**Status:** 🚧 In Progress
**Type:** implementation sprint
**Priority:** High
**Blocked By:** Plans #33, #37, #38, and #39 being defined
**Blocks:** a clean end-to-end closeout of the current coordination program

## Gap

The remaining coordination work is now understood, but it still spans multiple
repos and multiple implementation slices:

- downstream assignment/session adoption in `ecosystem-ops`
- explicit plan-bound crash/recovery lifecycle in `enforced-planning`
- remediation of weak/stale legacy lanes
- worktree-aware markdown-link validation
- authority-drift closeout gates

Without one explicit sprint contract, the work is easy to reorder
opportunistically or leave half-landed.

## Desired Outcome

The next 24 hours of coordination work execute as one bounded sprint with:

- explicit slice order
- explicit repo/worktree ownership per slice
- explicit verification commands
- explicit blocker handling

## Research

Reviewed before freezing this sprint:

- `CLAUDE.md`
- `ROADMAP.md`
- `docs/plans/CLAUDE.md`
- active coordination registry state
- in-progress `ecosystem-ops` Plan #33 worktree
- active `enforced-planning` Plan #24 authority lane

The main uncertainty is not what to do next. It is only whether Plan #38 can be
landed immediately or must wait for the currently active Plan #24 authority
lane.

## Execution Order

1. **Plan #33**
   Finish `ecosystem-ops` assignment/session contract integration and land it.
2. **Plan #37**
   Implement plan-bound session identity plus `resume` / `handoff` /
   `abandon` lifecycle.
3. **Plan #34**
   Remediate currently weak/stale lanes using the new lifecycle tooling.
4. **Plan #39**
   Investigate and, if needed, implement shared worktree-aware markdown-link
   validation.
5. **Plan #38**
   Implement authority-drift reconciliation gates if the overlapping Plan #24
   authority lane is either landed or can absorb the work without conflict.

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Sprint discipline | Every slice runs in its own dedicated worktree | Rollback, review, and cleanup must stay cheap |
| Commit policy | Every verified slice gets its own commit before moving on | Prevent invisible overnight work |
| Merge policy | Root-anchored control session merges and pushes between slices | Avoid worktree-CWD cleanup hazards |
| Plan #38 blocker | Do not silently overlap the active Plan #24 authority lane | Respect claimed authority surfaces |
| Weak/stale lanes | Use lifecycle tooling, not direct YAML edits, unless the tooling itself is the broken surface | Keep migration on the canonical path |

## Acceptance Criteria

1. Each slice above is either landed or closed with a written blocker.
2. No finished slice is left only in a worktree branch.
3. The coordination registry is healthier at sprint end than at sprint start.
4. Any deferred item has a written owner and blocking condition on disk.

## Required Verification

| Slice | Verification |
|---|---|
| Plan #33 | focused `ecosystem-ops` assignment/session tests |
| Plan #37 | `tests/test_session_cli.py` and related coordination tests |
| Plan #34 | active registry and claim-list health checks |
| Plan #39 | markdown-link/worktree tests plus real CLI runs from main and worktree checkouts |
| Plan #38 | authority validator tests and closeout-gate proof |

## Stop Conditions

Only these are real stop conditions:

1. irreversible action affecting shared state
2. a genuine architectural decision not already pre-made in the active plan
3. Plan #38 cannot proceed without violating the active Plan #24 claim and no
   safe ownership transfer exists

Everything else is not a stop condition; it belongs in the sprint tracker and
the next bounded slice.
