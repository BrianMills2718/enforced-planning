"""Both-sign checks for the disposable Plan 67 app-server instrument."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "scripts"
    / "worktree-coordination"
    / "codex_app_server_steering_spike.py"
)
SPEC = importlib.util.spec_from_file_location("codex_app_server_steering_spike", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_contains_marker_only_accepts_incoming_agent_message_events() -> None:
    """Outgoing prompts and unrelated events must not create false observation."""

    marker = "ACTIVE_STEER_abc"
    assert MODULE.contains_marker(
        {"method": "item/agentMessage/delta", "params": {"delta": marker}}, marker
    )
    assert MODULE.contains_marker(
        {"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": marker}}},
        marker,
    )
    assert not MODULE.contains_marker(
        {"method": "turn/started", "params": {"copiedPrompt": marker}}, marker
    )
    assert not MODULE.contains_marker(
        {"method": "item/agentMessage/delta", "params": {"delta": "different"}}, marker
    )


def test_redact_removes_nested_credential_shaped_fields() -> None:
    """Retained protocol evidence must not persist credentials from future fields."""

    payload = {
        "authorization": "Bearer secret",
        "nested": {"apiKey": "secret", "safe": "value"},
        "items": [{"access_token": "secret", "message": "ok"}],
    }
    assert MODULE.redact(payload) == {
        "authorization": "<redacted>",
        "nested": {"apiKey": "<redacted>", "safe": "value"},
        "items": [{"access_token": "<redacted>", "message": "ok"}],
    }


def test_schema_digest_binds_paths_and_bytes(tmp_path: Path) -> None:
    """Schema evidence must change when either a path or its content changes."""

    first = tmp_path / "first.json"
    first.write_text('{"type":"object"}\n', encoding="utf-8")
    digest_one = MODULE.schema_digest(tmp_path)
    first.write_text('{"type":"string"}\n', encoding="utf-8")
    digest_two = MODULE.schema_digest(tmp_path)
    assert digest_one != digest_two


def test_wait_for_turn_started_ignores_thread_start() -> None:
    """The protocol readiness boundary is the turn event, not thread creation."""

    turn_id = "turn-123"
    messages = iter(
        [
            {"method": "thread/started", "params": {"thread": {"id": "thread-1"}}},
            {"method": "turn/started", "params": {"turn": {"id": turn_id}}},
        ]
    )
    client = object.__new__(MODULE.ProtocolClient)
    client._timeout_seconds = 1.0
    client.receive = lambda _deadline: next(messages)
    observed: list[dict[str, object]] = []
    client.wait_for_turn_started(turn_id, observed)
    assert [message["method"] for message in observed] == ["thread/started", "turn/started"]
