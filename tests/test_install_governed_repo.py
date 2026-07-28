"""Tests for governed-repo installer/upgrader tooling."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_META_ROOT / "scripts" / "install_governed_repo.py"
INSTALL_SH = PROJECT_META_ROOT / "install.sh"
CANONICAL_FILE_CONTEXT = PROJECT_META_ROOT / "scripts" / "file_context.py"
CANONICAL_FILE_CONTEXT_MODULE = PROJECT_META_ROOT / "enforced_planning" / "file_context.py"
RELATIONSHIP_CONTEXT_ROLLOUT_PATHS = {
    ".claude/hooks/check-hook-enabled.sh",
    ".claude/hooks/gate-edit.sh",
    ".claude/hooks/track-reads.sh",
    ".claude/settings.json",
    "Makefile",
    "enforced_planning/context_packet.py",
    "enforced_planning/docstring_wiki.py",
    "enforced_planning/impact_obligations.py",
    "enforced_planning/relationship_context.py",
    "enforced_planning/test_relationships.py",
    "scripts/check_required_reading.py",
    "scripts/meta/context_packet.py",
    "scripts/meta/docstring_wiki.py",
    "scripts/meta/hook_log.py",
    "scripts/meta/impact_obligations.py",
    "scripts/meta/relationship_context.py",
    "scripts/meta/test_relationships.py",
}

MAILBOX_COMMON_ROLLOUT_PATHS = {
    ".claude/hooks/notify-coordination-messages.sh",
    ".claude/settings.json",
    ".codex/hooks.json",
    ".codex/hooks/notify-coordination-messages.sh",
    "scripts/coordination_hook.py",
    "scripts/coordination_inbox.py",
    "scripts/coordination_messages.py",
    "scripts/meta/coordination_hook.py",
    "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_messages.py",
    "scripts/meta/session_heartbeat.py",
    "scripts/meta/session_close.py",
    "scripts/meta/session_resume.py",
    "scripts/meta/session_start.py",
}

MAILBOX_ROLLOUT_PATHS = MAILBOX_COMMON_ROLLOUT_PATHS | {
    "enforced_planning/coordination_claims.py",
    "enforced_planning/coordination_messages.py",
    "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/prewrite_claim_projection.py",
    "enforced_planning/doc_authority.py",
    "enforced_planning/push_safety.py",
    "enforced_planning/session_contracts.py",
    "enforced_planning/session_lifecycle.py",
    "enforced_planning/worktree_lifecycle.yaml",
    "enforced_planning/worktree_paths.py",
    "scripts/refresh_prewrite_claim_projection.py",
}

CLAIM_PROJECTION_REFRESH_PATHS = {
    "enforced_planning/coordination_claims.py",
    "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/prewrite_claim_projection.py",
    "enforced_planning/worktree_paths.py",
    "scripts/refresh_prewrite_claim_projection.py",
    "scripts/meta/check_coordination_claims.py",
    "scripts/meta/session_close.py",
    "scripts/meta/session_end.py",
    "scripts/meta/session_finish.py",
    "scripts/meta/session_heartbeat.py",
    "scripts/meta/session_resume.py",
    "scripts/meta/session_start.py",
}


def _write_minimal_claude(repo_root: Path) -> None:
    """Write the smallest canonical CLAUDE.md that can generate AGENTS.md."""
    (repo_root / "CLAUDE.md").write_text(
        "\n".join(
            [
                "# Demo Repo",
                "",
                "Demo repo uses `CLAUDE.md` as canonical governance.",
                "",
                "## Commands",
                "",
                "```bash",
                "pytest -q",
                "```",
                "",
                "## Principles",
                "",
                "- Keep governance deterministic.",
                "",
                "## Workflow",
                "",
                "1. Read CLAUDE.md before edits.",
                "",
                "## References",
                "",
                "- `CLAUDE.md` - canonical governance",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_python_without_yaml(repo_root: Path) -> None:
    """Create a target virtualenv entrypoint that fails the PyYAML probe."""

    interpreter = repo_root / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    interpreter.chmod(0o755)


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the governed-repo installer and capture structured output."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _git(cwd: Path, *args: str) -> str:
    """Run one real Git command for installer integration fixtures."""

    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _prepare_relationship_context_target(repo_root: Path) -> None:
    """Create an existing governed repo eligible for the bounded rollout."""

    _write_minimal_claude(repo_root)
    (repo_root / "Makefile").write_text("help:\n\t@echo demo\n", encoding="utf-8")
    relationships = repo_root / "scripts" / "relationships.yaml"
    relationships.parent.mkdir(parents=True, exist_ok=True)
    relationships.write_text("version: 2\nrelationships: []\n", encoding="utf-8")
    file_context = repo_root / "scripts" / "meta" / "file_context.py"
    file_context.parent.mkdir(parents=True, exist_ok=True)
    file_context.write_text(CANONICAL_FILE_CONTEXT.read_text(encoding="utf-8"), encoding="utf-8")
    file_context_module = repo_root / "enforced_planning" / "file_context.py"
    file_context_module.parent.mkdir(parents=True, exist_ok=True)
    file_context_module.write_text(
        CANONICAL_FILE_CONTEXT_MODULE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "baseline",
        ],
        check=True,
    )


def _prepare_mailbox_target(repo_root: Path) -> None:
    """Create a partial local package like a real incrementally governed repo."""

    _write_minimal_claude(repo_root)
    required = (
        "enforced_planning/__init__.py",
    )
    for relative in required:
        source = PROJECT_META_ROOT / relative
        target = repo_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    stale_lifecycle = repo_root / "enforced_planning/session_lifecycle.py"
    stale_lifecycle.write_text('"""Stale lifecycle fixture."""\n', encoding="utf-8")
    (repo_root / "enforced_planning/push_safety.py").write_text(
        '"""Stale push-safety fixture."""\n', encoding="utf-8"
    )
    (repo_root / "enforced_planning/worktree_lifecycle.yaml").write_text(
        "schema_version: 0\n", encoding="utf-8"
    )
    settings = repo_root / ".claude/settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        json.dumps(
            {
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
                    ]
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_coordination_messages_only_rollout_is_bounded_runnable_and_idempotent(
    tmp_path: Path,
) -> None:
    """Mailbox adoption must not refresh unrelated governed-repo surfaces."""

    _prepare_mailbox_target(tmp_path)
    dry_run = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-messages-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    payload = json.loads(dry_run.stdout)
    assert payload["coordination_messages_only_mode"] is True
    action_paths = {action.split(":", 1)[1] for action in payload["actions"]}
    assert action_paths == MAILBOX_ROLLOUT_PATHS
    assert payload["blockers"] == []

    written = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-messages-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert written.returncode == 0, written.stdout + written.stderr
    for relative in MAILBOX_ROLLOUT_PATHS:
        assert (tmp_path / relative).exists()
    for wrapper in ("coordination_hook.py", "coordination_inbox.py", "coordination_messages.py"):
        help_result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts/meta" / wrapper), "--help"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stdout + help_result.stderr
    close_help = subprocess.run(
        [sys.executable, str(tmp_path / "scripts/meta/session_close.py"), "--help"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert close_help.returncode == 0, close_help.stdout + close_help.stderr
    assert "--mailbox-disposition" in close_help.stdout

    repeat = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-messages-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert repeat.returncode == 0
    assert json.loads(repeat.stdout)["actions"] == []


def test_coordination_messages_only_blocks_before_writing_without_session_substrate(
    tmp_path: Path,
) -> None:
    """The bounded profile must fail rather than expand its own ownership."""

    _write_minimal_claude(tmp_path)
    result = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-messages-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert "local enforced_planning package" in payload["blockers"][0]
    assert not (tmp_path / "enforced_planning/coordination_messages.py").exists()


def test_claim_projection_refresh_only_is_bounded_and_idempotent(tmp_path: Path) -> None:
    """Fleet repair must update mutation support without touching hook configuration."""

    _prepare_mailbox_target(tmp_path)
    original_claude_settings = (tmp_path / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    )
    dry_run = _run(
        "--repo-root",
        str(tmp_path),
        "--claim-projection-refresh-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    payload = json.loads(dry_run.stdout)
    assert payload["claim_projection_refresh_only_mode"] is True
    assert {action.split(":", 1)[1] for action in payload["actions"]} == (
        CLAIM_PROJECTION_REFRESH_PATHS
    )
    assert payload["blockers"] == []

    written = _run(
        "--repo-root",
        str(tmp_path),
        "--claim-projection-refresh-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert written.returncode == 0, written.stdout + written.stderr
    assert not (tmp_path / ".codex" / "hooks.json").exists()
    assert (tmp_path / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    ) == original_claude_settings
    for relative in CLAIM_PROJECTION_REFRESH_PATHS:
        assert (tmp_path / relative).is_file()

    # A bounded refresh may intentionally retain an older local lifecycle.
    # The refreshed wrapper must remain runnable rather than requiring a
    # broad lifecycle replacement just to support projection refresh.
    (tmp_path / "enforced_planning" / "session_lifecycle.py").write_text(
        "\n".join(
            [
                '"""Legacy lifecycle fixture."""',
                'MERGED_DISPOSITION = "merged"',
                'WORKTREE_DISPOSITIONS = {"merged"}',
                "def close_session(*, agent, project, scope, worktree_path=None, branch=None, note=None, delete_branch=True, disposition='merged', disposition_reason=None, recovery_ref=None, allow_discard_unique=False):",
                "    return {",
                "        'action': 'closed',",
                "        'worktree_action': 'removed',",
                "        'branch_action': 'deleted',",
                "        'disposition': 'merged',",
                "        'released': True,",
                "    }",
                "",
            ]
        ),
        encoding="utf-8",
    )
    close_help = subprocess.run(
        [sys.executable, str(tmp_path / "scripts/meta/session_close.py"), "--help"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert close_help.returncode == 0, close_help.stdout + close_help.stderr
    close_run = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts/meta/session_close.py"),
            "--agent",
            "codex",
            "--project",
            "demo",
            "--scope",
            "legacy-closeout",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert close_run.returncode == 0, close_run.stdout + close_run.stderr
    assert "closed: worktree=removed branch=deleted" in close_run.stdout

    repeat = _run(
        "--repo-root",
        str(tmp_path),
        "--claim-projection-refresh-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert repeat.returncode == 0, repeat.stdout + repeat.stderr
    assert json.loads(repeat.stdout)["actions"] == []


def test_coordination_messages_only_supports_upstream_bootstrap_consumers(
    tmp_path: Path,
) -> None:
    """Project Meta-style consumers should reuse upstream code, not vendor a second package."""

    _write_minimal_claude(tmp_path)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    helper = scripts_dir / "_upstream_enforced_planning.py"
    helper.write_text(
        "from __future__ import annotations\n"
        "import sys\n"
        "from pathlib import Path\n"
        "def bootstrap_upstream_package(_caller: Path) -> None:\n"
        f"    sys.path.insert(0, {str(PROJECT_META_ROOT)!r})\n",
        encoding="utf-8",
    )
    result = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-messages-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    action_paths = {action.split(":", 1)[1] for action in payload["actions"]}
    assert action_paths == MAILBOX_COMMON_ROLLOUT_PATHS
    assert not (tmp_path / "enforced_planning").exists()
    for wrapper in ("coordination_hook.py", "coordination_inbox.py", "coordination_messages.py"):
        help_result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts/meta" / wrapper), "--help"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stdout + help_result.stderr


def test_relationship_context_only_rollout_is_bounded_and_runnable(tmp_path: Path) -> None:
    """The narrow rollout must install only its declared surface and execute it."""

    _prepare_relationship_context_target(tmp_path)
    agents = tmp_path / "AGENTS.md"
    agents.write_text("unrelated authority\n", encoding="utf-8")
    unrelated = tmp_path / "scripts" / "meta" / "check_dead_code.py"
    unrelated.write_text("unrelated local drift\n", encoding="utf-8")

    dry_run = _run(
        "--repo-root",
        str(tmp_path),
        "--relationship-context-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["relationship_context_only_mode"] is True
    assert dry_payload["scaffolded_files"] == []
    assert "render:AGENTS.md" not in dry_payload["actions"]
    assert not any("check_dead_code" in action for action in dry_payload["actions"])
    assert "append:Makefile.relationship-context" in dry_payload["actions"]
    action_paths = {
        "Makefile" if action.endswith(":Makefile.relationship-context") else action.split(":", 1)[1]
        for action in dry_payload["actions"]
    }
    assert action_paths == RELATIONSHIP_CONTEXT_ROLLOUT_PATHS

    written = _run(
        "--repo-root",
        str(tmp_path),
        "--relationship-context-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert written.returncode == 0, written.stdout + written.stderr
    assert agents.read_text(encoding="utf-8") == "unrelated authority\n"
    assert unrelated.read_text(encoding="utf-8") == "unrelated local drift\n"
    for name in (
        "relationship_context.py",
        "context_packet.py",
        "impact_obligations.py",
        "docstring_wiki.py",
        "test_relationships.py",
    ):
        assert (tmp_path / "scripts" / "meta" / name).exists()
        assert (tmp_path / "enforced_planning" / name).exists()

    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "rollout",
        ],
        check=True,
    )
    commands = (
        ["make", "relationship-context"],
        ["make", "context-packet", "TARGET=CLAUDE.md"],
        ["make", "impact-obligations", "BASE=HEAD"],
        ["make", "docstring-wiki"],
        ["make", "docstring-wiki-check"],
        ["make", "test-relationships"],
    )
    for command in commands:
        result = subprocess.run(
            command,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{command}: {result.stdout}{result.stderr}"

    second = _run(
        "--repo-root",
        str(tmp_path),
        "--relationship-context-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert json.loads(second.stdout)["actions"] == []


def test_relationship_context_only_rejects_unmarked_make_target(tmp_path: Path) -> None:
    """Existing unowned targets must block instead of being duplicated or replaced."""

    _prepare_relationship_context_target(tmp_path)
    makefile = tmp_path / "Makefile"
    original = "context-packet:\n\t@echo local\n"
    makefile.write_text(original, encoding="utf-8")

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--relationship-context-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any("unmarked relationship-context Make targets" in item for item in payload["blockers"])
    assert makefile.read_text(encoding="utf-8") == original


def test_relationship_context_only_rejects_malformed_make_markers(tmp_path: Path) -> None:
    """A partial generated block must block all writes rather than compound corruption."""

    _prepare_relationship_context_target(tmp_path)
    makefile = tmp_path / "Makefile"
    original = "# <<< RELATIONSHIP CONTEXT TARGETS <<<\nhelp:\n\t@echo local\n"
    makefile.write_text(original, encoding="utf-8")

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--relationship-context-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any("malformed relationship-context Makefile markers" in item for item in payload["blockers"])
    assert makefile.read_text(encoding="utf-8") == original
    assert not (tmp_path / "enforced_planning" / "context_packet.py").exists()


def test_installer_rejects_multiple_bounded_scopes(tmp_path: Path) -> None:
    """Worktree-only and relationship-only are distinct, exclusive rollout modes."""

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--worktree-only",
        "--relationship-context-only",
        cwd=PROJECT_META_ROOT,
    )
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr


def test_install_governed_repo_dry_run_reports_expected_actions(tmp_path: Path) -> None:
    """Dry-run mode should report the scaffold and sync actions without writing."""
    _write_minimal_claude(tmp_path)

    result = _run("--repo-root", str(tmp_path), "--json", cwd=PROJECT_META_ROOT)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["write_mode"] is False
    assert "scaffold:meta-process.yaml" in payload["actions"]
    assert "scaffold:scripts/relationships.yaml" in payload["actions"]
    assert "scaffold:docs/plans/CLAUDE.md" in payload["actions"]
    assert "scaffold:Makefile" in payload["actions"]
    assert "install:enforced_planning/__init__.py" in payload["actions"]
    assert "install:enforced_planning/agents_rendering.py" in payload["actions"]
    assert "install:enforced_planning/concern_routing.py" in payload["actions"]
    assert "install:enforced_planning/file_context.py" in payload["actions"]
    assert "install:enforced_planning/relationship_context.py" in payload["actions"]
    assert "install:enforced_planning/context_packet.py" in payload["actions"]
    assert "install:enforced_planning/impact_obligations.py" in payload["actions"]
    assert "install:enforced_planning/verification_batch.py" in payload["actions"]
    assert "install:enforced_planning/docstring_wiki.py" in payload["actions"]
    assert "install:enforced_planning/notebook_registry_validation.py" in payload["actions"]
    assert "install:enforced_planning/plan_validation.py" in payload["actions"]
    assert "install:enforced_planning/push_safety.py" in payload["actions"]
    assert "install:hooks/pre-push" in payload["actions"]
    assert "install:scripts/meta/audit_dead_code.py" in payload["actions"]
    assert "install:scripts/meta/check_dead_code.py" in payload["actions"]
    assert "install:scripts/meta/check_push_safety.py" in payload["actions"]
    assert "install:scripts/meta/check_coordination_claims.py" in payload["actions"]
    assert "install:scripts/meta/session_start.py" in payload["actions"]
    assert "install:scripts/meta/session_heartbeat.py" in payload["actions"]
    assert "install:scripts/meta/session_status.py" in payload["actions"]
    assert "install:scripts/meta/session_finish.py" in payload["actions"]
    assert "install:scripts/meta/session_close.py" in payload["actions"]
    assert "install:scripts/meta/validate_dead_code_audit.py" in payload["actions"]
    assert "install:scripts/meta/worktree-coordination/create_publish_worktree.py" in payload["actions"]
    assert "install:scripts/meta/worktree-coordination/create_review_claim.py" in payload["actions"]
    assert "install:scripts/meta/worktree-coordination/raise_concern.py" in payload["actions"]
    assert "install:scripts/meta/file_context.py" in payload["actions"]
    assert "install:scripts/meta/relationship_context.py" in payload["actions"]
    assert "install:scripts/meta/context_packet.py" in payload["actions"]
    assert "install:scripts/meta/impact_obligations.py" in payload["actions"]
    assert "install:scripts/meta/verification_batch.py" in payload["actions"]
    assert "install:scripts/meta/docstring_wiki.py" in payload["actions"]
    assert "install:scripts/meta/render_agents_md.py" in payload["actions"]
    assert "install:scripts/meta/check_agents_sync.py" in payload["actions"]
    assert "install:meta-process/templates/agents.md.template" in payload["actions"]
    assert "sync:.claude/hooks/gate-edit.sh" in payload["actions"]
    assert "render:AGENTS.md" in payload["actions"]
    assert payload["dry_run_mode"] is True
    assert len(payload["actions"]) == len(set(payload["actions"]))
    assert not (tmp_path / "AGENTS.md").exists()


def test_installer_blocks_write_when_target_runtime_lacks_yaml(tmp_path: Path) -> None:
    """The installer must not claim runnable context tools via the host environment."""

    _write_minimal_claude(tmp_path)
    _write_python_without_yaml(tmp_path)

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any("cannot import PyYAML" in blocker for blocker in payload["blockers"])
    assert not (tmp_path / "scripts" / "meta" / "context_packet.py").exists()


def test_install_governed_repo_write_bootstraps_minimum_repo_and_passes_audit(
    tmp_path: Path,
) -> None:
    """Write mode should bootstrap the minimum governed-repo surface."""
    _write_minimal_claude(tmp_path)

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--strict-governed",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["post_audit"]["classification"] == "governed"
    assert (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "AGENTS.md").is_symlink()
    assert (tmp_path / "meta-process.yaml").exists()
    starter = yaml.safe_load(
        (tmp_path / "meta-process.yaml").read_text(encoding="utf-8")
    )["meta_process"]
    assert starter["claims"] == {
        "enabled": False,
        "require_for_worktree": False,
        "prewrite_mode": "off",
    }
    assert starter["worktrees"] == {
        "enabled": False,
        "protect_main": False,
    }
    assert starter["commits"]["require_prefix"] is False
    assert starter["quality"]["doc_coupling"]["enabled"] is False
    assert (tmp_path / "scripts" / "relationships.yaml").exists()
    assert (tmp_path / "docs" / "plans" / "CLAUDE.md").exists()
    assert (tmp_path / "docs" / "plans" / "TEMPLATE.md").exists()
    assert (tmp_path / "Makefile").exists()
    assert (tmp_path / "enforced_planning" / "__init__.py").exists()
    assert (tmp_path / "enforced_planning" / "agents_rendering.py").exists()
    assert (tmp_path / "enforced_planning" / "concern_routing.py").exists()
    assert (tmp_path / "enforced_planning" / "plan_readiness.py").exists()
    assert (tmp_path / "enforced_planning" / "file_context.py").exists()
    assert (tmp_path / "enforced_planning" / "relationship_context.py").exists()
    assert (tmp_path / "enforced_planning" / "context_packet.py").exists()
    assert (tmp_path / "enforced_planning" / "impact_obligations.py").exists()
    assert (tmp_path / "enforced_planning" / "verification_batch.py").exists()
    assert (tmp_path / "enforced_planning" / "docstring_wiki.py").exists()
    assert (tmp_path / "enforced_planning" / "notebook_registry_validation.py").exists()
    assert (tmp_path / "enforced_planning" / "plan_validation.py").exists()
    assert (tmp_path / "enforced_planning" / "push_safety.py").exists()
    assert (tmp_path / "hooks" / "pre-push").exists()
    assert os.access(tmp_path / "hooks" / "pre-push", os.X_OK)
    assert (tmp_path / "enforced_planning" / "repository_status.py").exists()
    assert (tmp_path / "enforced_planning" / "session_contracts.py").exists()
    assert (tmp_path / "enforced_planning" / "session_lifecycle.py").exists()
    assert (tmp_path / "enforced_planning" / "worktree_lifecycle.yaml").exists()
    assert (tmp_path / "enforced_planning" / "worktree_paths.py").exists()
    assert (tmp_path / "scripts" / "meta" / "audit_dead_code.py").exists()
    assert (tmp_path / "scripts" / "meta" / "check_dead_code.py").exists()
    assert (tmp_path / "scripts" / "meta" / "check_push_safety.py").exists()
    assert (tmp_path / "scripts" / "meta" / "check_coordination_claims.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_start.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_heartbeat.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_status.py").exists()
    assert (tmp_path / "scripts" / "meta" / "project_status.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_finish.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_close.py").exists()
    assert (tmp_path / "scripts" / "meta" / "validate_dead_code_audit.py").exists()
    assert (
        tmp_path / "scripts" / "meta" / "worktree-coordination" / "create_publish_worktree.py"
    ).exists()
    assert (
        tmp_path / "scripts" / "meta" / "worktree-coordination" / "create_review_claim.py"
    ).exists()
    assert (
        tmp_path / "scripts" / "meta" / "worktree-coordination" / "raise_concern.py"
    ).exists()
    assert (tmp_path / "scripts" / "meta" / "file_context.py").exists()
    assert (tmp_path / "scripts" / "meta" / "relationship_context.py").exists()
    assert (tmp_path / "scripts" / "meta" / "context_packet.py").exists()
    assert (tmp_path / "scripts" / "meta" / "impact_obligations.py").exists()
    assert (tmp_path / "scripts" / "meta" / "verification_batch.py").exists()
    assert (tmp_path / "scripts" / "meta" / "docstring_wiki.py").exists()
    assert (tmp_path / "scripts" / "meta" / "render_agents_md.py").exists()
    assert (tmp_path / "scripts" / "meta" / "check_agents_sync.py").exists()
    assert (tmp_path / "meta-process" / "templates" / "agents.md.template").exists()
    assert (tmp_path / ".claude" / "hooks" / "gate-edit.sh").exists()
    assert (tmp_path / ".claude" / "settings.json").exists()
    makefile_text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "worktree:" in makefile_text
    assert "worktree-list:" in makefile_text
    assert "worktree-remove:" in makefile_text
    assert "session-start:" in makefile_text
    assert "session-heartbeat:" in makefile_text
    assert "session-status:" in makefile_text
    assert "PROJECT_STATUS_SCRIPT ?= scripts/meta/project_status.py" in makefile_text
    assert "$(PROJECT_STATUS_SCRIPT) --repo-root ." in makefile_text
    assert "session-finish:" in makefile_text
    assert "session-close:" in makefile_text
    assert "review-claim:" in makefile_text
    assert "raise-concern:" in makefile_text
    assert "verification-batch-freeze:" in makefile_text
    assert "verification-batch-check:" in makefile_text
    assert "verification-batch-thaw:" in makefile_text
    assert "push-check:" in makefile_text
    assert "scripts/meta/worktree-coordination/../check_coordination_claims.py" in makefile_text
    assert "scripts/meta/worktree-coordination/../session_start.py" in makefile_text
    assert "scripts/meta/worktree-coordination/create_review_claim.py" in makefile_text
    assert "scripts/meta/worktree-coordination/raise_concern.py" in makefile_text
    assert "$(SCRIPTS_META)/worktree-coordination" not in makefile_text
    assert "--print-default-worktree-dir" in makefile_text
    assert '--agent "$(WORKTREE_AGENT)"' in makefile_text
    assert '--project "$(WORKTREE_PROJECT)"' in makefile_text
    assert '--scope "$(BRANCH)"' in makefile_text
    assert 'SESSION_GOAL is required' in makefile_text
    assert 'SESSION_PHASE is required' in makefile_text
    assert 'SESSION_CLAIM_TYPE ?= program' in makefile_text
    assert 'ALLOW_UNPLANNED ?=' in makefile_text
    assert makefile_text.count("$(if $(ALLOW_UNPLANNED),--allow-unplanned,)") == 3
    assert '--claim-type "$(SESSION_CLAIM_TYPE)"' in makefile_text
    assert '--parent-scope' in makefile_text
    assert '--write-path' in makefile_text
    assert "WORKTREE_DISPOSITION ?= merged" in makefile_text
    assert '--disposition "$(WORKTREE_DISPOSITION)"' in makefile_text
    assert "$(filter 1 true yes,$(WORKTREE_ALLOW_DISCARD_UNIQUE))" in makefile_text
    sync_result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts" / "meta" / "check_agents_sync.py"),
            "--repo-root",
            str(tmp_path),
            "--check",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert sync_result.returncode == 0, sync_result.stdout + sync_result.stderr
    file_context_result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts" / "meta" / "file_context.py"),
            "--json",
            "CLAUDE.md",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert file_context_result.returncode == 0, (
        file_context_result.stdout + file_context_result.stderr
    )


def test_installed_make_gate_rejects_stale_agents_projection(tmp_path: Path) -> None:
    """The canonical Make gate must discriminate a stale generated mirror."""

    _write_minimal_claude(tmp_path)
    installed = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    current = subprocess.run(
        ["make", "check-agents-sync"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert current.returncode == 0, current.stdout + current.stderr

    agents = tmp_path / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8") + "\nmanual drift\n", encoding="utf-8")
    stale = subprocess.run(
        ["make", "check-agents-sync"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert stale.returncode != 0
    assert "AGENTS.md drift detected" in stale.stdout


def test_install_governed_repo_reports_and_syncs_drifted_validator(tmp_path: Path) -> None:
    """Dry-run should report drift and write mode should restore canonical support files."""
    _write_minimal_claude(tmp_path)

    first = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert first.returncode == 0, first.stdout + first.stderr

    drifted_path = tmp_path / "scripts" / "meta" / "file_context.py"
    drifted_path.write_text('"""Drifted validator."""\n', encoding="utf-8")

    dry_run = _run("--repo-root", str(tmp_path), "--json", cwd=PROJECT_META_ROOT)
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    dry_payload = json.loads(dry_run.stdout)
    assert "scripts/meta/file_context.py" in dry_payload["drift_files"]

    second = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert drifted_path.read_text(encoding="utf-8") == CANONICAL_FILE_CONTEXT.read_text(
        encoding="utf-8"
    )


def test_installed_context_packet_wrapper_resolves_target_repo_root(tmp_path: Path) -> None:
    """The ``scripts/meta`` installation layout must import and inventory the target repo."""

    _write_minimal_claude(tmp_path)
    installed = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)

    result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts" / "meta" / "context_packet.py"),
            "CLAUDE.md",
            "--repo-root",
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    makefile_text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "PROJECT_STATUS_SCRIPT ?= scripts/meta/project_status.py" in makefile_text
    assert "$(PROJECT_STATUS_SCRIPT) --repo-root ." in makefile_text
    assert "git status --short --branch" not in makefile_text
    payload = json.loads(result.stdout)
    assert payload["target"] == "CLAUDE.md"
    assert payload["items"][0]["path"] == "CLAUDE.md"


def test_install_governed_repo_is_idempotent_after_write(tmp_path: Path) -> None:
    """A second dry-run after bootstrap should report no further actions."""
    _write_minimal_claude(tmp_path)

    first = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert first.returncode == 0, first.stdout + first.stderr

    second = _run("--repo-root", str(tmp_path), "--json", cwd=PROJECT_META_ROOT)
    assert second.returncode == 0, second.stdout + second.stderr
    payload = json.loads(second.stdout)
    assert payload["actions"] == []


def test_install_governed_repo_appends_makefile_meta_block_when_missing(
    tmp_path: Path,
) -> None:
    """Write mode should append the sanctioned worktree block to an existing Makefile."""
    _write_minimal_claude(tmp_path)
    (tmp_path / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "append:Makefile.status" in payload["actions"]
    assert "append:Makefile.worktree" in payload["actions"]
    makefile_text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "PROJECT_STATUS_SCRIPT ?= scripts/meta/project_status.py" in makefile_text
    assert "$(PROJECT_STATUS_SCRIPT) --repo-root ." in makefile_text
    assert "git status --short --branch" not in makefile_text
    assert "help:" in makefile_text
    assert "worktree:" in makefile_text
    assert "# >>> META-PROCESS WORKTREE TARGETS >>>" in makefile_text
    assert "# <<< META-PROCESS WORKTREE TARGETS <<<" in makefile_text
    assert '$(MAKE) session-close BRANCH="$(BRANCH)"' in makefile_text


def test_appended_project_status_target_executes_without_makefile_variables(
    tmp_path: Path,
) -> None:
    """A custom Makefile needs no pre-existing Python or script variables."""

    repo = tmp_path / "repo"
    remote = tmp_path / "remote.git"
    repo.mkdir()
    _write_minimal_claude(repo)
    (repo / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")

    install = _run("--repo-root", str(repo), "--write", "--json", cwd=PROJECT_META_ROOT)
    assert install.returncode == 0, install.stdout + install.stderr

    _git(tmp_path, "init", "--bare", str(remote))
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "installed governed repo")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "remote", "set-head", "origin", "-a")

    status = subprocess.run(
        ["make", "status"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
        env={key: value for key, value in os.environ.items() if key != "PYTHON"},
    )

    assert status.returncode == 0, status.stdout + status.stderr
    assert "Repository authority: current" in status.stdout


def test_install_governed_repo_syncs_worktree_block_into_existing_meta_makefile(
    tmp_path: Path,
) -> None:
    """Write mode should inject the sanctioned worktree block into a stale meta-process Makefile."""
    _write_minimal_claude(tmp_path)
    (tmp_path / "Makefile").write_text(
        "\n".join(
            [
                "# === META-PROCESS TARGETS ===",
                "# Added by meta-process install.sh",
                "",
                "# Configuration",
                "SCRIPTS_META := scripts/meta",
                "PLANS_DIR := docs/plans",
                "GITHUB_ACCOUNT ?= BrianMills2718",
                "PR_AUTO_EXPECTED_REPO ?= $(notdir $(CURDIR))",
                "",
                "# --- Session Start ---",
                ".PHONY: status",
                "",
                "status:  ## Show git status",
                "\t@git status --short --branch",
                "",
                "# --- During Implementation ---",
                ".PHONY: test",
                "",
                "test:  ## Run pytest",
                "\tpytest tests/ -q",
                "",
                "# --- Help ---",
                ".PHONY: help-meta",
                "",
                "help-meta:  ## Show meta-process targets",
                "\t@echo Meta",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "append:Makefile.worktree" in payload["actions"]
    makefile_text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "# >>> META-PROCESS WORKTREE TARGETS >>>" in makefile_text
    assert "WORKTREE_CREATE_SCRIPT := scripts/meta/worktree-coordination/create_worktree.py" in makefile_text
    assert "WORKTREE_CLAIMS_SCRIPT := scripts/meta/worktree-coordination/../check_coordination_claims.py" in makefile_text
    assert "WORKTREE_SESSION_START_SCRIPT := scripts/meta/worktree-coordination/../session_start.py" in makefile_text
    assert "WORKTREE_START_POINT ?= HEAD" in makefile_text
    assert "--print-canonical-project" in makefile_text
    assert "SESSION_CLAIM_TYPE ?= program" in makefile_text
    assert (
        "WORKTREE_PLAN_READINESS_SCRIPT := "
        "scripts/meta/worktree-coordination/../check_plan_readiness.py"
    ) in makefile_text
    assert "PLAN_READINESS_COMMAND ?=" in makefile_text
    assert "PLAN_RESUME ?=" in makefile_text
    assert '--qualified-plan-id "$(PLAN_PROJECT)#$(PLAN)"' in makefile_text
    assert "$(if $(PLAN_RESUME),--resume,)" in makefile_text
    assert makefile_text.index('"$(WORKTREE_PLAN_READINESS_SCRIPT)"') < makefile_text.index(
        '"$(WORKTREE_CLAIMS_SCRIPT)" --claim'
    )
    assert "--parent-scope" in makefile_text
    assert "--write-path" in makefile_text
    assert "session-start:" in makefile_text
    assert "session-finish:" in makefile_text
    assert "worktree-list:" in makefile_text
    assert "worktree-remove:" in makefile_text
    assert "# --- During Implementation ---" in makefile_text
    assert "test:  ## Run pytest" in makefile_text


def test_install_governed_repo_worktree_only_mode_stays_bounded(tmp_path: Path) -> None:
    """Worktree-only mode should sync only the sanctioned worktree surface."""
    _write_minimal_claude(tmp_path)
    (tmp_path / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--worktree-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["worktree_only_mode"] is True
    assert not (
        tmp_path / "enforced_planning" / "__init__.py"
    ).read_bytes().endswith(b"\n\n")
    assert sorted(payload["actions"]) == sorted(
        [
            "install:enforced_planning/__init__.py",
            "install:enforced_planning/concern_routing.py",
            "install:enforced_planning/coordination_claims.py",
            "install:enforced_planning/coordination_messages.py",
            "install:enforced_planning/prewrite_claim_fast.py",
            "install:enforced_planning/prewrite_claim_projection.py",
            "install:enforced_planning/plan_readiness.py",
            "install:enforced_planning/plan_close.py",
            "install:enforced_planning/doc_authority.py",
            "install:enforced_planning/push_safety.py",
            "install:enforced_planning/repository_status.py",
            "install:enforced_planning/session_contracts.py",
            "install:enforced_planning/session_lifecycle.py",
            "install:enforced_planning/verification_batch.py",
            "install:enforced_planning/worktree_lifecycle.yaml",
            "install:enforced_planning/worktree_paths.py",
            "install:hooks/pre-push",
            "install:scripts/meta/check_coordination_claims.py",
            "install:scripts/refresh_prewrite_claim_projection.py",
            "install:scripts/meta/check_push_safety.py",
            "install:scripts/meta/check_plan_readiness.py",
            "install:scripts/meta/plan_close.py",
                "install:scripts/meta/session_close.py",
                "install:scripts/meta/session_end.py",
                "install:scripts/meta/session_finish.py",
            "install:scripts/meta/session_heartbeat.py",
            "install:scripts/meta/session_start.py",
            "install:scripts/meta/session_status.py",
            "install:scripts/meta/project_status.py",
            "install:scripts/meta/session_resume.py",
            "install:scripts/meta/verification_batch.py",
            "install:scripts/coordination_inbox.py",
            "install:scripts/coordination_messages.py",
            "install:scripts/meta/coordination_inbox.py",
            "install:scripts/meta/coordination_messages.py",
            "install:scripts/meta/worktree-coordination/create_worktree.py",
            "install:scripts/meta/worktree-coordination/create_publish_worktree.py",
            "install:scripts/meta/worktree-coordination/create_review_claim.py",
            "install:scripts/meta/worktree-coordination/raise_concern.py",
            "install:scripts/meta/worktree-coordination/safe_worktree_remove.py",
            "append:Makefile.status",
            "append:Makefile.worktree",
        ]
    )
    assert not (tmp_path / "scripts" / "relationships.yaml").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".claude" / "hooks" / "gate-edit.sh").exists()
    assert (tmp_path / "scripts" / "meta" / "check_coordination_claims.py").exists()
    installed_readiness = tmp_path / "enforced_planning" / "plan_readiness.py"
    assert installed_readiness.read_text(encoding="utf-8") == (
        PROJECT_META_ROOT / "enforced_planning" / "plan_readiness.py"
    ).read_text(encoding="utf-8")
    installed_readiness_cli = tmp_path / "scripts" / "meta" / "check_plan_readiness.py"
    assert installed_readiness_cli.read_text(encoding="utf-8") == (
        PROJECT_META_ROOT / "scripts" / "check_plan_readiness.py"
    ).read_text(encoding="utf-8")
    assert "PLAN_RESUME ?=" in (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert (tmp_path / "hooks" / "pre-push").exists()
    assert os.access(tmp_path / "hooks" / "pre-push", os.X_OK)
    assert (tmp_path / "scripts" / "meta" / "session_start.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_heartbeat.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_status.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_resume.py").exists()
    assert (tmp_path / "scripts" / "meta" / "verification_batch.py").exists()
    assert (tmp_path / "scripts" / "coordination_inbox.py").exists()
    assert (tmp_path / "scripts" / "coordination_messages.py").exists()
    assert (tmp_path / "scripts" / "meta" / "coordination_messages.py").exists()
    assert (tmp_path / "enforced_planning" / "coordination_messages.py").exists()
    assert (tmp_path / "enforced_planning" / "plan_readiness.py").exists()
    assert (tmp_path / "enforced_planning" / "plan_close.py").exists()
    assert (tmp_path / "scripts" / "meta" / "check_plan_readiness.py").exists()
    assert (tmp_path / "scripts" / "meta" / "plan_close.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_finish.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_close.py").exists()
    assert (tmp_path / "enforced_planning" / "session_contracts.py").exists()
    assert (tmp_path / "enforced_planning" / "session_lifecycle.py").exists()
    assert (tmp_path / "enforced_planning" / "verification_batch.py").exists()
    assert (tmp_path / "enforced_planning" / "worktree_lifecycle.yaml").exists()
    assert (tmp_path / "enforced_planning" / "worktree_paths.py").exists()
    assert (
        tmp_path / "scripts" / "meta" / "worktree-coordination" / "create_worktree.py"
    ).exists()
    assert (
        tmp_path
        / "scripts"
        / "meta"
        / "worktree-coordination"
        / "create_publish_worktree.py"
    ).exists()
    assert (
        tmp_path
        / "scripts"
        / "meta"
        / "worktree-coordination"
        / "safe_worktree_remove.py"
    ).exists()
    makefile_text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "worktree:" in makefile_text
    assert "worktree-list:" in makefile_text
    assert "worktree-remove:" in makefile_text
    assert "session-start:" in makefile_text
    assert "session-finish:" in makefile_text
    assert "session-close:" in makefile_text
    assert "verification-batch-freeze:" in makefile_text
    assert "verification-batch-check:" in makefile_text
    assert "verification-batch-thaw:" in makefile_text
    assert "WORKTREE_DISPOSITION ?= merged" in makefile_text
    assert '--disposition "$(WORKTREE_DISPOSITION)"' in makefile_text
    assert "$(filter 1 true yes,$(WORKTREE_ALLOW_DISCARD_UNIQUE))" in makefile_text

    close_help = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "meta" / "session_close.py"), "--help"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert close_help.returncode == 0, close_help.stdout + close_help.stderr
    assert "--disposition" in close_help.stdout
    assert "--recovery-ref" in close_help.stdout

    safe_remove_help = subprocess.run(
        [
            sys.executable,
            str(
                tmp_path
                / "scripts"
                / "meta"
                / "worktree-coordination"
                / "safe_worktree_remove.py"
            ),
            "--help",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert safe_remove_help.returncode == 0, (
        safe_remove_help.stdout + safe_remove_help.stderr
    )

    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "installed worktree surface",
        ],
        check=True,
    )
    make_environment = [f"PYTHON={sys.executable}"]
    freeze = subprocess.run(
        [
            "make",
            "-C",
            str(tmp_path),
            "verification-batch-freeze",
            *make_environment,
            "DECISION=Verify installed terminal batch controls",
            "VERIFY_COMMAND=make check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert freeze.returncode == 0, freeze.stdout + freeze.stderr
    check = subprocess.run(
        ["make", "-C", str(tmp_path), "verification-batch-check", *make_environment],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
    thaw = subprocess.run(
        [
            "make",
            "-C",
            str(tmp_path),
            "verification-batch-thaw",
            *make_environment,
            "REASON=Both-sign installer test complete",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert thaw.returncode == 0, thaw.stdout + thaw.stderr

    portable_lint = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            str(tmp_path / "enforced_planning"),
            str(tmp_path / "scripts" / "meta"),
            "--ignore=F401",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert portable_lint.returncode == 0, portable_lint.stdout + portable_lint.stderr


def test_worktree_rollout_activates_versioned_git_hooks(tmp_path: Path) -> None:
    """A real Git consumer should receive an active pre-push gate."""

    _write_minimal_claude(tmp_path)
    (tmp_path / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--worktree-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert "configure:git.core.hooksPath=hooks" in payload["applied_actions"]
    assert _git(tmp_path, "config", "--local", "--get", "core.hooksPath") == "hooks"
    assert os.access(tmp_path / "hooks" / "pre-push", os.X_OK)


def test_worktree_rollout_refuses_to_replace_custom_git_hook_path(tmp_path: Path) -> None:
    """Installer must not silently displace a consumer-owned hook stack."""

    _write_minimal_claude(tmp_path)
    (tmp_path / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "--local", "core.hooksPath", ".custom-hooks")

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--worktree-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["blockers"] == [
        "core.hooksPath is already '.custom-hooks'; refusing to replace custom Git hooks"
    ]
    assert _git(tmp_path, "config", "--local", "--get", "core.hooksPath") == ".custom-hooks"
    assert not (tmp_path / "hooks" / "pre-push").exists()


def test_worktree_rollout_repairs_non_executable_pre_push_hook(tmp_path: Path) -> None:
    """Content equality must not conceal an inactive non-executable hook."""

    _write_minimal_claude(tmp_path)
    (tmp_path / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")
    first = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--worktree-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert first.returncode == 0, first.stdout + first.stderr
    hook = tmp_path / "hooks" / "pre-push"
    hook.chmod(0o644)

    repaired = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--worktree-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    payload = json.loads(repaired.stdout)
    assert "chmod:hooks/pre-push" in payload["applied_actions"]
    assert os.access(hook, os.X_OK)


def test_install_governed_repo_worktree_only_requires_existing_makefile(
    tmp_path: Path,
) -> None:
    """Worktree-only mode should fail loud instead of inventing a new Makefile."""
    _write_minimal_claude(tmp_path)

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--worktree-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["worktree_only_mode"] is True
    assert "missing Makefile for --worktree-only rollout" in payload["blockers"]
    assert not (tmp_path / "Makefile").exists()


def test_install_governed_repo_explicit_dry_run_reports_expected_actions(tmp_path: Path) -> None:
    """Explicit --dry-run should be treated as non-writing preview mode."""
    _write_minimal_claude(tmp_path)

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--dry-run",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["write_mode"] is False
    assert payload["dry_run_mode"] is True
    assert payload["actions"]


def test_install_sh_default_delegates_to_canonical_installer(tmp_path: Path) -> None:
    """The shell wrapper should delegate the default path to the canonical installer."""
    _write_minimal_claude(tmp_path)
    subprocess.run(
        ["git", "init", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )

    result = subprocess.run(
        ["bash", str(INSTALL_SH), str(tmp_path)],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Delegating to canonical Python installer" in result.stdout
    assert (tmp_path / "meta-process.yaml").exists()
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / "scripts" / "relationships.yaml").exists()
    assert (tmp_path / ".claude" / "hooks" / "gate-edit.sh").exists()


def test_install_governed_repo_fails_loud_without_claude_md(tmp_path: Path) -> None:
    """The installer should refuse to proceed when the repo lacks canonical governance."""
    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert "missing canonical CLAUDE.md" in payload["blockers"]


def test_install_governed_repo_rejects_write_and_dry_run(tmp_path: Path) -> None:
    """Install CLI should enforce that --write and --dry-run are mutually exclusive."""
    result = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--dry-run",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
