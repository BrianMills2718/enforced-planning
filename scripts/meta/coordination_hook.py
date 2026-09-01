#!/usr/bin/env python3
"""Run the native Codex mailbox hook from an installed governed repo."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "coordination_hook.py"
if not SOURCE.is_file():
    raise RuntimeError(f"Installed coordination hook entrypoint is missing: {SOURCE}")
if str(SOURCE.parent) not in sys.path:
    sys.path.insert(0, str(SOURCE.parent))
runpy.run_path(str(SOURCE), run_name="__main__")
