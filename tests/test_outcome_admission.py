from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from enforced_planning import outcome_admission_evaluation
from enforced_planning.outcome_admission import (
    OutcomeAdmissionBootstrapV1,
    OutcomeAdmissionDecisionV1,
    OutcomeAdmissionRequestV1,
    decide_outcome_admission,
    evaluate_first_consumer_bootstrap,
    is_first_consumer_bootstrap_path,
)
from enforced_planning.outcome_admission_evaluation import (
    OutcomeAdmissionEvaluationSuiteV1,
    candidate_decision,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "outcome_admission" / "plan121_cases.json"
CLI = ROOT / "scripts" / "outcome_admission.py"


def _frozen_suite() -> OutcomeAdmissionEvaluationSuiteV1:
    return OutcomeAdmissionEvaluationSuiteV1.model_validate_json(
        CASES.read_text(encoding="utf-8")
    )


def test_production_decision_reproduces_every_frozen_plan121_case() -> None:
    mismatches: list[str] = []
    for case in _frozen_suite().cases:
        decision = decide_outcome_admission(
            OutcomeAdmissionRequestV1(
                boundary=case.boundary,
                enforcement_scope=case.enforcement_scope,
                ordinary_allowed=case.ordinary_allowed,
                portfolio_state=case.portfolio_state,
                continuation_state=case.continuation_state,
                bootstrap_product_write_requested=case.bootstrap_product_write_requested,
            )
        )
        if (
            decision.disposition != case.expected_disposition
            or decision.reason_code != case.expected_reason_code
        ):
            mismatches.append(case.case_id)

    assert mismatches == []


def test_plan121_candidate_delegates_to_production_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[OutcomeAdmissionRequestV1] = []

    def fake_decision(request: OutcomeAdmissionRequestV1) -> OutcomeAdmissionDecisionV1:
        captured.append(request)
        return OutcomeAdmissionDecisionV1(
            disposition="deny",
            reason_code="delegated-production-decision",
        )

    monkeypatch.setattr(
        outcome_admission_evaluation,
        "decide_outcome_admission",
        fake_decision,
    )
    case = _frozen_suite().cases[0]

    decision = candidate_decision(case)

    assert len(captured) == 1
    assert captured[0].boundary == case.boundary
    assert decision.reason_code == "delegated-production-decision"


def test_first_consumer_bootstrap_allows_only_exact_plan_and_shared_paths() -> None:
    paths = (
        "docs/plans/122_first_consumer_outcome_admission.md",
        "docs/plans/122_first_consumer_outcome_admission_work_graph.json",
        "examples/owner-real-outcome-admission/plan122-maintenance-scenario.json",
        "docs/plans/CLAUDE.md",
        "ROADMAP.md",
    )

    result = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(plan_number=122, write_paths=paths)
    )

    assert result.allowed_paths == paths
    assert result.rejected_paths == ()
    assert result.decision.disposition == "allow"
    assert result.decision.reason_code == "admission_bootstrap_allowed"


@pytest.mark.parametrize(
    "path",
    [
        "enforced_planning/outcome_admission.py",
        "scripts/outcome_admission.py",
        "tests/test_outcome_admission.py",
        "docs/evidence/plan122_first_consumer_outcome_admission.json",
        "docs/plans/121_outcome_admission_false_block_evaluation.md",
        "examples/owner-real-outcome-admission/plan121-foreign.json",
        "../docs/plans/122_escape.md",
        "/tmp/plan122.json",
        "docs//plans/122_wrong.md",
    ],
)
def test_first_consumer_bootstrap_rejects_product_foreign_and_unsafe_paths(
    path: str,
) -> None:
    result = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(
            plan_number=122,
            write_paths=(
                "docs/plans/122_first_consumer_outcome_admission.md",
                path,
            ),
        )
    )

    assert result.rejected_paths == (path,)
    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "admission_bootstrap_scope_violation"


def test_empty_bootstrap_is_denied() -> None:
    result = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(plan_number=122, write_paths=())
    )

    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "admission_bootstrap_scope_violation"


def test_ordinary_denial_precedes_bootstrap_scope_denial() -> None:
    result = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(
            plan_number=122,
            write_paths=("enforced_planning/outcome_admission.py",),
            ordinary_allowed=False,
        )
    )

    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "ordinary_authority_denied"


def test_safe_boundary_requires_safe_scope() -> None:
    with pytest.raises(ValidationError, match="safe boundaries require always_safe"):
        OutcomeAdmissionRequestV1(
            boundary="closeout",
            enforcement_scope="new_or_renewed",
            ordinary_allowed=True,
            portfolio_state="active_exact",
            continuation_state="active_in_scope",
        )


def test_bootstrap_path_classifier_is_plan_bound() -> None:
    assert is_first_consumer_bootstrap_path(
        "docs/plans/122_first_consumer_outcome_admission.md",
        plan_number=122,
    )
    assert not is_first_consumer_bootstrap_path(
        "docs/plans/122_first_consumer_outcome_admission.md",
        plan_number=123,
    )


def test_bootstrap_cli_allows_exact_scope() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "bootstrap",
            "--plan",
            "122",
            "--write-path",
            "docs/plans/122_first_consumer_outcome_admission.md",
            "--write-path",
            "examples/owner-real-outcome-admission/plan122-maintenance-scenario.json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["decision"]["reason_code"] == "admission_bootstrap_allowed"


def test_bootstrap_cli_denies_source_smuggling() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "bootstrap",
            "--plan",
            "122",
            "--write-path",
            "docs/plans/122_first_consumer_outcome_admission.md",
            "--write-path",
            "enforced_planning/outcome_admission.py",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["rejected_paths"] == ["enforced_planning/outcome_admission.py"]
    assert payload["decision"]["reason_code"] == "admission_bootstrap_scope_violation"
