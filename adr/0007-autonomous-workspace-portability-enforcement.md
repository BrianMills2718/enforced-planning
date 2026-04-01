# META-ADR-0007: Autonomous Workspace Portability Enforcement

**Status:** Proposed
**Date:** 2026-03-15

## Context

The pilot for reusable agent workflows requires tooling that can run from locations outside `~/projects`. Existing projects still contain hardcoded path assumptions, so enforcement should start at the boundary where new autonomous work is launched.

## Decision

For any new autonomous-workspace launch, use `bootstrap_autonomous_projects.py` with `--portable-first`.

That mode must:

- run the portability checker during bootstrap
- fail bootstrap when violations are found
- write the portability report to `autonomous_portability_check.json` in the workspace root

## Consequences

### Positive
- New workspaces get a clean portability contract before execution.
- Regressions become explicit and localized to onboarding workflow.
- Existing legacy projects in `~/projects` can continue unchanged while new workflows pilot without breakage.

### Negative
- Portable-first projects must resolve paths via graph/env inputs rather than hardcoded roots.
- Extra migration may be required before a project can be onboarded into strict mode.

### Operational Rule

- New project onboarding should prioritize projects that pass `--portable-first`.
- Keep hardcoded-root exceptions documented as debt entries until a project is migrated.
