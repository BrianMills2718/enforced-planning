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

from enforced_planning.prewrite_claim_fast import _argv_is_read_only, evaluate_prewrite_fast
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
    client: str = "claude-code",
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
    code = prewrite_claim_gate.main(
        [
            "--client",
            client,
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


@pytest.mark.parametrize(
    "command",
    [
        "pwd",
        "ls -la",
        "rg needle .",
        "git status --short",
        "sed -n 1,20p README.md",
        "sort names.txt",
    ],
)
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


def test_workspace_inventory_can_pipe_through_safe_sort(tmp_path: Path) -> None:
    command = "find /home/brian/code -maxdepth 2 -type d -iname '*levin*' | sort"
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    decision = _evaluate(tmp_path, payload, tmp_path / "missing-claims")

    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "bash_read_only"


def test_compound_bash_with_a_mutation_requires_an_exact_healthy_claim(tmp_path: Path) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=worktree,
        tool="Bash",
        tool_input={"command": "git status --short && touch src/marker"},
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
    assert allowed["normalized_target_paths"] == ["src/generated.py"]
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

    assert code == 0, (decision["reason_code"], decision["details"], decision)
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "bash_read_only"


def test_read_only_bash_survives_malformed_outcome_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: definitely-invalid\n",
        encoding="utf-8",
    )
    payload = _payload(
        cwd=repo,
        tool="Bash",
        tool_input={"command": "git status --short && rg needle ."},
    )

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0, (decision["reason_code"], decision["details"], decision)
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


def test_host_gate_admits_exact_native_mailbox_send_without_repository_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "host-gate-test")
    native_session = "codex:host-gate-test"
    request = json.dumps(
        {
            "caller_session_id": native_session,
            "sender_session_id": native_session,
            "recipient": {"kind": "session", "session_id": "codex:recipient"},
            "project": "host-gate-test",
            "kind": "info",
            "subject": "Maintenance status",
            "body": "The governance repair is active.",
        },
        separators=(",", ":"),
    )
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'coordination_messages.py'} "
        f"send --request-json '{request}'"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, client="codex")

    assert code == 0, decision
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "native_mailbox_command"


def test_host_gate_admits_exact_native_closeout_for_merged_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "host-gate-test")
    _git(worktree, "add", "src/allowed.py")
    _git(worktree, "commit", "-m", "lane work")
    _git(repo, "merge", "--ff-only", "host-gate-lane")
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_close.py'} "
        "--agent claude-code --project host-gate-test --scope host-gate-lane --json"
    )
    payload = _payload(cwd=worktree, tool="Bash", tool_input={"command": command})

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        payload,
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 0, decision
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "native_closeout_command"


@pytest.mark.parametrize("tamper", ["wrong-scope", "wrong-agent", "composed"])
def test_host_gate_rejects_tampered_native_closeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "host-gate-test")
    agent = "codex" if tamper == "wrong-agent" else "claude-code"
    scope = "different-lane" if tamper == "wrong-scope" else "host-gate-lane"
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_close.py'} "
        f"--agent {agent} --project host-gate-test --scope {scope} --json"
    )
    if tamper == "composed":
        command += " && touch escaped"

    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
    )

    assert classification is False


@pytest.mark.parametrize("tamper", ["wrong-session", "composed", "noncanonical-script"])
def test_host_gate_rejects_tampered_claimless_mailbox_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tamper: str,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "host-gate-test")
    native_session = "codex:other" if tamper == "wrong-session" else "codex:host-gate-test"
    request = json.dumps(
        {
            "current_session_id": native_session,
            "observe": True,
        },
        separators=(",", ":"),
    )
    script = prewrite_claim_gate.REPO_ROOT / "scripts" / "coordination_messages.py"
    if tamper == "noncanonical-script":
        script = tmp_path / "coordination_messages.py"
    command = f"/usr/bin/python3 {script} poll --request-json '{request}'"
    if tamper == "composed":
        command += " && touch escaped"
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, client="codex")

    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] in {
        "projection_unavailable_or_stale",
        "repository_identity_unavailable",
    }


def test_workspace_root_admits_exact_read_target_selection_without_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = json.dumps(
        {
            "schema_version": "1.0",
            "operation": "select",
            "client": "codex",
            "project": "agent-skills",
            "repo_root": "/home/brian/code/active/agent-skills",
            "registry_path": "/home/brian/code/active/project-meta/PROJECT_GRAPH.json",
        },
        separators=(",", ":"),
    )
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_read_target.py'} "
        f"--request-json '{request}'"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="codex",
        claims_dir=tmp_path / "claims",
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
    )
    assert classification == "read_target_selection"

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, client="codex")

    assert code == 0, (decision["reason_code"], decision["details"], decision)
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "read_target_selection_command"


@pytest.mark.parametrize("change", ["subagent", "client"])
def test_read_target_selection_cannot_borrow_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    change: str,
) -> None:
    request = {
        "schema_version": "1.0",
        "operation": "select",
        "client": "claude-code" if change == "client" else "codex",
        "project": "agent-skills",
        "repo_root": "/home/brian/code/active/agent-skills",
        "registry_path": "/home/brian/code/active/project-meta/PROJECT_GRAPH.json",
    }
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_read_target.py'} "
        f"--request-json '{json.dumps(request, separators=(',', ':'))}'"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})
    if change == "subagent":
        payload["agent_id"] = "child-agent"

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, client="codex")

    assert code == 2
    assert decision["decision"] == "deny"


def test_workspace_root_typed_maintenance_bootstrap_is_denied_to_subagent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request = json.dumps(
        {
            "schema_version": "1.0",
            "operation": "maintenance_worktree",
            "agent": "codex",
            "project": "governed-repo",
            "scope": "fix/safe-lane",
            "repo_root": "/absolute/governed-repo",
            "branch": "fix/safe-lane",
            "claim_type": "program",
        },
        separators=(",", ":"),
    )
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'claim_bootstrap.py'} "
        f"--request-json '{request}'"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})
    payload["agent_id"] = "child-agent-123"

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        payload,
        client="codex",
    )

    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] in {
        "projection_unavailable_or_stale",
        "repository_identity_unavailable",
        "session_target_no_match",
    }


def test_workspace_root_admits_exact_typed_local_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    repo = (tmp_path / "weekly-plans").resolve()
    request = json.dumps(
        {
            "schema_version": "1.0",
            "operation": "local_repository_integrate",
            "agent": "codex",
            "project": "weekly-plans",
            "scope": "codex/initial-setup",
            "repo_root": str(repo),
            "branch": "codex/initial-setup",
            "default_branch": "main",
        },
        separators=(",", ":"),
    )
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'claim_bootstrap.py'} "
        f"--request-json '{request}'"
    )
    payload = _payload(
        cwd=tmp_path,
        tool="Bash",
        tool_input={"command": command},
        session="native-123",
    )

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        payload,
        client="codex",
    )

    assert code == 0, decision
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


def test_workspace_root_relative_apply_patch_uses_exact_claimed_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["agent"] = "codex"
    claim["session_id"] = "codex:host-gate-test"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    patch = "*** Begin Patch\n*** Update File: src/allowed.py\n@@\n-VALUE = 1\n+VALUE = 2\n*** End Patch"
    payload = _payload(
        cwd=workspace,
        tool="apply_patch",
        tool_input={"command": patch},
    )
    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        payload,
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        client="codex",
    )
    assert code == 0, (decision["reason_code"], decision["details"], decision)
    assert decision["worktree_path"] == str(worktree)
    assert decision["normalized_target_paths"] == ["src/allowed.py"]


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        (
            "apply_patch",
            {
                "command": "*** Begin Patch\n*** Update File: {target}\n@@\n-a\n+b\n*** End Patch"
            },
        ),
        ("Edit", {"file_path": "{target}"}),
    ],
)
def test_absolute_file_target_selects_target_repo_outcome_policy(
    tmp_path: Path,
    tool: str,
    tool_input: dict[str, str],
) -> None:
    workspace = tmp_path / "workspace"
    repo = workspace / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    target = repo / "file.txt"
    target.write_text("a\n", encoding="utf-8")
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )
    payload = _payload(
        cwd=workspace,
        tool=tool,
        tool_input={key: value.format(target=target) for key, value in tool_input.items()},
    )

    targeted = prewrite_claim_gate._session_bound_payload(
        payload,
        client="codex" if tool == "apply_patch" else "claude-code",
        claims_dir=tmp_path / "claims",
        projection_path=tmp_path / "projection.json",
    )

    assert targeted["cwd"] == str(repo)
    assert prewrite_claim_gate._resolved_outcome_mode(targeted, explicit_mode="enforce") == "enforce_selected"


def test_explicit_host_mode_resolves_bash_through_one_exact_session_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=workspace,
        tool="Bash",
        tool_input={"command": f"/usr/bin/env -C {worktree} touch generated.py"},
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
    assert decision["worktree_path"] == str(worktree)


def test_git_launch_cwd_resolves_bash_through_different_exact_session_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=repo,
        tool="Bash",
        tool_input={"command": f"/usr/bin/env -C {worktree} touch generated.py"},
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
    assert decision["worktree_path"] == str(worktree)


@pytest.mark.parametrize("command", ["touch generated.py", "{launch_bound}"])
def test_git_launch_cwd_requires_runtime_binding_to_different_claimed_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    _workspace, repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    rendered = command.format(launch_bound=f"/usr/bin/env -C {repo} touch generated.py")

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=repo, tool="Bash", tool_input={"command": rendered}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] in {
        "bash_runtime_workdir_unattested",
        "target_worktree_not_claimed",
    }


def test_git_launch_inside_exact_claim_does_not_require_synthetic_runtime_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=worktree, tool="Bash", tool_input={"command": "touch src/generated.py"}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 0
    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "exact_live_claim"
    assert decision["worktree_path"] == str(worktree)


def test_git_launch_cwd_relative_apply_patch_uses_different_claimed_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["agent"] = "codex"
    claim["session_id"] = "codex:host-gate-test"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    patch = "*** Begin Patch\n*** Update File: src/allowed.py\n@@\n-VALUE = 1\n+VALUE = 2\n*** End Patch"

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=repo, tool="apply_patch", tool_input={"command": patch}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        client="codex",
    )

    assert code == 0, decision
    assert decision["worktree_path"] == str(worktree)
    assert decision["normalized_target_paths"] == ["src/allowed.py"]


def test_git_launch_cwd_absolute_apply_patch_uses_targeted_claimed_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An absolute patch target owns routing even when the session launched elsewhere."""

    _workspace, repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["agent"] = "codex"
    claim["session_id"] = "codex:host-gate-test"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    target = worktree / "src" / "allowed.py"
    patch = f"*** Begin Patch\n*** Update File: {target}\n@@\n-VALUE = 1\n+VALUE = 2\n*** End Patch"

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=repo, tool="apply_patch", tool_input={"command": patch}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        client="codex",
    )

    assert code == 0, decision
    assert decision["worktree_path"] == str(worktree)
    assert decision["normalized_target_paths"] == ["src/allowed.py"]


def test_git_launch_cwd_absolute_new_file_patch_uses_targeted_claimed_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A nonexistent absolute file resolves through its owning worktree parent."""

    _workspace, repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["agent"] = "codex"
    claim["session_id"] = "codex:host-gate-test"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    target = worktree / "src" / "new.py"
    patch = f"*** Begin Patch\n*** Add File: {target}\n+VALUE = 1\n*** End Patch"

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=repo, tool="apply_patch", tool_input={"command": patch}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        client="codex",
    )

    assert code == 0, decision
    assert decision["worktree_path"] == str(worktree)
    assert decision["normalized_target_paths"] == ["src/new.py"]


def test_git_launch_cwd_does_not_hide_stale_session_target_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    (claims_dir / "projection-stale.yaml").write_text("changed\n", encoding="utf-8")

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(
            cwd=repo,
            tool="Bash",
            tool_input={"command": f"/usr/bin/env -C {worktree} touch generated.py"},
        ),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "projection_unavailable_or_stale"


def test_git_launch_cwd_stale_projection_still_allows_provably_read_only_bash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    (claims_dir / "projection-stale.yaml").write_text("changed\n", encoding="utf-8")

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=repo, tool="Bash", tool_input={"command": "git status --short"}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 0
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "bash_read_only"


def test_git_launch_cwd_uses_claimed_repo_outcome_policy(
    tmp_path: Path,
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: off\n",
        encoding="utf-8",
    )
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )
    payload = _payload(
        cwd=repo,
        tool="Bash",
        tool_input={"command": f"/usr/bin/env -C {worktree} touch generated.py"},
    )

    targeted = prewrite_claim_gate._session_bound_payload(
        payload,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert targeted["cwd"] == str(worktree)
    assert prewrite_claim_gate._resolved_outcome_mode(targeted, explicit_mode="enforce") == "enforce_selected"


def test_explicit_host_mode_routes_one_session_across_two_claimed_repositories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, first_worktree, claims_dir, claim_path = _fixture(tmp_path)
    second_repo = workspace / "project-two"
    second_repo.mkdir()
    _git(second_repo, "init", "-b", "main")
    _git(second_repo, "config", "user.name", "Test User")
    _git(second_repo, "config", "user.email", "test@example.com")
    (second_repo / "README.md").write_text("second seed\n", encoding="utf-8")
    _git(second_repo, "add", "README.md")
    _git(second_repo, "commit", "-m", "seed second repository")
    second_worktree = second_repo / "worktrees" / "second-lane"
    second_worktree.parent.mkdir()
    _git(second_repo, "worktree", "add", "-b", "second-lane", str(second_worktree))
    (second_worktree / "src").mkdir()

    second = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    second["scope"] = "second-lane"
    second["projects"] = ["host-gate-test-two"]
    second["repo_root"] = str(second_repo)
    second["worktree_path"] = str(second_worktree)
    second["branch"] = "second-lane"
    (claims_dir / "claude-code_host-gate-test_second-lane.yaml").write_text(
        yaml.safe_dump(second, sort_keys=False),
        encoding="utf-8",
    )
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")

    for target in (first_worktree, second_worktree):
        payload = _payload(
            cwd=workspace,
            tool="Bash",
            tool_input={"command": f"/usr/bin/env -C {target} touch src/generated.py"},
        )
        code, decision = _run_cli(
            monkeypatch,
            capsys,
            tmp_path,
            payload,
            claims_dir=claims_dir,
            projection_path=tmp_path / "projection.json",
        )

        assert code == 0, decision
        assert decision["decision"] == "allow"
        assert decision["reason_code"] == "exact_live_claim"
        assert decision["worktree_path"] == str(target)
        subprocess.run(
            ["/usr/bin/env", "-C", str(target), "touch", "src/generated.py"],
            check=True,
        )
        assert (target / "src" / "generated.py").is_file()

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Bash", tool_input={"command": "touch marker"}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )
    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "ambiguous_exact_session_target"


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
    assert "BLOCKED [prewrite/projection_unavailable_or_stale]" in captured.err
    assert "Why: The claim authority projection is unavailable or stale." in captured.err
    assert "Next:" in captured.err


def test_native_denial_keeps_raw_repository_failure_in_receipt_not_prompt() -> None:
    message = prewrite_claim_gate._native_denial_message(
        {
            "reason_code": "repository_identity_unavailable",
            "details": ["fatal: not a git repository\n" + "internal diagnostic " * 100],
            "recovery": "Create one exact claimed target, then retry.",
        }
    )

    assert message == (
        "BLOCKED [prewrite/repository_identity_unavailable]\n"
        "Why: The target repository could not be resolved from this event.\n"
        "Next: Create one exact claimed target, then retry."
    )
    assert "fatal:" not in message


@pytest.mark.parametrize(
    ("reason_code", "summary"),
    [
        (
            "no_exact_session_target",
            "This workspace-root session has no healthy claim selecting a target worktree.",
        ),
        (
            "client_identity_mismatch",
            "The event identity belongs to a different native client.",
        ),
        (
            "session_identity_unavailable",
            "The event does not identify the native session that would own the mutation.",
        ),
        (
            "claim_git_identity_mismatch",
            "The claimed worktree no longer matches its recorded Git identity.",
        ),
        (
            "unsupported_client",
            "The event names a client that this hook cannot authenticate.",
        ),
    ],
)
def test_native_denial_explains_session_target_failures(
    reason_code: str,
    summary: str,
) -> None:
    message = prewrite_claim_gate._native_denial_message(
        {
            "reason_code": reason_code,
            "details": ["resolver diagnostic"],
            "recovery": "Repair the exact session identity or claim, then retry.",
        }
    )

    assert message.startswith(f"BLOCKED [prewrite/{reason_code}]\nWhy: {summary}\n")
    assert "The requested mutation lacks verified authority." not in message


def test_json_mode_preserves_deny_exit_for_unclaimed_workspace_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": "touch marker"})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "projection_unavailable_or_stale"


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
    assert decision["reason_code"] == "projection_unavailable_or_stale"


def test_workspace_root_child_cannot_borrow_parent_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = {
        **_payload(cwd=workspace, tool="Bash", tool_input={"command": "touch marker"}),
        "agent_id": "child-agent",
    }

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        payload,
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 2
    assert decision["reason_code"] == "no_exact_session_target"


@pytest.mark.parametrize(
    "command",
    [
        "touch /tmp/outside",
        "touch ../outside",
        "cd ../other && touch marker",
        "git -C /tmp/other commit -m x",
        "echo x > /tmp/outside",
        "target=/tmp/outside; touch $target",
    ],
)
def test_rebound_bash_rejects_external_or_unprovable_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    workspace, _repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Bash", tool_input={"command": command}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )
    assert code == 2
    assert decision["reason_code"] in {
        "bash_path_outside_worktree",
        "bash_target_unprovable",
        "bash_runtime_workdir_unattested",
        "target_worktree_not_claimed",
    }


def test_bound_workspace_root_command_still_denies_path_outside_claimed_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    command = f"/usr/bin/env -C {worktree} touch /tmp/outside"
    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Bash", tool_input={"command": command}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )
    assert code == 2
    assert decision["reason_code"] == "bash_path_outside_worktree"


def test_workspace_root_symlink_sequence_is_not_treated_as_target_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, _worktree, claims_dir, _claim_path = _fixture(tmp_path)
    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(
            cwd=workspace,
            tool="Bash",
            tool_input={"command": "ln -s .. link && touch link/pwn"},
        ),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )
    assert code == 2
    assert decision["reason_code"] == "bash_runtime_workdir_unattested"


def test_exact_projection_recovery_is_admissible_when_projection_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims_dir = tmp_path / "claims"
    projection = tmp_path / "projection.json"
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'refresh_prewrite_claim_projection.py'} "
        f"--claims-dir {claims_dir} --projection-path {projection}"
    )
    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command}),
        claims_dir=claims_dir,
        projection_path=projection,
    )
    assert code == 0
    assert decision["reason_code"] == "projection_recovery_command"


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


def test_explicit_mode_exempts_only_classified_sanctioned_maintenance(
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
        "receipt_id": "ordinary-maintenance",
        "normalized_target_paths": ["marker"],
    }
    exemption = {
        "reason_code": "sanctioned_unplanned_maintenance",
        "claim_project": "host-gate-test",
        "claim_scope": "host-gate-lane",
        "claim_source_file": str(tmp_path / "claim.yaml"),
        "tracker_path": str(tmp_path / "tracker.yaml"),
    }
    monkeypatch.setattr(prewrite_claim_gate, "evaluate_prewrite_fast", lambda *_args, **_kwargs: ordinary)
    monkeypatch.setattr(
        prewrite_claim_gate,
        "_sanctioned_maintenance_exemption",
        lambda _decision: exemption,
    )

    def unexpected(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("sanctioned maintenance must not require a selected outcome")

    monkeypatch.setattr(prewrite_claim_gate, "_enforce_selected_outcome", unexpected)

    code, result = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0
    assert result["decision"] == "allow"
    assert result["outcome_admission_exemption"] == exemption


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
        "sed -n 1p -i victim.txt",
        "sed -n 1p --in-place victim.txt",
        "sed -n 1p --in-place=.bak victim.txt",
        "sed -n 1p --in-p victim.txt",
        "sed -n 1p --in-p=.bak victim.txt",
        "sed -ni 1p victim.txt",
        "sed -n e file.txt",
        "find . -delete",
        "find . -fls report.txt",
        "git branch new-name",
        "git show HEAD > snapshot.txt",
        "rg --pre 'touch marker' needle .",
        "sort names.txt -o sorted.txt",
        "sort names.txt -uo sorted.txt",
        "sort names.txt --output=sorted.txt",
        "sort names.txt --out=sorted.txt",
        "sort names.txt -T .",
        "sort names.txt --compress-program='touch marker'",
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


@pytest.mark.parametrize("option", ["--in-p", "--in-p=.bak"])
def test_sed_abbreviated_in_place_long_option_is_not_read_only(option: str) -> None:
    assert not _argv_is_read_only(("sed", "-n", "1p", option, "victim.txt"))
