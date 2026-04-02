"""Tests for semantic truth-surface review helpers."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import yaml

from scripts.review_truth_surface_semantic import (
    SemanticReviewReport,
    _load_llm_client_exports,
    build_semantic_review_context,
    load_semantic_review_payload,
)


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip())


def test_build_semantic_review_context_collects_bounded_surfaces(tmp_path: Path) -> None:
    tracker = tmp_path / "tracker.md"
    tracker.write_text("next action: reconcile tracker prose\n" + ("x" * 5000))
    plan_index = tmp_path / "CLAUDE.md"
    _write(
        plan_index,
        """
        # Implementation Plans
        | # | Gap | Priority | Status | Blocks |
        |---|-----|----------|--------|--------|
        | 11 | Example | High | 🚧 In Progress | None |
        """,
    )
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [{"status": "active", "project": "demo", "plan": 11}],
                "plan_reservations": [{"status": "consumed", "plan": 11, "plan_file": str(tmp_path / '11.md')}],
            }
        )
    )
    (tmp_path / "audit.json").write_text(json.dumps({"repo_results": {"demo": {"coordination_adoption_state": "adopted"}}}))
    config = tmp_path / "truth_surface_drift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "surfaces": {
                    "tracker_file": str(tracker),
                    "registry_file": str(registry),
                    "plan_index_file": str(plan_index),
                },
                "checks": {
                    "consumed_reservations_exist": {"severity": "fail"},
                    "no_active_work_for_complete_plans": {"severity": "fail"},
                    "audit_claim_rules": {
                        "rules": [
                            {
                                "source_pattern": "coordination adoption state: (?P<claim>\\w+)",
                                "audit_file": str(tmp_path / "audit.json"),
                                "audit_json_path": "repo_results.demo.coordination_adoption_state",
                                "severity": "fail",
                            }
                        ]
                    },
                },
            }
        )
    )

    context = build_semantic_review_context(config, max_evidence_chars=120)

    assert "Truth Surface Status" in context["rendered_status"]
    assert context["registry_summary"]["active_claim_count"] == 1
    assert any(item["label"] == "tracker_file" for item in context["evidence_surfaces"])
    tracker_entry = next(item for item in context["evidence_surfaces"] if item["label"] == "tracker_file")
    assert tracker_entry["content_excerpt"].endswith("... [truncated]")


def test_load_semantic_review_payload_reads_review_wrapper(tmp_path: Path) -> None:
    payload = tmp_path / "semantic.json"
    payload.write_text(
        json.dumps(
            {
                "review": {
                    "overview": "One semantic warning remains.",
                    "findings": [
                        {
                            "category": "stale_prose",
                            "severity": "warn",
                            "summary": "Tracker language is stale.",
                            "rationale": "The tracker still describes a completed phase as active.",
                            "evidence_refs": ["docs/ops/TRACKER.md"],
                            "promotion_candidate": True,
                            "promotion_rule_hint": "active tracker should not describe a completed phase as current",
                        }
                    ],
                }
            }
        )
    )

    report = load_semantic_review_payload(payload)

    assert isinstance(report, SemanticReviewReport)
    assert report.findings[0].category == "stale_prose"
    assert report.findings[0].promotion_candidate is True


def test_load_llm_client_exports_fails_loud_without_public_api() -> None:
    try:
        _load_llm_client_exports()
    except RuntimeError as exc:
        assert "llm_client" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected llm_client import contract failure in this test environment")
