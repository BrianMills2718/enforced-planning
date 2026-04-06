# Plan #35: Queue-Based Assignment And Session Routing Architecture

**Status:** ✅ Complete
**Type:** design
**Priority:** Medium
**Blocked By:** Plan #33
**Blocks:** long-term automated assignment / claim-on-start routing

## Gap

The current coordination model now has claims, sessions, trackers, and lanes,
but the higher-level routing story is still ad hoc. Assignment files can help
humans steer sessions, but they are not a queue and they are not yet governed
by the canonical lifecycle.

## Desired Outcome

A future queue-based routing system is designed explicitly on top of the
claim/session model rather than beside it.

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Queue role | Queue decides what can be claimed next; it does not redefine session identity | Keeps authority boundaries clean |
| Session bootstrap | Queue claim should end in the same `session-start` / claim / tracker lifecycle | One execution model |
| Human override | Human-assigned routing may coexist, but queue truth must still be inspectable and bounded | Operational flexibility without hidden state |
| Near-term scope | Design only; do not build queue infrastructure in this slice | Avoids overloading immediate remediation work |

## Files Expected

- `enforced-planning/docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md`
- optional future ADR/design doc for queue state, claim-on-start semantics, and blocking behavior

## Acceptance Criteria

1. The boundary between queue, assignment, claim, session, and lane is explicit.
2. Rejected anti-patterns are documented.
3. A follow-on implementation program can be derived without reopening the
   architecture from scratch.
