"""Same-goal successor lanes preserve closed history through native entrypoints."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from enforced_planning import claim_bootstrap, session_contracts
from tests.test_claim_bootstrap import (
    _configure_maintenance_runtime,
    _goal_worktree_payload,
    _governed_repo,
    _lane_path_released,
)


def _contract(tmp_path: Path, scope: str, goal: str = "Finish the same user outcome"):
    return session_contracts.SessionContract.build(
        agent="codex", project="demo", scope=scope, intent="repair one lane",
        plan_ref="goal:repair", repo_root=str(tmp_path / "repo"),
        worktree_path=str(tmp_path / "repo" / "worktrees" / scope),
        branch=scope, session_id="codex:native-123", broader_goal=goal,
    )


def _write(contract, directory: Path, phase: str):
    return session_contracts.write_session_tracker(
        session_contracts.build_session_tracker(contract=contract, current_phase=phase),
        tracker_dir=directory,
    )


def test_native_successor_bootstrap_refresh_and_close_preserve_predecessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _governed_repo(tmp_path)
    _, trackers = _configure_maintenance_runtime(tmp_path, monkeypatch)
    first = claim_bootstrap.execute_request(claim_bootstrap.parse_request_json(
        json.dumps(_goal_worktree_payload(repo))))
    old_path = Path(first["result"]["tracker_path"])
    old_claim = session_contracts.read_session_tracker(old_path)["claim"]
    closed = claim_bootstrap.session_lifecycle.close_session(
        agent="codex", project=repo.name, scope=old_claim["scope"],
        branch=old_claim["branch"], worktree_path=old_claim["worktree_path"],
        actor_session_id="codex:native-123",
    )
    assert closed["released"] is True
    previous_bytes = old_path.read_bytes()
    assert session_contracts.read_session_tracker(old_path)["tracker"]["current_phase"] == "closed"
    print("PREDECESSOR_CLOSED", json.dumps(old_claim, sort_keys=True))

    scope = "goal/second-repair"
    second = claim_bootstrap.execute_request(claim_bootstrap.parse_request_json(json.dumps(
        _goal_worktree_payload(repo, branch=scope, scope=scope))))
    new_path = Path(second["result"]["tracker_path"])
    assert new_path != old_path
    new_claim = session_contracts.read_session_tracker(new_path)["claim"]
    for key in ("session_id", "broader_goal", "session_name", "repo_root"):
        assert new_claim[key] == old_claim[key]
    assert new_claim["scope"] == new_claim["branch"] == scope
    assert old_path.read_bytes() == previous_bytes
    assert [c.scope for c in claim_bootstrap.coordination_claims.check_claims(repo.name)
            if c.status == "active"] == [scope]
    print("SUCCESSOR_ADMITTED", json.dumps(new_claim, sort_keys=True))

    claim_bootstrap.session_lifecycle.heartbeat_session(
        agent="codex", project=repo.name, scope=scope, branch=scope,
        session_id="codex:native-123", current_phase="verified successor",
        tracker_dir=trackers,
    )
    assert session_contracts.read_session_tracker(new_path)["tracker"]["current_phase"] == "verified successor"
    assert old_path.read_bytes() == previous_bytes
    closed = claim_bootstrap.session_lifecycle.close_session(
        agent="codex", project=repo.name, scope=scope, branch=scope,
        worktree_path=new_claim["worktree_path"], actor_session_id="codex:native-123",
    )
    assert closed["released"] is True
    assert _lane_path_released(Path(new_claim["worktree_path"]))
    assert old_path.read_bytes() == previous_bytes
    assert session_contracts.read_session_tracker(new_path)["tracker"]["current_phase"] == "closed"
    assert not [c for c in claim_bootstrap.coordination_claims.check_claims(repo.name)
                if c.status == "active"]
    print("SUCCESSOR_CLOSED_PREDECESSOR_UNCHANGED", str(new_path))


def test_active_predecessor_keeps_occupied_path(tmp_path: Path) -> None:
    first = _contract(tmp_path, "first")
    path = _write(first, tmp_path, "implementing")
    before = path.read_bytes()
    assert session_contracts.session_tracker_path(_contract(tmp_path, "second"), tracker_dir=tmp_path) == path
    assert path.read_bytes() == before


def test_closed_same_lane_keeps_history_path(tmp_path: Path) -> None:
    first = _contract(tmp_path, "first")
    path = _write(first, tmp_path, "closed")
    assert session_contracts.session_tracker_path(first, tracker_dir=tmp_path) == path


@pytest.mark.parametrize("field", ["scope", "branch", "session_id"])
def test_conflicting_successor_identity_is_refused(tmp_path: Path, field: str) -> None:
    first, second = _contract(tmp_path, "first"), _contract(tmp_path, "second")
    predecessor = _write(first, tmp_path, "closed")
    previous_bytes = predecessor.read_bytes()
    successor = _write(second, tmp_path, "implementing")
    payload = session_contracts.read_session_tracker(successor)
    payload["claim"][field] = "another-owner"
    successor.write_text(yaml.safe_dump(payload))
    before = successor.read_bytes()
    with pytest.raises(ValueError, match="conflicting lane identity"):
        _write(second, tmp_path, "refresh")
    assert successor.read_bytes() == before
    assert predecessor.read_bytes() == previous_bytes


def test_closed_tracker_missing_identity_is_refused(tmp_path: Path) -> None:
    first = _contract(tmp_path, "first")
    predecessor = _write(first, tmp_path, "closed")
    predecessor.write_text("tracker:\n  current_phase: closed\nclaim: {}\n")
    before = predecessor.read_bytes()
    with pytest.raises(ValueError, match="incomplete lane identity"):
        session_contracts.session_tracker_path(_contract(tmp_path, "second"), tracker_dir=tmp_path)
    assert predecessor.read_bytes() == before


def test_successor_key_survives_long_goal_and_native_rewrite(tmp_path: Path) -> None:
    first = _contract(tmp_path, "first", "continue " * 100)
    old = _write(first, tmp_path, "closed")
    old_bytes = old.read_bytes()
    second = replace(first, scope="second", branch="second",
                     worktree_path=str(tmp_path / "repo" / "worktrees" / "second"))
    new = _write(second, tmp_path, "implementing")
    assert "__lane-" in new.name
    assert len(new.name.encode()) <= session_contracts.MAX_TRACKER_NAME_BYTES
    assert _write(second, tmp_path, "refresh") == new
    assert old.read_bytes() == old_bytes
    assert session_contracts.find_session_tracker_path(
        agent=second.agent, project=second.project, scope=second.scope,
        session_id=second.session_id, tracker_dir=tmp_path,
    ) == new
