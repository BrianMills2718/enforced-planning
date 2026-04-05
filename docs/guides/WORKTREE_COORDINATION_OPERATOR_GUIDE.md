# Worktree And Coordination Operator Guide

This is the authoritative operator guide for sanctioned worktree usage and
cross-agent coordination in governed repos. Use this document for day-to-day
workflow. Keep rationale, rollout history, and boundary design in the pattern
and project-meta docs; do not treat them as competing operator handbooks.

## Canonical Truth Surfaces

- Cross-project coordination claims: `~/.claude/coordination/claims/*.yaml`
- Readable current-work snapshot: `~/.claude/coordination/active-work-registry.yaml`
- Repo-local in-flight architectural decisions: each repo's `KNOWLEDGE.md`
  `## Active Decisions`
- Repo opt-in switch: `meta-process.yaml`
- Sanctioned repo-local worktree interface: `make worktree`,
  `make worktree-list`, `make worktree-remove`

The older repo-local `.claude/active-work.yaml` plus
`scripts/meta/worktree-coordination/check_claims.py` surface is still present
in some repos for compatibility. It is not the canonical cross-project
coordination authority.

## Default Flow

1. Keep the canonical repo checkout on `main` or `master`.
2. Create one sibling worktree per bounded task:
   `git worktree add ../<repo>_worktrees/<branch> -b <branch> <trunk>`.
   In sanctioned repos prefer `make worktree BRANCH=... TASK="..." [PLAN=N]`.
3. Give each worktree one mission and one plan or one bounded temporary plan
   doc. Do not let a worktree become a second long-lived control plane.
4. Keep generated proof artifacts inside the worktree until they are
   intentionally promoted.
5. Merge back quickly. If a worktree starts owning root truth surfaces for
   days, it is no longer acting like a worktree slice.

## Session Safety

Some agent runtimes keep a persistent shell working directory. In those
environments, deleting a worktree from a session whose shell CWD still points
inside that worktree breaks subsequent shell commands.

Practical rule:

- keep one control session anchored at the canonical repo root
- run merge / finish / worktree removal from that root-anchored session
- do not delete a worktree from a session whose shell CWD is inside it

The `block-cd-worktree.sh`, `warn-worktree-cwd.sh`, and
`enforce-make-merge.sh` hooks enforce this safety rule for Claude Code style
sessions. That safety rule does not mean worktrees are optional; it means
cleanup must happen from a safe control session.

## What Coordination Does And Does Not Do

What it does:

- records who claimed what scope
- exposes a readable current-work registry
- lets repos block conflicting or unsafe worktree flows
- makes in-flight architectural decisions visible through `KNOWLEDGE.md`

What it does not do:

- real-time presence
- automatic conflict resolution
- automatic discovery of another agent mid-session

Agents only see what has been written to claims, the active-work registry, or
the repo's `KNOWLEDGE.md`. If those surfaces are stale, the agent view is stale.

## Repo Opt-In Contract

A repo truthfully opts into sanctioned worktree coordination when:

- `meta_process.claims.enabled: true`
- `meta_process.worktrees.enabled: true`

Opted-in repos are expected to expose:

- `make worktree BRANCH=... TASK="..." [PLAN=N]`
- `make worktree-list`
- `make worktree-remove BRANCH=...`

If a repo declares the opt-in flags but does not expose the sanctioned
entrypoints and local scripts, that is contract drift and should be fixed.

## Related Docs

- `README.md` for framework overview
- `patterns/worktree-coordination/README.md` for module structure
- `docs/reference/CONFIG_REFERENCE.md` for config key semantics
