"""Tests for native root/child mailbox execution identity."""

from __future__ import annotations

import pytest

from enforced_planning.mailbox_execution_identity import classify_hook_execution


@pytest.mark.parametrize(
    ("hook_event_name", "hook_run_id"),
    [
        ("SessionStart", None),
        ("UserPromptSubmit", "user_prompt_submit:1:/config.toml"),
        ("PreToolUse", "pre_tool_use:2:/config.toml"),
        ("PostToolUse", "post_tool_use:3:/config.toml"),
        ("Stop", "stop:4:/config.toml"),
    ],
)
def test_authentic_per_callback_receipt_ids_do_not_change_root_identity(
    hook_event_name: str, hook_run_id: str | None
) -> None:
    payload: dict[str, object] = {
        "session_id": "shared-session",
        "hook_event_name": hook_event_name,
    }
    if hook_run_id is not None:
        payload["hook_run_id"] = hook_run_id

    decision = classify_hook_execution(payload, client="codex")

    assert decision.role == "primary"
    assert decision.reason == "root_agent_id_absent"


def test_repeated_root_agent_id_is_primary() -> None:
    decision = classify_hook_execution(
        {
            "session_id": "shared-session",
            "agent_id": "shared-session",
            "hook_run_id": "pre_tool_use:2:/config.toml",
        },
        client="codex",
    )

    assert decision.role == "primary"
    assert decision.reason == "root_agent_id_matches_session"


@pytest.mark.parametrize("client", ["codex", "claude-code"])
def test_distinct_native_child_agent_is_secondary(client: str) -> None:
    decision = classify_hook_execution(
        {
            "session_id": "shared-session",
            "agent_id": "child-agent",
            "hook_run_id": "post_tool_use:3:/config.toml",
        },
        client=client,  # type: ignore[arg-type]
    )

    assert decision.role == "secondary"
    assert decision.reason == "child_agent_id"


def test_invalid_cross_client_agent_identity_fails_closed() -> None:
    decision = classify_hook_execution(
        {
            "session_id": "shared-session",
            "agent_id": "claude-code:child-agent",
        },
        client="codex",
    )

    assert decision.role == "secondary"
    assert decision.reason == "invalid_agent_identity"


def test_secondary_callback_cannot_poison_later_root_classification() -> None:
    secondary = classify_hook_execution(
        {"session_id": "shared-session", "agent_id": "child-agent"},
        client="codex",
    )
    root_next = classify_hook_execution(
        {
            "session_id": "shared-session",
            "hook_run_id": "pre_tool_use:9:/config.toml",
        },
        client="codex",
    )

    assert secondary.role == "secondary"
    assert root_next.role == "primary"
