from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from enforced_planning.read_target import (
    ReadTargetError,
    clear_read_target,
    parse_raw_bash_command,
    resolve_read_target,
    select_read_target,
)


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "remote", "add", "origin", "git@github.com:Example/project.git")
    registry = tmp_path / "repositories.json"
    registry.write_text(
        json.dumps(
            [
                {
                    "id": "project",
                    "record_kind": "repository",
                    "status": "active",
                    "github_repo": "Example/project",
                    "name": "Example Project",
                }
            ]
        ),
        encoding="utf-8",
    )
    return repo, registry, tmp_path / "targets"


def test_select_resolve_and_clear_never_grants_mutation(tmp_path: Path) -> None:
    repo, registry, state_dir = _fixture(tmp_path)
    payload = {"session_id": "read-target-test"}

    selected = select_read_target(
        payload,
        client="codex",
        project="project",
        repo_root=str(repo),
        registry_path=registry,
        state_dir=state_dir,
    )
    resolved = resolve_read_target(payload, client="codex", state_dir=state_dir)

    assert selected["repo_root"] == str(repo)
    assert resolved["project"] == "project"
    assert resolved["mutation_authority"] is False
    cleared = clear_read_target(payload, client="codex", state_dir=state_dir)
    assert cleared["cleared"] is True
    with pytest.raises(ReadTargetError) as missing:
        resolve_read_target(payload, client="codex", state_dir=state_dir)
    assert missing.value.reason_code == "no_exact_read_target"


def test_changed_registry_record_invalidates_selection(tmp_path: Path) -> None:
    repo, registry, state_dir = _fixture(tmp_path)
    payload = {"session_id": "read-target-test"}
    select_read_target(
        payload,
        client="codex",
        project="project",
        repo_root=str(repo),
        registry_path=registry,
        state_dir=state_dir,
    )
    rows = json.loads(registry.read_text(encoding="utf-8"))
    rows[0]["name"] = "Changed"
    registry.write_text(json.dumps(rows), encoding="utf-8")

    with pytest.raises(ReadTargetError) as stale:
        resolve_read_target(payload, client="codex", state_dir=state_dir)
    assert stale.value.reason_code == "read_target_record_stale"


def test_selection_rejects_relative_or_unregistered_repository(tmp_path: Path) -> None:
    repo, registry, state_dir = _fixture(tmp_path)
    payload = {"session_id": "read-target-test"}
    with pytest.raises(ReadTargetError) as relative:
        select_read_target(
            payload,
            client="codex",
            project="project",
            repo_root="project",
            registry_path=registry,
            state_dir=state_dir,
        )
    assert relative.value.reason_code == "read_target_repo_not_absolute"
    with pytest.raises(ReadTargetError) as missing:
        select_read_target(
            payload,
            client="codex",
            project="other",
            repo_root=str(repo),
            registry_path=registry,
            state_dir=state_dir,
        )
    assert missing.value.reason_code == "read_target_not_registered"


def test_raw_command_parser_accepts_only_exact_uncomposed_transaction(tmp_path: Path) -> None:
    script = tmp_path / "session_read_target.py"
    request = {
        "schema_version": "1.0",
        "operation": "select",
        "client": "codex",
        "project": "project",
        "repo_root": "/absolute/project",
        "registry_path": "/absolute/registry.json",
    }
    command = f"/usr/bin/python3 {script} --request-json '{json.dumps(request)}'"
    assert parse_raw_bash_command(command, script_path=script) == request
    for invalid in (command + " EXTRA=1", command + " && true", command.replace("/absolute/project", "../project")):
        with pytest.raises(ReadTargetError):
            parse_raw_bash_command(invalid, script_path=script)
