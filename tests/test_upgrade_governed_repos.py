"""Safety tests for governed-repository fleet upgrades."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "upgrade_governed_repos.py"


def _load():
    spec = importlib.util.spec_from_file_location("upgrade_governed_repos_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_write_mode_fails_before_registry_or_repository_mutation(capsys) -> None:
    """A clean primary checkout must not license direct fleet mutation."""

    module = _load()

    assert module.main(["--write", "--registry", "/definitely/missing.yaml"]) == 2
    captured = capsys.readouterr()
    assert "fleet --write is disabled" in captured.err
    assert "claimed linked worktrees" in captured.err
