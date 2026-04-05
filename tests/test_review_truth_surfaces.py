"""Tests for the deprecated semantic-review compatibility wrapper."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.review_truth_surfaces import resolve_config_path


def test_resolve_config_path_prefers_explicit_config(tmp_path: Path) -> None:
    explicit = tmp_path / "custom.yaml"
    explicit.write_text("surfaces: {}\n")

    resolved = resolve_config_path(tmp_path, str(explicit))

    assert resolved == explicit.resolve()


def test_resolve_config_path_defaults_to_repo_truth_surface_config(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    config_path = repo_root / "scripts" / "truth_surface_drift.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("surfaces: {}\n")

    resolved = resolve_config_path(repo_root, None)

    assert resolved == config_path.resolve()


def test_wrapper_dry_run_reports_canonical_config(tmp_path: Path, monkeypatch, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_path = repo_root / "scripts" / "truth_surface_drift.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("surfaces: {}\n")

    from scripts import review_truth_surfaces as wrapper_module

    monkeypatch.setattr(
        "sys.argv",
        [
            "review_truth_surfaces.py",
            "--repo",
            str(repo_root),
            "--dry-run",
        ],
    )

    exit_code = wrapper_module.main()
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["config_path"] == str(config_path.resolve())
    assert "DEPRECATED" in captured.err
