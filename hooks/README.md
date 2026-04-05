# Hooks Overview

This directory contains hook templates for the enforced-planning framework. There are two types of hooks:

1. **Git Hooks** - Run on git operations (commit, push)
2. **Claude Code Hooks** - Run on Claude Code tool operations (Edit, Write, Bash, Read)

## Quick Reference

### Git Hooks (`git/`)

Installed to `hooks/` in the target project.

| Hook | Trigger | Purpose | Blocking |
|------|---------|---------|----------|
| `pre-commit` | Before commit | Plan index, doc-coupling on staged files, mypy, plan status, branch freshness | Yes (per check) |
| `commit-msg` | After message entered | Validates `[Plan #N]` or `[Trivial]` prefix | Yes |
| `post-commit` | After commit | Reminds about unpushed commits | No (info) |

All git hooks degrade gracefully — checks are skipped when their scripts aren't installed. A minimal install won't block commits.

### Claude Code Hooks (`claude/`)

Installed to `.claude/hooks/` in the target project.

#### Core Hooks (always installed)

| Hook | Trigger | Purpose | Blocking |
|------|---------|---------|----------|
| `protect-main.sh` | Edit/Write | Warn when editing files on main/master branch | No (warning) |
| `check-hook-enabled.sh` | (helper) | Check if a hook is enabled in `meta-process.yaml` | N/A |
| `check-references-reviewed.sh` | Edit/Write | Warn if plan lacks References Reviewed section | No (warning) |

#### Worktree Coordination Hooks (opt-in, `claude/worktree-coordination/`)

Installed only with `install.sh --full`. For teams running multiple AI instances concurrently.

| Hook | Trigger | Purpose | Blocking |
|------|---------|---------|----------|
| `protect-main.sh` | Edit/Write | Block edits in main directory (force worktree use) | Yes |
| `block-cd-worktree.sh` | Bash | Block `cd worktrees/...` commands | Yes |
| `block-worktree-remove.sh` | Bash | Block direct `git worktree` commands | Yes |
| `check-cwd-valid.sh` | Bash | Fail gracefully if CWD was deleted | Yes |
| `warn-worktree-cwd.sh` | Session start | Warn if running from inside a worktree | No (warning) |
| `check-file-scope.sh` | Edit/Write | Block edits outside plan's declared scope | Yes (optional) |
| `enforce-make-merge.sh` | Bash | Block direct `gh pr merge` | Yes |
| `check-inbox.sh` | Edit/Write | Block edits if unread messages exist | Yes (optional) |
| `notify-inbox-startup.sh` | Read/Glob | Warn about unread messages on startup | No (warning) |

Authoritative operator workflow:
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`

Important nuance:
- `block-cd-worktree.sh` and `warn-worktree-cwd.sh` protect persistent-shell
  sessions from deleting the worktree they are still sitting inside
- they do not make worktrees optional
- merge / finish / worktree removal should run from a root-anchored control
  session

## Exit Codes

All hooks use consistent exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success / Allow operation |
| 1 | Block operation (with error message) |
| 2 | Block operation (permission/validation issue) |

## Portability

Git hooks use the `find_script()` pattern to locate scripts at either `scripts/meta/` (installed path) or `scripts/` (development path). This means hooks work both in the framework's source repo and in projects that installed the framework.

```bash
find_script() {
    local name="$1"
    if [[ -f "$REPO_ROOT/scripts/meta/$name" ]]; then
        echo "$REPO_ROOT/scripts/meta/$name"
    elif [[ -f "$REPO_ROOT/scripts/$name" ]]; then
        echo "$REPO_ROOT/scripts/$name"
    fi
}
```

Each check is guarded: if its script isn't found, the check is silently skipped.

## Debugging Hooks

### Enable Debug Output

```bash
# Set DEBUG=1 to see detailed hook output
DEBUG=1 git commit -m "[Trivial] Test"

# For Claude Code hooks
DEBUG=1 claude
```

### Test Hooks Manually

```bash
# Git hooks
./hooks/pre-commit
./hooks/commit-msg .git/COMMIT_EDITMSG

# Claude Code hooks (simulate tool call)
./.claude/hooks/protect-main.sh /path/to/file.py
```

### Check Hook Configuration

```bash
# See which hooks are enabled
cat meta-process.yaml | grep -A 20 "hooks:"

# Check if specific hook is enabled
source .claude/hooks/check-hook-enabled.sh
is_hook_enabled "check_file_scope" && echo "enabled"
```

## Enabling/Disabling Hooks

### Git Hooks

Git hooks are controlled by the `core.hooksPath` config:

```bash
# Enable (point to hooks directory)
git config core.hooksPath hooks

# Disable (use default, which has no hooks)
git config --unset core.hooksPath

# Bypass for single commit
git commit --no-verify -m "..."
```

### Claude Code Hooks

Claude Code hooks are configured in `.claude/settings.json`. Remove hook entries to disable specific hooks, or remove the `.claude/hooks/` directory to disable all.

Optional hooks can also be controlled via `meta-process.yaml`:

```yaml
hooks:
  check_file_scope: false      # Requires plan with Files Affected
  check_inbox: false           # Requires inter-CC messaging enabled
  check_references_reviewed: true
```

## Cross-Tool Governance Boundary

Claude Code hooks are currently the strongest interactive enforcement path in
this stack because they can block edits and return advisory context.

For cross-tool parity:

- `CLAUDE.md` should remain the canonical human-readable governance file.
- `scripts/relationships.yaml` should remain the canonical machine-readable
  coupling and required-reading graph.
- `AGENTS.md` should be treated as a generated Codex-oriented projection, not a
  separate authority.
- skills and custom subagents should be treated as optional accelerators, not
  governance authorities.
- Raw interactive Codex currently needs generated instructions plus
  deterministic validators or orchestration support; it does not share the same
  native hook surface described above.

When stronger guarantees are needed across both tools, prefer deterministic
validators and OpenClaw mediation over skill-only prompting.

## Git Hook Details

### pre-commit

Runs up to 5 checks, each skipped if its script isn't installed:

1. **Plan index regeneration** - Rebuilds `docs/plans/CLAUDE.md` when plan files change
2. **Doc-coupling check** - Validates doc-code relationships (requires `check_doc_coupling.py`)
3. **Mypy** - Type checks changed `src/` files (requires `mypy` installed)
4. **Plan status consistency** - Validates plan status format (requires `sync_plan_status.py`)
5. **Branch divergence check** - Warns/blocks if branch has diverged from remote

### commit-msg

Validates that commit messages start with `[Plan #N]` or `[Trivial]`. Also allows merge commits and fixup/squash commits.

### post-commit

Informational only. Shows count of unpushed commits and suggests `git push`.

## Installation

### For New Projects

```bash
./install.sh /path/to/project --minimal
```

This copies hooks and configures git to use the `hooks/` directory.

### Manual Setup

```bash
# Git hooks
git config core.hooksPath hooks

# Claude Code hooks (add to .claude/settings.json)
mkdir -p .claude/hooks
# Copy desired hooks from enforced-planning/hooks/claude/
```

## Troubleshooting

### "Commit message must start with [Plan #N] or [Trivial]"

Fix your commit message:
```bash
git commit -m "[Plan #1] Your description"
# or
git commit -m "[Trivial] Fix typo"
```

### Hooks not running at all

Check git config:
```bash
git config core.hooksPath
# Should output: hooks
```

If empty or wrong:
```bash
git config core.hooksPath hooks
```

### Hook blocks legitimate operation

For emergencies, bypass with:
```bash
# Git hooks
git commit --no-verify -m "..."
```

## See Also

- [Git Hooks Pattern](../patterns/06_git-hooks.md)
- [Plan Workflow](../patterns/15_plan-workflow.md)
- [Question-Driven Planning](../patterns/28_question-driven-planning.md)
- [Worktree Coordination Module](../patterns/worktree-coordination/README.md) (opt-in)
- [CLAUDE.md Authoring](../patterns/02_claude-md-authoring.md)
