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


def test_string_and_lazy_imports_count_as_edges(tmp_path: Path) -> None:
    """importlib names, alias constants, and PEP 562 lazy tables are real imports.

    Strings in a module without ``__getattr__`` are ordinary data, not imports.
    """
    sensor = _load()
    lazy = tmp_path / "lazy.py"
    lazy.write_text(
        "import importlib\n"
        '_LAZY = {"Thing": ".live", "Other": ("pkg.other", "Other")}\n'
        "def __getattr__(name):\n"
        "    return importlib.import_module(_LAZY[name])\n",
        encoding="utf-8",
    )
    alias = tmp_path / "alias.py"
    alias.write_text(
        "import importlib, sys\n"
        '_TARGET = "pkg.moved"\n'
        "sys.modules[__name__] = importlib.import_module(_TARGET)\n",
        encoding="utf-8",
    )
    data = tmp_path / "data.py"
    data.write_text('LABELS = {"a": "pkg.not_a_module"}\n', encoding="utf-8")

    lazy_imports = sensor._imports(lazy, "pkg.lazy", False)  # type: ignore[attr-defined]
    assert "pkg.live" in lazy_imports
    assert "pkg.other" in lazy_imports
    assert "pkg.moved" in sensor._imports(alias, "pkg.alias", False)  # type: ignore[attr-defined]
    assert "pkg.not_a_module" not in sensor._imports(data, "pkg.data", False)  # type: ignore[attr-defined]


def test_git_source_collection_excludes_environment_but_keeps_new_source(tmp_path: Path) -> None:
    """Ignored dependencies cannot become source; a new real orphan still fails."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".venv/\nworktrees/\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("import live\n", encoding="utf-8")
    (tmp_path / "live.py").write_text("VALUE = 1\n", encoding="utf-8")
    for name in (".venv/lib/dependency.py", "worktrees/other/foreign.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("IGNORED = True\n", encoding="utf-8")
    config = {"packages": ["."], "entrypoints": ["**/*.py"], "product_entrypoints": ["main.py"]}
    sensor = _load()
    report = sensor.analyse(tmp_path, config)
    assert set(report.entrypoints) == {"main.py", "live.py"}
    assert report.total_modules == 2
    assert report.unreachable == []
    config["entrypoints"] = ["main.py"]
    (tmp_path / "orphan.py").write_text("UNCONNECTED = True\n", encoding="utf-8")
    report = sensor.analyse(tmp_path, config)
    assert report.unreachable == ["orphan.py"]
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  quality:\n    reachability:\n      enabled: true\n"
        "      packages: ['.']\n      entrypoints: [main.py]\n"
        "      baseline: reachability_baseline.json\n", encoding="utf-8"
    )
    (tmp_path / "reachability_baseline.json").write_text('{"unreachable_count": 0, "unreachable": []}', encoding="utf-8")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "orphan.py" in result.stdout
    assert ".venv" not in result.stdout and "worktrees/" not in result.stdout


def test_git_tracked_source_survives_an_ignore_pattern(tmp_path: Path) -> None:
    """An ignore pattern cannot hide source already in Git's index."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "kept.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "kept.py"], check=True)
    (tmp_path / ".gitignore").write_text("*.py\n", encoding="utf-8")
    (tmp_path / "dependency.py").write_text("IGNORED = True\n", encoding="utf-8")
    report = _load().analyse(tmp_path, {"packages": ["."], "entrypoints": ["kept.py"]})
    assert report.entrypoints == ["kept.py"]
    assert report.total_modules == 1
    assert report.unreachable == []
