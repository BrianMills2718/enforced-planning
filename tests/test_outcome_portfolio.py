from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    CanonicalJourneyV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeCriterionV1,
    PortfolioClass,
    canonical_sha256,
)
from enforced_planning.outcome_portfolio import (
    OutcomePortfolioAllocationRequestV1,
    OutcomePortfolioDispositionRequestV1,
    OutcomePortfolioError,
    allocate_outcome_portfolio,
    dispose_outcome_portfolio_allocation,
    require_active_portfolio_allocation,
    resolve_project_graph_authority,
)

SESSION = "codex:portfolio-test"
TARGET = "docs/evidence/plan120.json"
ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _graph_record(
    project_id: str,
    *,
    owner_class: str = "brian",
    status: str = "active",
    record_kind: str = "repository",
    reviewed: bool = True,
    supersedes: list[str] | None = None,
) -> dict[str, Any]:
    governance: dict[str, Any] = {
        "owner_class": owner_class,
        "approved_remote_owners": ["BrianMills2718"],
        "mutation_authority": "normal_push",
        "publication_authority": "recoverable_git",
    }
    if reviewed:
        governance["review"] = {
            "reviewed_by": "Brian Mills",
            "reviewed_at": "2026-08-21",
            "evidence": ["Approved test repository governance."],
        }
    return {
        "id": project_id,
        "record_kind": record_kind,
        "status": status,
        "repository_governance": governance,
        "supersedes": supersedes or [],
    }


def _graph_repo(tmp_path: Path, records: list[dict[str, Any]]) -> tuple[Path, str]:
    repo = tmp_path / "project-meta"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "PROJECT_GRAPH.json").write_text(
        json.dumps(records, indent=2) + "\n",
        encoding="utf-8",
    )
    _git(repo, "add", "PROJECT_GRAPH.json")
    _git(repo, "commit", "-m", "graph")
    return repo, _git(repo, "rev-parse", "HEAD")


def _scenario(
    project_id: str,
    *,
    portfolio_class: PortfolioClass = "maintenance",
    owner_class: str = "brian",
    outcome_id: str | None = None,
    scenario_id: str | None = None,
    schema_version: str = "1.1.0",
) -> OutcomeContinuationScenarioV1:
    outcome_id = outcome_id or f"{project_id}-outcome"
    contract = OutcomeContractV1(
        schema_version=schema_version,
        portfolio_class=portfolio_class,
        outcome_id=outcome_id,
        owner_class=owner_class,
        project_id=project_id,
        lineage_id=f"{outcome_id}-lineage",
        intended_consumer="Brian and his coding agents",
        outcome="One deliberately allocated outcome reaches its user-visible result.",
        canonical_journey=CanonicalJourneyV1(
            starting_state="One exact claimed repository has no portfolio allocation.",
            input="One classed immutable outcome scenario.",
            action="Allocate it explicitly before selecting it.",
            observable_result="The selected outcome retains one exact active allocation.",
            failure_signal="Selection succeeds without an explicit active allocation.",
        ),
        baseline_revision="a" * 40,
        allowed_scope=[TARGET],
        progress_dimensions=["portfolio-bound outcome admission"],
        success_criteria=(
            [
                OutcomeCriterionV1(
                    criterion_id="visible-outcome",
                    description="The exact user-visible outcome is independently evidenced.",
                )
            ]
            if schema_version == "1.2.0"
            else []
        ),
    )
    return OutcomeContinuationScenarioV1(
        scenario_id=scenario_id or f"{project_id}-{portfolio_class.replace('_', '-')}-scenario",
        contract=contract,
        request=AdmissionRequestV1(operation="product_write", target_path=TARGET),
    )


def _claimed_inputs(
    tmp_path: Path,
    *,
    project_id: str,
    scenario: OutcomeContinuationScenarioV1,
    claims_dir: Path,
    allocation_id: str | None = None,
) -> tuple[Path, Path, Path]:
    repo = tmp_path / f"repo-{project_id}"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = tmp_path / f"worktree-{project_id}"
    _git(repo, "worktree", "add", "-b", f"test-{project_id}", str(worktree))
    inputs = worktree / "portfolio"
    inputs.mkdir()
    scenario_path = inputs / "scenario.json"
    scenario_path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")
    portfolio_class = scenario.contract.portfolio_class
    assert portfolio_class is not None
    request = OutcomePortfolioAllocationRequestV1(
        allocation_id=allocation_id or f"allocate-{project_id}",
        requested_at=datetime(2026, 8, 21, 8, tzinfo=UTC),
        project_id=project_id,
        scenario_id=scenario.scenario_id,
        outcome_contract_sha256=canonical_sha256(scenario.contract),
        outcome_id=scenario.contract.outcome_id,
        outcome_lineage_id=scenario.contract.lineage_id,
        portfolio_class=portfolio_class,
        decision_ref=f"decision:{project_id}",
        purpose="Exercise deliberate graph-bound portfolio admission.",
        stopping_condition="Stop when the exact slot is parked or completed.",
    )
    request_path = inputs / "allocation.json"
    request_path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tracker_path = tmp_path / f"tracker-{project_id}.yaml"
    tracker_path.write_text("tracker: {}\n", encoding="utf-8")
    claims_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    claim = {
        "schema_version": 3,
        "agent": "codex",
        "claimed_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "projects": [project_id],
        "scope": f"scope-{project_id}",
        "intent": "exercise graph-bound portfolio admission",
        "claim_type": "program",
        "write_paths": ["portfolio/scenario.json", "portfolio/allocation.json"],
        "read_paths": [],
        "repo_root": str(repo),
        "worktree_path": str(worktree),
        "branch": f"test-{project_id}",
        "session_id": SESSION,
        "session_name": f"portfolio-{project_id}",
        "broader_goal": f"Allocate {project_id} outcome",
        "tracker_path": str(tracker_path),
        "heartbeat_at": now.isoformat(),
        "status": "active",
        "updated_at": now.isoformat(),
        "plan_ref": f"goal:{scenario.contract.outcome_id}",
    }
    claim_path = claims_dir / f"codex_{project_id}_scope-{project_id}.yaml"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    return worktree, scenario_path, request_path


def _allocate(
    *,
    project_id: str,
    scenario_path: Path,
    request_path: Path,
    graph_repo: Path,
    graph_revision: str,
    claims_dir: Path,
    ledger_path: Path,
):
    return allocate_outcome_portfolio(
        agent="codex",
        project=project_id,
        scope=f"scope-{project_id}",
        session_id=SESSION,
        scenario_path=scenario_path,
        request_path=request_path,
        project_graph_repo=graph_repo,
        project_graph_revision=graph_revision,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )


def test_project_graph_authority_is_exact_reviewed_and_lineage_bound(tmp_path: Path) -> None:
    graph_repo, revision = _graph_repo(
        tmp_path,
        [_graph_record("successor", supersedes=["predecessor"])],
    )

    authority = resolve_project_graph_authority(
        project_graph_repo=graph_repo,
        project_graph_revision=revision,
        project_id="successor",
    )

    assert authority.owner_class == "brian"
    assert authority.predecessor_project_ids == ("predecessor",)
    expected_file_sha = hashlib.sha256((graph_repo / "PROJECT_GRAPH.json").read_bytes()).hexdigest()
    assert authority.project_graph_file_sha256 == expected_file_sha
    with pytest.raises(OutcomePortfolioError) as exc_info:
        resolve_project_graph_authority(
            project_graph_repo=graph_repo,
            project_graph_revision=revision[:12],
            project_id="successor",
        )
    assert exc_info.value.code == "project_graph_revision_not_exact"
    with pytest.raises(OutcomePortfolioError) as exc_info:
        resolve_project_graph_authority(
            project_graph_repo=graph_repo,
            project_graph_revision=revision,
            project_id="missing",
        )
    assert exc_info.value.code == "project_unregistered"


@pytest.mark.parametrize(
    ("record", "code"),
    [
        (_graph_record("project", status="parked"), "project_inactive"),
        (_graph_record("project", record_kind="pointer"), "project_not_repository"),
        (_graph_record("project", reviewed=False), "repository_governance_unreviewed"),
    ],
)
def test_project_graph_authority_rejects_ineligible_records(
    tmp_path: Path,
    record: dict[str, Any],
    code: str,
) -> None:
    graph_repo, revision = _graph_repo(tmp_path, [record])

    with pytest.raises(OutcomePortfolioError) as exc_info:
        resolve_project_graph_authority(
            project_graph_repo=graph_repo,
            project_graph_revision=revision,
            project_id="project",
        )

    assert exc_info.value.code == code


def test_underscore_project_id_allocates_and_resolves_through_portfolio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "portfolio-test")
    project_id = "qualitative_coding"
    graph_repo, revision = _graph_repo(tmp_path, [_graph_record(project_id)])
    claims_dir = tmp_path / "claims"
    ledger_path = tmp_path / "portfolio-ledger.json"
    scenario = _scenario(
        project_id,
        outcome_id="qualitative-coding-outcome",
        scenario_id="qualitative-coding-maintenance-scenario",
    )
    _worktree, scenario_path, request_path = _claimed_inputs(
        tmp_path,
        project_id=project_id,
        scenario=scenario,
        claims_dir=claims_dir,
        allocation_id="allocate-qualitative-coding",
    )

    allocated = _allocate(
        project_id=project_id,
        scenario_path=scenario_path,
        request_path=request_path,
        graph_repo=graph_repo,
        graph_revision=revision,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )
    resolved = require_active_portfolio_allocation(scenario, ledger_path=ledger_path)

    assert allocated.status == "allocated"
    assert allocated.allocation.project_id == project_id
    assert allocated.allocation.project_authority.project_id == project_id
    assert resolved.allocation_sha256 == allocated.allocation_sha256


def test_criterion_bound_contract_allocates_through_existing_portfolio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "portfolio-test")
    project_id = "enforced-planning"
    graph_repo, revision = _graph_repo(tmp_path, [_graph_record(project_id)])
    claims_dir = tmp_path / "claims"
    ledger_path = tmp_path / "portfolio-ledger.json"
    scenario = _scenario(project_id, schema_version="1.2.0")
    _worktree, scenario_path, request_path = _claimed_inputs(
        tmp_path,
        project_id=project_id,
        scenario=scenario,
        claims_dir=claims_dir,
    )

    allocated = _allocate(
        project_id=project_id,
        scenario_path=scenario_path,
        request_path=request_path,
        graph_repo=graph_repo,
        graph_revision=revision,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )

    assert allocated.status == "allocated"
    assert allocated.allocation.outcome_contract_sha256 == canonical_sha256(scenario.contract)


@pytest.mark.parametrize("terminal_status", ["complete", "completed", "COMPLETED"])
def test_allocation_ignores_malformed_completed_claim_debris(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal_status: str,
) -> None:
    """A historical terminal record cannot deny an unrelated live allocation."""

    monkeypatch.setenv("CODEX_THREAD_ID", "portfolio-test")
    project_id = "enforced-planning"
    graph_repo, revision = _graph_repo(tmp_path, [_graph_record(project_id)])
    claims_dir = tmp_path / "claims"
    ledger_path = tmp_path / "portfolio-ledger.json"
    scenario = _scenario(project_id)
    _, scenario_path, request_path = _claimed_inputs(
        tmp_path,
        project_id=project_id,
        scenario=scenario,
        claims_dir=claims_dir,
    )
    (claims_dir / "legacy-completed.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "status": terminal_status,
                "claim_type": "write",
                "branch": "historical-branch",
                "write_paths": ["historical.py"],
                "notes": "Merged before strict claim identity was required.",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    allocated = _allocate(
        project_id=project_id,
        scenario_path=scenario_path,
        request_path=request_path,
        graph_repo=graph_repo,
        graph_revision=revision,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )

    assert allocated.status == "allocated"


@pytest.mark.parametrize("unsafe_status", [None, "active", "archived"])
def test_allocation_fails_closed_on_malformed_noncompleted_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_status: str | None,
) -> None:
    """Only the two canonical completed statuses may bypass normalization."""

    monkeypatch.setenv("CODEX_THREAD_ID", "portfolio-test")
    project_id = "enforced-planning"
    graph_repo, revision = _graph_repo(tmp_path, [_graph_record(project_id)])
    claims_dir = tmp_path / "claims"
    ledger_path = tmp_path / "portfolio-ledger.json"
    scenario = _scenario(project_id)
    _, scenario_path, request_path = _claimed_inputs(
        tmp_path,
        project_id=project_id,
        scenario=scenario,
        claims_dir=claims_dir,
    )
    malformed: dict[str, Any] = {"schema_version": 3, "claim_type": "write"}
    if unsafe_status is not None:
        malformed["status"] = unsafe_status
    (claims_dir / "malformed.yaml").write_text(
        yaml.safe_dump(malformed, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(OutcomePortfolioError) as exc_info:
        _allocate(
            project_id=project_id,
            scenario_path=scenario_path,
            request_path=request_path,
            graph_repo=graph_repo,
            graph_revision=revision,
            claims_dir=claims_dir,
            ledger_path=ledger_path,
        )

    assert exc_info.value.code == "claim_registry_invalid"
    assert not ledger_path.exists()


def test_allocation_and_disposition_are_append_only_and_byte_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "portfolio-test")
    project_id = "enforced-planning"
    graph_repo, revision = _graph_repo(tmp_path, [_graph_record(project_id)])
    claims_dir = tmp_path / "claims"
    ledger_path = tmp_path / "portfolio-ledger.json"
    scenario = _scenario(project_id)
    worktree, scenario_path, request_path = _claimed_inputs(
        tmp_path,
        project_id=project_id,
        scenario=scenario,
        claims_dir=claims_dir,
    )

    allocated = _allocate(
        project_id=project_id,
        scenario_path=scenario_path,
        request_path=request_path,
        graph_repo=graph_repo,
        graph_revision=revision,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )
    allocation_bytes = ledger_path.read_bytes()
    replay = _allocate(
        project_id=project_id,
        scenario_path=scenario_path,
        request_path=request_path,
        graph_repo=graph_repo,
        graph_revision=revision,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )

    assert allocated.status == "allocated"
    assert replay.status == "idempotent"
    assert replay.allocation_sha256 == allocated.allocation_sha256
    assert ledger_path.read_bytes() == allocation_bytes
    resolved = require_active_portfolio_allocation(scenario, ledger_path=ledger_path)
    assert resolved is not None
    assert resolved.allocation_sha256 == allocated.allocation_sha256

    disposition_request = OutcomePortfolioDispositionRequestV1(
        disposition_id="park-enforced-planning",
        requested_at=datetime(2026, 8, 21, 8, 5, tzinfo=UTC),
        allocation_id=allocated.allocation.allocation_id,
        allocation_sha256=allocated.allocation_sha256,
        disposition="parked",
        decision_ref="decision:park-plan120",
        reason="Release the bounded maintenance slot after the authentic journey.",
    )
    disposition_path = worktree / "portfolio" / "disposition.json"
    disposition_path.write_text(
        disposition_request.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    disposed = dispose_outcome_portfolio_allocation(
        agent="codex",
        project=project_id,
        scope=f"scope-{project_id}",
        session_id=SESSION,
        request_path=disposition_path,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )
    disposition_bytes = ledger_path.read_bytes()
    disposed_replay = dispose_outcome_portfolio_allocation(
        agent="codex",
        project=project_id,
        scope=f"scope-{project_id}",
        session_id=SESSION,
        request_path=disposition_path,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )

    assert disposed.status == "recorded"
    assert disposed_replay.status == "idempotent"
    assert ledger_path.read_bytes() == disposition_bytes
    with pytest.raises(OutcomePortfolioError) as exc_info:
        require_active_portfolio_allocation(scenario, ledger_path=ledger_path)
    assert exc_info.value.code == "portfolio_allocation_inactive"

    changed_disposition = disposition_request.model_copy(
        update={"reason": "Changing an accepted disposition must fail without rewriting history."}
    )
    disposition_path.write_text(
        changed_disposition.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(OutcomePortfolioError) as exc_info:
        dispose_outcome_portfolio_allocation(
            agent="codex",
            project=project_id,
            scope=f"scope-{project_id}",
            session_id=SESSION,
            request_path=disposition_path,
            claims_dir=claims_dir,
            ledger_path=ledger_path,
        )
    assert exc_info.value.code == "portfolio_disposition_conflict"
    assert ledger_path.read_bytes() == disposition_bytes

    second_disposition = disposition_request.model_copy(
        update={
            "disposition_id": "complete-enforced-planning",
            "disposition": "complete",
            "reason": "A second disposition cannot overwrite the accepted parking event.",
        }
    )
    disposition_path.write_text(
        second_disposition.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(OutcomePortfolioError) as exc_info:
        dispose_outcome_portfolio_allocation(
            agent="codex",
            project=project_id,
            scope=f"scope-{project_id}",
            session_id=SESSION,
            request_path=disposition_path,
            claims_dir=claims_dir,
            ledger_path=ledger_path,
        )
    assert exc_info.value.code == "portfolio_allocation_already_disposed"
    assert ledger_path.read_bytes() == disposition_bytes


def test_product_owner_and_global_non_product_caps_are_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "portfolio-test")
    records = [
        _graph_record("product-one"),
        _graph_record("product-two"),
        _graph_record("other-product", owner_class="other"),
        _graph_record("maintenance"),
        _graph_record("external"),
    ]
    graph_repo, revision = _graph_repo(tmp_path, records)
    claims_dir = tmp_path / "claims"
    ledger_path = tmp_path / "portfolio-ledger.json"
    inputs: dict[str, tuple[Path, Path]] = {}
    cases: tuple[tuple[str, PortfolioClass, str], ...] = (
        ("product-one", "product", "brian"),
        ("product-two", "product", "brian"),
        ("other-product", "product", "other"),
        ("maintenance", "maintenance", "brian"),
        ("external", "external_obligation", "brian"),
    )
    for project_id, portfolio_class, owner_class in cases:
        scenario = _scenario(
            project_id,
            portfolio_class=portfolio_class,
            owner_class=owner_class,
        )
        _, scenario_path, request_path = _claimed_inputs(
            tmp_path,
            project_id=project_id,
            scenario=scenario,
            claims_dir=claims_dir,
        )
        inputs[project_id] = (scenario_path, request_path)

    def allocate(project_id: str):
        scenario_path, request_path = inputs[project_id]
        return _allocate(
            project_id=project_id,
            scenario_path=scenario_path,
            request_path=request_path,
            graph_repo=graph_repo,
            graph_revision=revision,
            claims_dir=claims_dir,
            ledger_path=ledger_path,
        )

    assert allocate("product-one").status == "allocated"
    with pytest.raises(OutcomePortfolioError) as exc_info:
        allocate("product-two")
    assert exc_info.value.code == "portfolio_product_slot_occupied"
    assert allocate("other-product").status == "allocated"
    assert allocate("maintenance").status == "allocated"
    with pytest.raises(OutcomePortfolioError) as exc_info:
        allocate("external")
    assert exc_info.value.code == "portfolio_global_slot_occupied"


def test_owner_and_changed_request_tamper_fail_without_ledger_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "portfolio-test")
    graph_repo, revision = _graph_repo(tmp_path, [_graph_record("project")])
    claims_dir = tmp_path / "claims"
    ledger_path = tmp_path / "portfolio-ledger.json"
    wrong_owner = _scenario("project", owner_class="caller-chosen-owner")
    _, wrong_scenario_path, wrong_request_path = _claimed_inputs(
        tmp_path,
        project_id="project",
        scenario=wrong_owner,
        claims_dir=claims_dir,
    )
    with pytest.raises(OutcomePortfolioError) as exc_info:
        _allocate(
            project_id="project",
            scenario_path=wrong_scenario_path,
            request_path=wrong_request_path,
            graph_repo=graph_repo,
            graph_revision=revision,
            claims_dir=claims_dir,
            ledger_path=ledger_path,
        )
    assert exc_info.value.code == "project_owner_mismatch"
    assert not ledger_path.exists()

    scenario = _scenario("project")
    scenario_path = wrong_scenario_path
    request_path = wrong_request_path
    scenario_path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")
    request = OutcomePortfolioAllocationRequestV1(
        allocation_id="allocate-project",
        requested_at=datetime(2026, 8, 21, 8, tzinfo=UTC),
        project_id="project",
        scenario_id=scenario.scenario_id,
        outcome_contract_sha256=canonical_sha256(scenario.contract),
        outcome_id=scenario.contract.outcome_id,
        outcome_lineage_id=scenario.contract.lineage_id,
        portfolio_class="maintenance",
        decision_ref="decision:project",
        purpose="Exercise deliberate graph-bound portfolio admission.",
        stopping_condition="Stop when the exact slot is parked or completed.",
    )
    request_path.write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
    allocated = _allocate(
        project_id="project",
        scenario_path=scenario_path,
        request_path=request_path,
        graph_repo=graph_repo,
        graph_revision=revision,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )
    before = ledger_path.read_bytes()
    changed = request.model_copy(update={"purpose": "A changed purpose must not replay."})
    request_path.write_text(changed.model_dump_json(indent=2) + "\n", encoding="utf-8")

    with pytest.raises(OutcomePortfolioError) as exc_info:
        _allocate(
            project_id="project",
            scenario_path=scenario_path,
            request_path=request_path,
            graph_repo=graph_repo,
            graph_revision=revision,
            claims_dir=claims_dir,
            ledger_path=ledger_path,
        )

    assert allocated.status == "allocated"
    assert exc_info.value.code == "portfolio_allocation_conflict"
    assert ledger_path.read_bytes() == before


def test_portfolio_cli_emits_machine_readable_allocation_and_disposition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "portfolio-test")
    project_id = "enforced-planning"
    graph_repo, revision = _graph_repo(tmp_path, [_graph_record(project_id)])
    claims_dir = tmp_path / "claims"
    ledger_path = tmp_path / "portfolio-ledger.json"
    scenario = _scenario(project_id)
    worktree, scenario_path, request_path = _claimed_inputs(
        tmp_path,
        project_id=project_id,
        scenario=scenario,
        claims_dir=claims_dir,
    )

    allocation_run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "outcome_continuation.py"),
            "allocate",
            "--scenario",
            str(scenario_path),
            "--request",
            str(request_path),
            "--project-graph-repo",
            str(graph_repo),
            "--project-graph-revision",
            revision,
            "--agent",
            "codex",
            "--project",
            project_id,
            "--scope",
            f"scope-{project_id}",
            "--session-id",
            SESSION,
            "--claims-dir",
            str(claims_dir),
            "--portfolio-ledger",
            str(ledger_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    allocation_payload = json.loads(allocation_run.stdout)
    assert allocation_payload["status"] == "allocated"

    disposition_request = OutcomePortfolioDispositionRequestV1(
        disposition_id="cli-park-enforced-planning",
        requested_at=datetime(2026, 8, 21, 8, 5, tzinfo=UTC),
        allocation_id=allocation_payload["allocation"]["allocation_id"],
        allocation_sha256=allocation_payload["allocation_sha256"],
        disposition="parked",
        decision_ref="decision:cli-park",
        reason="Release the CLI fixture allocation after observing its output.",
    )
    disposition_path = worktree / "portfolio" / "disposition.json"
    disposition_path.write_text(
        disposition_request.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    disposition_run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "outcome_continuation.py"),
            "dispose-allocation",
            "--request",
            str(disposition_path),
            "--agent",
            "codex",
            "--project",
            project_id,
            "--scope",
            f"scope-{project_id}",
            "--session-id",
            SESSION,
            "--claims-dir",
            str(claims_dir),
            "--portfolio-ledger",
            str(ledger_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    disposition_payload = json.loads(disposition_run.stdout)
    assert disposition_payload["status"] == "recorded"
    assert disposition_payload["disposition"]["disposition"] == "parked"
