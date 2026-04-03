# enforced-planning/scripts/worktree-coordination

This directory contains the optional portable worktree-coordination scripts.

## Use This Directory For

- scoped worktree creation and cleanup
- safe worktree cleanup
- inter-agent messaging helpers

## Keep One Level Up In `scripts/`

- claim-v2 schema and overlap detection
- generated active-work registry
- canonical worktree-path helpers

## Working Rules

- Keep these scripts optional and isolated from the core baseline.
- If a capability becomes mandatory for single-agent repos, move it out of this
  subtree.
