#!/usr/bin/env bash
# Execute the freshest locally known published evidence-sample gate while
# preserving the Stop payload on stdin.

set -u

REPO=${EVIDENCE_SAMPLE_REPO:-/home/brian/code/active/enforced-planning}
REF=${EVIDENCE_SAMPLE_REF:-origin/main}
PYTHON_BIN=${PYTHON_BIN:-python3}

BLOB=$(git -C "$REPO" show "$REF:scripts/evidence_sample_hook.py" 2>/dev/null) || exit 0
[ -n "$BLOB" ] || exit 0

# A stale ref from before the re-fire repair is more dangerous than no gate:
# it can refuse Stop forever. Fail open unless the published implementation
# visibly carries the mandatory escape guard.
case "$BLOB" in
  *stop_hook_active*) ;;
  *) exit 0 ;;
esac

# ``python3 -`` would consume the Stop JSON as source. Process substitution
# gives Python a script path and leaves stdin untouched for the hook payload.
exec "$PYTHON_BIN" <(printf '%s\n' "$BLOB") "$@"
