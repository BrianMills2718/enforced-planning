# meta-process/hooks

This subtree contains the portable hook templates for the meta-process
framework.

## Route Narrower Work

- Claude Code hooks and read-gating templates -> `claude/`
- git hook templates -> `git/`

## Working Rules

- Treat this parent as the router for portable hook behavior.
- Keep tool-specific hook contracts in the child directories, not here.
