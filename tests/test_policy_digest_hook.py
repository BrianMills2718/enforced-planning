from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from scripts import policy_digest_hook
from scripts.hook_receipts import load_completed_receipts


def _repo(path: Path, name: str = "alpha") -> Path:
    repo = path / name
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
    return repo


def _proposal(
    root: Path,
    proposal_id: str,
    *,
    scope: str,
    status: str = "pending",
    applicability: dict | None = None,
    priority: str = "normal",
) -> None:
    payload = {
        "id": proposal_id,
        "date": "2026-08-01",
        "status": status,
        "scope": scope,
        "priority": priority,
    }
    if applicability is not None:
        payload.update(
            {
                "schema_version": 2,
                "applicability": applicability,
                "decision": {"owner": "brian", "priority": priority, "review_after": None},
            }
        )
    (root / f"{proposal_id}.yaml").write_text(
        yaml.safe_dump(payload),
        encoding="utf-8",
    )


def _invoke(
    monkeypatch,
    capsys,
    *,
    cwd: Path,
    proposals: Path,
    state: Path,
    now: int,
    receipts: Path | None = None,
) -> tuple[int, str]:
    monkeypatch.setattr(
        sys,
        "stdin",
        StringIO(json.dumps({"session_id": "s1", "hook_event_name": "SessionStart", "cwd": str(cwd)})),
    )
    receipt_dir = receipts if receipts is not None else state.parent / "hook-receipts"
    code = policy_digest_hook.main(
        [
            "--agent",
            "claude-code",
            "--proposals-dir",
            str(proposals),
            "--state-dir",
            str(state),
            "--today",
            "2026-08-28",
            "--now-epoch",
            str(now),
            "--hook-receipt-dir",
            str(receipt_dir),
        ]
    )
    return code, capsys.readouterr().out


def _completed_receipts(receipt_dir: Path) -> list[dict]:
    return list(load_completed_receipts(receipt_dir))


def test_digest_is_project_scoped_compact_and_advisory(tmp_path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    _proposal(proposals, "alpha-local", scope="alpha maintenance")
    _proposal(proposals, "global-rule", scope="all projects")
    _proposal(proposals, "other-local", scope="beta only")
    _proposal(proposals, "already-done", scope="all projects", status="accepted")

    code, output = _invoke(
        monkeypatch,
        capsys,
        cwd=repo,
        proposals=proposals,
        state=tmp_path / "state",
        now=1_000,
    )

    assert code == 0
    message = json.loads(output)["hookSpecificOutput"]["additionalContext"]
    assert "2 pending proposal(s) relevant to alpha" in message
    assert "alpha-local" in message and "global-rule" in message
    assert "other-local" not in message and "already-done" not in message
    assert "advisory" in message and "never blocks work" in message


def test_digest_cools_down_but_new_relevant_policy_wakes_it(tmp_path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    state = tmp_path / "state"
    _proposal(proposals, "first", scope="all projects")

    assert _invoke(monkeypatch, capsys, cwd=repo, proposals=proposals, state=state, now=1_000)[1]
    assert _invoke(monkeypatch, capsys, cwd=repo, proposals=proposals, state=state, now=1_100)[1] == ""

    _proposal(proposals, "second", scope="alpha")
    changed = _invoke(monkeypatch, capsys, cwd=repo, proposals=proposals, state=state, now=1_200)[1]
    assert "second" in changed


def test_v2_digest_routes_only_from_structured_applicability(tmp_path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    empty_dimensions = {"capabilities": [], "events": []}
    _proposal(
        proposals,
        "alpha-structured",
        scope="legacy text does not mention alpha",
        applicability={"kind": "projects", "projects": ["alpha"], **empty_dimensions},
    )
    _proposal(
        proposals,
        "global-structured",
        scope="narrow-looking legacy text",
        applicability={"kind": "global", "projects": [], **empty_dimensions},
    )
    _proposal(
        proposals,
        "unclassified",
        scope="all projects",
        applicability={
            "kind": "needs-classification",
            "projects": [],
            "classification_note": "Human review required.",
            **empty_dimensions,
        },
    )
    _proposal(
        proposals,
        "beta-structured",
        scope="alpha appears here but must not be guessed",
        applicability={"kind": "projects", "projects": ["beta"], **empty_dimensions},
    )

    code, output = _invoke(
        monkeypatch,
        capsys,
        cwd=repo,
        proposals=proposals,
        state=tmp_path / "state",
        now=1_000,
    )

    assert code == 0
    message = json.loads(output)["hookSpecificOutput"]["additionalContext"]
    assert "2 pending proposal(s) relevant to alpha" in message
    assert "alpha-structured" in message and "global-structured" in message
    assert "unclassified" not in message and "beta-structured" not in message


def test_non_session_event_is_silent(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        StringIO(json.dumps({"session_id": "s1", "hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path)})),
    )
    receipts = tmp_path / "hook-receipts"

    assert policy_digest_hook.main(["--agent", "claude-code", "--hook-receipt-dir", str(receipts)]) == 0

    [receipt] = _completed_receipts(receipts)
    assert receipt["decision"] == "skip"
    assert receipt["reason_code"] == "not_session_start"


def test_receipt_records_emit_and_skip_decisions(tmp_path, monkeypatch, capsys) -> None:
    repo = _repo(tmp_path)
    proposals = tmp_path / "proposals"
    proposals.mkdir()
    state = tmp_path / "state"
    receipts = tmp_path / "hook-receipts"
    _proposal(proposals, "first", scope="all projects")

    emitted_code, emitted_output = _invoke(
        monkeypatch, capsys, cwd=repo, proposals=proposals, state=state, now=1_000, receipts=receipts
    )
    assert emitted_code == 0
    assert emitted_output

    cooled_code, cooled_output = _invoke(
        monkeypatch, capsys, cwd=repo, proposals=proposals, state=state, now=1_100, receipts=receipts
    )
    assert cooled_code == 0
    assert cooled_output == ""

    receipts_in_order = _completed_receipts(receipts)
    assert [r["decision"] for r in receipts_in_order] == ["emit", "skip"]
    assert [r["reason_code"] for r in receipts_in_order] == ["digest_emitted", "cooldown_active"]
    assert all(r["hook_name"] == "policy-digest" for r in receipts_in_order)
    assert all(r["exit_status"] == 0 for r in receipts_in_order)
    assert capsys.readouterr().out == ""
