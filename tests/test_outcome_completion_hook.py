from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from enforced_planning.coordination_messages import SessionInboxNotice
from enforced_planning.outcome_completion import OutcomeCompletionStopDecisionV1
from scripts import coordination_hook


def test_completion_cli_bootstraps_when_installed_under_scripts_meta(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "consumer"
    (repo / "scripts" / "meta").mkdir(parents=True)
    (repo / "enforced_planning").mkdir()
    source_root = Path(__file__).resolve().parents[1]
    for source in (source_root / "enforced_planning").glob("*.py"):
        (repo / "enforced_planning" / source.name).write_bytes(source.read_bytes())
    installed = repo / "scripts" / "meta" / "outcome_completion_hook.py"
    installed.write_bytes((source_root / "scripts" / "outcome_completion_hook.py").read_bytes())

    completed = subprocess.run(
        [sys.executable, str(installed), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Record canonical selected-outcome completion" in completed.stdout


def _run_stop(monkeypatch, tmp_path: Path, capsys, *, decision: OutcomeCompletionStopDecisionV1):
    payload = {
        "session_id": "native-session",
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
        "last_assistant_message": "done",
    }
    monkeypatch.setattr(coordination_hook, "_read_hook_input", lambda **_kwargs: payload)
    monkeypatch.setattr(coordination_hook, "_active_claims", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "dashboard")
    monkeypatch.setattr(coordination_hook, "_worktree_root", lambda _cwd: tmp_path)
    monkeypatch.setattr(coordination_hook, "_repository_closeout_failure", lambda **_kwargs: None)
    monkeypatch.setattr(
        coordination_hook.coordination_messages,
        "poll_session_inbox",
        lambda **_kwargs: SessionInboxNotice(
            session_id="codex:native-session",
            project="dashboard",
            active_count=0,
            message_ids=(),
            summary="",
        ),
    )
    monkeypatch.setattr(
        coordination_hook.outcome_completion,
        "evaluate_stop_for_session",
        lambda **_kwargs: decision,
    )
    result = coordination_hook.main(
        [
            "--claims-dir",
            str(tmp_path / "claims"),
            "--root",
            str(tmp_path / "messages"),
            "--hook-receipt-dir",
            str(tmp_path / "receipts"),
        ]
    )
    return result, capsys.readouterr().out


def test_native_stop_blocks_incomplete_selected_outcome(monkeypatch, tmp_path: Path, capsys) -> None:
    decision = OutcomeCompletionStopDecisionV1(
        applicable=True,
        allow_stop=False,
        reason_code="canonical_outcome_incomplete",
        summary=(
            "Outcome completion blocked: native green tasks and an archived cursor "
            "do not satisfy the frozen Purpose Map criteria."
        ),
        outcome_id="dashboard-purpose-map",
        current_lease_sha256="a" * 64,
    )
    result, output = _run_stop(monkeypatch, tmp_path, capsys, decision=decision)
    assert result == 0
    rendered = json.loads(output)
    assert rendered["decision"] == "block"
    assert "archived cursor" in rendered["reason"]


def test_native_stop_emits_no_denial_after_canonical_completion(monkeypatch, tmp_path: Path, capsys) -> None:
    decision = OutcomeCompletionStopDecisionV1(
        applicable=True,
        allow_stop=True,
        reason_code="canonical_outcome_complete",
        summary="Canonical selected outcome dashboard-purpose-map is complete.",
        outcome_id="dashboard-purpose-map",
        current_lease_sha256="a" * 64,
        completion_transition_sha256="b" * 64,
    )
    result, output = _run_stop(monkeypatch, tmp_path, capsys, decision=decision)
    assert result == 0
    assert output == ""


def test_stop_evaluates_claimed_worktree_when_callback_cwd_is_workspace_root(monkeypatch, tmp_path: Path) -> None:
    worktree = tmp_path / "dashboard-worktree"
    worktree.mkdir()
    claim = type(
        "ProjectedClaim",
        (),
        {
            "agent": "codex",
            "session_id": "codex:native-session",
            "worktree_path": str(worktree),
            "projects": ("initiative-roadmap-dashboard",),
        },
    )()
    observed: list[tuple[Path, str]] = []
    monkeypatch.setattr(coordination_hook, "_worktree_root", lambda _cwd: None)
    monkeypatch.setattr(
        coordination_hook.outcome_completion,
        "evaluate_stop_for_session",
        lambda **kwargs: (
            observed.append((kwargs["repo_root"], kwargs["project"]))
            or OutcomeCompletionStopDecisionV1(
                applicable=True,
                allow_stop=False,
                reason_code="canonical_outcome_incomplete",
                summary="Dashboard outcome remains incomplete.",
            )
        ),
    )

    decisions = coordination_hook._outcome_stop_decisions(
        payload={"cwd": str(tmp_path)},
        agent="codex",
        session_id="codex:native-session",
        cwd_project=None,
        active_claims=(claim,),
    )

    assert len(decisions) == 1
    assert decisions[0].allow_stop is False
    assert observed == [(worktree.resolve(), "initiative-roadmap-dashboard")]
