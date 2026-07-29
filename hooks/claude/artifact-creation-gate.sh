#!/bin/bash
# Claude Code PreToolUse/Edit|Write adapter for governed artifact creation.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
PYTHON="python3"
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON="$REPO_ROOT/.venv/bin/python"
fi

RECEIPT_ARGS=()
if [[ -n "${ARTIFACT_CREATION_RECEIPT_PATH:-}" ]]; then
    RECEIPT_ARGS=(--receipt-path "$ARTIFACT_CREATION_RECEIPT_PATH")
fi

exec "$PYTHON" "$REPO_ROOT/scripts/artifact_creation.py" hook --client claude-code "${RECEIPT_ARGS[@]}"
