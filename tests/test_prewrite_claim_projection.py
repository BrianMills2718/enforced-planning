"""Both-sign tests for the digest-bound low-latency pre-write projection."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from enforced_planning.prewrite_claim_fast import evaluate_prewrite_fast
from enforced_planning.prewrite_claim_projection import write_projection


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
                "session_id": SESSION,
                "heartbeat_at": now.isoformat(),
                "status": "active",
                "updated_at": now.isoformat(),
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
