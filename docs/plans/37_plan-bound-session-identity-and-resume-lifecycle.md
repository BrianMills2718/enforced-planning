# Plan #37: Plan-Bound Session Identity And Resume Lifecycle

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** Plans #29-32
**Blocks:** reliable crash recovery, duplicate-lane prevention, and truthful long-running session continuity

## Gap

The coordination stack now has session identity, trackers, and heartbeat-backed
liveness, but it still permits an operational ambiguity:

- a new runtime can conceptually resume old work without an explicit
  `plan_ref + scope` reattachment flow
- stale lanes can be detected, but their recovery path is not yet formalized
- closeout semantics distinguish clean finish versus dirty handoff, but not the
  broader resume / abandon / transfer lifecycle

That leaves "same conceptual work, new runtime" dependent on memory rather than
mechanical coordination truth.

## Desired Outcome

Every live session is explicitly attached to a plan-bound lane, and resuming
work after a crash or intentional session closure becomes an explicit lifecycle
action rather than an implicit guess.

## Research

Reviewed before freezing this plan:

- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md`
- `enforced_planning/coordination_claims.py`
- `enforced_planning/session_lifecycle.py`
- `enforced_planning/session_contracts.py`
- Plans `29_session_heartbeats_and_agent_liveness.md`,
  `30_session_bootstrap_contract_and_tracker.md`, and
  `31_session_cli_and_governed_repo_entrypoint_enforcement.md`

The gap is not basic liveness. The gap is explicit recovery semantics after
heartbeat expiry and a mandatory plan anchor for every resumed lane.

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Session attachment | Every live session must declare `plan_ref` except explicitly marked emergency/unplanned work | Resume and duplicate detection need a stable anchor |
| Recovery model | Treat sessions as leases; crash detection is heartbeat expiry, not daemon presence | Cross-tool and failure-tolerant |
| Resume semantics | A new runtime must explicitly resume an existing `project + plan_ref + scope` lane | Prevents duplicate live lanes that are really one mission |
| Parallel work | Starting a second live lane on the same `project + plan_ref + scope` fails unless `--allow-parallel` is explicit | Parallelism should be chosen, not accidental |
| Lifecycle states | Keep canonical states `healthy`, `handoff`, `stale`, and `completed` | Small, operator-meaningful state machine |
| Dirty stale worktrees | Stale + dirty is an escalation state that must become resumed, handed off, or abandoned | Avoids pretending abandoned work is healthy |

## Files Expected

- `enforced_planning/session_lifecycle.py`
- `enforced_planning/session_contracts.py`
- `enforced_planning/coordination_claims.py`
- `scripts/session_start.py`
- `scripts/session_status.py`
- new lifecycle CLI surfaces for `session_resume`, `session_handoff`, and `session_abandon`
- `tests/test_session_cli.py`
- `tests/test_generate_active_work_registry.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`

## Acceptance Criteria

1. `session-start` refuses new live sessions without `plan_ref` unless the
   caller explicitly declares sanctioned unplanned work.
2. A sanctioned `session-resume` path can reattach a new runtime to an existing
   stale or handed-off plan-bound lane when branch/worktree identity still
   matches.
3. A sanctioned `session-abandon` or equivalent explicit closeout path can mark
   dead lanes as intentionally abandoned instead of leaving them stale forever.
4. Starting another live session on the same `project + plan_ref + scope`
   fails by default unless parallelism is explicitly requested.
5. Session status surfaces clearly distinguish healthy, handoff, stale, and
   completed lanes and show the recovery action required for stale lanes.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_session_cli.py tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py` | Plan-bound session lifecycle, resume/handoff/abandon behavior, and duplicate-lane prevention work as designed |
| `python scripts/self_test.py --docs` | Operator docs stay truthful as the lifecycle model expands |

## Failure Modes And Recovery

| Failure Mode | Expected Handling |
|---|---|
| Crash leaves lane stale but worktree still exists and is dirty | `session-resume` or `session-handoff`, not silent replacement |
| Crash leaves lane stale and branch is already merged | stale claim is prunable after confirmation |
| Human intentionally closes a session and later returns | explicit `session-resume` against the same plan-bound lane |
| Operator tries to start a fresh session for the same lane | fail unless `--allow-parallel` is explicit |
| Emergency unplanned work is required | force explicit unplanned marker so the deviation is visible |

## Notes

This plan intentionally treats "resume" as a first-class lifecycle action. That
is the missing piece between heartbeat-based liveness and trustworthy
long-running execution.

Implemented on 2026-04-05:

- mandatory plan-bound session start with explicit unplanned override
- duplicate live-lane prevention on `project + plan_ref + scope`
- `session-resume`, `session-handoff`, and `session-abandon`
- recovery-action reporting in session status
