#!/usr/bin/env python3
"""LLM semantic review layer for truth surfaces — Plan #7.

Layer 2 of the truth-surface review stack. Deterministic checks run first
(check_truth_surface_drift.py). This script runs AFTER, on the same truth
surfaces, and uses an LLM to catch semantic drift that deterministic rules
cannot express cheaply or robustly:

- Stale prose: docs that are structurally linked but semantically outdated
- Misleading summaries: summaries that are technically accurate but give the
  wrong impression of the current state
- Cross-document disagreement: two docs that contradict each other in ways
  that deterministic checks won't catch
- Undocumented assumptions: important behaviors that are implied but never stated

Output: structured findings saved to docs/ops/semantic_review_findings.yaml.
Each finding records whether it is a candidate for promotion to a deterministic check.

Usage:
    python review_truth_surfaces.py --repo /path/to/repo
    python review_truth_surfaces.py --repo /path/to/repo --output findings.yaml
    python review_truth_surfaces.py --repo /path/to/repo --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

try:
    from pydantic import BaseModel, Field
except ImportError:
    print("Error: pydantic required. pip install pydantic", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

# Files to include in the review context (scanned relative to repo root)
TRUTH_SURFACE_FILES = [
    "CLAUDE.md",
    "ROADMAP.md",
    "PLANNING_OPERATING_MODEL.md",
    "STATIC_GRAPH_AND_RUNTIME_TRUTH.md",
    "relationships.yaml",
    "docs/plans/CLAUDE.md",
]

# Max chars for each surface file in the context package
DOC_MAX_CHARS = 4_000

# Default cost ceiling for the batch review call
DEFAULT_MAX_BUDGET = 1.0

DEFAULT_MODEL = os.getenv("SEMANTIC_REVIEW_MODEL") or "claude-sonnet-4-6"

FINDINGS_FILE = Path("docs/ops/semantic_review_findings.yaml")


class SemanticFinding(BaseModel):
    """A single semantic drift finding from the LLM review."""

    finding_type: Literal[
        "STALE_PROSE",
        "MISLEADING_SUMMARY",
        "CROSS_DOC_DISAGREEMENT",
        "UNDOCUMENTED_ASSUMPTION",
    ] = Field(
        description="Category of semantic drift: STALE_PROSE (outdated text), "
        "MISLEADING_SUMMARY (technically accurate but wrong impression), "
        "CROSS_DOC_DISAGREEMENT (two docs contradict), "
        "UNDOCUMENTED_ASSUMPTION (implied but never stated)."
    )
    severity: Literal["advisory", "important", "critical"] = Field(
        description="advisory: worth noting but low urgency. "
        "important: should be fixed before next major milestone. "
        "critical: actively misleads agents or humans right now."
    )
    doc_path: str = Field(
        description="Repo-relative path to the document with the finding. "
        "For cross-doc disagreements, cite the primary document."
    )
    evidence: str = Field(
        description="≤300 chars. Quote or reference the specific text triggering this finding."
    )
    suggested_fix: str | None = Field(
        default=None,
        description="Specific text edit or structural change to fix this finding. "
        "Null when the fix requires human judgment."
    )
    promotion_candidate: bool = Field(
        description="True if this finding could be expressed as a deterministic check "
        "in a future programmatic validator. False if it requires ongoing semantic judgment."
    )
    suggested_check: str | None = Field(
        default=None,
        description="If promotion_candidate is True, describe the deterministic check "
        "that would catch this class of issue. Null otherwise."
    )


class SemanticReviewResult(BaseModel):
    """Batch output from one semantic review run."""

    repo: str = Field(description="Repository name being reviewed")
    reviewed_at: str = Field(description="ISO 8601 timestamp of this review run")
    agent: str = Field(description="Model used for this review")
    surfaces_reviewed: list[str] = Field(
        description="Repo-relative paths of documents included in this review"
    )
    findings: list[SemanticFinding] = Field(
        description="All semantic drift findings, ordered by severity (critical first)"
    )
    summary: str = Field(
        description="≤200 chars. One-sentence characterization of the overall semantic health "
        "of this truth surface. e.g. 'Surface is largely current; 2 stale prose entries in ROADMAP.'"
    )
    promotion_candidates: int = Field(
        description="Count of findings that are candidates for promotion to deterministic checks"
    )


def _truncate(text: str, max_chars: int, label: str) -> str:
    """Truncate text to max_chars with a trailing note."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[{label} TRUNCATED at {max_chars} chars]"


def collect_surfaces(repo_root: Path) -> dict[str, str]:
    """Read truth surface files from repo root.

    Returns {relative_path: content} for each file that exists.
    """
    surfaces: dict[str, str] = {}
    for rel_path in TRUTH_SURFACE_FILES:
        full = repo_root / rel_path
        if not full.exists():
            continue
        text = full.read_text(encoding="utf-8", errors="replace")
        surfaces[rel_path] = _truncate(text, DOC_MAX_CHARS, rel_path)
    return surfaces


def build_review_context(surfaces: dict[str, str], repo_name: str) -> str:
    """Build the user-turn content for the semantic review call."""
    parts = [f"# Truth Surface Semantic Review — {repo_name}\n"]
    parts.append(
        "Review the following documents for semantic drift: stale prose, misleading "
        "summaries, cross-document disagreement, and undocumented assumptions.\n"
        "Focus on issues that deterministic structural checks would miss.\n"
    )
    for rel_path, content in surfaces.items():
        parts.append(f"\n## {rel_path}\n```\n{content}\n```")
    parts.append(
        "\n## Task\n"
        "Produce a SemanticReviewResult with:\n"
        "- findings: list of SemanticFinding (may be empty if the surface is clean)\n"
        "- summary: ≤200 chars, one-sentence health characterization\n"
        "- promotion_candidates: count of findings with promotion_candidate=true\n"
        "Order findings by severity: critical, then important, then advisory.\n"
        "Be specific: quote evidence from the documents above."
    )
    return "\n".join(parts)


SYSTEM_PROMPT = """You are a documentation governance agent performing a semantic
review of a software project's truth surfaces.

Your goal: find semantic drift that deterministic structural checks cannot catch.

Finding types:
- STALE_PROSE: Text that was once accurate but no longer reflects the current state
- MISLEADING_SUMMARY: Text that is technically accurate but gives a wrong impression
  of the current state, priorities, or design
- CROSS_DOC_DISAGREEMENT: Two documents that contradict each other in ways that
  a human would find confusing but that aren't detectable as structural errors
- UNDOCUMENTED_ASSUMPTION: Important behaviors, constraints, or policies that are
  implied throughout the docs but never explicitly stated

For each finding, judge whether it could eventually be expressed as a deterministic
check (promotion_candidate=true) or whether it will always require semantic judgment.

Be conservative: only report findings where you have clear textual evidence.
Do not report stylistic issues, only substantive accuracy or agreement problems."""


def _load_llm_client():
    """Import llm_client lazily to allow tests without it installed."""
    try:
        from llm_client import complete  # type: ignore[import]
        return complete
    except ImportError:
        return None


def review_truth_surfaces(
    repo_root: Path,
    model: str | None = None,
    max_budget: float = DEFAULT_MAX_BUDGET,
    trace_id: str | None = None,
) -> SemanticReviewResult:
    """Run the semantic review on a repo's truth surfaces.

    Args:
        repo_root: Root of the repository to review.
        model: Model override. Defaults to DEFAULT_MODEL.
        max_budget: Cost ceiling in USD.
        trace_id: Optional trace ID for llm_client observability.

    Returns:
        SemanticReviewResult with all findings.

    Raises:
        RuntimeError: If llm_client is not available.
    """
    repo_name = repo_root.name
    surfaces = collect_surfaces(repo_root)
    if not surfaces:
        # No reviewable surfaces — return clean result without loading llm_client
        return SemanticReviewResult(
            repo=repo_name,
            reviewed_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            agent=model or DEFAULT_MODEL,
            surfaces_reviewed=[],
            findings=[],
            summary="No reviewable truth surfaces found.",
            promotion_candidates=0,
        )

    complete = _load_llm_client()
    if complete is None:
        raise RuntimeError("llm_client not installed. pip install -e ~/projects/llm_client")

    user_content = build_review_context(surfaces, repo_name)
    effective_model = model or DEFAULT_MODEL
    schema = SemanticReviewResult.model_json_schema()

    result = complete(
        model=effective_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "SemanticReviewResult", "schema": schema},
        },
        task="semantic_truth_surface_review",
        trace_id=trace_id or f"semantic-review-{repo_name}",
        max_budget=max_budget,
    )

    raw = result.content if hasattr(result, "content") else result
    data = json.loads(raw) if isinstance(raw, str) else raw

    # Ensure metadata fields are current (LLM may produce stale placeholders)
    data["repo"] = repo_name
    data["reviewed_at"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    data["agent"] = effective_model
    data["surfaces_reviewed"] = list(surfaces.keys())

    review = SemanticReviewResult.model_validate(data)
    # Recompute promotion_candidates from the actual findings
    review = review.model_copy(
        update={"promotion_candidates": sum(1 for f in review.findings if f.promotion_candidate)}
    )
    return review


def save_findings(result: SemanticReviewResult, output_path: Path) -> None:
    """Append findings to the output YAML file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if output_path.exists() and yaml is not None:
        content = output_path.read_text(encoding="utf-8").strip()
        if content:
            loaded = yaml.safe_load(content)
            if isinstance(loaded, list):
                existing = loaded

    existing.append(result.model_dump())
    if yaml is not None:
        output_path.write_text(
            yaml.dump(existing, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    else:
        output_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def print_findings(result: SemanticReviewResult) -> None:
    """Print a human-readable findings report to stdout."""
    print(f"\n## Semantic Review — {result.repo}")
    print(f"Reviewed at: {result.reviewed_at}  |  Agent: {result.agent}")
    print(f"Surfaces reviewed: {', '.join(result.surfaces_reviewed) or 'none'}")
    print(f"\nSummary: {result.summary}")
    print(f"Findings: {len(result.findings)} ({result.promotion_candidates} promotion candidates)\n")

    if not result.findings:
        print("No semantic drift findings. Surface is clean.")
        return

    for i, f in enumerate(result.findings, 1):
        promote_tag = " [PROMOTABLE]" if f.promotion_candidate else ""
        print(f"{i}. [{f.severity.upper()}] {f.finding_type}{promote_tag}")
        print(f"   Doc: {f.doc_path}")
        print(f"   Evidence: {f.evidence}")
        if f.suggested_fix:
            print(f"   Fix: {f.suggested_fix}")
        if f.suggested_check:
            print(f"   Potential check: {f.suggested_check}")
        print()


def main() -> int:
    """Entry point for CLI usage."""
    parser = argparse.ArgumentParser(description="LLM semantic review of truth surfaces")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repo root (default: .)")
    parser.add_argument("--output", "-o", type=Path, default=FINDINGS_FILE, help="Output YAML file")
    parser.add_argument("--model", help=f"LLM model (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-budget", type=float, default=DEFAULT_MAX_BUDGET)
    parser.add_argument("--trace-id", help="Trace ID for observability")
    parser.add_argument("--dry-run", action="store_true", help="Show surfaces without LLM call")
    args = parser.parse_args()

    repo_root = args.repo.resolve()
    if not repo_root.is_dir():
        print(f"Error: {repo_root} is not a directory", file=sys.stderr)
        return 1

    surfaces = collect_surfaces(repo_root)
    if args.dry_run:
        print(f"Surfaces found in {repo_root.name}:")
        for path, content in surfaces.items():
            print(f"  {path}: {len(content)} chars")
        return 0

    try:
        result = review_truth_surfaces(
            repo_root,
            model=args.model,
            max_budget=args.max_budget,
            trace_id=args.trace_id,
        )
    except Exception as exc:
        print(f"Error: review failed: {exc}", file=sys.stderr)
        return 1

    print_findings(result)
    save_findings(result, args.output)
    print(f"\nFindings saved to {args.output}")
    return 1 if any(f.severity == "critical" for f in result.findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
