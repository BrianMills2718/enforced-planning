"""Tests for verify_coupling.py — agent verification protocol schema and context logic.

These tests verify schema constraints and context-building logic WITHOUT making
real LLM calls. The verify_coupling() function itself is tested via monkeypatching.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from verify_coupling import (
    DIFF_MAX_CHARS,
    VerificationJudgment,
    VerificationRequest,
    build_context_package,
    prepare_request,
    truncate_with_note,
    verify_coupling,
)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestVerificationJudgmentSchema:
    """Pydantic schema constraints on VerificationJudgment."""

    def test_current_verdict_no_proposed_fix(self):
        """CURRENT verdict must have proposed_fix=None."""
        j = VerificationJudgment(
            verdict="CURRENT",
            confidence="high",
            evidence="No behavioral change in diff.",
            proposed_fix=None,
            escalate=False,
        )
        assert j.proposed_fix is None

    def test_current_verdict_rejects_proposed_fix(self):
        """CURRENT verdict with proposed_fix raises ValueError."""
        with pytest.raises(Exception):
            VerificationJudgment(
                verdict="CURRENT",
                confidence="high",
                evidence="No behavioral change.",
                proposed_fix="Some fix text",  # INVALID for CURRENT
                escalate=False,
            )

    def test_uncertain_forces_escalate(self):
        """UNCERTAIN verdict must have escalate=True."""
        j = VerificationJudgment(
            verdict="UNCERTAIN",
            confidence="low",
            evidence="Cannot determine without more context.",
            proposed_fix=None,
            escalate=True,
        )
        assert j.escalate is True

    def test_uncertain_rejects_escalate_false(self):
        """UNCERTAIN verdict with escalate=False raises ValueError."""
        with pytest.raises(Exception):
            VerificationJudgment(
                verdict="UNCERTAIN",
                confidence="low",
                evidence="Cannot determine.",
                proposed_fix=None,
                escalate=False,  # INVALID for UNCERTAIN
            )

    def test_stale_allows_proposed_fix(self):
        """STALE verdict can have a proposed_fix."""
        j = VerificationJudgment(
            verdict="STALE",
            confidence="high",
            evidence="Diff removed function X but doc still references it.",
            proposed_fix="Remove reference to function X from the doc.",
            escalate=False,
        )
        assert j.proposed_fix is not None

    def test_stale_without_fix_can_escalate(self):
        """STALE verdict with no fix can have escalate=True."""
        j = VerificationJudgment(
            verdict="STALE",
            confidence="medium",
            evidence="Doc is outdated but the right fix is unclear.",
            proposed_fix=None,
            escalate=True,
        )
        assert j.escalate is True

    def test_valid_verdicts(self):
        """Only CURRENT, STALE, UNCERTAIN are valid verdicts."""
        for verdict in ("CURRENT", "STALE", "UNCERTAIN"):
            j = VerificationJudgment(
                verdict=verdict,  # type: ignore[arg-type]
                confidence="medium",
                evidence="Evidence.",
                proposed_fix=None,
                escalate=verdict == "UNCERTAIN",
            )
            assert j.verdict == verdict

    def test_invalid_verdict_rejected(self):
        with pytest.raises(Exception):
            VerificationJudgment(
                verdict="MAYBE",  # type: ignore[arg-type]
                confidence="medium",
                evidence="Evidence.",
            )

    def test_invalid_confidence_rejected(self):
        with pytest.raises(Exception):
            VerificationJudgment(
                verdict="CURRENT",
                confidence="super-high",  # type: ignore[arg-type]
                evidence="Evidence.",
            )


# ---------------------------------------------------------------------------
# Truncation tests
# ---------------------------------------------------------------------------

class TestTruncation:
    """truncate_with_note behavior."""

    def test_short_text_not_truncated(self):
        text = "short"
        result, was_truncated = truncate_with_note(text, 100, "TEST")
        assert result == text
        assert was_truncated is False

    def test_long_text_truncated_with_note(self):
        text = "x" * (DIFF_MAX_CHARS + 500)
        result, was_truncated = truncate_with_note(text, DIFF_MAX_CHARS, "DIFF")
        assert was_truncated is True
        assert "TRUNCATED" in result
        assert len(result) > DIFF_MAX_CHARS  # note is appended after the chars

    def test_truncated_content_length(self):
        """The first DIFF_MAX_CHARS chars of the truncated result are the original text."""
        text = "a" * (DIFF_MAX_CHARS + 1000)
        result, _ = truncate_with_note(text, DIFF_MAX_CHARS, "DIFF")
        assert result[:DIFF_MAX_CHARS] == "a" * DIFF_MAX_CHARS

    def test_exact_limit_not_truncated(self):
        text = "x" * DIFF_MAX_CHARS
        result, was_truncated = truncate_with_note(text, DIFF_MAX_CHARS, "DIFF")
        assert result == text
        assert was_truncated is False


# ---------------------------------------------------------------------------
# Context package tests
# ---------------------------------------------------------------------------

class TestContextPackage:
    """build_context_package output shape."""

    def _make_request(self, truncated_diff=False, truncated_doc=False):
        return VerificationRequest(
            coupling_id="src/foo.py → docs/bar.md",
            coupling_description="foo.py must stay aligned with bar.md",
            source_diff="--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new",
            coupled_doc_text="# Bar\n\nFoo does old things.",
            source_diff_truncated=truncated_diff,
            doc_truncated=truncated_doc,
        )

    def test_coupling_id_in_output(self):
        req = self._make_request()
        ctx = build_context_package(req)
        assert "src/foo.py → docs/bar.md" in ctx

    def test_description_in_output(self):
        req = self._make_request()
        ctx = build_context_package(req)
        assert "foo.py must stay aligned with bar.md" in ctx

    def test_truncation_note_shown_when_diff_truncated(self):
        req = self._make_request(truncated_diff=True)
        ctx = build_context_package(req)
        assert "TRUNCATED" in ctx

    def test_no_truncation_note_when_not_truncated(self):
        req = self._make_request(truncated_diff=False, truncated_doc=False)
        ctx = build_context_package(req)
        assert "TRUNCATED" not in ctx


# ---------------------------------------------------------------------------
# prepare_request truncation integration
# ---------------------------------------------------------------------------

class TestPrepareRequest:
    """prepare_request applies truncation to real inputs."""

    def test_short_diff_not_truncated(self, tmp_path):
        doc = tmp_path / "doc.md"
        doc.write_text("# Doc\n\nSome content.")
        req = prepare_request("id", "desc", "short diff", doc)
        assert req.source_diff_truncated is False
        assert req.doc_truncated is False

    def test_long_diff_is_truncated(self, tmp_path):
        doc = tmp_path / "doc.md"
        doc.write_text("content")
        long_diff = "+" * (DIFF_MAX_CHARS + 500)
        req = prepare_request("id", "desc", long_diff, doc)
        assert req.source_diff_truncated is True
        assert "TRUNCATED" in req.source_diff

    def test_missing_doc_file(self, tmp_path):
        doc = tmp_path / "missing.md"
        req = prepare_request("id", "desc", "diff", doc)
        assert "not found" in req.coupled_doc_text.lower()


# ---------------------------------------------------------------------------
# verify_coupling integration (mocked LLM)
# ---------------------------------------------------------------------------

class TestVerifyCouplingFunction:
    """verify_coupling() passes correct kwargs to llm_client."""

    def _make_request(self):
        return VerificationRequest(
            coupling_id="src/foo.py → docs/bar.md",
            coupling_description="stay aligned",
            source_diff="diff content",
            coupled_doc_text="doc content",
        )

    def test_passes_max_budget_to_llm(self):
        """verify_coupling passes max_budget kwarg to llm_client.call_llm_structured."""
        # mock-ok: testing kwarg passing without real LLM call
        judgment_data = {
            "verdict": "CURRENT",
            "confidence": "high",
            "evidence": "No change.",
            "proposed_fix": None,
            "escalate": False,
        }

        mock_complete = MagicMock()
        mock_complete.return_value = (VerificationJudgment.model_validate(judgment_data), MagicMock())

        with patch("verify_coupling._load_llm_client", return_value=mock_complete):
            verify_coupling(self._make_request(), max_budget=0.05)

        called_kwargs = mock_complete.call_args.kwargs
        assert called_kwargs.get("max_budget") == 0.05, f"Expected max_budget=0.05, got {called_kwargs}"

    def test_passes_task_kwarg(self):
        """verify_coupling passes task= kwarg for observability."""
        judgment_data = {
            "verdict": "CURRENT",
            "confidence": "high",
            "evidence": "No change.",
            "proposed_fix": None,
            "escalate": False,
        }

        mock_complete = MagicMock()
        mock_complete.return_value = (VerificationJudgment.model_validate(judgment_data), MagicMock())

        with patch("verify_coupling._load_llm_client", return_value=mock_complete):
            verify_coupling(self._make_request())

        called_kwargs = mock_complete.call_args.kwargs
        assert "task" in called_kwargs

    def test_returns_verification_judgment(self):
        """verify_coupling returns a VerificationJudgment instance."""
        judgment_data = {
            "verdict": "STALE",
            "confidence": "medium",
            "evidence": "Function removed but still documented.",
            "proposed_fix": "Remove mention of old function.",
            "escalate": False,
        }

        mock_complete = MagicMock()
        mock_complete.return_value = (VerificationJudgment.model_validate(judgment_data), MagicMock())

        with patch("verify_coupling._load_llm_client", return_value=mock_complete):
            result = verify_coupling(self._make_request())

        assert isinstance(result, VerificationJudgment)
        assert result.verdict == "STALE"
