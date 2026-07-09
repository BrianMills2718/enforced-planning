"""Tests for semantic truth-surface review helpers."""

from __future__ import annotations

import json
import sys
import textwrap
import types
from pathlib import Path

import yaml

from scripts.review_truth_surface_semantic import (
    _resolve_output_path,
    _load_llm_client_exports,
    append_semantic_review_history,
    build_semantic_review_context,
    load_semantic_review_history,
    load_semantic_review_payload,
    review_truth_surface_semantic,
)
from scripts.truth_surface_semantic_models import SemanticReviewReport


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
                "plan_reservations": [
                    {"status": "consumed", "plan": 11, "plan_file": str(tmp_path / "11.md")}
                ],
            }
        )
    )
    (tmp_path / "audit.json").write_text(
        json.dumps({"repo_results": {"demo": {"coordination_adoption_state": "adopted"}}})
    )
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
    tracker_entry = next(
        item for item in context["evidence_surfaces"] if item["label"] == "tracker_file"
    )
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


def test_load_semantic_review_payload_reads_latest_entry_from_history(tmp_path: Path) -> None:
    payload = tmp_path / "semantic_history.json"
    payload.write_text(
        json.dumps(
            [
                {"review": {"overview": "Older run.", "findings": []}},
                {
                    "review": {
                        "overview": "Latest run.",
                        "findings": [
                            {
                                "category": "missing_update",
                                "severity": "info",
                                "summary": "A summary file was not refreshed.",
                                "rationale": "The deterministic status changed but the summary did not.",
                                "evidence_refs": ["docs/ops/TRACKER.md"],
                                "promotion_candidate": False,
                                "promotion_rule_hint": "",
                            }
                        ],
                    }
                },
            ]
        )
    )

    report = load_semantic_review_payload(payload)

    assert report.overview == "Latest run."
    assert report.findings[0].category == "missing_update"


def test_append_semantic_review_history_creates_append_only_json_list(tmp_path: Path) -> None:
    history_path = tmp_path / "semantic_history.json"
    first = {
        "review": {
            "overview": "First run.",
            "findings": [],
        }
    }
    second = {
        "review": {
            "overview": "Second run.",
            "findings": [],
        }
    }

    append_semantic_review_history(history_path, first)
    append_semantic_review_history(history_path, second)

    history = load_semantic_review_history(history_path)

    assert len(history) == 2
    assert history[0]["review"]["overview"] == "First run."
    assert history[1]["review"]["overview"] == "Second run."


def test_resolve_output_path_anchors_relative_paths_to_target_repo(tmp_path: Path) -> None:
    config_path = tmp_path / "repo" / "scripts" / "truth_surface_drift.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("surfaces: {}\n")

    resolved = _resolve_output_path(
        "docs/ops/semantic_truth_surface_review.json",
        config_path=config_path,
    )

    assert resolved == tmp_path / "repo" / "docs" / "ops" / "semantic_truth_surface_review.json"


def test_load_llm_client_exports_fails_loud_without_public_api(monkeypatch) -> None:
    fake_module = types.ModuleType("llm_client")
    monkeypatch.setitem(sys.modules, "llm_client", fake_module)

    try:
        _load_llm_client_exports()
    except RuntimeError as exc:
        assert "llm_client" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected llm_client import contract failure")


def test_semantic_review_default_trace_id_is_unique(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_render_prompt(**_kwargs: object) -> list[dict[str, str]]:
        return [{"role": "user", "content": "review this"}]

    def fake_call_llm_structured(*_args: object, **kwargs: object) -> tuple[SemanticReviewReport, object]:
        calls.append(dict(kwargs))
        report = SemanticReviewReport(overview="No findings.", findings=[])
        return report, types.SimpleNamespace(cost=0.01, model="fake-model")

    monkeypatch.setattr(
        "scripts.review_truth_surface_semantic._load_llm_client_exports",
        lambda: (fake_call_llm_structured, fake_render_prompt),
    )
    monkeypatch.setattr(
        "scripts.review_truth_surface_semantic.build_semantic_review_context",
        lambda config_path, *, max_evidence_chars=4000: {
            "config_path": str(config_path),
            "rendered_status": "ok",
            "deterministic_issues": [],
            "registry_summary": {},
            "evidence_surfaces": [],
        },
    )

    review_truth_surface_semantic(tmp_path / "truth.yaml", model="fake-model", max_budget=0.5, trace_id=None)
    review_truth_surface_semantic(tmp_path / "truth.yaml", model="fake-model", max_budget=0.5, trace_id=None)

    first_trace_id = str(calls[0]["trace_id"])
    second_trace_id = str(calls[1]["trace_id"])
    assert first_trace_id != second_trace_id
    assert first_trace_id.startswith("enforced_planning.semantic_truth_surface_review.")
    assert second_trace_id.startswith("enforced_planning.semantic_truth_surface_review.")


def test_semantic_review_preserves_explicit_trace_id(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []

    def fake_render_prompt(**_kwargs: object) -> list[dict[str, str]]:
        return [{"role": "user", "content": "review this"}]

    def fake_call_llm_structured(*_args: object, **kwargs: object) -> tuple[SemanticReviewReport, object]:
        calls.append(dict(kwargs))
        report = SemanticReviewReport(overview="No findings.", findings=[])
        return report, types.SimpleNamespace(cost=0.01, model="fake-model")

    monkeypatch.setattr(
        "scripts.review_truth_surface_semantic._load_llm_client_exports",
        lambda: (fake_call_llm_structured, fake_render_prompt),
    )
    monkeypatch.setattr(
        "scripts.review_truth_surface_semantic.build_semantic_review_context",
        lambda config_path, *, max_evidence_chars=4000: {
            "config_path": str(config_path),
            "rendered_status": "ok",
            "deterministic_issues": [],
            "registry_summary": {},
            "evidence_surfaces": [],
        },
    )

    review_truth_surface_semantic(
        tmp_path / "truth.yaml",
        model="fake-model",
        max_budget=0.5,
        trace_id="reproducible-review",
    )

    assert calls[0]["trace_id"] == "reproducible-review"
