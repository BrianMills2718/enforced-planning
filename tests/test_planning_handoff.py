"""Both-sign tests for the roadmap-to-design handoff transport contract."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from enforced_planning.planning_handoff import (
    CapabilityAdoptionBinding,
    EvidenceTarget,
    PlanningHandoffExchange,
    RoadmapGoalHandoff,
    canonical_record_sha256,
    load_exchange,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "planning_handoff"
VALID_FIXTURE = FIXTURE_DIR / "valid_exchange.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load one mapping fixture or fail the test with a useful assertion."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _set_path(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Apply one declared negative mutation without duplicating the base fixture."""

    parts = dotted_path.split(".")
    current: dict[str, Any] = payload
    for part in parts[:-1]:
        child = current.get(part)
        assert isinstance(child, dict), f"Fixture path {dotted_path!r} is not a mapping path"
        current = child
    current[parts[-1]] = value


def _negative_cases() -> list[dict[str, Any]]:
    """Return the machine-readable negative mutation cases."""

    raw = _load_yaml(FIXTURE_DIR / "negative_cases.yaml")
    cases = raw.get("cases")
    assert isinstance(cases, list)
    return cases


def test_valid_exchange_round_trips_without_becoming_status_authority() -> None:
    """The valid fixture should retain identity while exposing no mutable status field."""

    exchange = load_exchange(VALID_FIXTURE)
    encoded = exchange.model_dump(mode="json")
    round_tripped = PlanningHandoffExchange.model_validate(encoded)

    assert round_tripped == exchange
    assert exchange.result.source_handoff_sha256 == canonical_record_sha256(exchange.handoff)
    assert "current_status" not in type(exchange.handoff).model_fields
    assert "current_priority" not in type(exchange.result).model_fields


@pytest.mark.parametrize("case", _negative_cases(), ids=lambda case: str(case["case_id"]))
def test_negative_exchange_fixtures_fail_loud(case: dict[str, Any]) -> None:
    """Each declared goal, revision, authority, or concern defect must be rejected."""

    payload = copy.deepcopy(_load_yaml(VALID_FIXTURE))
    _set_path(payload, str(case["set_path"]), case["value"])

    with pytest.raises(ValidationError) as exc_info:
        PlanningHandoffExchange.model_validate(payload)

    assert str(case["expected_error"]) in str(exc_info.value)


def test_handoff_json_schema_is_closed_and_described() -> None:
    """Generated schema should reject extras and retain field descriptions for agents."""

    schema = RoadmapGoalHandoff.model_json_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["objective"]["description"]
    assert schema["properties"]["project_roadmap_ref"]["description"]


def test_required_capability_must_have_exact_adoption_binding() -> None:
    """A capability reference cannot remain disconnected from its consumer path."""

    payload = _load_yaml(VALID_FIXTURE)["handoff"]
    capability_ref = {
        "path": "docs/capabilities/person-contract.md",
        "revision": "abc123",
        "concern": "person construction",
    }
    payload["required_capability_refs"] = [capability_ref]

    with pytest.raises(ValidationError, match="capability_adoptions must exactly match"):
        RoadmapGoalHandoff.model_validate(payload)

    payload["capability_adoptions"] = [
        {
            "capability_ref": capability_ref,
            "disposition": "reuse",
            "canonical_seam": "authoring.live.build_live_bindings",
            "intended_consumer": "regional outbreak scenario",
            "adoption_proof": {
                "claim": "An authentic outbreak run records person_contract_v1 for every participant.",
                "evidence_class": "observed",
            },
            "replacement_ref": None,
            "exception_reason": None,
        }
    ]

    handoff = RoadmapGoalHandoff.model_validate(payload)
    assert handoff.capability_adoptions[0].disposition == "reuse"


def test_capability_adoption_disposition_requires_authority_or_reason() -> None:
    """Supersession and reduced-capability exceptions cannot be silent."""

    common = {
        "capability_ref": {"path": "capability.md", "revision": "abc123", "concern": "owned seam"},
        "canonical_seam": "package.factory",
        "intended_consumer": "flagship demo",
        "adoption_proof": EvidenceTarget(claim="The demo executes the seam.", evidence_class="observed"),
    }
    with pytest.raises(ValidationError, match="supersede requires replacement_ref"):
        CapabilityAdoptionBinding.model_validate({**common, "disposition": "supersede"})
    with pytest.raises(ValidationError, match="explicit_exception requires exception_reason"):
        CapabilityAdoptionBinding.model_validate({**common, "disposition": "explicit_exception"})


def test_cli_validates_positive_fixture() -> None:
    """The public module CLI should validate the real committed positive fixture."""

    result = subprocess.run(
        [sys.executable, "-m", "enforced_planning.planning_handoff", "validate", str(VALID_FIXTURE)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["goal_id"] == "plan-72-handoff"


def test_cli_rejects_invalid_exchange(tmp_path: Path) -> None:
    """The public CLI should return structured nonzero failure for authority leakage."""

    payload = _load_yaml(VALID_FIXTURE)
    payload["result"]["current_priority"] = "high"
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "enforced_planning.planning_handoff", "validate", str(invalid)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    error = json.loads(result.stderr)
    assert error["ok"] is False
    assert "Extra inputs are not permitted" in error["error"]
