"""Both-sign tests for the digest-bound low-latency pre-write projection."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import prewrite_claim_fast, prewrite_claim_projection
from enforced_planning.prewrite_claim_fast import evaluate_prewrite_fast
from enforced_planning.prewrite_claim_projection import ProjectionBuildError, write_projection


SESSION = "codex:projection-test"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = tmp_path / "worktree"
    _git(repo, "worktree", "add", "-b", "projection-lane", str(worktree))
    (worktree / "src").mkdir()
    (worktree / "src" / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    now = datetime.now(timezone.utc)
    claim_path = claims_dir / "codex_projection-test_projection-lane.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["projection-test"],
                "scope": "projection-lane",
                "intent": "test projection parity",
                "claim_type": "write",
                "write_paths": ["src/allowed.py"],
                "read_paths": [],
                "worktree_path": str(worktree),
                "repo_root": str(repo),
                "branch": "projection-lane",
                "session_name": "projection-test",
                "broader_goal": "exercise projection authorization",
                "tracker_path": str(tmp_path / "projection-session.yaml"),
                "session_id": SESSION,
                "heartbeat_at": now.isoformat(),
                "status": "active",
                "updated_at": now.isoformat(),
                "plan_ref": "UNPLANNED",
                "progress_at": now.isoformat(),
                "progress_kind": "claim_started",
                "evidence_ref": "UNPLANNED",
                "next_action": "exercise the projection fixture",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return repo, worktree, claims_dir, claim_path


def _payload(worktree: Path, target: str = "src/allowed.py") -> dict[str, object]:
    return {
        "session_id": "projection-test",
        "cwd": str(worktree),
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {
            "command": f"*** Begin Patch\n*** Update File: {target}\n*** End Patch"
        },
    }


def _evaluate(
    tmp_path: Path,
    worktree: Path,
    claims_dir: Path,
    projection_path: Path,
    *,
    mode: str = "enforce",
) -> dict[str, object]:
    return evaluate_prewrite_fast(
        _payload(worktree),
        client="codex",
        mode=mode,
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "receipts.jsonl",
    )


def test_exact_projection_allows_and_claim_change_invalidates(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    allowed = _evaluate(tmp_path, worktree, claims_dir, projection_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["session_id"] = "codex:different-session"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    stale = _evaluate(tmp_path, worktree, claims_dir, projection_path)
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    refreshed = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert allowed["decision"] == "allow", allowed
    assert allowed["reason_code"] == "exact_live_claim"
    assert stale["decision"] == "deny"
    assert stale["reason_code"] == "projection_unavailable_or_stale"
    assert refreshed["decision"] == "deny"
    assert refreshed["reason_code"] == "no_exact_claim"


def test_missing_or_corrupt_projection_never_falls_back(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    projection_path = tmp_path / "projection.json"

    missing = _evaluate(tmp_path, worktree, claims_dir, projection_path)
    projection_path.write_text("not-json\n", encoding="utf-8")
    corrupt = _evaluate(tmp_path, worktree, claims_dir, projection_path)
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    malformed = json.loads(projection_path.read_text(encoding="utf-8"))
    malformed["claims"][0]["projects"] = "not-a-list"
    projection_path.write_text(json.dumps(malformed), encoding="utf-8")
    wrong_shape = _evaluate(tmp_path, worktree, claims_dir, projection_path)
    observed = _evaluate(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        mode="observe",
    )

    assert missing["decision"] == "deny"
    assert corrupt["decision"] == "deny"
    assert wrong_shape["decision"] == "deny"
    assert observed["decision"] == "observe_violation"
    assert {
        missing["reason_code"],
        corrupt["reason_code"],
        wrong_shape["reason_code"],
        observed["reason_code"],
    } == {"projection_unavailable_or_stale"}


def test_projection_contains_no_native_write_content(tmp_path: Path) -> None:
    _repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    projection_path = tmp_path / "projection.json"

    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    payload = json.loads(projection_path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, sort_keys=True)

    assert payload["schema_version"] == "1.0"
    assert len(payload["claims"]) == 1
    assert "tool_input" not in rendered
    assert "command" not in rendered
    assert "patch" not in rendered


def test_bootstrap_uses_v1_static_issue_without_projection_shape_drift(tmp_path: Path) -> None:
    """New bootstrap denial remains consumable by the exact legacy v1 wire reader."""

    _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim.update(
        schema_version=6,
        write_paths=["."],
        broad_scope_mode="bootstrap",
        broad_scope_reason="create and narrow the maintenance lane",
        target_worktree_path=str(worktree),
        worktree_path=str(worktree),
    )
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    projection_path = tmp_path / "projection.json"

    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    payload = json.loads(projection_path.read_text(encoding="utf-8"))
    projected = payload["claims"][0]
    decision = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert payload["schema_version"] == "1.0"
    assert set(payload) == prewrite_claim_fast.PROJECTION_FIELDS
    assert set(projected) == prewrite_claim_fast.CLAIM_FIELDS
    assert projected["worktree_path"].endswith(".bootstrap-no-mutation-authority")
    assert projected["static_issues"] == ["bootstrap_broad_claim_requires_narrowing"]
    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "no_exact_claim"


def test_duplicate_exact_projection_denies_as_ambiguous(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    duplicate = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    duplicate["scope"] = "duplicate-lane"
    (claims_dir / "codex_projection-test_duplicate-lane.yaml").write_text(
        yaml.safe_dump(duplicate, sort_keys=False),
        encoding="utf-8",
    )
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    decision = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "ambiguous_exact_claim"
    assert decision["details"] == [
        "projection-test:duplicate-lane",
        "projection-test:projection-lane",
    ]


@pytest.mark.parametrize(
    ("target", "expected_scope"),
    [
        ("src/allowed.py", "projection-lane"),
        ("tests/child.py", "projection-lane/child"),
    ],
)
def test_parent_child_exact_claims_select_sole_target_authority(
    tmp_path: Path,
    target: str,
    expected_scope: str,
) -> None:
    _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    child = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    child["scope"] = "projection-lane/child"
    child["write_paths"] = ["tests/child.py"]
    (claims_dir / "codex_projection-test_projection-lane_child.yaml").write_text(
        yaml.safe_dump(child, sort_keys=False),
        encoding="utf-8",
    )
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    decision = evaluate_prewrite_fast(
        _payload(worktree, target),
        client="codex",
        mode="enforce",
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "receipts.jsonl",
    )

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "exact_live_claim"
    assert decision["claim_scope"] == expected_scope


def test_disjoint_exact_claims_do_not_combine_authority(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    child = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    child["scope"] = "projection-lane/child"
    child["write_paths"] = ["tests/child.py"]
    (claims_dir / "codex_projection-test_projection-lane_child.yaml").write_text(
        yaml.safe_dump(child, sort_keys=False),
        encoding="utf-8",
    )
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    payload = _payload(worktree)
    payload["tool_input"] = {
        "command": (
            "*** Begin Patch\n"
            "*** Update File: src/allowed.py\n"
            "*** Update File: tests/child.py\n"
            "*** End Patch"
        )
    }

    decision = evaluate_prewrite_fast(
        payload,
        client="codex",
        mode="enforce",
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "receipts.jsonl",
    )

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "path_outside_claim"
    assert decision["claim_scope"] is None
    assert decision["details"] == ["src/allowed.py", "tests/child.py"]


def test_expired_projection_claim_is_not_authorized(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    decision = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "no_exact_claim"


def test_merged_active_claim_is_denied(tmp_path: Path) -> None:
    repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    _git(worktree, "add", "src/allowed.py")
    _git(worktree, "commit", "-m", "lane change")
    _git(repo, "merge", "--no-ff", "projection-lane", "-m", "merge lane")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    decision = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "claim_not_healthy"
    assert "merged_active_claim_requires_disposition" in decision["details"]


@pytest.mark.parametrize("pending_kind", ["modified", "staged", "untracked"])
def test_merged_active_claim_with_dirty_worktree_remains_authorized(
    tmp_path: Path,
    pending_kind: str,
) -> None:
    repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    _git(worktree, "add", "src/allowed.py")
    _git(worktree, "commit", "-m", "lane change")
    _git(repo, "merge", "--no-ff", "projection-lane", "-m", "merge lane")
    if pending_kind == "untracked":
        (worktree / "src" / "pending.py").write_text("PENDING = True\n", encoding="utf-8")
    else:
        (worktree / "src" / "allowed.py").write_text("VALUE = 2\n", encoding="utf-8")
        if pending_kind == "staged":
            _git(worktree, "add", "src/allowed.py")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    decision = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "exact_live_claim"


def test_merged_active_claim_with_only_ignored_files_is_denied(tmp_path: Path) -> None:
    repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    (worktree / ".gitignore").write_text("src/ignored.py\n", encoding="utf-8")
    _git(worktree, "add", "src/allowed.py", ".gitignore")
    _git(worktree, "commit", "-m", "lane change")
    _git(repo, "merge", "--no-ff", "projection-lane", "-m", "merge lane")
    (worktree / "src" / "ignored.py").write_text("IGNORED = True\n", encoding="utf-8")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    decision = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "claim_not_healthy"
    assert "merged_active_claim_requires_disposition" in decision["details"]


def test_merged_active_claim_fails_closed_when_status_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    _git(worktree, "add", "src/allowed.py")
    _git(worktree, "commit", "-m", "lane change")
    _git(repo, "merge", "--no-ff", "projection-lane", "-m", "merge lane")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    real_git = prewrite_claim_fast._git

    def fail_status(path: Path, *args: str, allow_failure: bool = False) -> str | None:
        if args[:2] == ("status", "--porcelain"):
            return None
        return real_git(path, *args, allow_failure=allow_failure)

    monkeypatch.setattr(prewrite_claim_fast, "_git", fail_status)

    decision = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "claim_not_healthy"
    assert "merged_active_claim_requires_disposition" in decision["details"]


def test_non_ancestor_claim_does_not_probe_worktree_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    _git(worktree, "add", "src/allowed.py")
    _git(worktree, "commit", "-m", "lane change")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    real_git = prewrite_claim_fast._git

    def reject_status(path: Path, *args: str, allow_failure: bool = False) -> str | None:
        if args[:2] == ("status", "--porcelain"):
            pytest.fail("non-ancestor claims must not pay for a worktree status probe")
        return real_git(path, *args, allow_failure=allow_failure)

    monkeypatch.setattr(prewrite_claim_fast, "_git", reject_status)

    decision = _evaluate(tmp_path, worktree, claims_dir, projection_path)

    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "exact_live_claim"


def test_projection_build_skips_an_unnormalizable_claim_belonging_to_another_project(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A malformed claim in an unrelated project must not block everyone else's projection.

    Regression target: 2026-09-09, a live claim for a different project
    (`chatgpt_brians-2nd-brain-integration-work_...yaml`, an older claim
    shape with no agent/scope/intent fields at all) made `build_projection`
    raise ProjectionBuildError, blocking a `make maintenance-worktree` for a
    completely unrelated project until the other session released its own
    claim -- a malformed claim anywhere broke prewrite gating everywhere.
    """
    _repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    now = datetime.now(timezone.utc)
    unrelated_claim = claims_dir / "chatgpt_unrelated-project_some-scope.yaml"
    unrelated_claim.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "status": "active",
                "claim_type": "write",
                "branch": "fix/something",
                "repo_root": "/tmp/unrelated",
                "worktree_path": "/tmp/unrelated/worktrees/fix",
                "write_paths": ["some/path.py"],
                "broader_goal": "an older claim shape with no agent/scope/intent fields",
                "updated_at": now.isoformat(),
            }
        ),
        encoding="utf-8",
    )

    projection = prewrite_claim_projection.build_projection(claims_dir=claims_dir)

    assert any(claim.scope == "projection-lane" for claim in projection.claims)
    assert not any("unrelated" in claim.scope for claim in projection.claims)
    captured = capsys.readouterr()
    assert "cannot be normalized" in captured.err
    assert "chatgpt_unrelated-project_some-scope.yaml" in captured.err


def test_projection_build_skips_an_unparseable_claim_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A claim file with invalid YAML must not block the rest of the projection."""
    _repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    broken_claim = claims_dir / "codex_other-project_broken.yaml"
    broken_claim.write_text("agent: codex\n  bad indentation: [unclosed\n", encoding="utf-8")

    projection = prewrite_claim_projection.build_projection(claims_dir=claims_dir)

    assert any(claim.scope == "projection-lane" for claim in projection.claims)
    captured = capsys.readouterr()
    assert "skipping unreadable claim" in captured.err
    assert "broken.yaml" in captured.err


def test_projection_build_rejects_concurrent_registry_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    real_digest = prewrite_claim_projection.registry_digest
    calls = 0

    def changing_digest(path: Path) -> str:
        nonlocal calls
        calls += 1
        value = real_digest(path)
        return value if calls == 1 else "f" * 64

    monkeypatch.setattr(prewrite_claim_projection, "registry_digest", changing_digest)

    with pytest.raises(ProjectionBuildError, match="changed while"):
        prewrite_claim_projection.build_projection(claims_dir=claims_dir)
