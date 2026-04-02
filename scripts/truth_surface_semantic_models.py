"""Shared models for semantic truth-surface review.

These models are kept separate from the renderer and reviewer entrypoints so the
structured advisory contract can be reused without import cycles.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SemanticFinding(BaseModel):
    """One advisory semantic drift finding."""

    category: str = Field(
        description="Short semantic drift class such as stale_prose, misleading_summary, or missing_update."
    )
    severity: Literal["info", "warn"] = Field(
        description="Advisory-only severity. Never emit fail for semantic review findings."
    )
    summary: str = Field(
        description="Short human-readable statement of the semantic drift concern."
    )
    rationale: str = Field(
        description="Why the finding matters, grounded in the supplied evidence."
    )
    evidence_refs: list[str] = Field(
        description="Short references to the supplied evidence entries that support this finding."
    )
    promotion_candidate: bool = Field(
        description="Whether this semantic finding appears precise enough to become a future deterministic rule."
    )
    promotion_rule_hint: str = Field(
        description="If promotion_candidate is true, suggest a future deterministic rule shape. Otherwise return an empty string."
    )


class SemanticReviewReport(BaseModel):
    """Structured advisory review output for truth-surface semantic drift."""

    overview: str = Field(
        description="One-paragraph summary of the semantic review result. Mention whether the semantic layer found meaningful drift."
    )
    findings: list[SemanticFinding] = Field(
        description="Advisory semantic findings. Use an empty list when no credible semantic drift is present."
    )
