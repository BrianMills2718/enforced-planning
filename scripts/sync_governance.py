#!/usr/bin/env python3
"""Compatibility wrapper for scripts/sync_governance.py."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


TARGET = Path(__file__).resolve().parents[2] / "scripts" / "sync_governance.py"


if __name__ == "__main__":
    if not TARGET.exists():
        print(f"Missing target script: {TARGET}", file=sys.stderr)
        raise SystemExit(2)
    runpy.run_path(str(TARGET), run_name="__main__")
