from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import (
    claim_bootstrap,
    prewrite_claim_fast,
    prewrite_claim_projection,
    session_target,
)


def _start_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "session_start_or_update",
        "agent": "codex",
        "project": "demo",
        "scope": "self-owned-scope",
        "intent": "create exact self ownership",
        "claim_type": "write",
        "repo_root": "/tmp/demo",
        "worktree_path": "/tmp/demo/worktrees/self-owned-scope",
        "branch": "self-owned-scope",
        "session_name": "create-exact-self-ownership",
        "broader_goal": "Create exact self ownership",
        "plan_ref": "UNPLANNED",
        "write_paths": ["src/owned.py"],
        "read_paths": [],
        "current_phase": "bootstrap",
        "next_action": "begin bounded work",
    }
    payload.update(updates)
    return payload


def _maintenance_payload(repo: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "maintenance_worktree",
        "agent": "codex",
        "project": repo.name,
        "scope": "fix/safe-lane",
        "repo_root": str(repo),
        "branch": "fix/safe-lane",
        "claim_type": "program",
    }
    payload.update(updates)
    return payload


def _goal_worktree_payload(repo: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "goal_worktree",
        "agent": "codex",
        "project": repo.name,
        "scope": "goal/owner-visible-outcome",
        "repo_root": str(repo),
        "branch": "goal/owner-visible-outcome",
        "claim_type": "program",
        "plan_ref": "goal:owner-visible-outcome",
        "broader_goal": "Deliver one owner-visible outcome",
        "current_phase": "first vertical",
        "next_action": "exercise the owner-visible boundary",
        "write_paths": ["src/vertical.py", "tests/test_vertical.py"],
    }
    payload.update(updates)
    return payload


def _delegated_maintenance_payload(repo: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "delegate_maintenance_worktree",
        "agent": "codex",
        "project": repo.name,
        "scope": "fix/child-lane",
        "repo_root": str(repo),
        "branch": "fix/child-lane",
        "claim_type": "write",
        "write_paths": ["CLAUDE.md"],
        "parent_scope": "coordinator-root",
        "child_agent_id": "child-456",
    }
    payload.update(updates)
    return payload


def _revoke_delegated_maintenance_payload(repo: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "revoke_delegated_maintenance_worktree",
        "agent": "codex",
        "project": repo.name,
        "scope": "fix/child-lane",
        "repo_root": str(repo),
        "branch": "fix/child-lane",
        "parent_scope": "coordinator-root",
        "child_agent_id": "child-456",
    }
    payload.update(updates)
    return payload


def _local_repository_payload(repo: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "local_repository_worktree",
        "agent": "codex",
        "project": repo.name,
        "scope": "codex/initial-setup",
        "repo_root": str(repo),
        "branch": "codex/initial-setup",
        "claim_type": "program",
    }
    payload.update(updates)
    return payload


def _local_integration_payload(repo: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "local_repository_integrate",
        "agent": "codex",
        "project": repo.name,
        "scope": "codex/initial-setup",
        "repo_root": str(repo),
        "branch": "codex/initial-setup",
        "default_branch": "main",
    }
    payload.update(updates)
    return payload


def _workspace_archive_payload(root: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "workspace_file_archive",
        "agent": "codex",
        "project": "workspace-root",
        "scope": "loose-file-archive",
        "workspace_root": str(root.resolve()),
        "source": "screenshot.png",
        "destination": "archive/workspace-cleanup/screenshot.png",
    }
    payload.update(updates)
    return payload


def _workspace_image_canary_payload(root: Path, **updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "workspace_image_canary",
        "agent": "codex",
        "project": "workspace-root",
        "scope": "image-ingest-canary",
        "workspace_root": str(root.resolve()),
        "source": "archive/workspace-cleanup/screenshot.png",
    }
    payload.update(updates)
    return payload


def _bind_workspace_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(claim_bootstrap, "_configured_workspace_root", lambda: root.resolve())


def test_configured_workspace_root_comes_from_hash_pinned_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "code"
    homes = {
        "code-active": root / "active",
        "code-inactive": root / "inactive",
        "code-template": root / "templates",
    }
    root.mkdir()
    provider = tmp_path / "workspace_authority_provider.py"
    configured = ", ".join(
        f"{key!r}: Path({str(path)!r})" for key, path in homes.items()
    )
    provider.write_text(
        "from pathlib import Path\n"
        f"WORKSPACE_HOME_PATHS = {{{configured}}}\n",
        encoding="utf-8",
    )
    provider.chmod(0o755)
    config = tmp_path / "provider.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "provider_path": str(provider),
                "provider_sha256": hashlib.sha256(provider.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    monkeypatch.setattr(
        claim_bootstrap.repository_authority,
        "DEFAULT_PROVIDER_CONFIG",
        config,
    )

    assert claim_bootstrap._configured_workspace_root() == root


def test_workspace_file_archive_preserves_bytes_and_removes_only_exact_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-archive")
    monkeypatch.chdir(tmp_path)
    _bind_workspace_root(monkeypatch, tmp_path)
    source = tmp_path / "screenshot.png"
    source.write_bytes(b"png-like-evidence")
    request = claim_bootstrap.parse_request_json(
        json.dumps(_workspace_archive_payload(tmp_path))
    )

    receipt = claim_bootstrap.execute_request(request)

    destination = tmp_path / "archive/workspace-cleanup/screenshot.png"
    assert not source.exists()
    assert destination.read_bytes() == b"png-like-evidence"
    assert receipt["result"]["destination"] == str(destination)
    assert receipt["result"]["recoverable"] is True
    assert len(receipt["result"]["sha256"]) == 64


@pytest.mark.parametrize(
    "updates",
    [
        {"source": "nested/screenshot.png"},
        {"source": "../screenshot.png"},
        {"destination": "inbox/screenshot.png"},
        {"destination": "archive/../screenshot.png"},
        {"project": "another-workspace"},
    ],
)
def test_workspace_file_archive_rejects_ambiguous_or_nonarchive_paths(
    tmp_path: Path,
    updates: dict[str, object],
) -> None:
    with pytest.raises(claim_bootstrap.ClaimBootstrapError):
        claim_bootstrap.parse_request_json(
            json.dumps(_workspace_archive_payload(tmp_path, **updates))
        )


def test_workspace_file_archive_never_overwrites_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-archive")
    monkeypatch.chdir(tmp_path)
    _bind_workspace_root(monkeypatch, tmp_path)
    source = tmp_path / "screenshot.png"
    destination = tmp_path / "archive/workspace-cleanup/screenshot.png"
    source.write_bytes(b"new")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"old")
    request = claim_bootstrap.parse_request_json(
        json.dumps(_workspace_archive_payload(tmp_path))
    )

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="never overwrites"):
        claim_bootstrap.execute_request(request)

    assert source.read_bytes() == b"new"
    assert destination.read_bytes() == b"old"


def test_workspace_file_archive_rejects_symlink_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-archive")
    monkeypatch.chdir(tmp_path)
    _bind_workspace_root(monkeypatch, tmp_path)
    target = tmp_path / "target.png"
    target.write_bytes(b"preserve")
    (tmp_path / "screenshot.png").symlink_to(target)
    request = claim_bootstrap.parse_request_json(
        json.dumps(_workspace_archive_payload(tmp_path))
    )

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="non-symlink"):
        claim_bootstrap.execute_request(request)

    assert target.read_bytes() == b"preserve"


def test_workspace_image_canary_stages_image_png_and_preserves_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-canary")
    monkeypatch.chdir(tmp_path)
    _bind_workspace_root(monkeypatch, tmp_path)
    source = tmp_path / "archive/workspace-cleanup/screenshot.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"\x89PNG\r\n\x1a\ncanary")
    request = claim_bootstrap.parse_request_json(
        json.dumps(_workspace_image_canary_payload(tmp_path))
    )

    receipt = claim_bootstrap.execute_request(request)

    assert source.read_bytes() == b"\x89PNG\r\n\x1a\ncanary"
    assert (tmp_path / "image.png").read_bytes() == source.read_bytes()
    assert receipt["result"]["source_preserved"] is True
    assert receipt["result"]["destination"] == str(tmp_path / "image.png")


def test_workspace_image_canary_never_overwrites_existing_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-canary")
    monkeypatch.chdir(tmp_path)
    _bind_workspace_root(monkeypatch, tmp_path)
    source = tmp_path / "archive/workspace-cleanup/screenshot.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    (tmp_path / "image.png").write_bytes(b"existing")
    request = claim_bootstrap.parse_request_json(
        json.dumps(_workspace_image_canary_payload(tmp_path))
    )

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="never overwrites"):
        claim_bootstrap.execute_request(request)

    assert source.read_bytes() == b"source"
    assert (tmp_path / "image.png").read_bytes() == b"existing"


@pytest.mark.parametrize(
    "source",
    ["screenshot.png", "archive/../screenshot.png", "archive/workspace-cleanup/file.txt"],
)
def test_workspace_image_canary_requires_canonical_archived_png(
    tmp_path: Path,
    source: str,
) -> None:
    with pytest.raises(claim_bootstrap.ClaimBootstrapError):
        claim_bootstrap.parse_request_json(
            json.dumps(_workspace_image_canary_payload(tmp_path, source=source))
        )


@pytest.mark.parametrize("operation", ["archive", "canary"])
def test_workspace_operations_reject_request_selected_absolute_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    canonical = tmp_path / "canonical-code"
    unrelated = tmp_path / "unrelated"
    canonical.mkdir()
    unrelated.mkdir()
    monkeypatch.setenv("CODEX_THREAD_ID", f"native-{operation}")
    monkeypatch.chdir(unrelated)
    _bind_workspace_root(monkeypatch, canonical)

    if operation == "archive":
        source = unrelated / "screenshot.png"
        source.write_bytes(b"must-stay")
        payload = _workspace_archive_payload(unrelated)
    else:
        source = unrelated / "archive/workspace-cleanup/screenshot.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"must-stay")
        payload = _workspace_image_canary_payload(unrelated)
    request = claim_bootstrap.parse_request_json(json.dumps(payload))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="configured workspace root"):
        claim_bootstrap.execute_request(request)

    assert source.read_bytes() == b"must-stay"
    assert not (unrelated / "image.png").exists()


def test_unclaimed_native_session_can_start_its_own_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "trackers"
    repo_root = tmp_path / "repo"
    worktree = repo_root / "worktrees" / "self-owned-scope"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(claim_bootstrap.coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(claim_bootstrap, "SESSION_TRACKERS_DIR", trackers_dir)
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims.claim_mutation_receipts,
        "append_receipt",
        lambda _receipt: None,
    )
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims.claim_mutation_receipts,
        "append_narrow_receipt",
        lambda _receipt: None,
    )
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims.claim_mutation_receipts,
        "DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH",
        tmp_path / "completed-claim-archive-v1.jsonl",
    )
    monkeypatch.setattr(
        claim_bootstrap.session_lifecycle,
        "_poll_mailbox",
        lambda **_kwargs: {"polled": True, "active_count": 0},
    )
    request = claim_bootstrap.parse_request_json(
        json.dumps(
            _start_payload(
                repo_root=str(repo_root),
                worktree_path=str(worktree),
            )
        )
    )

    receipt = claim_bootstrap.execute_request(request)

    assert receipt["ok"] is True
    assert receipt["session_id"] == "codex:native-123"
    claims = claim_bootstrap.coordination_claims.check_claims("demo")
    assert [(claim.scope, claim.session_id) for claim in claims] == [("self-owned-scope", "codex:native-123")]
    assert claims[0].write_paths == ["src/owned.py"]
    assert list(worktree.iterdir()) == []
    assert len(list(trackers_dir.rglob("*.yaml"))) == 1


def test_request_for_wrong_agent_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    request = claim_bootstrap.parse_request_json(json.dumps(_start_payload(agent="claude-code")))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="native claude-code runtime"):
        claim_bootstrap.execute_request(request)


def test_request_cannot_supply_session_id() -> None:
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="session_id"):
        claim_bootstrap.parse_request_json(json.dumps(_start_payload(session_id="codex:borrowed")))


def test_cross_session_scope_update_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")

    def reject_foreign_owner(**_kwargs: object) -> dict[str, object]:
        raise ValueError("Existing live claim slot demo:self-owned-scope is owned by runtime session codex:other")

    monkeypatch.setattr(claim_bootstrap.session_lifecycle, "start_session", reject_foreign_owner)
    request = claim_bootstrap.parse_request_json(json.dumps(_start_payload()))

    with pytest.raises(ValueError, match="owned by runtime session codex:other"):
        claim_bootstrap.execute_request(request)


def test_raw_bash_grammar_accepts_only_canonical_single_command(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "claim_bootstrap.py"
    raw_json = json.dumps(_start_payload(intent="Brian's claim"), separators=(",", ":")).replace("'", "\\u0027")
    command = f"/usr/bin/python3 {script} --request-json '{raw_json}'"

    request = claim_bootstrap.parse_raw_bash_command(command, script_path=script)

    assert request.operation == "session_start_or_update"
    assert request.intent == "Brian's claim"


def test_raw_bash_grammar_accepts_typed_local_integration(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "claim_bootstrap.py"
    repo = (tmp_path / "weekly-plans").resolve()
    raw_json = json.dumps(_local_integration_payload(repo), separators=(",", ":"))
    command = f"/usr/bin/python3 {script} --request-json '{raw_json}'"

    request = claim_bootstrap.parse_raw_bash_command(command, script_path=script)

    assert request.operation == "local_repository_integrate"
    assert request.repo_root == str(repo)


def _governed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "governed-repo"
    (repo / "docs" / "plans").mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "meta-process.yaml").write_text("meta_process: {}\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text("# Governed repository\n", encoding="utf-8")
    (repo / "docs" / "plans" / "CLAUDE.md").write_text("# Plans\n", encoding="utf-8")
    (repo / ".gitignore").write_text("/worktrees/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "governed fixture",
        ],
        check=True,
        capture_output=True,
    )
    return repo.resolve()


def _configure_maintenance_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "trackers"
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(claim_bootstrap.coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(claim_bootstrap, "SESSION_TRACKERS_DIR", trackers_dir)
    canonical_lock = claim_bootstrap._canonical_lock_module()
    monkeypatch.setattr(canonical_lock, "LOCK_INDEX", tmp_path / "canonical-locks.json")
    monkeypatch.setattr(claim_bootstrap, "_canonical_lock_module", lambda: canonical_lock)
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims.claim_mutation_receipts,
        "append_receipt",
        lambda _receipt: None,
    )
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims.claim_mutation_receipts,
        "DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH",
        tmp_path / "completed-claim-archive-v1.jsonl",
    )
    monkeypatch.setattr(
        claim_bootstrap.session_lifecycle,
        "_poll_mailbox",
        lambda **_kwargs: {"polled": True, "active_count": 0},
    )
    monkeypatch.setattr(
        claim_bootstrap,
        "_repository_authority",
        lambda repo, **_kwargs: claim_bootstrap.RepositoryAuthority(
            repo.name, f"Brian/{repo.name}", "main", "origin"
        ),
    )
    monkeypatch.setattr(
        claim_bootstrap,
        "_fresh_remote_default_revision",
        lambda repo, _authority: subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
    )
    return claims_dir, trackers_dir


def _start_coordinator_claim(repo: Path, trackers_dir: Path) -> Path:
    worktree = repo / "worktrees" / "coordinator-root"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-b", "coordinator-root", str(worktree), "main"],
        check=True,
        capture_output=True,
    )
    claim_bootstrap.session_lifecycle.start_session(
        agent="codex",
        project=repo.name,
        scope="coordinator-root",
        intent="Coordinate bounded child maintenance",
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="coordinator-root",
        broader_goal="Coordinate bounded child maintenance",
        current_phase="delegation",
        plan_ref=None,
        session_id="codex:native-123",
        session_name="coordinate-bounded-child-maintenance",
        claim_type="program",
        write_paths=["docs/plans/CLAUDE.md"],
        read_paths=[],
        tracker_dir=trackers_dir,
        allow_unplanned=True,
    )
    return worktree


def test_typed_local_repository_bootstrap_creates_local_repo_claim_and_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    repo = (tmp_path / "weekly-plans").resolve()
    request = claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(repo)))

    receipt = claim_bootstrap.execute_request(request)

    worktree = repo / "worktrees" / "codex" / "initial-setup"
    assert receipt["result"]["local_only"] is True
    assert receipt["result"]["default_branch"] == "main"
    assert subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        check=True, capture_output=True, text=True,
    ).stdout.strip() == "main"
    assert subprocess.run(
        ["git", "-C", str(repo), "remote"],
        check=True, capture_output=True, text=True,
    ).stdout == ""
    assert subprocess.run(
        ["git", "-C", str(worktree), "branch", "--show-current"],
        check=True, capture_output=True, text=True,
    ).stdout.strip() == "codex/initial-setup"
    assert (worktree / ".gitignore").read_text(encoding="utf-8") == "/worktrees/\n"
    claims = claim_bootstrap.coordination_claims.check_claims("weekly-plans")
    assert len(claims) == 1
    assert claims[0].session_id == "codex:native-123"
    assert claims[0].write_paths == ["."]
    assert claims[0].worktree_path == str(worktree)
    assert claims[0].target_worktree_path is None
    assert claims[0].broad_scope_mode == "bounded"
    assert len(list(trackers_dir.rglob("*.yaml"))) == 1
    assert prewrite_claim_projection.projection_is_current(
        claims_dir=claims_dir,
        projection_path=prewrite_claim_fast.projection_path_for(claims_dir),
    )

    (worktree / "README.md").write_text("# Weekly Plans\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(worktree), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test User", "-c", "user.email=test@example.invalid",
            "-C", str(worktree), "commit", "-m", "Add weekly plan",
        ],
        check=True,
        capture_output=True,
    )
    canonical_lock = claim_bootstrap._canonical_lock_module()
    monkeypatch.setattr(canonical_lock, "LOCK_INDEX", tmp_path / "locks.json")
    monkeypatch.setattr(claim_bootstrap, "_canonical_lock_module", lambda: canonical_lock)
    canonical_lock.lock_repo(
        repo,
        justifying_claims=["codex/initial-setup"],
        session_id="codex:native-123",
    )
    blocked = subprocess.run(
        ["git", "-C", str(repo), "merge", "--ff-only", "codex/initial-setup"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode != 0

    integrated = claim_bootstrap.execute_request(
        claim_bootstrap.parse_request_json(json.dumps(_local_integration_payload(repo)))
    )

    assert integrated["result"]["action"] == "integrated"
    assert integrated["result"]["integrated_revision"] == subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_LOCKED
    closed = claim_bootstrap.session_lifecycle.close_session(
        agent="codex",
        project="weekly-plans",
        scope="codex/initial-setup",
        worktree_path=str(worktree),
        branch="codex/initial-setup",
        actor_session_id="codex:native-123",
    )
    assert closed["released"] is True
    assert closed["disposition"] == "merged"
    assert not worktree.exists()
    canonical_lock.unlock_repo(repo)
    assert (repo / "README.md").read_text(encoding="utf-8") == "# Weekly Plans\n"


def test_local_integration_relocks_after_git_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    repo = (tmp_path / "weekly-plans").resolve()
    claim_bootstrap.execute_request(
        claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(repo)))
    )
    worktree = repo / "worktrees" / "codex" / "initial-setup"
    (worktree / "README.md").write_text("# Weekly Plans\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(worktree), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test User", "-c", "user.email=test@example.invalid",
            "-C", str(worktree), "commit", "-m", "Add weekly plan",
        ],
        check=True,
        capture_output=True,
    )
    canonical_lock = claim_bootstrap._canonical_lock_module()
    monkeypatch.setattr(canonical_lock, "LOCK_INDEX", tmp_path / "locks.json")
    monkeypatch.setattr(claim_bootstrap, "_canonical_lock_module", lambda: canonical_lock)
    canonical_lock.lock_repo(
        repo,
        justifying_claims=["codex/initial-setup"],
        session_id="codex:native-123",
    )
    original_git = claim_bootstrap._git

    def fail_merge(target: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("merge", "--ff-only"):
            return subprocess.CompletedProcess([], 1, "", "simulated merge failure")
        return original_git(target, *args)

    monkeypatch.setattr(claim_bootstrap, "_git", fail_merge)

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="simulated merge failure"):
        claim_bootstrap.execute_request(
            claim_bootstrap.parse_request_json(json.dumps(_local_integration_payload(repo)))
        )

    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_LOCKED
    canonical_lock.unlock_repo(repo)


def test_already_integrated_local_repository_requires_a_healthy_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    repo = (tmp_path / "weekly-plans").resolve()
    claim_bootstrap.execute_request(
        claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(repo)))
    )
    worktree = repo / "worktrees" / "codex" / "initial-setup"
    (worktree / "README.md").write_text("# Weekly Plans\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(worktree), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test User", "-c", "user.email=test@example.invalid",
            "-C", str(worktree), "commit", "-m", "Add weekly plan",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), "merge", "--ff-only", "codex/initial-setup"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="no live lock receipt"):
        claim_bootstrap.execute_request(
            claim_bootstrap.parse_request_json(json.dumps(_local_integration_payload(repo)))
        )


def test_local_integration_recovers_a_partial_relock_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    repo = (tmp_path / "weekly-plans").resolve()
    claim_bootstrap.execute_request(
        claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(repo)))
    )
    worktree = repo / "worktrees" / "codex" / "initial-setup"
    (worktree / "README.md").write_text("# Weekly Plans\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(worktree), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test User", "-c", "user.email=test@example.invalid",
            "-C", str(worktree), "commit", "-m", "Add weekly plan",
        ],
        check=True,
        capture_output=True,
    )
    canonical_lock = claim_bootstrap._canonical_lock_module()
    monkeypatch.setattr(canonical_lock, "LOCK_INDEX", tmp_path / "locks.json")
    monkeypatch.setattr(claim_bootstrap, "_canonical_lock_module", lambda: canonical_lock)
    canonical_lock.lock_repo(
        repo,
        justifying_claims=["codex/initial-setup"],
        session_id="codex:native-123",
    )
    original_lock = canonical_lock.lock_repo
    failed_once = False

    def partially_fail_lock(*args: object, **kwargs: object) -> dict[str, object]:
        nonlocal failed_once
        result = original_lock(*args, **kwargs)
        if not failed_once:
            failed_once = True
            target = repo / "README.md"
            os.chmod(target, stat.S_IMODE(target.lstat().st_mode) | stat.S_IWUSR)
            raise OSError("simulated post-receipt lock failure")
        return result

    monkeypatch.setattr(canonical_lock, "lock_repo", partially_fail_lock)

    integrated = claim_bootstrap.execute_request(
        claim_bootstrap.parse_request_json(json.dumps(_local_integration_payload(repo)))
    )

    assert integrated["result"]["action"] == "integrated"
    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_LOCKED
    canonical_lock.unlock_repo(repo)


@pytest.mark.parametrize("target_kind", ["directory", "file", "symlink"])
def test_typed_local_repository_bootstrap_rejects_every_existing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    repo = (tmp_path / "weekly-plans").resolve()
    if target_kind == "directory":
        repo.mkdir()
    elif target_kind == "file":
        repo.write_text("preserve\n", encoding="utf-8")
    else:
        destination = tmp_path / "elsewhere"
        destination.mkdir()
        repo.symlink_to(destination, target_is_directory=True)
    if target_kind == "symlink":
        with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="canonical absolute path"):
            claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(repo)))
    else:
        request = claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(repo)))
        with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="already exists"):
            claim_bootstrap.execute_request(request)


def test_typed_local_repository_bootstrap_rejects_nested_or_non_child_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    outside = (tmp_path / "outside").resolve()
    request = claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(outside)))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="direct child"):
        claim_bootstrap.execute_request(request)

    subprocess.run(["git", "init", "-b", "main", str(workspace)], check=True, capture_output=True)
    nested = (workspace / "nested").resolve()
    request = claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(nested)))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="inside another Git worktree"):
        claim_bootstrap.execute_request(request)


def test_typed_local_repository_bootstrap_rolls_back_unclaimed_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    repo = (tmp_path / "weekly-plans").resolve()
    monkeypatch.setattr(
        claim_bootstrap.session_lifecycle,
        "start_session",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("simulated claim failure")),
    )
    request = claim_bootstrap.parse_request_json(json.dumps(_local_repository_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="simulated claim failure"):
        claim_bootstrap.execute_request(request)

    assert not repo.exists()


def test_default_branch_target_is_rejected_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    claims_dir, _trackers = _configure_maintenance_runtime(tmp_path, monkeypatch)
    def must_not_fetch(*_args: object) -> str:
        pytest.fail("default branch rejection must precede remote fetch")
    monkeypatch.setattr(claim_bootstrap, "_fresh_remote_default_revision", must_not_fetch)
    request = claim_bootstrap.parse_request_json(json.dumps(
        _maintenance_payload(repo, branch="main", scope="main")
    ))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="non-default"):
        claim_bootstrap.execute_request(request)
    assert not (repo / "worktrees").exists()
    assert not list(claims_dir.glob("*.yaml"))


def _project_graph_fixture(
    tmp_path: Path,
    *,
    project_id: str = "agent-skills",
) -> tuple[Path, Path, str, str]:
    remote = tmp_path / "agent-skills.git"
    repo = tmp_path / "agent-skills"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", str(remote)],
        check=True,
        capture_output=True,
    )
    (repo / "CLAUDE.md").write_text("# Agent Skills instructions\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "CLAUDE.md"], check=True, capture_output=True)
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=Test User", "-c",
            "user.email=test@example.invalid", "commit", "-m", "initial",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(repo), "push", "-u", "origin", "main"], check=True, capture_output=True)
    subprocess.run(
        ["git", "--git-dir", str(remote), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    stale_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    publisher = tmp_path / "publisher"
    subprocess.run(["git", "clone", "-b", "main", str(remote), str(publisher)], check=True, capture_output=True)
    (publisher / "fresh.txt").write_text("fresh remote content\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(publisher), "add", "fresh.txt"], check=True, capture_output=True)
    subprocess.run(
        [
            "git", "-C", str(publisher), "-c", "user.name=Test User", "-c",
            "user.email=test@example.invalid", "commit", "-m", "remote advance",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "-C", str(publisher), "push", "origin", "main"], check=True, capture_output=True)
    fresh_head = subprocess.run(
        ["git", "-C", str(publisher), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    graph = tmp_path / "PROJECT_GRAPH.json"
    graph.write_text(
        json.dumps(
            [
                {
                    "id": project_id,
                    "record_kind": "repository",
                    "status": "active",
                    "github_repo": "Brian/agent-skills",
                    "default_branch": "main",
                    "repository_governance": {
                        "owner_class": "brian",
                        "approved_remote_owners": ["Brian"],
                        "mutation_authority": "normal_push",
                        "publication_authority": "recoverable_git",
                    },
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "set-url", "origin", "git@github.com:Brian/agent-skills.git"],
        check=True,
        capture_output=True,
    )
    return repo.resolve(), graph, stale_head, fresh_head


@pytest.mark.parametrize(
    "remote",
    [
        "https://evil.example/Brian/agent-skills.git",
        "git@evil.example:Brian/agent-skills.git",
        "/tmp/Brian/agent-skills.git",
        "file:///tmp/Brian/agent-skills.git",
    ],
)
def test_project_graph_rejects_non_github_origin_even_when_owner_repo_matches(
    tmp_path: Path,
    remote: str,
) -> None:
    repo, _graph, _stale_head, _fresh_head = _project_graph_fixture(tmp_path)
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", remote], check=True, capture_output=True)

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="GitHub|github.com"):
        claim_bootstrap._repository_authority(repo)


def test_project_graph_accepts_ssh_alias_only_when_it_resolves_to_github(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _graph, _stale_head, _fresh_head = _project_graph_fixture(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "set-url", "origin", "git@github-personal:Brian/agent-skills.git"],
        check=True,
        capture_output=True,
    )
    real_run = claim_bootstrap.subprocess.run

    def resolve_alias(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv == ["ssh", "-G", "github-personal"]:
            return subprocess.CompletedProcess(argv, 0, "hostname github.com\nuser git\n", "")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(claim_bootstrap.subprocess, "run", resolve_alias)

    monkeypatch.setattr(
        claim_bootstrap,
        "resolve_repository_authority",
        lambda **kwargs: claim_bootstrap.RepositoryAuthority(
            "agent-skills", kwargs["repository_identity"], "main", kwargs["remote_url"]
        ),
    )
    authority = claim_bootstrap._repository_authority(repo)

    assert authority.repository_identity == "Brian/agent-skills"


def test_typed_maintenance_bootstraps_from_fresh_remote_not_stale_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _graph, stale_head, fresh_head = _project_graph_fixture(tmp_path)
    authority = claim_bootstrap.RepositoryAuthority(
        "agent-skills", "Brian/agent-skills", "main", str(tmp_path / "agent-skills.git")
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "set-url", "origin", str(tmp_path / "redirected-evil.git")],
        check=True,
        capture_output=True,
    )
    real_fresh = claim_bootstrap._fresh_remote_default_revision
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(
        claim_bootstrap,
        "_repository_authority",
        lambda _target, **_kwargs: authority,
    )
    monkeypatch.setattr(claim_bootstrap, "_fresh_remote_default_revision", real_fresh)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    receipt = claim_bootstrap.execute_request(request)

    worktree = repo / "worktrees" / "fix" / "safe-lane"
    lane_head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert stale_head != fresh_head
    assert lane_head == fresh_head
    assert receipt["result"]["start_revision"] == fresh_head
    assert (worktree / "fresh.txt").read_text(encoding="utf-8") == "fresh remote content\n"


def test_remote_fetch_failure_leaves_no_lane_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _graph, _stale_head, _fresh_head = _project_graph_fixture(tmp_path)
    authority = claim_bootstrap.RepositoryAuthority(
        "agent-skills", "Brian/agent-skills", "main", str(tmp_path / "missing.git")
    )
    subprocess.run(
        ["git", "-C", str(repo), "remote", "set-url", "origin", str(tmp_path / "missing.git")],
        check=True,
        capture_output=True,
    )
    real_fresh = claim_bootstrap._fresh_remote_default_revision
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(
        claim_bootstrap,
        "_repository_authority",
        lambda _target, **_kwargs: authority,
    )
    monkeypatch.setattr(claim_bootstrap, "_fresh_remote_default_revision", real_fresh)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="does not appear to be a git repository"):
        claim_bootstrap.execute_request(request)

    assert not (repo / "worktrees").exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0


@pytest.mark.parametrize("write_paths", [None, ["src/adapter.py", "tests/test_adapter.py"]])
def test_typed_maintenance_worktree_transaction_creates_claim_tracker_and_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_paths: list[str] | None,
) -> None:
    repo = _governed_repo(tmp_path)
    claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    request = claim_bootstrap.parse_request_json(
        json.dumps(_maintenance_payload(
            repo, **({"write_paths": write_paths} if write_paths is not None else {})
        ), separators=(",", ":"))
    )

    receipt = claim_bootstrap.execute_request(request)

    worktree = repo / "worktrees" / "fix" / "safe-lane"
    assert receipt["ok"] is True
    assert receipt["session_id"] == "codex:native-123"
    assert worktree.is_dir()
    assert (worktree / "CLAUDE.md").is_file()
    assert subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""
    assert subprocess.run(
        ["git", "-C", str(worktree), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "fix/safe-lane"
    claims = claim_bootstrap.coordination_claims.check_claims(repo.name)
    assert len(claims) == 1
    assert claims[0].session_id == "codex:native-123"
    if write_paths is None:
        assert claims[0].worktree_path == str(worktree)
        assert claims[0].target_worktree_path == str(worktree)
        assert claims[0].broad_scope_mode == "bootstrap"
        assert receipt["result"]["bootstrap_requires_narrowing"] is True
    else:
        assert claims[0].worktree_path == str(worktree)
        assert claims[0].target_worktree_path is None
        assert receipt["result"]["bootstrap_requires_narrowing"] is False
    assert claims[0].claim_type == "program"
    assert claims[0].write_paths == (write_paths or ["."])
    assert claims[0].start_revision == receipt["result"]["start_revision"]
    tracker_files = list(trackers_dir.rglob("*.yaml"))
    assert len(tracker_files) == 1
    tracker = yaml.safe_load(tracker_files[0].read_text(encoding="utf-8"))
    assert tracker["claim"]["start_revision"] == receipt["result"]["start_revision"]
    projection_path = prewrite_claim_fast.projection_path_for(claims_dir)
    assert prewrite_claim_projection.projection_is_current(
        claims_dir=claims_dir,
        projection_path=projection_path,
    )
    resolved = session_target.resolve_exact_session_target(
        {"session_id": "native-123"},
        client="codex",
        claims_dir=claims_dir,
        projection_path=projection_path,
    )
    assert resolved.worktree_path == worktree
    inside = prewrite_claim_fast.evaluate_prewrite_fast(
        {
            "session_id": "native-123",
            "hook_event_name": "PreToolUse",
            "cwd": str(worktree),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": f"*** Begin Patch\n*** Update File: {worktree / 'CLAUDE.md'}\n@@\n-old\n+new\n*** End Patch"
            },
        },
        client="codex",
        mode="enforce",
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "inside-receipts.jsonl",
    )
    outside = prewrite_claim_fast.evaluate_prewrite_fast(
        {
            "session_id": "native-123",
            "hook_event_name": "PreToolUse",
            "cwd": str(repo),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": f"*** Begin Patch\n*** Update File: {repo / 'CLAUDE.md'}\n@@\n-old\n+new\n*** End Patch"
            },
        },
        client="codex",
        mode="enforce",
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "outside-receipts.jsonl",
    )
    # A narrow lane must not inherit permission to edit the root instruction.
    assert inside["decision"] == "deny"
    assert outside["decision"] == "deny"
    if write_paths is None:
        claim_bootstrap.coordination_claims.narrow_claim(
            agent="codex",
            project=repo.name,
            scope="fix/safe-lane",
            session_id="codex:native-123",
            write_paths=["CLAUDE.md"],
        )
        admitted = prewrite_claim_fast.evaluate_prewrite_fast(
            {
                "session_id": "native-123",
                "hook_event_name": "PreToolUse",
                "cwd": str(worktree),
                "tool_name": "apply_patch",
                "tool_input": {
                    "command": f"*** Begin Patch\n*** Update File: {worktree / 'CLAUDE.md'}\n@@\n-old\n+new\n*** End Patch"
                },
            },
            client="codex",
            mode="enforce",
            claims_dir=claims_dir,
            projection_path=projection_path,
            receipt_path=tmp_path / "admitted-receipts.jsonl",
        )
        assert admitted["decision"] == "allow"


def test_goal_worktree_transaction_pins_fresh_default_and_preserves_goal_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _graph, stale_head, fresh_head = _project_graph_fixture(tmp_path)
    authority = claim_bootstrap.RepositoryAuthority(
        "agent-skills", "Brian/agent-skills", "main", str(tmp_path / "agent-skills.git")
    )
    real_fresh = claim_bootstrap._fresh_remote_default_revision
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(claim_bootstrap, "_repository_authority", lambda _target, **_kwargs: authority)
    monkeypatch.setattr(claim_bootstrap, "_fresh_remote_default_revision", real_fresh)

    receipt = claim_bootstrap.execute_request(
        claim_bootstrap.parse_request_json(json.dumps(_goal_worktree_payload(repo)))
    )

    worktree = repo / "worktrees" / "goal" / "owner-visible-outcome"
    lane_head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    claim = claim_bootstrap.coordination_claims.check_claims(repo.name)[0]
    tracker_path = next(trackers_dir.rglob("*.yaml"))
    tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))

    assert stale_head != fresh_head
    assert lane_head == fresh_head
    assert receipt["result"]["start_revision"] == fresh_head
    assert claim.start_revision == fresh_head
    assert claim.plan_ref == "goal:owner-visible-outcome"
    assert claim.work_graph_path is None
    assert claim.work_unit_id is None
    assert tracker["claim"]["start_revision"] == fresh_head
    assert tracker["claim"]["plan_ref"] == "goal:owner-visible-outcome"
    assert tracker["tracker"]["current_phase"] == "first vertical"
    assert tracker["tracker"]["intended_next_phases"] == ["exercise the owner-visible boundary"]


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"plan_ref": "UNPLANNED"}, "plan_ref"),
        ({"plan_ref": "goal:owner visible"}, "plan_ref"),
        ({"broader_goal": " padded"}, "surrounding whitespace"),
        ({"current_phase": "phase "}, "surrounding whitespace"),
    ],
)
def test_goal_worktree_rejects_malformed_goal_contract(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    repo = tmp_path / "demo"
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match=message):
        claim_bootstrap.parse_request_json(json.dumps(_goal_worktree_payload(repo, **updates)))


def test_goal_worktree_lifecycle_failure_rolls_back_all_lane_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)

    def fail_lifecycle(**_kwargs: object) -> dict[str, object]:
        raise ValueError("simulated goal lifecycle failure")

    monkeypatch.setattr(claim_bootstrap.session_lifecycle, "start_session", fail_lifecycle)
    request = claim_bootstrap.parse_request_json(json.dumps(_goal_worktree_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="transaction rolled back"):
        claim_bootstrap.execute_request(request)

    assert not claims_dir.exists() or not list(claims_dir.glob("*.yaml"))
    assert not list(trackers_dir.rglob("*.yaml"))
    assert not (repo / "worktrees" / "goal" / "owner-visible-outcome").exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/goal/owner-visible-outcome"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_goal_worktree_preserves_entire_lane_when_persisted_identity_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    real_start = claim_bootstrap.session_lifecycle.start_session

    def persist_tamper_then_fail(**kwargs: object) -> dict[str, object]:
        real_start(**kwargs)
        tracker_path = next(trackers_dir.rglob("*.yaml"))
        tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
        tracker["claim"]["session_id"] = "codex:foreign-runtime"
        tracker_path.write_text(yaml.safe_dump(tracker, sort_keys=False), encoding="utf-8")
        raise RuntimeError("simulated goal failure after ownership changed")

    monkeypatch.setattr(claim_bootstrap.session_lifecycle, "start_session", persist_tamper_then_fail)
    request = claim_bootstrap.parse_request_json(json.dumps(_goal_worktree_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="intact lane preserved"):
        claim_bootstrap.execute_request(request)

    worktree = repo / "worktrees" / "goal" / "owner-visible-outcome"
    assert worktree.is_dir()
    assert claim_bootstrap.coordination_claims.check_claims(repo.name)
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/goal/owner-visible-outcome"],
        capture_output=True,
        check=False,
    ).returncode == 0


def test_goal_worktree_preserves_complete_lane_when_post_claim_reconciliation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)

    def fail_reconciliation(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("simulated canonical lock failure")

    monkeypatch.setattr(claim_bootstrap, "_reconcile_canonical_after_claim", fail_reconciliation)
    request = claim_bootstrap.parse_request_json(json.dumps(_goal_worktree_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="complete claimed lane remains intact"):
        claim_bootstrap.execute_request(request)

    worktree = repo / "worktrees" / "goal" / "owner-visible-outcome"
    claims = claim_bootstrap.coordination_claims.check_claims(repo.name)
    assert worktree.is_dir()
    assert len(claims) == 1
    assert claims[0].worktree_path == str(worktree)
    assert claims[0].plan_ref == "goal:owner-visible-outcome"
    assert len(list(trackers_dir.rglob("*.yaml"))) == 1
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/goal/owner-visible-outcome"],
        capture_output=True,
        check=False,
    ).returncode == 0

def test_parent_delegates_one_narrow_child_owned_maintenance_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    parent_worktree = _start_coordinator_claim(repo, trackers_dir)
    request = claim_bootstrap.parse_request_json(
        json.dumps(_delegated_maintenance_payload(repo), separators=(",", ":"))
    )

    receipt = claim_bootstrap.execute_request(request)

    child_worktree = repo / "worktrees" / "fix" / "child-lane"
    claims = claim_bootstrap.coordination_claims.check_claims(repo.name)
    parent = next(claim for claim in claims if claim.scope == "coordinator-root")
    child = next(claim for claim in claims if claim.scope == "fix/child-lane")
    assert parent.session_id == "codex:native-123"
    assert parent.write_paths == ["docs/plans/CLAUDE.md"]
    assert child.session_id == "codex:child-456"
    assert child.claim_type == "write"
    assert child.parent_scope == "coordinator-root"
    assert child.write_paths == ["CLAUDE.md"]
    assert child.worktree_path == str(child_worktree)
    assert receipt["session_id"] == "codex:native-123"
    assert receipt["result"]["delegated_session_id"] == "codex:child-456"
    assert receipt["result"]["delegated_by_session_id"] == "codex:native-123"

    projection_path = prewrite_claim_fast.projection_path_for(claims_dir)
    child_write = prewrite_claim_fast.evaluate_prewrite_fast(
        {
            "session_id": "native-123",
            "agent_id": "child-456",
            "hook_event_name": "PreToolUse",
            "cwd": str(child_worktree),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": (
                    f"*** Begin Patch\n*** Update File: {child_worktree / 'CLAUDE.md'}"
                    "\n@@\n-old\n+new\n*** End Patch"
                )
            },
        },
        client="codex",
        mode="enforce",
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "child-write.jsonl",
    )
    parent_borrow = prewrite_claim_fast.evaluate_prewrite_fast(
        {
            "session_id": "native-123",
            "hook_event_name": "PreToolUse",
            "cwd": str(parent_worktree),
            "tool_name": "apply_patch",
            "tool_input": {
                "command": (
                    f"*** Begin Patch\n*** Update File: {child_worktree / 'CLAUDE.md'}"
                    "\n@@\n-old\n+new\n*** End Patch"
                )
            },
        },
        client="codex",
        mode="enforce",
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "parent-borrow.jsonl",
    )
    assert child_write["decision"] == "allow"
    assert parent_borrow["decision"] == "deny"


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"write_paths": ["."]}, "narrow write_paths"),
        ({"child_agent_id": "codex:native-123"}, "must differ"),
        ({"child_agent_id": "claude-code:child-456"}, "does not belong"),
        ({"parent_scope": "fix/child-lane"}, "cannot name itself"),
    ],
)
def test_delegated_maintenance_rejects_unsafe_authority_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, object],
    message: str,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    _start_coordinator_claim(repo, trackers_dir)
    payload = _delegated_maintenance_payload(repo, **updates)

    if updates.get("write_paths") == ["."] or updates.get("parent_scope") == "fix/child-lane":
        with pytest.raises(claim_bootstrap.ClaimBootstrapError, match=message):
            claim_bootstrap.parse_request_json(json.dumps(payload))
        return

    request = claim_bootstrap.parse_request_json(json.dumps(payload))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match=message):
        claim_bootstrap.execute_request(request)


def test_delegated_maintenance_requires_exact_healthy_parent_before_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    claims_dir, _trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    request = claim_bootstrap.parse_request_json(
        json.dumps(_delegated_maintenance_payload(repo, parent_scope="missing-root"))
    )

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="exact live parent"):
        claim_bootstrap.execute_request(request)

    assert not (repo / "worktrees" / "fix" / "child-lane").exists()
    assert not list(claims_dir.glob("*.yaml"))
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/child-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_delegated_maintenance_admits_sibling_overlap_in_distinct_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    _start_coordinator_claim(repo, trackers_dir)
    first = claim_bootstrap.parse_request_json(json.dumps(_delegated_maintenance_payload(repo)))
    claim_bootstrap.execute_request(first)
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    second = claim_bootstrap.parse_request_json(
        json.dumps(
            _delegated_maintenance_payload(
                repo,
                scope="fix/sibling-lane",
                branch="fix/sibling-lane",
                child_agent_id="child-789",
            )
        )
    )

    result = claim_bootstrap.execute_request(second)

    assert result["ok"] is True
    assert (repo / "worktrees" / "fix" / "child-lane").is_dir()
    assert (repo / "worktrees" / "fix" / "sibling-lane").is_dir()
    sibling_claims = [
        claim
        for claim in claim_bootstrap.coordination_claims.check_claims(repo.name)
        if claim.scope in {"fix/child-lane", "fix/sibling-lane"}
    ]
    assert {claim.scope for claim in sibling_claims} == {"fix/child-lane", "fix/sibling-lane"}
    interaction = claim_bootstrap.coordination_claims.evaluate_claim(
        next(claim for claim in sibling_claims if claim.scope == "fix/sibling-lane"),
        active_claims=[next(claim for claim in sibling_claims if claim.scope == "fix/child-lane")],
    ).interactions[0]
    assert interaction.severity == "advisory_overlap"
    assert interaction.reason == "isolated_worktree_overlap"


def test_delegated_post_claim_failure_revokes_before_git_artifacts_disappear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    _start_coordinator_claim(repo, trackers_dir)
    request = claim_bootstrap.parse_request_json(json.dumps(_delegated_maintenance_payload(repo)))
    child_worktree = repo / "worktrees" / "fix" / "child-lane"
    real_revoke = claim_bootstrap.session_lifecycle.revoke_delegated_session
    observed: dict[str, bool] = {}

    def revoke_after_observation(**kwargs: object) -> dict[str, object]:
        observed["worktree_exists"] = child_worktree.is_dir()
        observed["branch_exists"] = subprocess.run(
            ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/child-lane"],
            capture_output=True,
            check=False,
        ).returncode == 0
        observed["claim_exists"] = any(
            claim.scope == "fix/child-lane"
            for claim in claim_bootstrap.coordination_claims.check_claims(repo.name)
        )
        return real_revoke(**kwargs)

    monkeypatch.setattr(
        claim_bootstrap,
        "_reconcile_canonical_after_claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("lock reconcile failed")),
    )
    monkeypatch.setattr(claim_bootstrap.session_lifecycle, "revoke_delegated_session", revoke_after_observation)

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="transaction revoked"):
        claim_bootstrap.execute_request(request)

    assert observed == {"worktree_exists": True, "branch_exists": True, "claim_exists": True}
    assert not child_worktree.exists()
    assert not any(
        claim.scope == "fix/child-lane"
        for claim in claim_bootstrap.coordination_claims.check_claims(repo.name)
    )
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/child-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_delegated_post_claim_revoke_failure_preserves_intact_lane_for_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    _start_coordinator_claim(repo, trackers_dir)
    request = claim_bootstrap.parse_request_json(json.dumps(_delegated_maintenance_payload(repo)))
    child_worktree = repo / "worktrees" / "fix" / "child-lane"
    monkeypatch.setattr(
        claim_bootstrap,
        "_reconcile_canonical_after_claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("lock reconcile failed")),
    )
    monkeypatch.setattr(
        claim_bootstrap.session_lifecycle,
        "revoke_delegated_session",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("revoke unavailable")),
    )
    monkeypatch.setattr(
        claim_bootstrap,
        "_rollback_created_worktree",
        lambda **_kwargs: pytest.fail("post-claim delegated cleanup must not independently remove Git artifacts"),
    )

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="intact lane preserved for retry"):
        claim_bootstrap.execute_request(request)

    child = next(
        claim
        for claim in claim_bootstrap.coordination_claims.check_claims(repo.name)
        if claim.scope == "fix/child-lane"
    )
    assert child.status == "active"
    assert child_worktree.is_dir()
    assert Path(child.tracker_path or "").is_file()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/child-lane"],
        capture_output=True,
        check=False,
    ).returncode == 0


def test_delegated_pre_claim_failure_rolls_back_git_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    _start_coordinator_claim(repo, trackers_dir)
    request = claim_bootstrap.parse_request_json(json.dumps(_delegated_maintenance_payload(repo)))
    child_worktree = repo / "worktrees" / "fix" / "child-lane"
    real_rollback = claim_bootstrap._rollback_created_worktree
    rollback_calls = 0

    def observed_rollback(**kwargs: object) -> list[str]:
        nonlocal rollback_calls
        rollback_calls += 1
        assert child_worktree.is_dir()
        return real_rollback(**kwargs)

    monkeypatch.setattr(
        claim_bootstrap.session_lifecycle,
        "start_delegated_session",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("claim start failed")),
    )
    monkeypatch.setattr(claim_bootstrap, "_rollback_created_worktree", observed_rollback)

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="failed before claim creation"):
        claim_bootstrap.execute_request(request)

    assert rollback_calls == 1
    assert not child_worktree.exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/child-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_public_delegated_revoke_reports_completed_when_lock_reconcile_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    _start_coordinator_claim(repo, trackers_dir)
    create_request = claim_bootstrap.parse_request_json(json.dumps(_delegated_maintenance_payload(repo)))
    claim_bootstrap.execute_request(create_request)
    revoke_request = claim_bootstrap.parse_request_json(
        json.dumps(_revoke_delegated_maintenance_payload(repo))
    )
    child_worktree = repo / "worktrees" / "fix" / "child-lane"
    monkeypatch.setattr(
        claim_bootstrap,
        "_reconcile_canonical_after_claim",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bounded lock fault")),
    )

    receipt = claim_bootstrap.execute_request(revoke_request)

    result = receipt["result"]
    assert result["action"] == "pristine_delegated_lane_revoked_canonical_reconciliation_required"
    assert result["status"] == "revoked_canonical_reconciliation_required"
    assert result["canonical_lock_reconciliation_required"] is True
    assert result["canonical_lock_error"] == {
        "type": "RuntimeError",
        "message": "bounded lock fault",
    }
    assert not child_worktree.exists()
    assert not any(
        claim.scope == "fix/child-lane"
        for claim in claim_bootstrap.coordination_claims.check_claims(repo.name)
    )


@pytest.mark.parametrize("extra", [{"extra": "nope"}, {"agent": "claude-code"}])
def test_typed_maintenance_rejects_extra_fields_and_native_client_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra: dict[str, object],
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    if "extra" in extra:
        with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="extra"):
            claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo, **extra)))
    else:
        request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo, **extra)))
        with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="native claude-code runtime"):
            claim_bootstrap.execute_request(request)


@pytest.mark.parametrize("branch", ["../escape", "fix/../escape", "foo$(id)", "foo;id", "foo|id"])
def test_typed_maintenance_rejects_traversal_and_shell_branches(tmp_path: Path, branch: str) -> None:
    repo = _governed_repo(tmp_path)
    with pytest.raises(claim_bootstrap.ClaimBootstrapError):
        claim_bootstrap.parse_request_json(
            json.dumps(_maintenance_payload(repo, branch=branch, scope=branch))
        )


@pytest.mark.parametrize("preexisting", ["branch", "worktree"])
def test_typed_maintenance_rejects_existing_branch_or_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preexisting: str,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    if preexisting == "branch":
        subprocess.run(["git", "-C", str(repo), "branch", "fix/safe-lane"], check=True)
    else:
        (repo / "worktrees" / "fix" / "safe-lane").mkdir(parents=True)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match=f"{preexisting} already exists"):
        claim_bootstrap.execute_request(request)


def test_typed_maintenance_reports_worktree_add_failure_without_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    real_run = claim_bootstrap.subprocess.run

    def fail_add(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "worktree" in argv and "add" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "simulated add failure")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(claim_bootstrap.subprocess, "run", fail_add)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="simulated add failure"):
        claim_bootstrap.execute_request(request)
    assert not (repo / "worktrees" / "fix" / "safe-lane").exists()
    assert real_run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_typed_maintenance_rolls_back_its_atomic_branch_after_failed_git_add(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    real_run = claim_bootstrap.subprocess.run

    def partially_fail_add(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "worktree" in argv and "add" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "simulated partial add failure")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(claim_bootstrap.subprocess, "run", partially_fail_add)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="simulated partial add failure"):
        claim_bootstrap.execute_request(request)
    assert real_run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0
    assert not (repo / "worktrees").exists()


def test_typed_maintenance_preserves_foreign_branch_that_wins_atomic_ref_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    real_run = claim_bootstrap.subprocess.run
    injected = False

    def race_ref(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal injected
        if "update-ref" in argv and "refs/heads/fix/safe-lane" in argv and not injected:
            injected = True
            real_run(
                ["git", "-C", str(repo), "update-ref", "refs/heads/fix/safe-lane", "HEAD"],
                check=True,
                capture_output=True,
            )
        return real_run(argv, **kwargs)

    monkeypatch.setattr(claim_bootstrap.subprocess, "run", race_ref)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="atomic maintenance branch creation failed|cannot lock ref"):
        claim_bootstrap.execute_request(request)
    assert real_run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode == 0
    assert not (repo / "worktrees").exists()


def test_typed_maintenance_rejects_symlinked_worktree_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    (repo / "worktrees").mkdir()
    (repo / "worktrees" / "fix").symlink_to(escaped, target_is_directory=True)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="real directory"):
        claim_bootstrap.execute_request(request)

    assert not (escaped / "safe-lane").exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_typed_maintenance_suppresses_unclaimed_git_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    sentinel = tmp_path / "hook-executed"
    hooks = repo / ".git" / "hooks"
    for name in ("reference-transaction", "post-checkout"):
        hook = hooks / name
        hook.write_text(
            f"#!/bin/sh\nprintf executed > {sentinel}\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    receipt = claim_bootstrap.execute_request(request)

    assert receipt["ok"] is True
    assert not sentinel.exists()


def test_typed_maintenance_rejects_session_with_existing_root_without_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    existing = claim_bootstrap.parse_request_json(
        json.dumps(
            _start_payload(
                project="other-project",
                scope="existing-root",
                intent="existing root",
                claim_type="program",
                repo_root=str(repo),
                worktree_path=str(repo),
                branch="main",
                session_name="existing-root",
                broader_goal="Existing root",
                write_paths=[],
            )
        )
    )
    claim_bootstrap.execute_request(existing)
    tracker_paths_before = set(trackers_dir.rglob("*.yaml"))
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="zero existing claim roots"):
        claim_bootstrap.execute_request(request)

    assert not (repo / "worktrees" / "fix" / "safe-lane").exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0
    assert set(trackers_dir.rglob("*.yaml")) == tracker_paths_before


def test_typed_maintenance_rolls_back_partial_session_start_before_git_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    real_start = claim_bootstrap.session_lifecycle.start_session

    def persist_then_fail(**kwargs: object) -> dict[str, object]:
        real_start(**kwargs)
        raise RuntimeError("simulated post-persist failure")

    monkeypatch.setattr(claim_bootstrap.session_lifecycle, "start_session", persist_then_fail)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="simulated post-persist failure"):
        claim_bootstrap.execute_request(request)

    worktree = repo / "worktrees" / "fix" / "safe-lane"
    assert not worktree.exists()
    assert claim_bootstrap.coordination_claims.check_claims(repo.name) == []
    assert list(trackers_dir.rglob("*.yaml")) == []
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_typed_maintenance_preserves_claim_when_partial_tracker_identity_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bootstrap must verify both authority records before deleting either one."""

    repo = _governed_repo(tmp_path)
    _claims_dir, trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    real_start = claim_bootstrap.session_lifecycle.start_session

    def persist_tamper_then_fail(**kwargs: object) -> dict[str, object]:
        real_start(**kwargs)
        tracker_path = next(trackers_dir.rglob("*.yaml"))
        tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
        tracker["claim"]["session_id"] = "codex:foreign-runtime"
        tracker_path.write_text(yaml.safe_dump(tracker, sort_keys=False), encoding="utf-8")
        raise RuntimeError("simulated failure after tracker ownership changed")

    monkeypatch.setattr(
        claim_bootstrap.session_lifecycle,
        "start_session",
        persist_tamper_then_fail,
    )
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="tracker identity changed"):
        claim_bootstrap.execute_request(request)

    claims = claim_bootstrap.coordination_claims.check_claims(repo.name)
    assert len(claims) == 1
    assert claims[0].session_id == "codex:native-123"
    assert len(list(trackers_dir.rglob("*.yaml"))) == 1
    assert not (repo / "worktrees" / "fix" / "safe-lane").exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0


def test_typed_maintenance_preserves_detached_same_head_worktree_on_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    worktree = repo / "worktrees" / "fix" / "safe-lane"

    real_run = claim_bootstrap.subprocess.run

    def detach_on_population(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if str(worktree) in argv and "checkout" in argv and "fix/safe-lane" in argv:
            real_run(
                ["git", "-c", "core.hooksPath=/dev/null", "-C", str(worktree), "checkout", "--detach", "--force"],
                check=True,
                capture_output=True,
            )
            return subprocess.CompletedProcess(argv, 1, "", "simulated population failure after detach")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(claim_bootstrap.subprocess, "run", detach_on_population)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="refusing unsafe cleanup"):
        claim_bootstrap.execute_request(request)

    assert worktree.is_dir()
    listing = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    target_block = next(block for block in listing.split("\n\n") if f"worktree {worktree}" in block)
    assert "detached" in target_block


def test_typed_maintenance_preserves_untracked_content_on_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    worktree = repo / "worktrees" / "fix" / "safe-lane"
    sentinel = worktree / "preserve-me.txt"

    real_run = claim_bootstrap.subprocess.run

    def add_sentinel_on_population(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if str(worktree) in argv and "checkout" in argv and "fix/safe-lane" in argv:
            completed = real_run(argv, **kwargs)
            assert completed.returncode == 0
            sentinel.write_text("valuable concurrent state\n", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 1, "", "simulated failure after concurrent write")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(claim_bootstrap.subprocess, "run", add_sentinel_on_population)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="refusing unsafe cleanup"):
        claim_bootstrap.execute_request(request)

    assert sentinel.read_text(encoding="utf-8") == "valuable concurrent state\n"
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode == 0


def test_typed_maintenance_preserves_branch_when_worktree_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    real_run = claim_bootstrap.subprocess.run

    def fail_remove(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "worktree" in argv and "remove" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "simulated remove failure")
        if "checkout" in argv and "fix/safe-lane" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "simulated population failure")
        return real_run(argv, **kwargs)

    monkeypatch.setattr(claim_bootstrap.subprocess, "run", fail_remove)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="simulated remove failure"):
        claim_bootstrap.execute_request(request)

    worktree = repo / "worktrees" / "fix" / "safe-lane"
    assert worktree.is_dir()
    assert real_run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
    ).returncode == 0
    listing = real_run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert f"worktree {worktree}" in listing


def test_projection_recovery_parser_accepts_only_exact_paths(tmp_path: Path) -> None:
    script = tmp_path / "refresh.py"
    claims = tmp_path / "claims"
    projection = tmp_path / "projection.json"
    command = claim_bootstrap.projection_recovery_command(
        script_path=script,
        claims_dir=claims,
        projection_path=projection,
    )
    assert claim_bootstrap.parse_projection_recovery_command(
        command,
        script_path=script,
        claims_dir=claims,
        projection_path=projection,
    ) is None
    with pytest.raises(claim_bootstrap.ClaimBootstrapError):
        claim_bootstrap.parse_projection_recovery_command(
            command + " --extra",
            script_path=script,
            claims_dir=claims,
            projection_path=projection,
        )


def test_shell_operators_inside_single_quoted_json_are_inert_data(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "claim_bootstrap.py"
    raw_json = json.dumps(
        _start_payload(intent="inspect && verify; preserve | literal > text"),
        separators=(",", ":"),
    )
    command = f"/usr/bin/python3 {script} --request-json '{raw_json}'"

    request = claim_bootstrap.parse_raw_bash_command(command, script_path=script)

    assert request.intent == "inspect && verify; preserve | literal > text"


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/claim_bootstrap.py --request-json '{}'",
        "/usr/bin/python3 /tmp/session_start.py --request-json '{}'",
        "/usr/bin/python3 /tmp/claim_bootstrap.py --request-json '{}' && touch /tmp/pwned",
        "/usr/bin/python3 /tmp/claim_bootstrap.py --request-json '{}' > /tmp/result",
        "/usr/bin/python3 /tmp/claim_bootstrap.py --request-json '{}'\nwhoami",
        "python scripts/session_start.py --agent codex --project demo",
    ],
)
def test_raw_bash_grammar_rejects_compound_or_raw_lifecycle_commands(
    command: str,
    tmp_path: Path,
) -> None:
    script = tmp_path / "claim_bootstrap.py"
    with pytest.raises(claim_bootstrap.ClaimBootstrapError):
        claim_bootstrap.parse_raw_bash_command(command, script_path=script)


def test_release_self_is_rejected_by_the_bootstrap_surface() -> None:
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="release_self"):
        claim_bootstrap.parse_request_json(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "operation": "release_self",
                    "agent": "codex",
                    "project": "demo",
                    "scope": "self-owned-scope",
                }
            )
        )


@pytest.mark.parametrize(
    ("payload", "expected_operation"),
    [
        (_start_payload(), "session_start_or_update"),
        (
            {
                "schema_version": "1.0",
                "operation": "heartbeat",
                "agent": "codex",
                "project": "demo",
                "scope": "self-owned-scope",
            },
            "heartbeat",
        ),
        (
            {
                "schema_version": "1.0",
                "operation": "progress",
                "agent": "codex",
                "project": "demo",
                "scope": "self-owned-scope",
                "progress_kind": "new_diagnostic",
                "evidence_ref": "tests/test_claim_bootstrap.py",
                "next_action": "continue bounded repair",
            },
            "progress",
        ),
    ],
)
def test_remaining_self_service_operations_are_accepted(
    payload: dict[str, object],
    expected_operation: str,
) -> None:
    request = claim_bootstrap.parse_request_json(json.dumps(payload))

    assert request.operation == expected_operation


def test_ownerless_existing_slot_cannot_be_bootstrapped_as_self(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims,
        "check_claims",
        lambda _project: [
            replace(
                claim_bootstrap.coordination_claims.build_candidate_claim(
                    agent="codex",
                    project="demo",
                    scope="self-owned-scope",
                    intent="legacy ownerless claim",
                    session_id="codex:placeholder",
                    plan_ref="UNPLANNED",
                    claim_type="program",
                    repo_root="/tmp/demo",
                    worktree_path="/tmp/demo/worktrees/self-owned-scope",
                    branch="self-owned-scope",
                    session_name="self-owned-scope",
                    broader_goal="Self owned scope",
                ),
                session_id=None,
            )
        ],
    )
    request = claim_bootstrap.parse_request_json(json.dumps(_start_payload()))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="<missing>"):
        claim_bootstrap.execute_request(request)


@pytest.mark.parametrize("paths", [
    [], ["../outside"], ["/absolute"], ["src/**"], ["." , "src"],
    ["src", "src"], ["./src"], ["src//file"], ["src/"], ["C:/outside"],
])
def test_maintenance_rejects_ambiguous_write_paths(tmp_path: Path, paths: list[str]) -> None:
    with pytest.raises(claim_bootstrap.ClaimBootstrapError):
        claim_bootstrap.parse_request_json(json.dumps(
            _maintenance_payload(tmp_path, write_paths=paths)
        ))


@pytest.mark.parametrize("other_path", ["unrelated.txt", "src/adapter.py", "."])
def test_narrow_bootstrap_preserves_other_writers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, other_path: str,
) -> None:
    repo = _governed_repo(tmp_path)
    _configure_maintenance_runtime(tmp_path, monkeypatch)
    if other_path == "unrelated.txt":
        (repo / other_path).write_text("unrelated\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", other_path], check=True)
        subprocess.run(
            [
                "git", "-c", "user.name=Test User", "-c", "user.email=test@example.invalid",
                "-C", str(repo), "commit", "-m", "add unrelated fixture",
            ],
            check=True,
        )
    ok, message = claim_bootstrap.coordination_claims.create_claim(
        agent="codex", project=repo.name, scope="other-lane", intent="other work",
        plan_ref="UNPLANNED", claim_type="write", write_paths=[other_path],
        repo_root=str(repo), worktree_path=str(repo / "worktrees" / "other-lane"),
        branch="other-lane", session_id="codex:other-native",
        session_name="other-work", broader_goal="Other work",
        broad_scope_mode="bounded" if other_path == "." else None,
        broad_scope_reason="deliberately reserve the whole fixture" if other_path == "." else None,
    )
    assert ok, message
    request = claim_bootstrap.parse_request_json(json.dumps(
        _maintenance_payload(repo, write_paths=["src/adapter.py"])
    ))
    assert claim_bootstrap.execute_request(request)["ok"]
    claims = claim_bootstrap.coordination_claims.check_claims(repo.name)
    other = [c for c in claims if c.scope == "other-lane"]
    assert len(other) == 1 and other[0].write_paths == [other_path]
    if other_path != "unrelated.txt":
        candidate = next(c for c in claims if c.scope == "fix/safe-lane")
        interaction = claim_bootstrap.coordination_claims.evaluate_claim(
            candidate,
            active_claims=other,
        ).interactions[0]
        assert interaction.severity == "advisory_overlap"
        assert interaction.reason == "isolated_worktree_overlap"


@pytest.mark.parametrize(("left", "right"), [
    (".", "src/adapter.py"), ("src/adapter.py", "."), ("./", "tests"),
])
def test_whole_repository_claim_overlaps_in_both_directions(left: str, right: str) -> None:
    assert claim_bootstrap.coordination_claims._paths_overlap(left, right)


def test_bootstrap_dispatches_to_scoped_resolver_with_exact_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                    "https://github.com/Brian/repo.git"], check=True)
    calls = []
    def scoped(**kwargs):
        calls.append(kwargs)
        return claim_bootstrap.MaintenanceWorktreeAuthority(
            repo.name, "Brian/repo", "main", kwargs["remote_url"],
            str(repo), "maintenance_worktree", kwargs["branch"], "feature_branch_only",
        )
    def generic(**kwargs):
        pytest.fail("maintenance cannot use generic authority")
    monkeypatch.setattr(claim_bootstrap, "resolve_maintenance_worktree_authority", scoped)
    monkeypatch.setattr(claim_bootstrap, "resolve_repository_authority", generic)
    result = claim_bootstrap._repository_authority(repo, branch="codex/example")
    assert result.branch == "codex/example"
    assert calls == [dict(repo_root=repo, repository_identity="Brian/repo",
                          remote_url="https://github.com/Brian/repo.git", branch="codex/example")]


def test_unknown_operation_and_extra_fields_fail_closed() -> None:
    for payload in (
        {"schema_version": "1.0", "operation": "end_other", "project": "demo", "scope": "x"},
        {
            "schema_version": "1.0",
            "operation": "heartbeat",
            "project": "demo",
            "scope": "x",
            "shell": "rm -rf /tmp/demo",
        },
    ):
        with pytest.raises(claim_bootstrap.ClaimBootstrapError):
            claim_bootstrap.parse_request_json(json.dumps(payload))


@pytest.mark.parametrize(
    "raw_json",
    [
        '{"schema_version":"1.0","operation":"heartbeat","project":"a","project":"b","scope":"x"}',
        '{"schema_version":"1.0","operation":"heartbeat","project":"a","scope":"x","nested":{"a":1,"a":2}}',
    ],
)
def test_duplicate_json_object_keys_fail_closed_at_every_depth(raw_json: str) -> None:
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="duplicate object key"):
        claim_bootstrap.parse_request_json(raw_json)


def test_maintenance_creation_reconciles_canonical_checkout_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _claims_dir, _trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    receipt = claim_bootstrap.execute_request(request)

    canonical_lock = claim_bootstrap._canonical_lock_module()
    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_LOCKED
    assert receipt["result"]["canonical_lock"]["ok"] is True


def test_maintenance_lock_failure_rolls_back_lane_and_reconciles_canonical_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    claims_dir, _trackers_dir = _configure_maintenance_runtime(tmp_path, monkeypatch)
    canonical_lock = claim_bootstrap._canonical_lock_module()
    original_reconcile = canonical_lock.reconcile
    calls = 0

    def fail_after_first_reconcile(**kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        result = original_reconcile(**kwargs)
        if calls == 1:
            raise RuntimeError("simulated post-lock transaction failure")
        return result

    monkeypatch.setattr(canonical_lock, "reconcile", fail_after_first_reconcile)
    request = claim_bootstrap.parse_request_json(json.dumps(_maintenance_payload(repo)))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="transaction rolled back"):
        claim_bootstrap.execute_request(request)

    assert calls == 2
    assert not claim_bootstrap.coordination_claims.check_claims(repo.name)
    assert not (repo / "worktrees" / "fix" / "safe-lane").exists()
    assert subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", "refs/heads/fix/safe-lane"],
        capture_output=True,
        check=False,
    ).returncode != 0
    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_UNLOCKED
    assert not list(claims_dir.glob("*.yaml"))
