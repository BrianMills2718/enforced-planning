"""Focused tests for the read-only coordination App readiness boundary."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "worktree-coordination"
    / "coordination_app_readiness.py"
)
HEAD = "a" * 40


def _load():
    spec = importlib.util.spec_from_file_location("coordination_app_readiness", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def protection(app_id=99, *, strict=True, enforce_admins=True):
    return {
        "required_status_checks": {
            "strict": strict,
            "checks": [{"context": "coordination-approval", "app_id": app_id}],
        },
        "enforce_admins": {"enabled": enforce_admins},
    }


def check_run(app_id=99, head_sha=HEAD):
    return {
        "name": "coordination-approval",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "success",
        "app": {"id": app_id},
    }


def test_exact_app_binding_and_exact_head_are_ready() -> None:
    module = _load()
    report = module.evaluate_readiness(
        repo="owner/repo",
        branch="main",
        expected_app_id=99,
        protection=protection(),
        head_sha=HEAD,
        check_runs=[check_run()],
    )

    assert report.ready is True
    assert report.same_name_wrong_app_rejected is True
    assert report.old_head_rejected is True


def test_same_name_wrong_app_and_old_sha_do_not_satisfy_readiness() -> None:
    module = _load()
    report = module.evaluate_readiness(
        repo="owner/repo",
        branch="main",
        expected_app_id=99,
        protection=protection(),
        head_sha=HEAD,
        check_runs=[check_run(app_id=100), check_run(head_sha="b" * 40)],
    )

    assert report.ready is False
    assert report.exact_head_success is False
    assert any("no completed successful" in problem for problem in report.problems)


def test_newest_same_name_run_controls_readiness() -> None:
    module = _load()
    failing_latest = {**check_run(), "conclusion": "failure"}
    report = module.evaluate_readiness(
        repo="owner/repo",
        branch="main",
        expected_app_id=99,
        protection=protection(),
        head_sha=HEAD,
        check_runs=[failing_latest, check_run()],
    )

    assert report.ready is False
    assert report.exact_head_success is False


def test_null_or_mismatched_binding_and_admin_bypass_fail_closed() -> None:
    module = _load()
    report = module.evaluate_readiness(
        repo="owner/repo",
        branch="main",
        expected_app_id=99,
        protection=protection(None, strict=False, enforce_admins=False),
    )

    assert report.ready is False
    assert report.observed_app_id is None
    assert "coordination-approval has no positive App ID binding" in report.problems
    assert "required status checks are not strict" in report.problems
    assert "branch protection does not enforce rules for administrators" in report.problems
