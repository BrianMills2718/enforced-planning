"""Archival of orphaned session trackers that no claim can close."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import (
    coordination_claims,
    session_contracts,
    session_lifecycle,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _seed_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    return repo


def _write_tracker(
    sessions_dir: Path,
    *,
    project: str = "demo",
    agent: str = "claude-code",
    scope: str = "lane",
    repo_root: Path | None = None,
    worktree_path: Path,
    branch: str | None = "lane",
) -> Path:
    path = sessions_dir / project / f"{agent}__{project}__session__goal.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "claim": {
            "agent": agent,
            "project": project,
            "scope": scope,
            "intent": "exercise orphaned tracker archival",
            "plan_ref": "UNPLANNED",
            "repo_root": str(repo_root) if repo_root is not None else None,
            "worktree_path": str(worktree_path),
            "branch": branch,
            "session_id": f"{agent}:orphan-fixture",
            "session_name": "orphan-fixture",
            "broader_goal": "Prove orphaned trackers archive safely",
            "tracker_path": str(path),
        },
        "tracker": {
            "current_phase": "implementation",
            "intended_next_phases": [],
            "depends_on_repos": [],
            "requires_shared_infra_changes": False,
            "stop_conditions": [],
            "notes": "",
        },
        "timestamps": {
            "created_at": "2026-08-17T03:38:54.452525+00:00",
            "updated_at": "2026-08-17T03:38:54.452525+00:00",
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def coordination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    sessions_dir = tmp_path / "coordination" / "sessions"
    claims_dir = tmp_path / "coordination" / "claims"
    sessions_dir.mkdir(parents=True)
    claims_dir.mkdir(parents=True)
    monkeypatch.setattr(session_contracts, "DEFAULT_SESSION_TRACKERS_DIR", sessions_dir)
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    return {"sessions": sessions_dir, "claims": claims_dir}


def test_archives_a_genuine_orphan_and_leaves_the_branch_untouched(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path)
    _git(repo, "branch", "lane")
    tracker = _write_tracker(
        coordination["sessions"],
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
    )

    result = session_lifecycle.archive_orphaned_session_tracker(
        tracker_path=tracker,
        expected_tracker_sha256=_digest(tracker),
    )

    assert result["action"] == "archived_orphaned_tracker"
    assert result["branch_action"] == "untouched"
    assert result["branch_state"] == "branch_present_integrated"
    assert result["filesystem_action"] == "not_attempted_absent_recorded_worktree"
    assert not tracker.exists()

    archived = Path(result["archived_tracker_path"])
    assert archived.is_file()
    assert archived.parent.name == "demo"
    persisted = yaml.safe_load(archived.read_text(encoding="utf-8"))
    assert persisted["tracker"]["current_phase"] == "closed"
    assert persisted["archive"]["reason"] == "orphaned_tracker_no_claim_no_worktree"
    assert persisted["archive"]["branch_action"] == "untouched"
    assert persisted["claim"]["scope"] == "lane"

    # The branch and its commit are still exactly where they were.
    assert _git(repo, "rev-parse", "lane") == _git(repo, "rev-parse", "main")
    assert "lane" in _git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_refuses_when_the_recorded_worktree_still_exists(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path)
    live_worktree = tmp_path / "live-worktree"
    live_worktree.mkdir()
    tracker = _write_tracker(
        coordination["sessions"],
        repo_root=repo,
        worktree_path=live_worktree,
    )

    with pytest.raises(ValueError, match="rejects an existing recorded worktree"):
        session_lifecycle.archive_orphaned_session_tracker(
            tracker_path=tracker,
            expected_tracker_sha256=_digest(tracker),
        )
    assert tracker.is_file()


def test_refuses_when_a_live_claim_still_exists(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path)
    tracker = _write_tracker(
        coordination["sessions"],
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
    )
    claim_file = coordination["claims"] / coordination_claims._claim_filename(
        "claude-code", "demo", "lane"
    )
    claim_file.write_text(yaml.safe_dump({"agent": "claude-code"}), encoding="utf-8")

    with pytest.raises(ValueError, match="still exists; that is a live lane"):
        session_lifecycle.archive_orphaned_session_tracker(
            tracker_path=tracker,
            expected_tracker_sha256=_digest(tracker),
        )
    assert tracker.is_file()


def test_refuses_on_a_tracker_digest_mismatch(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path)
    tracker = _write_tracker(
        coordination["sessions"],
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
    )

    with pytest.raises(ValueError, match="digest mismatch"):
        session_lifecycle.archive_orphaned_session_tracker(
            tracker_path=tracker,
            expected_tracker_sha256="0" * 64,
        )
    assert tracker.is_file()


def test_refuses_when_the_branch_still_holds_unique_commits(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path)
    _git(repo, "checkout", "-b", "lane")
    (repo / "unique.md").write_text("unique work\n", encoding="utf-8")
    _git(repo, "add", "unique.md")
    _git(repo, "commit", "-m", "unique lane work")
    _git(repo, "checkout", "main")
    tracker = _write_tracker(
        coordination["sessions"],
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
    )

    with pytest.raises(ValueError, match="commit\\(s\\) with no patch-equivalent"):
        session_lifecycle.archive_orphaned_session_tracker(
            tracker_path=tracker,
            expected_tracker_sha256=_digest(tracker),
        )
    assert tracker.is_file()
    assert "lane" in _git(repo, "branch", "--format=%(refname:short)").splitlines()

    result = session_lifecycle.archive_orphaned_session_tracker(
        tracker_path=tracker,
        expected_tracker_sha256=_digest(tracker),
        allow_unique_branch_commits=True,
    )
    assert result["branch_state"] == "branch_present_with_unique_commits"
    assert result["unique_commits_authorized"] is True
    assert len(result["unique_commits"]) == 1
    assert result["branch_action"] == "untouched"
    assert "lane" in _git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_squash_merged_branch_is_not_treated_as_unique_work(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    """git cherry is patch-based; merge-base --is-ancestor would refuse here."""

    repo = _seed_repo(tmp_path)
    _git(repo, "checkout", "-b", "lane")
    (repo / "feature.md").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "feature.md")
    _git(repo, "commit", "-m", "feature work")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--squash", "lane")
    _git(repo, "commit", "-m", "feature work (#42)")
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", "lane", "main"],
            capture_output=True,
            check=False,
        ).returncode
        != 0
    )
    tracker = _write_tracker(
        coordination["sessions"],
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
    )

    result = session_lifecycle.archive_orphaned_session_tracker(
        tracker_path=tracker,
        expected_tracker_sha256=_digest(tracker),
    )

    assert result["unique_commits"] == []
    assert result["branch_state"] == "branch_present_integrated"


def test_refuses_a_tracker_outside_the_canonical_sessions_tree(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    stray = tmp_path / "stray.yaml"
    stray.write_text(yaml.safe_dump({"claim": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="canonical session-tracker tree"):
        session_lifecycle.archive_orphaned_session_tracker(
            tracker_path=stray,
            expected_tracker_sha256=_digest(stray),
        )
    assert stray.is_file()


def test_refuses_to_overwrite_an_existing_archive_entry(
    coordination: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _seed_repo(tmp_path)
    tracker = _write_tracker(
        coordination["sessions"],
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
    )
    archive_root = tmp_path / "coordination" / "sessions-archive"
    from datetime import UTC, datetime

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    occupied = archive_root / day / "demo" / tracker.name
    occupied.parent.mkdir(parents=True)
    occupied.write_text("already archived\n", encoding="utf-8")

    with pytest.raises(ValueError, match="refuses to overwrite an existing archive entry"):
        session_lifecycle.archive_orphaned_session_tracker(
            tracker_path=tracker,
            expected_tracker_sha256=_digest(tracker),
        )
    assert tracker.is_file()
    assert occupied.read_text(encoding="utf-8") == "already archived\n"


def test_cli_archives_through_the_wrapper(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    repo = _seed_repo(tmp_path)
    tracker = _write_tracker(
        coordination["sessions"],
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
        branch=None,
    )
    script = Path(session_lifecycle.__file__).resolve().parents[1] / "scripts" / "session_archive_tracker.py"

    import sys

    sys.path.insert(0, str(script.parent))
    try:
        import importlib

        module = importlib.import_module("session_archive_tracker")
        importlib.reload(module)
        exit_code = module.main(
            [
                "--tracker-path",
                str(tracker),
                "--tracker-sha256",
                _digest(tracker),
                "--json",
            ]
        )
    finally:
        sys.path.remove(str(script.parent))

    assert exit_code == 0
    assert not tracker.exists()


def test_archives_a_legacy_agent_id_tracker(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    """A legacy per-lane agent id must not block archival of a genuine orphan.

    Before 2026-09-08 this raised "names an unsupported agent". 23 of 74
    orphaned trackers in the live workspace were unarchivable for that reason
    alone, written with identities such as 'codex-evidence-reader-wiki' and
    'codex-root'. Because claim creation enforced SUPPORTED_AGENTS while
    start_session did not, those trackers could never have a matching claim,
    so session-close could not reach them either: permanent residue.
    """
    repo = _seed_repo(tmp_path)
    _git(repo, "branch", "lane")
    tracker = _write_tracker(
        coordination["sessions"],
        agent="codex-evidence-reader-wiki",
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
    )

    result = session_lifecycle.archive_orphaned_session_tracker(
        tracker_path=tracker,
        expected_tracker_sha256=_digest(tracker),
    )

    assert result["action"] == "archived_orphaned_tracker"
    assert result["agent"] == "codex-evidence-reader-wiki"
    # The unusual identity stays visible rather than being normalised away.
    assert result["agent_supported"] is False
    assert result["branch_action"] == "untouched"
    assert not tracker.exists()
    assert Path(result["archived_tracker_path"]).is_file()
    # The branch is untouched, as for any other archival.
    assert "lane" in _git(repo, "branch", "--format=%(refname:short)").splitlines()


def test_supported_agent_still_reported_as_supported(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    """The receipt field must discriminate, not report False for everyone."""
    repo = _seed_repo(tmp_path)
    tracker = _write_tracker(
        coordination["sessions"],
        agent="claude-code",
        repo_root=repo,
        worktree_path=tmp_path / "gone-worktree",
    )

    result = session_lifecycle.archive_orphaned_session_tracker(
        tracker_path=tracker,
        expected_tracker_sha256=_digest(tracker),
    )

    assert result["agent_supported"] is True


def test_legacy_agent_id_does_not_bypass_the_real_safety_guards(
    coordination: dict[str, Path],
    tmp_path: Path,
) -> None:
    """Relaxing the agent check must not relax what actually makes this safe.

    The operator guide's contract for this operation names four conditions:
    the recorded worktree absent, the claim file gone, the tracker digest
    matching, and the tracker inside the canonical tree. None of them depends
    on the agent name, and all must still hold for a legacy identity.
    """
    repo = _seed_repo(tmp_path)
    live_worktree = tmp_path / "live-worktree"
    live_worktree.mkdir()
    tracker = _write_tracker(
        coordination["sessions"],
        agent="codex-root",
        repo_root=repo,
        worktree_path=live_worktree,
    )

    with pytest.raises(ValueError, match="rejects an existing recorded worktree"):
        session_lifecycle.archive_orphaned_session_tracker(
            tracker_path=tracker,
            expected_tracker_sha256=_digest(tracker),
        )
    assert tracker.is_file()

    # And the digest guard, on the same legacy identity.
    with pytest.raises(ValueError):
        session_lifecycle.archive_orphaned_session_tracker(
            tracker_path=tracker,
            expected_tracker_sha256="0" * 64,
        )
    assert tracker.is_file()


def test_start_session_refuses_an_unsupported_agent(tmp_path: Path) -> None:
    """The write path that created those 23 stranded trackers is now closed.

    start_session never validated `agent`, while claim creation always did.
    validate_native_session_binding does not catch it either:
    STRICT_NATIVE_SESSION_ENV_KEYS.get(agent) returns None for an unknown
    agent, so it no-ops instead of rejecting.
    """
    with pytest.raises(ValueError, match="refuses an unsupported agent"):
        session_lifecycle.start_session(
            agent="codex-evidence-reader-wiki",
            project="demo",
            scope="lane",
            intent="should never reach tracker creation",
            repo_root=str(tmp_path),
            worktree_path=str(tmp_path / "wt"),
            branch="lane",
            broader_goal="prove the write path is closed",
            current_phase="implementation",
        )
