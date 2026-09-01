"""Leased custody and exact provenance for protected coordination approval.

Claims own repository writes.  This module owns the narrower authority to
publish one protected approval for one exact pull-request head.  It deliberately
does not mutate branch protection or perform a merge.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import to_jsonable_python

DEFAULT_STATE_ROOT = Path.home() / ".claude" / "coordination" / "approval-producer-v1"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
FULL_SHA_PATTERN = r"^[0-9a-f]{40}$"
SESSION_PATTERN = r"^(codex|claude-code|openclaw):[^\s]+$"
ApprovalMode = Literal["compatibility_status", "github_app"]
LeaseOperation = Literal["acquire", "heartbeat", "transfer", "takeover", "release"]


class CoordinationApprovalError(RuntimeError):
    """Fail-loud approval custody or provenance error."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ApprovalTargetV1(_StrictModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    pr_number: int = Field(gt=0)
    pr_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+/pull/[1-9][0-9]*$")
    base_branch: str = Field(min_length=1)
    review_base_sha: str = Field(pattern=FULL_SHA_PATTERN)
    head_sha: str = Field(pattern=FULL_SHA_PATTERN)
    candidate_receipt_sha256: str = Field(pattern=SHA256_PATTERN)
    approval_mode: ApprovalMode
    protected_app_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_mode_binding(self) -> ApprovalTargetV1:
        expected_url = f"https://github.com/{self.repository}/pull/{self.pr_number}"
        if self.pr_url != expected_url:
            raise ValueError("pr_url must match repository and pr_number")
        if self.approval_mode == "github_app" and self.protected_app_id is None:
            raise ValueError("github_app mode requires protected_app_id")
        if self.approval_mode == "compatibility_status" and self.protected_app_id is not None:
            raise ValueError("compatibility_status mode forbids protected_app_id")
        return self


class ApprovalProducerLeaseV1(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["coordination_approval_producer_lease"] = (
        "coordination_approval_producer_lease"
    )
    lease_id: str = Field(pattern=SHA256_PATTERN)
    target: ApprovalTargetV1
    owner_session_id: str = Field(pattern=SESSION_PATTERN)
    revision: int = Field(gt=0)
    acquired_at: AwareDatetime
    heartbeat_at: AwareDatetime
    expires_at: AwareDatetime
    predecessor_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_times(self) -> ApprovalProducerLeaseV1:
        if self.lease_id != _lease_id(self.target):
            raise ValueError("lease_id does not match repository and PR")
        if (self.revision == 1) != (self.predecessor_sha256 is None):
            raise ValueError("only revision 1 may omit predecessor_sha256")
        if self.heartbeat_at < self.acquired_at:
            raise ValueError("heartbeat_at cannot precede acquired_at")
        if self.expires_at <= self.heartbeat_at:
            raise ValueError("expires_at must follow heartbeat_at")
        return self


class ApprovalLeaseMutationReceiptV1(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["coordination_approval_lease_mutation"] = (
        "coordination_approval_lease_mutation"
    )
    operation: LeaseOperation
    recorded_at: AwareDatetime
    actor_session_id: str = Field(pattern=SESSION_PATTERN)
    target: ApprovalTargetV1
    prior_lease: ApprovalProducerLeaseV1 | None = None
    prior_lease_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    successor_lease_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    successor_lease: ApprovalProducerLeaseV1 | None = None
    evidence_ref: str = Field(min_length=1)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_receipt(self) -> ApprovalLeaseMutationReceiptV1:
        has_prior = self.prior_lease is not None
        if has_prior != (self.prior_lease_sha256 is not None):
            raise ValueError("prior lease and digest must appear together")
        if self.prior_lease is not None:
            if lease_sha256(self.prior_lease) != self.prior_lease_sha256:
                raise ValueError("prior lease digest does not match receipt content")
            if self.prior_lease.target != self.target:
                raise ValueError("prior lease target differs from mutation target")
        has_successor = self.successor_lease is not None
        if has_successor != (self.successor_lease_sha256 is not None):
            raise ValueError("successor lease and digest must appear together")
        if self.operation == "release" and has_successor:
            raise ValueError("release must not retain a successor lease")
        if self.operation != "release" and not has_successor:
            raise ValueError("non-release mutation requires a successor lease")
        if self.successor_lease is not None and (
            lease_sha256(self.successor_lease) != self.successor_lease_sha256
        ):
            raise ValueError("successor lease digest does not match receipt content")
        if self.successor_lease is not None and self.successor_lease.target != self.target:
            raise ValueError("successor lease target differs from mutation target")
        if self.operation == "acquire":
            if has_prior or self.successor_lease is None or self.successor_lease.revision != 1:
                raise ValueError("acquire requires one revision-1 successor and no prior lease")
            if self.actor_session_id != self.successor_lease.owner_session_id:
                raise ValueError("acquire actor must own the successor lease")
        else:
            if self.prior_lease is None:
                raise ValueError("non-acquire mutation requires a prior lease")
            if self.operation == "release":
                if self.actor_session_id != self.prior_lease.owner_session_id:
                    raise ValueError("release actor must own the prior lease")
            else:
                assert self.successor_lease is not None
                if self.successor_lease.revision != self.prior_lease.revision + 1:
                    raise ValueError("successor revision must increment exactly once")
                if self.successor_lease.predecessor_sha256 != self.prior_lease_sha256:
                    raise ValueError("successor predecessor digest must equal the prior lease")
                if self.operation == "heartbeat":
                    if (
                        self.actor_session_id != self.prior_lease.owner_session_id
                        or self.successor_lease.owner_session_id
                        != self.prior_lease.owner_session_id
                    ):
                        raise ValueError("heartbeat must retain exact owner custody")
                elif self.operation == "transfer":
                    if self.actor_session_id != self.prior_lease.owner_session_id:
                        raise ValueError("transfer actor must own the prior lease")
                    if self.successor_lease.owner_session_id == self.prior_lease.owner_session_id:
                        raise ValueError("transfer must change owner")
                elif self.operation == "takeover":
                    if self.recorded_at < self.prior_lease.expires_at:
                        raise ValueError("takeover receipt cannot precede lease expiry")
                    if self.actor_session_id != self.successor_lease.owner_session_id:
                        raise ValueError("takeover actor must own the successor lease")
                if self.operation in {"heartbeat", "transfer"} and (
                    self.recorded_at >= self.prior_lease.expires_at
                ):
                    raise ValueError("expired custody cannot heartbeat or transfer")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        )
        if self.receipt_sha256 != expected:
            raise ValueError("mutation receipt digest does not match canonical content")
        return self


class ApprovalLeaseTransactionV1(_StrictModel):
    """Write-ahead record that makes a lease mutation process-death recoverable."""

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["coordination_approval_lease_transaction"] = (
        "coordination_approval_lease_transaction"
    )
    prepared_at: AwareDatetime
    target: ApprovalTargetV1
    prior_lease: ApprovalProducerLeaseV1 | None
    successor_lease: ApprovalProducerLeaseV1 | None
    terminal_receipt: ApprovalLeaseMutationReceiptV1

    @model_validator(mode="after")
    def validate_transaction(self) -> ApprovalLeaseTransactionV1:
        receipt = self.terminal_receipt
        if receipt.target != self.target:
            raise ValueError("transaction target differs from terminal receipt")
        if receipt.prior_lease != self.prior_lease:
            raise ValueError("transaction prior lease differs from terminal receipt")
        if receipt.successor_lease != self.successor_lease:
            raise ValueError("transaction successor lease differs from terminal receipt")
        return self


class LiveApprovalFactsV1(_StrictModel):
    """Facts re-read from GitHub immediately before and after publication."""

    observed_at: AwareDatetime
    repository: str
    pr_number: int = Field(gt=0)
    pr_url: str
    base_branch: str
    head_sha: str = Field(pattern=FULL_SHA_PATTERN)
    pr_state: Literal["OPEN"]
    protection_context: str
    protected_app_id: int | None = Field(default=None, gt=0)
    strict_required_checks: bool
    enforce_admins: bool


class ApprovalCandidateReceiptV1(_StrictModel):
    """Semantic wrapper around one independently produced PR sign-off receipt."""

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["coordination_approval_candidate"] = (
        "coordination_approval_candidate"
    )
    review_id: str = Field(min_length=1)
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    pr_number: int = Field(gt=0)
    base_sha: str = Field(pattern=FULL_SHA_PATTERN)
    head_sha: str = Field(pattern=FULL_SHA_PATTERN)
    rubric_revision: str = Field(min_length=1)
    reviewer_sessions: tuple[str, ...] = Field(min_length=1)
    verdict: Literal["signed_off"]
    authority_state: Literal["evidence_receipt"]
    source_signoff_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_reviewers(self) -> ApprovalCandidateReceiptV1:
        if len(self.reviewer_sessions) != len(set(self.reviewer_sessions)):
            raise ValueError("reviewer sessions must be unique")
        if any(not re.fullmatch(SESSION_PATTERN, item) for item in self.reviewer_sessions):
            raise ValueError("reviewer sessions must be exact native session labels")
        return self


class ApprovalPublicationIntentV1(_StrictModel):
    """Durable pre-provider intent used to reconcile a process death."""

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["coordination_approval_publication_intent"] = (
        "coordination_approval_publication_intent"
    )
    intent_id: str = Field(pattern=SHA256_PATTERN)
    prepared_at: AwareDatetime
    publisher_session_id: str = Field(pattern=SESSION_PATTERN)
    lease: ApprovalProducerLeaseV1
    lease_sha256: str = Field(pattern=SHA256_PATTERN)
    target: ApprovalTargetV1
    candidate_receipt: ApprovalCandidateReceiptV1
    candidate_receipt_bytes_sha256: str = Field(pattern=SHA256_PATTERN)
    live_facts_before: LiveApprovalFactsV1

    @model_validator(mode="after")
    def validate_intent(self) -> ApprovalPublicationIntentV1:
        if lease_sha256(self.lease) != self.lease_sha256:
            raise ValueError("publication intent lease digest is invalid")
        if self.publisher_session_id != self.lease.owner_session_id:
            raise ValueError("publication intent publisher does not own the lease")
        if self.lease.target != self.target:
            raise ValueError("publication intent target differs from the lease")
        if self.candidate_receipt_bytes_sha256 != self.target.candidate_receipt_sha256:
            raise ValueError("publication intent candidate byte digest is invalid")
        _validate_candidate_identity(self.target, self.candidate_receipt)
        _validate_live_facts(self.target, self.live_facts_before)
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"intent_id"})
        )
        if self.intent_id != expected:
            raise ValueError("publication intent digest does not match canonical content")
        return self


class PublishedApprovalV1(_StrictModel):
    kind: Literal["commit_status", "check_run"]
    context: Literal["coordination-approval"]
    head_sha: str = Field(pattern=FULL_SHA_PATTERN)
    state: Literal["SUCCESS"]
    creator_login: str | None = None
    target_url: str | None = None
    app_id: int | None = Field(default=None, gt=0)
    provider_record_id: int = Field(gt=0)
    publication_intent_id: str = Field(pattern=SHA256_PATTERN)
    provider_recorded_at: AwareDatetime


class ApprovalPublicationReceiptV1(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["coordination_approval_publication"] = (
        "coordination_approval_publication"
    )
    publication_intent: ApprovalPublicationIntentV1
    published_at: AwareDatetime
    publisher_session_id: str = Field(pattern=SESSION_PATTERN)
    lease: ApprovalProducerLeaseV1
    lease_sha256: str = Field(pattern=SHA256_PATTERN)
    target: ApprovalTargetV1
    candidate_receipt: ApprovalCandidateReceiptV1
    candidate_receipt_bytes_sha256: str = Field(pattern=SHA256_PATTERN)
    live_facts_before: LiveApprovalFactsV1
    published_approval: PublishedApprovalV1
    live_facts_after: LiveApprovalFactsV1
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_receipt(self) -> ApprovalPublicationReceiptV1:
        intent = self.publication_intent
        if (
            intent.publisher_session_id != self.publisher_session_id
            or intent.lease != self.lease
            or intent.target != self.target
            or intent.candidate_receipt != self.candidate_receipt
            or intent.live_facts_before != self.live_facts_before
        ):
            raise ValueError("publication receipt differs from durable pre-publication intent")
        if self.published_approval.publication_intent_id != intent.intent_id:
            raise ValueError("provider approval is not bound to publication intent")
        if lease_sha256(self.lease) != self.lease_sha256:
            raise ValueError("publication lease digest does not match embedded lease")
        if self.lease.target != self.target:
            raise ValueError("publication target differs from embedded lease")
        if self.publisher_session_id != self.lease.owner_session_id:
            raise ValueError("publication session does not own the embedded lease")
        if self.published_at >= self.lease.expires_at:
            raise ValueError("publication occurred after lease expiry")
        if self.candidate_receipt_bytes_sha256 != self.target.candidate_receipt_sha256:
            raise ValueError("candidate receipt byte digest differs from publication target")
        _validate_candidate_identity(self.target, self.candidate_receipt)
        for facts in (self.live_facts_before, self.live_facts_after):
            _validate_live_facts(self.target, facts)
        if self.live_facts_before.head_sha != self.live_facts_after.head_sha:
            raise ValueError("live head changed during publication")
        if self.published_approval.head_sha != self.target.head_sha:
            raise ValueError("provider approval targets a different head")
        repository_owner = self.target.repository.split("/", 1)[0]
        if self.target.approval_mode == "compatibility_status":
            if (
                self.published_approval.kind != "commit_status"
                or self.published_approval.creator_login != repository_owner
                or self.published_approval.target_url != self.target.pr_url
                or self.published_approval.app_id is not None
            ):
                raise ValueError("compatibility approval provenance is invalid")
        elif (
            self.published_approval.kind != "check_run"
            or self.published_approval.app_id != self.target.protected_app_id
        ):
            raise ValueError("GitHub App approval provenance is invalid")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        )
        if self.receipt_sha256 != expected:
            raise ValueError("publication receipt digest does not match canonical content")
        return self


def _canonical_payload(value: BaseModel | dict[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json.dumps(
        to_jsonable_python(payload), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: BaseModel | dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(value)).hexdigest()


def lease_sha256(lease: ApprovalProducerLeaseV1) -> str:
    return canonical_sha256(lease)


def validate_candidate_receipt_bytes(
    target: ApprovalTargetV1, candidate_receipt_bytes: bytes
) -> ApprovalCandidateReceiptV1:
    actual = hashlib.sha256(candidate_receipt_bytes).hexdigest()
    if actual != target.candidate_receipt_sha256:
        raise CoordinationApprovalError(
            "candidate sign-off receipt bytes do not match the leased digest"
        )
    try:
        candidate = ApprovalCandidateReceiptV1.model_validate_json(candidate_receipt_bytes)
    except ValueError as exc:
        raise CoordinationApprovalError(
            f"candidate sign-off receipt is not canonical: {exc}"
        ) from exc
    _validate_candidate_identity(target, candidate)
    return candidate


def _validate_candidate_identity(
    target: ApprovalTargetV1, candidate: ApprovalCandidateReceiptV1
) -> None:
    expected = (
        target.repository, target.pr_number, target.review_base_sha, target.head_sha
    )
    actual = (
        candidate.repository, candidate.pr_number, candidate.base_sha, candidate.head_sha
    )
    if actual != expected:
        raise CoordinationApprovalError(
            "candidate sign-off repository, PR, base, or head differs from leased target"
        )


def build_publication_intent(
    *, lease: ApprovalProducerLeaseV1, publisher_session_id: str,
    candidate_receipt: ApprovalCandidateReceiptV1,
    live_facts_before: LiveApprovalFactsV1,
    prepared_at: datetime | None = None,
) -> ApprovalPublicationIntentV1:
    timestamp = prepared_at or datetime.now(UTC)
    payload = {
        "schema_version": "1.0",
        "record_type": "coordination_approval_publication_intent",
        "prepared_at": timestamp,
        "publisher_session_id": publisher_session_id,
        "lease": lease,
        "lease_sha256": lease_sha256(lease),
        "target": lease.target,
        "candidate_receipt": candidate_receipt,
        "candidate_receipt_bytes_sha256": lease.target.candidate_receipt_sha256,
        "live_facts_before": live_facts_before,
    }
    return ApprovalPublicationIntentV1.model_validate(
        {**payload, "intent_id": canonical_sha256(payload)}
    )


def _lease_id(target: ApprovalTargetV1) -> str:
    return hashlib.sha256(
        f"{target.repository}#{target.pr_number}".encode()
    ).hexdigest()


def _receipt_with_digest(payload: dict[str, Any]) -> ApprovalLeaseMutationReceiptV1:
    digest = canonical_sha256(payload)
    return ApprovalLeaseMutationReceiptV1.model_validate(
        {**payload, "receipt_sha256": digest}
    )


def _publication_with_digest(payload: dict[str, Any]) -> ApprovalPublicationReceiptV1:
    digest = canonical_sha256(payload)
    return ApprovalPublicationReceiptV1.model_validate(
        {**payload, "receipt_sha256": digest}
    )


def _safe_key(repository: str, pr_number: int) -> str:
    return f"{repository.replace('/', '__')}__pr-{pr_number}"


class ApprovalLeaseStore:
    """Atomic single-writer store for per-PR producer custody."""

    def __init__(self, root: Path = DEFAULT_STATE_ROOT) -> None:
        self.root = root.expanduser().resolve()

    def _lease_path(self, target: ApprovalTargetV1) -> Path:
        return self.root / "leases" / f"{_safe_key(target.repository, target.pr_number)}.json"

    def _transaction_path(
        self, target: ApprovalTargetV1, receipt: ApprovalLeaseMutationReceiptV1
    ) -> Path:
        return self.root / "transactions" / (
            f"{_safe_key(target.repository, target.pr_number)}__{receipt.receipt_sha256}.json"
        )

    def _publication_intent_path(self, intent_id: str) -> Path:
        return self.root / "publication-intents" / f"{intent_id}.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _atomic_write(path: Path, payload: BaseModel) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_raw = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_raw)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload.model_dump(mode="json"), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read(self, path: Path) -> ApprovalProducerLeaseV1 | None:
        if not path.is_file():
            return None
        try:
            return ApprovalProducerLeaseV1.model_validate_json(path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise CoordinationApprovalError(f"invalid approval lease {path}: {exc}") from exc

    def _recover_transactions_locked(
        self, target: ApprovalTargetV1, lease_path: Path
    ) -> None:
        transaction_dir = self.root / "transactions"
        pattern = f"{_safe_key(target.repository, target.pr_number)}__*.json"
        for path in sorted(transaction_dir.glob(pattern)) if transaction_dir.exists() else []:
            try:
                transaction = ApprovalLeaseTransactionV1.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise CoordinationApprovalError(
                    f"invalid approval lease transaction {path}: {exc}"
                ) from exc
            current = self._read(lease_path)
            if current == transaction.successor_lease:
                self._persist_receipt(transaction.terminal_receipt)
                path.unlink()
                continue
            if current == transaction.prior_lease:
                path.unlink()
                continue
            raise CoordinationApprovalError(
                "approval lease transaction cannot reconcile current state"
            )

    def _apply_transaction(
        self, *, target: ApprovalTargetV1, lease_path: Path,
        prior: ApprovalProducerLeaseV1 | None,
        successor: ApprovalProducerLeaseV1 | None,
        receipt: ApprovalLeaseMutationReceiptV1,
    ) -> Path:
        transaction = ApprovalLeaseTransactionV1(
            prepared_at=receipt.recorded_at,
            target=target,
            prior_lease=prior,
            successor_lease=successor,
            terminal_receipt=receipt,
        )
        transaction_path = self._transaction_path(target, receipt)
        self._atomic_write(transaction_path, transaction)
        try:
            if successor is None:
                lease_path.unlink(missing_ok=True)
            else:
                self._atomic_write(lease_path, successor)
            receipt_path = self._persist_receipt(receipt)
            transaction_path.unlink()
            return receipt_path
        except Exception:
            if prior is None:
                lease_path.unlink(missing_ok=True)
            else:
                self._atomic_write(lease_path, prior)
            transaction_path.unlink(missing_ok=True)
            raise

    def _persist_receipt(self, receipt: ApprovalLeaseMutationReceiptV1) -> Path:
        path = self.root / "receipts" / f"{receipt.receipt_sha256}.json"
        if path.exists():
            existing = path.read_bytes()
            expected = json.dumps(
                receipt.model_dump(mode="json"), indent=2, sort_keys=True
            ).encode("utf-8") + b"\n"
            if existing != expected:
                raise CoordinationApprovalError("receipt digest collision")
            return path
        self._atomic_write(path, receipt)
        return path

    @staticmethod
    def _new_lease(
        *, target: ApprovalTargetV1, owner_session_id: str, now: datetime,
        duration: timedelta, revision: int, predecessor_sha256: str | None,
        acquired_at: datetime | None = None,
    ) -> tuple[ApprovalProducerLeaseV1, ApprovalCandidateReceiptV1]:
        return ApprovalProducerLeaseV1(
            lease_id=_lease_id(target), target=target, owner_session_id=owner_session_id,
            revision=revision, acquired_at=acquired_at or now, heartbeat_at=now,
            expires_at=now + duration, predecessor_sha256=predecessor_sha256,
        )

    def acquire(
        self, *, target: ApprovalTargetV1, owner_session_id: str,
        duration: timedelta, now: datetime | None = None,
        evidence_ref: str = "sanctioned acquisition",
    ) -> tuple[ApprovalProducerLeaseV1, ApprovalLeaseMutationReceiptV1, Path]:
        timestamp = now or datetime.now(UTC)
        if duration <= timedelta(0):
            raise CoordinationApprovalError("lease duration must be positive")
        path = self._lease_path(target)
        with self._locked():
            self._recover_transactions_locked(target, path)
            existing = self._read(path)
            if existing is not None:
                raise CoordinationApprovalError(
                    "approval custody already exists; heartbeat, transfer, takeover, or release it"
                )
            lease = self._new_lease(
                target=target, owner_session_id=owner_session_id, now=timestamp,
                duration=duration, revision=1, predecessor_sha256=None,
            )
            successor = lease_sha256(lease)
            receipt = _receipt_with_digest({
                "schema_version": "1.0", "record_type": "coordination_approval_lease_mutation",
                "operation": "acquire", "recorded_at": timestamp,
                "actor_session_id": owner_session_id, "target": target,
                "prior_lease": None, "prior_lease_sha256": None,
                "successor_lease_sha256": successor, "successor_lease": lease,
                "evidence_ref": evidence_ref,
            })
            receipt_path = self._apply_transaction(
                target=target, lease_path=path, prior=None,
                successor=lease, receipt=receipt,
            )
            return lease, receipt, receipt_path

    def heartbeat(
        self, *, target: ApprovalTargetV1, owner_session_id: str,
        expected_lease_sha256: str, duration: timedelta,
        now: datetime | None = None,
    ) -> tuple[ApprovalProducerLeaseV1, ApprovalLeaseMutationReceiptV1, Path]:
        return self._replace(
            operation="heartbeat", target=target, actor_session_id=owner_session_id,
            successor_session_id=owner_session_id, expected_lease_sha256=expected_lease_sha256,
            duration=duration, now=now, require_expired=False,
            evidence_ref="exact-owner heartbeat",
        )

    def transfer(
        self, *, target: ApprovalTargetV1, owner_session_id: str,
        successor_session_id: str, expected_lease_sha256: str,
        duration: timedelta, evidence_ref: str, now: datetime | None = None,
    ) -> tuple[ApprovalProducerLeaseV1, ApprovalLeaseMutationReceiptV1, Path]:
        if successor_session_id == owner_session_id:
            raise CoordinationApprovalError("transfer requires a distinct successor session")
        return self._replace(
            operation="transfer", target=target, actor_session_id=owner_session_id,
            successor_session_id=successor_session_id,
            expected_lease_sha256=expected_lease_sha256, duration=duration, now=now,
            require_expired=False, evidence_ref=evidence_ref,
        )

    def takeover(
        self, *, target: ApprovalTargetV1, successor_session_id: str,
        expected_lease_sha256: str, duration: timedelta,
        evidence_ref: str, now: datetime | None = None,
    ) -> tuple[ApprovalProducerLeaseV1, ApprovalLeaseMutationReceiptV1, Path]:
        return self._replace(
            operation="takeover", target=target, actor_session_id=successor_session_id,
            successor_session_id=successor_session_id,
            expected_lease_sha256=expected_lease_sha256, duration=duration, now=now,
            require_expired=True, evidence_ref=evidence_ref,
        )

    def release(
        self, *, target: ApprovalTargetV1, owner_session_id: str,
        expected_lease_sha256: str, evidence_ref: str,
        now: datetime | None = None,
    ) -> tuple[ApprovalLeaseMutationReceiptV1, Path]:
        timestamp = now or datetime.now(UTC)
        path = self._lease_path(target)
        with self._locked():
            self._recover_transactions_locked(target, path)
            current = self._read(path)
            if current is None:
                raise CoordinationApprovalError("approval custody does not exist")
            current_sha = lease_sha256(current)
            if current_sha != expected_lease_sha256:
                raise CoordinationApprovalError("approval lease compare-and-swap failed")
            if current.owner_session_id != owner_session_id:
                raise CoordinationApprovalError("only the exact owner session may release custody")
            receipt = _receipt_with_digest({
                "schema_version": "1.0", "record_type": "coordination_approval_lease_mutation",
                "operation": "release", "recorded_at": timestamp,
                "actor_session_id": owner_session_id, "target": target,
                "prior_lease": current, "prior_lease_sha256": current_sha,
                "successor_lease_sha256": None, "successor_lease": None,
                "evidence_ref": evidence_ref,
            })
            receipt_path = self._apply_transaction(
                target=target, lease_path=path, prior=current,
                successor=None, receipt=receipt,
            )
            return receipt, receipt_path

    def _replace(
        self, *, operation: Literal["heartbeat", "transfer", "takeover"],
        target: ApprovalTargetV1, actor_session_id: str, successor_session_id: str,
        expected_lease_sha256: str, duration: timedelta, now: datetime | None,
        require_expired: bool, evidence_ref: str,
    ) -> tuple[ApprovalProducerLeaseV1, ApprovalLeaseMutationReceiptV1, Path]:
        timestamp = now or datetime.now(UTC)
        if duration <= timedelta(0):
            raise CoordinationApprovalError("lease duration must be positive")
        path = self._lease_path(target)
        with self._locked():
            self._recover_transactions_locked(target, path)
            current = self._read(path)
            if current is None:
                raise CoordinationApprovalError("approval custody does not exist")
            current_sha = lease_sha256(current)
            if current_sha != expected_lease_sha256:
                raise CoordinationApprovalError("approval lease compare-and-swap failed")
            if current.target != target:
                raise CoordinationApprovalError("approval target changed")
            if require_expired:
                if timestamp < current.expires_at:
                    raise CoordinationApprovalError("healthy approval custody cannot be taken over")
            elif current.owner_session_id != actor_session_id:
                raise CoordinationApprovalError("only the exact owner session may mutate custody")
            if not require_expired and timestamp >= current.expires_at:
                raise CoordinationApprovalError(
                    "expired approval custody cannot heartbeat or transfer; use takeover"
                )
            successor = self._new_lease(
                target=current.target, owner_session_id=successor_session_id,
                now=timestamp, duration=duration, revision=current.revision + 1,
                predecessor_sha256=current_sha, acquired_at=current.acquired_at,
            )
            successor_sha = lease_sha256(successor)
            receipt = _receipt_with_digest({
                "schema_version": "1.0", "record_type": "coordination_approval_lease_mutation",
                "operation": operation, "recorded_at": timestamp,
                "actor_session_id": actor_session_id, "target": target,
                "prior_lease": current, "prior_lease_sha256": current_sha,
                "successor_lease_sha256": successor_sha, "successor_lease": successor,
                "evidence_ref": evidence_ref,
            })
            receipt_path = self._apply_transaction(
                target=target, lease_path=path, prior=current,
                successor=successor, receipt=receipt,
            )
            return successor, receipt, receipt_path

    def current(self, target: ApprovalTargetV1) -> ApprovalProducerLeaseV1 | None:
        with self._locked():
            path = self._lease_path(target)
            self._recover_transactions_locked(target, path)
            return self._read(path)

    def assert_publishable(
        self, *, target: ApprovalTargetV1, owner_session_id: str,
        expected_lease_sha256: str, live_facts: LiveApprovalFactsV1,
        candidate_receipt_bytes: bytes,
        now: datetime | None = None, max_observation_age: timedelta = timedelta(minutes=2),
    ) -> ApprovalProducerLeaseV1:
        timestamp = now or datetime.now(UTC)
        with self._locked():
            path = self._lease_path(target)
            self._recover_transactions_locked(target, path)
            lease = self._read(path)
            if lease is None:
                raise CoordinationApprovalError("approval custody does not exist")
            if lease_sha256(lease) != expected_lease_sha256:
                raise CoordinationApprovalError("approval lease compare-and-swap failed")
            if lease.owner_session_id != owner_session_id:
                raise CoordinationApprovalError("publisher is not the exact owner session")
            if timestamp >= lease.expires_at:
                raise CoordinationApprovalError("approval custody expired")
            candidate = validate_candidate_receipt_bytes(target, candidate_receipt_bytes)
            if live_facts.observed_at > timestamp or timestamp - live_facts.observed_at > max_observation_age:
                raise CoordinationApprovalError("live GitHub facts are stale or future-dated")
            _validate_live_facts(target, live_facts)
            return lease, candidate

    def persist_publication_intent(self, intent: ApprovalPublicationIntentV1) -> Path:
        with self._locked():
            pending = self._pending_publication_intents_locked(intent.target)
            if pending:
                if len(pending) == 1 and pending[0] == intent:
                    return self._publication_intent_path(intent.intent_id)
                raise CoordinationApprovalError(
                    "another publication intent is already pending for this PR"
                )
            path = self._publication_intent_path(intent.intent_id)
            self._atomic_write(path, intent)
            return path

    def _pending_publication_intents_locked(
        self, target: ApprovalTargetV1
    ) -> list[ApprovalPublicationIntentV1]:
        directory = self.root / "publication-intents"
        if not directory.exists():
            return []
        pending: list[ApprovalPublicationIntentV1] = []
        for path in sorted(directory.glob("*.json")):
            try:
                intent = ApprovalPublicationIntentV1.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise CoordinationApprovalError(
                    f"invalid publication intent {path}: {exc}"
                ) from exc
            if intent.target.repository == target.repository and intent.target.pr_number == target.pr_number:
                pending.append(intent)
        return pending

    def pending_publication_intents(
        self, target: ApprovalTargetV1
    ) -> tuple[ApprovalPublicationIntentV1, ...]:
        with self._locked():
            return tuple(self._pending_publication_intents_locked(target))

    def complete_publication(
        self, *, intent: ApprovalPublicationIntentV1,
        receipt: ApprovalPublicationReceiptV1,
    ) -> Path:
        if receipt.publication_intent != intent:
            raise CoordinationApprovalError(
                "publication receipt does not consume the exact pending intent"
            )
        intent_path = self._publication_intent_path(intent.intent_id)
        receipt_path = self.root / "publications" / f"{receipt.receipt_sha256}.json"
        with self._locked():
            if not intent_path.is_file():
                if receipt_path.is_file():
                    return receipt_path
                raise CoordinationApprovalError("publication intent is not pending")
            persisted = ApprovalPublicationIntentV1.model_validate_json(
                intent_path.read_text(encoding="utf-8")
            )
            if persisted != intent:
                raise CoordinationApprovalError("pending publication intent changed")
            if receipt_path.exists():
                raise CoordinationApprovalError("publication receipt already exists")
            self._atomic_write(receipt_path, receipt)
            intent_path.unlink()
            return receipt_path


def _validate_live_facts(target: ApprovalTargetV1, facts: LiveApprovalFactsV1) -> None:
    expected = (
        target.repository, target.pr_number, target.pr_url,
        target.base_branch, target.head_sha,
    )
    actual = (
        facts.repository, facts.pr_number, facts.pr_url,
        facts.base_branch, facts.head_sha,
    )
    if actual != expected:
        raise CoordinationApprovalError("live pull-request identity differs from leased target")
    if facts.protection_context != "coordination-approval":
        raise CoordinationApprovalError(
            "branch protection is frozen or lacks canonical coordination-approval"
        )
    if facts.protected_app_id != target.protected_app_id:
        raise CoordinationApprovalError("branch-protection App binding differs from leased target")
    if not facts.strict_required_checks or not facts.enforce_admins:
        raise CoordinationApprovalError(
            "branch protection must require strict checks and administrator enforcement"
        )


def build_publication_receipt(
    *, publication_intent: ApprovalPublicationIntentV1,
    published_approval: PublishedApprovalV1,
    live_facts_after: LiveApprovalFactsV1,
) -> ApprovalPublicationReceiptV1:
    intent = publication_intent
    target = intent.target
    payload = {
        "schema_version": "1.0", "record_type": "coordination_approval_publication",
        "publication_intent": intent,
        "published_at": published_approval.provider_recorded_at,
        "publisher_session_id": intent.publisher_session_id,
        "lease": intent.lease, "lease_sha256": intent.lease_sha256, "target": target,
        "candidate_receipt": intent.candidate_receipt,
        "candidate_receipt_bytes_sha256": intent.candidate_receipt_bytes_sha256,
        "live_facts_before": intent.live_facts_before,
        "published_approval": published_approval,
        "live_facts_after": live_facts_after,
    }
    return _publication_with_digest(payload)
