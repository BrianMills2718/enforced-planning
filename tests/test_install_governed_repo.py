"""Tests for governed-repo installer/upgrader tooling."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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
    "scripts/check_required_reading.py",
    "scripts/meta/context_packet.py",
    "scripts/meta/docstring_wiki.py",
    "scripts/meta/hook_log.py",
    "scripts/meta/impact_obligations.py",
    "scripts/meta/relationship_context.py",
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
    assert "install:enforced_planning/docstring_wiki.py" in payload["actions"]
    assert "install:enforced_planning/notebook_registry_validation.py" in payload["actions"]
    assert "install:enforced_planning/plan_validation.py" in payload["actions"]
    assert "install:enforced_planning/push_safety.py" in payload["actions"]
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
    assert (tmp_path / "scripts" / "relationships.yaml").exists()
    assert (tmp_path / "docs" / "plans" / "CLAUDE.md").exists()
    assert (tmp_path / "docs" / "plans" / "TEMPLATE.md").exists()
    assert (tmp_path / "Makefile").exists()
    assert (tmp_path / "enforced_planning" / "__init__.py").exists()
    assert (tmp_path / "enforced_planning" / "agents_rendering.py").exists()
    assert (tmp_path / "enforced_planning" / "concern_routing.py").exists()
    assert (tmp_path / "enforced_planning" / "file_context.py").exists()
    assert (tmp_path / "enforced_planning" / "relationship_context.py").exists()
    assert (tmp_path / "enforced_planning" / "context_packet.py").exists()
    assert (tmp_path / "enforced_planning" / "impact_obligations.py").exists()
    assert (tmp_path / "enforced_planning" / "docstring_wiki.py").exists()
    assert (tmp_path / "enforced_planning" / "notebook_registry_validation.py").exists()
    assert (tmp_path / "enforced_planning" / "plan_validation.py").exists()
    assert (tmp_path / "enforced_planning" / "push_safety.py").exists()
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
    assert "session-finish:" in makefile_text
    assert "session-close:" in makefile_text
    assert "review-claim:" in makefile_text
    assert "raise-concern:" in makefile_text
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
    assert '--claim-type program' in makefile_text
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
    assert "append:Makefile.worktree" in payload["actions"]
    makefile_text = (tmp_path / "Makefile").read_text(encoding="utf-8")
    assert "help:" in makefile_text
    assert "worktree:" in makefile_text
    assert "# >>> META-PROCESS WORKTREE TARGETS >>>" in makefile_text
    assert "# <<< META-PROCESS WORKTREE TARGETS <<<" in makefile_text
    assert '$(MAKE) session-close BRANCH="$(BRANCH)"' in makefile_text


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
    assert "WORKTREE_PROJECT ?= $(notdir $(CURDIR))" in makefile_text
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
    assert sorted(payload["actions"]) == sorted(
        [
            "install:enforced_planning/__init__.py",
            "install:enforced_planning/concern_routing.py",
            "install:enforced_planning/coordination_claims.py",
            "install:enforced_planning/doc_authority.py",
            "install:enforced_planning/push_safety.py",
            "install:enforced_planning/session_contracts.py",
            "install:enforced_planning/session_lifecycle.py",
            "install:enforced_planning/worktree_lifecycle.yaml",
            "install:enforced_planning/worktree_paths.py",
            "install:scripts/meta/check_coordination_claims.py",
            "install:scripts/meta/check_push_safety.py",
            "install:scripts/meta/session_close.py",
            "install:scripts/meta/session_finish.py",
            "install:scripts/meta/session_heartbeat.py",
            "install:scripts/meta/session_start.py",
            "install:scripts/meta/session_status.py",
            "install:scripts/meta/worktree-coordination/create_worktree.py",
            "install:scripts/meta/worktree-coordination/create_publish_worktree.py",
            "install:scripts/meta/worktree-coordination/create_review_claim.py",
            "install:scripts/meta/worktree-coordination/raise_concern.py",
            "install:scripts/meta/worktree-coordination/safe_worktree_remove.py",
            "append:Makefile.worktree",
        ]
    )
    assert not (tmp_path / "scripts" / "relationships.yaml").exists()
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".claude" / "hooks" / "gate-edit.sh").exists()
    assert (tmp_path / "scripts" / "meta" / "check_coordination_claims.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_start.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_heartbeat.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_status.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_finish.py").exists()
    assert (tmp_path / "scripts" / "meta" / "session_close.py").exists()
    assert (tmp_path / "enforced_planning" / "session_contracts.py").exists()
    assert (tmp_path / "enforced_planning" / "session_lifecycle.py").exists()
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
