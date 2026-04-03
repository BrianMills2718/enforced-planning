#!/usr/bin/env python3
"""Agent verification protocol for validated couplings — Layer 3 of relationships.yaml V2.

When a source file changes, validated couplings trigger this script to determine
whether the coupled documentation is still accurate. The agent reads the diff and
doc, produces a structured verdict, and the caller (apply_coupling_fix.py) takes
the appropriate action: auto-fix, escalate, or mark verified.

Usage:
    python verify_coupling.py --coupling-id "src/foo.py → docs/adr/001.md" \\
        --diff-file /tmp/foo.diff \\
        --doc-path docs/adr/001.md \\
        --description "foo.py must stay aligned with ADR 001"

    python verify_coupling.py --relationships scripts/relationships.yaml \\
        --since-commit abc123
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal

try:
    from pydantic import BaseModel, Field, model_validator
except ImportError:
    print("Error: pydantic required. pip install pydantic", file=sys.stderr)
    sys.exit(1)

# Truncation limits (characters, not lines — more predictable for LLM context)
DIFF_MAX_CHARS = 8_000   # ~200 lines at 40 chars/line
DOC_MAX_CHARS = 20_000   # ~500 lines at 40 chars/line

DEFAULT_MODEL = "gemini/gemini-2.5-flash"
# Why Gemini instead of Claude for the default?
# 1. Cost: gemini-2.5-flash is ~10x cheaper per token than claude-sonnet.
#    verify_coupling fires once per locked coupling per commit — potentially
#    dozens of calls in a busy repo. Cost adds up fast.
# 2. Latency: faster first-token matters in a pre-commit loop where the
#    developer is waiting.
# review_truth_surfaces.py uses Claude because semantic doc review requires
# stronger prose reasoning and happens much less frequently (not per-commit).
# Override at runtime: VERIFY_COUPLING_MODEL env var or --model flag.
DEFAULT_MAX_BUDGET = 0.05  # USD per coupling verification


class VerificationRequest(BaseModel):
    """Input to the agent verification call."""

    coupling_id: str = Field(description="Human-readable coupling identifier, e.g. 'src/foo.py → docs/bar.md'")
    coupling_description: str = Field(description="Description field from relationships.yaml")
    source_diff: str = Field(description="Git diff of the changed source file(s), possibly truncated")
    coupled_doc_text: str = Field(description="Full text of the coupled doc, possibly truncated")
    source_diff_truncated: bool = Field(default=False, description="True when diff exceeded DIFF_MAX_CHARS")
    doc_truncated: bool = Field(default=False, description="True when doc exceeded DOC_MAX_CHARS")


class VerificationJudgment(BaseModel):
    """Structured verdict from the agent verification call."""

    verdict: Literal["CURRENT", "STALE", "UNCERTAIN"] = Field(
        description="CURRENT: doc is accurate given the diff. STALE: doc is definitely wrong. UNCERTAIN: cannot determine without more context."
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="How confident the agent is in its verdict."
    )
    evidence: str = Field(
        description="≤200 chars. What in the diff or doc triggered this verdict."
    )
    proposed_fix: str | None = Field(
        default=None,
        description="For STALE verdicts: the replacement text or specific edit to apply to the coupled doc. None for CURRENT or UNCERTAIN."
    )
    escalate: bool = Field(
        default=False,
        description="True when the situation requires human review (always True for UNCERTAIN, may be True for STALE when proposed_fix is None)."
    )

    @model_validator(mode="after")
    def check_consistency(self) -> "VerificationJudgment":
        """Enforce cross-field consistency rules."""
        if self.verdict == "CURRENT":
            if self.proposed_fix is not None:
                raise ValueError("CURRENT verdict must have proposed_fix=None")
        if self.verdict == "UNCERTAIN":
            if not self.escalate:
                raise ValueError("UNCERTAIN verdict must have escalate=True")
        return self


def truncate_with_note(text: str, max_chars: int, label: str) -> tuple[str, bool]:
    """Truncate text to max_chars and append a note if truncated."""
    if len(text) <= max_chars:
        return text, False
    truncated = text[:max_chars]
    note = f"\n\n[{label} TRUNCATED at {max_chars} chars — {len(text) - max_chars} chars omitted]"
    return truncated + note, True


def build_context_package(request: VerificationRequest) -> str:
    """Build the user-turn content for the LLM call.

    Returns a compact string containing diff and doc with truncation notes.
    """
    diff_note = " (TRUNCATED)" if request.source_diff_truncated else ""
    doc_note = " (TRUNCATED)" if request.doc_truncated else ""

    return f"""## Coupling
ID: {request.coupling_id}
Policy: {request.coupling_description}

## Source Change (git diff){diff_note}
```diff
{request.source_diff}
```

## Coupled Documentation{doc_note}
```
{request.coupled_doc_text}
```

## Task
Based on the source change above, determine whether the coupled documentation
is still accurate. Produce a VerificationJudgment with:
- verdict: CURRENT (doc still accurate), STALE (doc is wrong/outdated), or UNCERTAIN (cannot tell)
- confidence: high, medium, or low
- evidence: ≤200 chars explaining what triggered your verdict
- proposed_fix: if STALE, the specific text edit to fix the doc; otherwise null
- escalate: true if UNCERTAIN or if STALE but you cannot propose a safe fix
"""


def _load_llm_client():
    """Import llm_client lazily to allow tests to run without it installed."""
    try:
        from llm_client import call_llm_structured  # type: ignore[import]
        return call_llm_structured
    except ImportError:
        return None


SYSTEM_PROMPT = """You are a documentation governance agent. Your job is to determine
whether a piece of coupled documentation is still accurate after a source code change.

Coupling policy: validated couplings mean the documentation should reflect the
current behavior or contract of the source. When in doubt, err toward UNCERTAIN
rather than guessing.

Verdict taxonomy:
- CURRENT: the documentation accurately describes the current state. No action needed.
- STALE: the documentation is definitely inaccurate given the change. Propose a fix.
- UNCERTAIN: you cannot determine accuracy without more context. Escalate to human.

Your response must be valid JSON matching the VerificationJudgment schema."""


def verify_coupling(
    request: VerificationRequest,
    model: str | None = None,
    max_budget: float = DEFAULT_MAX_BUDGET,
    trace_id: str | None = None,
) -> VerificationJudgment:
    """Call the LLM to verify a single validated coupling.

    Args:
        request: Context package for the coupling check.
        model: Model override. Defaults to DEFAULT_MODEL or VERIFY_COUPLING_MODEL env var.
        max_budget: Cost ceiling in USD. Defaults to DEFAULT_MAX_BUDGET.
        trace_id: Optional trace ID for llm_client observability.

    Returns:
        VerificationJudgment with verdict, confidence, evidence, fix, escalate.

    Raises:
        RuntimeError: If llm_client is not available.
        ValueError: If the LLM returns an invalid judgment.
    """
    call_llm_structured = _load_llm_client()
    if call_llm_structured is None:
        raise RuntimeError("llm_client not installed. pip install -e ~/projects/llm_client")

    effective_model = model or os.getenv("VERIFY_COUPLING_MODEL") or DEFAULT_MODEL
    user_content = build_context_package(request)

    judgment, _llm_result = call_llm_structured(
        model=effective_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_model=VerificationJudgment,
        task="verify_validated_coupling",
        trace_id=trace_id or f"verify-{request.coupling_id[:40]}",
        max_budget=max_budget,
    )
    return judgment


def prepare_request(
    coupling_id: str,
    coupling_description: str,
    source_diff: str,
    doc_path: Path,
) -> VerificationRequest:
    """Build a VerificationRequest from raw inputs, applying truncation."""
    truncated_diff, diff_was_truncated = truncate_with_note(
        source_diff, DIFF_MAX_CHARS, "DIFF"
    )
    doc_text = doc_path.read_text(encoding="utf-8") if doc_path.exists() else f"[File not found: {doc_path}]"
    truncated_doc, doc_was_truncated = truncate_with_note(
        doc_text, DOC_MAX_CHARS, "DOC"
    )
    return VerificationRequest(
        coupling_id=coupling_id,
        coupling_description=coupling_description,
        source_diff=truncated_diff,
        coupled_doc_text=truncated_doc,
        source_diff_truncated=diff_was_truncated,
        doc_truncated=doc_was_truncated,
    )


def main() -> int:
    """Entry point for CLI usage."""
    parser = argparse.ArgumentParser(description="Verify a validated coupling via LLM agent")
    parser.add_argument("--coupling-id", required=True, help="Human-readable coupling ID")
    parser.add_argument("--description", required=True, help="Coupling description from relationships.yaml")
    parser.add_argument("--diff-file", type=Path, required=True, help="Path to git diff file")
    parser.add_argument("--doc-path", type=Path, required=True, help="Path to coupled doc")
    parser.add_argument("--model", help=f"LLM model (default: {DEFAULT_MODEL})")
    parser.add_argument("--max-budget", type=float, default=DEFAULT_MAX_BUDGET, help="Cost ceiling USD")
    parser.add_argument("--trace-id", help="Trace ID for observability")
    args = parser.parse_args()

    if not args.diff_file.exists():
        print(f"Error: diff file not found: {args.diff_file}", file=sys.stderr)
        return 1
    if not args.doc_path.exists():
        print(f"Warning: doc not found: {args.doc_path}", file=sys.stderr)

    source_diff = args.diff_file.read_text(encoding="utf-8")
    request = prepare_request(args.coupling_id, args.description, source_diff, args.doc_path)

    try:
        judgment = verify_coupling(request, model=args.model, max_budget=args.max_budget, trace_id=args.trace_id)
    except Exception as exc:
        print(f"Error: verification failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(judgment.model_dump(), indent=2))
    return 0 if judgment.verdict == "CURRENT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
