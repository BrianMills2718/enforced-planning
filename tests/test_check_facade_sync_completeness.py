"""Tests for the facade-sync completeness checker.

Regression target: policy_friction.md cluster ``coordination-claims-wrapper``
(6 friction entries, 2026-07-16 to 2026-08-03) -- process_tracing,
qualitative_coding, and project-meta each crashed with ImportError because a
shipped ``scripts/meta/*.py`` facade imported an ``enforced_planning`` module
that the installer's sync map never copied into the consumer repo. Live audit
on 2026-09-09 found the same class of gap still present and reproducing:
``scripts/meta/session_close.py`` (shipped by four sync profiles) imports
``enforced_planning.concurrent_writers``, which none of those profiles synced.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = FRAMEWORK_ROOT / "scripts" / "check_facade_sync_completeness.py"

sys.path.insert(0, str(FRAMEWORK_ROOT / "scripts"))
import check_facade_sync_completeness as checker  # noqa: E402


def test_checker_currently_passes_for_every_real_profile():
    """The actual install_governed_repo.py sync maps have zero gaps right now."""
    violations = checker.check_all()
    assert violations == {}, (
        "a real sync profile ships a facade that imports an enforced_planning "
        f"module it never syncs: {violations}"
    )


def test_checker_cli_exits_zero_on_the_real_repo():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=FRAMEWORK_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_checker_detects_a_missing_direct_import(tmp_path: Path):
    """A facade importing a module absent from its own profile must be flagged.

    This is the non-vacuity check: stub a profile with a known gap and confirm
    the checker actually goes red, rather than only ever observing it green.
    """
    consumer = tmp_path / "enforced_planning"
    consumer.mkdir()
    facade_dir = tmp_path / "scripts"
    facade_dir.mkdir()
    facade = facade_dir / "fake_facade.py"
    facade.write_text("from enforced_planning import concurrent_writers\n", encoding="utf-8")

    profile = {"scripts/meta/fake_facade.py": "scripts/fake_facade.py"}
    missing = checker.profile_gaps(profile, framework_root=tmp_path)
    assert missing == ["concurrent_writers"]


def test_checker_detects_a_transitive_missing_import(tmp_path: Path):
    """A gap two hops away (facade -> module A -> module B) must also be caught."""
    ep_dir = tmp_path / "enforced_planning"
    ep_dir.mkdir()
    (ep_dir / "module_a.py").write_text(
        "from enforced_planning import module_b\n", encoding="utf-8"
    )
    facade_dir = tmp_path / "scripts"
    facade_dir.mkdir()
    (facade_dir / "fake_facade.py").write_text(
        "from enforced_planning import module_a\n", encoding="utf-8"
    )

    profile = {
        "scripts/meta/fake_facade.py": "scripts/fake_facade.py",
        "enforced_planning/module_a.py": "enforced_planning/module_a.py",
        # module_b is never synced -- this is the gap under test
    }
    missing = checker.profile_gaps(profile, framework_root=tmp_path)
    assert missing == ["module_b"]


def test_checker_passes_when_the_transitive_closure_is_fully_synced(tmp_path: Path):
    ep_dir = tmp_path / "enforced_planning"
    ep_dir.mkdir()
    (ep_dir / "module_a.py").write_text(
        "from enforced_planning import module_b\n", encoding="utf-8"
    )
    (ep_dir / "module_b.py").write_text("VALUE = 1\n", encoding="utf-8")
    facade_dir = tmp_path / "scripts"
    facade_dir.mkdir()
    (facade_dir / "fake_facade.py").write_text(
        "from enforced_planning import module_a\n", encoding="utf-8"
    )

    profile = {
        "scripts/meta/fake_facade.py": "scripts/fake_facade.py",
        "enforced_planning/module_a.py": "enforced_planning/module_a.py",
        "enforced_planning/module_b.py": "enforced_planning/module_b.py",
    }
    missing = checker.profile_gaps(profile, framework_root=tmp_path)
    assert missing == []
