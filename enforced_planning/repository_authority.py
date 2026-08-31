"""Generic, fail-closed repository mutation-authority provider boundary."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class RepositoryAuthorityError(ValueError):
    """The configured provider could not produce one trustworthy decision."""


DEFAULT_PROVIDER_CONFIG = (
    Path.home() / ".config" / "enforced-planning" / "repository-authority-provider-v1.json"
)


@dataclass(frozen=True)
class RepositoryAuthority:
    project_id: str
    repository_identity: str
    default_branch: str
    remote_url: str


@dataclass(frozen=True)
class MaintenanceWorktreeAuthority:
    """An exact worktree-creation grant, never general repository-write authority."""

    project_id: str
    repository_identity: str
    default_branch: str
    remote_url: str
    repo_root: str
    operation: str
    branch: str
    mutation_authority: str


def _strict_object(raw: str, *, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise RepositoryAuthorityError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise RepositoryAuthorityError(f"{label} is not valid JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise RepositoryAuthorityError(f"{label} must be one JSON object")
    return value


def _load_provider(config_path: Path) -> Path:
    try:
        info = config_path.stat()
        config = _strict_object(config_path.read_text(encoding="utf-8"), label="provider config")
    except OSError as exc:
        raise RepositoryAuthorityError(f"repository authority provider is unavailable: {exc}") from exc
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise RepositoryAuthorityError("repository authority provider config is group/world writable")
    if set(config) != {"schema_version", "provider_path", "provider_sha256"}:
        raise RepositoryAuthorityError("provider config has unknown or missing fields")
    if config["schema_version"] != "1.0":
        raise RepositoryAuthorityError("provider config schema_version must be '1.0'")
    provider = Path(str(config["provider_path"]))
    expected = str(config["provider_sha256"])
    if not provider.is_absolute() or ".." in provider.parts or provider.resolve() != provider:
        raise RepositoryAuthorityError("provider_path must be one canonical absolute path")
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise RepositoryAuthorityError("provider_sha256 must be one lowercase SHA-256 digest")
    try:
        source = provider.read_bytes()
        provider_info = provider.stat()
    except OSError as exc:
        raise RepositoryAuthorityError(f"repository authority provider cannot be read: {exc}") from exc
    if not stat.S_ISREG(provider_info.st_mode) or not os.access(provider, os.X_OK):
        raise RepositoryAuthorityError("repository authority provider must be an executable regular file")
    if stat.S_IMODE(provider_info.st_mode) & 0o022:
        raise RepositoryAuthorityError("repository authority provider is group/world writable")
    if hashlib.sha256(source).hexdigest() != expected:
        raise RepositoryAuthorityError("repository authority provider digest mismatch; reinstall its adapter")
    return provider


def _provider_response(request: dict[str, str], config_path: Path) -> dict[str, Any]:
    """Call the pinned adapter without falling back to broader authority."""
    provider = _load_provider(config_path)
    try:
        completed = subprocess.run(
            [str(provider)],
            input=json.dumps(request, separators=(",", ":")),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepositoryAuthorityError(f"repository authority provider failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "provider denied the repository"
        raise RepositoryAuthorityError(detail)
    return _strict_object(completed.stdout, label="provider response")


def resolve_repository_authority(
    *,
    repo_root: Path,
    repository_identity: str,
    remote_url: str,
    config_path: Path = DEFAULT_PROVIDER_CONFIG,
) -> RepositoryAuthority:
    """Resolve legacy v1 general authority; scoped grants cannot satisfy it."""
    response = _provider_response({
        "schema_version": "1.0",
        "repo_root": str(repo_root),
        "repository_identity": repository_identity,
        "remote_url": remote_url,
    }, config_path)
    expected_fields = {
        "schema_version", "allowed", "project_id", "repository_identity", "default_branch", "remote_url"
    }
    if set(response) != expected_fields:
        raise RepositoryAuthorityError("provider response has unknown or missing fields")
    if response["schema_version"] != "1.0" or response["allowed"] is not True:
        raise RepositoryAuthorityError("repository authority provider did not allow mutation")
    if response["repository_identity"] != repository_identity or response["remote_url"] != remote_url:
        raise RepositoryAuthorityError("provider response does not bind the exact inspected repository")
    project_id = response["project_id"]
    default_branch = response["default_branch"]
    if not isinstance(project_id, str) or not project_id.strip():
        raise RepositoryAuthorityError("provider response has no stable project id")
    if not isinstance(default_branch, str) or not default_branch.strip():
        raise RepositoryAuthorityError("provider response has no default branch")
    checked = subprocess.run(
        ["git", "check-ref-format", "--branch", default_branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if checked.returncode != 0:
        raise RepositoryAuthorityError("provider default branch is invalid")
    return RepositoryAuthority(project_id.strip(), repository_identity, default_branch, remote_url)


def _literal_branch(value: object) -> bool:
    """Reject Git shorthands whose meaning depends on the caller's checkout."""
    if not isinstance(value, str) or not value or value != value.strip() or value.startswith("refs/"):
        return False
    checked = subprocess.run(
        ["git", "check-ref-format", "--branch", value],
        capture_output=True, text=True, check=False,
    )
    return checked.returncode == 0 and checked.stdout.strip() == value


def resolve_maintenance_worktree_authority(
    *,
    repo_root: Path,
    repository_identity: str,
    remote_url: str,
    branch: str,
    config_path: Path = DEFAULT_PROVIDER_CONFIG,
) -> MaintenanceWorktreeAuthority:
    """Require a v2 grant bound to this operation, root, identity, and branch."""
    if not _literal_branch(branch):
        raise RepositoryAuthorityError("invalid maintenance branch")
    request = {
        "schema_version": "2.0",
        "repo_root": str(repo_root),
        "repository_identity": repository_identity,
        "remote_url": remote_url,
        "operation": "maintenance_worktree",
        "branch": branch,
    }
    response = _provider_response(request, config_path)
    if set(response) != set(request) | {
        "allowed", "project_id", "default_branch", "mutation_authority",
    }:
        raise RepositoryAuthorityError("scoped provider response has unknown or missing fields")
    if response["allowed"] is not True or any(
        response[key] != value for key, value in request.items()
    ):
        raise RepositoryAuthorityError("scoped provider response does not bind the exact request")
    if not isinstance(response["mutation_authority"], str) or response["mutation_authority"] not in {
        "normal_push", "feature_branch_only",
    }:
        raise RepositoryAuthorityError("unsupported scoped mutation authority")
    project_id, default = response["project_id"], response["default_branch"]
    if not isinstance(project_id, str) or not project_id.strip():
        raise RepositoryAuthorityError("scoped provider response has no project id")
    if (
        not _literal_branch(default)
        or branch == default
    ):
        raise RepositoryAuthorityError("maintenance target must be a non-default branch")
    return MaintenanceWorktreeAuthority(
        project_id, repository_identity, default, remote_url, str(repo_root),
        "maintenance_worktree", branch, response["mutation_authority"],
    )
