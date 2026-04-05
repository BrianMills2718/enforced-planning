#!/usr/bin/env python3
"""CLI wrapper for the importable notebook-registry validation module."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.notebook_registry_validation import ALLOWED_EXECUTION_MODES
from enforced_planning.notebook_registry_validation import ALLOWED_JOURNEY_MODES
from enforced_planning.notebook_registry_validation import ALLOWED_PHASE_STATUS
from enforced_planning.notebook_registry_validation import HEADER_LABELS
from enforced_planning.notebook_registry_validation import NotebookRegistryValidationResult
from enforced_planning.notebook_registry_validation import PHASE_LABELS
from enforced_planning.notebook_registry_validation import _to_list
from enforced_planning.notebook_registry_validation import load_notebook
from enforced_planning.notebook_registry_validation import load_notebook_registry
from enforced_planning.notebook_registry_validation import load_yaml
from enforced_planning.notebook_registry_validation import main as _main
from enforced_planning.notebook_registry_validation import print_human_readable
from enforced_planning.notebook_registry_validation import resolve_workspace_path as _resolve_workspace_path
from enforced_planning.notebook_registry_validation import validate_notebook_registry as _validate_notebook_registry
from enforced_planning.worktree_paths import detect_workspace_root


def _detect_workspace_root(repo_root: Path) -> Path:
    """Compatibility wrapper for existing tests and callers."""
    return detect_workspace_root(repo_root)


WORKSPACE_ROOT = _detect_workspace_root(REPO_ROOT)
DEFAULT_REGISTRY = REPO_ROOT / "notebooks" / "notebook_registry.yaml"


def resolve_workspace_path(raw_path: str) -> Path:
    """Resolve a registry path relative to this repo's workspace root."""
    return _resolve_workspace_path(raw_path, workspace_root=WORKSPACE_ROOT)


def validate_notebook_registry(
    registry: dict[str, Any],
    *,
    registry_path: Path,
    journey_id: str | None = None,
) -> NotebookRegistryValidationResult:
    """Validate one registry using the local repo's workspace-root defaults."""
    return _validate_notebook_registry(
        registry,
        registry_path=registry_path,
        journey_id=journey_id,
        workspace_root=WORKSPACE_ROOT,
    )


def main() -> int:
    """Run notebook registry validation using this repo's local defaults."""
    return _main(repo_root=REPO_ROOT, workspace_root=WORKSPACE_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
