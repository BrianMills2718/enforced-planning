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
- Canonical installed claim CLI for governed repos:
  `scripts/meta/check_coordination_claims.py`

The older repo-local `.claude/active-work.yaml` plus legacy
`scripts/meta/worktree-coordination/check_claims.py` surface may still be
present in some repos for compatibility. They are not the canonical
cross-project coordination authority.

## Canonical Terms

- **claim**: the canonical low-level ownership record. Claims say who is
  claiming which project/scope/write paths, on which branch/worktree, for what
  intent.
- **lane**: a bounded execution slice derived from one or more live claims.
  In practice a lane is the operator-facing unit of work: one project, one
  branch/worktree, one plan or bounded sprint, one mission.
- **worktree**: the git checkout where a lane executes.
- **plan**: the pre-made execution contract that tells the lane what success,
  failure, and next actions mean.

Important rule: **claims are canonical, lanes are derived**. Do not invent a
second mutable lane registry by hand. Update claims; regenerate readable lane
surfaces from them.

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

## Lane Lifecycle

1. Define the bounded mission in a numbered plan or one temporary sprint/plan
   document.
2. Create the worktree/branch for that lane.
3. Create a live claim with real ownership metadata:
   - `project`
   - `scope`
   - `intent`
   - `plan_ref`
   - `branch`
   - `worktree_path`
   - `session_id`
   - narrow `write_paths` for write claims
4. Execute, commit verified slices, and keep docs/trackers truthful.
5. Merge/push from the safe root-anchored control session.
6. Release the claim when the lane is done.

For the sanctioned repo-local `make worktree` flow, the default claim is a v2
**program** claim with real `branch`, `worktree_path`, and `session_id`
metadata. That keeps lane tracking healthy without inventing a fake broad
write-path claim for the whole repo.

If any of `branch`, `worktree_path`, `session_id`, or required write ownership
is missing for a live write/program/research claim, the claim is weak and the
registry should treat the lane as attention-worthy rather than healthy.

Stale is a different class of problem. A live claim is **stale** when the lane
state is no longer truthful even though the claim still says `active`. The
canonical stale diagnostics are:

- `missing_worktree_on_disk`
- `missing_branch_ref`
- `branch_merged_to_default`
- `stale_session_heartbeat`

Stale outranks weak. A stale claim should be cleaned up, not merely tolerated.

Liveness is heartbeat-backed:

- `session_id` identifies which runtime session owns the lane
- `heartbeat_at` says when that session last refreshed its lease
- missing `heartbeat_at` on an older live claim is compatibility debt, not
  automatically stale
- once a claim has a heartbeat, an overly old heartbeat becomes
  `stale_session_heartbeat`

The canonical v2 claim CLI now auto-resolves `session_id` from supported tool
runtime env vars when possible. In governed repos the installed local entrypoint
is `scripts/meta/check_coordination_claims.py`. In the framework repo the
equivalent source entrypoint is `scripts/check_coordination_claims.py`. If older
live claims are missing `session_id`, repair them explicitly with:

```bash
python scripts/meta/check_coordination_claims.py --hydrate-session-ids --agent codex --project your-repo
```

Use narrower filters such as `--scope` or `--branch` when you only want to
repair one bounded lane.

To clean up claims that are mechanically provable stale, use:

```bash
python scripts/meta/check_coordination_claims.py --prune-stale --json
```

That command is intentionally separate from `--prune`, which only removes
expired claims. Use `--prune-stale` when worktree/branch lifecycle drift has
left a live claim no longer truthful.

To refresh the heartbeat for the current live session, use:

```bash
python scripts/meta/check_coordination_claims.py --heartbeat --agent codex --project your-repo
```

For Claude Code, the same command shape applies with `--agent claude-code`.
Session identity is auto-resolved from the supported runtime env vars when
available.

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
- exposes a readable current-work registry, including derived active lanes
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

Maintenance commands:

- `python scripts/audit_governed_repo.py --repo-root <repo> --json`
- `python scripts/scan_coordination_mirrors.py --workspace-root ~/projects --fail-on-copied`

## Related Docs

- `README.md` for framework overview
- `patterns/worktree-coordination/README.md` for module structure
- `docs/reference/CONFIG_REFERENCE.md` for config key semantics
