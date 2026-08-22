"""Regression tests for provider-package versus consumer-repository roots."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from enforced_planning.file_context import load_relationships

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI = REPO_ROOT / "scripts" / "file_context.py"


def _write_consumer(root: Path, sentinel: str) -> None:
    config = root / "scripts" / "relationships.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "\n".join(
            [
                "governance: []",
                "couplings:",
                "  - sources: [src/example.py]",
                f"    docs: [{sentinel}]",
                "architecture: []",
                "adrs: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _run_cli(consumer_root: Path) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "src/example.py",
            "--repo-root",
            str(consumer_root),
            "--config",
            "scripts/relationships.yaml",
            "--json",
        ],
        cwd=consumer_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_cli_uses_consumer_graph_and_survives_checkout_move(tmp_path: Path) -> None:
    """The provider package must not capture its own relationship graph."""

    original = tmp_path / "consumer-original"
    moved = tmp_path / "renamed-consumer"
    sentinel = "docs/consumer-only-sentinel.md"
    _write_consumer(original, sentinel)

    before = _run_cli(original)
    shutil.move(original, moved)
    after = _run_cli(moved)

    assert before == after
    assert before["files"][0]["coupled_docs"] == [sentinel]


def test_api_resolves_relative_config_from_explicit_consumer_root(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "consumer"
    sentinel = "docs/api-consumer-sentinel.md"
    _write_consumer(consumer, sentinel)

    relationships = load_relationships(
        repo_root=consumer,
        config_path="scripts/relationships.yaml",
    )

    assert relationships["couplings"][0]["docs"] == [sentinel]


def test_explicit_missing_config_fails_instead_of_using_provider_fallback(
    tmp_path: Path,
) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()

    with pytest.raises(FileNotFoundError, match="requested relationships config"):
        load_relationships(
            repo_root=consumer,
            config_path="scripts/missing-relationships.yaml",
        )
