"""Regression tests for the pre-write gate's workspace-root bootstrap trap.

Background
----------
``scripts/prewrite_claim_gate.py --mode enforce`` caused two total session
outages (2026-08-28 and 2026-08-31).  Native sessions launch from a shared
workspace root such as ``~/code`` which is not a Git checkout.  The gate
resolved its mode from that *launch directory*, could not reach any governed
repository, and therefore denied every write -- including the ``Edit`` that
would have disabled the hook.  The only recovery was to reconfigure the client
from outside the session.

The contract these tests pin down:

* The mode is resolved from the payload that ``main`` has already rebound to
  the repository owning the *target*, not from the session launch directory.
* A mutation whose target is in no Git checkout at all cannot be authorised by
  any claim, so an explicit ``enforce`` downgrades to ``observe`` rather than
  denying.  This is what keeps the client's own configuration editable.
* A mutation whose target *is* inside a governed checkout still enforces, and
  a session whose claim authority failed to resolve still fails closed.  The
  downgrade must never become a way to opt out of the gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning.prewrite_claim_projection import write_projection
from scripts import prewrite_claim_gate

PAYLOAD_SESSION = "workspace-root-test"
CLAIM_SESSION = f"claude-code:{PAYLOAD_SESSION}"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _governed_repo(tmp_path: Path, *, claim_session: str | None) -> tuple[Path, Path, Path]:
    """Build a workspace root that is not a repo, holding one governed repo.

    ``claim_session`` names the session the lane claim belongs to.  ``None``
    leaves the lane unclaimed by writing the claim under a foreign session, so
    the projection is healthy and the denial is specifically "this session has
    no exact claim" rather than "the authority cache is missing".
    """

    workspace = tmp_path / "workspace"
    repo = workspace / "project"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    prewrite_mode: enforce\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md", "meta-process.yaml")
    _git(repo, "commit", "-m", "seed")

    worktree = repo / "worktrees" / "workspace-root-lane"
    worktree.parent.mkdir()
    _git(repo, "worktree", "add", "-b", "workspace-root-lane", str(worktree))
    (worktree / "src").mkdir()
    (worktree / "src" / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    now = datetime.now(timezone.utc)
    claim = {
        "schema_version": 3,
        "agent": "claude-code",
        "claimed_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "projects": ["workspace-root-test"],
        "scope": "workspace-root-lane",
        "intent": "exercise workspace-root mode resolution",
        "claim_type": "write",
        "plan_ref": "UNPLANNED",
        "write_paths": ["src"],
        "read_paths": [],
        "worktree_path": str(worktree),
        "repo_root": str(repo),
        "branch": "workspace-root-lane",
        "session_name": "workspace-root-test",
        "broader_goal": "exercise workspace-root mode resolution",
        "tracker_path": str(tmp_path / "tracker.yaml"),
        "session_id": claim_session or "claude-code:some-other-session",
        "heartbeat_at": now.isoformat(),
        "status": "active",
        "updated_at": now.isoformat(),
    }
    (claims_dir / "claude-code_workspace-root-test_workspace-root-lane.yaml").write_text(
        yaml.safe_dump(claim, sort_keys=False),
        encoding="utf-8",
    )
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    return workspace, worktree, claims_dir


def _payload(*, cwd: Path, tool: str, tool_input: dict[str, str]) -> dict[str, object]:
    return {
        "session_id": PAYLOAD_SESSION,
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
    }


def _run_gate(
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


# --------------------------------------------------------------------------
# The outage: a write whose target is in no repository must not be denied.
# --------------------------------------------------------------------------


def test_enforce_allows_edit_to_target_outside_any_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Session launched from a non-Git workspace root, target in no repo."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "notes" / "scratch.md"
    target.parent.mkdir()
    target.write_text("seed\n", encoding="utf-8")

    code, decision = _run_gate(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Edit", tool_input={"file_path": str(target)}),
    )

    assert code == 0, decision
    assert decision["mode"] == "observe"
    assert decision["decision"] != "deny"


def test_enforce_allows_edit_to_claude_settings_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The exact outage regression.

    ``~/.claude/settings.json`` is where this hook is configured and it lives
    outside any Git checkout.  A gate that can deny the only tool able to
    reconfigure it has no route out, which is how two sessions were lost.
    """

    home = tmp_path / "home"
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n", encoding="utf-8")
    workspace = tmp_path / "code"
    workspace.mkdir()

    code, decision = _run_gate(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Edit", tool_input={"file_path": str(settings)}),
    )

    assert code == 0, decision
    assert decision["mode"] == "observe"
    assert decision["decision"] != "deny"


def test_enforce_allows_read_only_bash_from_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A session in a non-Git workspace root keeps a usable shell."""

    workspace = tmp_path / "code"
    workspace.mkdir()

    code, decision = _run_gate(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Bash", tool_input={"command": "git status --short"}),
    )

    assert code == 0, decision
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "bash_read_only"


def test_session_ended_owner_closeout_is_claimless_control_command(
    tmp_path: Path,
) -> None:
    """An owner may reconcile its own explicitly ended claim from the workspace root."""

    _workspace, _worktree, claims_dir = _governed_repo(
        tmp_path,
        claim_session=CLAIM_SESSION,
    )
    claim_path = claims_dir / "claude-code_workspace-root-test_workspace-root-lane.yaml"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["status"] = "session_ended"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    command = (
        f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'session_close.py'} "
        "--agent claude-code --project workspace-root-test --scope workspace-root-lane "
        f"--session-id {CLAIM_SESSION} --reconcile-session-ended "
        f"--claim-sha256 {'a' * 64} --tracker-sha256 {'b' * 64} --json"
    )

    classification = prewrite_claim_gate._special_unclaimed_command(
        command,
        client="claude-code",
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=CLAIM_SESSION,
    )

    assert classification == "native_closeout"


def test_coordination_list_is_claimless_but_mutation_is_not(tmp_path: Path) -> None:
    """Zero-claim sessions may inspect coordination state, never mutate it."""

    script = prewrite_claim_gate.REPO_ROOT / "scripts" / "check_coordination_claims.py"
    read_command = f"/usr/bin/python3 {script} --list --project project-meta --json"
    mutation_command = f"/usr/bin/python3 {script} --prune-stale --project project-meta --json"

    assert (
        prewrite_claim_gate._special_unclaimed_command(
            read_command,
            client="claude-code",
            claims_dir=tmp_path / "claims",
            projection_path=tmp_path / "projection.json",
            subagent_event=False,
            native_session=CLAIM_SESSION,
        )
        == "hook_feedback_report"
    )
    assert not prewrite_claim_gate._special_unclaimed_command(
        mutation_command,
        client="claude-code",
        claims_dir=tmp_path / "claims",
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session=CLAIM_SESSION,
    )


def test_skill_feedback_append_is_claimless_but_hook_mode_is_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qualitative feedback remains possible after closeout without admitting stdin hooks."""

    home = tmp_path / "home"
    logger = home / ".claude" / "skill-feedback" / "log.py"
    logger.parent.mkdir(parents=True)
    logger.write_text("# logger\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    feedback_command = (
        f"/usr/bin/python3 {logger} --client codex --skill audit --rating 4 "
        "--task 'review a repair' --friction 'closeout blocked feedback' "
        "--fix 'admit the bounded logger'"
    )
    hook_command = f"/usr/bin/python3 {logger} --client codex --from-hook"

    assert (
        prewrite_claim_gate._special_unclaimed_command(
            feedback_command,
            client="codex",
            claims_dir=tmp_path / "claims",
            projection_path=tmp_path / "projection.json",
            subagent_event=False,
            native_session="codex:test",
        )
        == "hook_feedback_report"
    )
    assert not prewrite_claim_gate._special_unclaimed_command(
        hook_command,
        client="codex",
        claims_dir=tmp_path / "claims",
        projection_path=tmp_path / "projection.json",
        subagent_event=False,
        native_session="codex:test",
    )


@pytest.mark.parametrize(
    ("command", "reason_code"),
    [
        (
            f"/usr/bin/python3 {prewrite_claim_gate.REPO_ROOT / 'scripts' / 'check_coordination_claims.py'} "
            "--list --project project-meta --json",
            "hook_feedback_report_command",
        ),
        (
            f"/usr/bin/python3 {Path.home() / '.claude' / 'skill-feedback' / 'log.py'} "
            "--client codex --skill audit --rating 4 --task 'review a repair' "
            "--friction 'closeout blocked feedback' --fix 'admit the bounded logger'",
            "hook_feedback_report_command",
        ),
    ],
)
def test_zero_claim_session_admits_typed_inspection_and_feedback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    reason_code: str,
) -> None:
    """The full gate admits post-closeout inspection and feedback from a workspace root."""

    workspace = tmp_path / "code"
    workspace.mkdir()
    code, decision = _run_gate(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(cwd=workspace, tool="Bash", tool_input={"command": command}),
    )

    assert code == 0, decision
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == reason_code


# --------------------------------------------------------------------------
# The gate must not become a no-op: governed targets still enforce.
# --------------------------------------------------------------------------


def test_enforce_still_denies_unclaimed_edit_inside_governed_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Same non-Git launch directory, but the target is governed."""

    workspace, worktree, claims_dir = _governed_repo(tmp_path, claim_session=None)

    code, decision = _run_gate(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(
            cwd=workspace,
            tool="Edit",
            tool_input={"file_path": str(worktree / "src" / "allowed.py")},
        ),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 2, decision
    assert decision["mode"] == "enforce"
    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "no_exact_claim"


def test_enforce_allows_claimed_edit_inside_governed_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, worktree, claims_dir = _governed_repo(tmp_path, claim_session=CLAIM_SESSION)

    code, decision = _run_gate(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(
            cwd=workspace,
            tool="Edit",
            tool_input={"file_path": str(worktree / "src" / "allowed.py")},
        ),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 0, decision
    assert decision["mode"] == "enforce"
    assert decision["decision"] == "allow"
    assert decision["reason_code"] == "exact_live_claim"
    assert decision["worktree_path"] == str(worktree)


def test_enforce_still_denies_when_session_claim_authority_did_not_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Unresolved authority is not the same as "no governed repository".

    A claimed session naming a worktree outside its own claim resolves no
    target, so the payload keeps the non-Git launch directory.  Downgrading on
    that would let any claimed session escape its claim by running from a
    workspace root, so it must still fail closed.
    """

    workspace, _worktree, claims_dir = _governed_repo(tmp_path, claim_session=CLAIM_SESSION)
    outside = tmp_path / "elsewhere"
    outside.mkdir()

    code, decision = _run_gate(
        monkeypatch,
        capsys,
        tmp_path,
        _payload(
            cwd=workspace,
            tool="Bash",
            tool_input={"command": f"git -C {outside} commit -m x"},
        ),
        claims_dir=claims_dir,
        projection_path=tmp_path / "projection.json",
    )

    assert code == 2, decision
    assert decision["mode"] == "enforce"
    assert decision["decision"] == "deny"


# --------------------------------------------------------------------------
# Mode resolution itself.
# --------------------------------------------------------------------------


def test_explicit_enforce_is_not_downgraded_by_a_repo_without_meta_process(
    tmp_path: Path,
) -> None:
    """The host flag stays authoritative inside any Git checkout.

    Deferring to ``meta-process.yaml`` here would silently turn the gate off
    for every repository that does not configure ``claims.prewrite_mode``.
    """

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")

    assert prewrite_claim_gate._mode({"cwd": str(repo)}, "enforce") == "enforce"


def test_non_enforce_host_modes_are_returned_verbatim(tmp_path: Path) -> None:
    workspace = tmp_path / "code"
    workspace.mkdir()

    assert prewrite_claim_gate._mode({"cwd": str(workspace)}, "off") == "off"
    assert prewrite_claim_gate._mode({"cwd": str(workspace)}, "observe") == "observe"


def test_unconfigured_mode_outside_a_repository_is_off(tmp_path: Path) -> None:
    """Without a host mode there is nothing to downgrade and nothing to load."""

    workspace = tmp_path / "code"
    workspace.mkdir()

    assert prewrite_claim_gate._mode({"cwd": str(workspace)}, None) == "off"


def test_unconfigured_mode_inside_a_repository_reads_repo_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    prewrite_mode: enforce\n",
        encoding="utf-8",
    )

    assert prewrite_claim_gate._mode({"cwd": str(repo)}, None) == "enforce"
