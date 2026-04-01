# META-ADR-0002: Thin-Slice Enforcement

**Status:** Accepted
**Date:** 2026-01-18

## Context

Claude Code (and AI coding assistants generally) tends toward **big-bang development**:
- Works for days on implementation without integration testing
- Hopes everything comes together at the end
- Discovers fundamental issues too late
- Results in painful integration failures and rework

This pattern emerged repeatedly in practice:
- Multi-day implementations that failed basic E2E tests
- "Complete" plans that didn't actually work when integrated
- Wasted effort on code that needed fundamental rework

The existing "Thin Slices" section in Pattern 13 mentioned the principle but didn't explain **why** it exists or what problem it solves.

## Decision

**Acceptance gates exist to enforce thin-slice development and prevent big-bang integration.**

This is the primary purpose of the acceptance gate pattern - not just organization or documentation, but **discipline enforcement**.

Key principles:
1. Functional capabilities must pass real E2E tests before being considered complete
2. "Complete" means "gate passed", not "code written"
3. Working for days without E2E verification is an anti-pattern

The meta-process documentation must prominently explain this motivation.

## Consequences

### Positive
- **Clear purpose**: The "why" of acceptance gates is documented
- **Behavior change**: CC instances understand the goal is E2E verification, not just planning
- **Earlier detection**: Integration issues found sooner

### Negative
- **Friction**: Requires E2E tests to exist before claiming completion
- **Overhead**: Some work items may feel "too small" for E2E gates
- **Dependency**: Requires E2E test infrastructure to be working

### Mitigations
- Not every atomic task needs an acceptance gate - only functional capabilities
- Plans (work coordination) have different completion criteria than gates (E2E verification)
- See META-ADR-0003 for the hierarchy clarification
