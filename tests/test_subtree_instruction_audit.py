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


def test_agents_only_subtree_is_accepted(tmp_path: Path) -> None:
    """A migrated repo can use AGENTS.md at root and in included subtrees."""
    (tmp_path / "AGENTS.md").write_text("# Root\n", encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "AGENTS.md").write_text("# Docs\n", encoding="utf-8")
    _write_registry(
        tmp_path,
        'version: 1\nclassification_depth: 1\nincluded:\n'
        '  - path: "docs"\n    reason: "Docs subtree."\n'
        'excluded:\n  - path: "scripts"\n    reason: "Fixture registry."\n',
    )

    result = _run_check(tmp_path)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["errors"] == []
    assert (docs_dir / "AGENTS.md").read_text() == "# Docs\n"


def test_agents_only_subtree_requires_agents_and_rejects_claude(tmp_path: Path) -> None:
    """The migrated mode detects missing instructions and old filename residue."""
    (tmp_path / "AGENTS.md").write_text("# Root\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CLAUDE.md").write_text("# Old\n", encoding="utf-8")
    _write_registry(
        tmp_path,
        'version: 1\nclassification_depth: 1\nincluded:\n'
        '  - path: "docs"\n    reason: "Docs subtree."\n'
        'excluded:\n  - path: "scripts"\n    reason: "Fixture registry."\n',
    )

    result = _run_check(tmp_path)

    assert result.returncode == 1
    errors = json.loads(result.stdout)["errors"]
    assert "docs: missing AGENTS.md" in errors
    assert "docs: CLAUDE.md remains in an AGENTS-only repo" in errors


def test_agents_only_cleanup_never_deletes_instruction_file(tmp_path: Path) -> None:
    """A legacy cleanup flag cannot delete a migrated nested AGENTS.md."""
    (tmp_path / "AGENTS.md").write_text("# Root\n", encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "AGENTS.md").write_text("# Docs\n", encoding="utf-8")
    _write_registry(
        tmp_path,
        'version: 1\nclassification_depth: 1\nincluded:\n'
        '  - path: "docs"\n    reason: "Docs subtree."\n'
        'excluded:\n  - path: "scripts"\n    reason: "Fixture registry."\n',
    )

    result = _run_check(tmp_path, cleanup_stale_agents=True)

    assert result.returncode == 1
    assert "--cleanup-stale-agents is unsafe" in result.stdout
    assert (docs_dir / "AGENTS.md").read_text() == "# Docs\n"


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
    assert "removed-subdirectory-agents:docs/AGENTS.md" in payload["actions"]
    assert "removed-subdirectory-agents:scripts/meta/AGENTS.md" in payload["actions"]
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



def _load_checker():
    """Import the checker directly for unit-level cases.

    The cases above drive it as a subprocess, which is right for CLI behaviour
    but cannot reach the sweep and registry-resolution helpers.
    """

    import importlib.util

    name = "_check_subtree_instructions"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, CHECK_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check_subtree_instructions = _load_checker()


def _repo(tmp_path: Path) -> Path:
    """Build a bare Git repository root."""

    (tmp_path / ".git").mkdir(parents=True)
    return tmp_path


def test_sweep_finds_every_subdirectory_agents_file(tmp_path: Path):
    """Cleanup used to run only over registered subtrees.

    That made it useless for the repositories that needed it: agentic_scaffolding
    and prompt_eval carried 31 dead symlinks between them and have no registry at
    all, so all 31 had to be deleted by hand on 2026-08-21.
    """

    repo = _repo(tmp_path)
    for rel in ("docs", "docs/plans", "scripts"):
        (repo / rel).mkdir(parents=True)
        (repo / rel / "CLAUDE.md").write_text(f"rules for {rel}\n", encoding="utf-8")
        (repo / rel / "AGENTS.md").symlink_to("CLAUDE.md")

    redundant, distinct = check_subtree_instructions.sweep_subdirectory_agents(
        repo, remove=False
    )
    assert redundant == ["docs/AGENTS.md", "docs/plans/AGENTS.md", "scripts/AGENTS.md"]
    assert distinct == []
    assert (repo / "scripts" / "AGENTS.md").is_file(), "dry run must not delete"

    check_subtree_instructions.sweep_subdirectory_agents(repo, remove=True)
    assert check_subtree_instructions.sweep_subdirectory_agents(repo, remove=False) == ([], [])


def test_sweep_skips_nested_repositories_and_vendor_trees(tmp_path: Path):
    """A nested repo's root AGENTS.md is its own artifact, and Codex does load it.

    A depth-based sweep over ~/code/active counted 80 dead files; 33 of them were
    the root file of a nested clone or worktree and deleting those would have
    removed live guidance.
    """

    repo = _repo(tmp_path)
    nested = repo / "repos" / "inner"
    (nested / ".git").mkdir(parents=True)
    (nested / "AGENTS.md").write_text("inner root\n", encoding="utf-8")
    (nested / "ui").mkdir()
    (nested / "ui" / "AGENTS.md").write_text("below a nested root\n", encoding="utf-8")
    vendored = repo / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "AGENTS.md").write_text("vendor\n", encoding="utf-8")

    assert check_subtree_instructions.sweep_subdirectory_agents(repo, remove=True) == ([], [])
    assert (nested / "AGENTS.md").is_file()
    assert (nested / "ui" / "AGENTS.md").is_file()
    assert (vendored / "AGENTS.md").is_file()


def test_registry_defaults_to_the_audited_repository(tmp_path: Path):
    """The default pointed at this repository's own path, which does not exist.

    Every caller that omitted --registry failed with a FileNotFoundError naming a
    file in enforced-planning, whatever repository they were auditing.
    """

    repo = _repo(tmp_path)
    (repo / "scripts").mkdir()
    local = repo / "scripts" / "subtree_instruction_registry.yaml"
    local.write_text("version: 1\nincluded: []\nexcluded: []\n", encoding="utf-8")
    assert check_subtree_instructions._resolve_registry(repo, None) == local

    bare = _repo(tmp_path / "bare")
    assert (
        check_subtree_instructions._resolve_registry(bare, None)
        == check_subtree_instructions.DEFAULT_REGISTRY
    )


def test_missing_registry_still_sweeps_and_says_so(tmp_path: Path):
    """A repository with no registry is exactly the one carrying dead mirrors."""

    repo = _repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "CLAUDE.md").write_text("rules\n", encoding="utf-8")
    (repo / "docs" / "AGENTS.md").write_text("rules\n", encoding="utf-8")

    result = check_subtree_instructions.audit_subtree_instructions(
        repo, repo / "no-such-registry.yaml", cleanup_stale_agents=True
    )
    assert "removed-subdirectory-agents:docs/AGENTS.md" in result.actions
    assert not (repo / "docs" / "AGENTS.md").exists()
    assert any("classification skipped" in error for error in result.errors)
    assert not any("Unclassified directory" in error for error in result.errors)
