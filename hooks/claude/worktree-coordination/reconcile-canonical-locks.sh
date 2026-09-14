#!/usr/bin/env bash
# Keep canonical checkouts read-only while a lane claim is live, and print the
# escape hatch when that read-only state blocks something.
#
# Wired to SessionStart (reconcile, which is also the stale-lock repair) and to
# PreToolUse/PostToolUse on Bash|Edit|Write (explain a denial at the moment it
# happens). This hook never blocks: enforcement is the checkout's permission
# bits, so a hook that fails simply says less, it does not open the boundary.
set -u

WORKTREE_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
SCRIPT="$WORKTREE_ROOT/scripts/worktree-coordination/canonical_lock.py"
[[ -f "$SCRIPT" ]] || SCRIPT="$WORKTREE_ROOT/scripts/meta/canonical_lock.py"
[[ -f "$SCRIPT" ]] || exit 0

PYTHON="$WORKTREE_ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=$(command -v python3 2>/dev/null) || exit 0

ERR_FILE=$(mktemp)
"$PYTHON" "$SCRIPT" --hook 2>"$ERR_FILE"
STATUS=$?
if [[ $STATUS -ne 0 ]]; then
    # The script reports its own runtime errors; a non-zero exit means it could
    # not start (import error, broken interpreter). That also skips the
    # SessionStart stale-lock repair, so say so instead of going silent.
    "$PYTHON" -c 'import json, sys
lines = open(sys.argv[1], errors="replace").read().strip().splitlines()
reason = lines[-1] if lines else "no stderr"
print(json.dumps({"systemMessage": "canonical-lock hook could not run (exit %s): %s; stale-lock repair did not happen" % (sys.argv[2], reason)}))' "$ERR_FILE" "$STATUS"
fi
rm -f "$ERR_FILE"
exit 0
