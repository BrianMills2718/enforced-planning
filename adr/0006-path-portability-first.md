# META-ADR-0006: Path Portability First for Autonomous Tooling

**Status:** Proposed
**Date:** 2026-03-15

## Context

Current agent tooling and project bootstrap flows still assume paths anchored at `~/projects` (or `/home/brian/projects`), including several reusable scripts and config snippets. This makes:

- Piloting workflows in a different workspace difficult.
- Refactoring harder when projects need to move.
- New agents brittle when absolute roots differ between environments.

The framework is growing toward reusable orchestration, and path assumptions are now a real architectural constraint.

## Decision

All **portable** automation and control-plane tooling should resolve project paths from explicit inputs (`PROJECTS_ROOT`, `PROJECT_META_ROOT`, project graph entries) rather than hardcoded roots.

### Rule

- **Portable set**: tools under `project-meta/scripts`, `meta-process`, and workspace bootstrap scripts should avoid hardcoded `~/projects` / `/home/brian/projects` references.
- **Legacy compatibility exception**: existing non-portable scripts in active projects may keep current references until migrated.
- **Source of truth**: project paths come from `PROJECT_GRAPH.json` or `PROJECTS_ROOT + project id/name`.
- **Validation**: add advisory checks that report hardcoded root usage in candidate portable tooling.

## Consequences

### Positive

- Enables safe pilots in alternate locations (e.g. `~/autonomous_projects`).
- Reduces risk when projects are temporarily re-homed, symlinked, or relocated.
- Makes automation easier to test in isolated environments before scaling to the main workspace.

### Negative

- Initial migration effort: old scripts and docs that are expected to be portable need path normalization.
- Short-term increase in false positives if scanners include historical or legacy references in non-portable files.

### Mitigation

- Start as advisory (warn-only) and enforce only once the pilot baseline passes.
- Keep migration scoped to newly adopted orchestration/pilot tooling first.

## Implementation Notes

1. Add a path portability checker that scans tracked project tooling/code files for hardcoded `~/projects` and `/home/brian/projects`.
2. Run the checker in pilot mode for managed symlink/workspace candidates before promoting checks to global enforcement.
3. Track exceptions and migration debt in `project-meta/investigations` or project-specific ADRs as needed.
