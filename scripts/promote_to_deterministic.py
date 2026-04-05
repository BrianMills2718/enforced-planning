#!/usr/bin/env python3
"""Promote stable semantic-review findings into candidate deterministic checks.

Reads semantic review history from the canonical config-driven semantic-review
payloads and identifies findings that are candidates for promotion to
deterministic checks (promotion_candidate=True). Stable findings — those
appearing in multiple review runs without being resolved — are strongest
candidates.

Output:
    Prints a report of promotion candidates ranked by stability (run count).
    For candidates above the stability threshold, prints a check scaffold
    that can be turned into a new script in scripts/.

Usage:
    python promote_to_deterministic.py
    python promote_to_deterministic.py --findings docs/ops/semantic_truth_surface_review_history.json
    python promote_to_deterministic.py --min-runs 2    # only stable findings
    python promote_to_deterministic.py --scaffold      # emit check scaffolds
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed — pip install pyyaml", file=sys.stderr)
    sys.exit(2)


DEFAULT_FINDINGS_PATH = Path("docs/ops/semantic_truth_surface_review_history.json")

def _fingerprint(finding: dict[str, Any]) -> str:
    """Build a stable fingerprint for a finding (for grouping across runs)."""
    surface = finding.get("surface_ref", "")
    kind = finding.get("kind", "")
    rule_hint = (finding.get("rule_hint") or "").strip()[:160]
    return f"{surface}|{kind}|{rule_hint}"


def _load_structured(path: Path) -> Any:
    """Load JSON first, then YAML as a legacy fallback."""
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return yaml.safe_load(content)


def _normalize_legacy_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Normalize one legacy repo-wide semantic finding."""
    return {
        "kind": finding.get("finding_type", ""),
        "severity": finding.get("severity", "advisory"),
        "surface_ref": finding.get("doc_path", ""),
        "summary": finding.get("suggested_fix") or finding.get("evidence", ""),
        "evidence": finding.get("evidence", ""),
        "rule_hint": finding.get("suggested_check") or "",
        "promotion_candidate": bool(finding.get("promotion_candidate")),
    }


def _normalize_canonical_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """Normalize one canonical config-driven semantic finding."""
    evidence_refs = finding.get("evidence_refs") or []
    surface_ref = ", ".join(evidence_refs[:2]) if isinstance(evidence_refs, list) else ""
    return {
        "kind": finding.get("category", ""),
        "severity": finding.get("severity", "info"),
        "surface_ref": surface_ref,
        "summary": finding.get("summary", ""),
        "evidence": finding.get("rationale", ""),
        "rule_hint": finding.get("promotion_rule_hint") or "",
        "promotion_candidate": bool(finding.get("promotion_candidate")),
    }


def _iter_runs(raw: Any) -> list[dict[str, Any]]:
    """Normalize raw findings/history data into a list of run dictionaries."""
    if isinstance(raw, list):
        return [run for run in raw if isinstance(run, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def load_findings(findings_path: Path) -> list[dict[str, Any]]:
    """Load all review runs from canonical or legacy semantic-review files.

    Returns a flat list of finding dicts, each annotated with 'run_index'.
    """
    if not findings_path.exists():
        return []
    data = _load_structured(findings_path)

    flat: list[dict[str, Any]] = []
    for run_idx, run in enumerate(_iter_runs(data)):
        findings = run.get("findings", [])
        if "review" in run and isinstance(run["review"], dict):
            findings = run["review"].get("findings", [])

        for finding in findings:
            if not isinstance(finding, dict):
                continue
            if "category" in finding:
                normalized = _normalize_canonical_finding(finding)
            else:
                normalized = _normalize_legacy_finding(finding)
            if normalized.get("promotion_candidate"):
                flat.append(
                    {
                        **normalized,
                        "_run_index": run_idx,
                        "_run_repo": run.get("repo", run.get("config_path", "")),
                    }
                )
    return flat


def group_by_fingerprint(
    findings: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group promotion-candidate findings by fingerprint."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in findings:
        groups[_fingerprint(f)].append(f)
    return dict(groups)


def rank_candidates(
    groups: dict[str, list[dict[str, Any]]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Return groups sorted by stability (count, then severity)."""
    severity_order = {
        "critical": 0,
        "important": 1,
        "warn": 2,
        "advisory": 3,
        "info": 4,
    }

    def sort_key(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, int]:
        _, findings = item
        severity = findings[0].get("severity", "advisory")
        return (-len(findings), severity_order.get(severity, 99))

    return sorted(groups.items(), key=sort_key)


def generate_scaffold(finding: dict[str, Any]) -> str:
    """Generate a Python check scaffold for a promotable finding."""
    surface_ref = finding.get("surface_ref", "UNKNOWN")
    finding_type = finding.get("kind", "UNKNOWN")
    suggested = finding.get("rule_hint") or "(no suggested check text)"
    evidence = (finding.get("evidence") or finding.get("summary", ""))[:200]

    return f"""\
#!/usr/bin/env python3
\"\"\"Deterministic check: promoted from semantic review finding.

Origin:
    Finding type: {finding_type}
    Surface: {surface_ref}
    Evidence: {evidence}
    LLM suggested check: {suggested}

Promoted by: promote_to_deterministic.py
\"\"\"

import sys

# TODO: implement this deterministic check based on the suggested_check above.
# Return exit code 0 on pass, 1 on failure.

def main() -> int:
    print("TODO: implement {finding_type} check for {surface_ref}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
"""


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_report(
    ranked: list[tuple[str, list[dict[str, Any]]]],
    min_runs: int,
    scaffold: bool,
) -> str:
    """Format the promotion candidate report."""
    lines = ["# Semantic Finding Promotion Candidates\n"]

    if not ranked:
        lines.append("No promotion candidates found. Run `make review-surfaces` first.")
        return "\n".join(lines)

    stable = [(k, v) for k, v in ranked if len(v) >= min_runs]
    unstable = [(k, v) for k, v in ranked if len(v) < min_runs]

    if stable:
        lines.append(f"## Stable candidates ({min_runs}+ runs) — ready to promote\n")
        for _, findings in stable:
            f = findings[0]
            lines.append(
                f"  [{f['severity'].upper()}] {f['kind']}"
                f" — {f['surface_ref'] or 'unspecified surface'} ({len(findings)} run(s))"
            )
            lines.append(f"  Evidence: {f['evidence'][:120]}...")
            if f.get("rule_hint"):
                lines.append(f"  Check: {f['rule_hint']}")
            if scaffold:
                lines.append("\n--- SCAFFOLD ---")
                lines.append(generate_scaffold(f))
                lines.append("--- END SCAFFOLD ---")
            lines.append("")

    if unstable:
        lines.append(f"## Unstable candidates (<{min_runs} runs) — needs more evidence\n")
        for _, findings in unstable:
            f = findings[0]
            lines.append(
                f"  [{f['severity'].upper()}] {f['kind']}"
                f" — {f['surface_ref'] or 'unspecified surface'} ({len(findings)} run(s))"
            )
            if f.get("rule_hint"):
                lines.append(f"  Check: {f['rule_hint']}")
            lines.append("")

    lines.append(
        f"Total promotion candidates: {len(ranked)} ({len(stable)} stable, {len(unstable)} unstable)"
    )
    lines.append(
        "To increase stability: run `make review-surfaces` periodically and re-check."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Show semantic review findings ready for deterministic promotion"
    )
    parser.add_argument(
        "--findings",
        type=Path,
        default=DEFAULT_FINDINGS_PATH,
        help="Path to semantic review history (canonical JSON, legacy YAML supported)",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=1,
        help="Minimum run count to be considered 'stable' (default: 1)",
    )
    parser.add_argument(
        "--scaffold",
        action="store_true",
        help="Emit check scaffold for stable candidates",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of human-readable report",
    )
    args = parser.parse_args()

    findings_path = args.findings
    if not findings_path.exists():
        print(f"No findings file at {findings_path}. Run `make review-surfaces` first.")
        return 0

    all_findings = load_findings(findings_path)
    groups = group_by_fingerprint(all_findings)
    ranked = rank_candidates(groups)

    if args.json:
        output = [
            {
                "fingerprint": fp,
                "run_count": len(finds),
                "finding": finds[0],
            }
            for fp, finds in ranked
        ]
        print(json.dumps(output, indent=2))
    else:
        print(format_report(ranked, min_runs=args.min_runs, scaffold=args.scaffold))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
