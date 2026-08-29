"""Host-boundary tests for target resolution and Bash claim admission."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
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


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    payload: dict[str, object],
    *,
    claims_dir: Path | None = None,
    projection_path: Path | None = None,
    mode: str = "enforce",
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
    code = prewrite_claim_gate.main(
        [
            "--client",
            "claude-code",
            "--mode",
            mode,
            "--claims-dir",
            str(claims_dir or tmp_path / "missing-claims"),
            "--projection-path",
            str(projection_path or tmp_path / "missing-projection.json"),
            "--receipt-path",
            str(tmp_path / "receipts.jsonl"),
            "--outcome-receipt-path",
            str(tmp_path / "outcome-receipts.jsonl"),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert not captured.err
    return code, json.loads(captured.out)


def test_repo_prewrite_mode_accepts_documented_unquoted_off(tmp_path: Path) -> None:
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    prewrite_mode: off\n",
        encoding="utf-8",
    )

    assert prewrite_claim_gate._load_mode(tmp_path) == "off"


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


def test_compound_bash_does_not_require_claim_when_every_command_is_read_only(tmp_path: Path) -> None:
    payload = _payload(
        cwd=tmp_path,
        tool="Bash",
        tool_input={"command": "git status --short && pwd"},
        session="wrong-session",
    )

    decision = _evaluate(tmp_path, payload, tmp_path / "missing-claims")

    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "bash_read_only"


def test_compound_bash_with_a_mutation_requires_an_exact_healthy_claim(tmp_path: Path) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=worktree,
        tool="Bash",
        tool_input={"command": "git status --short && touch marker"},
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


def test_explicit_host_mode_allows_read_only_bash_from_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": "pwd"})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "bash_read_only"


def test_explicit_host_mode_admits_strict_claim_bootstrap_from_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = json.dumps(
        {
            "schema_version": "1.0",
            "operation": "heartbeat",
            "agent": "claude-code",
            "project": "host-gate-test",
            "scope": "host-gate-lane",
        },
        separators=(",", ":"),
    )
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'claim_bootstrap.py'} "
        f"--request-json '{request}'"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "claim_bootstrap_command"


def test_explicit_host_mode_resolves_nested_edit_target_before_claim_evaluation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=workspace,
        tool="Edit",
        tool_input={"file_path": str(worktree / "src" / "allowed.py")},
    )

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        payload,
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 0
    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "exact_live_claim"


def test_explicit_host_mode_denies_unclaimed_mutating_bash_from_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": "touch marker"})
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))

    code = prewrite_claim_gate.main(
        [
            "--client",
            "claude-code",
            "--mode",
            "enforce",
            "--claims-dir",
            str(tmp_path / "missing-claims"),
            "--projection-path",
            str(tmp_path / "missing-projection.json"),
            "--receipt-path",
            str(tmp_path / "receipts.jsonl"),
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert not captured.out
    assert "Pre-write claim denied (repository_identity_unavailable)" in captured.err


def test_json_mode_preserves_deny_exit_for_unclaimed_workspace_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": "touch marker"})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "repository_identity_unavailable"


@pytest.mark.parametrize(
    ("mode", "expected_decision"),
    [("off", "allow"), ("observe", "observe_violation")],
)
def test_explicit_host_mode_preserves_off_and_observe_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    expected_decision: str,
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": "touch marker"})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, mode=mode)

    assert code == 0
    assert decision["mode"] == mode
    assert decision["decision"] == expected_decision
    assert decision["reason_code"] == "repository_identity_unavailable"


def test_explicit_mode_applies_repo_local_enforce_selected_to_claimed_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, _repo, worktree, _claims_dir, _claim_path = _fixture(tmp_path)
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )
    payload = _payload(cwd=worktree, tool="Bash", tool_input={"command": "touch marker"})
    ordinary = {
        "decision": "allow",
        "reason_code": "exact_live_claim",
        "receipt_id": "ordinary",
        "normalized_target_paths": [],
    }
    observed: dict[str, object] = {}

    monkeypatch.setattr(prewrite_claim_gate, "evaluate_prewrite_fast", lambda *_args, **_kwargs: ordinary)

    def enforce_selected(
        decision: dict[str, object], *, receipt_path: Path, allow_bootstrap: bool
    ) -> dict[str, object]:
        observed.update(decision=decision, receipt_path=receipt_path, allow_bootstrap=allow_bootstrap)
        return {"result": {"decision": {"disposition": "allow", "reason_code": "selected_outcome"}}}

    monkeypatch.setattr(prewrite_claim_gate, "_enforce_selected_outcome", enforce_selected)

    code, result = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0
    assert result["outcome_admission"]["result"]["decision"]["disposition"] == "allow"  # type: ignore[index]
    assert observed["decision"] is ordinary
    assert observed["allow_bootstrap"] is True


def test_explicit_mode_exempts_read_only_bash_from_repo_local_enforce_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, _repo, worktree, _claims_dir, _claim_path = _fixture(tmp_path)
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )
    payload = _payload(
        cwd=worktree,
        tool="Bash",
        tool_input={"command": "git status --short && pwd"},
    )

    def unexpected(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("read-only work must not enter outcome admission")

    monkeypatch.setattr(prewrite_claim_gate, "_enforce_selected_outcome", unexpected)

    code, result = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0
    assert result["decision"] == "allow"
    assert result["reason_code"] == "bash_read_only"
    assert "outcome_admission" not in result


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
        "/tmp/ls",
        "./git status",
        "/opt/tools/rg needle .",
    ],
)
def test_ambiguous_or_mutating_bash_fails_closed_without_claim(tmp_path: Path, command: str) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    decision = _evaluate(tmp_path, payload, tmp_path / "missing")

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "repository_identity_unavailable"
