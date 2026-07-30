"""Both-sign checks for Plan 106 MF-06 operator-facing session response truth."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from enforced_planning import client_session_metadata, coordination_claims, coordination_messages


NOW = datetime(2026, 7, 30, 19, 15, tzinfo=UTC)
SESSION_ID = "codex:019f95f8-75e9-7a31-bba1-527695ed821e"
MESSAGE_ID = "msg_11111111111111111111111111111111"


def _write_index(path: Path) -> None:
    records = [
        {"id": SESSION_ID.removeprefix("codex:"), "thread_name": "old-name", "updated_at": "2026-07-29T10:00:00Z"},
        {"unrelated": "valid-object"},
        "{not-json",
        {
            "id": SESSION_ID.removeprefix("codex:"),
            "thread_name": "gap_closure_including_composability",
            "updated_at": "2026-07-30T10:00:00Z",
        },
    ]
    path.write_text(
        "\n".join(item if isinstance(item, str) else json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )


def _claim() -> coordination_claims.ClaimRecord:
    return coordination_claims.ClaimRecord(
        agent="codex",
        claimed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        projects=["Digimon_for_KG_application"],
        scope="digimon-plan189-sc-10-compatibility-deletion-and-promotion",
        intent="Close SC-10",
        claim_type="write",
        write_paths=[],
        read_paths=[],
        worktree_path="/tmp/worktree",
        repo_root="/tmp/repo",
        branch="plan189-sc10-promotion-20260730",
        session_name="close-plan-189-situational-composition-architecture-gap",
        broader_goal="Close Plan 189 situational composition architecture gap",
        tracker_path=None,
        session_id=SESSION_ID,
        heartbeat_at=NOW.isoformat(),
        status="active",
        updated_at=NOW.isoformat(),
        parent_scope="digimon-plan189-gap-closure-program",
        notes=None,
        plan_ref="Plan #189",
        source_file=None,
        schema_version=3,
    )


def _status(
    state: coordination_messages.MessageState,
) -> coordination_messages.MessageStatusView:
    message = coordination_messages.CoordinationMessage(
        schema_version="1.0",
        message_id=MESSAGE_ID,
        sender_session_id="codex:22222222-2222-2222-2222-222222222222",
        recipient_selector=coordination_messages.ExactSessionSelector(
            kind="session",
            session_id=SESSION_ID,
        ),
        recipient_session_id=SESSION_ID,
        project="Digimon_for_KG_application",
        kind="coordination_request",
        subject="Finish SC-10",
        body="Run the remaining gates.",
        created_at=NOW,
        expires_at=NOW + timedelta(days=1),
        request_sha256="a" * 64,
    )
    receipts: list[coordination_messages.MessageReceipt] = []
    if state in {"observed", "acknowledged"}:
        receipts.append(
            coordination_messages.MessageReceipt(
                schema_version="1.0",
                receipt_id="rcpt_33333333333333333333333333333333",
                message_id=MESSAGE_ID,
                recipient_session_id=SESSION_ID,
                event="observed",
                recorded_at=NOW + timedelta(minutes=1),
            )
        )
    if state == "acknowledged":
        receipts.append(
            coordination_messages.MessageReceipt(
                schema_version="1.0",
                receipt_id="rcpt_44444444444444444444444444444444",
                message_id=MESSAGE_ID,
                recipient_session_id=SESSION_ID,
                event="acknowledged",
                recorded_at=NOW + timedelta(minutes=2),
                disposition="accepted",
                note="Continuing SC-10.",
            )
        )
    return coordination_messages.MessageStatusView(
        message=message,
        state=state,
        runtime_accepted=state == "runtime_accepted",
        observed=state in {"observed", "acknowledged"},
        acknowledged=state == "acknowledged",
        expired=state == "expired",
        receipts=tuple(receipts),
        receipt_paths=tuple(f"/tmp/{receipt.receipt_id}.json" for receipt in receipts),
        receipt_set_sha256="b" * 64,
        message_path="/tmp/message.json",
    )


def test_codex_display_resolution_keeps_routing_identity_and_latest_name(tmp_path: Path) -> None:
    index = tmp_path / "session_index.jsonl"
    _write_index(index)

    display = client_session_metadata.resolve_client_session_display(
        SESSION_ID,
        codex_session_index=index,
    )

    assert display.session_id == SESSION_ID
    assert display.state == "resolved"
    assert display.display_name == "gap_closure_including_composability"
    assert display.source == str(index)
    assert display.warnings == ("invalid_json_line:3",)


def test_missing_index_and_non_codex_client_remain_explicit(tmp_path: Path) -> None:
    missing = client_session_metadata.resolve_client_session_display(
        SESSION_ID,
        codex_session_index=tmp_path / "missing.jsonl",
    )
    claude = client_session_metadata.resolve_client_session_display(
        "claude-code:session-1",
        codex_session_index=tmp_path / "unused.jsonl",
    )

    assert (missing.state, missing.display_name) == ("source_unavailable", None)
    assert (claude.state, claude.display_name) == ("not_supported", None)


@pytest.mark.parametrize(
    ("message_state", "response_state", "has_resume"),
    [
        ("persisted", "persisted_not_displayed", True),
        ("runtime_accepted", "runtime_accepted_not_displayed", True),
        ("observed", "displayed_awaiting_acknowledgement", True),
        ("acknowledged", "recipient_acknowledged", False),
        ("expired", "expired_unresolved", False),
    ],
)
def test_response_readout_never_conflates_display_acknowledgement_or_completion(
    tmp_path: Path,
    message_state: coordination_messages.MessageState,
    response_state: str,
    has_resume: bool,
) -> None:
    index = tmp_path / "session_index.jsonl"
    _write_index(index)

    readout = client_session_metadata.build_coordination_response_readout(
        _status(message_state),
        claims=[_claim()],
        codex_session_index=index,
    )

    assert readout.client_display.display_name == "gap_closure_including_composability"
    assert readout.internal_session_names == (
        "close-plan-189-situational-composition-architecture-gap",
    )
    assert readout.active_claim_scopes == (
        "digimon-plan189-sc-10-compatibility-deletion-and-promotion",
    )
    assert readout.retained_claim_scopes == ()
    assert readout.response_state == response_state
    assert readout.completion_claim == "not_evaluated"
    assert (readout.manual_resume_command is not None) is has_resume
    if readout.manual_resume_command:
        assert SESSION_ID.removeprefix("codex:") in readout.manual_resume_command
        assert "gap_closure_including_composability" not in readout.manual_resume_command


def test_session_status_enrichment_preserves_internal_name(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "session_status.py"
    spec = importlib.util.spec_from_file_location("session_status_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    index = tmp_path / "session_index.jsonl"
    _write_index(index)
    payload: dict[str, object] = {
        "session_count": 1,
        "sessions": [
            {
                "session_id": SESSION_ID,
                "session_name": "close-plan-189-situational-composition-architecture-gap",
            }
        ],
    }

    module.enrich_client_displays(payload, codex_session_index=index)

    session = payload["sessions"][0]  # type: ignore[index]
    assert session["session_name"] == "close-plan-189-situational-composition-architecture-gap"
    assert session["client_display"]["display_name"] == "gap_closure_including_composability"
