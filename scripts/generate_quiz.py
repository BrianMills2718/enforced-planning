#!/usr/bin/env python3
"""CLI entrypoint for enforced_planning.quiz_generation."""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enforced_planning.quiz_generation import *  # noqa: F401,F403
from enforced_planning.quiz_generation import main


if __name__ == "__main__":
    raise SystemExit(main())
