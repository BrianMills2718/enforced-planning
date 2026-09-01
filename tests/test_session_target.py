from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning.prewrite_claim_projection import write_projection
from enforced_planning.session_target import (
    SessionTargetError,
    effective_session_id,
    resolve_exact_session_target,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _authority(tmp_path: Path, *, session_id: str = "codex:parent") -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = repo / "worktrees" / "lane"
    worktree.parent.mkdir()
    _git(repo, "worktree", "add", "-b", "lane", str(worktree))
    claims = tmp_path / "claims"
    claims.mkdir()
    now = datetime.now(timezone.utc)
    (claims / "claim.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "agent": "codex",
                "projects": ["repo"],
                "scope": "lane",
                "intent": "test",
                "claim_type": "program",
                "plan_ref": "UNPLANNED",
                "write_paths": ["src"],
                "repo_root": str(repo),
                "worktree_path": str(worktree),
                "branch": "lane",
                "session_id": session_id,
                "session_name": "test-lane",
                "broader_goal": "Exercise exact session targeting",
                "tracker_path": str(tmp_path / "tracker.yaml"),
                "status": "active",
                "heartbeat_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    projection = tmp_path / "projection.json"
    write_projection(claims_dir=claims, projection_path=projection)
    return repo, worktree, claims, projection


def test_effective_identity_prefers_child_agent_id() -> None:
    payload = {"session_id": "parent", "agent_id": "child"}
    assert effective_session_id(payload, "codex") == "codex:child"


def test_parent_claim_does_not_authorize_child_but_child_claim_does(tmp_path: Path) -> None:
    _repo, worktree, claims, projection = _authority(tmp_path)
    child = {"session_id": "parent", "agent_id": "child"}

    with pytest.raises(SessionTargetError, match="codex:child"):
        resolve_exact_session_target(
            child,
            client="codex",
            claims_dir=claims,
            projection_path=projection,
        )

    claim_path = claims / "claim.yaml"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["session_id"] = "codex:child"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims, projection_path=projection)

    target = resolve_exact_session_target(
        child,
        client="codex",
        claims_dir=claims,
        projection_path=projection,
    )
    assert target.worktree_path == worktree


def test_bootstrap_target_resolves_for_context_without_mutation_authority(tmp_path: Path) -> None:
    """A v6 bootstrap claim selects its real target while legacy authority stays detached."""

    _repo, worktree, claims, projection = _authority(tmp_path)
    claim_path = claims / "claim.yaml"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim.update(
        schema_version=6,
        write_paths=["."],
        broad_scope_mode="bootstrap",
        broad_scope_reason="construct and narrow the maintenance lane",
        target_worktree_path=str(worktree),
        worktree_path=f"{worktree}.bootstrap-no-mutation-authority",
    )
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims, projection_path=projection)

    target = resolve_exact_session_target(
        {"session_id": "parent"},
        client="codex",
        claims_dir=claims,
        projection_path=projection,
    )

    assert target.worktree_path == worktree
    projected = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert projected["worktree_path"] != projected["target_worktree_path"]


def test_bootstrap_target_from_different_git_repository_fails_closed(tmp_path: Path) -> None:
    """Digest-bound YAML cannot redirect instruction context to another repository."""

    _repo, worktree, claims, projection = _authority(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-b", "lane")
    _git(other, "config", "user.name", "Test")
    _git(other, "config", "user.email", "test@example.com")
    (other / "README.md").write_text("other\n", encoding="utf-8")
    _git(other, "add", "README.md")
    _git(other, "commit", "-m", "other")
    claim_path = claims / "claim.yaml"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim.update(
        schema_version=6,
        write_paths=["."],
        broad_scope_mode="bootstrap",
        broad_scope_reason="attempt a wrong-repository redirect",
        target_worktree_path=str(other),
        worktree_path=f"{other}.bootstrap-no-mutation-authority",
    )
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims, projection_path=projection)

    with pytest.raises(SessionTargetError) as mismatch:
        resolve_exact_session_target(
            {"session_id": "parent"},
            client="codex",
            claims_dir=claims,
            projection_path=projection,
        )

    assert mismatch.value.reason_code == "claim_git_identity_mismatch"


def test_stale_projection_and_branch_mismatch_fail_closed(tmp_path: Path) -> None:
    _repo, _worktree, claims, projection = _authority(tmp_path)
    payload = {"session_id": "parent"}
    (claims / "unprojected.yaml").write_text("agent: codex\n", encoding="utf-8")
    with pytest.raises(SessionTargetError) as stale:
        resolve_exact_session_target(
            payload,
            client="codex",
            claims_dir=claims,
            projection_path=projection,
        )
    assert stale.value.reason_code == "projection_unavailable_or_stale"

    (claims / "unprojected.yaml").unlink()
    claim_path = claims / "claim.yaml"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["branch"] = "wrong-branch"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims, projection_path=projection)
    with pytest.raises(SessionTargetError) as mismatch:
        resolve_exact_session_target(
            payload,
            client="codex",
            claims_dir=claims,
            projection_path=projection,
        )
    assert mismatch.value.reason_code in {"claim_not_healthy", "claim_git_identity_mismatch"}


def test_two_healthy_claims_are_ambiguous(tmp_path: Path) -> None:
    repo, first, claims, projection = _authority(tmp_path)
    second = repo / "worktrees" / "lane-two"
    _git(repo, "worktree", "add", "-b", "lane-two", str(second))
    payload = yaml.safe_load((claims / "claim.yaml").read_text(encoding="utf-8"))
    payload.update(scope="lane-two", worktree_path=str(second), branch="lane-two")
    (claims / "claim-two.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims, projection_path=projection)

    with pytest.raises(SessionTargetError) as ambiguous:
        resolve_exact_session_target(
            {"session_id": "parent"},
            client="codex",
            claims_dir=claims,
            projection_path=projection,
        )
    assert ambiguous.value.reason_code == "ambiguous_exact_session_target"

    assert resolve_exact_session_target(
        {"session_id": "parent"},
        client="codex",
        claims_dir=claims,
        projection_path=projection,
        target_worktree=first,
    ).worktree_path == first
    assert resolve_exact_session_target(
        {"session_id": "parent"},
        client="codex",
        claims_dir=claims,
        projection_path=projection,
        target_worktree=second,
    ).worktree_path == second


def test_explicit_unclaimed_worktree_fails_closed(tmp_path: Path) -> None:
    _repo, _worktree, claims, projection = _authority(tmp_path)

    with pytest.raises(SessionTargetError) as unclaimed:
        resolve_exact_session_target(
            {"session_id": "parent"},
            client="codex",
            claims_dir=claims,
            projection_path=projection,
            target_worktree=tmp_path / "unclaimed",
        )

    assert unclaimed.value.reason_code == "target_worktree_not_claimed"
