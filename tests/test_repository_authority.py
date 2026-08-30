from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enforced_planning.repository_authority import (
    RepositoryAuthority,
    RepositoryAuthorityError,
    resolve_repository_authority,
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
