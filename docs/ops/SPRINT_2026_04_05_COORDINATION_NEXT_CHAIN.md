# Coordination Next Chain — 2026-04-05

## Mission

Close the remaining coordination-runtime gaps exposed by live execution:

1. publish lanes must fail loud when the canonical primary checkout is unsafe
2. startup surfaces must stop confusing global routing context with ownership of
   the current interactive session
3. queue/routing architecture must build on those truths, not bypass them

## Mandatory Execution Order

1. **Plan #43** — publish-lane safety and dirty primary checkout handling
2. **Plan #44** — interactive startup mode and session-owned surface policy
3. **Plan #35** — queue-based assignment and session routing architecture

Do not reshuffle this queue casually. If a blocker changes the order, write the
reason into this file and the affected plan before continuing.

## Current Known Constraint

- `enforced-planning` root checkout has unrelated ADR dirt that does not overlap
  this lane.
- `ecosystem-ops` root checkout is dirty and has unpublished local work, which
  is exactly why publish-lane safety is the first next slice.

## Completion Rule

A phase is not complete until:

1. verification passes
2. the phase is committed
3. the phase is merged/pushed or its publish blocker is documented explicitly
4. the lane is closed through the sanctioned lifecycle
