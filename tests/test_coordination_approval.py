from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from enforced_planning.coordination_approval import (
    ApprovalLeaseMutationReceiptV1,
    ApprovalLeaseStore,
    ApprovalTargetV1,
    CoordinationApprovalError,
    LiveApprovalFactsV1,
    PublishedApprovalV1,
    build_publication_intent,
    build_publication_receipt,
    lease_sha256,
    validate_candidate_receipt_bytes,
)

NOW = datetime(2026, 9, 1, 20, 0, tzinfo=UTC)
OWNER = "codex:owner-session"
SUCCESSOR = "claude-code:successor-session"
HEAD = "a" * 40
BASE = "e" * 40
CANDIDATE = (
    json.dumps(
        {
            "schema_version": "1.0",
            "record_type": "coordination_approval_candidate",
            "review_id": "pr-321-independent-review",
            "repository": "BrianMills2718/enforced-planning",
            "pr_number": 321,
            "base_sha": BASE,
            "head_sha": HEAD,
            "rubric_revision": "fundamentals-v1",
            "reviewer_sessions": ["codex:independent-reviewer"],
            "verdict": "signed_off",
            "authority_state": "evidence_receipt",
            "source_signoff_sha256": "f" * 64,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    + b"\n"
)


def target(*, mode: str = "compatibility_status", app_id: int | None = None) -> ApprovalTargetV1:
    return ApprovalTargetV1(
        repository="BrianMills2718/enforced-planning",
        pr_number=321,
        pr_url="https://github.com/BrianMills2718/enforced-planning/pull/321",
        base_branch="main",
        review_base_sha=BASE,
        head_sha=HEAD,
        candidate_receipt_sha256=hashlib.sha256(CANDIDATE).hexdigest(),
        approval_mode=mode,
        protected_app_id=app_id,
    )


def candidate_receipt():
    return validate_candidate_receipt_bytes(target(), CANDIDATE)


def facts(
    *, context: str = "coordination-approval", head: str = HEAD,
    app_id: int | None = None, observed_at: datetime = NOW,
    strict: bool = True, enforce_admins: bool = True,
) -> LiveApprovalFactsV1:
    return LiveApprovalFactsV1(
        observed_at=observed_at,
        repository="BrianMills2718/enforced-planning",
        pr_number=321,
        pr_url="https://github.com/BrianMills2718/enforced-planning/pull/321",
        base_branch="main",
        head_sha=head,
        pr_state="OPEN",
        protection_context=context,
        protected_app_id=app_id,
        strict_required_checks=strict,
        enforce_admins=enforce_admins,
    )


def acquire(store: ApprovalLeaseStore, *, item: ApprovalTargetV1 | None = None):
    lease, receipt, path = store.acquire(
        target=item or target(), owner_session_id=OWNER,
        duration=timedelta(minutes=10), now=NOW,
        evidence_ref="review receipt verified",
    )
    assert path.is_file()
    assert receipt.successor_lease_sha256 == lease_sha256(lease)
    return lease


def test_acquire_is_exclusive_and_digest_bound(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    lease = acquire(store)
    with pytest.raises(CoordinationApprovalError, match="already exists"):
        acquire(store)
    assert store.current(target()) == lease


def test_mutation_receipt_rejects_tampering(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    _lease, receipt, _path = store.acquire(
        target=target(), owner_session_id=OWNER,
        duration=timedelta(minutes=10), now=NOW,
        evidence_ref="review receipt verified",
    )
    payload = receipt.model_dump()
    payload["evidence_ref"] = "tampered"
    with pytest.raises(ValueError, match="digest"):
        ApprovalLeaseMutationReceiptV1.model_validate(payload)


def test_exact_owner_heartbeat_and_explicit_transfer_preserve_target(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    initial = acquire(store)
    renewed, renewal, _ = store.heartbeat(
        target=target(), owner_session_id=OWNER,
        expected_lease_sha256=lease_sha256(initial),
        duration=timedelta(minutes=10), now=NOW + timedelta(minutes=1),
    )
    assert renewed.owner_session_id == OWNER
    assert renewed.revision == 2
    assert renewal.prior_lease_sha256 == lease_sha256(initial)
    transferred, transfer, _ = store.transfer(
        target=target(), owner_session_id=OWNER,
        successor_session_id=SUCCESSOR,
        expected_lease_sha256=lease_sha256(renewed),
        duration=timedelta(minutes=10), now=NOW + timedelta(minutes=2),
        evidence_ref="exact-session mailbox handoff msg_123",
    )
    assert transferred.owner_session_id == SUCCESSOR
    assert transferred.target == initial.target
    assert transfer.operation == "transfer"


def test_wrong_session_and_stale_cache_cannot_mutate(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    initial = acquire(store)
    with pytest.raises(CoordinationApprovalError, match="exact owner"):
        store.heartbeat(
            target=target(), owner_session_id=SUCCESSOR,
            expected_lease_sha256=lease_sha256(initial),
            duration=timedelta(minutes=10), now=NOW + timedelta(minutes=1),
        )
    renewed, _, _ = store.heartbeat(
        target=target(), owner_session_id=OWNER,
        expected_lease_sha256=lease_sha256(initial),
        duration=timedelta(minutes=10), now=NOW + timedelta(minutes=1),
    )
    with pytest.raises(CoordinationApprovalError, match="compare-and-swap"):
        store.transfer(
            target=target(), owner_session_id=OWNER,
            successor_session_id=SUCCESSOR,
            expected_lease_sha256=lease_sha256(initial),
            duration=timedelta(minutes=10), now=NOW + timedelta(minutes=2),
            evidence_ref="stale cached handoff",
        )
    assert store.current(target()) == renewed


def test_takeover_refuses_healthy_owner_and_succeeds_only_after_expiry(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    initial = acquire(store)
    with pytest.raises(CoordinationApprovalError, match="healthy"):
        store.takeover(
            target=target(), successor_session_id=SUCCESSOR,
            expected_lease_sha256=lease_sha256(initial),
            duration=timedelta(minutes=10), now=NOW + timedelta(minutes=9),
            evidence_ref="mailbox prose is not sufficient",
        )
    successor, receipt, _ = store.takeover(
        target=target(), successor_session_id=SUCCESSOR,
        expected_lease_sha256=lease_sha256(initial),
        duration=timedelta(minutes=10), now=NOW + timedelta(minutes=10),
        evidence_ref="expired lease plus exact predecessor digest",
    )
    assert successor.owner_session_id == SUCCESSOR
    assert receipt.operation == "takeover"
    assert receipt.prior_lease_sha256 == lease_sha256(initial)


def test_expired_owner_cannot_revive_or_transfer(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    initial = acquire(store)
    for operation in ("heartbeat", "transfer"):
        with pytest.raises(CoordinationApprovalError, match="expired"):
            if operation == "heartbeat":
                store.heartbeat(
                    target=target(), owner_session_id=OWNER,
                    expected_lease_sha256=lease_sha256(initial),
                    duration=timedelta(minutes=10), now=NOW + timedelta(minutes=10),
                )
            else:
                store.transfer(
                    target=target(), owner_session_id=OWNER,
                    successor_session_id=SUCCESSOR,
                    expected_lease_sha256=lease_sha256(initial),
                    duration=timedelta(minutes=10), now=NOW + timedelta(minutes=10),
                    evidence_ref="too late",
                )


def test_release_requires_exact_owner_and_preserves_terminal_receipt(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    initial = acquire(store)
    with pytest.raises(CoordinationApprovalError, match="exact owner"):
        store.release(
            target=target(), owner_session_id=SUCCESSOR,
            expected_lease_sha256=lease_sha256(initial),
            evidence_ref="wrong owner",
            now=NOW + timedelta(minutes=1),
        )
    receipt, path = store.release(
        target=target(), owner_session_id=OWNER,
        expected_lease_sha256=lease_sha256(initial),
        evidence_ref="publication consumed by merge gate",
        now=NOW + timedelta(minutes=1),
    )
    assert receipt.operation == "release"
    assert receipt.successor_lease is None
    assert path.is_file()
    assert store.current(target()) is None


def test_receipt_failure_rolls_back_acquire_replace_and_release(tmp_path, monkeypatch) -> None:
    store = ApprovalLeaseStore(tmp_path)
    original_persist = store._persist_receipt

    def fail_receipt(_receipt):
        raise OSError("injected receipt failure")

    monkeypatch.setattr(store, "_persist_receipt", fail_receipt)
    with pytest.raises(OSError, match="injected"):
        store.acquire(
            target=target(), owner_session_id=OWNER,
            duration=timedelta(minutes=10), now=NOW,
            evidence_ref="failure injection",
        )
    assert store.current(target()) is None

    monkeypatch.setattr(store, "_persist_receipt", original_persist)
    initial = acquire(store)
    monkeypatch.setattr(store, "_persist_receipt", fail_receipt)
    with pytest.raises(OSError, match="injected"):
        store.heartbeat(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(initial),
            duration=timedelta(minutes=10), now=NOW + timedelta(minutes=1),
        )
    assert store.current(target()) == initial
    with pytest.raises(OSError, match="injected"):
        store.release(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(initial),
            evidence_ref="failure injection",
            now=NOW + timedelta(minutes=2),
        )
    assert store.current(target()) == initial


def test_process_death_after_state_mutation_recovers_receipt_and_release(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    initial = acquire(store)
    initial_receipts = len(list((tmp_path / "receipts").glob("*.json")))

    pid = os.fork()
    if pid == 0:
        child = ApprovalLeaseStore(tmp_path)
        child._persist_receipt = lambda _receipt: os._exit(17)  # type: ignore[method-assign]
        child.heartbeat(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(initial),
            duration=timedelta(minutes=10), now=NOW + timedelta(minutes=1),
        )
        os._exit(99)
    _pid, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 17
    recovered = store.current(target())
    assert recovered is not None and recovered.revision == 2
    assert len(list((tmp_path / "receipts").glob("*.json"))) == initial_receipts + 1
    assert list((tmp_path / "transactions").glob("*.json")) == []

    pid = os.fork()
    if pid == 0:
        child = ApprovalLeaseStore(tmp_path)
        child._persist_receipt = lambda _receipt: os._exit(18)  # type: ignore[method-assign]
        child.release(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(recovered),
            evidence_ref="process-death release",
            now=NOW + timedelta(minutes=2),
        )
        os._exit(99)
    _pid, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 18
    assert store.current(target()) is None
    assert len(list((tmp_path / "receipts").glob("*.json"))) == initial_receipts + 2
    assert list((tmp_path / "transactions").glob("*.json")) == []


def test_publishability_rejects_frozen_context_stale_facts_and_head_drift(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    lease = acquire(store)
    with pytest.raises(CoordinationApprovalError, match="receipt bytes"):
        store.assert_publishable(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(lease),
            live_facts=facts(), candidate_receipt_bytes=b"stale cached receipt", now=NOW,
        )
    with pytest.raises(CoordinationApprovalError, match="frozen"):
        store.assert_publishable(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(lease),
            live_facts=facts(context="coordination-approval-frozen"),
            candidate_receipt_bytes=CANDIDATE, now=NOW,
        )
    with pytest.raises(CoordinationApprovalError, match="strict checks"):
        store.assert_publishable(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(lease),
            live_facts=facts(strict=False), candidate_receipt_bytes=CANDIDATE, now=NOW,
        )
    with pytest.raises(CoordinationApprovalError, match="stale"):
        store.assert_publishable(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(lease),
            live_facts=facts(observed_at=NOW - timedelta(minutes=3)),
            candidate_receipt_bytes=CANDIDATE, now=NOW,
        )
    with pytest.raises(CoordinationApprovalError, match="identity"):
        store.assert_publishable(
            target=target(), owner_session_id=OWNER,
            expected_lease_sha256=lease_sha256(lease),
            live_facts=facts(head="c" * 40), candidate_receipt_bytes=CANDIDATE, now=NOW,
        )


def test_compatibility_receipt_requires_owner_creator_and_exact_pr_url(tmp_path) -> None:
    store = ApprovalLeaseStore(tmp_path)
    lease = acquire(store)
    observed = facts()
    lease, parsed_candidate = store.assert_publishable(
        target=target(), owner_session_id=OWNER,
        expected_lease_sha256=lease_sha256(lease), live_facts=observed, now=NOW,
        candidate_receipt_bytes=CANDIDATE,
    )
    approval = PublishedApprovalV1(
        kind="commit_status", context="coordination-approval", head_sha=HEAD,
        state="SUCCESS", creator_login="BrianMills2718",
        target_url=target().pr_url, provider_record_id=123,
        publication_intent_id="0" * 64, provider_recorded_at=NOW,
    )
    intent = build_publication_intent(
        lease=lease, publisher_session_id=OWNER,
        candidate_receipt=parsed_candidate, live_facts_before=observed,
        prepared_at=NOW,
    )
    approval = approval.model_copy(update={"publication_intent_id": intent.intent_id})
    receipt = build_publication_receipt(
        publication_intent=intent, published_approval=approval,
        live_facts_after=observed,
    )
    assert receipt.lease_sha256 == lease_sha256(lease)
    assert len(receipt.receipt_sha256) == 64

    with pytest.raises(CoordinationApprovalError, match="publisher"):
        build_publication_receipt(
            publication_intent=intent.model_copy(
                update={"publisher_session_id": SUCCESSOR}
            ),
            published_approval=approval,
            live_facts_after=observed,
        )

    for bad in (
        approval.model_copy(update={"creator_login": "worker"}),
        approval.model_copy(update={"target_url": None}),
    ):
        with pytest.raises(CoordinationApprovalError):
            build_publication_receipt(
                publication_intent=intent, published_approval=bad,
                live_facts_after=observed,
            )


def test_app_receipt_rejects_wrong_app_and_old_head(tmp_path) -> None:
    item = target(mode="github_app", app_id=4242)
    store = ApprovalLeaseStore(tmp_path)
    lease = acquire(store, item=item)
    observed = facts(app_id=4242)
    good = PublishedApprovalV1(
        kind="check_run", context="coordination-approval", head_sha=HEAD,
        state="SUCCESS", app_id=4242, provider_record_id=456,
        publication_intent_id="0" * 64, provider_recorded_at=NOW,
    )
    app_candidate = candidate_receipt()
    intent = build_publication_intent(
        lease=lease, publisher_session_id=OWNER,
        candidate_receipt=app_candidate, live_facts_before=observed,
        prepared_at=NOW,
    )
    good = good.model_copy(update={"publication_intent_id": intent.intent_id})
    receipt = build_publication_receipt(
        publication_intent=intent, published_approval=good,
        live_facts_after=observed,
    )
    assert receipt.published_approval.app_id == 4242
    with pytest.raises(CoordinationApprovalError, match="wrong GitHub App"):
        build_publication_receipt(
            publication_intent=intent,
            published_approval=good.model_copy(update={"app_id": 99}),
            live_facts_after=observed,
        )
    with pytest.raises(CoordinationApprovalError, match="different head"):
        build_publication_receipt(
            publication_intent=intent,
            published_approval=good.model_copy(update={"head_sha": "d" * 40}),
            live_facts_after=observed,
        )


def test_direct_cli_acquire_status_and_release_journey(tmp_path) -> None:
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(CANDIDATE)
    item = target()
    target_path = tmp_path / "target.json"
    target_path.write_text(item.model_dump_json(), encoding="utf-8")
    state_root = tmp_path / "state"
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "worktree-coordination"
        / "publish_coordination_approval.py"
    )

    def run(*arguments: str) -> dict:
        env = dict(os.environ)
        env["CODEX_THREAD_ID"] = "owner-session"
        env["ENFORCED_PLANNING_APPROVAL_TESTING"] = "1"
        completed = subprocess.run(
            [sys.executable, str(script), "--state-root", str(state_root), *arguments],
            check=True, capture_output=True, text=True, env=env,
        )
        return json.loads(completed.stdout)

    acquired = run(
        "acquire", "--target", str(target_path), "--agent", "codex",
        "--duration-seconds", "600", "--evidence-ref", "direct CLI test",
    )
    digest = acquired["lease_sha256"]
    status = run("status", "--target", str(target_path))
    assert status["lease_sha256"] == digest
    released = run(
        "release", "--target", str(target_path), "--agent", "codex",
        "--expected-lease-sha256", digest, "--evidence-ref", "CLI journey complete",
    )
    assert released["mutation_receipt"]["operation"] == "release"
    assert run("status", "--target", str(target_path))["lease"] is None
