"""Tests for check_reachability.py — the product-path ratchet.

The sensor already measured `product_share` (the share of lines reachable from a
repo's declared *product* entrypoint) but only ever failed `--check` on
`newly_unreachable`, which counts modules unreachable from *any* declared
entrypoint. Because governed repos declare tests as entrypoints, a module
reachable only from its own test file was "reachable" by definition. These tests
cover the regression branch that closes that gap, and the compatibility branch
that keeps baselines predating the field silent.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
SENSOR = SCRIPTS_DIR / "check_reachability.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("check_reachability_module", SENSOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _project(root: Path, *, product_share_baseline: float | None) -> None:
    """Write a minimal governed project whose product path is exactly 50%."""

    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    # Reachable from the product entrypoint.
    (root / "pkg" / "main.py").write_text(
        "from pkg import live\n\n\ndef main() -> int:\n    return live.run()\n",
        encoding="utf-8",
    )
    (root / "pkg" / "live.py").write_text("def run() -> int:\n    return 0\n", encoding="utf-8")
    # Reachable only from the test entrypoint - the accretion case.
    (root / "pkg" / "orphan.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_orphan.py").write_text(
        "from pkg import orphan\n\n\ndef test_helper() -> None:\n    assert orphan.helper() == 1\n",
        encoding="utf-8",
    )
    (root / "meta-process.yaml").write_text(
        "meta_process:\n"
        "  quality:\n"
        "    reachability:\n"
        "      enabled: true\n"
        "      packages: [pkg, tests]\n"
        "      entrypoints: ['pkg/main.py', 'tests/**/*.py']\n"
        "      product_entrypoints: ['pkg/main.py']\n"
        "      dynamic: []\n"
        "      ignore: []\n"
        "      baseline: reachability_baseline.json\n",
        encoding="utf-8",
    )
    baseline: dict[str, object] = {"unreachable_count": 0, "unreachable": []}
    if product_share_baseline is not None:
        baseline["product_share"] = product_share_baseline
    (root / "reachability_baseline.json").write_text(
        json.dumps(baseline, indent=2) + "\n", encoding="utf-8"
    )


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SENSOR), "--project-root", str(root), "--check"],
        capture_output=True,
        text=True,
    )


def test_check_fails_when_product_share_regresses(tmp_path: Path) -> None:
    """A baseline above the current product share must fail --check."""
    _project(tmp_path, product_share_baseline=0.99)
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "product path fell from" in result.stdout


def test_check_passes_when_product_share_holds(tmp_path: Path) -> None:
    """A baseline at or below the current product share must pass --check."""
    _project(tmp_path, product_share_baseline=0.0)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "product path fell from" not in result.stdout


def test_check_is_silent_for_baselines_without_product_share(tmp_path: Path) -> None:
    """Baselines written before product_share existed must not start failing."""
    _project(tmp_path, product_share_baseline=None)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "product path fell from" not in result.stdout


def test_share_tolerance_absorbs_baseline_rounding() -> None:
    """The tolerance must cover the 4-place rounding the baseline writer uses."""
    module = _load()
    assert module.SHARE_TOLERANCE >= 0.00005  # type: ignore[attr-defined]
    assert module.SHARE_TOLERANCE < 0.01  # type: ignore[attr-defined]
