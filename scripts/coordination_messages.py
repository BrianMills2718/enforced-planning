#!/usr/bin/env python3
"""Run the package-backed cross-client coordination mailbox CLI."""

from __future__ import annotations

import sys
from pathlib import Path


def _find_repo_root() -> Path:
    """Resolve the nearest ancestor containing the installed support package."""

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            return parent
    raise RuntimeError("Unable to locate repo root containing enforced_planning/")


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.coordination_messages import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
