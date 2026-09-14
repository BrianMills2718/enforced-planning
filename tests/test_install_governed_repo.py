"""Tests for governed-repo installer/upgrader tooling."""

from __future__ import annotations

import json
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

import yaml


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_META_ROOT / "scripts" / "install_governed_repo.py"
INSTALL_SH = PROJECT_META_ROOT / "install.sh"
CANONICAL_FILE_CONTEXT = PROJECT_META_ROOT / "scripts" / "file_context.py"
CANONICAL_FILE_CONTEXT_MODULE = PROJECT_META_ROOT / "enforced_planning" / "file_context.py"
COORDINATION_CLAIMS_ROLLOUT_PATHS = {
    "enforced_planning/coordination_claims.py",
    "scripts/meta/check_coordination_claims.py",
}
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
    # The canonical-checkout lock rides the coordination-messages rollout: a
    # repo that gains coordination also gains the hook that repairs a stale
    # canonical lock at session start and prints the escape hatch when a lock
    # blocks a write.
    ".claude/hooks/reconcile-canonical-locks.sh",
    "scripts/meta/canonical_lock.py",
    ".claude/settings.json",
    ".codex/hooks.json",
    ".codex/hooks/notify-coordination-messages.sh",
    "scripts/coordination_hook.py",
    "scripts/coordination_inbox.py",
    "scripts/coordination_messages.py",
    "scripts/coordination_operator_status.py",
    "scripts/meta/coordination_hook.py",
    "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_messages.py",
    "scripts/meta/coordination_operator_status.py",
    "scripts/meta/session_heartbeat.py",
    "scripts/meta/session_narrow.py",
    "scripts/meta/apply_blocker_disposition.py",
    "scripts/meta/outcome_completion_hook.py",
    "scripts/meta/session_close.py",
    "scripts/meta/session_continuity.py",
    "scripts/meta/session_resume.py",
    "scripts/meta/session_start.py",
    "scripts/hook_receipts.py",
    "scripts/meta/hook_receipts.py",
}

MAILBOX_ROLLOUT_PATHS = MAILBOX_COMMON_ROLLOUT_PATHS | {
    "enforced_planning/claim_mutation_receipts.py",
    "enforced_planning/blocker_policy.py",
    "enforced_planning/client_session_metadata.py",
    "enforced_planning/coordination_claims.py",
    "enforced_planning/concurrent_writers.py",
    "enforced_planning/concern_routing.py",
    "enforced_planning/mailbox_execution_identity.py",
    "enforced_planning/coordination_messages.py",
    "enforced_planning/outcome_admission.py",
    "enforced_planning/outcome_completion.py",
    "enforced_planning/outcome_continuation.py",
    "enforced_planning/outcome_portfolio.py",
    "enforced_planning/outcome_selection.py",
    "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/prewrite_claim_projection.py",
    "enforced_planning/file_context.py",
    "enforced_planning/notebook_registry_validation.py",
    "enforced_planning/plan_validation.py",
    "enforced_planning/doc_authority.py",
    "enforced_planning/push_safety.py",
    "enforced_planning/session_contracts.py",
    "enforced_planning/session_continuity.py",
    "enforced_planning/session_lifecycle.py",
    "enforced_planning/session_process_fencing.py",
    "enforced_planning/session_target.py",
    "enforced_planning/surface_runtime.py",
    "enforced_planning/worktree_lifecycle.yaml",
    "enforced_planning/worktree_paths.py",
    "scripts/refresh_prewrite_claim_projection.py",
}

CLAIM_PROJECTION_REFRESH_PATHS = {
    "enforced_planning/blocker_policy.py",
    "enforced_planning/claim_mutation_receipts.py",
    "enforced_planning/client_session_metadata.py",
    "enforced_planning/coordination_claims.py",
    "enforced_planning/concurrent_writers.py",
    "enforced_planning/mailbox_execution_identity.py",
    "enforced_planning/coordination_messages.py",
    "enforced_planning/outcome_admission.py",
    "enforced_planning/outcome_continuation.py",
    "enforced_planning/outcome_portfolio.py",
    "enforced_planning/outcome_selection.py",
    "enforced_planning/doc_authority.py",
    "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/prewrite_claim_projection.py",
    "enforced_planning/file_context.py",
    "enforced_planning/notebook_registry_validation.py",
    "enforced_planning/plan_validation.py",
    "enforced_planning/push_safety.py",
    "enforced_planning/session_contracts.py",
    "enforced_planning/session_continuity.py",
    "enforced_planning/session_lifecycle.py",
    "enforced_planning/session_process_fencing.py",
    "enforced_planning/session_target.py",
    "enforced_planning/surface_runtime.py",
    "enforced_planning/worktree_lifecycle.yaml",
    "enforced_planning/worktree_paths.py",
    "scripts/refresh_prewrite_claim_projection.py",
    "scripts/meta/canonical_lock.py",
    "scripts/meta/check_coordination_claims.py",
    "scripts/meta/worktree-coordination/create_worktree.py",
    "scripts/meta/session_close.py",
    "scripts/meta/session_continuity.py",
    "scripts/meta/session_end.py",
    "scripts/meta/session_finish.py",
    "scripts/meta/session_heartbeat.py",
    "scripts/meta/session_narrow.py",
    "scripts/meta/apply_blocker_disposition.py",
    "scripts/meta/session_resume.py",
    "scripts/meta/session_start.py",
}


def test_source_repo_claim_facade_projection_matches_canonical_source() -> None:
    """The source repo's normal Make entrypoint must not run a stale claim facade."""

    canonical = PROJECT_META_ROOT / "scripts" / "check_coordination_claims.py"
    installed = PROJECT_META_ROOT / "scripts" / "meta" / "check_coordination_claims.py"

    assert installed.read_bytes() == canonical.read_bytes()


def test_source_repo_narrowing_facades_match_canonical_sources() -> None:
    """Generated lifecycle/worktree copies are installer outputs, never independent owners."""

    pairs = {
        "scripts/meta/session_start.py": "scripts/session_start.py",
        "scripts/meta/session_narrow.py": "scripts/session_narrow.py",
        "scripts/meta/apply_blocker_disposition.py": "scripts/apply_blocker_disposition.py",
        "scripts/meta/session_close.py": "scripts/session_close.py",
        "scripts/meta/worktree-coordination/create_worktree.py": (
            "scripts/worktree-coordination/create_worktree.py"
        ),
    }
    for generated, canonical in pairs.items():
        assert (PROJECT_META_ROOT / generated).read_bytes() == (PROJECT_META_ROOT / canonical).read_bytes()


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
    required = ("enforced_planning/__init__.py",)
    for relative in required:
        source = PROJECT_META_ROOT / relative
        target = repo_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    stale_lifecycle = repo_root / "enforced_planning/session_lifecycle.py"
    stale_lifecycle.write_text('"""Stale lifecycle fixture."""\n', encoding="utf-8")
    (repo_root / "enforced_planning/push_safety.py").write_text('"""Stale push-safety fixture."""\n', encoding="utf-8")
    (repo_root / "enforced_planning/worktree_lifecycle.yaml").write_text("schema_version: 0\n", encoding="utf-8")
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
    codex_settings = json.loads(
        (tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8")
    )
    assert "enforce-make-merge.sh" not in json.dumps(codex_settings)
    for wrapper in (
        "coordination_hook.py",
        "coordination_inbox.py",
        "coordination_messages.py",
        "coordination_operator_status.py",
    ):
        help_result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts/meta" / wrapper), "--help"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stdout + help_result.stderr
    clean_env = dict(os.environ)
    clean_env.pop("PYTHONPATH", None)
    lifecycle_help = {}
    for lifecycle_wrapper in ("session_close.py", "session_resume.py"):
        lifecycle_help[lifecycle_wrapper] = subprocess.run(
            [sys.executable, str(tmp_path / "scripts/meta" / lifecycle_wrapper), "--help"],
            cwd=str(tmp_path),
            env=clean_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert lifecycle_help[lifecycle_wrapper].returncode == 0, (
            lifecycle_help[lifecycle_wrapper].stdout
            + lifecycle_help[lifecycle_wrapper].stderr
        )
    assert "--mailbox-disposition" in lifecycle_help["session_close.py"].stdout

    repeat = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-messages-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert repeat.returncode == 0
    assert json.loads(repeat.stdout)["actions"] == []


def test_coordination_claims_only_rollout_is_exact_and_idempotent(tmp_path: Path) -> None:
    """One claim-policy repair must not drag unrelated fleet surfaces with it."""

    _prepare_mailbox_target(tmp_path)
    dry_run = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-claims-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    payload = json.loads(dry_run.stdout)
    assert payload["coordination_claims_only_mode"] is True
    assert {action.split(":", 1)[1] for action in payload["actions"]} == (
        COORDINATION_CLAIMS_ROLLOUT_PATHS
    )
    assert payload["blockers"] == []

    written = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-claims-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert written.returncode == 0, written.stdout + written.stderr
    for relative in COORDINATION_CLAIMS_ROLLOUT_PATHS:
        assert (tmp_path / relative).read_bytes() == (PROJECT_META_ROOT / relative).read_bytes()

    repeat = _run(
        "--repo-root",
        str(tmp_path),
        "--coordination-claims-only",
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
    original_claude_settings = (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8")
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
    assert {action.split(":", 1)[1] for action in payload["actions"]} == (CLAIM_PROJECTION_REFRESH_PATHS)
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
    assert (tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8") == original_claude_settings
    for relative in CLAIM_PROJECTION_REFRESH_PATHS:
        assert (tmp_path / relative).is_file()

    installed_lifecycle = tmp_path / "enforced_planning" / "session_lifecycle.py"
    assert (
        installed_lifecycle.read_bytes()
        == (PROJECT_META_ROOT / "enforced_planning" / "session_lifecycle.py").read_bytes()
    )
    clean_env = dict(os.environ)
    clean_env.pop("PYTHONPATH", None)
    for wrapper in (
        "session_start.py",
        "session_narrow.py",
        "session_close.py",
        "session_resume.py",
    ):
        help_result = subprocess.run(
            [sys.executable, str(tmp_path / "scripts/meta" / wrapper), "--help"],
            cwd=str(tmp_path),
            env=clean_env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stdout + help_result.stderr

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


def test_worktree_rollout_rejects_unmarked_legacy_merge_targets(tmp_path: Path) -> None:
    """An installer must not append a sanctioned finish behind legacy bypasses."""

    _write_minimal_claude(tmp_path)
    makefile = tmp_path / "Makefile"
    original = (
        "merge:\n\t@python scripts/meta/merge_pr.py $(PR)\n\n"
        "finish:\n\t@gh pr merge $(PR) --squash --delete-branch\n"
    )
    makefile.write_text(original, encoding="utf-8")

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--worktree-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any("legacy PR Make targets" in item for item in payload["blockers"])
    assert makefile.read_text(encoding="utf-8") == original


def test_worktree_rollout_rejects_legacy_finish_outside_existing_marker(tmp_path: Path) -> None:
    """An upgrade must catch a historical recipe trailing a generated block."""

    _write_minimal_claude(tmp_path)
    generated = (PROJECT_META_ROOT / "templates/Makefile.worktree.block.template").read_text(
        encoding="utf-8"
    )
    makefile = tmp_path / "Makefile"
    original = generated + "\nfinish:\n\t@gh pr merge $(PR) --squash --delete-branch\n"
    makefile.write_text(original, encoding="utf-8")

    result = _run(
        "--repo-root",
        str(tmp_path),
        "--worktree-only",
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert any("outside the generated worktree block" in item for item in payload["blockers"])
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
    assert "install:scripts/meta/validate_doc_authority.py" in payload["actions"]
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


def test_install_governed_repo_check_fails_on_managed_drift(tmp_path: Path) -> None:
    """Check mode must expose stale installed support files without repairing them."""

    _write_minimal_claude(tmp_path)
    installed = _run("--repo-root", str(tmp_path), "--write", "--json", cwd=PROJECT_META_ROOT)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    renderer = tmp_path / "scripts" / "meta" / "render_agents_md.py"
    renderer.write_text("# stale installed renderer\n", encoding="utf-8")

    checked = _run("--repo-root", str(tmp_path), "--check", "--json", cwd=PROJECT_META_ROOT)

    assert checked.returncode == 1
    payload = json.loads(checked.stdout)
    assert "sync:scripts/meta/render_agents_md.py" in payload["actions"]
    assert renderer.read_text(encoding="utf-8") == "# stale installed renderer\n"


def test_installed_agents_tools_run_from_linked_worktree(tmp_path: Path) -> None:
    """Installed render/check entrypoints must resolve local runtime in a worktree."""

    repo_root = tmp_path / "consumer"
    repo_root.mkdir()
    _write_minimal_claude(repo_root)
    installed = _run("--repo-root", str(repo_root), "--write", "--json", cwd=PROJECT_META_ROOT)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    for command in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test User"],
        ["git", "add", "."],
        ["git", "commit", "-m", "initial"],
    ):
        result = subprocess.run(command, cwd=repo_root, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stdout + result.stderr

    linked = repo_root / "worktrees" / "portability-probe"
    result = subprocess.run(
        ["git", "worktree", "add", "-b", "portability-probe", str(linked)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    for script in ("render_agents_md.py", "check_agents_sync.py"):
        result = subprocess.run(
            [sys.executable, str(linked / "scripts" / "meta" / script), "--help"],
            cwd=linked,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


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
    starter = yaml.safe_load((tmp_path / "meta-process.yaml").read_text(encoding="utf-8"))["meta_process"]
    assert starter["plans"]["integrity"] == {
        "mode": "enforce",
        "contract_version": "1.0.0",
        "minimum_plan_number": 1,
    }
    assert starter["governance"] == {"enabled": True}
    assert starter["knowledge_navigation"] == {
        "enabled": True,
        "freshness_mode": "observe",
    }
    assert (tmp_path / "enforced_planning" / "effective_project_profile.py").exists()
    assert (tmp_path / "scripts" / "meta" / "effective_project_profile.py").exists()
    assert payload["post_audit"]["effective_project_profile"]["master_enabled"] is True
    assert starter["claims"] == {
        "enabled": True,
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
    plan_template = (tmp_path / "docs" / "plans" / "TEMPLATE.md").read_text(encoding="utf-8")
    assert "## Epistemic Planning Frontier" in plan_template
    assert "## Reassessment Contract" in plan_template
    assert "Structural PASS cannot prove" in plan_template
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
    assert (tmp_path / "enforced_planning" / "repository_authority.py").exists()
    assert (tmp_path / "enforced_planning" / "session_contracts.py").exists()
    assert (tmp_path / "enforced_planning" / "session_lifecycle.py").exists()
    assert (tmp_path / "enforced_planning" / "session_process_fencing.py").exists()
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
    assert (tmp_path / "scripts" / "meta" / "validate_doc_authority.py").exists()
    assert (tmp_path / "scripts" / "meta" / "worktree-coordination" / "create_publish_worktree.py").exists()
    assert (tmp_path / "scripts" / "meta" / "worktree-coordination" / "create_review_claim.py").exists()
    assert (tmp_path / "scripts" / "meta" / "worktree-coordination" / "raise_concern.py").exists()
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
    assert "goal-worktree:" in makefile_text
    assert '"operation":"goal_worktree"' in makefile_text
    assert "maintenance-worktree:" in makefile_text
    assert "scripts/meta/claim_bootstrap.py --request-json" in makefile_text
    assert "worktree-list:" in makefile_text
    assert "worktree-remove:" in makefile_text
    assert "session-start:" in makefile_text
    assert "session-heartbeat:" in makefile_text
    assert (
        '$(if $(or $(PLAN),$(OUTCOME_ADMISSION_BOOTSTRAP_PLAN)),--start-revision '
        '"$(WORKTREE_START_REVISION)",)'
    ) in makefile_text


def test_default_off_reenable_and_wiki_freshness_journey(tmp_path: Path) -> None:
    """One disposable consumer must exercise the Plan 128 stable example."""

    _write_minimal_claude(tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "example.py"
    source.write_text('"""Initial documented module."""\n', encoding="utf-8")
    installed = _run("--repo-root", str(tmp_path), "--write", "--json", cwd=PROJECT_META_ROOT)
    assert installed.returncode == 0, installed.stdout + installed.stderr
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
            "baseline",
        ],
        check=True,
    )

    profile_command = [
        sys.executable,
        str(tmp_path / "scripts/meta/effective_project_profile.py"),
        "--repo-root",
        str(tmp_path),
    ]
    default_profile = json.loads(subprocess.run(profile_command, check=True, capture_output=True, text=True).stdout)
    assert default_profile["master_enabled"] is True
    assert default_profile["controls"]["knowledge_navigation.enabled"]["effective"] is True

    config_path = tmp_path / "meta-process.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["meta_process"]["governance"]["enabled"] = False
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    disabled = json.loads(subprocess.run(profile_command, check=True, capture_output=True, text=True).stdout)
    assert disabled["controls"]["plans.integrity.mode"]["effective"] == "off"
    assert disabled["controls"]["knowledge_navigation.enabled"]["effective"] is False

    config["meta_process"]["governance"]["enabled"] = True
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    restored = json.loads(subprocess.run(profile_command, check=True, capture_output=True, text=True).stdout)
    assert restored["controls"]["plans.integrity.mode"]["effective"] == "enforce"

    wiki = [sys.executable, str(tmp_path / "scripts/meta/docstring_wiki.py"), "--repo-root", str(tmp_path)]
    assert subprocess.run([*wiki, "--write"], capture_output=True, text=True).returncode == 0
    source.write_text('"""Changed documented module."""\n', encoding="utf-8")
    stale = subprocess.run([*wiki, "--check"], capture_output=True, text=True)
    assert stale.returncode != 0
    assert "stale" in stale.stdout + stale.stderr
    assert subprocess.run([*wiki, "--write"], capture_output=True, text=True).returncode == 0
    assert subprocess.run([*wiki, "--check"], capture_output=True, text=True).returncode == 0
    makefile_text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "session-status:" in makefile_text
    assert "PROJECT_STATUS_SCRIPT ?= scripts/meta/project_status.py" in makefile_text
    assert "$(PROJECT_STATUS_SCRIPT) --repo-root ." in makefile_text
    assert "session-finish:" in makefile_text
    assert "session-close:" in makefile_text
    assert "surface-up:" in makefile_text
    assert "surface-preview:" in makefile_text
    assert "surface-audit:" in makefile_text
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
    assert "SESSION_GOAL is required" in makefile_text
    assert "SESSION_PHASE is required" in makefile_text
    assert "SESSION_CLAIM_TYPE ?= program" in makefile_text
    assert "ALLOW_UNPLANNED ?=" in makefile_text
    assert makefile_text.count("$(if $(ALLOW_UNPLANNED),--allow-unplanned,)") == 3
    assert '--claim-type "$(SESSION_CLAIM_TYPE)"' in makefile_text
    assert "--parent-scope" in makefile_text
    assert "--write-path" in makefile_text
    assert "WORKTREE_DISPOSITION ?= merged" in makefile_text
    assert "WORKTREE_REPO_ROOT ?=" in makefile_text
    assert "SESSION_WORK_GRAPH ?=" in makefile_text
    assert "SESSION_WORK_UNIT_ID ?=" in makefile_text
    assert '--work-graph "$(SESSION_WORK_GRAPH)"' in makefile_text
    assert '--work-unit-id "$(SESSION_WORK_UNIT_ID)"' in makefile_text
    assert '--disposition "$(WORKTREE_DISPOSITION)"' in makefile_text
    assert "$(filter 1 true yes,$(WORKTREE_ALLOW_DISCARD_UNIQUE))" in makefile_text
    assert "WORKTREE_MERGE_COMMIT ?=" in makefile_text
    assert '$(if $(WORKTREE_MERGE_COMMIT),--merge-commit "$(WORKTREE_MERGE_COMMIT)",)' in makefile_text
    assert '$(if $(WORKTREE_MERGE_COMMIT),WORKTREE_MERGE_COMMIT="$(WORKTREE_MERGE_COMMIT)",)' in makefile_text
    assert "scripts/meta/claim_bootstrap.py --request-json" in makefile_text
    maintenance_with_plan = subprocess.run(
        ["make", "maintenance-worktree", "PLAN=123"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert maintenance_with_plan.returncode != 0
    assert "only for explicitly unplanned light maintenance" in (
        maintenance_with_plan.stdout + maintenance_with_plan.stderr
    )
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
    assert file_context_result.returncode == 0, file_context_result.stdout + file_context_result.stderr
    authority_help = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts" / "meta" / "validate_doc_authority.py"),
            "--help",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert authority_help.returncode == 0, authority_help.stdout + authority_help.stderr


def test_installed_make_denies_incomplete_plan_before_lane_mutation(tmp_path: Path) -> None:
    """The real installed operator entrypoint must stop before claim or Git mutation."""

    _write_minimal_claude(tmp_path)
    installed = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--strict-governed",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    config_path = tmp_path / "meta-process.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["meta_process"]["plans"]["integrity"] = {
        "mode": "enforce",
        "contract_version": "1.0.0",
        "minimum_plan_number": 1,
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    plan_path = tmp_path / "docs" / "plans" / "1_incomplete.md"
    plan_path.write_text("# Incomplete installed plan\n", encoding="utf-8")

    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "install incomplete governed plan"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    scope = f"pi02-denied-{tmp_path.name}"
    worktree_dir = tmp_path / "worktrees"
    claim_path = Path.home() / ".claude" / "coordination" / "claims" / f"codex_fixture_{scope}.yaml"
    assert not claim_path.exists()
    environment = os.environ.copy()
    environment["CODEX_THREAD_ID"] = f"pi02-installed-{tmp_path.name}"

    denied = subprocess.run(
        [
            "make",
            "worktree",
            f"BRANCH={scope}",
            "TASK=Attempt incomplete installed plan",
            "SESSION_GOAL=Prove installed planning admission",
            "SESSION_PHASE=Attempt denied lane start",
            "WORKTREE_AGENT=codex",
            "WORKTREE_PROJECT=fixture",
            "PLAN_PROJECT=fixture",
            "PLAN=1",
            "PLAN_READINESS_COMMAND=python not-reached.py",
            f"WORKTREE_DIR={worktree_dir}",
            "SESSION_WRITE_PATHS=src/feature.py",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert denied.returncode != 0
    assert "missing_epistemic_frontier" in denied.stderr
    assert not claim_path.exists()
    assert not worktree_dir.exists()
    branches = subprocess.run(
        ["git", "branch", "--list", scope],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert branches.stdout.strip() == ""


def _installed_planning_make_fixture(tmp_path: Path) -> tuple[dict[str, str], str]:
    """Install and commit one observed plan lane that can exercise the real Make entrypoint."""

    _write_minimal_claude(tmp_path)
    installed = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--strict-governed",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    config_path = tmp_path / "meta-process.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["meta_process"]["plans"]["integrity"] = {
        "mode": "observe",
        "contract_version": "1.0.0",
        "minimum_plan_number": 1,
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (tmp_path / "docs/plans/1_observed.md").write_text(
        "# Incomplete observed consumer plan\n",
        encoding="utf-8",
    )
    graph_path = tmp_path / "docs/plans/1_observed_work_graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "id": "pi02-installed",
                        "status": "ready",
                        "readiness": {
                            "status": "ready",
                            "required_approval_types": [],
                            "approvals": [],
                            "failed_guards": [],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    query_path = tmp_path / "plan_graph_fixture.py"
    query_path.write_text(
        "import json\n"
        "print(json.dumps({"
        "'schema_version': '1.0.0', "
        "'qualified_plan_id': 'fixture#1', "
        f"'graph_revision': '{'a' * 64}', "
        "'decision': 'ready', 'blocker_ids': [], 'evidence_refs': ['fixture'], "
        "'reason': 'installed fixture ready', 'error_code': None}))\n",
        encoding="utf-8",
    )
    (tmp_path / "fail_session.py").write_text(
        "raise SystemExit('injected session-start failure')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "installed planning fixture"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    isolated_home = tmp_path / "operator-home"
    isolated_home.mkdir()
    remote = tmp_path.parent / f"{tmp_path.name}-origin.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "push", str(remote), "main"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:fixture/fixture.git"],
        cwd=tmp_path,
        check=True,
    )
    fake_ssh = isolated_home / "fixture-ssh"
    fake_ssh.write_text(
        f"#!/bin/sh\nexec git-upload-pack {str(remote)!r}\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    provider = isolated_home / "repository-authority-provider.py"
    provider.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "response = dict(request)\n"
        "response.update(allowed=True, project_id='fixture', default_branch='main', "
        "mutation_authority='normal_push')\n"
        "print(json.dumps(response, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    provider.chmod(0o700)
    provider_config = isolated_home / ".config/enforced-planning/repository-authority-provider-v1.json"
    provider_config.parent.mkdir(parents=True)
    provider_config.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "provider_path": str(provider),
                "provider_sha256": hashlib.sha256(provider.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    provider_config.chmod(0o600)
    environment = os.environ.copy()
    environment["HOME"] = str(isolated_home)
    environment["PYTHON"] = sys.executable
    environment["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path and "site-packages" in path)
    environment["CODEX_THREAD_ID"] = f"installed-{tmp_path.name}"
    environment["ENFORCED_PLANNING_LOCK_DIR"] = str(
        tmp_path.parent / f"{tmp_path.name}-tracker-locks"
    )
    environment["GIT_SSH_COMMAND"] = str(fake_ssh)
    environment.pop("CLAUDE_SESSION_ID", None)
    environment.pop("OPENCLAW_SESSION_ID", None)
    environment.pop("OPENCLAW_RUN_ID", None)
    return environment, revision


def _installed_worktree_make_args(tmp_path: Path, *, scope: str) -> list[str]:
    """Return the exact installed Make invocation for the revision-custody vertical."""

    return [
        "make",
        "worktree",
        f"PYTHON={sys.executable}",
        f"BRANCH={scope}",
        "TASK=Exercise installed revision custody",
        "SESSION_GOAL=Prove Installed Revision Custody",
        "SESSION_PHASE=Open exact governed lane",
        "WORKTREE_AGENT=codex",
        "WORKTREE_PROJECT=fixture",
        "PLAN_PROJECT=fixture",
        "PLAN=1",
        f"WORKTREE_DIR={tmp_path / 'worktrees'}",
        "SESSION_WRITE_PATHS=src/feature.py",
        "SESSION_WORK_GRAPH=docs/plans/1_observed_work_graph.json",
        "SESSION_WORK_UNIT_ID=pi02-installed",
        f"PLAN_READINESS_COMMAND={sys.executable} {tmp_path / 'plan_graph_fixture.py'}",
    ]


def test_installed_maintenance_bootstrap_denies_then_narrows_and_closes(
    tmp_path: Path,
) -> None:
    """One generated consumer completes the public bootstrap recovery journey."""

    environment, _revision = _installed_planning_make_fixture(tmp_path)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    scope = f"plan132-installed-{tmp_path.name}"
    worktrees = tmp_path / "worktrees"
    created = subprocess.run(
        [
            "make",
            "maintenance-worktree",
            f"PYTHON={sys.executable}",
            f"BRANCH={scope}",
            "TASK=Exercise installed broad-claim narrowing",
            "WORKTREE_AGENT=codex",
            "WORKTREE_PROJECT=fixture",
            f"WORKTREE_DIR={worktrees}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    assert "canonical lock unavailable" not in created.stderr
    assert not ((tmp_path / "CLAUDE.md").stat().st_mode & stat.S_IWUSR)
    lock_status = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts/meta/canonical_lock.py"),
            "--verify",
            str(tmp_path),
            "--json",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert lock_status.returncode == 0, lock_status.stdout + lock_status.stderr
    assert json.loads(lock_status.stdout)["verdict"] == "locked"

    worktree = worktrees / scope
    claims_dir = Path(environment["HOME"]) / ".claude" / "coordination" / "claims"
    receipt_path = claims_dir.parent / "receipts" / "installed-prewrite-receipts.jsonl"
    payload = json.dumps(
        {
            "session_id": environment["CODEX_THREAD_ID"],
            "hook_event_name": "PreToolUse",
            "cwd": str(worktree),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": (
                    f"*** Begin Patch\n*** Update File: {worktree / 'CLAUDE.md'}"
                    "\n@@\n-old\n+new\n*** End Patch"
                )
            },
        }
    )
    gate_adapter = "\n".join(
        [
            "import json, sys",
            "from pathlib import Path",
            "from enforced_planning.prewrite_claim_fast import evaluate_prewrite_fast, projection_path_for",
            "claims_dir = Path(sys.argv[1])",
            "result = evaluate_prewrite_fast(json.load(sys.stdin), client='codex', mode='enforce', "
            "claims_dir=claims_dir, projection_path=projection_path_for(claims_dir), "
            "receipt_path=Path(sys.argv[2]))",
            "print(json.dumps(result, sort_keys=True))",
            "raise SystemExit(0 if result['decision'] == 'allow' else 1)",
        ]
    )
    gate_command = [
        sys.executable,
        "-c",
        gate_adapter,
        str(claims_dir),
        str(receipt_path),
    ]
    denied = subprocess.run(
        gate_command,
        cwd=worktree,
        env=environment,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert denied.returncode == 1, denied.stdout + denied.stderr
    assert denied.stdout, denied.stderr
    assert json.loads(denied.stdout)["reason_code"] == "no_exact_claim"

    narrowed = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts" / "meta" / "session_narrow.py"),
            "--agent",
            "codex",
            "--project",
            "fixture",
            "--scope",
            scope,
            "--session-id",
            f"codex:{environment['CODEX_THREAD_ID']}",
            "--write-path",
            "CLAUDE.md",
            "--json",
        ],
        cwd=worktree,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert narrowed.returncode == 0, narrowed.stdout + narrowed.stderr
    assert json.loads(narrowed.stdout)["new_write_paths"] == ["CLAUDE.md"]

    admitted = subprocess.run(
        gate_command,
        cwd=worktree,
        env=environment,
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert admitted.returncode == 0, admitted.stdout + admitted.stderr
    assert json.loads(admitted.stdout)["reason_code"] == "exact_live_claim"

    closed = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts" / "meta" / "session_close.py"),
            "--agent",
            "codex",
            "--project",
            "fixture",
            "--scope",
            scope,
            "--worktree-path",
            str(worktree),
            "--branch",
            scope,
            "--json",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert closed.returncode == 0, closed.stdout + closed.stderr
    close_payload = json.loads(closed.stdout)
    assert close_payload["disposition"] == "merged"
    assert close_payload["released"] is True


def test_installed_make_retains_one_revision_across_claim_worktree_and_tracker(
    tmp_path: Path,
) -> None:
    """The authentic installed entrypoint must retain exactly one start commit end to end."""

    environment, revision = _installed_planning_make_fixture(tmp_path)
    scope = f"pi02-success-{tmp_path.name}"
    created = subprocess.run(
        _installed_worktree_make_args(tmp_path, scope=scope),
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    assert '"planning_integrity"' in created.stdout
    assert "missing_epistemic_frontier" in created.stdout
    claim_path = Path(environment["HOME"]) / ".claude/coordination/claims" / f"codex_fixture_{scope}.yaml"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    tracker_paths = list((Path(environment["HOME"]) / ".claude/coordination/sessions/fixture").glob("*.yaml"))
    assert len(tracker_paths) == 1
    tracker = yaml.safe_load(tracker_paths[0].read_text(encoding="utf-8"))
    worktree = tmp_path / "worktrees" / scope
    worktree_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert claim["schema_version"] == 6
    assert "broad_scope_mode" not in claim
    assert claim["start_revision"] == revision
    assert tracker["schema_version"] == 2
    assert tracker["claim"]["start_revision"] == revision
    assert worktree_revision == revision

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", scope],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    released = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts/meta/check_coordination_claims.py"),
            "--release",
            "--agent",
            "codex",
            "--project",
            "fixture",
            "--scope",
            scope,
            "--require-current-session",
            "--expected-start-revision",
            revision,
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert released.returncode == 0, released.stdout + released.stderr


def test_installed_make_session_failure_preserves_preexisting_branch(
    tmp_path: Path,
) -> None:
    """Rollback removes only state this invocation created and releases exact claim custody."""

    environment, revision = _installed_planning_make_fixture(tmp_path)
    scope = f"pi02-existing-{tmp_path.name}"
    subprocess.run(["git", "branch", scope, revision], cwd=tmp_path, check=True)
    failed = subprocess.run(
        [
            *_installed_worktree_make_args(tmp_path, scope=scope),
            f"WORKTREE_SESSION_START_SCRIPT={tmp_path / 'fail_session.py'}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode != 0
    branch_revision = subprocess.run(
        ["git", "rev-parse", scope],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    claim_path = Path(environment["HOME"]) / ".claude/coordination/claims" / f"codex_fixture_{scope}.yaml"
    assert branch_revision == revision
    assert not (tmp_path / "worktrees" / scope).exists()
    assert not claim_path.exists()


def test_installed_make_session_failure_preserves_branch_created_during_helper_race(
    tmp_path: Path,
) -> None:
    """Rollback trusts the helper receipt when a branch appears after claim admission."""

    environment, revision = _installed_planning_make_fixture(tmp_path)
    scope = f"pi02-raced-{tmp_path.name}"
    wrapper = tmp_path / "race_then_create_worktree.py"
    wrapper.write_text(
        "import os, subprocess, sys\n"
        "args = sys.argv[1:]\n"
        "def value(flag): return args[args.index(flag) + 1]\n"
        "subprocess.run(['git', '-C', value('--repo-root'), 'branch', value('--branch'), "
        "value('--start-point')], check=True)\n"
        "raise SystemExit(subprocess.call([sys.executable, os.environ['REAL_WORKTREE_CREATE'], "
        "*args]))\n",
        encoding="utf-8",
    )
    environment["REAL_WORKTREE_CREATE"] = str(tmp_path / "scripts/meta/worktree-coordination/create_worktree.py")
    failed = subprocess.run(
        [
            *_installed_worktree_make_args(tmp_path, scope=scope),
            f"WORKTREE_CREATE_SCRIPT={wrapper}",
            f"WORKTREE_SESSION_START_SCRIPT={tmp_path / 'fail_session.py'}",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode != 0
    branch_revision = subprocess.run(
        ["git", "rev-parse", scope],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    claim_path = Path(environment["HOME"]) / ".claude/coordination/claims" / f"codex_fixture_{scope}.yaml"
    assert branch_revision == revision
    assert not (tmp_path / "worktrees" / scope).exists()
    assert not claim_path.exists()


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
    assert drifted_path.read_text(encoding="utf-8") == CANONICAL_FILE_CONTEXT.read_text(encoding="utf-8")


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


def test_full_install_coordination_hook_has_clean_import_closure(tmp_path: Path) -> None:
    """Default full mode must install every direct coordination-hook dependency."""

    _write_minimal_claude(tmp_path)
    installed = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert (tmp_path / "scripts" / "hook_receipts.py").is_file()
    assert (tmp_path / "scripts" / "meta" / "hook_receipts.py").is_file()
    assert (tmp_path / "enforced_planning" / "mailbox_execution_identity.py").is_file()

    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(tmp_path / 'scripts')!r}); "
                "import coordination_hook"
            ),
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr


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


def test_session_close_make_target_forwards_exact_squash_merge_commit(tmp_path: Path) -> None:
    """The sanctioned Make closeout wrapper preserves exact squash evidence."""
    captured_argv = tmp_path / "session-close-argv.json"
    recorder = tmp_path / "record_session_close.py"
    recorder.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CAPTURED_ARGV']).write_text(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    merge_commit = "a" * 40

    result = subprocess.run(
        [
            "make",
            "-f",
            str(PROJECT_META_ROOT / "Makefile"),
            "session-close",
            "BRANCH=plan-234-squash-closeout",
            "WORKTREE_AGENT=codex",
            "WORKTREE_PROJECT=fixture",
            f"WORKTREE_DIR={tmp_path / 'worktrees'}",
            f"WORKTREE_SESSION_CLOSE_SCRIPT={recorder}",
            f"WORKTREE_MERGE_COMMIT={merge_commit}",
        ],
        cwd=tmp_path,
        capture_output=True,
        env={**os.environ, "CAPTURED_ARGV": str(captured_argv)},
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(captured_argv.read_text(encoding="utf-8")) == [
        "--agent",
        "codex",
        "--project",
        "fixture",
        "--scope",
        "plan-234-squash-closeout",
        "--worktree-path",
        str(tmp_path / "worktrees" / "plan-234-squash-closeout"),
        "--branch",
        "plan-234-squash-closeout",
        "--disposition",
        "merged",
        "--disposition-reason",
        "",
        "--recovery-ref",
        "",
        "--merge-commit",
        merge_commit,
    ]


def test_worktree_remove_make_target_forwards_exact_squash_merge_commit(tmp_path: Path) -> None:
    """The compatibility worktree-remove wrapper cannot drop squash evidence."""
    source_makefile = (PROJECT_META_ROOT / "Makefile").read_text(encoding="utf-8")
    assert '$(if $(WORKTREE_MERGE_COMMIT),WORKTREE_MERGE_COMMIT="$(WORKTREE_MERGE_COMMIT)",)' in source_makefile
    (tmp_path / "Makefile").write_text(
        source_makefile,
        encoding="utf-8",
    )
    captured_argv = tmp_path / "session-close-argv.json"
    recorder = tmp_path / "record_session_close.py"
    recorder.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CAPTURED_ARGV']).write_text(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    merge_commit = "b" * 40

    result = subprocess.run(
        [
            "make",
            "worktree-remove",
            "BRANCH=plan-234-squash-closeout",
            "WORKTREE_AGENT=codex",
            "WORKTREE_PROJECT=fixture",
            f"WORKTREE_DIR={tmp_path / 'worktrees'}",
            f"WORKTREE_SESSION_CLOSE_SCRIPT={recorder}",
            f"WORKTREE_MERGE_COMMIT={merge_commit}",
        ],
        cwd=tmp_path,
        capture_output=True,
        env={**os.environ, "CAPTURED_ARGV": str(captured_argv)},
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "--merge-commit" in json.loads(captured_argv.read_text(encoding="utf-8"))
    assert merge_commit in json.loads(captured_argv.read_text(encoding="utf-8"))


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
    assert (
        "WORKTREE_CLAIMS_SCRIPT := scripts/meta/worktree-coordination/../check_coordination_claims.py" in makefile_text
    )
    assert "WORKTREE_SESSION_START_SCRIPT := scripts/meta/worktree-coordination/../session_start.py" in makefile_text
    assert "WORKTREE_START_POINT ?= HEAD" in makefile_text
    assert "--print-canonical-project" in makefile_text
    assert "SESSION_CLAIM_TYPE ?= program" in makefile_text
    assert (
        "WORKTREE_PLAN_READINESS_SCRIPT := scripts/meta/worktree-coordination/../check_plan_readiness.py"
    ) in makefile_text
    assert "PLAN_READINESS_COMMAND ?=" in makefile_text
    assert "PLAN_RESUME ?=" in makefile_text
    assert '--qualified-plan-id "$(PLAN_PROJECT)#$(PLAN)"' in makefile_text
    assert '--repo-root "$(WORKTREE_REPO_ROOT)"' in makefile_text
    assert '--start-point "$(WORKTREE_START_REVISION)"' in makefile_text
    assert "WORKTREE_START_REVISION :=" in makefile_text
    assert "--require-new" in makefile_text
    assert "--claim-start-revision" in makefile_text
    assert "--require-current-session" in makefile_text
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


def test_installed_worktree_surface_preserves_external_plan_authority(tmp_path: Path) -> None:
    """Every installed bootstrap consumer receives the same two-repository contract."""

    _write_minimal_claude(tmp_path)
    (tmp_path / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")
    result = _run("--repo-root", str(tmp_path), "--write", "--worktree-only", "--json", cwd=PROJECT_META_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    makefile = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "PLAN_REPO_ROOT ?=" in makefile
    assert "PLAN_START_POINT ?=" in makefile
    assert makefile.count('--plan-repo-root "$(PLAN_REPO_ROOT)"') == 4
    assert makefile.count('--plan-start-point "$(PLAN_START_POINT)"') == 4
    for relative in (
        "enforced_planning/coordination_claims.py",
        "enforced_planning/plan_readiness.py",
        "enforced_planning/outcome_admission.py",
        "enforced_planning/session_contracts.py",
        "enforced_planning/session_lifecycle.py",
    ):
        assert (tmp_path / relative).read_bytes() == (PROJECT_META_ROOT / relative).read_bytes()
    for name in ("session_start.py", "check_plan_readiness.py"):
        installed = tmp_path / "scripts/meta" / name
        assert installed.read_bytes() == (PROJECT_META_ROOT / "scripts" / name).read_bytes()
        help_result = subprocess.run(
            [sys.executable, str(installed), "--help"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stderr
        assert "--plan-repo-root" in help_result.stdout
        assert "--plan-start-point" in help_result.stdout


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
    assert not (tmp_path / "enforced_planning" / "__init__.py").read_bytes().endswith(b"\n\n")
    assert sorted(payload["actions"]) == sorted(
            [
                "install:contracts/pr-review-signoff.schema.json",
                "install:enforced_planning/__init__.py",
                "install:enforced_planning/artifact_creation.py",
                "install:enforced_planning/blocker_policy.py",
            "install:enforced_planning/concern_routing.py",
            "install:enforced_planning/claim_mutation_receipts.py",
            "install:enforced_planning/claim_bootstrap.py",
            "install:enforced_planning/repository_authority.py",
            "install:enforced_planning/client_session_metadata.py",
            "install:enforced_planning/coordination_claims.py",
            "install:enforced_planning/concurrent_writers.py",
            "install:enforced_planning/mailbox_execution_identity.py",
            "install:enforced_planning/coordination_messages.py",
            "install:enforced_planning/outcome_admission.py",
            "install:enforced_planning/outcome_continuation.py",
            "install:enforced_planning/outcome_portfolio.py",
            "install:enforced_planning/outcome_selection.py",
                "install:enforced_planning/prewrite_claim_fast.py",
                "install:enforced_planning/integration_authority.py",
                "install:enforced_planning/pr_review_signoff.py",
            "install:enforced_planning/prewrite_claim_projection.py",
            "install:enforced_planning/plan_readiness.py",
            "install:enforced_planning/plan_close.py",
            "install:enforced_planning/doc_authority.py",
            "install:enforced_planning/file_context.py",
            "install:enforced_planning/notebook_registry_validation.py",
            "install:enforced_planning/plan_validation.py",
            "install:enforced_planning/push_safety.py",
            "install:enforced_planning/repository_status.py",
                "install:enforced_planning/session_contracts.py",
                "install:enforced_planning/session_continuity.py",
                "install:enforced_planning/session_lifecycle.py",
                "install:enforced_planning/session_process_fencing.py",
                "install:enforced_planning/session_target.py",
            "install:enforced_planning/surface_runtime.py",
            "install:enforced_planning/verification_batch.py",
            "install:enforced_planning/worktree_lifecycle.yaml",
            "install:enforced_planning/worktree_paths.py",
            "install:hooks/pre-push",
            "install:scripts/meta/check_coordination_claims.py",
            "install:scripts/meta/claim_bootstrap.py",
            "install:scripts/meta/canonical_lock.py",
            "install:scripts/refresh_prewrite_claim_projection.py",
            "install:scripts/artifact_creation.py",
            "install:scripts/meta/check_push_safety.py",
            "install:scripts/meta/check_plan_readiness.py",
            "install:scripts/meta/plan_close.py",
            "install:scripts/meta/session_close.py",
            "install:scripts/meta/session_continuity.py",
            "install:scripts/meta/session_end.py",
            "install:scripts/meta/session_finish.py",
            "install:scripts/meta/session_heartbeat.py",
                "install:scripts/meta/session_narrow.py",
                "install:scripts/meta/apply_blocker_disposition.py",
            "install:scripts/meta/session_start.py",
            "install:scripts/meta/session_status.py",
            "install:scripts/meta/project_status.py",
            "install:scripts/meta/pr_auto.py",
            "install:scripts/meta/pr_review_signoff_runtime.py",
            "install:scripts/meta/session_resume.py",
            "install:scripts/meta/surface_runtime.py",
            "install:scripts/meta/validate_doc_authority.py",
            "install:scripts/meta/verification_batch.py",
            "install:scripts/coordination_inbox.py",
            "install:scripts/coordination_messages.py",
            "install:scripts/coordination_operator_status.py",
            "install:scripts/meta/coordination_inbox.py",
            "install:scripts/meta/coordination_messages.py",
            "install:scripts/meta/coordination_operator_status.py",
            "install:scripts/meta/worktree-coordination/create_worktree.py",
            "install:scripts/meta/worktree-coordination/create_publish_worktree.py",
            "install:scripts/meta/worktree-coordination/create_review_claim.py",
            "install:scripts/meta/worktree-coordination/finish_pr.py",
            "install:scripts/meta/worktree-coordination/integration_authority.py",
            "install:scripts/meta/worktree-coordination/raise_concern.py",
            "install:scripts/meta/worktree-coordination/safe_worktree_remove.py",
            "sync:.claude/hooks/worktree-coordination/check-hook-enabled.sh",
            "sync:.claude/hooks/worktree-coordination/enforce-make-merge.sh",
            "sync:.claude/settings.json",
            "sync:.codex/hooks/enforce-make-merge.sh",
            "sync:.codex/hooks.json",
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
    readiness_help = subprocess.run(
        [sys.executable, str(installed_readiness_cli), "--help"],
        cwd=str(tmp_path),
        text=True,
        capture_output=True,
        check=False,
    )
    assert readiness_help.returncode == 0, readiness_help.stdout + readiness_help.stderr
    assert "PLAN_RESUME ?=" in (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert (tmp_path / "hooks" / "pre-push").exists()
    assert os.access(tmp_path / "hooks" / "pre-push", os.X_OK)
    assert (tmp_path / "scripts" / "meta" / "session_start.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_heartbeat.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_status.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_continuity.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_resume.py").exists()
    assert (tmp_path / "scripts" / "meta" / "surface_runtime.py").exists()
    assert (tmp_path / "scripts" / "meta" / "verification_batch.py").exists()
    assert (tmp_path / "scripts" / "coordination_inbox.py").exists()
    assert (tmp_path / "scripts" / "coordination_messages.py").exists()
    assert (tmp_path / "scripts" / "coordination_operator_status.py").exists()
    assert (tmp_path / "scripts" / "meta" / "coordination_messages.py").exists()
    assert (tmp_path / "scripts" / "meta" / "coordination_operator_status.py").exists()
    assert (tmp_path / "enforced_planning" / "client_session_metadata.py").exists()
    assert (tmp_path / "enforced_planning" / "coordination_messages.py").exists()
    assert (tmp_path / "enforced_planning" / "plan_readiness.py").exists()
    assert (tmp_path / "enforced_planning" / "plan_close.py").exists()
    assert (tmp_path / "scripts" / "meta" / "check_plan_readiness.py").exists()
    assert (tmp_path / "scripts" / "meta" / "plan_close.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_finish.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_close.py").exists()
    assert (tmp_path / "enforced_planning" / "session_contracts.py").exists()
    assert (tmp_path / "enforced_planning" / "session_lifecycle.py").exists()
    assert (tmp_path / "enforced_planning" / "surface_runtime.py").exists()
    assert (tmp_path / "enforced_planning" / "verification_batch.py").exists()
    assert (tmp_path / "enforced_planning" / "worktree_lifecycle.yaml").exists()
    assert (tmp_path / "enforced_planning" / "worktree_paths.py").exists()
    for installed_cli in (
        tmp_path / "scripts" / "coordination_operator_status.py",
        tmp_path / "scripts" / "meta" / "coordination_operator_status.py",
        tmp_path / "scripts" / "meta" / "session_status.py",
    ):
        help_result = subprocess.run(
            [sys.executable, str(installed_cli), "--help"],
            cwd=str(tmp_path),
            text=True,
            capture_output=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stdout + help_result.stderr
    assert (tmp_path / "scripts" / "meta" / "worktree-coordination" / "create_worktree.py").exists()
    assert (tmp_path / "scripts" / "meta" / "worktree-coordination" / "create_publish_worktree.py").exists()
    assert (tmp_path / "scripts" / "meta" / "worktree-coordination" / "finish_pr.py").exists()
    assert (
        tmp_path / "scripts" / "meta" / "worktree-coordination" / "integration_authority.py"
    ).exists()
    assert (tmp_path / "scripts" / "meta" / "worktree-coordination" / "safe_worktree_remove.py").exists()
    assert (tmp_path / "enforced_planning" / "pr_review_signoff.py").exists()
    assert (tmp_path / "enforced_planning" / "integration_authority.py").exists()
    assert (tmp_path / "scripts" / "meta" / "pr_review_signoff_runtime.py").exists()
    assert (tmp_path / "contracts" / "pr-review-signoff.schema.json").exists()
    makefile_text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "worktree:" in makefile_text
    assert "worktree-list:" in makefile_text
    assert "worktree-remove:" in makefile_text
    assert "finish:" in makefile_text
    assert 'REVIEW_SPEC=/absolute/review-spec.json' in makefile_text
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

    surface_help = subprocess.run(
        [sys.executable, str(tmp_path / "scripts" / "meta" / "surface_runtime.py"), "--help"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert surface_help.returncode == 0, surface_help.stdout + surface_help.stderr
    assert "revision-bound canonical and preview" in surface_help.stdout

    safe_remove_help = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts" / "meta" / "worktree-coordination" / "safe_worktree_remove.py"),
            "--help",
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert safe_remove_help.returncode == 0, safe_remove_help.stdout + safe_remove_help.stderr

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
            "--select=E9,F63,F7,F82",
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


def test_worktree_rollout_accepts_equivalent_absolute_git_hook_path(
    tmp_path: Path,
) -> None:
    """An absolute path to the installed hooks directory is not a custom stack."""

    _write_minimal_claude(tmp_path)
    (tmp_path / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "--local", "core.hooksPath", str(tmp_path / "hooks"))

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
    assert payload["blockers"] == []
    assert "configure:git.core.hooksPath=hooks" not in payload["applied_actions"]
    assert _git(tmp_path, "config", "--local", "--get", "core.hooksPath") == str(tmp_path / "hooks")
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
    assert payload["blockers"] == ["core.hooksPath is already '.custom-hooks'; refusing to replace custom Git hooks"]
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


def test_source_make_heartbeat_executes_canonical_lifecycle_before_stale_mirror(
    tmp_path: Path,
) -> None:
    """The real Make target must consume the canonical source adapter when present."""

    canonical = tmp_path / "scripts" / "session_heartbeat.py"
    stale = tmp_path / "scripts" / "meta" / "session_heartbeat.py"
    (stale.parent / "worktree-coordination").mkdir(parents=True)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(
        "from pathlib import Path\nPath('canonical-lifecycle-ran').write_text('canonical\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    stale.write_text(
        "from pathlib import Path\n"
        "Path('stale-lifecycle-ran').write_text('stale\\n', encoding='utf-8')\n"
        "raise SystemExit(23)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "make",
            "-f",
            str(PROJECT_META_ROOT / "Makefile"),
            "session-heartbeat",
            "BRANCH=plan123-make-adoption",
            "WORKTREE_AGENT=codex",
            "WORKTREE_PROJECT=enforced-planning",
            f"WORKTREE_REPO_ROOT={tmp_path}",
            f"WORKTREE_DIR={tmp_path / 'worktrees'}",
            f"PYTHON={sys.executable}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "canonical-lifecycle-ran").read_text(encoding="utf-8") == "canonical\n"
    assert not (tmp_path / "stale-lifecycle-ran").exists()


def test_source_make_start_executes_canonical_lifecycle_before_stale_mirror(
    tmp_path: Path,
) -> None:
    """The exact source start target must not regress to its generated mirror."""

    canonical = tmp_path / "scripts" / "session_start.py"
    stale = tmp_path / "scripts" / "meta" / "session_start.py"
    (stale.parent / "worktree-coordination").mkdir(parents=True)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(
        "from pathlib import Path\nPath('canonical-start-ran').write_text('canonical\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    stale.write_text(
        "from pathlib import Path\n"
        "Path('stale-start-ran').write_text('stale\\n', encoding='utf-8')\n"
        "raise SystemExit(24)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "make",
            "-f",
            str(PROJECT_META_ROOT / "Makefile"),
            "session-start",
            "BRANCH=plan123-make-start-adoption",
            "TASK=exercise canonical start",
            "SESSION_GOAL=exercise-canonical-start",
            "SESSION_PHASE=source Make integration",
            "WORKTREE_AGENT=codex",
            "WORKTREE_PROJECT=enforced-planning",
            f"WORKTREE_REPO_ROOT={tmp_path}",
            f"WORKTREE_DIR={tmp_path / 'worktrees'}",
            f"PYTHON={sys.executable}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "canonical-start-ran").read_text(encoding="utf-8") == "canonical\n"
    assert not (tmp_path / "stale-start-ran").exists()


def _write_consumer(root: Path, *, declares_framework: bool) -> None:
    """Create a minimal consumer, with or without a declared framework dependency."""

    dependency = (
        '  "enforced-planning @ git+https://example.invalid/enforced-planning.git@abc",\n' if declares_framework else ""
    )
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "consumer"\nversion = "0.1.0"\ndependencies = [\n{dependency}]\n',
        encoding="utf-8",
    )


def test_installed_dependency_stops_the_installer_re_vendoring(tmp_path: Path) -> None:
    """A consumer that declares the framework must not have the package copied back in.

    Without this, running the sanctioned installer or upgrader against a
    converted repository silently restores the vendored tree and undoes the
    conversion.
    """

    from enforced_planning.installed_framework import drop_vendored_package_files

    files = {
        "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
        "scripts/meta/session_start.py": "scripts/session_start.py",
    }

    _write_consumer(tmp_path, declares_framework=True)
    reduced = drop_vendored_package_files(files, tmp_path)
    assert reduced == {"scripts/meta/session_start.py": "scripts/session_start.py"}


def test_worktree_only_install_preserves_declared_framework_dependency(tmp_path: Path) -> None:
    """The AES bootstrap upgrade must not shadow its pinned installed package."""

    _write_minimal_claude(tmp_path)
    _write_consumer(tmp_path, declares_framework=True)
    (tmp_path / "Makefile").write_text("help:\n\t@echo hello\n", encoding="utf-8")
    declaration = (tmp_path / "pyproject.toml").read_bytes()
    result = _run("--repo-root", str(tmp_path), "--write", "--worktree-only", "--json", cwd=PROJECT_META_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert not (tmp_path / "enforced_planning").exists()
    assert (tmp_path / "scripts/meta/pr_review_signoff_runtime.py").is_file()
    assert (tmp_path / "scripts/meta/worktree-coordination/finish_pr.py").is_file()
    assert (tmp_path / "scripts/meta/worktree-coordination/integration_authority.py").is_file()
    assert "mode:installed-package" in payload["actions"]
    assert (tmp_path / "pyproject.toml").read_bytes() == declaration
    assert "PLAN_REPO_ROOT ?=" in (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert (tmp_path / "scripts/meta/session_start.py").read_bytes() == (
        PROJECT_META_ROOT / "scripts/session_start.py"
    ).read_bytes()
    shadow = tmp_path / "shadow" / "enforced_planning"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    help_result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "scripts/meta/worktree-coordination/finish_pr.py"),
            "--help",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(shadow.parent)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stdout + help_result.stderr
    repeated = _run("--repo-root", str(tmp_path), "--check", "--worktree-only", "--json", cwd=PROJECT_META_ROOT)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert json.loads(repeated.stdout)["drift_files"] == []


def test_vendored_consumer_keeps_receiving_the_package(tmp_path: Path) -> None:
    """A consumer that does not declare the framework keeps the existing behaviour."""

    from enforced_planning.installed_framework import drop_vendored_package_files

    files = {
        "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
        "scripts/meta/session_start.py": "scripts/session_start.py",
    }

    _write_consumer(tmp_path, declares_framework=False)
    assert drop_vendored_package_files(files, tmp_path) == files


def test_declaration_detection_handles_real_requirement_forms(tmp_path: Path) -> None:
    """Underscores, extras, markers, and optional groups all count as a declaration."""

    from enforced_planning.installed_framework import declares_installed_framework

    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "consumer"\n'
        'version = "0.1.0"\n'
        "dependencies = []\n"
        "[project.optional-dependencies]\n"
        "dev = [\"Enforced_Planning[extra] >=1.0 ; python_version >= '3.11'\"]\n",
        encoding="utf-8",
    )
    assert declares_installed_framework(tmp_path) is True


def test_missing_or_unparseable_pyproject_is_not_a_declaration(tmp_path: Path) -> None:
    """Absent or broken metadata must fall back to the vendoring behaviour."""

    from enforced_planning.installed_framework import declares_installed_framework

    assert declares_installed_framework(tmp_path) is False
    (tmp_path / "pyproject.toml").write_text("this is not toml [[[", encoding="utf-8")
    assert declares_installed_framework(tmp_path) is False


def test_live_v6_broad_claim_blocks_runtime_downgrade(tmp_path: Path) -> None:
    """An installer cannot remove schema or narrow support beneath a live broad lease."""

    from scripts import install_governed_repo

    repo = tmp_path / "repo"
    repo.mkdir()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_path = claims_dir / "codex_demo_lane.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 6,
                "agent": "codex",
                "projects": ["demo"],
                "scope": "lane",
                "intent": "exercise downgrade protection",
                "claim_type": "program",
                "plan_ref": "UNPLANNED",
                "write_paths": ["."],
                "repo_root": str(repo),
                "worktree_path": f"{repo}.bootstrap-no-mutation-authority",
                "target_worktree_path": str(repo),
                "branch": "lane",
                "session_id": "codex:runtime",
                "session_name": "runtime",
                "broader_goal": "Keep broad authority fail-closed",
                "status": "active",
                "broad_scope_mode": "bootstrap",
                "broad_scope_reason": "construct and narrow this fixture",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    compatible = install_governed_repo._claim_runtime_downgrade_blockers(
        repo,
        candidate_schema_version=6,
        session_narrow_available=True,
        claims_dir=claims_dir,
    )
    older = install_governed_repo._claim_runtime_downgrade_blockers(
        repo,
        candidate_schema_version=5,
        session_narrow_available=True,
        claims_dir=claims_dir,
    )
    missing_recovery = install_governed_repo._claim_runtime_downgrade_blockers(
        repo,
        candidate_schema_version=6,
        session_narrow_available=False,
        claims_dir=claims_dir,
    )

    assert compatible == []
    assert len(older) == 1 and "older than required schema 6" in older[0]
    assert len(missing_recovery) == 1 and "lacks scripts/session_narrow.py" in missing_recovery[0]


def test_every_claim_runtime_installer_profile_carries_session_narrow() -> None:
    """Full and bounded runtime rollouts must install the owner recovery adapter."""

    from scripts import install_governed_repo

    for manifest in (
        install_governed_repo.SYNC_SUPPORT_FILES,
        install_governed_repo.WORKTREE_ONLY_SYNC_SUPPORT_FILES,
        install_governed_repo.COORDINATION_MESSAGES_SHARED_FILES,
        install_governed_repo.CLAIM_PROJECTION_SHARED_FILES,
    ):
        assert manifest["scripts/meta/session_narrow.py"] == "scripts/session_narrow.py"
        assert manifest["scripts/meta/apply_blocker_disposition.py"] == (
            "scripts/apply_blocker_disposition.py"
        )


def test_outcome_completion_installs_only_with_stop_capable_profiles() -> None:
    """Selected-completion enforcement must not enter projection-only runtimes."""

    from scripts import install_governed_repo

    module = "enforced_planning/outcome_completion.py"
    wrapper = "scripts/meta/outcome_completion_hook.py"
    assert install_governed_repo.SYNC_SUPPORT_FILES[module] == module
    assert install_governed_repo.SYNC_SUPPORT_FILES[wrapper] == "scripts/outcome_completion_hook.py"
    assert install_governed_repo.COORDINATION_MESSAGES_SHARED_FILES[wrapper] == (
        "scripts/outcome_completion_hook.py"
    )
    assert install_governed_repo.COORDINATION_MESSAGES_LOCAL_PACKAGE_FILES[module] == module
    assert module not in install_governed_repo.WORKTREE_ONLY_SYNC_SUPPORT_FILES
    assert wrapper not in install_governed_repo.WORKTREE_ONLY_SYNC_SUPPORT_FILES
    assert module not in install_governed_repo.CLAIM_PROJECTION_LOCAL_PACKAGE_FILES
    assert wrapper not in install_governed_repo.CLAIM_PROJECTION_SHARED_FILES


def test_every_claim_runtime_installer_profile_carries_session_continuity() -> None:
    """Every installed claim runtime exposes the observe-only continuity CLI."""

    from scripts import install_governed_repo

    for shared_manifest, package_manifest in (
        (install_governed_repo.SYNC_SUPPORT_FILES, install_governed_repo.SYNC_SUPPORT_FILES),
        (
            install_governed_repo.WORKTREE_ONLY_SYNC_SUPPORT_FILES,
            install_governed_repo.WORKTREE_ONLY_SYNC_SUPPORT_FILES,
        ),
        (
            install_governed_repo.COORDINATION_MESSAGES_SHARED_FILES,
            install_governed_repo.COORDINATION_MESSAGES_LOCAL_PACKAGE_FILES,
        ),
        (
            install_governed_repo.CLAIM_PROJECTION_SHARED_FILES,
            install_governed_repo.CLAIM_PROJECTION_LOCAL_PACKAGE_FILES,
        ),
    ):
        assert shared_manifest["scripts/meta/session_continuity.py"] == "scripts/session_continuity.py"
        assert package_manifest["enforced_planning/session_continuity.py"] == (
            "enforced_planning/session_continuity.py"
        )


def test_installed_coordination_runtime_exposes_session_continuity_cli(tmp_path: Path) -> None:
    """A real bounded install must leave the one-shot continuity entrypoint runnable."""

    _prepare_mailbox_target(tmp_path)
    installed = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--coordination-messages-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    clean_env = dict(os.environ)
    clean_env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(tmp_path / "scripts/meta/session_continuity.py"), "--help"],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "--send-resume-offer" in result.stdout
    assert "--resume-offer-message-id" in result.stdout


def test_installed_blocker_command_applies_both_dispositions_without_duplicate_executor(
    tmp_path: Path,
) -> None:
    """The installed command, not only its source function, executes NPW-03 A/B."""

    from enforced_planning.blocker_policy import BlockerDecisionInputV1
    from tests.test_blocker_policy import (
        GRAPH_REF,
        SESSION_ID,
        _application_expected,
        _request,
        _unit,
        _write_application_claim,
        _write_graph,
    )

    _prepare_mailbox_target(tmp_path)
    installed = _run(
        "--repo-root",
        str(tmp_path),
        "--write",
        "--coordination-messages-only",
        "--json",
        cwd=PROJECT_META_ROOT,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr

    isolated_home = tmp_path.parent / f"{tmp_path.name}-operator-home"
    claims_dir = isolated_home / ".claude/coordination/claims"
    dirty_worktree = tmp_path / "dirty-worktree"
    dirty_worktree.mkdir()
    dirty_file = dirty_worktree / "pending.txt"
    dirty_file.write_text("preserve installed contribution\n", encoding="utf-8")
    graph_path, digest = _write_graph(
        tmp_path,
        [_unit("A", "blocked"), _unit("B", "ready")],
    )
    root = _write_application_claim(
        claims_dir,
        scope="goal-root",
        graph_path=GRAPH_REF,
        graph_sha256=digest,
        work_unit_id="B",
    )
    child = _write_application_claim(
        claims_dir,
        scope="goal-child",
        parent_scope="goal-root",
        graph_path=GRAPH_REF,
        graph_sha256=digest,
        work_unit_id="B",
    )
    unrelated = _write_application_claim(
        claims_dir,
        scope="unrelated-root",
        graph_path=None,
        graph_sha256=None,
        plan_ref="UNPLANNED",
        work_unit_id=None,
    )
    for claim_path in (root, child, unrelated):
        claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
        claim["repo_root"] = str(tmp_path)
        claim["worktree_path"] = str(dirty_worktree)
        claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")

    environment = os.environ.copy()
    environment["HOME"] = str(isolated_home)
    environment["PYTHONPATH"] = os.pathsep.join(
        path for path in sys.path if path and "site-packages" in path
    )
    environment["CODEX_THREAD_ID"] = SESSION_ID.removeprefix("codex:")
    environment["ENFORCED_PLANNING_LOCK_DIR"] = str(isolated_home / "tracker-locks")
    command = [
        sys.executable,
        str(tmp_path / "scripts/meta/apply_blocker_disposition.py"),
        "--agent",
        "codex",
        "--project",
        "enforced-planning",
        "--root-scope",
        "goal-root",
        "--session-id",
        SESSION_ID,
    ]

    input_path = tmp_path / "blocker-input.json"
    decision_path = tmp_path / "blocker-decision.json"

    def run_current_files() -> dict[str, object]:
        result = subprocess.run(
            [
                *command,
                "--input-json",
                str(input_path),
                "--decision-json",
                str(decision_path),
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    def invoke(decision_input: BlockerDecisionInputV1) -> dict[str, object]:
        expected = _application_expected(
            decision_input=decision_input,
            repository_root=tmp_path,
            claims_dir=claims_dir,
        )
        input_path.write_text(decision_input.model_dump_json(indent=2), encoding="utf-8")
        decision_path.write_text(expected.model_dump_json(indent=2), encoding="utf-8")
        return run_current_files()

    continued = invoke(
        BlockerDecisionInputV1(
            request_ref="installed-continue",
            request=_request(blocked_items=("A",)),
            work_graph_ref_path=GRAPH_REF,
            expected_work_graph_sha256=digest,
        )
    )
    assert continued["decision"] == "continue_ready_work"
    assert continued["result"] == "recorded_no_mutation"
    assert dirty_file.read_text(encoding="utf-8") == "preserve installed contribution\n"

    graph_path, blocked_digest = _write_graph(tmp_path, [_unit("A", "blocked")])
    assert graph_path.is_file()
    for claim_path in (root, child):
        claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
        claim["work_graph_sha256"] = blocked_digest
        claim["work_unit_id"] = "A"
        claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    retired = invoke(
        BlockerDecisionInputV1(
            request_ref="installed-terminal",
            request=_request(),
            work_graph_ref_path=GRAPH_REF,
            expected_work_graph_sha256=blocked_digest,
        )
    )
    assert retired["result"] == "applied"
    assert retired["affected_scopes"] == ["goal-child", "goal-root"]
    assert yaml.safe_load(root.read_text(encoding="utf-8"))["status"] == "session_ended"
    assert yaml.safe_load(child.read_text(encoding="utf-8"))["status"] == "session_ended"
    assert yaml.safe_load(unrelated.read_text(encoding="utf-8"))["status"] == "active"
    assert dirty_file.read_text(encoding="utf-8") == "preserve installed contribution\n"
    replay = run_current_files()
    assert replay["idempotent_replay"] is True
    assert replay["application_id"] == retired["application_id"]


def test_pr_auto_default_resolves_canonical_repo_from_linked_worktree(tmp_path: Path) -> None:
    """A branch-folder name must not replace the Git repository identity."""

    repo = tmp_path / "canonical-repository"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "fixture")

    worktree = tmp_path / "feature-branch-folder"
    _git(repo, "worktree", "add", "-b", "feature", str(worktree))
    assignment = next(
        line
        for line in (PROJECT_META_ROOT / "templates/Makefile.meta").read_text().splitlines()
        if line.startswith("PR_AUTO_EXPECTED_REPO ?=")
    )
    probe = worktree / "Probe.mk"
    probe.write_text(
        f"{assignment}\nprint-repo:\n\t@echo $(PR_AUTO_EXPECTED_REPO)\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["make", "-s", "-f", str(probe), "print-repo"],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "canonical-repository"
