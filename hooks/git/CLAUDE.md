# meta-process/hooks/git

This directory contains portable git hook templates.

## Use This Directory For

- pre-commit, commit-msg, and post-commit hook templates shipped by the
  framework

## Working Rules

- Hooks must be portable across governed repos.
- When looking for support scripts, preserve the installed-path pattern that
  checks both `scripts/meta/` and `scripts/`.
- Do not hardcode repo-specific assumptions into these templates.
