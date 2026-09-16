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

from enforced_planning import coordination_claims, session_lifecycle
from enforced_planning.prewrite_claim_fast import (
    _argv_is_read_only,
    _bash_declared_paths,
    _bash_target_is_unprovable,
    evaluate_prewrite_fast,
)
from enforced_planning.prewrite_claim_projection import write_projection
from scripts import prewrite_claim_gate

SESSION = "claude-code:host-gate-test"
INSTALLED_SESSION_STATUS = Path.home() / ".codex/runtime/enforced-planning/scripts/session_status.py"


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
        "cat README.md",
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


def test_read_only_if_control_flow_does_not_require_claim(tmp_path: Path) -> None:
    command = (
        "git status --short && "
        "if test -f generated/runtime/active_work_registry.json; "
        "then jq -r '.claims[]?' generated/runtime/active_work_registry.json; "
        "else echo 'active registry missing'; fi"
    )
    payload = _payload(
        cwd=tmp_path,
        tool="Bash",
        tool_input={"command": command},
        session="unclaimed-session",
    )

    decision = _evaluate(tmp_path, payload, tmp_path / "missing-claims")

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "bash_read_only"


@pytest.mark.parametrize(
    "command",
    [
        "if true; then touch marker; fi",
        "if touch marker; then echo safe; fi",
        "if true; then echo safe; else rm marker; fi",
    ],
)
def test_if_control_flow_with_any_mutation_still_requires_claim(
    tmp_path: Path,
    command: str,
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    decision = _evaluate(tmp_path, payload, tmp_path / "missing-claims")

    assert decision["decision"] == "deny", decision
    assert decision["reason_code"] == "repository_identity_unavailable"


def test_compound_cat_inventory_from_workspace_root_does_not_require_claim(tmp_path: Path) -> None:
    payload = _payload(
        cwd=tmp_path,
        tool="Bash",
        tool_input={
            "command": "cat /workspace/CLAUDE.md && cat /workspace/project-meta/README.md",
        },
        session="unclaimed-session",
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


@pytest.mark.parametrize(
    "command",
    [
        "date -u +%Y-%m-%dT%H:%M:%SZ",
        "git ls-remote --heads origin | jq -R .",
        "gh pr view 132 --json state | jq -r .state",
        "gh-insidesuccess issue view 438 --repo Inside-Success/Team-Brains --json state | jq -r .state",
        "gh api --method GET repos/example/project | jq -r .default_branch",
        "gh api -XGET repos/example/project | jq -r .default_branch",
    ],
)
def test_external_observation_commands_and_safe_jq_pipelines_are_read_only(
    tmp_path: Path,
    command: str,
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    decision = _evaluate(tmp_path, payload, tmp_path / "missing-claims")

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "bash_read_only"


@pytest.mark.parametrize(
    ("client", "raw_session", "agent"),
    [
        ("codex", "codex-status-fixture", "codex"),
        ("claude-code", "claude-status-fixture", "claude-code"),
    ],
)
def test_canonical_installed_session_status_payload_is_read_only_for_both_clients(
    tmp_path: Path,
    client: str,
    raw_session: str,
    agent: str,
) -> None:
    """The exact installed status grammar bypasses claims without opening Python."""

    worktree = tmp_path / "target-worktree"
    worktree.mkdir()
    command = (
        f"/usr/bin/env -C {worktree} /usr/bin/python3 {INSTALLED_SESSION_STATUS} "
        f"--agent {agent} --project demo --scope lane "
        f"--session-id {agent}:{raw_session} --include-ended --json"
    )
    decision = evaluate_prewrite_fast(
        _payload(
            cwd=tmp_path,
            tool="Bash",
            tool_input={"command": command},
            session=raw_session,
        ),
        client=client,
        mode="enforce",
        claims_dir=tmp_path / "missing-claims",
        projection_path=tmp_path / "missing-projection.json",
        receipt_path=tmp_path / f"{client}-receipts.jsonl",
    )

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "bash_read_only"


@pytest.mark.parametrize(
    "command",
    [
        "/usr/bin/python3 /tmp/session_status.py --json",
        "/usr/bin/python3 -c 'print(1)'",
        f"/usr/bin/env -C relative /usr/bin/python3 {INSTALLED_SESSION_STATUS} --json",
        "/usr/bin/env -C /tmp/evil /usr/bin/python3 /tmp/evil/scripts/meta/session_status.py --json",
        f"/usr/bin/env -C /tmp/worktree /usr/bin/python3 {INSTALLED_SESSION_STATUS} --json --json",
        f"/usr/bin/env -C /tmp/worktree /usr/bin/python3 {INSTALLED_SESSION_STATUS} --write",
    ],
)
def test_session_status_lookalikes_do_not_create_generic_python_bypass(
    tmp_path: Path,
    command: str,
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    decision = _evaluate(tmp_path, payload, tmp_path / "missing-claims")

    assert decision["decision"] == "deny", decision
    assert decision["reason_code"] in {"no_exact_claim", "repository_identity_unavailable"}


@pytest.mark.parametrize(
    "command",
    [
        "date --set=tomorrow",
        "date --se=tomorrow",
        "git ls-remote --upload-pack='touch marker' origin",
        "gh pr merge 132",
        "gh api --method POST repos/example/project/issues",
        "gh api -XPOST repos/example/project/issues",
        "gh api repos/example/project -f name=value",
        "gh api repos/example/project -fname=value",
        "gh api repos/example/project -Fname=value",
        "python --help",
    ],
)
def test_write_capable_or_unbounded_observation_lookalikes_require_claim(
    tmp_path: Path,
    command: str,
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    decision = _evaluate(tmp_path, payload, tmp_path / "missing-claims")

    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "repository_identity_unavailable"


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
    assert "/usr/bin/make -C" in denied["recovery"]
    assert "split it into simple read-only commands" in denied["recovery"]


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


@pytest.mark.parametrize(
    "command",
    [
        "sha256sum image.png",
        "systemctl --user is-active code-image-ingest.path",
        "systemctl --user show code-image-ingest.path --property=ActiveState --value",
    ],
)
def test_host_gate_admits_workspace_root_status_and_hash_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0, decision
    assert decision["reason_code"] == "bash_read_only"


@pytest.mark.parametrize(
    "command",
    [
        "systemctl --user restart code-image-ingest.path",
        "systemctl --user enable code-image-ingest.path",
        "systemctl --user is-active",
    ],
)
def test_systemctl_mutation_or_incomplete_query_is_not_read_only(command: str) -> None:
    assert not _argv_is_read_only(tuple(command.split()))


def test_exact_shared_goal_validator_is_read_only() -> None:
    validator = (
        Path.home()
        / ".agents"
        / "skills"
        / "authoring-goals"
        / "scripts"
        / "validate_goal_authority.py"
    )
    assert _argv_is_read_only(("/usr/bin/python3", str(validator), "/tmp/goal.md"))
    assert not _argv_is_read_only(("python3", str(validator), "/tmp/goal.md"))
    assert not _argv_is_read_only(
        ("/usr/bin/python3", str(validator), "/tmp/goal.md", "--write")
    )


def test_quoted_brackets_do_not_make_literal_commit_message_unprovable() -> None:
    assert not _bash_target_is_unprovable("git commit -m '[Unplanned] literal message'")
    assert _bash_target_is_unprovable("touch source[12].txt")


def test_env_bound_python_script_is_read_input_not_external_mutation_target() -> None:
    command = (
        "/usr/bin/env -C /repo/worktrees/lane python3 "
        "/home/user/.codex/plugins/cache/company-planning/scripts/manage_plan_execution.py "
        "start .company-planning/candidate.json"
    )

    assert _bash_declared_paths(command) == (".company-planning/candidate.json",)


def test_env_bound_basename_command_retains_target_operand() -> None:
    command = "/usr/bin/env -C /repo/worktrees/lane /usr/bin/touch README.md"

    assert _bash_declared_paths(command) == ("README.md",)


def test_git_merge_revision_is_not_misclassified_as_a_path() -> None:
    command = "git -C /repo/worktrees/lane merge --no-edit origin/main"

    assert _bash_declared_paths(command) == ("/repo/worktrees/lane",)


def test_git_merge_message_file_remains_a_declared_path() -> None:
    command = "git -C /repo/worktrees/lane merge --file=notes/message.txt origin/main"

    assert _bash_declared_paths(command) == (
        "/repo/worktrees/lane",
        "notes/message.txt",
    )


def test_git_rev_list_range_is_an_identifier_not_a_path() -> None:
    command = "git -C /repo/worktrees/lane rev-list --left-right --count origin/topic...HEAD"

    assert _argv_is_read_only(tuple(command.split()))
    assert _bash_declared_paths(command) == ("/repo/worktrees/lane",)


def test_git_push_origin_branch_is_an_identifier_not_a_path() -> None:
    command = "git -C /repo/worktrees/lane push origin fix/topic"

    assert _bash_declared_paths(command) == ("/repo/worktrees/lane",)


def test_pytest_node_selector_retains_only_its_file_path() -> None:
    command = (
        "/usr/bin/env -C /repo/worktrees/lane python3 -m pytest -q "
        "tests/test_feature.py::test_exact_case"
    )

    assert _bash_declared_paths(command) == ("tests/test_feature.py",)


def test_session_close_scope_branch_and_recovery_ref_are_identifiers() -> None:
    command = (
        "/usr/bin/env -C /repo/worktrees/lane /usr/bin/python3 scripts/session_close.py "
        "--agent codex --project enforced-planning --scope runtime/install-fix "
        "--worktree-path /repo/worktrees/lane --branch runtime/install-fix "
        "--disposition merged --recovery-ref refs/recovery/runtime/install-fix"
    )

    assert _bash_declared_paths(command) == ("/repo/worktrees/lane",)


def test_make_session_close_branch_override_is_an_identifier() -> None:
    command = (
        "/usr/bin/make -C /repo/worktrees/lane session-close "
        "BRANCH=runtime/install-fix WORKTREE_RECOVERY_REF=refs/recovery/runtime/install-fix"
    )

    assert _bash_declared_paths(command) == ("/repo/worktrees/lane",)


def test_make_session_close_unknown_path_override_remains_a_target() -> None:
    command = (
        "/usr/bin/make -C /repo/worktrees/lane session-close "
        "BRANCH=runtime/install-fix PYTHON=/outside/python"
    )

    assert _bash_declared_paths(command) == (
        "/repo/worktrees/lane",
        "/outside/python",
    )


def test_untrusted_session_close_basename_does_not_gain_identifier_parsing() -> None:
    command = (
        "/usr/bin/python3 /tmp/session_close.py "
        "--scope /outside/claim --worktree-path /repo/worktrees/lane"
    )

    assert _bash_declared_paths(command) == (
        "/tmp/session_close.py",
        "/outside/claim",
        "/repo/worktrees/lane",
    )


def test_host_gate_admits_claimed_make_closeout_with_slash_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    command = (
        f"/usr/bin/make -C {worktree} session-close "
        "BRANCH=runtime/host-gate-lane"
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
    assert decision["reason_code"] == "exact_live_claim"


def test_host_gate_admits_claimed_relative_closeout_with_slash_identifiers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    command = (
        f"/usr/bin/env -C {worktree} /usr/bin/python3 scripts/session_close.py "
        "--agent claude-code --project host-gate-test --scope runtime/host-gate-lane "
        f"--worktree-path {worktree} --branch runtime/host-gate-lane "
        "--disposition merged --recovery-ref refs/recovery/runtime/host-gate-lane"
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
    assert decision["reason_code"] == "exact_live_claim"


def test_claimed_env_bound_python_manager_uses_candidate_as_the_write_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    command = (
        f"/usr/bin/env -C {worktree} python3 "
        "/opt/company-planning/scripts/manage_plan_execution.py "
        "start src/candidate.json"
    )

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Bash", tool_input={"command": command}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 0, decision
    assert decision["reason_code"] == "exact_live_claim"
    assert decision["normalized_target_paths"] == ["src/candidate.json"]


def test_host_gate_admits_exact_hook_feedback_make_target_without_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = (
        f"make -C {prewrite_claim_gate.REPO_ROOT} hook-feedback-report "
        "ARGS='--threshold 2 --format json'"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0, decision
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "hook_feedback_report_command"


def test_host_gate_admits_exact_maintenance_worktree_make_target_without_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = (
        f"make -C {prewrite_claim_gate.REPO_ROOT} maintenance-worktree "
        "BRANCH=verify/maintenance-bootstrap "
        "SESSION_WRITE_PATHS=.company-planning/maintenance-bootstrap-proof"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload)

    assert code == 0, decision
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "claim_bootstrap_command"


def test_root_agent_id_equal_to_session_id_keeps_maintenance_bootstrap_admitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = (
        f"make -C {prewrite_claim_gate.REPO_ROOT} maintenance-worktree "
        "BRANCH=verify/root-bootstrap"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})
    payload["agent_id"] = payload["session_id"]

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, client="codex")

    assert code == 0, decision
    assert decision["reason_code"] == "claim_bootstrap_command"


def test_child_agent_id_keeps_maintenance_bootstrap_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    command = (
        f"make -C {prewrite_claim_gate.REPO_ROOT} maintenance-worktree "
        "BRANCH=verify/child-bootstrap"
    )
    payload = _payload(cwd=tmp_path, tool="Bash", tool_input={"command": command})
    payload["agent_id"] = "different-child-agent"

    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, client="codex")

    assert code == 2
    assert decision["decision"] == "deny"


@pytest.mark.parametrize(
    "suffix",
    [
        "BRANCH=main",
        "BRANCH=../escape",
        "BRANCH=verify/safe SESSION_WRITE_PATHS=../escape",
        "BRANCH=verify/safe SESSION_WRITE_PATHS='src src'",
        "BRANCH=verify/safe EVIL=1",
        "BRANCH=verify/safe; touch escaped",
        "BRANCH=verify/safe WORKTREE_AGENT=claude-code",
    ],
)
def test_maintenance_worktree_make_target_rejects_unsafe_variants(suffix: str) -> None:
    command = f"make -C {prewrite_claim_gate.REPO_ROOT} maintenance-worktree {suffix}"

    assert prewrite_claim_gate._special_unclaimed_command(
        command,
        client="codex",
        claims_dir=Path("/tmp/claims"),
        projection_path=Path("/tmp/projection.json"),
        subagent_event=False,
        native_session=SESSION,
    ) is False


def test_maintenance_worktree_make_target_rejects_unmatched_control_files(tmp_path: Path) -> None:
    target = tmp_path / "lookalike"
    (target / "scripts").mkdir(parents=True)
    (target / "Makefile").write_text(
        "maintenance-worktree:\n\ttouch escaped\n", encoding="utf-8"
    )
    (target / "scripts" / "claim_bootstrap.py").write_text(
        "print('not canonical')\n", encoding="utf-8"
    )
    command = f"make -C {target} maintenance-worktree BRANCH=verify/safe"

    assert prewrite_claim_gate._special_unclaimed_command(
        command,
        client="codex",
        claims_dir=tmp_path / "claims",
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    ) is False


def test_maintenance_worktree_make_target_accepts_exact_rendered_consumer_block(
    tmp_path: Path,
) -> None:
    target = tmp_path / "consumer"
    (target / "scripts" / "meta").mkdir(parents=True)
    (target / "enforced_planning").mkdir()
    template = (
        prewrite_claim_gate.REPO_ROOT / "templates" / "Makefile.worktree.block.template"
    ).read_text(encoding="utf-8")
    rendered = template.replace(
        "__WORKTREE_SCRIPT_ROOT__", "scripts/meta/worktree-coordination"
    )
    (target / "Makefile").write_text(f"consumer-target:\n\t@true\n\n{rendered}", encoding="utf-8")
    (target / "scripts" / "meta" / "claim_bootstrap.py").write_bytes(
        (prewrite_claim_gate.REPO_ROOT / "scripts" / "claim_bootstrap.py").read_bytes()
    )
    (target / "enforced_planning" / "claim_bootstrap.py").write_bytes(
        (prewrite_claim_gate.REPO_ROOT / "enforced_planning" / "claim_bootstrap.py").read_bytes()
    )
    command = f"make -C {target} maintenance-worktree BRANCH=verify/consumer"

    assert prewrite_claim_gate._special_unclaimed_command(
        command,
        client="codex",
        claims_dir=tmp_path / "claims",
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    ) == "claim_bootstrap"


def test_hook_feedback_make_target_rejects_unmatched_control_files(tmp_path: Path) -> None:
    target = tmp_path / "lookalike"
    (target / "scripts").mkdir(parents=True)
    (target / "Makefile").write_text("hook-feedback-report:\n\ttouch escaped\n", encoding="utf-8")
    (target / "scripts" / "hook_feedback_report.py").write_text("print('not canonical')\n", encoding="utf-8")
    command = f"make -C {target} hook-feedback-report ARGS='--threshold 2'"

    assert prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=tmp_path / "claims",
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    ) is False


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
    monkeypatch.setenv("CODEX_THREAD_ID", "conflicting-shell-session")
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
    monkeypatch.setenv("CLAUDE_SESSION_ID", "conflicting-shell-session")
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


def test_host_gate_admits_exact_missing_worktree_reconciliation_for_session_ended_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    monkeypatch.setattr(prewrite_claim_gate, "REPO_ROOT", repo)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["status"] = coordination_claims.SESSION_ENDED_STATUS
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    _git(repo, "worktree", "remove", "--force", str(worktree))
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    command = (
        f"/usr/bin/python3 {repo / 'scripts' / 'session_close.py'} "
        "--agent claude-code --project host-gate-test --scope host-gate-lane "
        "--session-id claude-code:host-gate-test --reconcile-missing-worktree "
        f"--tracker-sha256 {'a' * 64} --json"
    )
    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    )
    assert classification == "native_closeout"
    payload = _payload(cwd=repo, tool="Bash", tool_input={"command": command})

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


def test_host_gate_rejects_ordinary_closeout_for_session_ended_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _workspace, repo, _worktree, claims_dir, claim_path = _fixture(tmp_path)
    monkeypatch.setattr(prewrite_claim_gate, "REPO_ROOT", repo)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["status"] = coordination_claims.SESSION_ENDED_STATUS
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    command = (
        f"/usr/bin/python3 {repo / 'scripts' / 'session_close.py'} "
        "--agent claude-code --project host-gate-test --scope host-gate-lane "
        "--session-id claude-code:host-gate-test --json"
    )

    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    )

    assert classification is False


def test_host_gate_admits_exact_native_session_end_for_unhealthy_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    monkeypatch.setattr(prewrite_claim_gate, "REPO_ROOT", repo)
    _git(repo, "worktree", "remove", "--force", str(worktree))
    command = (
        f"/usr/bin/python3 {repo / 'scripts' / 'session_end.py'} "
        "--agent claude-code --session-id claude-code:host-gate-test "
        "--reason 'recover missing worktree claim' --json"
    )
    payload = _payload(cwd=repo, tool="Bash", tool_input={"command": command})

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


@pytest.mark.parametrize(
    "command_suffix",
    [
        "--agent codex --session-id claude-code:host-gate-test --json",
        "--agent claude-code --session-id claude-code:other --json",
        "--agent claude-code --session-id claude-code:host-gate-test --json && touch escaped",
    ],
)
def test_host_gate_rejects_non_self_owned_native_session_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command_suffix: str,
) -> None:
    repo = tmp_path / "runtime"
    (repo / "scripts").mkdir(parents=True)
    monkeypatch.setattr(prewrite_claim_gate, "REPO_ROOT", repo)
    command = f"/usr/bin/python3 {repo / 'scripts' / 'session_end.py'} {command_suffix}"

    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=tmp_path / "claims",
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session="claude-code:host-gate-test",
    )

    assert classification is False


def test_host_gate_admits_exact_make_closeout_for_merged_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    (worktree / "Makefile").write_text("session-close:\n\t@true\n", encoding="utf-8")
    close_script = worktree / "scripts" / "meta" / "session_close.py"
    close_script.parent.mkdir(parents=True)
    close_script.write_text("# trusted fixture\n", encoding="utf-8")
    _git(worktree, "add", "src/allowed.py", "Makefile", "scripts/meta/session_close.py")
    _git(worktree, "commit", "-m", "merged lane work")
    _git(repo, "merge", "--ff-only", "host-gate-lane")
    monkeypatch.setattr(prewrite_claim_gate, "REPO_ROOT", repo)
    merge_commit = _git(repo, "rev-parse", "HEAD")
    command = (
        f"/usr/bin/make -C {worktree} session-close BRANCH=host-gate-lane "
        f"WORKTREE_AGENT=claude-code WORKTREE_PROJECT=host-gate-test "
        f"WORKTREE_DISPOSITION=merged WORKTREE_MERGE_COMMIT={merge_commit}"
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


def test_host_gate_routes_merged_consumer_make_closeout_to_installed_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unrelated consumer Git history gets an executable recovery, not bootstrap."""

    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    _git(worktree, "add", "src/allowed.py")
    _git(worktree, "commit", "-m", "merged consumer lane work")
    _git(repo, "merge", "--ff-only", "host-gate-lane")
    merge_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "commit", "--allow-empty", "-m", "advance default after merge")
    command = (
        f"/usr/bin/make -C {worktree} session-close BRANCH=host-gate-lane "
        f"WORKTREE_AGENT=claude-code WORKTREE_PROJECT=host-gate-test "
        f"WORKTREE_DISPOSITION=merged WORKTREE_MERGE_COMMIT={merge_commit}"
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

    recovery = decision["recovery"]
    installed_script = prewrite_claim_gate.REPO_ROOT / "scripts" / "session_close.py"
    assert code == 2
    assert decision["reason_code"] == "claim_not_healthy"
    assert any(
        "merged_active_claim_requires_disposition" in str(item)
        for item in decision["details"]
    )
    assert f"/usr/bin/python3 {installed_script}" in recovery
    assert "--session-id claude-code:host-gate-test" in recovery
    assert f"--worktree-path {worktree}" in recovery
    assert f"--merge-commit {merge_commit}" in recovery
    assert "/usr/bin/make" not in recovery
    assert "maintenance_worktree" not in recovery
    installed_command = recovery.split("instead: ", 1)[1]
    assert prewrite_claim_gate._special_unclaimed_command(
        installed_command,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    ) == "native_closeout"


@pytest.mark.parametrize("tamper", ["wrong-agent", "extra-assignment"])
def test_host_gate_does_not_translate_untrusted_consumer_make_closeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tamper: str,
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    _git(worktree, "add", "src/allowed.py")
    _git(worktree, "commit", "-m", "merged consumer lane work")
    _git(repo, "merge", "--ff-only", "host-gate-lane")
    _git(repo, "commit", "--allow-empty", "-m", "advance default after merge")
    agent = "codex" if tamper == "wrong-agent" else "claude-code"
    extra = " PYTHON=/tmp/python" if tamper == "extra-assignment" else ""
    command = (
        f"/usr/bin/make -C {worktree} session-close BRANCH=host-gate-lane "
        f"WORKTREE_AGENT={agent}{extra}"
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

    assert code == 2
    assert str(prewrite_claim_gate.REPO_ROOT / "scripts" / "session_close.py") not in str(
        decision.get("recovery")
    )


@pytest.mark.parametrize("tamper", ["dirty", "wrong-agent", "extra-assignment"])
def test_host_gate_rejects_tampered_make_closeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    (worktree / "Makefile").write_text("session-close:\n\t@true\n", encoding="utf-8")
    close_script = worktree / "scripts" / "meta" / "session_close.py"
    close_script.parent.mkdir(parents=True)
    close_script.write_text("# trusted fixture\n", encoding="utf-8")
    _git(worktree, "add", "src/allowed.py", "Makefile", "scripts/meta/session_close.py")
    _git(worktree, "commit", "-m", "merged lane work")
    _git(repo, "merge", "--ff-only", "host-gate-lane")
    monkeypatch.setattr(prewrite_claim_gate, "REPO_ROOT", repo)
    if tamper == "dirty":
        (worktree / "Makefile").write_text("session-close:\n\t@echo tampered\n", encoding="utf-8")
    agent = "codex" if tamper == "wrong-agent" else "claude-code"
    extra = " PYTHON=/tmp/python" if tamper == "extra-assignment" else ""
    command = (
        f"/usr/bin/make -C {worktree} session-close BRANCH=host-gate-lane "
        f"WORKTREE_AGENT={agent}{extra}"
    )

    assert prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    ) is False

def test_host_gate_admits_exact_dirty_handoff_finish_for_live_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_finish.py'} "
        "--agent claude-code --project host-gate-test --scope host-gate-lane "
        f"--worktree-path {worktree} --allow-dirty-handoff --json"
    )
    payload = _payload(cwd=workspace, tool="Bash", tool_input={"command": command})

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

    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "host-gate-test")
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    result = session_lifecycle.finish_session(
        agent="claude-code",
        project="host-gate-test",
        scope="host-gate-lane",
        worktree_path=str(worktree),
        allow_dirty_handoff=True,
        note="preserve dirty state after enforce-mode recovery",
        actor_session_id=SESSION,
    )
    claim = coordination_claims._load_claims(claims_dir)[0]
    assert result["action"] == "handoff"
    assert claim.status == "handoff"


def test_host_gate_rejects_claimless_session_finish_without_dirty_handoff(
    tmp_path: Path,
) -> None:
    _workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_finish.py'} "
        "--agent claude-code --project host-gate-test --scope host-gate-lane "
        f"--worktree-path {worktree} --json"
    )

    assert prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    ) is False


def test_host_gate_admits_bootstrap_closeout_for_real_target_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Control-plane closeout binds to the real target, not the authority sentinel."""

    workspace, _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim.update(
        schema_version=6,
        agent="codex",
        session_id="codex:host-gate-test",
        write_paths=["."],
        broad_scope_mode="bootstrap",
        broad_scope_reason="construct and narrow the exact maintenance lane",
        target_worktree_path=str(worktree),
        worktree_path=f"{worktree}.bootstrap-no-mutation-authority",
    )
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_close.py'} "
        "--agent codex --project host-gate-test --scope host-gate-lane "
        f"--worktree-path {worktree} --branch host-gate-lane --disposition merged --json"
    )
    payload = _payload(
        cwd=workspace,
        tool="Bash",
        tool_input={"command": command},
        session="host-gate-test",
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


def _bootstrap_narrow_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path, str]:
    """Return one valid authority-disabled v6 claim and its exact recovery command."""

    workspace, _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    monkeypatch.setenv("CODEX_THREAD_ID", "host-gate-test")
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim.update(
        schema_version=6,
        agent="codex",
        session_id="codex:host-gate-test",
        write_paths=["."],
        broad_scope_mode="bootstrap",
        broad_scope_reason="construct and narrow the exact maintenance lane",
        target_worktree_path=str(worktree),
        worktree_path=f"{worktree}.bootstrap-no-mutation-authority",
    )
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    command = (
        f"/usr/bin/make -C {worktree} session-narrow "
        "WORKTREE_AGENT=codex WORKTREE_PROJECT=host-gate-test "
        "BRANCH=host-gate-lane SESSION_WRITE_PATHS='src/allowed.py'"
    )
    return workspace, worktree, claims_dir, command


def test_workspace_root_admits_exact_native_session_narrow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bootstrap claim can admit its only strict-subset recovery operation."""

    workspace, _worktree, claims_dir, command = _bootstrap_narrow_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("CODEX_THREAD_ID", "conflicting-shell-session")
    payload = _payload(
        cwd=workspace,
        tool="Bash",
        tool_input={"command": command},
        session="host-gate-test",
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

    assert code == 0, decision
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "native_session_narrow_command"


def test_workspace_root_admits_direct_runtime_session_narrow_without_repo_make_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A registered non-governed target can use the canonical host runtime directly."""

    workspace, _worktree, claims_dir, _make_command = _bootstrap_narrow_fixture(
        tmp_path, monkeypatch
    )
    monkeypatch.setenv("CODEX_THREAD_ID", "conflicting-shell-session")
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_narrow.py'} "
        "--agent codex --project host-gate-test --scope host-gate-lane "
        "--session-id codex:host-gate-test --write-path src/allowed.py --json"
    )
    payload = _payload(
        cwd=workspace,
        tool="Bash",
        tool_input={"command": command},
        session="host-gate-test",
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

    assert code == 0, decision
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "native_session_narrow_command"


@pytest.mark.parametrize(
    "tamper",
    ["wrong-session", "noncanonical-script", "traversal", "composed", "subagent"],
)
def test_workspace_root_rejects_tampered_direct_runtime_session_narrow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    _workspace, _worktree, claims_dir, _make_command = _bootstrap_narrow_fixture(
        tmp_path, monkeypatch
    )
    script = prewrite_claim_gate.REPO_ROOT / "scripts" / "session_narrow.py"
    session_id = "codex:other" if tamper == "wrong-session" else "codex:host-gate-test"
    write_path = "../escaped.py" if tamper == "traversal" else "src/allowed.py"
    if tamper == "noncanonical-script":
        script = tmp_path / "session_narrow.py"
    command = (
        f"/usr/bin/python3 {script} --agent codex --project host-gate-test "
        f"--scope host-gate-lane --session-id {session_id} --write-path {write_path} --json"
    )
    if tamper == "composed":
        command += " && touch escaped"

    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="codex",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=tamper == "subagent",
        native_session="codex:host-gate-test",
    )

    assert classification is False


def test_native_session_narrow_does_not_fall_back_to_shell_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The authenticated hook payload, not an ambient variable, owns control commands."""

    workspace, _worktree, claims_dir, command = _bootstrap_narrow_fixture(tmp_path, monkeypatch)
    payload = _payload(cwd=workspace, tool="Bash", tool_input={"command": command})
    payload.pop("session_id")

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        payload,
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        client="codex",
    )

    assert code == 2
    assert decision["ok"] is False
    assert decision["reason_code"] == "invalid_hook_payload"
    assert "session_id" in decision["error"]


@pytest.mark.parametrize(
    "tamper",
    [
        "extra-variable",
        "composed",
        "relative-target",
        "traversal-path",
        "client-mismatch",
        "no-op",
        "subagent",
    ],
)
def test_workspace_root_rejects_tampered_native_session_narrow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    """Composition, ambiguity, expansion, and borrowed identity all fail closed."""

    _workspace, worktree, claims_dir, command = _bootstrap_narrow_fixture(tmp_path, monkeypatch)
    if tamper == "extra-variable":
        command += " EXTRA=1"
    elif tamper == "composed":
        command += " && touch escaped"
    elif tamper == "relative-target":
        command = command.replace(str(worktree), "relative/worktree", 1)
    elif tamper == "traversal-path":
        command = command.replace("src/allowed.py", "../escaped.py")
    elif tamper == "client-mismatch":
        command = command.replace("WORKTREE_AGENT=codex", "WORKTREE_AGENT=claude-code")
    elif tamper == "no-op":
        command = command.replace("src/allowed.py", ".")
    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="codex",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=tamper == "subagent",
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
        tool_input={"command": f"/usr/bin/env -C {worktree} touch src/allowed.py"},
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
    assert decision["normalized_target_paths"] == ["src/allowed.py"]


def test_git_launch_cwd_resolves_bash_through_different_exact_session_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    payload = _payload(
        cwd=repo,
        tool="Bash",
        tool_input={"command": f"/usr/bin/env -C {worktree} touch src/allowed.py"},
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
    assert decision["normalized_target_paths"] == ["src/allowed.py"]


def test_git_launch_cwd_accepts_quoted_shell_metacharacters_in_bound_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    command = (
        f"/usr/bin/env -C {worktree} gh api --method POST example "
        "-f 'description=verified; exact head | approved'"
    )

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=repo, tool="Bash", tool_input={"command": command}),
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
            tool_input={"command": f"/usr/bin/env -C {worktree} touch src/allowed.py"},
        ),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "projection_unavailable_or_stale"


def test_git_launch_cwd_repairs_valid_projection_staled_by_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _workspace, repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")

    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(
            cwd=repo,
            tool="Bash",
            tool_input={"command": f"/usr/bin/env -C {worktree} touch src/allowed.py"},
        ),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 0
    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "exact_live_claim"
    assert decision["normalized_target_paths"] == ["src/allowed.py"]


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
        tool_input={"command": f"/usr/bin/env -C {worktree} touch src/allowed.py"},
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
    assert decision["recovery"] == (
        "Create one healthy claim for this native session with the exact typed maintenance_worktree "
        "claim-bootstrap transaction, or close duplicate claims before mutating. The raw Bash "
        "bootstrap form must start with /usr/bin/python3 and the installed canonical "
        "scripts/claim_bootstrap.py; bare python3 is intentionally not admitted."
    )


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


def test_bound_worktree_command_denies_repo_relative_path_outside_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, _repo, worktree, claims_dir, _claim_path = _fixture(tmp_path)
    command = f"/usr/bin/env -C {worktree} touch GETTING_STARTED.md"
    code, decision = _run_cli(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Bash", tool_input={"command": command}),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 2
    assert decision["reason_code"] == "path_outside_claim"
    assert decision["normalized_target_paths"] == ["GETTING_STARTED.md"]


def _plan_cursor_command_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, Path, Path]:
    _workspace, _repo, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["write_paths"] = [
        "src",
        ".company-planning/active-execution.json",
        ".company-planning/history",
    ]
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        coordination_claims,
        "claim_runtime_status",
        lambda _claim, *, active_claims: "healthy",
    )

    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    version = "0.2.0+codex.test"
    plugin = home / ".codex/plugins/cache/inside-success/company-planning" / version
    manager = plugin / "scripts" / "manage_plan_execution.py"
    manager.parent.mkdir(parents=True)
    manager.write_text("# trusted fixture\n", encoding="utf-8")
    manifest = plugin / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps({"name": "company-planning", "version": version}),
        encoding="utf-8",
    )
    candidate = tmp_path / "candidate.json"
    candidate.write_text("{}\n", encoding="utf-8")
    command = (
        f"/usr/bin/env -C {worktree} /usr/bin/python3 {manager} --cwd {worktree} "
        f"--session-id {SESSION} start {candidate}"
    )
    return command, claims_dir, worktree


@pytest.mark.parametrize("operation", ["start", "replace", "archive"])
def test_exact_plan_cursor_manager_treats_candidate_as_read_only_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    command, claims_dir, _worktree = _plan_cursor_command_fixture(tmp_path, monkeypatch)
    if operation == "replace":
        command = command.replace(" start ", " replace ") + " --expected-revision 1"
    elif operation == "archive":
        command = command.rsplit(" start ", 1)[0] + " archive"

    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=SESSION,
    )

    assert classification == "claim_bootstrap"


@pytest.mark.parametrize(
    "tamper",
    ["wrong-session", "wrong-worktree", "wrong-runtime-worktree", "untrusted", "composed"],
)
def test_plan_cursor_manager_rejects_unbound_or_composed_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    command, claims_dir, worktree = _plan_cursor_command_fixture(tmp_path, monkeypatch)
    if tamper == "wrong-session":
        command = command.replace(SESSION, "claude-code:other")
    elif tamper == "wrong-worktree":
        other = tmp_path / "other"
        other.mkdir()
        command = command.replace(f"--cwd {worktree}", f"--cwd {other}")
    elif tamper == "wrong-runtime-worktree":
        other = tmp_path / "other"
        other.mkdir()
        command = command.replace(f"-C {worktree}", f"-C {other}")
    elif tamper == "untrusted":
        untrusted = tmp_path / "manage_plan_execution.py"
        untrusted.write_text("# untrusted fixture\n", encoding="utf-8")
        manager = next(token for token in command.split() if token.endswith("/manage_plan_execution.py"))
        command = command.replace(manager, str(untrusted))
    else:
        command += " && touch escaped"

    with pytest.raises(ValueError):
        prewrite_claim_gate._parse_plan_execution_cursor_command(
            command,
            client="claude-code",
            claims_dir=claims_dir,
            native_session=SESSION,
        )


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


def test_delegated_maintenance_exemption_is_distinct_and_evidenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from enforced_planning import outcome_admission

    class DelegatedClaim:
        scope = "fix/delegated-child"
        source_file = "/tmp/delegated-claim.yaml"
        tracker_path = "/tmp/delegated-tracker.yaml"
        parent_scope = "weekly-parent"
        start_revision = "a" * 40

        @staticmethod
        def primary_project() -> str:
            return "host-gate-test"

    claim = DelegatedClaim()
    monkeypatch.setattr(prewrite_claim_gate, "_exact_outcome_claim", lambda _decision: claim)
    monkeypatch.setattr(
        outcome_admission,
        "is_sanctioned_maintenance_claim",
        lambda _claim: False,
    )
    monkeypatch.setattr(
        outcome_admission,
        "is_sanctioned_delegated_maintenance_claim",
        lambda _claim: True,
        raising=False,
    )

    result = prewrite_claim_gate._sanctioned_maintenance_exemption(
        {
            "decision": "allow",
            "reason_code": "exact_live_claim",
            "claim_source_file": claim.source_file,
        }
    )

    assert result == {
        "reason_code": "sanctioned_delegated_maintenance",
        "claim_project": "host-gate-test",
        "claim_scope": "fix/delegated-child",
        "claim_source_file": claim.source_file,
        "tracker_path": claim.tracker_path,
        "parent_scope": "weekly-parent",
        "start_revision": "a" * 40,
    }


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


def _no_claim_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """A real git repo with an empty (no live claim) claims registry.

    Distinct from `_fixture`, which always seeds one claim -- this exercises
    the append-only exemption's actual trigger condition: zero matching
    claims at all, not merely an unhealthy or non-covering one.
    """
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    (repo / "learnings" / "entries").mkdir(parents=True)
    (repo / "policy" / "proposals").mkdir(parents=True)
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    return repo, claims_dir


def test_append_only_write_is_exempt_with_zero_live_claims(tmp_path: Path) -> None:
    """A session with no claim at all can still record a learning/finding.

    An append-only store cannot contend with itself
    (enforced_planning/coordination_claims.py's APPEND_ONLY_WRITE_PREFIXES);
    this is the same exemption for the earlier gate a zero-claim session
    actually hits (lrn: Plan #259 Step 5 -- evaluate_request_fast()'s
    `if not candidates` branch previously denied this unconditionally).
    """
    repo, claims_dir = _no_claim_fixture(tmp_path)
    payload = _payload(
        cwd=repo,
        tool="Write",
        tool_input={"file_path": str(repo / "learnings" / "entries" / "probe.json")},
    )

    decision = _evaluate(tmp_path, payload, claims_dir)

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "append_only_exempt"


def test_append_only_exemption_covers_policy_proposals_too(tmp_path: Path) -> None:
    """The exemption follows the same prefix list as coordination_claims.py, not just learnings/."""
    repo, claims_dir = _no_claim_fixture(tmp_path)
    payload = _payload(
        cwd=repo,
        tool="Write",
        tool_input={"file_path": str(repo / "policy" / "proposals" / "2026-09-05-idea.yaml")},
    )

    decision = _evaluate(tmp_path, payload, claims_dir)

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "append_only_exempt"


def test_append_only_exemption_does_not_cover_a_mixed_mutation(tmp_path: Path) -> None:
    """One append-only path plus one ordinary path must still require a claim.

    The exemption is narrow by design: every target must be append-only, or
    a session could smuggle an arbitrary write through by pairing it with a
    throwaway learnings/entries touch.
    """
    repo, claims_dir = _no_claim_fixture(tmp_path)
    payload = _payload(
        cwd=repo,
        tool="Bash",
        tool_input={
            "command": (
                f"echo hi > {repo}/learnings/entries/probe.json && "
                f"echo hi > {repo}/README.md"
            )
        },
    )

    decision = _evaluate(tmp_path, payload, claims_dir)

    assert decision["decision"] == "deny", decision
    assert decision["reason_code"] == "no_exact_claim"


def test_ordinary_path_alone_still_denies_with_zero_claims(tmp_path: Path) -> None:
    """A non-append-only write with zero claims is unaffected by the exemption."""
    repo, claims_dir = _no_claim_fixture(tmp_path)
    payload = _payload(cwd=repo, tool="Write", tool_input={"file_path": str(repo / "README.md")})

    decision = _evaluate(tmp_path, payload, claims_dir)

    assert decision["decision"] == "deny", decision
    assert decision["reason_code"] == "no_exact_claim"
