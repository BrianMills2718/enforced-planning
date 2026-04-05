# Worktree Coordination Module

Optional module for teams running **multiple AI coding instances concurrently** on the same codebase.

Canonical operator instructions live in
`docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`. This module README
explains the moving parts and the portability boundary.

## When to Use This

Enable this module when:
- 3+ AI instances work on the same repo simultaneously
- You experience merge conflicts from parallel work
- Instances start the same task without knowing about each other

**Most projects don't need this.** A simple branch-based workflow (one instance at a time) is simpler and sufficient.

## What It Provides

**Claims** — Coordination that prevents two instances from writing the same
scope at once:
- See [18_claim-system.md](18_claim-system.md)

**Worktree Enforcement** — File isolation via git worktrees so each instance has its own working directory:
- See [19_worktree-enforcement.md](19_worktree-enforcement.md)

**Rebase Workflow** — Prevents "reverted" changes when worktrees get stale:
- See [20_rebase-workflow.md](20_rebase-workflow.md)

**PR Coordination** — Tracks review requests between instances:
- See [21_pr-coordination.md](21_pr-coordination.md)

## Session Safety

Some agent runtimes keep a persistent shell CWD. In those environments, a
session that deletes the worktree it is still sitting inside will poison the
shell for later commands.

That is why the Claude hook stack blocks `cd worktrees/...` for the persistent
Bash session and requires merge / finish / worktree removal from a control
session anchored at the canonical repo root.

This is a session-safety rule, not a claim that worktrees are unused. The
worktree is still the isolated execution surface; the control session just must
not delete it from inside itself.

## Setup

1. Enable claims in `meta-process.yaml`:
   ```yaml
   claims:
     enabled: true
   ```

2. Register worktree hooks in `.claude/settings.json` (see hook files in `hooks/claude/worktree-coordination/`)

3. Add worktree targets to your Makefile (see
   `templates/Makefile.worktree.block.template`)

## Related Scripts

Portable coordination scripts now split across two locations:

In `scripts/`:
- `check_coordination_claims.py` — claim-v2 schema, overlap detection, and
  live file-based claims
- `generate_active_work_registry.py` — derived readable current-work registry
- `worktree_paths.py` — canonical repo/worktree-root helpers

In `scripts/worktree-coordination/`:
- `check_claims.py` — legacy active-work claim management
- `create_worktree.py` — sanctioned worktree creation with optional scoped
  write-claim enforcement
- `safe_worktree_remove.py` — Safe worktree removal with checks
- `finish_pr.py` — PR merge + worktree cleanup + claim release
- `check_messages.py` — Inter-instance inbox checking
- `send_message.py` — Send messages between instances

Use the claim-v2 surfaces for cross-project coordination truth. Keep
`check_claims.py` only as the repo-local compatibility layer until convergence.
