# META-ADR-0001: Acceptance Gate Terminology

**Status:** Accepted
**Date:** 2026-01-18

## Context

The meta-process documentation used two terms interchangeably:
- "Feature" - a common software development term
- "Acceptance gate" - describing the E2E verification checkpoint

This caused confusion:
1. "Feature" is overloaded - it means different things in different contexts (product feature, feature flag, feature branch, etc.)
2. Documentation inconsistently used both terms for the same concept
3. The purpose of the concept (a gate that must be passed) was lost in the generic term "feature"

Pattern 11 (Terminology) defined: `Feature (E2E acceptance gate)` - treating them as synonyms rather than choosing one.

## Decision

Use **"acceptance gate"** as the canonical term for E2E verification checkpoints. Do not use "feature" to describe this concept.

**Rationale:**
1. "Acceptance gate" conveys the mechanism - it's a gate you must pass, not an optional checkpoint
2. The name encodes the discipline - it's not a suggestion, it's a requirement
3. Eliminates confusion with overloaded "feature" terminology

**Terminology mapping:**
| Old Term | New Term |
|----------|----------|
| Feature | Acceptance gate |
| Feature definition | Gate definition |
| Feature-driven development | Acceptance-gate-driven development |
| Feature completion | Gate passed |

## Consequences

### Positive
- **Clarity**: Single unambiguous term
- **Intent**: Name conveys that passing the gate is mandatory
- **Consistency**: All documentation uses one term

### Negative
- **Migration**: Existing documentation needs updating (patterns 11, 13, 14)
- **Familiarity**: "Feature" is more widely understood; "acceptance gate" requires explanation
- **Length**: "Acceptance gate" is longer than "feature"

### Neutral
- The `acceptance_gates/` directory name already uses the correct term
- YAML files don't need renaming
