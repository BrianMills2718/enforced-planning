#!/usr/bin/env python3
"""CLI entrypoint for enforced_planning.friction_log."""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import enforced_planning.friction_log as UPSTREAM_MODULE


REPO_ROOT = UPSTREAM_MODULE.REPO_ROOT
FRICTION_FILE = UPSTREAM_MODULE.FRICTION_FILE
TEMPLATE = UPSTREAM_MODULE.TEMPLATE


def _sync_globals() -> None:
    """Keep the wrapper's mutable file paths aligned with the upstream module."""
    UPSTREAM_MODULE.REPO_ROOT = REPO_ROOT
    UPSTREAM_MODULE.FRICTION_FILE = FRICTION_FILE
    UPSTREAM_MODULE.TEMPLATE = TEMPLATE


def ensure_friction_file() -> Path:
    """Proxy to the package implementation with wrapper-scoped globals."""
    _sync_globals()
    return UPSTREAM_MODULE.ensure_friction_file()


def append_entry(
    friction: str,
    impact: str,
    suggestion: str,
    severity: str = "medium",
    agent: str = "claude-code",
    phase: str = "unknown",
) -> None:
    """Append one structured friction entry through the package implementation."""
    _sync_globals()
    UPSTREAM_MODULE.append_entry(
        friction=friction,
        impact=impact,
        suggestion=suggestion,
        severity=severity,
        agent=agent,
        phase=phase,
    )


def list_entries() -> None:
    """List friction entries through the package implementation."""
    _sync_globals()
    UPSTREAM_MODULE.list_entries()


def summary() -> None:
    """Summarize friction entries through the package implementation."""
    _sync_globals()
    UPSTREAM_MODULE.summary()


def main() -> int:
    """Run the upstream CLI with wrapper-scoped file locations."""
    _sync_globals()
    return UPSTREAM_MODULE.main()


if __name__ == "__main__":
    raise SystemExit(main())
