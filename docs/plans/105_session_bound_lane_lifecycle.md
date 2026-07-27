# Plan #105: Session-Bound Lane Lifecycle

**Status:** In Progress
**Type:** coordination lifecycle enforcement
**Priority:** Critical
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** reliable long-running-session cleanup and truthful plan closeout

`trace_evaluable: false # deterministic coordination lifecycle`

## Objective

Prevent one runtime session from silently accumulating unrelated root lanes,
and make a real session termination retire its live ownership without deleting
or losing recoverable Git work.

## Gap

Claims already record session identity, heartbeat, plan, branch, worktree, and
parent scope. Atomic closeout already requires merge or a durable recovery
disposition. However, the live hook surface has no session-end transition,
`handoff` remains live ownership, and the parallel-start check only detects a
duplicate of the same project/plan/scope lane. A week-long session can therefore
open unrelated roots and leave them live after the runtime exits.

## Research

- `enforced_planning/coordination_claims.py` — live-status vocabulary,
  registry lock, heartbeats, session metadata, and root hierarchy checks.
- `enforced_planning/session_lifecycle.py` — start, resume, handoff, status,
  finish, and atomic closeout behavior.
- `enforced_planning/plan_close.py` — all-status plan lane inventory and
  terminal merge/recovery evidence gate.
- `scripts/coordination_hook.py` and current user hook configuration — activity
  heartbeats exist, but no real session-end transition is wired.
- Claude Agent SDK `SessionEndHookInput` in the locally installed SDK — native
  end events include `session_id`, `hook_event_name`, and `reason`.
- Plans #29, #37, #42, #59, #73, #74, and #104 — prior heartbeat, resume,
  closeout, disposition, status-integrity, plan-DAG, and recovery contracts.

## Landscape And Prior Art

**Disposition:** inline. The existing claim registry, session tracker, native
hook surfaces, and atomic closeout already own every required responsibility.
The smallest safe solution is one new non-live lifecycle state, one exact
session transition, and one pre-creation root guard. A scheduler, process
manager, second lock store, or destructive session-exit cleanup would duplicate
authority or risk unique work.

**Alternatives:** Blind claim deletion on exit loses observability; automatic
worktree deletion risks unique work; using `Stop` misclassifies every completed
turn as a terminated runtime; and relying only on TTL leaves normal exits live
for hours. All are rejected.

**Project implications:** Enforced Planning owns the portable implementation
and governed-repo propagation. Project Meta owns only the shared policy registry
and feedback route. User-level Claude/Codex hook configuration points to the
source-owned adapter and does not become a new policy authority.

## Contract

- A session may own one unparented program root by default.
- A related lane uses `parent_scope`; intentional multiple roots require the
  existing explicit parallel authorization.
- Session end changes every exact-session live claim to `session_ended` under
  the registry lock. It preserves the claim, branch, worktree, tracker, and Git
  objects and records the end reason and prior status.
- `session_ended` is non-live ownership but is not terminal disposition. It can
  be resumed, explicitly taken over, or closed through the existing atomic
  merge/recovery path.
- Plan completion remains blocked until every matching claim has accepted
  merged or durable-recovery evidence.
- A native end hook is installed only where the client emits a real
  `SessionEnd` event. A turn-level `Stop` event must never release ownership.
- If a client crashes or cannot emit session end, heartbeat staleness remains
  the degraded-mode signal; no hook deletes a worktree or branch.

## Observability And Feedback

The canonical claim YAML remains the audit record. `session-status` can include
ended sessions and reports their recovery action. The end command emits the
exact affected claim identities and reason as JSON. Shared policy feedback is
routed to Project Meta's existing `policy_friction.md` register and
`make policy-friction` command; this plan does not create a second feedback
store.

## Acceptance Criteria

| ID | Criterion | Evidence |
| --- | --- | --- |
| AC-105-01 | A second unrelated root for one session fails before claim/worktree creation. | positive/negative claim and session-start tests |
| AC-105-02 | An explicitly parallel root and a valid child remain possible. | regression tests |
| AC-105-03 | Session end makes exact-session claims non-live while preserving recovery metadata and worktree state. | lifecycle and hook tests |
| AC-105-04 | An ended lane can resume or close through existing guarded paths. | resume and plan-close tests |
| AC-105-05 | Status output exposes ended lanes and their required recovery action. | CLI/status test |
| AC-105-06 | Claude and Codex user hook configuration invokes the source-owned end adapter only on `SessionEnd`. | config validation and adapter fixture |
| AC-105-07 | Governed-repo installer and Make surfaces include the end/status contract. | installer parity tests |
| AC-105-08 | Operator documentation names enforcement, degraded behavior, observability, and feedback routing. | documentation/link checks |

## Non-Goals

- Deleting historical worktrees merely because a session ended.
- Treating stale heartbeat age as proof that unique work may be discarded.
- Serializing child work or explicitly authorized parallel roots.
- Creating a second lane registry, scheduler, or feedback register.

## Verification

Run focused coordination, session, hook, plan-close, installer, and audit tests;
Ruff on changed Python; the repository self-test; template/source parity; and a
native-hook input fixture before publishing.

## Completion Record

Not started.
