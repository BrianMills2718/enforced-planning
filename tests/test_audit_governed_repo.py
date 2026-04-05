"""Tests for governed-repo audit and deterministic AGENTS refresh."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = PROJECT_META_ROOT / "scripts" / "audit_governed_repo.py"


def _write_canonical_governance(repo_root: Path) -> None:
    """Create the minimum canonical inputs needed for AGENTS rendering."""
    (repo_root / "scripts").mkdir(parents=True, exist_ok=True)
    (repo_root / "CLAUDE.md").write_text(
        "# Sample Repo\n"
        "\n"
        "This repo proves governed-repo rollout tooling.\n"
        "\n"
        "---\n"
        "\n"
        "## Commands\n"
        "\n"
        "```bash\n"
        "pytest -q\n"
        "```\n"
        "\n"
        "## Principles\n"
        "\n"
        "1. Keep one canonical source.\n"
        "2. Fail loud.\n"
        "\n"
        "## Workflow\n"
        "\n"
        "- Validate plans before implementation.\n"
        "\n"
        "## References\n"
        "\n"
        "| Doc | Purpose |\n"
        "|-----|---------|\n"
        "| `docs/ARCH.md` | Architecture |\n",
        encoding="utf-8",
    )
    (repo_root / "scripts" / "relationships.yaml").write_text(
        "governance: []\n",
        encoding="utf-8",
    )


def _write_governed_repo_scaffold(repo_root: Path) -> None:
    """Create a minimal mechanically governed repo for audit tests."""
    _write_canonical_governance(repo_root)
    (repo_root / "meta-process.yaml").write_text(
        "meta_process:\n  version: '1.0'\n",
        encoding="utf-8",
    )
    (repo_root / "docs" / "plans").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs" / "plans" / "CLAUDE.md").write_text(
        "# Plans Index\n",
        encoding="utf-8",
    )
    (repo_root / "scripts" / "meta").mkdir(parents=True, exist_ok=True)
    for relpath in (
        "scripts/meta/file_context.py",
        "scripts/meta/validate_plan.py",
        "scripts/meta/check_doc_coupling.py",
        "scripts/meta/sync_plan_status.py",
        "scripts/check_markdown_links.py",
    ):
        file_path = repo_root / relpath
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text('"""Stub validator."""\n', encoding="utf-8")

    # Read-gating hooks (Level 1 requirement per GOVERNED_REPO_CONTRACT.md §6)
    hooks_dir = repo_root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    for hook_name in ("gate-edit.sh", "track-reads.sh"):
        (hooks_dir / hook_name).write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    settings = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "bash .claude/hooks/track-reads.sh",
                            "timeout": 1000,
                        }
                    ],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "Edit|Write",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "bash .claude/hooks/gate-edit.sh",
                            "timeout": 5000,
                        }
                    ],
                }
            ],
        }
    }
    settings_path = repo_root / ".claude" / "settings.json"
    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )


def _write_capability_ownership_config(
    repo_root: Path,
    *,
    enabled: bool,
    source_of_record: str,
    shared_registry_required: bool = False,
    source_project: str | None = None,
) -> None:
    """Write a minimal meta-process capability-ownership declaration."""
    payload = {
        "meta_process": {
            "version": "1.0",
            "capability_ownership": {
                "enabled": enabled,
                "source_of_record": source_of_record,
                "shared_registry_required": shared_registry_required,
                "source_project": source_project or repo_root.name,
            },
        }
    }
    (repo_root / "meta-process.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _write_shared_capability_registry(
    registry_path: Path,
    *,
    entries: list[dict[str, object]],
) -> None:
    """Write one minimal advisory shared capability registry for tests."""
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        yaml.safe_dump({"version": 1, "entries": entries}, sort_keys=False),
        encoding="utf-8",
    )


def _write_worktree_coordination_config(
    repo_root: Path,
    *,
    claims_enabled: bool = True,
) -> None:
    """Write a minimal meta-process config that expects sanctioned worktree targets."""
    payload = {
        "meta_process": {
            "version": "1.0",
            "claims": {
                "enabled": claims_enabled,
                "require_for_worktree": True,
            },
            "worktrees": {
                "enabled": True,
                "protect_main": True,
                "worktree_dir": "../example_project_worktrees",
                "safe_remove_only": True,
            },
        }
    }
    (repo_root / "meta-process.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def _write_worktree_coordination_surface(repo_root: Path) -> None:
    """Install the minimum local scripts and Makefile targets for worktree coordination."""
    scripts_dir = repo_root / "scripts" / "meta" / "worktree-coordination"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for script_name in ("create_worktree.py", "safe_worktree_remove.py"):
        (scripts_dir / script_name).write_text('"""stub."""\n', encoding="utf-8")
    (repo_root / "scripts" / "meta").mkdir(parents=True, exist_ok=True)
    (repo_root / "scripts" / "meta" / "check_coordination_claims.py").write_text(
        '"""stub."""\n',
        encoding="utf-8",
    )
    for relpath in (
        "scripts/meta/session_start.py",
        "scripts/meta/session_heartbeat.py",
        "scripts/meta/session_status.py",
        "scripts/meta/session_finish.py",
        "scripts/meta/session_close.py",
    ):
        file_path = repo_root / relpath
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text('"""stub."""\n', encoding="utf-8")

    (repo_root / "Makefile").write_text(
        "\n".join(
            [
                "# === META-PROCESS TARGETS ===",
                ".PHONY: worktree worktree-list worktree-remove session-start session-heartbeat session-status session-finish session-close",
                "worktree:",
                "\t@echo create",
                "worktree-list:",
                "\t@echo list",
                "worktree-remove:",
                "\t@echo remove",
                "session-start:",
                "\t@echo start",
                "session-heartbeat:",
                "\t@echo heartbeat",
                "session-status:",
                "\t@echo status",
                "session-finish:",
                "\t@echo finish",
                "session-close:",
                "\t@echo close",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_worktree_repo_from_canonical(
    canonical_repo_root: Path,
    worktree_root: Path,
    *,
    include_local_claude: bool,
) -> None:
    """Materialize a worktree-like repo layout from a canonical scaffold."""
    for relpath in (
        "CLAUDE.md",
        "scripts/relationships.yaml",
        "docs/plans/CLAUDE.md",
        "scripts/meta/file_context.py",
        "scripts/meta/validate_plan.py",
        "scripts/meta/check_doc_coupling.py",
        "scripts/meta/sync_plan_status.py",
        "scripts/check_markdown_links.py",
    ):
        source = canonical_repo_root / relpath
        target = worktree_root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    if include_local_claude:
        shutil.copytree(
            canonical_repo_root / ".claude",
            worktree_root / ".claude",
            dirs_exist_ok=True,
        )


def test_audit_governed_repo_reports_partial_for_missing_contract(tmp_path: Path) -> None:
    """Audit should classify a repo as partial when required signals are missing."""
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["classification"] == "partial"
    assert "canonical CLAUDE.md" in payload["missing_required"]
    assert "meta-process.yaml" in payload["missing_required"]
    assert "scripts/relationships.yaml" in payload["missing_required"]


def test_audit_governed_repo_warns_when_worktree_entrypoints_are_missing(
    tmp_path: Path,
) -> None:
    """Opted-in repos should fail the governed audit when sanctioned targets are absent."""
    _write_governed_repo_scaffold(tmp_path)
    _write_worktree_coordination_config(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    check = payload["checks"]["worktree_entrypoints"]
    assert payload["classification"] == "partial"
    assert check["expected"] is True
    assert check["claims_enabled"] is True
    assert check["targets_present"]["worktree"] is False
    assert check["targets_present"]["worktree-remove"] is False
    assert check["warnings"]
    assert "sanctioned Makefile worktree entrypoints" in payload["missing_required"]


def test_audit_governed_repo_reports_present_worktree_entrypoints(
    tmp_path: Path,
) -> None:
    """Advisory audit should stay quiet when the sanctioned targets are present."""
    _write_governed_repo_scaffold(tmp_path)
    _write_worktree_coordination_config(tmp_path)
    _write_worktree_coordination_surface(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    check = payload["checks"]["worktree_entrypoints"]
    assert check["expected"] is True
    assert check["claims_enabled"] is True
    assert check["warnings"] == []
    assert all(check["targets_present"].values())
    assert all(check["scripts_present"].values())


def test_audit_governed_repo_warns_when_worktrees_enabled_without_claims_enabled(
    tmp_path: Path,
) -> None:
    """Sanctioned worktree opt-in should fail governed classification without claims.enabled."""
    _write_governed_repo_scaffold(tmp_path)
    _write_worktree_coordination_config(tmp_path, claims_enabled=False)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    check = payload["checks"]["worktree_entrypoints"]
    assert payload["classification"] == "partial"
    assert check["expected"] is True
    assert check["claims_enabled"] is False
    assert any("claims.enabled" in warning for warning in check["warnings"])
    assert "meta-process.yaml claims.enabled for worktree opt-in" in payload["missing_required"]


def test_audit_governed_repo_does_not_expect_worktree_opt_in_from_preinstalled_surface(
    tmp_path: Path,
) -> None:
    """Preinstalled worktree scripts/targets should not imply opt-in without config."""
    _write_governed_repo_scaffold(tmp_path)
    _write_worktree_coordination_surface(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    check = payload["checks"]["worktree_entrypoints"]
    assert check["expected"] is False
    assert all(check["scripts_present"].values())
    assert all(check["targets_present"].values())
    assert check["warnings"] == []


def test_audit_governed_repo_uses_repo_local_renderer_for_agents_sync(
    tmp_path: Path,
) -> None:
    """A repo-local renderer should define AGENTS sync truth for that repo."""
    _write_governed_repo_scaffold(tmp_path)
    renderer = tmp_path / "scripts" / "meta" / "render_agents_md.py"
    renderer.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "",
                "class Inputs:",
                "    def __init__(self, output_path):",
                "        self.output_path = output_path",
                "",
                "def resolve_inputs(repo_root, claude_file='CLAUDE.md', relationships_file='scripts/relationships.yaml', output_file='AGENTS.md', template_path=None):",
                "    return Inputs(Path(repo_root) / output_file)",
                "",
                "def render_agents_markdown(inputs):",
                "    return 'LOCAL RENDER\\n'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text("LOCAL RENDER\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["checks"]["agents_md"]["in_sync"] is True


def test_audit_governed_repo_refreshes_agents_and_passes_strict(
    tmp_path: Path,
) -> None:
    """Audit should refresh AGENTS.md and pass strict mode for a complete scaffold."""
    _write_governed_repo_scaffold(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--refresh-agents",
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["classification"] == "governed"
    assert payload["status"] == "PASS"
    assert payload["checks"]["agents_md"]["in_sync"] is True
    assert (tmp_path / "AGENTS.md").exists()
    assert payload["actions"] == ["rendered:AGENTS.md"]


def test_audit_governed_repo_fails_strict_on_agents_drift(tmp_path: Path) -> None:
    """Strict mode should fail loudly when AGENTS.md is present but stale."""
    _write_governed_repo_scaffold(tmp_path)
    (tmp_path / "AGENTS.md").write_text("stale\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["classification"] == "partial"
    assert payload["checks"]["agents_md"]["present"] is True
    assert payload["checks"]["agents_md"]["in_sync"] is False
    assert "in-sync AGENTS.md" in payload["missing_required"]


def test_audit_governed_repo_reports_agents_symlink_error_without_crashing(
    tmp_path: Path,
) -> None:
    """Legacy repos with AGENTS symlinked to CLAUDE should audit as partial, not traceback."""
    _write_governed_repo_scaffold(tmp_path)
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    agents = payload["checks"]["agents_md"]
    assert payload["classification"] == "partial"
    assert agents["present"] is True
    assert agents["in_sync"] is False
    assert "symlink to CLAUDE.md" in agents["error"]


def test_audit_governed_repo_fails_without_read_gating_hooks(
    tmp_path: Path,
) -> None:
    """Audit should classify a repo as partial when read-gating hooks are missing.

    Per GOVERNED_REPO_CONTRACT.md section 6, read-gating hooks are a Level 1
    requirement. A repo with all other signals but no hooks is not governed.
    """
    _write_governed_repo_scaffold(tmp_path)

    # Remove hook files and settings to simulate a repo without read-gating
    import shutil

    shutil.rmtree(tmp_path / ".claude")

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--refresh-agents",
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["classification"] == "partial"
    assert payload["checks"]["read_gating"]["present"] is False
    missing = payload["missing_required"]
    assert any("hook:" in m for m in missing)


def test_audit_governed_repo_strict_linkage_blocks_scaffolded_relationships(
    tmp_path: Path,
) -> None:
    """Strict linkage mode should fail when relationships.yaml is scaffold-only."""
    _write_governed_repo_scaffold(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--strict-linkage",
            "--strict-governed",
            "--refresh-agents",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["checks"]["relationships_yaml"]["linkage"]["status"] == "minimal"
    assert "relationships.yaml has no actionable governance/coupling/architecture entries" in payload[
        "missing_required"
    ]


def test_audit_governed_repo_flags_minimal_relationships_as_warning(tmp_path: Path) -> None:
    """Without strict linkage mode, scaffold-only relationships should still pass with warning metadata."""
    _write_governed_repo_scaffold(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--refresh-agents",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["classification"] == "governed"
    assert payload["checks"]["relationships_yaml"]["linkage"]["status"] == "minimal"
    assert payload["checks"]["relationships_yaml"]["warnings"]


def test_audit_governed_repo_warns_when_registry_covered_repo_has_no_capability_declaration(
    tmp_path: Path,
) -> None:
    """Registry-covered repos should get advisory capability warnings, not lose governed status."""
    repo_root = tmp_path / "Digimon_for_KG_application"
    registry_path = tmp_path / "shared-capability-registry.yaml"
    _write_governed_repo_scaffold(repo_root)
    _write_shared_capability_registry(
        registry_path,
        entries=[
            {
                "capability_id": "digimon.retrieval_projection_runtime",
                "source_project": "Digimon_for_KG_application",
                "source_of_record": "~/projects/Digimon_for_KG_application/docs/ops/CAPABILITY_DECOMPOSITION.md",
            }
        ],
    )

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(repo_root),
            "--shared-capability-registry",
            str(registry_path),
            "--refresh-agents",
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    capability = payload["checks"]["capability_ownership"]
    assert payload["classification"] == "governed"
    assert capability["declared"] is False
    assert capability["shared_registry_matches"]
    assert any("capability registry" in warning for warning in capability["warnings"])


def test_audit_governed_repo_accepts_complete_capability_declaration(
    tmp_path: Path,
) -> None:
    """A complete advisory capability declaration should clear capability warnings."""
    repo_root = tmp_path / "Digimon_for_KG_application"
    registry_path = tmp_path / "shared-capability-registry.yaml"
    _write_governed_repo_scaffold(repo_root)
    source_of_record = "docs/ops/CAPABILITY_DECOMPOSITION.md"
    capability_doc = repo_root / source_of_record
    capability_doc.parent.mkdir(parents=True, exist_ok=True)
    capability_doc.write_text("# Capability Decomposition\n", encoding="utf-8")
    _write_shared_capability_registry(
        registry_path,
        entries=[
            {
                "capability_id": "digimon.retrieval_projection_runtime",
                "source_project": "Digimon_for_KG_application",
                "source_of_record": "~/projects/Digimon_for_KG_application/docs/ops/CAPABILITY_DECOMPOSITION.md",
            }
        ],
    )
    _write_capability_ownership_config(
        repo_root,
        enabled=True,
        source_of_record=source_of_record,
        shared_registry_required=True,
        source_project="Digimon_for_KG_application",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(repo_root),
            "--shared-capability-registry",
            str(registry_path),
            "--refresh-agents",
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    capability = payload["checks"]["capability_ownership"]
    assert payload["classification"] == "governed"
    assert capability["declared"] is True
    assert capability["enabled"] is True
    assert capability["source_exists"] is True
    assert capability["shared_registry_required"] is True
    assert capability["warnings"] == []


def test_audit_governed_repo_warns_when_multi_capability_monorepo_points_to_detail_doc(
    tmp_path: Path,
) -> None:
    """Multi-capability monorepos should keep the local source of record at umbrella level."""
    repo_root = tmp_path / "mcp-servers"
    registry_path = tmp_path / "shared-capability-registry.yaml"
    _write_governed_repo_scaffold(repo_root)
    source_of_record = "docs/ops/SOCIAL_MEDIA_CAPABILITY_DECOMPOSITION.md"
    capability_doc = repo_root / source_of_record
    capability_doc.parent.mkdir(parents=True, exist_ok=True)
    capability_doc.write_text("# Social Media Capability\n", encoding="utf-8")
    _write_shared_capability_registry(
        registry_path,
        entries=[
            {
                "capability_id": "mcp_servers.social_media",
                "source_project": "mcp-servers",
                "source_of_record": "~/projects/mcp-servers/docs/ops/SOCIAL_MEDIA_CAPABILITY_DECOMPOSITION.md",
            },
            {
                "capability_id": "mcp_servers.github",
                "source_project": "mcp-servers",
                "source_of_record": "~/projects/mcp-servers/docs/ops/GITHUB_CAPABILITY_DECOMPOSITION.md",
            },
        ],
    )
    _write_capability_ownership_config(
        repo_root,
        enabled=True,
        source_of_record=source_of_record,
        shared_registry_required=True,
        source_project="mcp-servers",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(repo_root),
            "--shared-capability-registry",
            str(registry_path),
            "--refresh-agents",
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    capability = payload["checks"]["capability_ownership"]
    assert payload["classification"] == "governed"
    assert capability["multi_capability_monorepo"] is True
    assert capability["shared_registry_match_count"] >= 2
    assert any("umbrella ownership memo" in warning for warning in capability["warnings"])


def test_audit_governed_repo_accepts_multi_capability_monorepo_umbrella_source(
    tmp_path: Path,
) -> None:
    """Multi-capability monorepos should pass when the local source points at an umbrella memo."""
    repo_root = tmp_path / "mcp-servers"
    registry_path = tmp_path / "shared-capability-registry.yaml"
    _write_governed_repo_scaffold(repo_root)
    source_of_record = "docs/ops/MCP_SERVERS_CAPABILITY_OWNERSHIP.md"
    capability_doc = repo_root / source_of_record
    capability_doc.parent.mkdir(parents=True, exist_ok=True)
    capability_doc.write_text("# MCP Servers Capability Ownership\n", encoding="utf-8")
    _write_shared_capability_registry(
        registry_path,
        entries=[
            {
                "capability_id": "mcp_servers.social_media",
                "source_project": "mcp-servers",
                "source_of_record": "~/projects/mcp-servers/docs/ops/SOCIAL_MEDIA_CAPABILITY_DECOMPOSITION.md",
            },
            {
                "capability_id": "mcp_servers.github",
                "source_project": "mcp-servers",
                "source_of_record": "~/projects/mcp-servers/docs/ops/GITHUB_CAPABILITY_DECOMPOSITION.md",
            },
        ],
    )
    _write_capability_ownership_config(
        repo_root,
        enabled=True,
        source_of_record=source_of_record,
        shared_registry_required=True,
        source_project="mcp-servers",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(repo_root),
            "--shared-capability-registry",
            str(registry_path),
            "--refresh-agents",
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    capability = payload["checks"]["capability_ownership"]
    assert payload["classification"] == "governed"
    assert capability["multi_capability_monorepo"] is True
    assert capability["shared_registry_match_count"] >= 2
    assert capability["warnings"] == []


def test_audit_governed_repo_uses_canonical_read_gating_for_worktree_checkout(
    tmp_path: Path,
) -> None:
    """Worktree audits should use canonical hook surfaces when the worktree lacks `.claude`."""
    workspace_root = tmp_path / "workspace"
    canonical_repo_root = workspace_root / "Digimon_for_KG_application"
    worktree_root = workspace_root / "Digimon_for_KG_application_worktrees" / "plan-38"
    _write_governed_repo_scaffold(canonical_repo_root)
    _write_worktree_repo_from_canonical(
        canonical_repo_root,
        worktree_root,
        include_local_claude=False,
    )

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(worktree_root),
            "--refresh-agents",
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    read_gating = payload["checks"]["read_gating"]
    assert payload["classification"] == "governed"
    assert read_gating["present"] is True
    assert read_gating["canonical_fallback_used"] is True
    assert read_gating["settings_source_path"] == str(
        (canonical_repo_root / ".claude" / "settings.json").resolve()
    )
    assert read_gating["hook_source_paths"][".claude/hooks/gate-edit.sh"] == str(
        (canonical_repo_root / ".claude" / "hooks" / "gate-edit.sh").resolve()
    )


def test_audit_governed_repo_prefers_local_worktree_settings_when_present(
    tmp_path: Path,
) -> None:
    """A local settings file should remain authoritative even in a worktree."""
    workspace_root = tmp_path / "workspace"
    canonical_repo_root = workspace_root / "Digimon_for_KG_application"
    worktree_root = workspace_root / "Digimon_for_KG_application_worktrees" / "plan-38"
    _write_governed_repo_scaffold(canonical_repo_root)
    _write_worktree_repo_from_canonical(
        canonical_repo_root,
        worktree_root,
        include_local_claude=True,
    )
    settings_path = worktree_root / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["hooks"]["PreToolUse"][0]["hooks"] = []
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(AUDIT_SCRIPT),
            "--repo-root",
            str(worktree_root),
            "--refresh-agents",
            "--strict-governed",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    read_gating = payload["checks"]["read_gating"]
    assert payload["classification"] == "partial"
    assert read_gating["present"] is False
    assert read_gating["canonical_fallback_used"] is False
    assert read_gating["settings_source_path"] == str(settings_path.resolve())
