"""Tests for the commit-msg hook's YAML-driven prefix validation."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PROJECT_META_ROOT / "hooks" / "git" / "commit-msg"


def _run_hook(
    commit_msg: str,
    tmp_path: Path,
    *,
    yaml_content: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the commit-msg hook with a temporary commit message file.

    Sets up a fake repo root with meta-process.yaml so the hook can
    find its config. If yaml_content is None, uses the real config.
    """
    # Create a fake repo root with .git marker
    fake_root = tmp_path / "repo"
    fake_root.mkdir(parents=True, exist_ok=True)
    (fake_root / ".git").mkdir(exist_ok=True)

    # Write meta-process.yaml (or skip for missing-yaml tests)
    if yaml_content is not None:
        (fake_root / "meta-process.yaml").write_text(yaml_content, encoding="utf-8")

    # Write commit message file
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(commit_msg, encoding="utf-8")

    # Copy the hook script into the fake repo's hooks/ dir so
    # find_repo_root() walks up to the fake .git
    hooks_dir = fake_root / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_copy = hooks_dir / "commit-msg"
    hook_copy.write_text(HOOK_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")

    return subprocess.run(
        [sys.executable, str(hook_copy), str(msg_file)],
        cwd=str(fake_root),
        check=False,
        text=True,
        capture_output=True,
    )


STANDARD_YAML = textwrap.dedent("""\
    meta_process:
      version: "1.0"
      commits:
        require_prefix: true
        valid_prefixes:
          - "\\\\[Plan #\\\\d+\\\\]"
          - "\\\\[Goal [a-z0-9][a-z0-9._:-]*\\\\]"
          - "\\\\[Trivial\\\\]"
          - "\\\\[Unplanned\\\\]"
""")


def test_accepts_plan_prefix(tmp_path: Path) -> None:
    """Valid [Plan #N] prefix should be accepted."""
    result = _run_hook("[Plan #7] Add feature X", tmp_path, yaml_content=STANDARD_YAML)
    assert result.returncode == 0


def test_accepts_goal_prefix(tmp_path: Path) -> None:
    """A durable autonomous goal is planned provenance, not unplanned work."""
    result = _run_hook(
        "[Goal coordination-runtime-consumer-sync] Reconcile coordination consumers",
        tmp_path,
        yaml_content=STANDARD_YAML,
    )
    assert result.returncode == 0


def test_rejects_goal_prefix_without_stable_reference(tmp_path: Path) -> None:
    """A bare goal label must not manufacture planned provenance."""
    result = _run_hook("[Goal] Reconcile coordination consumers", tmp_path, yaml_content=STANDARD_YAML)
    assert result.returncode == 1


def test_accepts_trivial_prefix(tmp_path: Path) -> None:
    """Valid [Trivial] prefix should be accepted."""
    result = _run_hook("[Trivial] Fix typo", tmp_path, yaml_content=STANDARD_YAML)
    assert result.returncode == 0


def test_accepts_unplanned_prefix(tmp_path: Path) -> None:
    """Valid [Unplanned] prefix should be accepted."""
    result = _run_hook("[Unplanned] Emergency fix", tmp_path, yaml_content=STANDARD_YAML)
    assert result.returncode == 0


def test_accepts_merge_commit(tmp_path: Path) -> None:
    """Merge commits are always accepted regardless of prefix config."""
    result = _run_hook("Merge branch 'feature' into main", tmp_path, yaml_content=STANDARD_YAML)
    assert result.returncode == 0


def test_accepts_fixup_commit(tmp_path: Path) -> None:
    """Fixup commits are always accepted."""
    result = _run_hook("fixup! [Plan #1] Original commit", tmp_path, yaml_content=STANDARD_YAML)
    assert result.returncode == 0


def test_accepts_squash_commit(tmp_path: Path) -> None:
    """Squash commits are always accepted."""
    result = _run_hook("squash! [Plan #1] Original commit", tmp_path, yaml_content=STANDARD_YAML)
    assert result.returncode == 0


def test_rejects_bad_prefix(tmp_path: Path) -> None:
    """Commit messages without a valid prefix should be rejected."""
    result = _run_hook("just a random commit message", tmp_path, yaml_content=STANDARD_YAML)
    assert result.returncode == 1
    assert "valid prefix" in result.stderr.lower()


def test_rejects_when_yaml_missing(tmp_path: Path) -> None:
    """Hook should fail loud when meta-process.yaml is missing."""
    result = _run_hook("[Plan #1] Test commit", tmp_path, yaml_content=None)
    assert result.returncode == 1
    assert "not found" in result.stderr.lower()


def test_accepts_all_when_require_prefix_false(tmp_path: Path) -> None:
    """When require_prefix is false, any message should be accepted."""
    yaml_content = textwrap.dedent("""\
        meta_process:
          version: "1.0"
          commits:
            require_prefix: false
            valid_prefixes:
              - "\\\\[Plan #\\\\d+\\\\]"
    """)
    result = _run_hook("whatever I want", tmp_path, yaml_content=yaml_content)
    assert result.returncode == 0


def test_rejects_when_no_prefixes_defined(tmp_path: Path) -> None:
    """Hook should reject when valid_prefixes list is empty."""
    yaml_content = textwrap.dedent("""\
        meta_process:
          version: "1.0"
          commits:
            require_prefix: true
            valid_prefixes: []
    """)
    result = _run_hook("[Plan #1] Test", tmp_path, yaml_content=yaml_content)
    assert result.returncode == 1


def test_rejects_invalid_yaml_structure(tmp_path: Path) -> None:
    """Hook should fail loud when YAML is missing meta_process key."""
    yaml_content = "some_other_key: true\n"
    result = _run_hook("[Plan #1] Test", tmp_path, yaml_content=yaml_content)
    assert result.returncode == 1
    assert "meta_process" in result.stderr.lower()
