#!/usr/bin/env python3
"""Promote stable LLM semantic findings into candidate deterministic checks.

Reads semantic review findings from docs/ops/semantic_review_findings.yaml
and identifies findings that are candidates for promotion to deterministic
checks (promotion_candidate=True). Stable findings — those appearing in
multiple review runs without being resolved — are strongest candidates.

Output:
    Prints a report of promotion candidates ranked by stability (run count).
    For candidates above the stability threshold, prints a check scaffold
    that can be turned into a new script in scripts/.

Usage:
    python promote_to_deterministic.py
    python promote_to_deterministic.py --findings docs/ops/semantic_review_findings.yaml
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


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _fingerprint(finding: dict[str, Any]) -> str:
    """Build a stable fingerprint for a finding (for grouping across runs)."""
    # Use doc_path + finding_type as the fingerprint key
    # suggested_check may be None or vary slightly between runs
    doc = finding.get("doc_path", "")
    ftype = finding.get("finding_type", "")
    suggested = (finding.get("suggested_check") or "").strip()[:100]
    return f"{doc}|{ftype}|{suggested}"


def load_findings(findings_path: Path) -> list[dict[str, Any]]:
    """Load all review runs from the findings YAML file.

    Returns a flat list of finding dicts, each annotated with 'run_index'.
    """
    if not findings_path.exists():
        return []
    content = findings_path.read_text(encoding="utf-8").strip()
    if not content:
        return []
    data = yaml.safe_load(content)
    if not isinstance(data, list):
        return []

    flat: list[dict[str, Any]] = []
    for run_idx, run in enumerate(data):
        if not isinstance(run, dict):
            continue
        for finding in run.get("findings", []):
            if not isinstance(finding, dict):
                continue
            if finding.get("promotion_candidate"):
                flat.append({**finding, "_run_index": run_idx, "_run_repo": run.get("repo", "")})
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
    severity_order = {"critical": 0, "important": 1, "advisory": 2}

    def sort_key(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, int]:
        _, findings = item
        severity = findings[0].get("severity", "advisory")
        return (-len(findings), severity_order.get(severity, 99))

    return sorted(groups.items(), key=sort_key)


def generate_scaffold(finding: dict[str, Any]) -> str:
    """Generate a Python check scaffold for a promotable finding."""
    doc = finding.get("doc_path", "UNKNOWN")
    finding_type = finding.get("finding_type", "UNKNOWN")
    suggested = finding.get("suggested_check") or "(no suggested check text)"
    evidence = finding.get("evidence", "")[:200]

    return f"""\
#!/usr/bin/env python3
\"\"\"Deterministic check: promoted from semantic review finding.

Origin:
    Finding type: {finding_type}
    Doc: {doc}
    Evidence: {evidence}
    LLM suggested check: {suggested}

Promoted by: promote_to_deterministic.py
\"\"\"

import sys

# TODO: implement this deterministic check based on the suggested_check above.
# Return exit code 0 on pass, 1 on failure.

def main() -> int:
    print("TODO: implement {finding_type} check for {doc}")
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
                f"  [{f['severity'].upper()}] {f['finding_type']}"
                f" — {f['doc_path']} ({len(findings)} run(s))"
            )
            lines.append(f"  Evidence: {f['evidence'][:120]}...")
            if f.get("suggested_check"):
                lines.append(f"  Check: {f['suggested_check']}")
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
                f"  [{f['severity'].upper()}] {f['finding_type']}"
                f" — {f['doc_path']} ({len(findings)} run(s))"
            )
            if f.get("suggested_check"):
                lines.append(f"  Check: {f['suggested_check']}")
            lines.append("")

    lines.append(
        f"Total promotion candidates: {len(ranked)} ({len(stable)} stable, {len(unstable)} unstable)"
    )
    lines.append(
        f"To increase stability: run `make review-surfaces` periodically and re-check."
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
        default=Path("docs/ops/semantic_review_findings.yaml"),
        help="Path to semantic review findings YAML",
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
