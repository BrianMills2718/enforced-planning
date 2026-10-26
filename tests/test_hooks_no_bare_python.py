"""Claude hooks must not run a bare ``python``.

Observed 2026-10-26 in the Paperclip hive worker container, which has only
``python3``: ``gate-edit.sh`` exited 127 ("python: command not found") instead
of blocking, so llm_client's hook tests failed there. Hooks run
``"${HOOK_PYTHON:-python3}"`` instead. The next run showed the container's
``python3`` lacks pydantic, which the hook scripts import, so each hook first
defaults ``HOOK_PYTHON`` to the repo's ``.venv/bin/python`` when it exists.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK_DIRS = [ROOT / "hooks" / "claude", ROOT / ".claude" / "hooks"]
BARE_PYTHON = re.compile(r'(^|[ (=\t])python(?= ")')


def test_claude_hooks_do_not_call_bare_python() -> None:
    offenders = []
    for hook_dir in HOOK_DIRS:
        for path in sorted(hook_dir.rglob("*.sh")):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.lstrip()
                if stripped.startswith("#") or stripped.startswith(("echo", "debug ")):
                    continue
                if BARE_PYTHON.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {stripped}")
    assert not offenders, "\n".join(offenders)


def test_hooks_using_python_default_to_repo_venv() -> None:
    missing = []
    for hook_dir in HOOK_DIRS:
        for path in sorted(hook_dir.rglob("*.sh")):
            text = path.read_text()
            if "${HOOK_PYTHON:-python3}" in text and "/.venv/bin/python" not in text:
                missing.append(str(path.relative_to(ROOT)))
    assert not missing, missing
