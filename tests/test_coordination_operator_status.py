"""Both-sign checks for Plan 106 MF-06 operator-facing session response truth."""

from __future__ import annotations

import importlib.util
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

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


def test_missing_index_and_unsupported_client_remain_explicit(tmp_path: Path) -> None:
    missing = client_session_metadata.resolve_client_session_display(
        SESSION_ID,
        codex_session_index=tmp_path / "missing.jsonl",
    )
    absent_registry = client_session_metadata.resolve_client_session_display(
        "claude-code:session-1",
        codex_session_index=tmp_path / "unused.jsonl",
        claude_session_registry=tmp_path / "missing-sessions",
    )
    openclaw = client_session_metadata.resolve_client_session_display(
        "openclaw:session-1",
        codex_session_index=tmp_path / "unused.jsonl",
        claude_session_registry=tmp_path / "unused-sessions",
    )

    assert (missing.state, missing.display_name) == ("source_unavailable", None)
    assert (absent_registry.state, absent_registry.display_name) == ("source_unavailable", None)
    assert (openclaw.state, openclaw.display_name) == ("not_supported", None)


def _write_claude_registry(registry: Path) -> None:
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "104821.json").write_text(
        json.dumps(
            {
                "pid": 104821,
                "sessionId": "58a54b6c-683c-454c-a1b2-430cf78fc48a",
                "name": "never_0902",
                "updatedAt": 1788370433034,
            }
        ),
        encoding="utf-8",
    )
    (registry / "21735.json").write_text(
        json.dumps({"pid": 21735, "sessionId": "other-session", "name": "organization_0902"}),
        encoding="utf-8",
    )
    (registry / "broken.json").write_text("{not json", encoding="utf-8")


def test_claude_code_display_resolves_the_name_peers_address(tmp_path: Path) -> None:
    registry = tmp_path / "sessions"
    _write_claude_registry(registry)

    display = client_session_metadata.resolve_client_session_display(
        "claude-code:58a54b6c-683c-454c-a1b2-430cf78fc48a",
        codex_session_index=tmp_path / "unused.jsonl",
        claude_session_registry=registry,
    )

    assert display.session_id == "claude-code:58a54b6c-683c-454c-a1b2-430cf78fc48a"
    assert display.client == "claude-code"
    assert display.state == "resolved"
    assert display.display_name == "never_0902"
    assert display.client_updated_at == "2026-09-02T17:33:53.034000+00:00"
    assert display.warnings == ("unreadable_record:broken.json",)


def test_claude_code_session_absent_from_registry_is_not_found(tmp_path: Path) -> None:
    registry = tmp_path / "sessions"
    _write_claude_registry(registry)

    display = client_session_metadata.resolve_client_session_display(
        "claude-code:no-such-session",
        codex_session_index=tmp_path / "unused.jsonl",
        claude_session_registry=registry,
    )

    assert (display.state, display.display_name) == ("not_found", None)
    assert display.source == str(registry)


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


def test_operator_readout_exposes_state_disabled_pretooluse_as_advisory_only(
    tmp_path: Path,
) -> None:
    """The canonical readout reports actual operator-host enforcement, not hook presence."""

    index = tmp_path / "session_index.jsonl"
    _write_index(index)
    config = tmp_path / "config.toml"
    adapter = tmp_path / "coordination_hook.py"
    shutil.copy2(Path(__file__).resolve().parents[1] / "scripts" / adapter.name, adapter)
    command = f"python3 {adapter} --agent codex"
    config.write_text(
        f'''[[hooks.SessionStart]]
matcher = "startup|resume|clear|compact"
[[hooks.SessionStart.hooks]]
type = "command"
command = "{command}"

[[hooks.PostToolUse]]
matcher = "*"
[[hooks.PostToolUse.hooks]]
type = "command"
command = "{command}"

[[hooks.PreToolUse]]
matcher = "Bash|apply_patch"
[[hooks.PreToolUse.hooks]]
type = "command"
command = "{command}"

[[hooks.Stop]]
matcher = ""
[[hooks.Stop.hooks]]
type = "command"
command = "{command}"

[hooks.state."{config.resolve()}:pre_tool_use:0:0"]
enabled = false
''',
        encoding="utf-8",
    )

    readout = client_session_metadata.build_coordination_response_readout(
        _status("observed"),
        claims=[_claim()],
        codex_session_index=index,
        codex_config_path=config,
    )

    capability = readout.operator_host_delivery_capability
    assert capability.scope == "operator_host_recipient_client_config"
    assert capability.delivery_mode == "advisory_only"
    assert capability.mutation_enforcement_available is False
    assert capability.stop_enforcement_available is True
    assert capability.observed_proves_exposure_only is True
    assert capability.observed_proves_stopped is False
    assert capability.observed_proves_acknowledged is False
    assert "mutation enforcement is unavailable" in capability.operator_message


def test_operator_readout_fails_closed_for_digest_drift(tmp_path: Path) -> None:
    """The canonical operator projection shares adapter-aware host classification."""

    index = tmp_path / "session_index.jsonl"
    _write_index(index)
    adapter = tmp_path / "coordination_hook.py"
    adapter.write_text("# drifted adapter\n", encoding="utf-8")
    command = f"python3 {adapter} --agent codex"
    config = tmp_path / "config.toml"
    blocks = "\n".join(
        f'''[[hooks.{event}]]
matcher = "{matcher}"
[[hooks.{event}.hooks]]
type = "command"
command = "{command}"
'''
        for event, matcher in (
            ("SessionStart", "startup|resume|clear|compact"),
            ("UserPromptSubmit", ""),
            ("PostToolUse", "*"),
            ("PreToolUse", "Bash|apply_patch"),
            ("Stop", ""),
        )
    )
    config.write_text(blocks, encoding="utf-8")

    readout = client_session_metadata.build_coordination_response_readout(
        _status("observed"),
        claims=[_claim()],
        codex_session_index=index,
        codex_config_path=config,
    )

    capability = readout.operator_host_delivery_capability
    assert capability.delivery_mode == "unavailable"
    assert capability.mutation_enforcement_available is False
    assert capability.stop_enforcement_available is False
    assert "adapter_digest_mismatch" in capability.issues


def test_v2_operator_readout_has_explicit_v1_migration_boundary(tmp_path: Path) -> None:
    """The operator capability addition advances the strict readout contract version."""

    index = tmp_path / "session_index.jsonl"
    _write_index(index)
    current = client_session_metadata.build_coordination_response_readout(
        _status("observed"), claims=[_claim()], codex_session_index=index
    )
    current_payload = current.model_dump(mode="json")
    legacy_payload = {
        **current_payload,
        "schema_version": "1.0.0",
    }
    legacy_payload.pop("operator_host_delivery_capability")

    assert (
        client_session_metadata.CoordinationResponseReadoutV1.model_validate_json(
            json.dumps(legacy_payload)
        ).schema_version
        == "1.0.0"
    )
    assert (
        client_session_metadata.CoordinationResponseReadoutV2.model_validate_json(
            json.dumps(current_payload)
        ).schema_version
        == "1.1.0"
    )
    with pytest.raises(ValidationError):
        client_session_metadata.CoordinationResponseReadoutV1.model_validate_json(
            json.dumps(current_payload)
        )
    with pytest.raises(ValidationError):
        client_session_metadata.CoordinationResponseReadoutV2.model_validate_json(
            json.dumps(legacy_payload)
        )


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


def test_session_status_keeps_live_but_unindexed_runtime_healthy(tmp_path: Path) -> None:
    """Missing display metadata cannot negate independent live claim evidence."""

    script = Path(__file__).resolve().parents[1] / "scripts" / "session_status.py"
    spec = importlib.util.spec_from_file_location("session_status_script_missing", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    index = tmp_path / "session_index.jsonl"
    index.write_text("", encoding="utf-8")
    payload: dict[str, object] = {
        "session_count": 1,
        "sessions": [
            {
                "session_id": SESSION_ID,
                "health_status": "healthy",
                "recovery_action": "continue",
                "health_issues": [],
            }
        ],
    }

    module.enrich_client_displays(payload, codex_session_index=index)

    session = payload["sessions"][0]  # type: ignore[index]
    assert session["health_status"] == "healthy"
    assert session["recovery_action"] == "continue"
    assert session["health_issues"] == []
    assert session["client_evidence_issues"] == ["metadata_not_indexed"]


def test_session_status_preserves_independent_runtime_absence_classification(tmp_path: Path) -> None:
    """A stale heartbeat remains unhealthy independently of display-index state."""

    script = Path(__file__).resolve().parents[1] / "scripts" / "session_status.py"
    spec = importlib.util.spec_from_file_location("session_status_script_stale", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    index = tmp_path / "session_index.jsonl"
    index.write_text("", encoding="utf-8")
    payload: dict[str, object] = {
        "session_count": 1,
        "sessions": [
            {
                "session_id": SESSION_ID,
                "health_status": "stale",
                "recovery_action": "resume_or_disposition_stale_lane",
                "health_issues": ["stale_session_heartbeat"],
            }
        ],
    }

    module.enrich_client_displays(payload, codex_session_index=index)

    session = payload["sessions"][0]  # type: ignore[index]
    assert session["health_status"] == "stale"
    assert session["recovery_action"] == "resume_or_disposition_stale_lane"
    assert session["health_issues"] == ["stale_session_heartbeat"]
    assert session["client_evidence_issues"] == ["metadata_not_indexed"]
