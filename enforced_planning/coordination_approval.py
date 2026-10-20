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
    prior_lease_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    successor_lease_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    successor_lease: ApprovalProducerLeaseV1 | None = None
    evidence_ref: str = Field(min_length=1)
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_receipt(self) -> ApprovalLeaseMutationReceiptV1:
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
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        )
        if self.receipt_sha256 != expected:
            raise ValueError("mutation receipt digest does not match canonical content")
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


class PublishedApprovalV1(_StrictModel):
    kind: Literal["commit_status", "check_run"]
    context: Literal["coordination-approval"]
    head_sha: str = Field(pattern=FULL_SHA_PATTERN)
    state: Literal["SUCCESS"]
    creator_login: str | None = None
    target_url: str | None = None
    app_id: int | None = Field(default=None, gt=0)
    provider_record_id: int = Field(gt=0)


class ApprovalPublicationReceiptV1(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["coordination_approval_publication"] = (
        "coordination_approval_publication"
    )
    published_at: AwareDatetime
    publisher_session_id: str = Field(pattern=SESSION_PATTERN)
    lease_sha256: str = Field(pattern=SHA256_PATTERN)
    target: ApprovalTargetV1
    live_facts_before: LiveApprovalFactsV1
    published_approval: PublishedApprovalV1
    live_facts_after: LiveApprovalFactsV1
    receipt_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_receipt(self) -> ApprovalPublicationReceiptV1:
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
) -> None:
    actual = hashlib.sha256(candidate_receipt_bytes).hexdigest()
    if actual != target.candidate_receipt_sha256:
        raise CoordinationApprovalError(
            "candidate sign-off receipt bytes do not match the leased digest"
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
    ) -> ApprovalProducerLeaseV1:
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
                "actor_session_id": owner_session_id, "prior_lease_sha256": None,
                "successor_lease_sha256": successor, "successor_lease": lease,
                "evidence_ref": evidence_ref,
            })
            self._atomic_write(path, lease)
            try:
                receipt_path = self._persist_receipt(receipt)
            except Exception:
                path.unlink(missing_ok=True)
                raise
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
                "actor_session_id": owner_session_id, "prior_lease_sha256": current_sha,
                "successor_lease_sha256": None, "successor_lease": None,
                "evidence_ref": evidence_ref,
            })
            path.unlink()
            try:
                receipt_path = self._persist_receipt(receipt)
            except Exception:
                self._atomic_write(path, current)
                raise
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
            successor = self._new_lease(
                target=current.target, owner_session_id=successor_session_id,
                now=timestamp, duration=duration, revision=current.revision + 1,
                predecessor_sha256=current_sha, acquired_at=current.acquired_at,
            )
            successor_sha = lease_sha256(successor)
            receipt = _receipt_with_digest({
                "schema_version": "1.0", "record_type": "coordination_approval_lease_mutation",
                "operation": operation, "recorded_at": timestamp,
                "actor_session_id": actor_session_id, "prior_lease_sha256": current_sha,
                "successor_lease_sha256": successor_sha, "successor_lease": successor,
                "evidence_ref": evidence_ref,
            })
            self._atomic_write(path, successor)
            try:
                receipt_path = self._persist_receipt(receipt)
            except Exception:
                self._atomic_write(path, current)
                raise
            return successor, receipt, receipt_path

    def current(self, target: ApprovalTargetV1) -> ApprovalProducerLeaseV1 | None:
        with self._locked():
            return self._read(self._lease_path(target))

    def assert_publishable(
        self, *, target: ApprovalTargetV1, owner_session_id: str,
        expected_lease_sha256: str, live_facts: LiveApprovalFactsV1,
        candidate_receipt_bytes: bytes,
        now: datetime | None = None, max_observation_age: timedelta = timedelta(minutes=2),
    ) -> ApprovalProducerLeaseV1:
        timestamp = now or datetime.now(UTC)
        with self._locked():
            lease = self._read(self._lease_path(target))
            if lease is None:
                raise CoordinationApprovalError("approval custody does not exist")
            if lease_sha256(lease) != expected_lease_sha256:
                raise CoordinationApprovalError("approval lease compare-and-swap failed")
            if lease.owner_session_id != owner_session_id:
                raise CoordinationApprovalError("publisher is not the exact owner session")
            if timestamp >= lease.expires_at:
                raise CoordinationApprovalError("approval custody expired")
            validate_candidate_receipt_bytes(target, candidate_receipt_bytes)
            if live_facts.observed_at > timestamp or timestamp - live_facts.observed_at > max_observation_age:
                raise CoordinationApprovalError("live GitHub facts are stale or future-dated")
            _validate_live_facts(target, live_facts)
            return lease

    def persist_publication(self, receipt: ApprovalPublicationReceiptV1) -> Path:
        path = self.root / "publications" / f"{receipt.receipt_sha256}.json"
        with self._locked():
            if path.exists():
                raise CoordinationApprovalError("publication receipt already exists")
            self._atomic_write(path, receipt)
        return path


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


def build_publication_receipt(
    *, lease: ApprovalProducerLeaseV1, publisher_session_id: str,
    live_facts_before: LiveApprovalFactsV1, published_approval: PublishedApprovalV1,
    live_facts_after: LiveApprovalFactsV1, repository_owner: str,
    published_at: datetime | None = None,
) -> ApprovalPublicationReceiptV1:
    timestamp = published_at or datetime.now(UTC)
    target = lease.target
    if publisher_session_id != lease.owner_session_id:
        raise CoordinationApprovalError("publication receipt publisher is not the lease owner")
    if timestamp >= lease.expires_at:
        raise CoordinationApprovalError("publication occurred after lease expiry")
    _validate_live_facts(target, live_facts_before)
    _validate_live_facts(target, live_facts_after)
    if live_facts_after.head_sha != live_facts_before.head_sha:
        raise CoordinationApprovalError("pull-request head changed during publication")
    if published_approval.head_sha != target.head_sha:
        raise CoordinationApprovalError("published approval targets a different head")
    if target.approval_mode == "compatibility_status":
        if published_approval.kind != "commit_status":
            raise CoordinationApprovalError("compatibility mode requires a commit status")
        if published_approval.creator_login != repository_owner:
            raise CoordinationApprovalError("compatibility status creator is not repository owner")
        if published_approval.target_url != target.pr_url:
            raise CoordinationApprovalError("compatibility status target_url is not the exact PR")
        if published_approval.app_id is not None:
            raise CoordinationApprovalError("compatibility status must not claim an App identity")
    else:
        if published_approval.kind != "check_run":
            raise CoordinationApprovalError("github_app mode requires a check run")
        if published_approval.app_id != target.protected_app_id:
            raise CoordinationApprovalError("approval check came from the wrong GitHub App")
    payload = {
        "schema_version": "1.0", "record_type": "coordination_approval_publication",
        "published_at": timestamp, "publisher_session_id": publisher_session_id,
        "lease_sha256": lease_sha256(lease), "target": target,
        "live_facts_before": live_facts_before,
        "published_approval": published_approval,
        "live_facts_after": live_facts_after,
    }
    return _publication_with_digest(payload)
