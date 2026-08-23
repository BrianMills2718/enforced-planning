"""Tests for the lane confinement wrapper's self-test reporting.

These exist because of a specific defect: the unconfined sensitivity arm
graded itself against a relaxed expectation set, met it, and returned ``ok:
true`` with exit 0 on a run that had just mutated the canonical checkout. That
is the fail-open-silently shape the wrapper itself was built to eliminate, so
the reporting invariant is pinned here rather than left to review.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "worktree-coordination" / "run_confined_lane.py"


def _load_module():
    """Load the standalone confinement wrapper as a module."""
    spec = importlib.util.spec_from_file_location("run_confined_lane_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()

ALL_ALLOWED = {name: "ALLOWED" for name in MODULE.EXPECTED_CONFINED}
CONFINED_PASS = dict(MODULE.EXPECTED_CONFINED)
MUTATED = "mutated\nmutated"


def test_confined_pass_sets_boundary_verified() -> None:
    result = MODULE.grade_probe(True, CONFINED_PASS, MODULE.PRISTINE_CANONICAL)
    assert result["ok"] is True
    assert result["boundary_verified"] is True
    assert result["probe_sensitive"] is None


@pytest.mark.parametrize("confined", [True, False])
def test_ok_is_never_true_when_canonical_was_mutated(confined: bool) -> None:
    """The invariant, in every mode.

    Both arms are handed observations that fully satisfy their own expectation
    set. Only the canonical file differs.
    """
    observed = CONFINED_PASS if confined else ALL_ALLOWED
    result = MODULE.grade_probe(confined, observed, MUTATED)
    assert result["expectations_met"] is True, "precondition: the arm met its own expectations"
    assert result["ok"] is False
    assert result["boundary_verified"] is False
    assert result["canonical_file_intact"] is False


def test_unconfined_sensitivity_is_reported_but_never_verifies_the_boundary() -> None:
    """Passing the relaxed set proves the probe works, not that a boundary exists."""
    result = MODULE.grade_probe(False, ALL_ALLOWED, MUTATED)
    assert result["probe_sensitive"] is True
    assert result["expectations_met"] is True
    assert result["boundary_verified"] is False
    assert result["ok"] is False


def test_unconfined_arm_that_blocks_negatives_is_not_sensitive() -> None:
    """If the negatives are blocked with no boundary, the probe measures nothing."""
    rigged = {**ALL_ALLOWED, **{name: "BLOCKED" for name in MODULE.NEGATIVE_CONTROLS}}
    result = MODULE.grade_probe(False, rigged, MODULE.PRISTINE_CANONICAL)
    assert result["probe_sensitive"] is False
    assert result["ok"] is False


@pytest.mark.parametrize(
    ("results", "expected_exit"),
    [
        ([MODULE.grade_probe(True, CONFINED_PASS, MODULE.PRISTINE_CANONICAL)], 0),
        ([MODULE.grade_probe(False, ALL_ALLOWED, MUTATED)], MODULE.EXIT_BOUNDARY_ABSENT),
        (
            [
                MODULE.grade_probe(True, CONFINED_PASS, MODULE.PRISTINE_CANONICAL),
                MODULE.grade_probe(False, ALL_ALLOWED, MUTATED),
            ],
            MODULE.EXIT_BOUNDARY_ABSENT,
        ),
        ([MODULE.grade_probe(True, ALL_ALLOWED, MUTATED)], MODULE.EXIT_SELF_TEST_FAILED),
    ],
)
def test_report_self_test_exit_codes(results: list[dict], expected_exit: int) -> None:
    assert MODULE.report_self_test(results, available=True, as_json=True) == expected_exit


def test_boundary_verified_requires_a_confined_arm() -> None:
    """A run consisting only of the sensitivity arm never claims verification."""
    payload_exit = MODULE.report_self_test(
        [MODULE.grade_probe(False, ALL_ALLOWED, MUTATED)], available=True, as_json=True
    )
    assert payload_exit != 0


def test_cli_unconfined_arm_does_not_exit_zero() -> None:
    """End to end: the negative control for the negative control.

    This is the check whose absence let the defect ship. It needs no systemd,
    because the unconfined arm applies no boundary.
    """
    proc = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--self-test-unconfined", "--json"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode != 0, f"unconfined arm exited 0; stdout={proc.stdout}"
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False
    assert payload["boundary_verified"] is False
    assert payload["canonical_mutated_in_any_arm"] is True
    assert payload["exit_code"] == proc.returncode
