# META-ADR-0012: Progress Leases Are Separate From Session Liveness

**Status:** Proposed
**Date:** 2026-07-14

## Context

The coordination claim model records `heartbeat_at`, which answers whether an
owning runtime is probably alive. A live runtime can nevertheless spend hours
editing, reviewing, or broadening scope without producing an accepted
milestone. Treating heartbeat freshness or file modification time as progress
therefore hides stalled work behind healthy-looking coordination state.

The Plan 0145 Step 5 incident in onto-canon6 demonstrated the failure: the lane
kept heartbeating and changing files for six hours, but it moved into a new
semantic-envelope layer before repairing a known coordinate-proof blocker.

## Decision

Coordination claims will carry a **progress lease** that is independent of the
session heartbeat.

- Heartbeats prove probable runtime liveness only.
- Progress is renewed only by an explicit durable event with a timestamp, kind,
  evidence reference, and next action.
- The progress deadline is configurable. Exceeding it produces a report-only
  `stalled` condition.
- A declared quiet interval may suppress stall reporting for a known long
  operation, but does not count as progress.
- A stalled claim is never automatically released, pruned, rolled back, or
  reassigned. Dirty and committed work remain owned until an explicit handoff,
  release, or closeout action.
- Legacy claims without progress metadata remain readable and are not
  retroactively classified as stalled.

The first slice is visibility only. Later enforcement may prevent scope
broadening after a stall, but only after report-only behavior and negative
controls are accepted.

## Alternatives Considered

### Treat every heartbeat as progress

Rejected because it reproduces the incident: an active loop can renew the
lease indefinitely without advancing the outcome.

### Infer progress from file modification times or git dirt

Rejected because activity is not an accepted milestone, file churn is easy to
produce accidentally, and read-only diagnosis can be genuine progress.

### Automatically release or reassign stalled claims

Rejected because a stalled lane may contain dirty or unique work. Automatic
takeover would turn a visibility improvement into a data-loss and ownership
hazard.

## Consequences

- Operators can distinguish `healthy`, `stalled`, and `stale` lanes.
- Agents must explicitly record what changed and what comes next.
- Status generation gains time-dependent progress classification.
- The first rollout reports problems without changing ownership.
- A dishonest progress event remains possible; the evidence reference makes
  it inspectable, while deeper evidence validation remains a later decision.

## Research Basis

| Source | Relevance |
|---|---|
| [Kubernetes Deployment progress deadlines](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) | Separates continued controller operation from lack of rollout progress and surfaces `ProgressDeadlineExceeded` as status rather than automatically destroying or rolling back work. |
| `docs/plans/29_session_heartbeats_and_agent_liveness.md` | Establishes the existing heartbeat as a liveness lease and its configurable freshness precedent. |
| `~/projects/project-meta/policy_friction.md`, 2026-07-14 progress-lease entry | Records the concrete six-hour coordination incident and the requirement not to auto-release dirty work. |

