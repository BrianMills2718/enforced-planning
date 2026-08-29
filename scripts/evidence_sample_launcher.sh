#!/usr/bin/env bash
# Execute the freshest locally known published evidence-sample gate while
# preserving the Stop payload on stdin.

set -u

REPO=${EVIDENCE_SAMPLE_REPO:-/home/brian/code/active/enforced-planning}
REF=${EVIDENCE_SAMPLE_REF:-origin/main}
PYTHON_BIN=${PYTHON_BIN:-python3}

PAYLOAD=$(cat)
REPEAT_STATUS=0
printf '%s' "$PAYLOAD" | "$PYTHON_BIN" -c '
import json, sys
try:
    payload = json.load(sys.stdin)
except Exception:
    raise SystemExit(2)
raise SystemExit(0 if payload.get("stop_hook_active") is True else 1)
' || REPEAT_STATUS=$?
case "$REPEAT_STATUS" in
  0) exit 0 ;;
  1) ;;
  *) exit 0 ;;
esac

BLOB=$(git -C "$REPO" show "$REF:scripts/evidence_sample_hook.py" 2>/dev/null) || exit 0
[ -n "$BLOB" ] || exit 0

# ``python3 -`` would consume the Stop JSON as source. Process substitution
# gives Python a script path. The launcher owns the repeat guard, so even a
# stale or carelessly refactored published hook can refuse at most once.
printf '%s' "$PAYLOAD" | "$PYTHON_BIN" <(printf '%s\n' "$BLOB") "$@"
