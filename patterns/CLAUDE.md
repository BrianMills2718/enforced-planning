# meta-process/patterns

This directory contains the canonical portable meta-process patterns.

## Use This Directory For

- the framework source of truth for pattern behavior
- deciding whether a change belongs in core patterns or only in local repo docs

## Route Narrower Work

- optional multi-agent worktree module -> `worktree-coordination/`

## Working Rules

- Keep core patterns portable and independent of the optional module.
- If a pattern change affects installed docs in `docs/meta-patterns/`, update
  the local copy or sync path in the same change.
