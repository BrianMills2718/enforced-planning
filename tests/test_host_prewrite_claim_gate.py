"""Host-boundary tests for target resolution and Bash claim admission."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning.prewrite_claim_fast import evaluate_prewrite_fast
from enforced_planning.prewrite_claim_projection import write_projection
from scripts import prewrite_claim_gate

SESSION = "claude-code:host-gate-test"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    workspace = tmp_path / "workspace"
    repo = workspace / "project"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = repo / "worktrees" / "host-gate-lane"
    worktree.parent.mkdir()
    _git(repo, "worktree", "add", "-b", "host-gate-lane", str(worktree))
    (worktree / "src").mkdir()
    (worktree / "src" / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    now = datetime.now(timezone.utc)
    claim_path = claims_dir / "claude-code_host-gate-test_host-gate-lane.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "agent": "claude-code",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["host-gate-test"],
                "scope": "host-gate-lane",
                "intent": "exercise host prewrite admission",
                "claim_type": "write",
                "plan_ref": "UNPLANNED",
                "write_paths": ["src"],
                "read_paths": [],
                "worktree_path": str(worktree),
                "repo_root": str(repo),
                "branch": "host-gate-lane",
                "session_name": "host-gate-test",
                "broader_goal": "exercise host prewrite admission",
                "tracker_path": str(tmp_path / "tracker.yaml"),
                "session_id": SESSION,
                "heartbeat_at": now.isoformat(),
                "status": "active",
                "updated_at": now.isoformat(),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    projection = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection)
    return workspace, repo, worktree, claims_dir, claim_path


def _payload(*, cwd: Path, tool: str, tool_input: dict[str, str], session: str = "host-gate-test") -> dict[str, object]:
    return {
        "session_id": session,
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def _evaluate(
    tmp_path: Path,
    payload: dict[str, object],
    claims_dir: Path,
    *,
    bootstrap_classifier=None,
) -> dict[str, object]:
    return evaluate_prewrite_fast(
        payload,
        client="claude-code",
        mode="enforce",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        receipt_path=tmp_path / "receipts.jsonl",
        claim_bootstrap_classifier=bootstrap_classifier,
    )


@pytest.mark.parametrize(
    ("tool", "path_field", "suffix"),
    [
        ("Edit", "file_path", "src/allowed.py"),
        ("Write", "file_path", "src/new/deep.py"),
        ("NotebookEdit", "notebook_path", "src/review.ipynb"),
    ],
)
def test_file_tools_resolve_claim_from_target_when_cwd_is_workspace_root(
    tmp_path: Path,
    tool: str,
    path_field: str,
    suffix: str,
) -> None:
    workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)

    decision = _evaluate(
        tmp_path,
        _payload(cwd=workspace, tool=tool, tool_input={path_field: str(worktree / suffix)}),
        claims_dir,
    )

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "exact_live_claim"
    assert decision["worktree_path"] == str(worktree)
    assert decision["normalized_target_paths"] == [suffix]


def test_target_claim_rejects_wrong_session_and_stale_heartbeat(tmp_path: Path) -> None:
    workspace, _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=workspace,
        tool="Edit",
        tool_input={"file_path": str(worktree / "src" / "allowed.py")},
    )

    wrong = _evaluate(tmp_path, {**payload, "session_id": "wrong-session"}, claims_dir)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    stale = _evaluate(tmp_path, payload, claims_dir)

    assert wrong["decision"] == "deny"
    assert wrong["reason_code"] == "no_exact_claim"
    assert stale["decision"] == "deny"
    assert stale["reason_code"] == "claim_not_healthy"
    assert "stale_session_heartbeat" in stale["details"]


def test_relative_nested_target_is_resolved_from_root_cwd(tmp_path: Path) -> None:
    workspace, _repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    relative = "project/worktrees/host-gate-lane/src/allowed.py"

    decision = _evaluate(
        tmp_path,
        _payload(cwd=workspace, tool="Edit", tool_input={"file_path": relative}),
        claims_dir,
    )

    assert decision["decision"] == "allow", decision
    assert decision["normalized_target_paths"] == ["src/allowed.py"]


@pytest.mark.parametrize("command", ["pwd", "ls -la", "rg needle .", "git status --short", "sed -n 1,20p README.md"])
def test_simple_read_only_bash_does_not_require_repository_or_claim(
    tmp_path: Path,
    command: str,
) -> None:
    claims_dir = tmp_path / "missing-claims"
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    decision = _evaluate(tmp_path, payload, claims_dir)

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "bash_read_only"


def test_compound_bash_requires_claim_even_when_each_command_is_read_only(tmp_path: Path) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=worktree,
        tool="Bash",
        tool_input={"command": "git status --short && pwd"},
        session="wrong-session",
    )

    decision = _evaluate(tmp_path, payload, claims_dir)

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "no_exact_claim"


def test_compound_bash_is_allowed_with_exact_healthy_claim(tmp_path: Path) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=worktree,
        tool="Bash",
        tool_input={"command": "git status --short && pwd"},
    )

    decision = _evaluate(tmp_path, payload, claims_dir)

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "exact_live_claim"


def test_mutating_bash_is_allowed_only_by_exact_healthy_worktree_claim(tmp_path: Path) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    claimed = _payload(cwd=worktree, tool="Bash", tool_input={"command": "touch src/generated.py"})
    unclaimed = {**claimed, "session_id": "wrong-session"}

    allowed = _evaluate(tmp_path, claimed, claims_dir)
    denied = _evaluate(tmp_path, unclaimed, claims_dir)

    assert allowed["decision"] == "allow", allowed
    assert allowed["reason_code"] == "exact_live_claim"
    assert allowed["normalized_target_paths"] == []
    assert denied["decision"] == "deny"
    assert denied["reason_code"] == "no_exact_claim"


def test_bootstrap_bash_bypasses_claim_only_when_strict_classifier_accepts(tmp_path: Path) -> None:
    exact = '/usr/bin/python3 /canonical/scripts/claim_bootstrap.py --request-json \'{"schema_version":"1.0"}\''
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": exact})

    allowed = _evaluate(tmp_path, payload, tmp_path / "missing", bootstrap_classifier=lambda raw: raw == exact)
    denied = _evaluate(tmp_path, payload, tmp_path / "missing", bootstrap_classifier=lambda _raw: False)

    assert allowed["decision"] == "allow"
    assert allowed["reason_code"] == "claim_bootstrap_command"
    assert denied["decision"] == "deny"
    assert denied["reason_code"] == "repository_identity_unavailable"


def test_cli_bootstrap_classifier_delegates_to_claim_bootstrap_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    module = ModuleType("enforced_planning.claim_bootstrap")

    def parse_raw_bash_command(raw: str, *, script_path: Path) -> object:
        observed.update(raw=raw, script_path=script_path)
        return object()

    module.parse_raw_bash_command = parse_raw_bash_command  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "enforced_planning.claim_bootstrap", module)

    assert prewrite_claim_gate._is_claim_bootstrap_command("exact bootstrap")
    assert observed == {
        "raw": "exact bootstrap",
        "script_path": (prewrite_claim_gate.REPO_ROOT / "scripts" / "claim_bootstrap.py").resolve(),
    }


@pytest.mark.parametrize(
    "command",
    [
        "sed -i s/old/new/ file.txt",
        "sed --in-place s/old/new/ file.txt",
        "sed -n e file.txt",
        "find . -delete",
        "find . -fls report.txt",
        "git branch new-name",
        "git show HEAD > snapshot.txt",
        "rg --pre 'touch marker' needle .",
    ],
)
def test_ambiguous_or_mutating_bash_fails_closed_without_claim(tmp_path: Path, command: str) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    decision = _evaluate(tmp_path, payload, tmp_path / "missing")

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "repository_identity_unavailable"
