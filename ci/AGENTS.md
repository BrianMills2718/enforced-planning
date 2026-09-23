# enforced-planning/ci

This directory holds portable CI templates for the enforced-planning framework.

## Use This Directory For

- CI workflow templates intended for installation into governed repos

## Working Rules

- Keep templates portable. No hardcoded workspace-specific paths, usernames, or
  repo names.
- Prefer feature detection and graceful degradation over assumptions about a
  target repo's tooling.
