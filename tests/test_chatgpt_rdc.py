from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

from enforced_planning import chatgpt_rdc, claim_bootstrap, coordination_claims


@pytest.fixture
def isolated_chatgpt_runtime() -> Iterator[None]:
    supported = coordination_claims.SUPPORTED_AGENTS
    session_env_keys = dict(coordination_claims.SESSION_ENV_KEYS)
    strict_native_keys = dict(coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS)
    try:
        yield
    finally:
        coordination_claims.SUPPORTED_AGENTS = supported
        coordination_claims.SESSION_ENV_KEYS.clear()
        coordination_claims.SESSION_ENV_KEYS.update(session_env_keys)
        coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS.clear()
        coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS.update(strict_native_keys)


def _maintenance_payload(tmp_path: Path) -> dict[str, Any]:
    repo = tmp_path / "repo"
    repo.mkdir()
    branch = "chatgpt/test-lane"
    return {
        "schema_version": "1.0",
        "operation": "maintenance_worktree",
        "project": "example",
        "scope": branch,
        "repo_root": str(repo.resolve()),
        "branch": branch,
        "claim_type": "program",
        "write_paths": ["src"],
    }


def test_package_registers_chatgpt_as_portable_claim_owner() -> None:
    assert "chatgpt" in coordination_claims.SUPPORTED_AGENTS
    assert coordination_claims.SESSION_ENV_KEYS["chatgpt"] == ("CHATGPT_SESSION_ID",)
    assert coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS["chatgpt"] == "CHATGPT_SESSION_ID"


def test_chatgpt_request_retains_canonical_bootstrap_validation(tmp_path: Path) -> None:
    payload = _maintenance_payload(tmp_path)

    request = chatgpt_rdc.parse_request_json(json.dumps(payload))

    assert isinstance(request, claim_bootstrap.MaintenanceWorktreeRequest)
    assert request.agent == "chatgpt"
    assert request.write_paths == ["src"]

    payload["unexpected"] = True
    with pytest.raises(chatgpt_rdc.ChatGPTRDCError):
        chatgpt_rdc.parse_request_json(json.dumps(payload))


def test_chatgpt_request_rejects_borrowed_agent_and_unsafe_operation(tmp_path: Path) -> None:
    payload = _maintenance_payload(tmp_path)
    payload["agent"] = "codex"
    with pytest.raises(chatgpt_rdc.ChatGPTRDCError, match="cannot borrow"):
        chatgpt_rdc.parse_request_json(json.dumps(payload))

    payload = {
        "schema_version": "1.0",
        "operation": "local_repository_integrate",
        "agent": "chatgpt",
        "project": "example",
        "scope": "chatgpt/test-lane",
    }
    with pytest.raises(chatgpt_rdc.ChatGPTRDCError, match="outside the ChatGPT/RDC safety surface"):
        chatgpt_rdc.parse_request_json(json.dumps(payload))


def test_chatgpt_request_rejects_duplicate_json_keys() -> None:
    raw = '{"operation":"heartbeat","operation":"progress","project":"example","scope":"lane"}'

    with pytest.raises(chatgpt_rdc.ChatGPTRDCError, match="duplicate object key 'operation'"):
        chatgpt_rdc.parse_request_json(raw)


def test_runtime_registration_derives_exact_chatgpt_session(
    monkeypatch: pytest.MonkeyPatch,
    isolated_chatgpt_runtime: None,
) -> None:
    monkeypatch.setenv(chatgpt_rdc.CHATGPT_SESSION_ENV, "rdc-session-1234")

    session_id = chatgpt_rdc.enable_chatgpt_runtime()

    assert session_id == "chatgpt:rdc-session-1234"
    assert "chatgpt" in coordination_claims.SUPPORTED_AGENTS
    assert coordination_claims.resolve_session_id("chatgpt") == session_id
    assert claim_bootstrap._native_agent(cast(Any, "chatgpt")) == ("chatgpt", session_id)


def test_runtime_registration_requires_valid_explicit_lane_marker(
    monkeypatch: pytest.MonkeyPatch,
    isolated_chatgpt_runtime: None,
) -> None:
    monkeypatch.delenv(chatgpt_rdc.CHATGPT_SESSION_ENV, raising=False)
    with pytest.raises(chatgpt_rdc.ChatGPTRDCError, match="is required"):
        chatgpt_rdc.enable_chatgpt_runtime()

    monkeypatch.setenv(chatgpt_rdc.CHATGPT_SESSION_ENV, "bad:marker")
    with pytest.raises(chatgpt_rdc.ChatGPTRDCError, match="must be 8-128 characters"):
        chatgpt_rdc.enable_chatgpt_runtime()


def test_execute_request_uses_canonical_transaction_and_adds_transport_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_chatgpt_runtime: None,
) -> None:
    monkeypatch.setenv(chatgpt_rdc.CHATGPT_SESSION_ENV, "rdc-session-5678")
    request = chatgpt_rdc.parse_request_json(json.dumps(_maintenance_payload(tmp_path)))
    observed: list[claim_bootstrap.ClaimBootstrapRequest] = []

    def execute_canonical(candidate: claim_bootstrap.ClaimBootstrapRequest) -> dict[str, Any]:
        observed.append(candidate)
        return {
            "ok": True,
            "schema_version": "1.0",
            "operation": candidate.operation,
            "agent": candidate.agent,
            "session_id": "chatgpt:rdc-session-5678",
            "project": candidate.project,
            "scope": candidate.scope,
            "result": {"action": "test"},
        }

    monkeypatch.setattr(claim_bootstrap, "execute_request", execute_canonical)

    receipt = chatgpt_rdc.execute_request(request)

    assert observed == [request]
    assert receipt["agent"] == "chatgpt"
    assert receipt["session_id"] == "chatgpt:rdc-session-5678"
    assert receipt["transport"] == "remote-desktop-commander"
