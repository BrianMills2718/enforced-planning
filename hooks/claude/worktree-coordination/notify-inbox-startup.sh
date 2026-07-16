#!/usr/bin/env bash
# Compatibility redirect: startup notification reads only the canonical JSON mailbox.

set -u
WORKTREE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
REPO_ROOT=$(git worktree list --porcelain 2>/dev/null | awk '/^worktree / {sub(/^worktree /, ""); print; exit}')
[[ -n "$REPO_ROOT" ]] || REPO_ROOT="$WORKTREE_ROOT"
SCRIPT="$WORKTREE_ROOT/scripts/meta/coordination_inbox.py"
[[ -f "$SCRIPT" ]] || exit 0
PROJECT=$(basename "$REPO_ROOT")
PYTHON="$WORKTREE_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$REPO_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=$(command -v python3 2>/dev/null) || exit 0
"$PYTHON" "$SCRIPT" --agent claude-code --project "$PROJECT" 2>&1 || true
exit 0
