#!/usr/bin/env python3
"""CLI entrypoint for enforced_planning.hook_log."""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import enforced_planning.hook_log as UPSTREAM_MODULE


REPO_ROOT = UPSTREAM_MODULE.REPO_ROOT
DEFAULT_CONFIG = UPSTREAM_MODULE.DEFAULT_CONFIG
DEFAULT_LOG_FILE = UPSTREAM_MODULE.DEFAULT_LOG_FILE
_build_gate_entry = UPSTREAM_MODULE._build_gate_entry
_build_read_entry = UPSTREAM_MODULE._build_read_entry
_write_entry = UPSTREAM_MODULE._write_entry
main = UPSTREAM_MODULE.main


if __name__ == "__main__":
    raise SystemExit(main())
