"""Tests for nested subtree instruction auditing and subdirectory AGENTS.md cleanup."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_subtree_instructions.py"


def _write_registry(repo_root: Path, content: str) -> Path:
    """Write a subtree registry file inside the temporary repo root."""

    registry_path = repo_root / "scripts" / "subtree_instruction_registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(content, encoding="utf-8")
    return registry_path


def _run_check(
    repo_root: Path,
    *,
    sync_agents: bool = False,
    cleanup_stale_agents: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the subtree instruction checker for a temporary repo."""

    registry_path = repo_root / "scripts" / "subtree_instruction_registry.yaml"
    command = [
        sys.executable,
        str(CHECK_SCRIPT),
        "--repo-root",
        str(repo_root),
        "--registry",
        str(registry_path),
        "--json",
    ]
    if sync_agents:
        command.append("--sync-agents")
    if cleanup_stale_agents:
        command.append("--cleanup-stale-agents")
    return subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_subtree_audit_reports_unclassified_directories(tmp_path: Path) -> None:
    """Directories within audit depth must be explicitly included or excluded."""

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "CLAUDE.md").write_text("# Docs\n", encoding="utf-8")
    (tmp_path / "src").mkdir()

    _write_registry(
        tmp_path,
        "\n".join(
            [
                "version: 1",
                "classification_depth: 2",
                "included:",
                '  - path: "docs"',
                '    reason: "Docs subtree."',
                "excluded:",
                '  - path: ".git"',
                '    reason: "VCS internals."',
                "",
            ]
        ),
    )

    result = _run_check(tmp_path)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert "src" in payload["unclassified_paths"]
    assert any("Unclassified directory within audit depth: src" == error for error in payload["errors"])


def test_subtree_audit_reports_stale_agents_symlinks_without_cleanup(
    tmp_path: Path,
) -> None:
    """Audit should be read-only by default when stale AGENTS symlinks exist.

    AGENTS.md is a root-level artifact only. Subdirectories should never
    have one. Older versions of the script created these; cleanup must
    require an explicit write flag.
    """

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "CLAUDE.md").write_text("# Docs\n", encoding="utf-8")
    # Simulate a stale symlink left by older versions:
    (docs_dir / "AGENTS.md").symlink_to("CLAUDE.md")

    meta_dir = tmp_path / "scripts" / "meta"
    meta_dir.mkdir(parents=True)
    (meta_dir / "CLAUDE.md").write_text("# Meta Scripts\n", encoding="utf-8")
    # Simulate a stale symlink left by older versions:
    (meta_dir / "AGENTS.md").symlink_to("CLAUDE.md")

    _write_registry(
        tmp_path,
        "\n".join(
            [
                "version: 1",
                "classification_depth: 3",
                "included:",
                '  - path: "docs"',
                '    reason: "Docs subtree."',
                '  - path: "scripts"',
                '    reason: "Scripts router."',
                '  - path: "scripts/meta"',
                '    reason: "Scripts implementation subtree."',
                "excluded:",
                '  - path: ".git"',
                '    reason: "VCS internals."',
                "",
            ]
        ),
    )
    (tmp_path / "scripts" / "CLAUDE.md").write_text("# Scripts\n", encoding="utf-8")

    result = _run_check(tmp_path)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["actions"] == []
    assert any(
        "docs: AGENTS.md should not exist in subdirectories" in error
        for error in payload["errors"]
    )
    assert any(
        "scripts/meta: AGENTS.md should not exist in subdirectories" in error
        for error in payload["errors"]
    )
    assert (docs_dir / "AGENTS.md").is_symlink()
    assert (meta_dir / "AGENTS.md").is_symlink()


def test_subtree_audit_cleans_up_stale_agents_symlinks_with_explicit_flag(
    tmp_path: Path,
) -> None:
    """Explicit cleanup should remove stale AGENTS.md symlinks."""

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "CLAUDE.md").write_text("# Docs\n", encoding="utf-8")
    (docs_dir / "AGENTS.md").symlink_to("CLAUDE.md")

    meta_dir = tmp_path / "scripts" / "meta"
    meta_dir.mkdir(parents=True)
    (meta_dir / "CLAUDE.md").write_text("# Meta Scripts\n", encoding="utf-8")
    (meta_dir / "AGENTS.md").symlink_to("CLAUDE.md")

    _write_registry(
        tmp_path,
        "\n".join(
            [
                "version: 1",
                "classification_depth: 3",
                "included:",
                '  - path: "docs"',
                '    reason: "Docs subtree."',
                '  - path: "scripts"',
                '    reason: "Scripts router."',
                '  - path: "scripts/meta"',
                '    reason: "Scripts implementation subtree."',
                "excluded:",
                '  - path: ".git"',
                '    reason: "VCS internals."',
                "",
            ]
        ),
    )
    (tmp_path / "scripts" / "CLAUDE.md").write_text("# Scripts\n", encoding="utf-8")

    result = _run_check(tmp_path, cleanup_stale_agents=True)

    payload = json.loads(result.stdout)
    assert "removed-stale-symlink:docs/AGENTS.md" in payload["actions"]
    assert "removed-stale-symlink:scripts/meta/AGENTS.md" in payload["actions"]
    assert result.returncode == 0
    assert not (docs_dir / "AGENTS.md").exists()
    assert not (meta_dir / "AGENTS.md").exists()


def test_subtree_audit_does_not_create_agents_symlinks(tmp_path: Path) -> None:
    """Even with --sync-agents, no new AGENTS.md symlinks should be created.

    The --sync-agents flag is deprecated and is now a no-op.
    """

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "CLAUDE.md").write_text("# Docs\n", encoding="utf-8")

    _write_registry(
        tmp_path,
        "\n".join(
            [
                "version: 1",
                "classification_depth: 2",
                "included:",
                '  - path: "docs"',
                '    reason: "Docs subtree."',
                "excluded:",
                '  - path: ".git"',
                '    reason: "VCS internals."',
                "",
            ]
        ),
    )

    result = _run_check(tmp_path, sync_agents=True)

    payload = json.loads(result.stdout)
    # No AGENTS.md should be created in subdirectories
    assert not (docs_dir / "AGENTS.md").exists()
    # No "created:" actions should appear
    assert not any(action.startswith("created:") for action in payload["actions"])


def test_subtree_audit_errors_on_regular_agents_file_in_subdir(tmp_path: Path) -> None:
    """A regular AGENTS.md file in a subdirectory should produce an error."""

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "CLAUDE.md").write_text("# Docs\n", encoding="utf-8")
    (docs_dir / "AGENTS.md").write_text("# Drifted\n", encoding="utf-8")

    _write_registry(
        tmp_path,
        "\n".join(
            [
                "version: 1",
                "classification_depth: 2",
                "included:",
                '  - path: "docs"',
                '    reason: "Docs subtree."',
                "excluded:",
                '  - path: ".git"',
                '    reason: "VCS internals."',
                "",
            ]
        ),
    )

    result = _run_check(tmp_path)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any(
        "AGENTS.md should not exist in subdirectories" in error
        for error in payload["errors"]
    )
