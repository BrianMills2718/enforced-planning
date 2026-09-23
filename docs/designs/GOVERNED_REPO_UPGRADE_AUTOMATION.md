# Design: Governed Repo Upgrade Automation

**Date:** 2026-04-04
**Status:** Accepted

## Purpose

Define the future automation contract for upgrading multiple governed repos from
the `enforced-planning` source repo without relying on ad hoc manual sync work.

## Source of Truth

Upgrade automation should use an explicit registry, not filesystem discovery.

Recommended registry shape:

```yaml
version: 1
repos:
  - repo_id: enforced-planning
    repo_root: ~/projects/enforced-planning
    tier: source
    governed: true
  - repo_id: llm_client
    repo_root: ~/projects/llm_client
    tier: governed
    governed: true
    upgrade_mode: worktree-branch
```

Why explicit registry over discovery:

- avoids guessing which repos are real governed consumers
- allows per-repo rollout state and policy
- gives operators one place to review the fleet

## Upgrade Workflow

The canonical future entrypoint should be one CLI that orchestrates the
existing installer and audit path per repo.

Recommended shape:

```bash
python scripts/upgrade_governed_repos.py --registry governed_repos.yaml --dry-run
python scripts/upgrade_governed_repos.py --registry governed_repos.yaml --repo llm_client --write
```

Each repo upgrade should follow this sequence:

1. load registry entry
2. verify repo is eligible for upgrade
3. create or use a sanctioned worktree/branch lane
4. run `scripts/install_governed_repo.py --write`
5. run `scripts/audit_governed_repo.py --strict-governed`
6. run repo-local follow-up checks if declared
7. emit one per-repo upgrade report

## Dry-Run vs Apply

### Dry-run

Dry-run is required and should:

- never modify files
- report scaffold, install, and sync actions per repo
- classify blockers such as missing authored instructions, partial governed state, or
  local dirt
- produce one machine-readable report

### Apply

Apply should:

- require an explicit target repo or operator-confirmed batch scope
- run only from a clean lane
- create a rollback-safe branch/worktree before modifying files
- stop on first hard failure for the targeted repo

Current implementation guard: `upgrade_governed_repos.py --write` fails closed
until the CLI actually creates the claimed linked worktree, commit/publication
receipt, and sanctioned closeout required above. Operators may use its dry-run
report, then run the selected bounded installer profile inside each target
repository's own claimed worktree. A clean primary checkout is not a substitute
for that lane.

## Rollback Model

Rollback should be branch-based, not file-rewrite-based.

The canonical rollback story is:

- every upgrade runs in a dedicated branch/worktree
- every successful repo upgrade becomes a commit
- rollback means abandoning the branch/worktree or reverting the upgrade commit

Avoid "restore previous file snapshots in place" logic. Git already owns that.

## Safety Boundaries

### Local dirt

- `--dry-run`: allowed, but must report the dirt clearly
- `--write`: blocked

### Partial governed repos

- classify as `partial-governed`
- allow reporting
- do not auto-upgrade them as if they were healthy governed repos

### Legacy rollout modes

- `legacy-compatible` repos may be reported
- automatic write-mode upgrade should not assume safe migration from
  `install.sh --full` / `--pre-commit` without an explicit migration lane

### Missing canonical governance

Missing root instructions remain a hard blocker. Legacy consumers may still
author `CLAUDE.md` and render `AGENTS.md`; migrated consumers author a regular
`AGENTS.md` and do not regenerate it. The installer must preserve the authored
AGENTS content and scaffold nested AGENTS instructions in that mode.

## Minimal First Slice

The first implementation slice should not try to solve fleet orchestration in
full. It should do only this:

1. read explicit registry
2. dry-run one or many repos
3. write-mode one repo at a time
4. produce per-repo reports

Batch write-mode upgrades across many repos should come later.

## Relationship to Existing Tools

- `scripts/install_governed_repo.py`
  - remains the per-repo sync primitive
- `scripts/audit_governed_repo.py`
  - remains the post-upgrade mechanical verifier
- sanctioned worktree creation
  - remains the safety mechanism for write-mode upgrades

Upgrade automation should compose these primitives rather than bypassing them.
