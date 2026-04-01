"""Tests for interpreter-qualified pytest invocation in complete-plan flow."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
COMPLETE_PLAN_PATH = PROJECT_META_ROOT / "scripts" / "meta" / "complete_plan.py"
SPEC = importlib.util.spec_from_file_location("complete_plan_module", COMPLETE_PLAN_PATH)
assert SPEC is not None and SPEC.loader is not None
complete_plan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(complete_plan)


def test_run_unit_tests_uses_interpreter_qualified_pytest(monkeypatch, tmp_path: Path) -> None:
    """Unit-test runner should use ``sys.executable -m pytest`` instead of bare ``pytest``."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="================ 1 passed in 0.01s ================\n",
            stderr="",
        )

    monkeypatch.setattr(complete_plan.subprocess, "run", fake_run)

    passed, summary = complete_plan.run_unit_tests(tmp_path, verbose=False)

    assert passed is True
    assert "passed" in summary
    assert commands
    assert commands[0][:3] == [sys.executable, "-m", "pytest"]


def test_run_e2e_tests_uses_interpreter_qualified_pytest(monkeypatch, tmp_path: Path) -> None:
    """Smoke-test runner should use the same interpreter-qualified pytest command."""
    commands: list[list[str]] = []
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n",
        encoding="utf-8",
    )

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="================ 1 passed in 0.01s ================\n",
            stderr="",
        )

    monkeypatch.setattr(complete_plan.subprocess, "run", fake_run)

    passed, summary = complete_plan.run_e2e_tests(tmp_path, verbose=False)

    assert passed is True
    assert "PASSED" in summary
    assert commands
    assert commands[0][:3] == [sys.executable, "-m", "pytest"]
