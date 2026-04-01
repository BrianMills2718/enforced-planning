# META-ADR-0004: Gate YAML Is Documentation

**Status:** Accepted
**Date:** 2026-01-18

## Context

The project had two locations for acceptance gate information:
1. `acceptance_gates/*.yaml` - Gate definitions with specs, criteria, code mappings
2. `docs/acceptance_gates/*.md` - Markdown documentation about gates

This created:
- **Redundancy**: Same information in two places
- **Drift**: Markdown could become stale relative to YAML
- **Confusion**: Which is authoritative?
- **Naming collision**: Two directories with similar names, different purposes

The YAML files already contained documentation-like content:
- `problem:` - Why this gate exists
- `design:` - How it will be implemented
- `out_of_scope:` - What's explicitly excluded
- `acceptance_criteria:` - What must pass (Given/When/Then)

## Decision

**The gate YAML file is the documentation. No separate markdown files for gates.**

The `acceptance_gates/*.yaml` files are the single source of truth containing:
- Problem statement (why)
- Acceptance criteria (what)
- Design approach (how, optional)
- Out of scope (boundaries)
- Code/test/doc mappings

**Delete `docs/acceptance_gates/`** and merge any unique content to `docs/architecture/current/`.

## Consequences

### Positive
- **Single source of truth**: One place for gate information
- **No drift**: Can't have stale markdown
- **Simpler structure**: One directory, not two
- **Portability**: Gate definition is self-contained

### Negative
- **YAML readability**: Markdown is more human-friendly for long prose
- **Migration**: Existing markdown content must be relocated

### Mitigations
- Extended documentation (deep explanations, tutorials) belongs in `docs/architecture/current/`
- Gate YAML should be concise - problem/criteria/design, not essays
- The YAML `problem:` field uses YAML multiline strings for readability

### Migration
| Current Location | Action |
|------------------|--------|
| `docs/acceptance_gates/dashboard.md` | Merge to `docs/architecture/current/supporting_systems.md` |
| `docs/acceptance_gates/mint_auction.md` | Merge to `docs/architecture/current/mint.md` |
| `docs/acceptance_gates/README.md` | Delete (covered by `acceptance_gates/CLAUDE.md`) |
| `docs/acceptance_gates/CLAUDE.md` | Delete (redundant) |
