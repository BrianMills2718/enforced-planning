#!/usr/bin/env python3
"""Generate a compact active-work registry from live coordination claims.

The registry is a derivative runtime surface, not a source of truth. Claim YAML
files under ``~/.claude/coordination/claims/`` remain canonical. This script
loads those claims through the existing claim-management module, computes
inter-agent interaction notes, and writes both JSON and compact markdown views.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_JSON_OUTPUT = Path("generated/runtime/active_work_registry.json")
DEFAULT_MARKDOWN_OUTPUT = Path("generated/runtime/active_work_registry.md")


def _load_claims_module() -> Any:
    """Load the sibling coordination-claims script as a module."""
    module_path = Path(__file__).resolve().with_name("check_coordination_claims.py")
    spec = importlib.util.spec_from_file_location("coordination_claims_runtime", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load claims module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_registry_payload(*, claims_module: Any, claims: list[Any]) -> dict[str, Any]:
    """Build the machine-readable registry payload from normalized claim records."""
    sorted_claims = sorted(
        claims,
        key=lambda claim: (
            claim.primary_project() or "",
            claim.claim_type,
            claim.agent,
            claim.scope,
        ),
    )
    claims_by_type = Counter(claim.claim_type for claim in sorted_claims)
    claims_by_project = Counter(claim.primary_project() or "(none)" for claim in sorted_claims)

    claim_entries: list[dict[str, Any]] = []
    weak_claim_count = 0
    hard_conflict_claim_count = 0
    soft_overlap_claim_count = 0
    for claim in sorted_claims:
        check_result = claims_module.evaluate_claim(claim, active_claims=sorted_claims)
        entry = claim.to_dict()
        health_issues = claims_module.claim_health_issues(claim)
        entry["interaction_summary"] = {
            "hard_conflict_count": sum(1 for item in check_result.interactions if item.severity == "hard_conflict"),
            "soft_overlap_count": sum(1 for item in check_result.interactions if item.severity == "soft_overlap"),
            "informational_count": sum(1 for item in check_result.interactions if item.severity == "informational"),
        }
        entry["health_status"] = "weak" if health_issues else "healthy"
        entry["health_issues"] = health_issues
        entry["conflict_notes"] = [
            {
                "severity": item.severity,
                "other_agent": item.other_agent,
                "other_scope": item.other_scope,
                "reason": item.reason,
                "overlapping_write_paths": item.overlapping_write_paths,
            }
            for item in check_result.interactions
        ]
        if health_issues:
            weak_claim_count += 1
        if entry["interaction_summary"]["hard_conflict_count"] > 0:
            hard_conflict_claim_count += 1
        if entry["interaction_summary"]["soft_overlap_count"] > 0:
            soft_overlap_claim_count += 1
        claim_entries.append(entry)

    overall_status = "idle"
    if claim_entries:
        if weak_claim_count or hard_conflict_claim_count:
            overall_status = "attention"
        elif soft_overlap_claim_count:
            overall_status = "warning"
        else:
            overall_status = "healthy"

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_count": len(claim_entries),
        "claims_by_type": dict(sorted(claims_by_type.items())),
        "claims_by_project": dict(sorted(claims_by_project.items())),
        "health_summary": {
            "overall_status": overall_status,
            "weak_claim_count": weak_claim_count,
            "hard_conflict_claim_count": hard_conflict_claim_count,
            "soft_overlap_claim_count": soft_overlap_claim_count,
        },
        "claims": claim_entries,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    """Render a compact human-readable registry view."""
    lines = [
        "# Active Work Registry",
        "",
        "This file is generated from live coordination claims. Do not edit by hand.",
        "",
        f"Generated: `{payload['generated_at_utc']}`",
        f"Live claims: `{payload['claim_count']}`",
        "",
        "## Coordination Health",
        "",
        f"- Overall status: `{payload['health_summary']['overall_status']}`",
        f"- Weak claims: `{payload['health_summary']['weak_claim_count']}`",
        f"- Claims with hard conflicts: `{payload['health_summary']['hard_conflict_claim_count']}`",
        f"- Claims with soft overlaps: `{payload['health_summary']['soft_overlap_claim_count']}`",
        "",
        "## Summary",
        "",
    ]

    if payload["claims_by_type"]:
        for claim_type, count in payload["claims_by_type"].items():
            lines.append(f"- `{claim_type}`: {count}")
    else:
        lines.append("- No live claims.")

    lines.extend(["", "## Active Claims", ""])
    if not payload["claims"]:
        lines.append("No live claims.")
        return "\n".join(lines) + "\n"

    lines.append("| Agent | Project | Type | Scope | Branch | Worktree | Write Paths | Plan | Status | Health | Interactions |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for claim in payload["claims"]:
        interactions = claim["interaction_summary"]
        interaction_text = (
            f"hard={interactions['hard_conflict_count']}, "
            f"soft={interactions['soft_overlap_count']}, "
            f"info={interactions['informational_count']}"
        )
        write_paths = ", ".join(claim["write_paths"]) if claim["write_paths"] else "-"
        health = claim["health_status"]
        if claim["health_issues"]:
            health = f"{health} ({', '.join(claim['health_issues'])})"
        lines.append(
            "| {agent} | {project} | {claim_type} | {scope} | {branch} | {worktree} | {write_paths} | {plan_ref} | {status} | {health} | {interaction_text} |".format(
                agent=claim["agent"],
                project=claim.get("project") or "-",
                claim_type=claim["claim_type"],
                scope=claim["scope"],
                branch=claim.get("branch") or "-",
                worktree=claim.get("worktree_path") or "-",
                write_paths=write_paths,
                plan_ref=claim.get("plan_ref") or "-",
                status=claim["status"],
                health=health,
                interaction_text=interaction_text,
            )
        )

    lines.extend(["", "## Health Notes", ""])
    any_health_notes = False
    for claim in payload["claims"]:
        if not claim["health_issues"]:
            continue
        any_health_notes = True
        lines.append(
            f"- `{claim['agent']}` / `{claim.get('project') or '-'}` / `{claim['scope']}` is `weak`: "
            + ", ".join(claim["health_issues"])
        )
    if not any_health_notes:
        lines.append("No weak live claims detected.")
    lines.append("")

    lines.extend(["", "## Conflict Notes", ""])
    any_notes = False
    for claim in payload["claims"]:
        notes = claim["conflict_notes"]
        if not notes:
            continue
        any_notes = True
        lines.append(f"### `{claim['agent']}` — `{claim.get('project') or '-'}` / `{claim['scope']}`")
        for note in notes:
            overlaps = ", ".join(note["overlapping_write_paths"]) or "none"
            lines.append(
                f"- `{note['severity']}` with `{note['other_agent']}` / `{note['other_scope']}`: {note['reason']} (overlap: {overlaps})"
            )
        lines.append("")
    if not any_notes:
        lines.append("No inter-agent interactions detected.")
        lines.append("")

    return "\n".join(lines)


def write_registry_outputs(
    *,
    payload: dict[str, Any],
    json_output: Path,
    markdown_output: Path,
) -> None:
    """Write the registry payload to JSON and markdown output files."""
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    markdown_output.write_text(render_markdown(payload), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for active-work registry generation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claims-dir",
        help="Override claims directory instead of ~/.claude/coordination/claims/",
    )
    parser.add_argument(
        "--json-output",
        default=str(DEFAULT_JSON_OUTPUT),
        help=f"Path for machine-readable output (default: {DEFAULT_JSON_OUTPUT})",
    )
    parser.add_argument(
        "--markdown-output",
        default=str(DEFAULT_MARKDOWN_OUTPUT),
        help=f"Path for compact markdown output (default: {DEFAULT_MARKDOWN_OUTPUT})",
    )
    parser.add_argument("--stdout-json", action="store_true", help="Print the payload to stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Generate the active-work registry from live coordination claims."""
    args = parse_args(argv)
    claims_module = _load_claims_module()
    if args.claims_dir:
        claims_module.CLAIMS_DIR = Path(args.claims_dir).expanduser().resolve()

    claims = claims_module.check_claims()
    payload = build_registry_payload(claims_module=claims_module, claims=claims)

    json_output = Path(args.json_output).expanduser().resolve()
    markdown_output = Path(args.markdown_output).expanduser().resolve()
    write_registry_outputs(
        payload=payload,
        json_output=json_output,
        markdown_output=markdown_output,
    )

    if args.stdout_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {payload['claim_count']} live claims to {json_output} and {markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
