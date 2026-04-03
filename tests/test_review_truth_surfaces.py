"""Tests for review_truth_surfaces.py — Plan #7 semantic review layer.

Tests cover schema constraints, surface collection, and context building.
No live LLM calls are made; verify_coupling mock pattern is reused.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from review_truth_surfaces import (
    DOC_MAX_CHARS,
    SemanticFinding,
    SemanticReviewResult,
    build_review_context,
    collect_surfaces,
    review_truth_surfaces,
    save_findings,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSemanticFindingSchema:
    """Pydantic constraints on SemanticFinding."""

    def test_valid_finding_types(self):
        for ftype in ("STALE_PROSE", "MISLEADING_SUMMARY", "CROSS_DOC_DISAGREEMENT", "UNDOCUMENTED_ASSUMPTION"):
            f = SemanticFinding(
                finding_type=ftype,  # type: ignore[arg-type]
                severity="advisory",
                doc_path="CLAUDE.md",
                evidence="Some evidence.",
                promotion_candidate=False,
            )
            assert f.finding_type == ftype

    def test_invalid_finding_type_rejected(self):
        with pytest.raises(Exception):
            SemanticFinding(
                finding_type="UNKNOWN_TYPE",  # type: ignore[arg-type]
                severity="advisory",
                doc_path="CLAUDE.md",
                evidence="Evidence.",
                promotion_candidate=False,
            )

    def test_valid_severities(self):
        for sev in ("advisory", "important", "critical"):
            f = SemanticFinding(
                finding_type="STALE_PROSE",
                severity=sev,  # type: ignore[arg-type]
                doc_path="CLAUDE.md",
                evidence="Evidence.",
                promotion_candidate=False,
            )
            assert f.severity == sev

    def test_invalid_severity_rejected(self):
        with pytest.raises(Exception):
            SemanticFinding(
                finding_type="STALE_PROSE",
                severity="blocker",  # type: ignore[arg-type]
                doc_path="CLAUDE.md",
                evidence="Evidence.",
                promotion_candidate=False,
            )

    def test_suggested_fix_optional(self):
        f = SemanticFinding(
            finding_type="STALE_PROSE",
            severity="advisory",
            doc_path="CLAUDE.md",
            evidence="Evidence.",
            promotion_candidate=False,
        )
        assert f.suggested_fix is None

    def test_promotion_candidate_with_no_check(self):
        """promotion_candidate can be True without suggested_check."""
        f = SemanticFinding(
            finding_type="STALE_PROSE",
            severity="important",
            doc_path="CLAUDE.md",
            evidence="Evidence.",
            promotion_candidate=True,
            suggested_check=None,
        )
        assert f.promotion_candidate is True

    def test_promotion_candidate_with_check(self):
        f = SemanticFinding(
            finding_type="STALE_PROSE",
            severity="advisory",
            doc_path="ROADMAP.md",
            evidence="Phase 4 marked complete but CLAUDE.md still says in progress.",
            promotion_candidate=True,
            suggested_check="Check ROADMAP.md phase status matches CLAUDE.md sprint tracker.",
        )
        assert f.suggested_check is not None


class TestSemanticReviewResultSchema:
    """SemanticReviewResult schema constraints."""

    def _make_result(self, findings=None):
        return SemanticReviewResult(
            repo="enforced-planning",
            reviewed_at="2026-04-02T17:00:00+00:00",
            agent="claude-sonnet-4-6",
            surfaces_reviewed=["CLAUDE.md", "ROADMAP.md"],
            findings=findings or [],
            summary="Surface is clean.",
            promotion_candidates=0,
        )

    def test_empty_findings_valid(self):
        r = self._make_result()
        assert r.findings == []

    def test_promotion_candidates_is_int(self):
        r = self._make_result()
        assert isinstance(r.promotion_candidates, int)

    def test_summary_required(self):
        with pytest.raises(Exception):
            SemanticReviewResult(
                repo="foo",
                reviewed_at="2026-04-02",
                agent="claude",
                surfaces_reviewed=[],
                findings=[],
                promotion_candidates=0,
                # missing summary
            )


# ---------------------------------------------------------------------------
# Surface collection tests
# ---------------------------------------------------------------------------

class TestCollectSurfaces:
    """collect_surfaces reads truth surface files from repo root."""

    def test_returns_empty_for_empty_dir(self, tmp_path):
        result = collect_surfaces(tmp_path)
        assert result == {}

    def test_reads_present_surfaces(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE\n\nContent here.")
        (tmp_path / "ROADMAP.md").write_text("# ROADMAP\n\nPhase 1: done.")
        result = collect_surfaces(tmp_path)
        assert "CLAUDE.md" in result
        assert "ROADMAP.md" in result

    def test_skips_missing_surfaces(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("content")
        result = collect_surfaces(tmp_path)
        # ROADMAP.md missing — should not appear
        assert "ROADMAP.md" not in result
        assert "CLAUDE.md" in result

    def test_long_surface_truncated(self, tmp_path):
        long_content = "x" * (DOC_MAX_CHARS + 500)
        (tmp_path / "CLAUDE.md").write_text(long_content)
        result = collect_surfaces(tmp_path)
        assert "TRUNCATED" in result["CLAUDE.md"]

    def test_short_surface_not_truncated(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("short content")
        result = collect_surfaces(tmp_path)
        assert "TRUNCATED" not in result["CLAUDE.md"]
        assert result["CLAUDE.md"] == "short content"


# ---------------------------------------------------------------------------
# Context building tests
# ---------------------------------------------------------------------------

class TestBuildReviewContext:
    """build_review_context shapes the user-turn content correctly."""

    def test_repo_name_in_context(self):
        ctx = build_review_context({"CLAUDE.md": "content"}, "my-repo")
        assert "my-repo" in ctx

    def test_surface_paths_in_context(self):
        ctx = build_review_context({"CLAUDE.md": "content", "ROADMAP.md": "roadmap"}, "repo")
        assert "CLAUDE.md" in ctx
        assert "ROADMAP.md" in ctx

    def test_content_in_context(self):
        ctx = build_review_context({"CLAUDE.md": "unique-marker-12345"}, "repo")
        assert "unique-marker-12345" in ctx

    def test_task_instructions_in_context(self):
        ctx = build_review_context({}, "repo")
        assert "SemanticReviewResult" in ctx


# ---------------------------------------------------------------------------
# review_truth_surfaces mocked
# ---------------------------------------------------------------------------

class TestReviewTruthSurfaces:
    """review_truth_surfaces passes correct kwargs and returns SemanticReviewResult."""

    def _make_result_data(self):
        return {
            "repo": "test-repo",
            "reviewed_at": "2026-04-02T17:00:00+00:00",
            "agent": "claude-sonnet-4-6",
            "surfaces_reviewed": ["CLAUDE.md"],
            "findings": [],
            "summary": "Surface is clean.",
            "promotion_candidates": 0,
        }

    def _make_review_result(self, data: dict | None = None) -> SemanticReviewResult:
        """Build a SemanticReviewResult from dict (default: clean result)."""
        return SemanticReviewResult.model_validate(data or self._make_result_data())

    def test_returns_semantic_review_result(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE")

        mock_complete = MagicMock()
        mock_complete.return_value = (self._make_review_result(), MagicMock())

        with patch("review_truth_surfaces._load_llm_client", return_value=mock_complete):
            result = review_truth_surfaces(tmp_path)

        assert isinstance(result, SemanticReviewResult)

    def test_passes_max_budget(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE")

        mock_complete = MagicMock()
        mock_complete.return_value = (self._make_review_result(), MagicMock())

        with patch("review_truth_surfaces._load_llm_client", return_value=mock_complete):
            review_truth_surfaces(tmp_path, max_budget=0.75)

        kwargs = mock_complete.call_args.kwargs
        assert kwargs.get("max_budget") == 0.75

    def test_passes_task_kwarg(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE")

        mock_complete = MagicMock()
        mock_complete.return_value = (self._make_review_result(), MagicMock())

        with patch("review_truth_surfaces._load_llm_client", return_value=mock_complete):
            review_truth_surfaces(tmp_path)

        kwargs = mock_complete.call_args.kwargs
        assert "task" in kwargs

    def test_empty_repo_returns_clean_result(self, tmp_path):
        """Repos with no reviewable surfaces return a clean result without LLM call."""
        with patch("review_truth_surfaces._load_llm_client") as mock_loader:
            result = review_truth_surfaces(tmp_path)

        # LLM should NOT be called when no surfaces found
        mock_loader.assert_not_called()
        assert result.findings == []
        assert "No reviewable" in result.summary

    def test_promotion_candidates_recalculated(self, tmp_path):
        """promotion_candidates is recalculated from findings, not trusted from LLM."""
        (tmp_path / "CLAUDE.md").write_text("# CLAUDE")

        result_data = self._make_result_data()
        result_data["findings"] = [
            {
                "finding_type": "STALE_PROSE",
                "severity": "advisory",
                "doc_path": "CLAUDE.md",
                "evidence": "Phase 4 marked complete but text says in progress.",
                "suggested_fix": None,
                "promotion_candidate": True,
                "suggested_check": "Check phase status consistency.",
            }
        ]
        result_data["promotion_candidates"] = 999  # LLM returned wrong count
        llm_result = SemanticReviewResult.model_validate(result_data)

        mock_complete = MagicMock()
        mock_complete.return_value = (llm_result, MagicMock())

        with patch("review_truth_surfaces._load_llm_client", return_value=mock_complete):
            result = review_truth_surfaces(tmp_path)

        # Should be 1, not 999
        assert result.promotion_candidates == 1


# ---------------------------------------------------------------------------
# save_findings
# ---------------------------------------------------------------------------

class TestSaveFindings:
    """save_findings appends to output file."""

    def _make_result(self):
        return SemanticReviewResult(
            repo="test",
            reviewed_at="2026-04-02T17:00:00+00:00",
            agent="claude-sonnet-4-6",
            surfaces_reviewed=["CLAUDE.md"],
            findings=[],
            summary="Clean.",
            promotion_candidates=0,
        )

    def test_creates_file_if_missing(self, tmp_path):
        output = tmp_path / "findings.yaml"
        save_findings(self._make_result(), output)
        assert output.exists()

    def test_appends_not_overwrites(self, tmp_path):
        output = tmp_path / "findings.yaml"
        r1 = self._make_result()
        r2 = self._make_result()
        r2 = r2.model_copy(update={"repo": "second-repo"})

        save_findings(r1, output)
        save_findings(r2, output)

        content = output.read_text()
        assert "test" in content
        assert "second-repo" in content
