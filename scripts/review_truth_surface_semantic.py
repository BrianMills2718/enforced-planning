#!/usr/bin/env python3
"""Run optional semantic review on truth-surface outputs.

This entrypoint sits on top of the deterministic validator. It summarizes the
existing measured state, gathers a bounded evidence bundle, and asks a shared
LLM runtime for structured advisory findings. The result is intentionally
advisory-only for the first slice: it must never collapse into the same
certainty class as deterministic failures.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts" / "truth_surface_semantic_review.yaml"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_truth_surface_drift import (  # noqa: E402
    Issue,
    _load_structured,
    _load_yaml,
    _resolve_surface_path,
    run_checks,
)
from scripts.truth_surface_semantic_models import (  # noqa: E402
    SemanticReviewReport,
)


def _load_llm_client_exports() -> tuple[Any, Any]:
    """Import shared llm_client entrypoints or fail loud with setup guidance."""
    try:
        from llm_client import call_llm_structured, render_prompt  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised in unit tests via helper
        raise RuntimeError(
            "Semantic truth-surface review requires shared llm_client to be installed in the active environment and expose call_llm_structured/render_prompt."
        ) from exc
    return call_llm_structured, render_prompt


def _serialize_issues(issues: list[Issue]) -> list[dict[str, Any]]:
    """Convert deterministic issues into a JSON-safe payload for prompts and output."""
    return [
        {
            "code": issue.code,
            "severity": issue.severity,
            "message": issue.message,
            "evidence": issue.evidence,
        }
        for issue in issues
    ]


def _collect_registry_summary(registry: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded summary of mutable coordination state for semantic review."""
    active_work = registry.get("active_work") or []
    reservations = registry.get("plan_reservations") or []
    active_claims = [item for item in active_work if isinstance(item, dict) and item.get("status") == "active"]
    consumed = [item for item in reservations if isinstance(item, dict) and item.get("status") == "consumed"]
    return {
        "active_work_count": len(active_work),
        "active_claim_count": len(active_claims),
        "plan_reservation_count": len(reservations),
        "consumed_reservation_count": len(consumed),
        "active_projects": sorted(
            {
                item.get("project")
                for item in active_claims
                if isinstance(item.get("project"), str) and item.get("project")
            }
        ),
    }


def _collect_evidence_surfaces(config: dict[str, Any], *, config_dir: Path, max_chars: int) -> list[dict[str, str]]:
    """Collect a bounded evidence bundle from configured truth surfaces.

    The first slice intentionally prefers concise excerpts over full raw files so
    semantic review stays cheap and reviewable.
    """
    surfaces = config.get("surfaces", {}) if isinstance(config, dict) else {}
    evidence_paths: list[tuple[str, Path]] = []
    for key in ("tracker_file", "plan_index_file"):
        value = surfaces.get(key)
        if isinstance(value, str) and value.strip():
            evidence_paths.append((key, _resolve_surface_path(value, base_dir=config_dir)))

    audit_rules = (((config.get("checks") or {}).get("audit_claim_rules") or {}).get("rules") or [])
    for rule in audit_rules:
        if not isinstance(rule, dict):
            continue
        audit_file = rule.get("audit_file")
        if isinstance(audit_file, str) and audit_file.strip():
            evidence_paths.append(("audit_file", _resolve_surface_path(audit_file, base_dir=config_dir)))

    seen: set[Path] = set()
    bundle: list[dict[str, str]] = []
    for label, path in evidence_paths:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        text = path.read_text()
        excerpt = text[:max_chars]
        if len(text) > max_chars:
            excerpt += "\n... [truncated]"
        bundle.append({
            "label": label,
            "path": str(path),
            "content_excerpt": excerpt,
        })
    return bundle


def build_semantic_review_context(config_path: Path, *, max_evidence_chars: int = 4000) -> dict[str, Any]:
    """Build the bounded semantic-review context from deterministic truth surfaces."""
    from scripts.render_truth_surface_status import render_status

    config_path = config_path.expanduser().resolve()
    config = _load_yaml(config_path)
    issues = run_checks(config_path)
    rendered = render_status(issues)
    config_dir = config_path.parent
    registry_path = _resolve_surface_path(config["surfaces"]["registry_file"], base_dir=config_dir)
    registry = _load_structured(registry_path) or {}
    if not isinstance(registry, dict):
        raise ValueError(f"Expected mapping in registry file {registry_path}")

    return {
        "config_path": str(config_path),
        "rendered_status": rendered,
        "deterministic_issues": _serialize_issues(issues),
        "registry_summary": _collect_registry_summary(registry),
        "evidence_surfaces": _collect_evidence_surfaces(
            config,
            config_dir=config_dir,
            max_chars=max_evidence_chars,
        ),
    }


def review_truth_surface_semantic(
    config_path: Path,
    *,
    model: str,
    max_budget: float,
    trace_id: str,
    max_evidence_chars: int = 4000,
) -> tuple[SemanticReviewReport, dict[str, Any]]:
    """Run the semantic review and return the parsed report plus metadata."""
    call_llm_structured, render_prompt = _load_llm_client_exports()
    context = build_semantic_review_context(config_path, max_evidence_chars=max_evidence_chars)
    messages = render_prompt(
        template_path=PROMPT_PATH,
        rendered_status=context["rendered_status"],
        deterministic_issues_json=json.dumps(context["deterministic_issues"], indent=2, sort_keys=True),
        registry_summary_json=json.dumps(context["registry_summary"], indent=2, sort_keys=True),
        evidence_surfaces_json=json.dumps(context["evidence_surfaces"], indent=2, sort_keys=True),
    )
    review, meta = call_llm_structured(
        model,
        messages,
        response_model=SemanticReviewReport,
        task="enforced_planning.truth_surface.semantic_review",
        trace_id=trace_id,
        max_budget=max_budget,
    )
    payload = {
        "model": model,
        "trace_id": trace_id,
        "max_budget": max_budget,
        "config_path": context["config_path"],
        "deterministic_issues": context["deterministic_issues"],
        "registry_summary": context["registry_summary"],
        "evidence_surfaces": context["evidence_surfaces"],
        "review": review.model_dump(mode="json"),
        "meta": {
            "cost": getattr(meta, "cost", None),
            "model": getattr(meta, "model", None),
        },
    }
    return review, payload


def load_semantic_review_payload(path: Path) -> SemanticReviewReport:
    """Load a semantic review JSON payload from disk."""
    payload = json.loads(path.read_text())
    review = payload.get("review", payload)
    return SemanticReviewReport.model_validate(review)


def main() -> int:
    """CLI entrypoint for semantic truth-surface review."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to a truth_surface_drift.yaml config")
    parser.add_argument(
        "--model",
        default="gemini/gemini-2.5-flash",
        help="Reviewer model identifier",
    )
    parser.add_argument(
        "--max-budget",
        type=float,
        default=0.50,
        help="Per-review USD budget ceiling passed to llm_client",
    )
    parser.add_argument(
        "--trace-id",
        default="enforced_planning/semantic_truth_surface_review",
        help="Trace ID for shared observability",
    )
    parser.add_argument(
        "--max-evidence-chars",
        type=int,
        default=4000,
        help="Maximum characters to include from each evidence surface",
    )
    parser.add_argument("--output-json", help="Optional output file for the review payload")
    args = parser.parse_args()

    review, payload = review_truth_surface_semantic(
        Path(args.config),
        model=args.model,
        max_budget=args.max_budget,
        trace_id=args.trace_id,
        max_evidence_chars=args.max_evidence_chars,
    )

    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output_json:
        Path(args.output_json).expanduser().write_text(rendered + "\n")
    else:
        print(rendered)

    if review.findings:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
