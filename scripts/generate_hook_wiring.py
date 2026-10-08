#!/usr/bin/env python3
"""CLI wrapper for the importable hook-wiring module."""

from __future__ import annotations

import sys
from pathlib import Path


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

from enforced_planning.hook_wiring import *  # noqa: E402, F403
from enforced_planning.hook_wiring import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
