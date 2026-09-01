"""Tests for exact primary execution ownership of one mailbox inbox."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from enforced_planning.mailbox_execution_identity import (
    PrimaryExecutionBindingStore,
    PrimaryExecutionBindingV1,
    hook_run_id,
)

NOW = datetime(2026, 9, 1, 19, 0, tzinfo=UTC)


def test_advisory_posttool_cannot_claim_an_unbound_inbox(tmp_path: Path) -> None:
    store = PrimaryExecutionBindingStore(tmp_path)

    decision = store.classify(
        session_id="codex:shared-session",
        run_id="secondary-run",
        event_name="PostToolUse",
        now=NOW,
    )

    assert decision.role == "unbound"
    assert decision.reason == "advisory_event_cannot_bind"
    assert not Path(decision.binding_path).exists()


def test_user_prompt_binds_primary_and_secondary_cannot_take_it(tmp_path: Path) -> None:
    store = PrimaryExecutionBindingStore(tmp_path)
    primary = store.classify(
        session_id="codex:shared-session",
        run_id="root-run",
        event_name="UserPromptSubmit",
        now=NOW,
    )
    secondary = store.classify(
        session_id="codex:shared-session",
        run_id="subagent-run",
        event_name="PreToolUse",
        now=NOW,
    )
    root_next = store.classify(
        session_id="codex:shared-session",
        run_id="root-run",
        event_name="PreToolUse",
        now=NOW,
    )

    assert primary.role == "primary"
    assert secondary.role == "secondary"
    assert secondary.generation == 1
    assert root_next.role == "primary"
    binding = PrimaryExecutionBindingV1.model_validate_json(
        Path(primary.binding_path).read_text(encoding="utf-8")
    )
    assert binding.generation == 1
    assert "root-run" not in Path(primary.binding_path).read_text(encoding="utf-8")
    assert "shared-session" not in Path(primary.binding_path).read_text(encoding="utf-8")


def test_session_start_epoch_rejects_stale_run_until_new_prompt_binds(tmp_path: Path) -> None:
    store = PrimaryExecutionBindingStore(tmp_path)
    store.classify(
        session_id="codex:resumed-session",
        run_id="old-run",
        event_name="UserPromptSubmit",
        now=NOW,
    )

    reset = store.classify(
        session_id="codex:resumed-session",
        run_id=None,
        event_name="SessionStart",
        now=NOW,
    )
    stale = store.classify(
        session_id="codex:resumed-session",
        run_id="old-run",
        event_name="PostToolUse",
        now=NOW,
    )
    rotated = store.classify(
        session_id="codex:resumed-session",
        run_id="new-run",
        event_name="UserPromptSubmit",
        now=NOW,
    )

    assert reset.role == "unbound"
    assert reset.reason == "session_start_awaiting_primary_run"
    assert stale.role == "unbound"
    assert stale.reason == "awaiting_primary_run"
    assert rotated.role == "primary"
    assert rotated.reason == "authoritative_event_bound"
    assert rotated.generation == 2


def test_different_run_prompt_cannot_rotate_active_primary(tmp_path: Path) -> None:
    store = PrimaryExecutionBindingStore(tmp_path)
    store.classify(
        session_id="codex:shared-session",
        run_id="root-run",
        event_name="UserPromptSubmit",
        now=NOW,
    )

    secondary_prompt = store.classify(
        session_id="codex:shared-session",
        run_id="subagent-run",
        event_name="UserPromptSubmit",
        now=NOW,
    )

    assert secondary_prompt.role == "secondary"
    assert secondary_prompt.reason == "different_execution_run"


def test_pretool_bootstraps_legacy_session_but_posttool_does_not(tmp_path: Path) -> None:
    store = PrimaryExecutionBindingStore(tmp_path)

    advisory = store.classify(
        session_id="codex:legacy-session",
        run_id="run-a",
        event_name="PostToolUse",
        now=NOW,
    )
    boundary = store.classify(
        session_id="codex:legacy-session",
        run_id="run-a",
        event_name="PreToolUse",
        now=NOW,
    )

    assert advisory.role == "unbound"
    assert boundary.role == "primary"
    assert boundary.reason == "authoritative_event_bound"


def test_missing_run_identity_uses_unpersisted_legacy_compatibility(tmp_path: Path) -> None:
    decision = PrimaryExecutionBindingStore(tmp_path).classify(
        session_id="codex:shared-session",
        run_id=None,
        event_name="PreToolUse",
        now=NOW,
    )

    assert decision.role == "primary"
    assert decision.reason == "legacy_missing_run_identity"
    assert not Path(decision.binding_path).exists()


def test_hook_run_id_accepts_only_native_run_fields() -> None:
    assert hook_run_id({"hook_run_id": "run-one", "session_id": "session"}) == "run-one"
    assert hook_run_id({"hookRunId": "run-two", "session_id": "session"}) == "run-two"
    assert hook_run_id({"session_id": "session", "event_id": "event"}) is None
