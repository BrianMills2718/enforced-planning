#!/usr/bin/env bash
# Poll the canonical mailbox from a native Codex lifecycle event.
set -u

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
SCRIPT="${REPO_ROOT}/scripts/meta/coordination_hook.py"
if [[ -z "${REPO_ROOT}" || ! -f "${SCRIPT}" ]]; then
  printf '%s\n' '{"systemMessage":"coordination mailbox unavailable: installed Codex hook script is missing"}'
  exit 0
fi

PYTHON="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "${PYTHON}" ]]; then
  printf '%s\n' '{"systemMessage":"coordination mailbox unavailable: python3 is missing"}'
  exit 0
fi

exec "${PYTHON}" "${SCRIPT}"
