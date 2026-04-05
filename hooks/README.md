# Hooks Reference

Reference surface for hook templates shipped by the `enforced-planning`
framework.

This document is **not** the primary installation guide. Use
[README.md](../README.md) for framework-source overview and
[GETTING_STARTED.md](../GETTING_STARTED.md) for the installed-repo onboarding
path.

## What This Directory Contains

Two hook families ship in the source repo:

1. **Git hooks** under `hooks/git/`
2. **Claude Code hook templates** under `hooks/claude/`

Some templates are part of the canonical minimum governed-repo install. Others
exist only for legacy or optional rollout surfaces.

## Canonical Minimum Hook Surface

The canonical minimum governed-repo installer is:

```bash
python scripts/install_governed_repo.py --repo-root /path/to/repo --write
```

That minimum path installs and wires only the read-gating hook surface:

| Installed Path | Purpose |
|---|---|
| `.claude/hooks/gate-edit.sh` | Block edits until required reading is satisfied |
| `.claude/hooks/track-reads.sh` | Record document reads for gating |
| `.claude/settings.json` | Wires the `Read` and `Edit|Write` hook commands |

This minimum path does **not** currently install the broader raw git-hook stack
or the larger Claude hook template set.

## Legacy And Optional Hook Surfaces

The source repo still contains additional templates for broader rollout modes:

- `install.sh --full`
  - legacy compatibility bootstrap for raw git hooks, extra Claude hooks, and
    optional coordination surfaces
- `install.sh --pre-commit`
  - legacy compatibility bootstrap for pre-commit-based hook distribution
- worktree-coordination hooks under `hooks/claude/worktree-coordination/`
  - optional coordination surfaces, not part of the minimum governed contract

Those modes are still available, but they are not the canonical sync authority.

## Git Hook Templates

The source repo includes these git hook templates:

| Hook | Purpose |
|---|---|
| `pre-commit` | Run staged validation checks before commit |
| `commit-msg` | Enforce commit prefix conventions |
| `post-commit` | Advisory reminder about unpushed commits |

These remain reference/legacy rollout assets until the broader hook-distribution
story is fully converged.

## Claude Hook Templates

### Minimum Canonical Templates

| Hook | Purpose |
|---|---|
| `gate-edit.sh` | Enforce read-gating before edits |
| `track-reads.sh` | Track read events used by the gate |

### Additional Source Templates

These exist in the framework repo but are not part of the minimum canonical
install path:

| Hook | Role |
|---|---|
| `protect-main.sh` | Protect or warn on direct main-branch edits |
| `check-hook-enabled.sh` | Helper for optional hook enablement |
| `check-references-reviewed.sh` | Advisory plan hygiene check |
| `post-edit-quiz.sh` | Legacy/advisory post-edit quiz hook |

### Worktree Coordination Templates

Hooks under `hooks/claude/worktree-coordination/` belong to the optional
multi-agent coordination layer. They should be read alongside:

- [WORKTREE_COORDINATION_OPERATOR_GUIDE.md](../docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md)
- [worktree-coordination/README.md](../patterns/worktree-coordination/README.md)

## Portability Note

Several git hooks use a `find_script()` pattern so they can work from either:

- `scripts/meta/...` in an installed governed repo
- `scripts/...` in the framework source repo

That portability is intentional, but it does not mean every template is part of
the canonical minimum install.

## Debugging

For a repo that already has the canonical minimum hook surface installed:

```bash
python scripts/meta/file_context.py --json CLAUDE.md
python scripts/meta/check_agents_sync.py --repo-root . --check
```

For a repo using legacy raw hook rollout:

```bash
git config core.hooksPath
./hooks/pre-commit
./hooks/commit-msg .git/COMMIT_EDITMSG
```

## Cross-Tool Boundary

Claude Code currently has the strongest native interactive enforcement path.
For cross-tool governance:

- `CLAUDE.md` remains the canonical human-readable governance file
- `scripts/relationships.yaml` remains the canonical machine-readable graph
- `AGENTS.md` remains a generated projection, not a second authority
- deterministic validators remain the portability layer across tools

## See Also

- [README.md](../README.md)
- [GETTING_STARTED.md](../GETTING_STARTED.md)
- [Git Hooks Pattern](../patterns/06_git-hooks.md)
- [CLAUDE.md Authoring](../patterns/02_claude-md-authoring.md)
