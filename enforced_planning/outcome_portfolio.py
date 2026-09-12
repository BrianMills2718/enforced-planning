"""Allocate graph-bound outcome slots before durable outcome selection.

Project Graph owns static repository identity and reviewed owner class.  This
module owns only local, append-only allocation and disposition events.  It
never chooses an outcome implicitly: callers must provide an immutable request
inside an exact live claim worktree before a class-bearing outcome can consume a
portfolio slot.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from enforced_planning import coordination_claims
from enforced_planning.outcome_continuation import (
    ContinuationError,
    OutcomeContinuationScenarioV1,
    PortfolioClass,
    canonical_sha256,
    evaluate_scenario,
)

DEFAULT_OUTCOME_PORTFOLIO_LEDGER_PATH = (
    Path.home() / ".claude" / "coordination" / "outcome-portfolio-allocations-v1.json"
)
HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"
FULL_GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PORTABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
GLOBAL_NON_PRODUCT_BUCKET = "global:maintenance-or-external-obligation"

PortfolioDisposition = Literal["parked", "complete"]


class OutcomePortfolioError(RuntimeError):
    """Fail-loud portfolio error with one stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class StrictModel(BaseModel):
    """Strict immutable-compatible base for portfolio records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _timezone_aware(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _portable_id(value: str, *, field_name: str) -> None:
    if not PORTABLE_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a portable identifier")


class ProjectGraphOutcomeAuthorityV1(StrictModel):
    """Exact reviewed repository identity loaded from one Git object."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["project_graph_outcome_authority"] = "project_graph_outcome_authority"
    project_graph_repo: str = Field(min_length=1)
    project_graph_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    project_graph_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    project_record_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    governance_review_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    project_id: str = Field(min_length=1)
    status: Literal["active"] = "active"
    record_kind: Literal["repository"] = "repository"
    owner_class: str = Field(min_length=1)
    predecessor_project_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_authority(self) -> ProjectGraphOutcomeAuthorityV1:
        _portable_id(self.project_id, field_name="project_id")
        _portable_id(self.owner_class, field_name="owner_class")
        for predecessor in self.predecessor_project_ids:
            _portable_id(predecessor, field_name="predecessor_project_ids")
        if len(set(self.predecessor_project_ids)) != len(self.predecessor_project_ids):
            raise ValueError("predecessor_project_ids must be unique")
        return self


class PortfolioClaimBindingV1(StrictModel):
    """Stable exact-claim identity retained by one portfolio event."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    agent: str = Field(min_length=1)
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    session_id: str = Field(min_length=3)
    repo_root: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    claim_source_file: str = Field(min_length=1)
    claim_plan_ref: str | None = None


class OutcomePortfolioAllocationRequestV1(StrictModel):
    """Explicit human/operator decision to consume one bounded WIP slot."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_portfolio_allocation_request"] = "outcome_portfolio_allocation_request"
    allocation_id: str = Field(min_length=3)
    requested_at: datetime
    project_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=3)
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_id: str = Field(min_length=3)
    outcome_lineage_id: str = Field(min_length=3)
    portfolio_class: PortfolioClass
    decision_ref: str = Field(min_length=3)
    purpose: str = Field(min_length=12)
    stopping_condition: str = Field(min_length=12)

    @model_validator(mode="after")
    def validate_request(self) -> OutcomePortfolioAllocationRequestV1:
        _timezone_aware(self.requested_at, field_name="requested_at")
        for field_name, value in (
            ("allocation_id", self.allocation_id),
            ("project_id", self.project_id),
            ("scenario_id", self.scenario_id),
            ("outcome_id", self.outcome_id),
            ("outcome_lineage_id", self.outcome_lineage_id),
        ):
            _portable_id(value, field_name=field_name)
        return self


class OutcomePortfolioDispositionRequestV1(StrictModel):
    """Explicit append-only release request for one exact allocation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_portfolio_disposition_request"] = "outcome_portfolio_disposition_request"
    disposition_id: str = Field(min_length=3)
    requested_at: datetime
    allocation_id: str = Field(min_length=3)
    allocation_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    disposition: PortfolioDisposition
    decision_ref: str = Field(min_length=3)
    reason: str = Field(min_length=12)

    @model_validator(mode="after")
    def validate_request(self) -> OutcomePortfolioDispositionRequestV1:
        _timezone_aware(self.requested_at, field_name="requested_at")
        _portable_id(self.disposition_id, field_name="disposition_id")
        _portable_id(self.allocation_id, field_name="allocation_id")
        return self


class OutcomePortfolioAllocationV1(StrictModel):
    """Immutable accepted allocation event."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_portfolio_allocation"] = "outcome_portfolio_allocation"
    allocated_at: datetime
    allocation_id: str = Field(min_length=3)
    bucket: str = Field(min_length=3)
    portfolio_class: PortfolioClass
    owner_class: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=3)
    outcome_lineage_id: str = Field(min_length=3)
    scenario_id: str = Field(min_length=3)
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_ref: str = Field(min_length=1)
    request: OutcomePortfolioAllocationRequestV1
    request_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    request_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    request_ref: str = Field(min_length=1)
    project_authority: ProjectGraphOutcomeAuthorityV1
    project_authority_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    claim: PortfolioClaimBindingV1
    claim_sha256: str = Field(pattern=HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_allocation(self) -> OutcomePortfolioAllocationV1:
        _timezone_aware(self.allocated_at, field_name="allocated_at")
        expected_bucket = portfolio_bucket(self.portfolio_class, self.owner_class)
        checks: dict[str, tuple[Any, Any]] = {
            "bucket": (self.bucket, expected_bucket),
            "allocation_id": (self.allocation_id, self.request.allocation_id),
            "portfolio_class": (self.portfolio_class, self.request.portfolio_class),
            "project_id": (self.project_id, self.request.project_id),
            "scenario_id": (self.scenario_id, self.request.scenario_id),
            "outcome_contract_sha256": (
                self.outcome_contract_sha256,
                self.request.outcome_contract_sha256,
            ),
            "outcome_id": (self.outcome_id, self.request.outcome_id),
            "outcome_lineage_id": (
                self.outcome_lineage_id,
                self.request.outcome_lineage_id,
            ),
            "authority_project": (self.project_id, self.project_authority.project_id),
            "authority_owner": (self.owner_class, self.project_authority.owner_class),
            "claim_project": (self.project_id, self.claim.project),
            "request_sha256": (self.request_sha256, canonical_sha256(self.request)),
            "project_authority_sha256": (
                self.project_authority_sha256,
                canonical_sha256(self.project_authority),
            ),
            "claim_sha256": (self.claim_sha256, canonical_sha256(self.claim)),
        }
        mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
        if mismatches:
            raise ValueError("portfolio allocation mismatch: " + ", ".join(mismatches))
        return self


class OutcomePortfolioDispositionV1(StrictModel):
    """Immutable event that releases one allocation without deleting it."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_portfolio_disposition"] = "outcome_portfolio_disposition"
    recorded_at: datetime
    disposition_id: str = Field(min_length=3)
    allocation_id: str = Field(min_length=3)
    allocation_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    disposition: PortfolioDisposition
    request: OutcomePortfolioDispositionRequestV1
    request_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    request_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    request_ref: str = Field(min_length=1)
    claim: PortfolioClaimBindingV1
    claim_sha256: str = Field(pattern=HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_disposition(self) -> OutcomePortfolioDispositionV1:
        _timezone_aware(self.recorded_at, field_name="recorded_at")
        checks: dict[str, tuple[Any, Any]] = {
            "disposition_id": (self.disposition_id, self.request.disposition_id),
            "allocation_id": (self.allocation_id, self.request.allocation_id),
            "allocation_sha256": (
                self.allocation_sha256,
                self.request.allocation_sha256,
            ),
            "disposition": (self.disposition, self.request.disposition),
            "request_sha256": (self.request_sha256, canonical_sha256(self.request)),
            "claim_sha256": (self.claim_sha256, canonical_sha256(self.claim)),
        }
        mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
        if mismatches:
            raise ValueError("portfolio disposition mismatch: " + ", ".join(mismatches))
        return self


OutcomePortfolioRecordV1: TypeAlias = Annotated[
    OutcomePortfolioAllocationV1 | OutcomePortfolioDispositionV1,
    Field(discriminator="record_type"),
]


class OutcomePortfolioLedgerV1(StrictModel):
    """Atomically stored append-only portfolio event history."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_portfolio_ledger"] = "outcome_portfolio_ledger"
    records: tuple[OutcomePortfolioRecordV1, ...] = ()


class OutcomePortfolioAllocationResultV1(StrictModel):
    """Operator-facing accepted or idempotently replayed allocation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["allocated", "idempotent"]
    allocation: OutcomePortfolioAllocationV1
    allocation_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    ledger_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    ledger_path: str = Field(min_length=1)


class OutcomePortfolioDispositionResultV1(StrictModel):
    """Operator-facing accepted or idempotently replayed disposition."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["recorded", "idempotent"]
    disposition: OutcomePortfolioDispositionV1
    disposition_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    ledger_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    ledger_path: str = Field(min_length=1)


class ResolvedOutcomePortfolioAllocationV1(StrictModel):
    """One exact active allocation accepted for classed selection."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    allocation: OutcomePortfolioAllocationV1
    allocation_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    ledger_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    ledger_path: str = Field(min_length=1)


def portfolio_bucket(portfolio_class: PortfolioClass, owner_class: str) -> str:
    """Return the approved WIP bucket for one class and reviewed owner."""

    return f"product:{owner_class}" if portfolio_class == "product" else GLOBAL_NON_PRODUCT_BUCKET


def _run_git(repo: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = ""
        if isinstance(exc, subprocess.CalledProcessError):
            stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        detail = f": {stderr}" if stderr else ""
        raise OutcomePortfolioError(
            "project_graph_git_unavailable",
            f"unable to read exact Project Graph Git object{detail}",
        ) from exc
    return completed.stdout


def _required_mapping(value: Any, *, code: str, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OutcomePortfolioError(code, message)
    return value


def resolve_project_graph_authority(
    *,
    project_graph_repo: Path,
    project_graph_revision: str,
    project_id: str,
) -> ProjectGraphOutcomeAuthorityV1:
    """Resolve one active reviewed repository from exact Git bytes."""

    if not FULL_GIT_REVISION_PATTERN.fullmatch(project_graph_revision):
        raise OutcomePortfolioError(
            "project_graph_revision_not_exact",
            "Project Graph revision must be one full lowercase 40-character commit id",
        )
    resolved_repo = project_graph_repo.expanduser().resolve()
    resolved_revision = (
        _run_git(
            resolved_repo,
            "rev-parse",
            "--verify",
            f"{project_graph_revision}^{{commit}}",
        )
        .decode("ascii", errors="strict")
        .strip()
    )
    if resolved_revision != project_graph_revision:
        raise OutcomePortfolioError(
            "project_graph_revision_mismatch",
            "Project Graph revision did not resolve to the exact supplied commit",
        )
    graph_bytes = _run_git(
        resolved_repo,
        "show",
        f"{project_graph_revision}:PROJECT_GRAPH.json",
    )
    try:
        records = json.loads(graph_bytes)
    except json.JSONDecodeError as exc:
        raise OutcomePortfolioError(
            "project_graph_invalid",
            f"exact PROJECT_GRAPH.json is not valid JSON: {exc}",
        ) from exc
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise OutcomePortfolioError(
            "project_graph_invalid",
            "exact PROJECT_GRAPH.json must be an array of object records",
        )
    matches = [record for record in records if record.get("id") == project_id]
    if not matches:
        raise OutcomePortfolioError(
            "project_unregistered",
            f"project {project_id!r} is absent from the exact Project Graph revision",
        )
    if len(matches) != 1:
        raise OutcomePortfolioError(
            "project_graph_invalid",
            f"project {project_id!r} appears {len(matches)} times in Project Graph",
        )
    record = matches[0]
    if record.get("status") != "active":
        raise OutcomePortfolioError(
            "project_inactive",
            f"project {project_id!r} is not active at the exact Project Graph revision",
        )
    if record.get("record_kind") != "repository":
        raise OutcomePortfolioError(
            "project_not_repository",
            f"project {project_id!r} is not a repository record",
        )
    governance = _required_mapping(
        record.get("repository_governance"),
        code="repository_governance_missing",
        message=f"project {project_id!r} lacks repository_governance",
    )
    owner_class = governance.get("owner_class")
    if not isinstance(owner_class, str) or not owner_class.strip():
        raise OutcomePortfolioError(
            "repository_owner_class_missing",
            f"project {project_id!r} lacks a reviewed owner class",
        )
    review = _required_mapping(
        governance.get("review"),
        code="repository_governance_unreviewed",
        message=f"project {project_id!r} lacks repository-governance review evidence",
    )
    evidence = review.get("evidence")
    if not (
        isinstance(review.get("reviewed_by"), str)
        and review["reviewed_by"].strip()
        and isinstance(review.get("reviewed_at"), str)
        and review["reviewed_at"].strip()
        and isinstance(evidence, list)
        and evidence
        and all(isinstance(item, str) and item.strip() for item in evidence)
    ):
        raise OutcomePortfolioError(
            "repository_governance_unreviewed",
            f"project {project_id!r} has incomplete repository-governance review evidence",
        )
    raw_predecessors = record.get("supersedes", [])
    if not isinstance(raw_predecessors, list) or not all(
        isinstance(item, str) and item.strip() for item in raw_predecessors
    ):
        raise OutcomePortfolioError(
            "project_graph_invalid",
            f"project {project_id!r} has invalid supersedes lineage",
        )
    return ProjectGraphOutcomeAuthorityV1(
        project_graph_repo=str(resolved_repo),
        project_graph_revision=project_graph_revision,
        project_graph_file_sha256=hashlib.sha256(graph_bytes).hexdigest(),
        project_record_sha256=canonical_sha256(record),
        governance_review_sha256=canonical_sha256(review),
        project_id=project_id,
        owner_class=owner_class.strip(),
        predecessor_project_ids=tuple(sorted(set(raw_predecessors))),
    )


def _load_claim_records(claims_dir: Path) -> list[coordination_claims.ClaimRecord]:
    """Load authority-relevant claims while isolating explicit terminal debris.

    Completed claims cannot authorize an allocation or conflict with a live
    claim. Older tooling sometimes left incomplete completed records in the
    live registry, so requiring those terminal records to normalize makes an
    unrelated historical file a global allocator outage. Missing, unknown, and
    live statuses still fail closed below.
    """

    records: list[coordination_claims.ClaimRecord] = []
    if not claims_dir.is_dir():
        return records
    for path in sorted(claims_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise OutcomePortfolioError(
                "claim_registry_invalid",
                f"unable to read canonical claim {path}: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise OutcomePortfolioError(
                "claim_registry_invalid",
                f"canonical claim {path} must be a YAML mapping",
            )
        raw_status = payload.get("status")
        if isinstance(raw_status, str) and raw_status.strip().lower() in coordination_claims.COMPLETED_STATUSES:
            continue
        record = coordination_claims.normalize_claim(
            payload,
            source_file=str(path.resolve()),
        )
        if record is None:
            raise OutcomePortfolioError(
                "claim_registry_invalid",
                f"canonical claim {path} cannot be normalized",
            )
        records.append(record)
    return records


def _exact_live_claim(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str,
    claims_dir: Path,
) -> coordination_claims.ClaimRecord:
    claims = _load_claim_records(claims_dir)
    live = [claim for claim in claims if claim.is_live()]
    matches = [
        claim
        for claim in live
        if claim.agent == agent
        and claim.primary_project() == project
        and claim.scope == scope
        and claim.session_id == session_id
    ]
    if len(matches) != 1:
        raise OutcomePortfolioError(
            "exact_claim_unavailable",
            f"expected exactly one live claim for {agent}:{project}:{scope}:{session_id}; found {len(matches)}",
        )
    claim = matches[0]
    issues = coordination_claims.coordination_health_issues(claim, active_claims=live)
    if issues:
        raise OutcomePortfolioError(
            "claim_not_healthy",
            "exact live claim is not healthy: " + ", ".join(issues),
        )
    return claim


def _normalized_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def _claim_binding(claim: coordination_claims.ClaimRecord) -> PortfolioClaimBindingV1:
    return PortfolioClaimBindingV1(
        agent=claim.agent,
        project=claim.primary_project() or "",
        scope=claim.scope,
        session_id=claim.session_id or "",
        repo_root=_normalized_path(claim.repo_root or ""),
        worktree_path=_normalized_path(claim.worktree_path or ""),
        branch=claim.branch or "",
        claim_source_file=_normalized_path(claim.source_file or ""),
        claim_plan_ref=claim.plan_ref,
    )


def _claimed_file(path: Path, *, claim: coordination_claims.ClaimRecord) -> tuple[bytes, str]:
    resolved = path.expanduser().resolve()
    worktree = Path(claim.worktree_path or "").expanduser().resolve()
    try:
        reference = resolved.relative_to(worktree).as_posix()
    except ValueError as exc:
        raise OutcomePortfolioError(
            "portfolio_input_outside_worktree",
            "portfolio scenario and request files must be inside the exact claim worktree",
        ) from exc
    try:
        return resolved.read_bytes(), reference
    except OSError as exc:
        raise OutcomePortfolioError(
            "portfolio_input_unavailable",
            f"unable to read claimed portfolio input {reference}: {exc}",
        ) from exc


def _load_scenario(
    path: Path,
    *,
    claim: coordination_claims.ClaimRecord,
) -> tuple[OutcomeContinuationScenarioV1, str, str]:
    content, reference = _claimed_file(path, claim=claim)
    try:
        scenario = OutcomeContinuationScenarioV1.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomePortfolioError(
            "portfolio_scenario_invalid",
            f"portfolio scenario is invalid: {exc}",
        ) from exc
    return scenario, hashlib.sha256(content).hexdigest(), reference


def _load_allocation_request(
    path: Path,
    *,
    claim: coordination_claims.ClaimRecord,
) -> tuple[OutcomePortfolioAllocationRequestV1, str, str]:
    content, reference = _claimed_file(path, claim=claim)
    try:
        request = OutcomePortfolioAllocationRequestV1.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomePortfolioError(
            "portfolio_allocation_request_invalid",
            f"portfolio allocation request is invalid: {exc}",
        ) from exc
    return request, hashlib.sha256(content).hexdigest(), reference


def _load_disposition_request(
    path: Path,
    *,
    claim: coordination_claims.ClaimRecord,
) -> tuple[OutcomePortfolioDispositionRequestV1, str, str]:
    content, reference = _claimed_file(path, claim=claim)
    try:
        request = OutcomePortfolioDispositionRequestV1.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomePortfolioError(
            "portfolio_disposition_request_invalid",
            f"portfolio disposition request is invalid: {exc}",
        ) from exc
    return request, hashlib.sha256(content).hexdigest(), reference


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = resolved.parent / f".{resolved.name}.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        lock_path.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _ledger_bytes(ledger: OutcomePortfolioLedgerV1) -> bytes:
    return (
        json.dumps(
            ledger.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")


def _active_allocations(
    ledger: OutcomePortfolioLedgerV1,
) -> dict[str, OutcomePortfolioAllocationV1]:
    allocations: dict[str, OutcomePortfolioAllocationV1] = {}
    allocation_digests: dict[str, str] = {}
    dispositions: set[str] = set()
    disposition_ids: set[str] = set()
    active_buckets: dict[str, str] = {}
    for record in ledger.records:
        if isinstance(record, OutcomePortfolioAllocationV1):
            if record.allocation_id in allocations:
                raise OutcomePortfolioError(
                    "portfolio_ledger_invalid",
                    f"duplicate allocation id {record.allocation_id!r}",
                )
            if record.bucket in active_buckets:
                raise OutcomePortfolioError(
                    "portfolio_ledger_invalid",
                    f"allocation history overbooks bucket {record.bucket!r}",
                )
            allocations[record.allocation_id] = record
            allocation_digests[record.allocation_id] = canonical_sha256(record)
            active_buckets[record.bucket] = record.allocation_id
            continue
        if record.disposition_id in disposition_ids:
            raise OutcomePortfolioError(
                "portfolio_ledger_invalid",
                f"duplicate disposition id {record.disposition_id!r}",
            )
        disposition_ids.add(record.disposition_id)
        allocation = allocations.get(record.allocation_id)
        if allocation is None:
            raise OutcomePortfolioError(
                "portfolio_ledger_invalid",
                f"disposition references unknown allocation {record.allocation_id!r}",
            )
        if record.allocation_id in dispositions:
            raise OutcomePortfolioError(
                "portfolio_ledger_invalid",
                f"allocation {record.allocation_id!r} has multiple dispositions",
            )
        if record.allocation_sha256 != allocation_digests[record.allocation_id]:
            raise OutcomePortfolioError(
                "portfolio_ledger_invalid",
                f"disposition digest does not match allocation {record.allocation_id!r}",
            )
        dispositions.add(record.allocation_id)
        active_buckets.pop(allocation.bucket, None)
    return {
        allocation_id: allocation
        for allocation_id, allocation in allocations.items()
        if allocation_id not in dispositions
    }


def load_outcome_portfolio_ledger(path: Path) -> OutcomePortfolioLedgerV1:
    """Load and validate the complete event history, or return an empty ledger."""

    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return OutcomePortfolioLedgerV1()
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise OutcomePortfolioError(
            "portfolio_ledger_unavailable",
            f"unable to read portfolio ledger: {exc}",
        ) from exc
    try:
        ledger = OutcomePortfolioLedgerV1.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomePortfolioError(
            "portfolio_ledger_invalid",
            f"portfolio ledger is invalid: {exc}",
        ) from exc
    _active_allocations(ledger)
    return ledger


def _write_ledger(path: Path, ledger: OutcomePortfolioLedgerV1) -> bytes:
    resolved = path.expanduser().resolve()
    content = _ledger_bytes(ledger)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
        directory = os.open(resolved.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return content


def _allocation_candidate(
    *,
    allocated_at: datetime,
    scenario: OutcomeContinuationScenarioV1,
    scenario_file_sha256: str,
    scenario_ref: str,
    request: OutcomePortfolioAllocationRequestV1,
    request_file_sha256: str,
    request_ref: str,
    authority: ProjectGraphOutcomeAuthorityV1,
    claim: coordination_claims.ClaimRecord,
) -> OutcomePortfolioAllocationV1:
    try:
        result = evaluate_scenario(scenario)
    except ContinuationError as exc:
        raise OutcomePortfolioError(
            "portfolio_scenario_evaluation_failed",
            f"portfolio scenario cannot be evaluated: {exc}",
        ) from exc
    contract = scenario.contract
    if contract.schema_version not in {"1.1.0", "1.2.0"} or contract.portfolio_class is None:
        raise OutcomePortfolioError(
            "portfolio_class_required",
            "portfolio allocation requires a class-bearing outcome contract",
        )
    if contract.project_id != claim.primary_project():
        raise OutcomePortfolioError(
            "project_mismatch",
            "portfolio scenario project does not equal the exact claim project",
        )
    if contract.project_id != authority.project_id:
        raise OutcomePortfolioError(
            "project_graph_project_mismatch",
            "portfolio scenario project does not equal Project Graph authority",
        )
    if contract.owner_class != authority.owner_class:
        raise OutcomePortfolioError(
            "project_owner_mismatch",
            "outcome owner_class does not equal reviewed Project Graph authority",
        )
    expected: dict[str, tuple[Any, Any]] = {
        "project_id": (request.project_id, contract.project_id),
        "scenario_id": (request.scenario_id, scenario.scenario_id),
        "outcome_contract_sha256": (
            request.outcome_contract_sha256,
            result.outcome_contract_sha256,
        ),
        "outcome_id": (request.outcome_id, contract.outcome_id),
        "outcome_lineage_id": (request.outcome_lineage_id, contract.lineage_id),
        "portfolio_class": (request.portfolio_class, contract.portfolio_class),
    }
    mismatches = [name for name, (actual, wanted) in expected.items() if actual != wanted]
    if mismatches:
        raise OutcomePortfolioError(
            "portfolio_allocation_request_mismatch",
            "allocation request does not match the exact scenario: " + ", ".join(mismatches),
        )
    claim_binding = _claim_binding(claim)
    return OutcomePortfolioAllocationV1(
        allocated_at=allocated_at,
        allocation_id=request.allocation_id,
        bucket=portfolio_bucket(contract.portfolio_class, authority.owner_class),
        portfolio_class=contract.portfolio_class,
        owner_class=authority.owner_class,
        project_id=contract.project_id,
        outcome_id=contract.outcome_id,
        outcome_lineage_id=contract.lineage_id,
        scenario_id=scenario.scenario_id,
        outcome_contract_sha256=result.outcome_contract_sha256,
        scenario_sha256=result.scenario_sha256,
        scenario_file_sha256=scenario_file_sha256,
        scenario_ref=scenario_ref,
        request=request,
        request_sha256=canonical_sha256(request),
        request_file_sha256=request_file_sha256,
        request_ref=request_ref,
        project_authority=authority,
        project_authority_sha256=canonical_sha256(authority),
        claim=claim_binding,
        claim_sha256=canonical_sha256(claim_binding),
    )


def allocate_outcome_portfolio(
    *,
    agent: str,
    project: str,
    scope: str,
    scenario_path: Path,
    request_path: Path,
    project_graph_repo: Path,
    project_graph_revision: str,
    session_id: str | None = None,
    claims_dir: Path | None = None,
    ledger_path: Path = DEFAULT_OUTCOME_PORTFOLIO_LEDGER_PATH,
) -> OutcomePortfolioAllocationResultV1:
    """Deliberately allocate one exact graph-backed portfolio slot."""

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise OutcomePortfolioError(
            "session_identity_unavailable",
            "portfolio allocation requires an explicit or native exact session ID",
        )
    coordination_claims.validate_native_session_binding(agent, resolved_session_id)
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    resolved_ledger = ledger_path.expanduser().resolve()
    with coordination_claims.claim_registry_lock(resolved_claims_dir):
        claim = _exact_live_claim(
            agent=agent,
            project=project,
            scope=scope,
            session_id=resolved_session_id,
            claims_dir=resolved_claims_dir,
        )
        scenario, scenario_file_sha256, scenario_ref = _load_scenario(
            scenario_path,
            claim=claim,
        )
        request, request_file_sha256, request_ref = _load_allocation_request(
            request_path,
            claim=claim,
        )
        authority = resolve_project_graph_authority(
            project_graph_repo=project_graph_repo,
            project_graph_revision=project_graph_revision,
            project_id=scenario.contract.project_id,
        )
        with _ledger_lock(resolved_ledger):
            ledger = load_outcome_portfolio_ledger(resolved_ledger)
            active = _active_allocations(ledger)
            existing = next(
                (
                    record
                    for record in ledger.records
                    if isinstance(record, OutcomePortfolioAllocationV1)
                    and record.allocation_id == request.allocation_id
                ),
                None,
            )
            candidate = _allocation_candidate(
                allocated_at=existing.allocated_at if existing else datetime.now(UTC),
                scenario=scenario,
                scenario_file_sha256=scenario_file_sha256,
                scenario_ref=scenario_ref,
                request=request,
                request_file_sha256=request_file_sha256,
                request_ref=request_ref,
                authority=authority,
                claim=claim,
            )
            if existing is not None:
                if canonical_sha256(existing) != canonical_sha256(candidate):
                    raise OutcomePortfolioError(
                        "portfolio_allocation_conflict",
                        "allocation id already exists with different exact inputs",
                    )
                if existing.allocation_id not in active:
                    raise OutcomePortfolioError(
                        "portfolio_allocation_inactive",
                        "the exact allocation was already parked or completed",
                    )
                content = _ledger_bytes(ledger)
                status: Literal["allocated", "idempotent"] = "idempotent"
                allocation = existing
            else:
                occupying = next(
                    (allocation for allocation in active.values() if allocation.bucket == candidate.bucket),
                    None,
                )
                if occupying is not None:
                    code = (
                        "portfolio_product_slot_occupied"
                        if candidate.portfolio_class == "product"
                        else "portfolio_global_slot_occupied"
                    )
                    raise OutcomePortfolioError(
                        code,
                        f"bucket {candidate.bucket!r} is occupied by allocation {occupying.allocation_id!r}",
                    )
                allocation = candidate
                ledger = ledger.model_copy(update={"records": (*ledger.records, allocation)})
                _active_allocations(ledger)
                content = _write_ledger(resolved_ledger, ledger)
                status = "allocated"
    return OutcomePortfolioAllocationResultV1(
        status=status,
        allocation=allocation,
        allocation_sha256=canonical_sha256(allocation),
        ledger_sha256=hashlib.sha256(content).hexdigest(),
        ledger_path=str(resolved_ledger),
    )


def dispose_outcome_portfolio_allocation(
    *,
    agent: str,
    project: str,
    scope: str,
    request_path: Path,
    session_id: str | None = None,
    claims_dir: Path | None = None,
    ledger_path: Path = DEFAULT_OUTCOME_PORTFOLIO_LEDGER_PATH,
) -> OutcomePortfolioDispositionResultV1:
    """Append one exact disposition and release its bucket."""

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise OutcomePortfolioError(
            "session_identity_unavailable",
            "portfolio disposition requires an explicit or native exact session ID",
        )
    coordination_claims.validate_native_session_binding(agent, resolved_session_id)
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    resolved_ledger = ledger_path.expanduser().resolve()
    with coordination_claims.claim_registry_lock(resolved_claims_dir):
        claim = _exact_live_claim(
            agent=agent,
            project=project,
            scope=scope,
            session_id=resolved_session_id,
            claims_dir=resolved_claims_dir,
        )
        request, request_file_sha256, request_ref = _load_disposition_request(
            request_path,
            claim=claim,
        )
        claim_binding = _claim_binding(claim)
        with _ledger_lock(resolved_ledger):
            ledger = load_outcome_portfolio_ledger(resolved_ledger)
            allocations = {
                record.allocation_id: record
                for record in ledger.records
                if isinstance(record, OutcomePortfolioAllocationV1)
            }
            allocation = allocations.get(request.allocation_id)
            if allocation is None:
                raise OutcomePortfolioError(
                    "portfolio_allocation_missing",
                    f"allocation {request.allocation_id!r} does not exist",
                )
            if allocation.project_id != claim.primary_project():
                raise OutcomePortfolioError(
                    "project_mismatch",
                    "disposition claim project does not equal the allocation project",
                )
            allocation_sha256 = canonical_sha256(allocation)
            if request.allocation_sha256 != allocation_sha256:
                raise OutcomePortfolioError(
                    "portfolio_disposition_request_mismatch",
                    "disposition request does not bind the exact allocation digest",
                )
            existing = next(
                (
                    record
                    for record in ledger.records
                    if isinstance(record, OutcomePortfolioDispositionV1)
                    and record.disposition_id == request.disposition_id
                ),
                None,
            )
            candidate = OutcomePortfolioDispositionV1(
                recorded_at=existing.recorded_at if existing else datetime.now(UTC),
                disposition_id=request.disposition_id,
                allocation_id=request.allocation_id,
                allocation_sha256=request.allocation_sha256,
                disposition=request.disposition,
                request=request,
                request_sha256=canonical_sha256(request),
                request_file_sha256=request_file_sha256,
                request_ref=request_ref,
                claim=claim_binding,
                claim_sha256=canonical_sha256(claim_binding),
            )
            if existing is not None:
                if canonical_sha256(existing) != canonical_sha256(candidate):
                    raise OutcomePortfolioError(
                        "portfolio_disposition_conflict",
                        "disposition id already exists with different exact inputs",
                    )
                content = _ledger_bytes(ledger)
                status: Literal["recorded", "idempotent"] = "idempotent"
                disposition = existing
            else:
                active = _active_allocations(ledger)
                if request.allocation_id not in active:
                    raise OutcomePortfolioError(
                        "portfolio_allocation_already_disposed",
                        "allocation already has an append-only disposition",
                    )
                disposition = candidate
                ledger = ledger.model_copy(update={"records": (*ledger.records, disposition)})
                _active_allocations(ledger)
                content = _write_ledger(resolved_ledger, ledger)
                status = "recorded"
    return OutcomePortfolioDispositionResultV1(
        status=status,
        disposition=disposition,
        disposition_sha256=canonical_sha256(disposition),
        ledger_sha256=hashlib.sha256(content).hexdigest(),
        ledger_path=str(resolved_ledger),
    )


def require_active_portfolio_allocation(
    scenario: OutcomeContinuationScenarioV1,
    *,
    ledger_path: Path = DEFAULT_OUTCOME_PORTFOLIO_LEDGER_PATH,
) -> ResolvedOutcomePortfolioAllocationV1 | None:
    """Require the unique exact active allocation for a classed scenario.

    Legacy schema-1.0 scenarios remain readable and return ``None``.  They are
    deliberately not portfolio-admitted evidence.
    """

    if scenario.contract.schema_version == "1.0.0":
        return None
    if scenario.contract.portfolio_class is None:
        raise OutcomePortfolioError(
            "portfolio_class_required",
            "classed selection requires an explicit portfolio class",
        )
    try:
        result = evaluate_scenario(scenario)
    except ContinuationError as exc:
        raise OutcomePortfolioError(
            "portfolio_scenario_evaluation_failed",
            f"classed scenario cannot be evaluated: {exc}",
        ) from exc
    resolved_ledger = ledger_path.expanduser().resolve()
    with _ledger_lock(resolved_ledger):
        ledger = load_outcome_portfolio_ledger(resolved_ledger)
        active = _active_allocations(ledger)
        matches = [
            allocation
            for allocation in active.values()
            if allocation.project_id == scenario.contract.project_id
            and allocation.outcome_contract_sha256 == result.outcome_contract_sha256
            and allocation.scenario_sha256 == result.scenario_sha256
            and allocation.portfolio_class == scenario.contract.portfolio_class
            and allocation.outcome_id == scenario.contract.outcome_id
            and allocation.outcome_lineage_id == scenario.contract.lineage_id
        ]
        if not matches:
            all_matching = [
                record
                for record in ledger.records
                if isinstance(record, OutcomePortfolioAllocationV1)
                and record.project_id == scenario.contract.project_id
                and record.outcome_contract_sha256 == result.outcome_contract_sha256
                and record.scenario_sha256 == result.scenario_sha256
            ]
            code = "portfolio_allocation_inactive" if all_matching else "portfolio_allocation_required"
            raise OutcomePortfolioError(
                code,
                "classed selection requires one exact active portfolio allocation",
            )
        if len(matches) != 1:
            raise OutcomePortfolioError(
                "portfolio_ledger_invalid",
                "classed scenario resolves to multiple active allocations",
            )
        allocation = matches[0]
        current_authority = resolve_project_graph_authority(
            project_graph_repo=Path(allocation.project_authority.project_graph_repo),
            project_graph_revision=allocation.project_authority.project_graph_revision,
            project_id=allocation.project_id,
        )
        if canonical_sha256(current_authority) != allocation.project_authority_sha256:
            raise OutcomePortfolioError(
                "project_graph_authority_stale",
                "active allocation no longer matches its exact Project Graph authority",
            )
        content = _ledger_bytes(ledger)
    return ResolvedOutcomePortfolioAllocationV1(
        allocation=allocation,
        allocation_sha256=canonical_sha256(allocation),
        ledger_sha256=hashlib.sha256(content).hexdigest(),
        ledger_path=str(resolved_ledger),
    )


__all__ = [
    "DEFAULT_OUTCOME_PORTFOLIO_LEDGER_PATH",
    "GLOBAL_NON_PRODUCT_BUCKET",
    "OutcomePortfolioAllocationRequestV1",
    "OutcomePortfolioAllocationResultV1",
    "OutcomePortfolioAllocationV1",
    "OutcomePortfolioDispositionRequestV1",
    "OutcomePortfolioDispositionResultV1",
    "OutcomePortfolioDispositionV1",
    "OutcomePortfolioError",
    "OutcomePortfolioLedgerV1",
    "ProjectGraphOutcomeAuthorityV1",
    "ResolvedOutcomePortfolioAllocationV1",
    "allocate_outcome_portfolio",
    "dispose_outcome_portfolio_allocation",
    "load_outcome_portfolio_ledger",
    "portfolio_bucket",
    "require_active_portfolio_allocation",
    "resolve_project_graph_authority",
]
