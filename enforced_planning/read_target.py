"""Session-bound read/context targets that never grant mutation authority."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from enforced_planning.claim_bootstrap import _github_repo_from_remote
from enforced_planning.session_target import effective_session_id

DEFAULT_READ_TARGET_DIR = Path.home() / ".claude" / "coordination" / "read-targets-v1"
SELECT_REQUEST_FIELDS = {
    "schema_version",
    "operation",
    "client",
    "project",
    "repo_root",
    "registry_path",
}
CLEAR_REQUEST_FIELDS = {"schema_version", "operation", "client"}
STATE_FIELDS = {
    "schema_version",
    "session_id",
    "client",
    "project",
    "repo_root",
    "repository_identity",
    "registry_path",
    "record_sha256",
    "selected_at",
}


class ReadTargetError(ValueError):
    """The requested read target is missing, stale, or not registry-backed."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _state_path(session_id: str, state_dir: Path) -> Path:
    name = hashlib.sha256(session_id.encode("utf-8")).hexdigest() + ".json"
    return state_dir.expanduser().resolve() / name


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ReadTargetError("read_target_git_identity_invalid", completed.stderr.strip())
    return completed.stdout.strip()


def _canonical_repository(repo_root: str) -> tuple[Path, str]:
    raw = Path(repo_root).expanduser()
    if not raw.is_absolute():
        raise ReadTargetError("read_target_repo_not_absolute", "repo_root must be absolute")
    repo = raw.resolve()
    if not repo.is_dir() or Path(_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ReadTargetError("read_target_git_identity_invalid", "repo_root is not a canonical Git root")
    remote = _git(repo, "remote", "get-url", "origin")
    try:
        identity = _github_repo_from_remote(remote)
    except Exception as exc:
        raise ReadTargetError("read_target_repository_identity_invalid", str(exc)) from exc
    return repo, identity


def _registry_record(registry_path: Path, project: str, identity: str) -> dict[str, Any]:
    path = registry_path.expanduser()
    if not path.is_absolute():
        raise ReadTargetError("read_target_registry_not_absolute", "registry_path must be absolute")
    try:
        payload = json.loads(path.resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReadTargetError("read_target_registry_unavailable", str(exc)) from exc
    if not isinstance(payload, list):
        raise ReadTargetError("read_target_registry_invalid", "repository registry root must be a list")
    matches = [
        row
        for row in payload
        if isinstance(row, dict)
        and row.get("record_kind") == "repository"
        and row.get("status") == "active"
        and row.get("id") == project
        and str(row.get("github_repo", "")).casefold() == identity.casefold()
    ]
    if len(matches) != 1:
        raise ReadTargetError(
            "read_target_not_registered",
            f"project {project!r} and repository {identity!r} must match one active record; found {len(matches)}",
        )
    return matches[0]


def select_read_target(
    payload: dict[str, Any],
    *,
    client: str,
    project: str,
    repo_root: str,
    registry_path: Path,
    state_dir: Path = DEFAULT_READ_TARGET_DIR,
) -> dict[str, Any]:
    """Persist one registry-backed context target for the exact native session."""

    session_id = effective_session_id(payload, client)
    repo, identity = _canonical_repository(repo_root)
    record = _registry_record(registry_path, project, identity)
    state = {
        "schema_version": "1.0",
        "session_id": session_id,
        "client": client,
        "project": project,
        "repo_root": str(repo),
        "repository_identity": identity,
        "registry_path": str(registry_path.expanduser().resolve()),
        "record_sha256": _json_digest(record),
        "selected_at": datetime.now(UTC).isoformat(),
    }
    directory = state_dir.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    target = _state_path(session_id, directory)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as handle:
        json.dump(state, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return {**state, "state_path": str(target), "mutation_authority": False}


def resolve_read_target(
    payload: dict[str, Any],
    *,
    client: str,
    state_dir: Path = DEFAULT_READ_TARGET_DIR,
) -> dict[str, Any]:
    """Resolve and revalidate one session read target against its exact record."""

    session_id = effective_session_id(payload, client)
    target = _state_path(session_id, state_dir)
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReadTargetError("no_exact_read_target", str(exc)) from exc
    if not isinstance(state, dict) or set(state) != STATE_FIELDS or state.get("schema_version") != "1.0":
        raise ReadTargetError("read_target_state_invalid", "read target state has an invalid schema")
    if state.get("session_id") != session_id or state.get("client") != client:
        raise ReadTargetError("read_target_session_mismatch", "read target belongs to another native session")
    repo, identity = _canonical_repository(str(state["repo_root"]))
    if identity.casefold() != str(state["repository_identity"]).casefold():
        raise ReadTargetError("read_target_repository_identity_invalid", "repository origin identity changed")
    record = _registry_record(Path(str(state["registry_path"])), str(state["project"]), identity)
    if _json_digest(record) != state.get("record_sha256"):
        raise ReadTargetError("read_target_record_stale", "selected repository record changed; select it again")
    return {**state, "repo_root": str(repo), "state_path": str(target), "mutation_authority": False}


def clear_read_target(
    payload: dict[str, Any],
    *,
    client: str,
    state_dir: Path = DEFAULT_READ_TARGET_DIR,
) -> dict[str, Any]:
    session_id = effective_session_id(payload, client)
    target = _state_path(session_id, state_dir)
    target.unlink(missing_ok=True)
    return {"schema_version": "1.0", "session_id": session_id, "cleared": True, "mutation_authority": False}


def validate_request(request: object) -> dict[str, Any]:
    """Validate the strict select/clear transaction independent of shell syntax."""

    if not isinstance(request, dict):
        raise ReadTargetError("read_target_command_invalid", "request must be an object")
    expected_fields = SELECT_REQUEST_FIELDS if request.get("operation") == "select" else CLEAR_REQUEST_FIELDS
    if set(request) != expected_fields:
        raise ReadTargetError("read_target_command_invalid", "request fields do not match the exact schema")
    if request.get("schema_version") != "1.0" or request.get("operation") not in {"select", "clear"}:
        raise ReadTargetError("read_target_command_invalid", "unsupported request schema or operation")
    if request.get("client") not in {"codex", "claude-code"}:
        raise ReadTargetError("read_target_command_invalid", "client must be codex or claude-code")
    if request.get("operation") == "select":
        if not isinstance(request.get("project"), str) or not request["project"].strip():
            raise ReadTargetError("read_target_command_invalid", "project must be non-empty")
        for field in ("repo_root", "registry_path"):
            value = request.get(field)
            path = Path(value) if isinstance(value, str) else Path("")
            if not path.is_absolute() or ".." in path.parts:
                raise ReadTargetError("read_target_command_invalid", f"{field} must be absolute without traversal")
    return request


def parse_raw_bash_command(command: str, *, script_path: Path) -> dict[str, Any]:
    """Parse only the exact uncomposed read-target CLI transaction."""

    if not command.strip() or "\n" in command or "\r" in command:
        raise ReadTargetError("read_target_command_invalid", "command must be one line")
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        raise ReadTargetError("read_target_command_invalid", str(exc)) from exc
    expected = ["/usr/bin/python3", str(script_path.resolve()), "--request-json"]
    if len(argv) != 4 or argv[:3] != expected:
        raise ReadTargetError("read_target_command_invalid", "command does not match the exact read-target grammar")
    try:
        request = json.loads(argv[3])
    except json.JSONDecodeError as exc:
        raise ReadTargetError("read_target_command_invalid", str(exc)) from exc
    return validate_request(request)


__all__ = [
    "DEFAULT_READ_TARGET_DIR",
    "ReadTargetError",
    "clear_read_target",
    "parse_raw_bash_command",
    "resolve_read_target",
    "select_read_target",
    "validate_request",
]
