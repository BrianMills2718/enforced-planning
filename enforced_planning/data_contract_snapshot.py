"""Render the portable data-contract snapshot owned by Enforced Planning.

The domain model remains authoritative in :mod:`planning_handoff`. This module
adapts that model to the dependency-free ``contract-snapshot-v1`` transport so
the public framework does not require an Inside Success package at runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from enforced_planning.planning_handoff import RoadmapGoalHandoff

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_PATH = REPOSITORY_ROOT / "contracts" / "data-contracts.snapshot.json"
BOUNDARY_NAME = "enforced-planning.roadmap-goal-handoff"


class SnapshotDriftError(RuntimeError):
    """Raised when a committed contract snapshot differs from its source model."""


def build_contract_snapshot() -> dict[str, Any]:
    """Build the definition-only snapshot for Enforced Planning boundaries."""
    return {
        "schema_version": "contract-snapshot-v1",
        "contracts": [
            {
                "name": BOUNDARY_NAME,
                "version": "1.0.0",
                "producer": "enforced-planning",
                "consumers": ["company-planning"],
                "input_schema": None,
                "output_schema": RoadmapGoalHandoff.model_json_schema(),
                "description": (
                    "Immutable roadmap goal selection exported for bounded design."
                ),
            }
        ],
        "pipelines": [],
    }


def render_contract_snapshot() -> bytes:
    """Return stable UTF-8 JSON bytes with no runtime registry state."""
    payload = build_contract_snapshot()
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_contract_snapshot(path: Path = DEFAULT_SNAPSHOT_PATH) -> None:
    """Write the current deterministic snapshot to ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_contract_snapshot())


def check_contract_snapshot(path: Path = DEFAULT_SNAPSHOT_PATH) -> None:
    """Fail loud when ``path`` is missing or stale relative to the source model."""
    expected = render_contract_snapshot()
    try:
        actual = path.read_bytes()
    except FileNotFoundError as exc:
        raise SnapshotDriftError(f"contract snapshot is missing: {path}") from exc
    if actual != expected:
        raise SnapshotDriftError(
            f"contract snapshot is stale: {path}; refresh it with "
            "python -m enforced_planning.data_contract_snapshot --write"
        )


def main(argv: list[str] | None = None) -> int:
    """Write or check the committed snapshot from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--write", action="store_true", help="Refresh the snapshot")
    action.add_argument("--check", action="store_true", help="Check for model drift (default)")
    parser.add_argument("--path", type=Path, default=DEFAULT_SNAPSHOT_PATH, help="Snapshot path")
    args = parser.parse_args(argv)

    if args.write:
        write_contract_snapshot(args.path)
        print(f"Wrote contract snapshot: {args.path}")
        return 0
    try:
        check_contract_snapshot(args.path)
    except SnapshotDriftError as exc:
        print(str(exc))
        return 1
    print(f"Contract snapshot is current: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
