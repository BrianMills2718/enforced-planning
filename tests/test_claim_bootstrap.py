from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from enforced_planning import claim_bootstrap


def _start_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": "session_start_or_update",
        "agent": "codex",
        "project": "demo",
        "scope": "self-owned-scope",
        "intent": "create exact self ownership",
        "claim_type": "write",
        "repo_root": "/tmp/demo",
        "worktree_path": "/tmp/demo/worktrees/self-owned-scope",
        "branch": "self-owned-scope",
        "session_name": "create-exact-self-ownership",
        "broader_goal": "Create exact self ownership",
        "plan_ref": "UNPLANNED",
        "write_paths": ["src/owned.py"],
        "read_paths": [],
        "current_phase": "bootstrap",
        "next_action": "begin bounded work",
    }
    payload.update(updates)
    return payload


def test_unclaimed_native_session_can_start_its_own_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "trackers"
    repo_root = tmp_path / "repo"
    worktree = repo_root / "worktrees" / "self-owned-scope"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(claim_bootstrap.coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(claim_bootstrap, "SESSION_TRACKERS_DIR", trackers_dir)
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims.claim_mutation_receipts,
        "append_receipt",
        lambda _receipt: None,
    )
    monkeypatch.setattr(
        claim_bootstrap.session_lifecycle,
        "_poll_mailbox",
        lambda **_kwargs: {"polled": True, "active_count": 0},
    )
    request = claim_bootstrap.parse_request_json(
        json.dumps(
            _start_payload(
                repo_root=str(repo_root),
                worktree_path=str(worktree),
            )
        )
    )

    receipt = claim_bootstrap.execute_request(request)

    assert receipt["ok"] is True
    assert receipt["session_id"] == "codex:native-123"
    claims = claim_bootstrap.coordination_claims.check_claims("demo")
    assert [(claim.scope, claim.session_id) for claim in claims] == [("self-owned-scope", "codex:native-123")]
    assert claims[0].write_paths == ["src/owned.py"]
    assert list(worktree.iterdir()) == []
    assert len(list(trackers_dir.rglob("*.yaml"))) == 1


def test_request_for_wrong_agent_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    request = claim_bootstrap.parse_request_json(json.dumps(_start_payload(agent="claude-code")))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="native claude-code runtime"):
        claim_bootstrap.execute_request(request)


def test_request_cannot_supply_session_id() -> None:
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="session_id"):
        claim_bootstrap.parse_request_json(json.dumps(_start_payload(session_id="codex:borrowed")))


def test_cross_session_scope_update_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")

    def reject_foreign_owner(**_kwargs: object) -> dict[str, object]:
        raise ValueError("Existing live claim slot demo:self-owned-scope is owned by runtime session codex:other")

    monkeypatch.setattr(claim_bootstrap.session_lifecycle, "start_session", reject_foreign_owner)
    request = claim_bootstrap.parse_request_json(json.dumps(_start_payload()))

    with pytest.raises(ValueError, match="owned by runtime session codex:other"):
        claim_bootstrap.execute_request(request)


def test_raw_bash_grammar_accepts_only_canonical_single_command(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "claim_bootstrap.py"
    raw_json = json.dumps(_start_payload(intent="Brian's claim"), separators=(",", ":")).replace("'", "\\u0027")
    command = f"/usr/bin/python3 {script} --request-json '{raw_json}'"

    request = claim_bootstrap.parse_raw_bash_command(command, script_path=script)

    assert request.operation == "session_start_or_update"
    assert request.intent == "Brian's claim"


def test_shell_operators_inside_single_quoted_json_are_inert_data(tmp_path: Path) -> None:
    script = tmp_path / "scripts" / "claim_bootstrap.py"
    raw_json = json.dumps(
        _start_payload(intent="inspect && verify; preserve | literal > text"),
        separators=(",", ":"),
    )
    command = f"/usr/bin/python3 {script} --request-json '{raw_json}'"

    request = claim_bootstrap.parse_raw_bash_command(command, script_path=script)

    assert request.intent == "inspect && verify; preserve | literal > text"


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/claim_bootstrap.py --request-json '{}'",
        "/usr/bin/python3 /tmp/session_start.py --request-json '{}'",
        "/usr/bin/python3 /tmp/claim_bootstrap.py --request-json '{}' && touch /tmp/pwned",
        "/usr/bin/python3 /tmp/claim_bootstrap.py --request-json '{}' > /tmp/result",
        "/usr/bin/python3 /tmp/claim_bootstrap.py --request-json '{}'\nwhoami",
        "python scripts/session_start.py --agent codex --project demo",
    ],
)
def test_raw_bash_grammar_rejects_compound_or_raw_lifecycle_commands(
    command: str,
    tmp_path: Path,
) -> None:
    script = tmp_path / "claim_bootstrap.py"
    with pytest.raises(claim_bootstrap.ClaimBootstrapError):
        claim_bootstrap.parse_raw_bash_command(command, script_path=script)


def test_release_is_guarded_by_derived_exact_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    observed: dict[str, object] = {}

    def fake_release(agent: str, project: str, scope: str, **kwargs: object) -> tuple[bool, str]:
        observed.update(agent=agent, project=project, scope=scope, **kwargs)
        return True, "released"

    monkeypatch.setattr(claim_bootstrap.coordination_claims, "release_claim", fake_release)
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims,
        "check_claims",
        lambda _project: [
            claim_bootstrap.coordination_claims.build_candidate_claim(
                agent="codex",
                project="demo",
                scope="self-owned-scope",
                intent="owned",
                session_id="codex:native-123",
                plan_ref="UNPLANNED",
                claim_type="program",
                repo_root="/tmp/demo",
                worktree_path="/tmp/demo/worktrees/self-owned-scope",
                branch="self-owned-scope",
                session_name="self-owned-scope",
                broader_goal="Self owned scope",
            )
        ],
    )
    request = claim_bootstrap.parse_request_json(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation": "release_self",
                "agent": "codex",
                "project": "demo",
                "scope": "self-owned-scope",
            }
        )
    )

    claim_bootstrap.execute_request(request)

    assert observed["expected_session_id"] == "codex:native-123"


def test_ownerless_existing_slot_cannot_be_bootstrapped_as_self(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "native-123")
    monkeypatch.setattr(
        claim_bootstrap.coordination_claims,
        "check_claims",
        lambda _project: [
            replace(
                claim_bootstrap.coordination_claims.build_candidate_claim(
                    agent="codex",
                    project="demo",
                    scope="self-owned-scope",
                    intent="legacy ownerless claim",
                    session_id="codex:placeholder",
                    plan_ref="UNPLANNED",
                    claim_type="program",
                    repo_root="/tmp/demo",
                    worktree_path="/tmp/demo/worktrees/self-owned-scope",
                    branch="self-owned-scope",
                    session_name="self-owned-scope",
                    broader_goal="Self owned scope",
                ),
                session_id=None,
            )
        ],
    )
    request = claim_bootstrap.parse_request_json(json.dumps(_start_payload()))

    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="<missing>"):
        claim_bootstrap.execute_request(request)


def test_unknown_operation_and_extra_fields_fail_closed() -> None:
    for payload in (
        {"schema_version": "1.0", "operation": "end_other", "project": "demo", "scope": "x"},
        {
            "schema_version": "1.0",
            "operation": "heartbeat",
            "project": "demo",
            "scope": "x",
            "shell": "rm -rf /tmp/demo",
        },
    ):
        with pytest.raises(claim_bootstrap.ClaimBootstrapError):
            claim_bootstrap.parse_request_json(json.dumps(payload))


@pytest.mark.parametrize(
    "raw_json",
    [
        '{"schema_version":"1.0","operation":"heartbeat","project":"a","project":"b","scope":"x"}',
        '{"schema_version":"1.0","operation":"heartbeat","project":"a","scope":"x","nested":{"a":1,"a":2}}',
    ],
)
def test_duplicate_json_object_keys_fail_closed_at_every_depth(raw_json: str) -> None:
    with pytest.raises(claim_bootstrap.ClaimBootstrapError, match="duplicate object key"):
        claim_bootstrap.parse_request_json(raw_json)
