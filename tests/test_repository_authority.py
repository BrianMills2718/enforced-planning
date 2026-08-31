from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enforced_planning.repository_authority import (
    RepositoryAuthority,
    RepositoryAuthorityError,
    resolve_repository_authority,
    MaintenanceWorktreeAuthority,
    resolve_maintenance_worktree_authority,
)


def _provider(tmp_path: Path, response: dict[str, object]) -> Path:
    path = tmp_path / "provider"
    path.write_text(
        "#!/usr/bin/python3\n"
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        f"response = {response!r}\n"
        "response.setdefault('repository_identity', request['repository_identity'])\n"
        "response.setdefault('remote_url', request['remote_url'])\n"
        "print(json.dumps(response))\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _config(tmp_path: Path, provider: Path, *, digest: str | None = None) -> Path:
    path = tmp_path / "provider.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "provider_path": str(provider),
                "provider_sha256": digest or hashlib.sha256(provider.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_exact_provider_decision_is_returned(tmp_path: Path) -> None:
    provider = _provider(
        tmp_path,
        {
            "schema_version": "1.0",
            "allowed": True,
            "project_id": "agent-skills",
            "default_branch": "main",
        },
    )
    authority = resolve_repository_authority(
        repo_root=Path("/repo"),
        repository_identity="Brian/agent-skills",
        remote_url="git@github.com:Brian/agent-skills.git",
        config_path=_config(tmp_path, provider),
    )
    assert authority == RepositoryAuthority(
        "agent-skills", "Brian/agent-skills", "main", "git@github.com:Brian/agent-skills.git"
    )


def test_provider_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    provider = _provider(tmp_path, {})
    with pytest.raises(RepositoryAuthorityError, match="digest mismatch"):
        resolve_repository_authority(
            repo_root=Path("/repo"),
            repository_identity="Brian/repo",
            remote_url="git@github.com:Brian/repo.git",
            config_path=_config(tmp_path, provider, digest="0" * 64),
        )


@pytest.mark.parametrize("mutation", ["identity", "extra", "denied"])
def test_ambiguous_or_unbound_provider_response_fails_closed(tmp_path: Path, mutation: str) -> None:
    response: dict[str, object] = {
        "schema_version": "1.0",
        "allowed": mutation != "denied",
        "project_id": "repo",
        "default_branch": "main",
    }
    if mutation == "identity":
        response["repository_identity"] = "SomeoneElse/repo"
    if mutation == "extra":
        response["extra"] = True
    provider = _provider(tmp_path, response)
    with pytest.raises(RepositoryAuthorityError):
        resolve_repository_authority(
            repo_root=Path("/repo"),
            repository_identity="Brian/repo",
            remote_url="git@github.com:Brian/repo.git",
            config_path=_config(tmp_path, provider),
        )


def _scoped_response() -> dict[str, object]:
    return {
        "schema_version": "2.0", "allowed": True,
        "project_id": "company-planning", "default_branch": "main",
        "repo_root": "/repo", "operation": "maintenance_worktree",
        "branch": "codex/reconcile", "mutation_authority": "feature_branch_only",
    }


def test_scoped_grant_is_distinct_from_general_authority(tmp_path: Path) -> None:
    provider = _provider(tmp_path, _scoped_response())
    config = _config(tmp_path, provider)
    kwargs = dict(
        repo_root=Path("/repo"), repository_identity="Inside-Success/company-planning",
        remote_url="https://github.com/Inside-Success/company-planning.git",
        config_path=config,
    )
    authority = resolve_maintenance_worktree_authority(**kwargs, branch="codex/reconcile")
    assert isinstance(authority, MaintenanceWorktreeAuthority)
    assert not isinstance(authority, RepositoryAuthority)
    assert authority.branch == "codex/reconcile"
    with pytest.raises(RepositoryAuthorityError):
        resolve_repository_authority(**kwargs)


@pytest.mark.parametrize(("field", "value"), [
    ("schema_version", "1.0"), ("operation", "push"),
    ("branch", "codex/other"), ("repo_root", "/elsewhere"),
    ("repository_identity", "Other/repo"), ("remote_url", "https://example.com"),
    ("allowed", False), ("allowed", 1), ("extra", True),
    ("mutation_authority", "read_only"), ("default_branch", "codex/reconcile"),
    ("default_branch", "bad branch"), ("project_id", ""),
])
def test_scoped_response_must_bind_every_field(
    tmp_path: Path, field: str, value: object,
) -> None:
    response = _scoped_response()
    response[field] = value
    provider = _provider(tmp_path, response)
    with pytest.raises(RepositoryAuthorityError):
        resolve_maintenance_worktree_authority(
            repo_root=Path("/repo"), repository_identity="Inside-Success/company-planning",
            remote_url="https://github.com/Inside-Success/company-planning.git",
            branch="codex/reconcile", config_path=_config(tmp_path, provider),
        )


@pytest.mark.parametrize("branch", ["", "bad branch", "refs/heads/main", "-bad", "HEAD"])
def test_invalid_scoped_branch_is_rejected_before_provider(tmp_path: Path, branch: str) -> None:
    with pytest.raises(RepositoryAuthorityError, match="invalid maintenance branch"):
        resolve_maintenance_worktree_authority(
            repo_root=Path("/repo"), repository_identity="Inside-Success/company-planning",
            remote_url="https://github.com/Inside-Success/company-planning.git",
            branch=branch, config_path=tmp_path / "missing-config",
        )
