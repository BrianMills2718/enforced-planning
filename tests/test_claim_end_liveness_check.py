"""Regression coverage for policy claim-end-requires-liveness-check.

project-meta/policy/proposals/2026-08-20-claim-end-requires-liveness-check.yaml
measured a coordination claim flipping to ``session_ended`` while its owning
session was still heartbeating -- the pre-fix code silently retired it.
``end_session_claims`` must now refuse (and durably record the refusal)
instead.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import coordination_claims, coordination_messages, session_lifecycle


def _write_claim(
    claims_dir: Path,
    *,
    agent: str = "claude-code",
    project: str = "llm_client",
    scope: str,
    session_id: str,
    heartbeat_at: str | None,
    status: str = "active",
) -> Path:
    """Write one minimal live-claim fixture directly, bypassing create_claim's timestamps."""

    claims_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "agent": agent,
        "projects": [project],
        "scope": scope,
        "intent": "regression fixture for claim-end-requires-liveness-check",
        "claim_type": "program",
        "status": status,
        "session_id": session_id,
        "heartbeat_at": heartbeat_at,
        "claimed_at": "2026-08-20T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    path = claims_dir / f"{agent}_{project}_{scope}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# The three real cases measured in the accepted proposal: a claim's
# heartbeat_at strictly newer than the sweep that ended it -- direct evidence
# the owning session was alive when the sweep ran.
REAL_HEARTBEAT_AFTER_END_FIXTURES = [
    pytest.param(
        "llm_client",
        "claim-verification-severity",
        "2026-08-20T16:52:08+00:00",
        "2026-08-20T17:18:10+00:00",
        id="llm_client:claim-verification-severity",
    ),
    pytest.param(
        "llm_client",
        "prompt-quality-rubric",
        "2026-08-20T16:52:08+00:00",
        "2026-08-20T17:01:12+00:00",
        id="llm_client:prompt-quality-rubric",
    ),
    pytest.param(
        "process_tracing",
        "adopt-corpus-skip-guards",
        "2026-08-20T18:49:25+00:00",
        "2026-08-20T18:59:14+00:00",
        id="process_tracing:adopt-corpus-skip-guards",
    ),
]


@pytest.mark.parametrize(
    ("project", "scope", "sweep_started_at", "heartbeat_at"),
    REAL_HEARTBEAT_AFTER_END_FIXTURES,
)
def test_end_refuses_claim_with_heartbeat_newer_than_sweep_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
    scope: str,
    sweep_started_at: str,
    heartbeat_at: str,
) -> None:
    """A claim heartbeating after the sweep began must survive, not be retired."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_id = f"claude-code:{scope}-session"
    claim_path = _write_claim(
        claims_dir,
        project=project,
        scope=scope,
        session_id=session_id,
        heartbeat_at=heartbeat_at,
    )

    result = coordination_claims.end_session_claims(
        agent="claude-code",
        session_id=session_id,
        reason="other",
        claims_dir=claims_dir,
        sweep_started_at=sweep_started_at,
    )

    assert result.ended_count == 0
    assert result.refused == [
        {
            "project": project,
            "scope": scope,
            "heartbeat_at": heartbeat_at,
            "sweep_started_at": sweep_started_at,
        }
    ]
    on_disk = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert on_disk["status"] == "active"
    assert "session_ended_at" not in on_disk

    refusal_log = claims_dir.parent / coordination_claims.CLAIM_LIVENESS_REFUSAL_LOG_NAME
    entries = [json.loads(line) for line in refusal_log.read_text(encoding="utf-8").splitlines()]
    assert any(entry["scope"] == scope and entry["heartbeat_at"] == heartbeat_at for entry in entries)


def test_end_still_retires_a_genuinely_stale_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The liveness check must not block ending a claim that is actually dead."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_id = "claude-code:genuinely-dead"
    old_heartbeat = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    _write_claim(claims_dir, scope="dead-lane", session_id=session_id, heartbeat_at=old_heartbeat)

    result = coordination_claims.end_session_claims(
        agent="claude-code",
        session_id=session_id,
        reason="logout",
        claims_dir=claims_dir,
    )

    assert result.ended_count == 1
    assert result.refused == []
    assert result.ended_scopes == ["llm_client:dead-lane"]


def test_end_rejects_the_shared_sse_port_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defect A: an end must never resolve through the multi-session SSE-port alias."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    # Two different real sessions both stamped the same shared alias onto
    # their claims (as heartbeat/release still may, by design).
    _write_claim(claims_dir, scope="lane-a", session_id="claude-code:sse:41292", heartbeat_at=None)
    _write_claim(claims_dir, scope="lane-b", session_id="claude-code:sse:41292", heartbeat_at=None)

    with pytest.raises(ValueError, match="shared alias"):
        coordination_claims.end_session_claims(
            agent="claude-code",
            session_id="claude-code:sse:41292",
            reason="logout",
            claims_dir=claims_dir,
        )

    # Neither lane was touched by the rejected call.
    for scope in ("lane-a", "lane-b"):
        payload = yaml.safe_load((claims_dir / f"claude-code_llm_client_{scope}.yaml").read_text())
        assert payload["status"] == "active"


def test_end_falls_through_to_no_identity_when_only_the_alias_env_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect A: env-derived resolution must not silently fall back to the alias for an end."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "41292")

    with pytest.raises(ValueError, match="Unable to resolve a session ID"):
        coordination_claims.end_session_claims(agent="claude-code", claims_dir=claims_dir)


def test_forced_end_requires_a_specific_reason_not_other(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Item 2: a non-self-initiated end needs an actor and a real reason."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    with pytest.raises(ValueError, match="specific session_end_reason"):
        coordination_claims.end_session_claims(
            agent="claude-code",
            session_id="claude-code:some-session",
            reason="other",
            claims_dir=claims_dir,
            actor="sweep:prune-tool",
        )


def test_legitimate_forced_end_notifies_the_ended_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 3: a legitimate forced end leaves a mailbox message for the owning session."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_id = "claude-code:forced-end-target"
    old_heartbeat = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
    _write_claim(claims_dir, scope="forced-lane", session_id=session_id, heartbeat_at=old_heartbeat)

    payload = session_lifecycle.end_runtime_session(
        agent="claude-code",
        session_id=session_id,
        reason="administrative sweep of an abandoned lane",
        claims_dir=claims_dir,
        actor="sweep:prune-tool",
    )

    assert payload["ended_count"] == 1
    assert payload.get("notify_failures", []) == []

    notice = coordination_messages.poll_session_inbox(
        agent="claude-code",
        project="llm_client",
        session_id=session_id,
        claims_dir=claims_dir,
        require_live_claim=False,
    )
    assert notice.active_count == 1
    assert "forced-lane" in notice.summary


def test_ambiguous_sessionend_signal_defers_a_freshly_heartbeating_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect B: SessionEnd alone is not proof of death for a recently-alive claim."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_id = "claude-code:wsl-blip"
    fresh_heartbeat = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    _write_claim(claims_dir, scope="still-working", session_id=session_id, heartbeat_at=fresh_heartbeat)

    payload = session_lifecycle.end_runtime_session(
        agent="claude-code",
        session_id=session_id,
        reason="other",
        claims_dir=claims_dir,
        ambiguous_signal=True,
    )

    assert payload["ended_count"] == 0
    assert len(payload["refused"]) == 1

    claim_path = claims_dir / "claude-code_llm_client_still-working.yaml"
    assert yaml.safe_load(claim_path.read_text())["status"] == "active"


def test_ambiguous_sessionend_signal_still_ends_a_stale_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect B: a claim already stale by the existing heartbeat-staleness rule still ends."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_id = "claude-code:actually-dead"
    stale_heartbeat = (datetime.now(UTC) - timedelta(minutes=200)).isoformat()
    _write_claim(claims_dir, scope="really-gone", session_id=session_id, heartbeat_at=stale_heartbeat)

    payload = session_lifecycle.end_runtime_session(
        agent="claude-code",
        session_id=session_id,
        reason="other",
        claims_dir=claims_dir,
        ambiguous_signal=True,
    )

    assert payload["ended_count"] == 1
    assert payload["refused"] == []
