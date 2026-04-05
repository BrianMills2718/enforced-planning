#!/usr/bin/env python3
"""CLI entrypoint for enforced_planning.dead_code."""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import enforced_planning.dead_code as UPSTREAM_MODULE


Finding = UPSTREAM_MODULE.Finding
Result = UPSTREAM_MODULE.Result
_load_config = UPSTREAM_MODULE._load_config
_parse_vulture_line = UPSTREAM_MODULE._parse_vulture_line
check_dead_code = UPSTREAM_MODULE.check_dead_code
main = UPSTREAM_MODULE.main


if __name__ == "__main__":
    main()
