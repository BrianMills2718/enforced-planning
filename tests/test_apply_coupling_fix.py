"""Tests for apply_coupling_fix.py — VerificationJudgment action dispatch.

Verifies the action dispatch logic WITHOUT real file system side effects,
using tmp_path fixtures to isolate file writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from apply_coupling_fix import FixResult, apply_fix


# ---------------------------------------------------------------------------
# CURRENT verdict
# ---------------------------------------------------------------------------

class TestCurrentVerdict:
    """CURRENT verdict: log only, no file writes, no escalation."""

    def test_current_logs_and_does_not_apply(self, tmp_path):
        """CURRENT verdict writes to verification log, does not modify doc."""
        doc = tmp_path / "doc.md"
        doc.write_text("Original content.")
        log_path = tmp_path / "verification_log.yaml"
        escalations_path = tmp_path / "escalations.yaml"

        result = apply_fix(
            judgment_data={
                "verdict": "CURRENT",
                "confidence": "high",
                "evidence": "No relevant change.",
                "proposed_fix": None,
                "escalate": False,
            },
            coupling_id="src/foo.py → docs/doc.md",
            doc_path=doc,
            commit="abc123",
            log_path=log_path,
            escalations_path=escalations_path,
        )

        assert result.applied is False
        assert result.escalated is False
        assert result.logged is True
        # Doc is untouched
        assert doc.read_text() == "Original content."
        # Log was written
        assert log_path.exists()
        # Escalations not created
        assert not escalations_path.exists()

    def test_fix_skipped_for_current(self, tmp_path):
        """CURRENT verdict must not modify any docs (acceptance criterion)."""
        doc = tmp_path / "doc.md"
        original = "Unchanged content."
        doc.write_text(original)
        log_path = tmp_path / "log.yaml"

        apply_fix(
            judgment_data={
                "verdict": "CURRENT",
                "confidence": "high",
                "evidence": "OK.",
                "proposed_fix": None,
                "escalate": False,
            },
            coupling_id="src/foo.py → docs/doc.md",
            doc_path=doc,
            commit="abc",
            log_path=log_path,
            escalations_path=tmp_path / "esc.yaml",
        )

        assert doc.read_text() == original, "Doc must not be modified for CURRENT verdict"


# ---------------------------------------------------------------------------
# STALE verdict with proposed fix
# ---------------------------------------------------------------------------

class TestStaleVerdictWithFix:
    """STALE verdict with proposed_fix: apply fix to doc."""

    def test_applies_fix_to_doc(self, tmp_path):
        doc = tmp_path / "doc.md"
        doc.write_text("Old content.")
        log_path = tmp_path / "log.yaml"

        result = apply_fix(
            judgment_data={
                "verdict": "STALE",
                "confidence": "high",
                "evidence": "Function removed.",
                "proposed_fix": "New fixed content.",
                "escalate": False,
            },
            coupling_id="src/foo.py → docs/doc.md",
            doc_path=doc,
            commit="abc",
            log_path=log_path,
            escalations_path=tmp_path / "esc.yaml",
        )

        assert result.applied is True
        assert doc.read_text() == "New fixed content."

    def test_stale_with_fix_logs_not_escalates(self, tmp_path):
        doc = tmp_path / "doc.md"
        doc.write_text("Old.")
        log_path = tmp_path / "log.yaml"
        esc_path = tmp_path / "esc.yaml"

        result = apply_fix(
            judgment_data={
                "verdict": "STALE",
                "confidence": "high",
                "evidence": "Function removed.",
                "proposed_fix": "Fixed.",
                "escalate": False,
            },
            coupling_id="src/foo.py → docs/doc.md",
            doc_path=doc,
            commit="abc",
            log_path=log_path,
            escalations_path=esc_path,
        )

        assert result.escalated is False
        assert result.logged is True
        assert not esc_path.exists()


# ---------------------------------------------------------------------------
# UNCERTAIN verdict
# ---------------------------------------------------------------------------

class TestUncertainVerdict:
    """UNCERTAIN verdict: write escalation, do not modify doc."""

    def test_uncertain_writes_escalation(self, tmp_path):
        """UNCERTAIN verdict appends to escalations.yaml (acceptance criterion)."""
        doc = tmp_path / "doc.md"
        doc.write_text("Content.")
        esc_path = tmp_path / "escalations.yaml"

        result = apply_fix(
            judgment_data={
                "verdict": "UNCERTAIN",
                "confidence": "low",
                "evidence": "Cannot determine from diff alone.",
                "proposed_fix": None,
                "escalate": True,
            },
            coupling_id="src/foo.py → docs/doc.md",
            doc_path=doc,
            commit="abc",
            log_path=tmp_path / "log.yaml",
            escalations_path=esc_path,
        )

        assert result.escalated is True
        assert result.applied is False
        assert esc_path.exists()
        # Doc untouched
        assert doc.read_text() == "Content."

    def test_fix_appends_to_escalations(self, tmp_path):
        """Multiple UNCERTAIN verdicts append (not overwrite) escalations."""
        esc_path = tmp_path / "escalations.yaml"

        for i in range(3):
            apply_fix(
                judgment_data={
                    "verdict": "UNCERTAIN",
                    "confidence": "low",
                    "evidence": f"Cannot determine #{i}.",
                    "proposed_fix": None,
                    "escalate": True,
                },
                coupling_id=f"src/foo{i}.py → docs/doc.md",
                doc_path=tmp_path / "doc.md",
                commit="abc",
                log_path=tmp_path / "log.yaml",
                escalations_path=esc_path,
            )

        content = esc_path.read_text()
        # All three coupling IDs should appear
        for i in range(3):
            assert f"src/foo{i}.py" in content, f"Escalation {i} missing from {esc_path}"


# ---------------------------------------------------------------------------
# STALE without fix (escalates)
# ---------------------------------------------------------------------------

class TestStaleVerdictWithoutFix:
    """STALE verdict with no proposed_fix escalates instead of applying."""

    def test_stale_without_fix_escalates(self, tmp_path):
        esc_path = tmp_path / "escalations.yaml"

        result = apply_fix(
            judgment_data={
                "verdict": "STALE",
                "confidence": "medium",
                "evidence": "Doc is wrong but fix is unclear.",
                "proposed_fix": None,
                "escalate": True,
            },
            coupling_id="src/foo.py → docs/doc.md",
            doc_path=tmp_path / "doc.md",
            commit="abc",
            log_path=tmp_path / "log.yaml",
            escalations_path=esc_path,
        )

        assert result.escalated is True
        assert result.applied is False
        assert esc_path.exists()


# ---------------------------------------------------------------------------
# FixResult schema
# ---------------------------------------------------------------------------

class TestFixResultSchema:
    """FixResult Pydantic model constraints."""

    def test_fix_result_defaults(self):
        r = FixResult(applied=True, escalated=False, logged=True, message="done")
        assert r.committed is False  # default

    def test_fix_result_requires_applied(self):
        with pytest.raises(Exception):
            FixResult(escalated=False, logged=True, message="missing applied")
