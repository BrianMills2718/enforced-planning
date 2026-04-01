# meta-process/hooks/claude

This directory contains portable Claude Code hook templates.

## Use This Directory For

- read-gating and context-injection hooks
- pre-edit and post-edit guardrails
- Claude-specific runtime checks that governed repos install into `.claude/hooks/`

## Working Rules

- Keep hooks deterministic and shell-safe.
- Hook behavior must degrade gracefully when optional local tooling is absent.
- Changes here affect installed governed repos, so update generators and docs in
  the same change when behavior moves.
