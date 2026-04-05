#!/usr/bin/env python3
"""CLI wrapper for the importable governed-repo audit module."""

from __future__ import annotations

import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

from enforced_planning.governed_repo_audit import *  # noqa: F403
from enforced_planning.governed_repo_audit import main


if __name__ == "__main__":
    raise SystemExit(main())
