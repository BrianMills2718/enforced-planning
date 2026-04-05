# Plan #34: Weak-Claim Remediation And Live-Lane Migration

**Status:** 📋 Planned
**Type:** implementation
**Priority:** High
**Blocked By:** Plans #29-32
**Blocks:** trustworthy operator use of the active registry

## Gap

The coordination stack can now represent healthy session lifecycle state, but
some live lanes in `project-meta` still appear as `weak` or `stale` because
they never migrated onto the session-aware surfaces.

## Desired Outcome

Active high-value lanes are either:

- hydrated onto the session lifecycle model
- explicitly handed off
- or pruned if the lifecycle truth is already broken

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Remediation path | Prefer sanctioned `session-start` / `session-heartbeat` / `session-finish` over direct YAML editing | Keeps migration on the same runtime path we want long-term |
| Weak claims | Hydrate when the worktree/branch is still real and active | Preserves live work |
| Stale claims | Prune or close out when branch/worktree truth is already broken | Avoids pretending dead lanes are healthy |
| Scope | Start with currently visible weak/stale `project-meta` lanes | Highest operator-value cleanup |

## Files Expected

- `project-meta` claimed lane surfaces and their worktrees
- `enforced-planning/docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- optional migration evidence note in `investigations/cross-project/`

## Acceptance Criteria

1. All currently visible weak/stale live lanes under active review are
   adjudicated.
2. The active registry health summary no longer shows known unattended weak
   lanes from the current backlog.
3. Any unresolved lane is documented with a concrete reason, not left as silent
   ambiguity.

## Required Tests

| Command | What It Verifies |
|---|---|
| `python scripts/check_coordination_claims.py --list --json` | Claim health reflects the remediation results |
| `python scripts/generate_active_work_registry.py --stdout-json` | Registry health summary reflects the new lane state |
