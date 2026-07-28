"""Deterministic coverage for Plan 108 PW-02B0 claim mutation receipts."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from enforced_planning import claim_mutation_receipts as receipts
from enforced_planning import coordination_claims


QUERY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "query_claim_mutation_fleet.py"


def _load_query_module():
    spec = importlib.util.spec_from_file_location("query_claim_mutation_fleet_test", QUERY_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _claim(
    *,
    scope: str,
    claims_dir: Path,
    session_id: str = "codex:receipt-test",
    plan_ref: str = "Plan #108",
) -> Path:
    ok, message = coordination_claims.create_claim(
        "codex",
        "enforced-planning",
        scope,
        "verify mutation provenance",
        plan_ref=plan_ref,
        branch=scope,
        worktree_path=str(claims_dir.parent / "worktree" / scope),
        session_id=session_id,
        session_name=scope,
    )
    assert ok, message
    return claims_dir / coordination_claims._claim_filename("codex", "enforced-planning", scope)


def _isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    claims_dir = tmp_path / "claims"
    events_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(receipts, "DEFAULT_EVENTS_PATH", events_path)
    return claims_dir, events_path


def _operations(events_path: Path) -> list[str]:
    return [receipt.operation for receipt in receipts.load_receipts(events_path=events_path)]


def test_receipt_contract_rejects_unknown_fields() -> None:
    """The durable contract must fail closed on a ledger schema extension."""

    with pytest.raises(ValidationError, match="extra_forbidden"):
        receipts.ClaimMutationReceiptV1.model_validate(
            {
                "operation": "create",
                "result": "applied_projection_current",
                "writer_source_path": "/tmp/runtime.py",
                "writer_source_sha256": "a" * 64,
                "writer_repo_root": "/tmp",
                "process_id": 1,
                "session_id": "codex:test",
                "target_project": "project",
                "target_scope": "scope",
                "target_claim_path": "/tmp/claim.yaml",
                "registry_digest_before": "b" * 64,
                "registry_digest_after": "c" * 64,
                "projection_digest_after": "d" * 64,
                "projection_current_after": True,
                "error_code": None,
                "unexpected": "not accepted",
            }
        )


def test_each_supported_mutation_emits_one_terminal_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Create, heartbeat, release, session-end, closeout, and prune are all attributable."""

    claims_dir, events_path = _isolated_registry(tmp_path, monkeypatch)

    release_path = _claim(scope="release", claims_dir=claims_dir)
    coordination_claims.heartbeat_claims(
        agent="codex", project="enforced-planning", scope="release", session_id="codex:receipt-test",
        require_exact_session=True,
    )
    released, _ = coordination_claims.release_claim("codex", "enforced-planning", "release")
    assert released

    session_end_path = _claim(scope="session-end", claims_dir=claims_dir)
    coordination_claims.end_session_claims(agent="codex", session_id="codex:receipt-test")

    closeout_path = _claim(scope="closeout", claims_dir=claims_dir, plan_ref="Plan #109")
    completed, scopes = coordination_claims.complete_claims_for_plan(
        project="enforced-planning", plan_ref="Plan #109"
    )
    assert completed == 1 and scopes == ["closeout"]

    expired_path = claims_dir / "codex_enforced-planning_expired.yaml"
    expired_payload = yaml.safe_load(closeout_path.read_text(encoding="utf-8"))
    expired_payload.update(
        {
            "scope": "expired",
            "branch": "expired",
            "status": "active",
            "claimed_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        }
    )
    expired_path.write_text(yaml.safe_dump(expired_payload, sort_keys=False), encoding="utf-8")
    assert coordination_claims.prune_expired() == 1

    records = receipts.load_receipts(events_path=events_path)
    by_path: dict[str, list[receipts.ClaimMutationReceiptV1]] = {}
    for record in records:
        by_path.setdefault(record.target_claim_path or "", []).append(record)

    assert [record.operation for record in by_path[str(release_path)]] == ["create", "heartbeat", "release"]
    assert [record.operation for record in by_path[str(session_end_path)]] == ["create", "session_end"]
    assert [record.operation for record in by_path[str(closeout_path)]] == ["create", "closeout"]
    assert [record.operation for record in by_path[str(expired_path)]] == ["prune"]
    assert set(_operations(events_path)) == {"create", "heartbeat", "release", "session_end", "closeout", "prune"}
    assert all(record.result == "applied_projection_current" for record in records)
    assert all(record.projection_current_after is True for record in records)


def test_ledger_failure_reports_mutation_applied_without_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed ledger append cannot conceal the already-applied YAML mutation."""

    claims_dir, _events_path = _isolated_registry(tmp_path, monkeypatch)
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("not a ledger directory\n", encoding="utf-8")
    monkeypatch.setattr(receipts, "DEFAULT_EVENTS_PATH", blocked_parent / "events.jsonl")
    with pytest.raises(receipts.MutationAuditError, match="mutation_applied_audit_failed") as raised:
        _claim(scope="audit-failure", claims_dir=claims_dir)

    assert raised.value.to_dict()["mutation_applied"] is True
    assert isinstance(raised.value.cause, OSError)
    assert (claims_dir / coordination_claims._claim_filename("codex", "enforced-planning", "audit-failure")).exists()


def test_cli_returns_nonzero_and_discloses_applied_audit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI callers receive a truthful nonzero result after a post-mutation audit failure."""

    claims_dir, _events_path = _isolated_registry(tmp_path, monkeypatch)
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_text("not a ledger directory\n", encoding="utf-8")
    monkeypatch.setattr(receipts, "DEFAULT_EVENTS_PATH", blocked_parent / "events.jsonl")
    result = coordination_claims.main(
        [
            "--claim",
            "--agent",
            "codex",
            "--project",
            "enforced-planning",
            "--scope",
            "cli-audit-failure",
            "--intent",
            "verify truthful CLI failure",
            "--branch",
            "cli-audit-failure",
            "--worktree-path",
            str(tmp_path / "worktree"),
            "--session-id",
            "codex:receipt-test",
            "--session-name",
            "cli-audit-failure",
            "--json",
        ]
    )

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error_code"] == "mutation_applied_audit_failed"
    assert payload["mutation_applied"] is True
    assert payload["projection_current_after"] is True
    assert (claims_dir / coordination_claims._claim_filename("codex", "enforced-planning", "cli-audit-failure")).exists()


def test_fleet_query_marks_missing_receipt_as_unclassified_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No writer provenance may be inferred from a live claim's repository path."""

    claims_dir, events_path = _isolated_registry(tmp_path, monkeypatch)
    legacy = claims_dir / "codex_enforced-planning_legacy.yaml"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "agent": "codex",
                "projects": ["enforced-planning"],
                "scope": "legacy",
                "intent": "legacy writer",
                "claim_type": "program",
                "write_paths": [],
                "read_paths": [],
                "session_id": "codex:legacy",
                "session_name": "legacy",
                "repo_root": str(tmp_path),
                "worktree_path": str(tmp_path / "worktree"),
                "branch": "legacy",
                "status": "active",
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = _load_query_module().build_report(claims_dir=claims_dir, events_path=events_path)

    assert report["live_writer_groups"] == []
    assert report["unclassified_legacy"] == [
        {
            "project": "enforced-planning",
            "scope": "legacy",
            "session_id": "codex:legacy",
            "claim_path": str(legacy.resolve()),
        }
    ]
