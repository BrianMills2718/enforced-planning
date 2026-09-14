#!/usr/bin/env bash
# Inject canonical mailbox messages after Claude read operations without blocking work.

set -u

WORKTREE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
REPO_ROOT=$(git worktree list --porcelain 2>/dev/null | awk '/^worktree / {sub(/^worktree /, ""); print; exit}')
[[ -n "$REPO_ROOT" ]] || REPO_ROOT="$WORKTREE_ROOT"
SCRIPT="$WORKTREE_ROOT/scripts/meta/coordination_hook.py"
[[ -f "$SCRIPT" ]] || exit 0

PROJECT=$(basename "$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null)")
PYTHON="$WORKTREE_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$REPO_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=$(command -v python3 2>/dev/null) || exit 0

ERR_FILE=$(mktemp)
"$PYTHON" "$SCRIPT" --agent claude-code --project "$PROJECT" 2>"$ERR_FILE"
STATUS=$?
if [[ $STATUS -ne 0 ]]; then
    # Never block work, but never go silent either: a hook that cannot start
    # (import error, broken interpreter) delivers no messages at all.
    "$PYTHON" -c 'import json, sys
lines = open(sys.argv[1], errors="replace").read().strip().splitlines()
reason = lines[-1] if lines else "no stderr"
print(json.dumps({"systemMessage": "coordination mailbox hook failed (exit %s): %s; messages were not checked" % (sys.argv[2], reason)}))' "$ERR_FILE" "$STATUS"
else
    cat "$ERR_FILE" >&2
fi
rm -f "$ERR_FILE"
exit 0
