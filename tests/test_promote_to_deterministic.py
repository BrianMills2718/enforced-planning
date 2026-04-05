"""Tests for promote_to_deterministic.py — semantic promotion reporter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from promote_to_deterministic import (
    _fingerprint,
    format_report,
    generate_scaffold,
    group_by_fingerprint,
    load_findings,
    rank_candidates,
)


def _make_canonical_finding(
    category: str = "stale_prose",
    severity: str = "warn",
    promotion_candidate: bool = True,
    promotion_rule_hint: str = "tracker should not describe a completed phase as current",
    summary: str = "Tracker prose is stale.",
    rationale: str = "The tracker still reads like the prior phase is active.",
    evidence_refs: list[str] | None = None,
) -> dict:
    return {
        "category": category,
        "severity": severity,
        "summary": summary,
        "rationale": rationale,
        "evidence_refs": evidence_refs or ["docs/ops/TRACKER.md"],
        "promotion_candidate": promotion_candidate,
        "promotion_rule_hint": promotion_rule_hint,
    }


def _make_canonical_run(findings: list[dict]) -> dict:
    return {
        "config_path": "/tmp/demo/scripts/truth_surface_drift.yaml",
        "review": {
            "overview": "Semantic drift remains bounded.",
            "findings": findings,
        },
    }


def _make_legacy_finding(
    doc_path: str = "CLAUDE.md",
    finding_type: str = "STALE_PROSE",
    severity: str = "important",
    promotion_candidate: bool = True,
    suggested_check: str | None = "Count files in patterns/",
    evidence: str = "Test evidence.",
) -> dict:
    return {
        "finding_type": finding_type,
        "severity": severity,
        "doc_path": doc_path,
        "evidence": evidence,
        "suggested_fix": None,
        "promotion_candidate": promotion_candidate,
        "suggested_check": suggested_check,
    }


def _make_legacy_run(findings: list[dict], repo: str = "test-repo") -> dict:
    return {
        "repo": repo,
        "reviewed_at": "2026-04-03T00:00:00+00:00",
        "agent": "claude-sonnet-4-6",
        "surfaces_reviewed": ["CLAUDE.md"],
        "findings": findings,
        "summary": "Test run.",
        "promotion_candidates": sum(1 for f in findings if f.get("promotion_candidate")),
    }


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload))
    return path


def _write_yaml(path: Path, payload: object) -> Path:
    path.write_text(yaml.safe_dump(payload))
    return path


class TestFingerprint:
    def test_same_surface_kind_rule_hint_same_fingerprint(self):
        f1 = {
            "surface_ref": "docs/ops/TRACKER.md",
            "kind": "stale_prose",
            "rule_hint": "same",
        }
        f2 = {
            "surface_ref": "docs/ops/TRACKER.md",
            "kind": "stale_prose",
            "rule_hint": "same",
        }
        assert _fingerprint(f1) == _fingerprint(f2)

    def test_different_surface_different_fingerprint(self):
        f1 = {"surface_ref": "CLAUDE.md", "kind": "stale_prose", "rule_hint": "x"}
        f2 = {"surface_ref": "ROADMAP.md", "kind": "stale_prose", "rule_hint": "x"}
        assert _fingerprint(f1) != _fingerprint(f2)


class TestLoadFindings:
    def test_empty_file(self, tmp_path):
        path = tmp_path / "findings.json"
        path.write_text("")
        assert load_findings(path) == []

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        assert load_findings(path) == []

    def test_loads_canonical_history_format(self, tmp_path):
        path = _write_json(
            tmp_path / "findings.json",
            [_make_canonical_run([_make_canonical_finding()])],
        )

        findings = load_findings(path)

        assert len(findings) == 1
        assert findings[0]["kind"] == "stale_prose"
        assert findings[0]["surface_ref"] == "docs/ops/TRACKER.md"

    def test_loads_legacy_yaml_format(self, tmp_path):
        path = _write_yaml(
            tmp_path / "findings.yaml",
            [_make_legacy_run([_make_legacy_finding()])],
        )

        findings = load_findings(path)

        assert len(findings) == 1
        assert findings[0]["kind"] == "STALE_PROSE"
        assert findings[0]["surface_ref"] == "CLAUDE.md"

    def test_filters_non_promotion_candidates(self, tmp_path):
        path = _write_json(
            tmp_path / "findings.json",
            [
                _make_canonical_run(
                    [
                        _make_canonical_finding(promotion_candidate=True),
                        _make_canonical_finding(
                            promotion_candidate=False,
                            category="missing_update",
                        ),
                    ]
                )
            ],
        )

        findings = load_findings(path)

        assert len(findings) == 1


class TestGroupAndRank:
    def test_same_finding_in_two_runs_grouped(self):
        findings = [
            {
                "kind": "stale_prose",
                "severity": "warn",
                "surface_ref": "docs/ops/TRACKER.md",
                "evidence": "stale tracker prose",
                "rule_hint": "refresh tracker after completion",
            },
            {
                "kind": "stale_prose",
                "severity": "warn",
                "surface_ref": "docs/ops/TRACKER.md",
                "evidence": "stale tracker prose",
                "rule_hint": "refresh tracker after completion",
            },
        ]
        groups = group_by_fingerprint(findings)

        assert len(groups) == 1
        assert len(next(iter(groups.values()))) == 2

    def test_more_runs_ranked_first(self):
        groups = {
            "a": [{"severity": "warn"}],
            "b": [{"severity": "warn"}, {"severity": "warn"}],
        }
        ranked = rank_candidates(groups)
        assert len(ranked[0][1]) == 2

    def test_warn_ranked_before_info_same_count(self):
        groups = {
            "a": [{"severity": "info"}],
            "b": [{"severity": "warn"}],
        }
        ranked = rank_candidates(groups)
        assert ranked[0][1][0]["severity"] == "warn"


class TestFormatReport:
    def test_no_candidates(self):
        report = format_report([], min_runs=1, scaffold=False)
        assert "No promotion candidates" in report

    def test_shows_stable_candidates(self):
        groups = {
            "fp": [
                {
                    "kind": "stale_prose",
                    "severity": "warn",
                    "surface_ref": "docs/ops/TRACKER.md",
                    "evidence": "stale tracker prose",
                    "rule_hint": "refresh tracker after completion",
                },
                {
                    "kind": "stale_prose",
                    "severity": "warn",
                    "surface_ref": "docs/ops/TRACKER.md",
                    "evidence": "stale tracker prose",
                    "rule_hint": "refresh tracker after completion",
                },
            ]
        }
        ranked = rank_candidates(groups)
        report = format_report(ranked, min_runs=1, scaffold=False)
        assert "Stable candidates" in report
        assert "stale_prose" in report

    def test_scaffold_included_when_requested(self):
        groups = {
            "fp": [
                {
                    "kind": "stale_prose",
                    "severity": "warn",
                    "surface_ref": "docs/ops/TRACKER.md",
                    "evidence": "stale tracker prose",
                    "rule_hint": "refresh tracker after completion",
                }
            ]
        }
        ranked = rank_candidates(groups)
        report = format_report(ranked, min_runs=1, scaffold=True)
        assert "SCAFFOLD" in report


class TestGenerateScaffold:
    def test_scaffold_is_valid_python_string(self):
        scaffold = generate_scaffold(
            {
                "kind": "stale_prose",
                "surface_ref": "docs/ops/TRACKER.md",
                "rule_hint": "refresh tracker after completion",
                "evidence": "tracker prose is stale",
                "summary": "Tracker prose is stale",
            }
        )
        assert "def main()" in scaffold
        assert "#!/usr/bin/env python3" in scaffold

    def test_scaffold_includes_surface_ref(self):
        scaffold = generate_scaffold(
            {
                "kind": "missing_update",
                "surface_ref": "docs/plans/CLAUDE.md",
                "rule_hint": "update plan index after landing",
                "evidence": "plan index stale",
                "summary": "Plan index stale",
            }
        )
        assert "docs/plans/CLAUDE.md" in scaffold
