#!/usr/bin/env python3
"""CLI wrapper for the importable file-context module."""

from __future__ import annotations

from pathlib import Path
import sys


def _detect_repo_root(script_path: Path) -> Path:
    """Resolve repo root for both canonical and installed script layouts."""
    if script_path.parent.name == "meta" and script_path.parent.parent.name == "scripts":
        return script_path.parents[2]
    if script_path.parent.name == "scripts":
        return script_path.parents[1]
    return script_path.parents[1]


REPO_ROOT = _detect_repo_root(Path(__file__).resolve())
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.file_context import DEFAULT_CONFIG  # noqa: E402
from enforced_planning.file_context import DEFAULT_READS_FILE  # noqa: E402
from enforced_planning.file_context import FileContext  # noqa: E402
from enforced_planning.file_context import ReadCheckResult  # noqa: E402
from enforced_planning.file_context import check_required_reads  # noqa: E402
from enforced_planning.file_context import collect_context  # noqa: E402
from enforced_planning.file_context import load_relationships  # noqa: E402
from enforced_planning.file_context import load_yaml  # noqa: E402
from enforced_planning.file_context import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
