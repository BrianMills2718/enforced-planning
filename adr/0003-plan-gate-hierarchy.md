# META-ADR-0003: Plan-Gate Hierarchy

**Status:** Accepted
**Date:** 2026-01-18

## Context

Pattern 13 stated: "Every unit of work must prove it works end-to-end before declaring success."

This was overstated. Not every atomic work item can or should have E2E tests:
- Adding a helper function doesn't warrant E2E
- Refactoring internals shouldn't require new E2E tests
- Some changes are too small to be "functional capabilities"

The relationship between plans (work coordination) and acceptance gates (E2E verification) was unclear.

## Decision

Establish a clear hierarchy:

```
Acceptance Gate (functional capability)    ← E2E test required
└── Plan(s) (work coordination)            ← Unit/integration tests
    └── Task(s) (atomic work)              ← May have no tests
```

**Key distinctions:**

| Concept | Purpose | Test Level | Done When |
|---------|---------|------------|-----------|
| Acceptance Gate | E2E checkpoint for functional capability | E2E (no mocks) | Real E2E tests pass |
| Plan | Work coordination document | Unit/integration | Code complete, unit tests pass |
| Task | Atomic work item | Optional | Work done |

**Relationships:**
- Multiple plans can contribute to one acceptance gate
- A plan can be "complete" while its gate is still not passed
- Gate completion is the **real** checkpoint

**When E2E is appropriate:**

| Scope | E2E? | Example |
|-------|------|---------|
| Functional capability | Yes | "Agents can trade via escrow" |
| Infrastructure | Maybe | "Rate limiting throttles calls" |
| Refactor | No* | "Rename oracle to mint" |
| Bug fix | Sometimes | Depends on user-visibility |
| Utility addition | No | "Add string helper" |

*Existing E2E must still pass for refactors.

## Consequences

### Positive
- **Appropriate scope**: E2E tests where they make sense
- **Reduced friction**: Not every change needs E2E
- **Clear expectations**: Plans vs gates have different completion criteria

### Negative
- **Complexity**: Two concepts to understand (plan vs gate)
- **Judgment required**: Deciding what constitutes a "functional capability"

### Guidance
A good heuristic: if you can describe it as "users/agents can [verb]", it's probably a functional capability that warrants an acceptance gate.
