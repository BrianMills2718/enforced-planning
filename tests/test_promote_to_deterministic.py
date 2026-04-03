"""Tests for promote_to_deterministic.py — promotion candidate reporter."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from promote_to_deterministic import (
    _fingerprint,
    format_report,
    generate_scaffold,
    group_by_fingerprint,
    load_findings,
    rank_candidates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(
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


def _make_run(findings: list[dict], repo: str = "test-repo") -> dict:
    return {
        "repo": repo,
        "reviewed_at": "2026-04-03T00:00:00+00:00",
        "agent": "claude-sonnet-4-6",
        "surfaces_reviewed": ["CLAUDE.md"],
        "findings": findings,
        "summary": "Test run.",
        "promotion_candidates": sum(1 for f in findings if f.get("promotion_candidate")),
    }


def write_findings_yaml(tmp_path: Path, runs: list[dict]) -> Path:
    """Write findings YAML and return path."""
    try:
        import yaml
        path = tmp_path / "findings.yaml"
        path.write_text(yaml.dump(runs))
        return path
    except ImportError:
        import json as _json
        path = tmp_path / "findings.yaml"
        # Approximate YAML with JSON-safe content
        path.write_text(_json.dumps(runs))
        return path


# ---------------------------------------------------------------------------
# _fingerprint
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_same_doc_type_check_same_fingerprint(self):
        f1 = _make_finding(doc_path="CLAUDE.md", finding_type="STALE_PROSE", suggested_check="abc")
        f2 = _make_finding(doc_path="CLAUDE.md", finding_type="STALE_PROSE", suggested_check="abc")
        assert _fingerprint(f1) == _fingerprint(f2)

    def test_different_doc_different_fingerprint(self):
        f1 = _make_finding(doc_path="CLAUDE.md")
        f2 = _make_finding(doc_path="ROADMAP.md")
        assert _fingerprint(f1) != _fingerprint(f2)

    def test_different_type_different_fingerprint(self):
        f1 = _make_finding(finding_type="STALE_PROSE")
        f2 = _make_finding(finding_type="CROSS_DOC_DISAGREEMENT")
        assert _fingerprint(f1) != _fingerprint(f2)

    def test_none_suggested_check(self):
        f = _make_finding(suggested_check=None)
        fp = _fingerprint(f)
        assert isinstance(fp, str)


# ---------------------------------------------------------------------------
# load_findings
# ---------------------------------------------------------------------------

class TestLoadFindings:
    def test_empty_file(self, tmp_path):
        path = tmp_path / "findings.yaml"
        path.write_text("")
        assert load_findings(path) == []

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.yaml"
        assert load_findings(path) == []

    def test_loads_promotion_candidates_only(self, tmp_path):
        runs = [_make_run([
            _make_finding(promotion_candidate=True),
            _make_finding(promotion_candidate=False),
        ])]
        path = write_findings_yaml(tmp_path, runs)
        findings = load_findings(path)
        assert len(findings) == 1
        assert findings[0]["promotion_candidate"] is True

    def test_empty_run_list(self, tmp_path):
        runs = [_make_run([])]
        path = write_findings_yaml(tmp_path, runs)
        assert load_findings(path) == []

    def test_multiple_runs_flattened(self, tmp_path):
        runs = [
            _make_run([_make_finding()]),
            _make_run([_make_finding(), _make_finding(doc_path="ROADMAP.md")]),
        ]
        path = write_findings_yaml(tmp_path, runs)
        findings = load_findings(path)
        assert len(findings) == 3


# ---------------------------------------------------------------------------
# group_by_fingerprint
# ---------------------------------------------------------------------------

class TestGroupByFingerprint:
    def test_same_finding_in_two_runs_grouped(self):
        f = _make_finding()
        findings = [
            {**f, "_run_index": 0},
            {**f, "_run_index": 1},
        ]
        groups = group_by_fingerprint(findings)
        assert len(groups) == 1
        fp = list(groups.keys())[0]
        assert len(groups[fp]) == 2

    def test_different_findings_separate_groups(self):
        findings = [
            {**_make_finding(doc_path="CLAUDE.md"), "_run_index": 0},
            {**_make_finding(doc_path="ROADMAP.md"), "_run_index": 0},
        ]
        groups = group_by_fingerprint(findings)
        assert len(groups) == 2


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------

class TestRankCandidates:
    def test_more_runs_ranked_first(self):
        groups = {
            "a": [_make_finding()],
            "b": [_make_finding(), _make_finding()],
        }
        ranked = rank_candidates(groups)
        # 'b' (2 runs) should come first
        assert len(ranked[0][1]) == 2

    def test_critical_ranked_before_advisory_same_count(self):
        groups = {
            "a": [_make_finding(severity="advisory")],
            "b": [_make_finding(severity="critical")],
        }
        ranked = rank_candidates(groups)
        assert ranked[0][1][0]["severity"] == "critical"


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------

class TestFormatReport:
    def test_no_candidates(self):
        report = format_report([], min_runs=1, scaffold=False)
        assert "No promotion candidates" in report

    def test_shows_stable_candidates(self):
        groups = {"fp": [_make_finding(), _make_finding()]}
        ranked = rank_candidates(groups)
        report = format_report(ranked, min_runs=1, scaffold=False)
        assert "Stable candidates" in report

    def test_min_runs_filters_unstable(self):
        groups = {"fp": [_make_finding()]}  # 1 run only
        ranked = rank_candidates(groups)
        report = format_report(ranked, min_runs=2, scaffold=False)
        assert "Unstable candidates" in report

    def test_scaffold_included_when_requested(self):
        groups = {"fp": [_make_finding(), _make_finding()]}
        ranked = rank_candidates(groups)
        report = format_report(ranked, min_runs=1, scaffold=True)
        assert "SCAFFOLD" in report

    def test_total_count_in_report(self):
        groups = {
            "fp1": [_make_finding()],
            "fp2": [_make_finding(doc_path="ROADMAP.md")],
        }
        ranked = rank_candidates(groups)
        report = format_report(ranked, min_runs=1, scaffold=False)
        assert "Total promotion candidates: 2" in report


# ---------------------------------------------------------------------------
# generate_scaffold
# ---------------------------------------------------------------------------

class TestGenerateScaffold:
    def test_scaffold_is_valid_python_string(self):
        scaffold = generate_scaffold(_make_finding())
        assert "def main()" in scaffold
        assert "#!/usr/bin/env python3" in scaffold

    def test_scaffold_includes_doc_path(self):
        scaffold = generate_scaffold(_make_finding(doc_path="docs/plans/CLAUDE.md"))
        assert "docs/plans/CLAUDE.md" in scaffold

    def test_scaffold_includes_finding_type(self):
        scaffold = generate_scaffold(_make_finding(finding_type="CROSS_DOC_DISAGREEMENT"))
        assert "CROSS_DOC_DISAGREEMENT" in scaffold
