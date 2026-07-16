"""Generate a compact active-work registry from live coordination claims.

The registry is a derivative runtime surface, not a source of truth. Claim YAML
files under ``~/.claude/coordination/claims/`` remain canonical. This module
groups live claims into human-readable execution lanes, computes interaction
notes, and writes both machine-readable and compact markdown views.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from enforced_planning import coordination_claims


DEFAULT_JSON_OUTPUT = Path("generated/runtime/active_work_registry.json")
DEFAULT_MARKDOWN_OUTPUT = Path("generated/runtime/active_work_registry.md")


def _lane_group_key(
    claim: coordination_claims.ClaimRecord,
) -> tuple[str, str, str, str, str, str]:
    """Return the grouping key for one derived execution lane.

    Claims with concrete execution metadata group by project, plan, branch, and
    worktree so multiple write/review/research claims in one worktree render as
    one operator-facing lane. Legacy or weak claims without branch/worktree
    metadata fall back to scope-level grouping so unrelated broad claims do not
    collapse together.
    """

    project = claim.primary_project() or "(none)"
    plan_ref = claim.plan_ref or "-"
    branch = claim.branch or "-"
    worktree_path = claim.worktree_path or "-"
    if claim.branch or claim.worktree_path:
        return ("execution", project, plan_ref, branch, worktree_path, "-")
    return ("scope", project, plan_ref, claim.parent_scope or "-", "-", claim.scope)


def _lane_id_from_key(key: tuple[str, str, str, str, str, str]) -> str:
    """Return a stable readable identifier for one derived lane."""

    mode, project, plan_ref, branch_or_parent, worktree_path, scope = key
    if mode == "execution":
        branch_text = branch_or_parent if branch_or_parent != "-" else "no-branch"
        worktree_text = Path(worktree_path).name if worktree_path != "-" else "no-worktree"
        return f"{project}:{plan_ref}:{branch_text}:{worktree_text}"
    parent_text = branch_or_parent if branch_or_parent != "-" else "no-parent"
    return f"{project}:{plan_ref}:{parent_text}:{scope}"


def build_lane_entries(*, claim_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse claim-level entries into lane-level operator summaries."""

    grouped: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for claim in claim_entries:
        record = coordination_claims.ClaimRecord(
            agent=claim["agent"],
            claimed_at=claim.get("claimed_at"),
            expires_at=claim.get("expires_at"),
            projects=claim.get("projects") or ([claim["project"]] if claim.get("project") else []),
            scope=claim["scope"],
            intent=claim["intent"],
            claim_type=claim["claim_type"],
            write_paths=claim.get("write_paths") or [],
            read_paths=claim.get("read_paths") or [],
            worktree_path=claim.get("worktree_path"),
            repo_root=claim.get("repo_root"),
            branch=claim.get("branch"),
            session_name=claim.get("session_name"),
            broader_goal=claim.get("broader_goal"),
            tracker_path=claim.get("tracker_path"),
            session_id=claim.get("session_id"),
            heartbeat_at=claim.get("heartbeat_at"),
            status=claim["status"],
            updated_at=claim.get("updated_at"),
            parent_scope=claim.get("parent_scope"),
            notes=claim.get("notes"),
            plan_ref=claim.get("plan_ref"),
            source_file=claim.get("source_file"),
            schema_version=claim.get("schema_version") or 2,
        )
        grouped.setdefault(_lane_group_key(record), []).append(claim)

    lanes: list[dict[str, Any]] = []
    for key, items in sorted(grouped.items(), key=lambda item: item[0]):
        mode, project, plan_ref, branch_or_parent, worktree_path, scope = key
        hard_conflicts = sum(item["interaction_summary"]["hard_conflict_count"] for item in items)
        soft_overlaps = sum(item["interaction_summary"]["soft_overlap_count"] for item in items)
        informational = sum(item["interaction_summary"]["informational_count"] for item in items)
        health_issues = sorted({issue for item in items for issue in item["health_issues"]})
        lifecycle_issues = sorted({issue for item in items for issue in item.get("lifecycle_issues", [])})
        liveness_issues = sorted({issue for item in items for issue in item.get("liveness_issues", [])})
        health_status = "healthy"
        if lifecycle_issues or liveness_issues:
            health_status = "stale"
        elif health_issues:
            health_status = "weak"
        elif hard_conflicts:
            health_status = "attention"
        elif soft_overlaps:
            health_status = "warning"
        lanes.append(
            {
                "lane_id": _lane_id_from_key(key),
                "grouping_mode": mode,
                "project": None if project == "(none)" else project,
                "plan_ref": None if plan_ref == "-" else plan_ref,
                "branch": None if mode != "execution" or branch_or_parent == "-" else branch_or_parent,
                "worktree_path": None if mode != "execution" or worktree_path == "-" else worktree_path,
                "parent_scope": None if mode != "scope" or branch_or_parent == "-" else branch_or_parent,
                "fallback_scope": None if mode != "scope" or scope == "-" else scope,
                "claim_count": len(items),
                "claim_types": sorted({item["claim_type"] for item in items}),
                "agents": sorted({item["agent"] for item in items}),
                "scopes": sorted({item["scope"] for item in items}),
                "write_paths": sorted({path for item in items for path in item["write_paths"]}),
                "status_set": sorted({item["status"] for item in items}),
                "health_status": health_status,
                "health_issues": health_issues,
                "lifecycle_issues": lifecycle_issues,
                "liveness_issues": liveness_issues,
                "interaction_summary": {
                    "hard_conflict_count": hard_conflicts,
                    "soft_overlap_count": soft_overlaps,
                    "informational_count": informational,
                },
            }
        )
    return lanes


def build_plan_hierarchy_entries(
    *,
    claim_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive normalized plan roots and child scopes from canonical claims."""

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for claim in claim_entries:
        project = claim.get("project")
        plan_identity = coordination_claims.normalize_plan_identity(claim.get("plan_ref"))
        if not project or not plan_identity or not claim.get("session_id"):
            continue
        grouped.setdefault((project, plan_identity), []).append(claim)

    entries: list[dict[str, Any]] = []
    for (project, plan_identity), claims in sorted(grouped.items()):
        roots = [
            claim
            for claim in claims
            if claim["claim_type"] == "program" and not claim.get("parent_scope")
        ]
        root_scope = roots[0]["scope"] if len(roots) == 1 else None
        root_scopes = {claim["scope"] for claim in roots}
        health_issues = sorted(
            {
                issue
                for claim in claims
                for issue in claim.get("hierarchy_issues", [])
            }
        )
        health_status = "weak" if health_issues else "healthy"
        entries.append(
            {
                "project": project,
                "plan_identity": plan_identity,
                "root_scope": root_scope,
                "root_count": len(roots),
                "child_scopes": sorted(
                    claim["scope"] for claim in claims if claim["scope"] not in root_scopes
                ),
                "claim_count": len(claims),
                "health_status": health_status,
                "health_issues": health_issues,
            }
        )
    return entries


def build_registry_payload(
    *,
    claims: list[coordination_claims.ClaimRecord],
) -> dict[str, object]:
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
    stale_claim_count = 0
    weak_claim_count = 0
    hard_conflict_claim_count = 0
    soft_overlap_claim_count = 0
    for claim in sorted_claims:
        check_result = coordination_claims.evaluate_claim(claim, active_claims=sorted_claims)
        entry = claim.to_dict()
        health_issues = coordination_claims.coordination_health_issues(
            claim,
            active_claims=sorted_claims,
        )
        hierarchy_issues = coordination_claims.claim_hierarchy_issues(
            claim,
            active_claims=sorted_claims,
        )
        lifecycle_issues = coordination_claims.claim_lifecycle_issues(claim)
        liveness_issues = coordination_claims.claim_liveness_issues(claim)
        entry["interaction_summary"] = {
            "hard_conflict_count": sum(1 for item in check_result.interactions if item.severity == "hard_conflict"),
            "soft_overlap_count": sum(1 for item in check_result.interactions if item.severity == "soft_overlap"),
            "informational_count": sum(1 for item in check_result.interactions if item.severity == "informational"),
        }
        entry["health_status"] = coordination_claims.claim_runtime_status(
            claim,
            active_claims=sorted_claims,
        )
        entry["health_issues"] = health_issues
        entry["hierarchy_issues"] = hierarchy_issues
        entry["lifecycle_issues"] = lifecycle_issues
        entry["liveness_issues"] = liveness_issues
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
        if lifecycle_issues or liveness_issues:
            stale_claim_count += 1
        elif health_issues:
            weak_claim_count += 1
        if entry["interaction_summary"]["hard_conflict_count"] > 0:
            hard_conflict_claim_count += 1
        if entry["interaction_summary"]["soft_overlap_count"] > 0:
            soft_overlap_claim_count += 1
        claim_entries.append(entry)

    lane_entries = build_lane_entries(claim_entries=claim_entries)
    plan_hierarchy_entries = build_plan_hierarchy_entries(claim_entries=claim_entries)
    lanes_by_project = Counter((lane["project"] or "(none)") for lane in lane_entries)

    overall_status = "idle"
    if claim_entries:
        if stale_claim_count or weak_claim_count or hard_conflict_claim_count:
            overall_status = "attention"
        elif soft_overlap_claim_count:
            overall_status = "warning"
        else:
            overall_status = "healthy"

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "claim_count": len(claim_entries),
        "lane_count": len(lane_entries),
        "claims_by_type": dict(sorted(claims_by_type.items())),
        "claims_by_project": dict(sorted(claims_by_project.items())),
        "lanes_by_project": dict(sorted(lanes_by_project.items())),
        "health_summary": {
            "overall_status": overall_status,
            "stale_claim_count": stale_claim_count,
            "weak_claim_count": weak_claim_count,
            "hard_conflict_claim_count": hard_conflict_claim_count,
            "soft_overlap_claim_count": soft_overlap_claim_count,
        },
        "lanes": lane_entries,
        "plan_hierarchies": plan_hierarchy_entries,
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
        f"Live lanes: `{payload['lane_count']}`",
        f"Live claims: `{payload['claim_count']}`",
        "",
        "## Coordination Health",
        "",
        f"- Overall status: `{payload['health_summary']['overall_status']}`",
        f"- Stale claims: `{payload['health_summary']['stale_claim_count']}`",
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

    lines.extend(["", "## Plan Hierarchies", ""])
    if payload["plan_hierarchies"]:
        lines.append("| Project | Plan | Root | Children | Claims | Health |")
        lines.append("|---|---|---|---|---|---|")
        for hierarchy in payload["plan_hierarchies"]:
            health = hierarchy["health_status"]
            if hierarchy["health_issues"]:
                health = f"{health} ({', '.join(hierarchy['health_issues'])})"
            lines.append(
                "| {project} | {plan} | {root} | {children} | {count} | {health} |".format(
                    project=hierarchy["project"],
                    plan=hierarchy["plan_identity"],
                    root=hierarchy["root_scope"] or "-",
                    children=", ".join(hierarchy["child_scopes"]) or "-",
                    count=hierarchy["claim_count"],
                    health=health,
                )
            )
    else:
        lines.append("No live numbered-plan session claims.")

    lines.extend(["", "## Active Lanes", ""])
    lines.append("Lanes are derived summaries. Individual claim files remain the canonical coordination source.")
    lines.append("")
    if payload["lanes"]:
        lines.append("| Project | Plan | Branch | Worktree | Claims | Agents | Types | Scopes | Health | Interactions |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for lane in payload["lanes"]:
            interactions = lane["interaction_summary"]
            interaction_text = (
                f"hard={interactions['hard_conflict_count']}, "
                f"soft={interactions['soft_overlap_count']}, "
                f"info={interactions['informational_count']}"
            )
            health = lane["health_status"]
            if lane.get("lifecycle_issues"):
                health = f"{health} ({', '.join(lane['lifecycle_issues'])})"
            if lane.get("liveness_issues"):
                health = f"{health} ({', '.join(lane['liveness_issues'])})"
            if lane["health_issues"]:
                health = f"{health} ({', '.join(lane['health_issues'])})"
            lines.append(
                "| {project} | {plan_ref} | {branch} | {worktree} | {claim_count} | {agents} | {claim_types} | {scopes} | {health} | {interaction_text} |".format(
                    project=lane.get("project") or "-",
                    plan_ref=lane.get("plan_ref") or "-",
                    branch=lane.get("branch") or "-",
                    worktree=lane.get("worktree_path") or (lane.get("fallback_scope") or "-"),
                    claim_count=lane["claim_count"],
                    agents=", ".join(lane["agents"]) or "-",
                    claim_types=", ".join(lane["claim_types"]) or "-",
                    scopes=", ".join(lane["scopes"]) or "-",
                    health=health,
                    interaction_text=interaction_text,
                )
            )
    else:
        lines.append("No live lanes.")

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
        if claim.get("lifecycle_issues"):
            health = f"{health} ({', '.join(claim['lifecycle_issues'])})"
        if claim.get("liveness_issues"):
            health = f"{health} ({', '.join(claim['liveness_issues'])})"
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
        if not claim.get("lifecycle_issues") and not claim.get("liveness_issues") and not claim["health_issues"]:
            continue
        any_health_notes = True
        lines.append(
            f"- `{claim['agent']}` / `{claim.get('project') or '-'}` / `{claim['scope']}` is `{claim['health_status']}`: "
            + ", ".join((claim.get("lifecycle_issues") or []) + (claim.get("liveness_issues") or []) + claim["health_issues"])
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


def refresh_registry(
    *,
    claims_dir: Path | None = None,
    json_output: Path = DEFAULT_JSON_OUTPUT,
    markdown_output: Path = DEFAULT_MARKDOWN_OUTPUT,
) -> dict[str, Any]:
    """Regenerate the registry and return the payload.

    The claims directory override is temporary and restored before returning so
    callers can refresh one repo's derivative outputs without mutating global
    module state permanently.
    """

    previous_claims_dir = coordination_claims.CLAIMS_DIR
    try:
        if claims_dir is not None:
            coordination_claims.CLAIMS_DIR = claims_dir
        payload = build_registry_payload(claims=coordination_claims.check_claims())
        write_registry_outputs(
            payload=payload,
            json_output=json_output,
            markdown_output=markdown_output,
        )
        return payload
    finally:
        coordination_claims.CLAIMS_DIR = previous_claims_dir


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
    json_output = Path(args.json_output).expanduser().resolve()
    markdown_output = Path(args.markdown_output).expanduser().resolve()
    payload = refresh_registry(
        claims_dir=Path(args.claims_dir).expanduser().resolve() if args.claims_dir else None,
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
