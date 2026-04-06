#!/usr/bin/env python3
"""Build ecosystem status JSON and rendered Markdown summary.

Reads:
  - governed_repos.yaml (explicit fleet registry)
  - generated/plan_registry.json (cross-repo plan state)
  - generated/ecosystem_dep_map.json (cross-repo dependency map)
  - scripts/audit_governed_repo.py per-repo (classification)

Writes:
  - generated/ecosystem_status.json (machine-readable)
  - docs/ops/ECOSYSTEM_STATUS.md (rendered human summary)

Usage:
    python scripts/ecosystem_status.py
    python scripts/ecosystem_status.py --repo-root /path/to/enforced-planning
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_governed_repos(repo_root: Path) -> list[dict[str, Any]]:
    """Load the explicit fleet registry from governed_repos.yaml."""
    registry_path = repo_root / "governed_repos.yaml"
    if not registry_path.exists():
        raise FileNotFoundError(f"governed_repos.yaml not found at {registry_path}")
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    repos: list[dict[str, Any]] = raw.get("repos", [])
    return repos


def _audit_repo(repo_root: Path, repo_path: Path) -> str:
    """Run audit_governed_repo.py against one repo and return its classification.

    Returns one of: "governed", "partial", "legacy", "not_found", "error".
    "legacy" is used when the repo exists but has no meta-process.yaml at all.
    """
    if not repo_path.exists():
        return "not_found"

    audit_script = repo_root / "scripts" / "audit_governed_repo.py"
    if not audit_script.exists():
        return "error"

    # Use --json for machine-parseable output
    try:
        result = subprocess.run(
            [sys.executable, str(audit_script), "--repo-root", str(repo_path), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "error"
    except OSError:
        return "error"

    stdout = result.stdout.strip()
    if not stdout:
        # Fallback: try human-readable output and parse Classification: line
        try:
            result2 = subprocess.run(
                [sys.executable, str(audit_script), "--repo-root", str(repo_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in result2.stdout.splitlines():
                if line.startswith("Classification:"):
                    return line.split(":", 1)[1].strip().lower()
        except (subprocess.TimeoutExpired, OSError):
            pass
        return "error"

    try:
        report = json.loads(stdout)
        classification = report.get("classification", "").lower()
        if classification in ("governed", "partial", "legacy"):
            return classification
        # Fallback if classification key missing — check status
        status = report.get("status", "").upper()
        return "governed" if status == "PASS" else "partial"
    except (json.JSONDecodeError, KeyError):
        # Parse human-readable output from stdout as last resort
        for line in stdout.splitlines():
            if line.startswith("Classification:"):
                return line.split(":", 1)[1].strip().lower()
        return "error"


def _load_plan_registry(repo_root: Path) -> dict[str, Any]:
    """Load generated/plan_registry.json."""
    path = repo_root / "generated" / "plan_registry.json"
    if not path.exists():
        return {"projects": {}, "total_plans": 0, "complete": 0,
                "in_progress": 0, "planned": 0, "blocked": 0}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_dep_map(repo_root: Path) -> dict[str, Any]:
    """Load generated/ecosystem_dep_map.json."""
    path = repo_root / "generated" / "ecosystem_dep_map.json"
    if not path.exists():
        return {"repos": [], "total_edges": 0, "cross_repo_edges": 0, "dep_graph": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_plan_lists(
    plan_registry: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return (in_progress_list, blocked_list) from the plan registry."""
    in_progress: list[dict[str, str]] = []
    blocked: list[dict[str, str]] = []
    for proj_name, proj_info in plan_registry.get("projects", {}).items():
        for plan in proj_info.get("plans", []):
            entry = {
                "project": proj_name,
                "number": str(plan.get("plan_num", "")),
                "title": plan.get("title", ""),
            }
            status = plan.get("status", "")
            if status == "in_progress":
                in_progress.append(entry)
            elif status == "blocked":
                blocked.append(entry)
    return in_progress, blocked


def build_status(repo_root: Path) -> dict[str, Any]:
    """Build the full ecosystem status payload.

    Runs per-repo governance audits (subprocess), loads plan registry and dep
    map, and returns a dict matching the documented JSON schema.
    """
    governed_repos = _load_governed_repos(repo_root)
    plan_registry = _load_plan_registry(repo_root)
    dep_map = _load_dep_map(repo_root)

    # Per-repo audit
    repo_statuses: list[dict[str, str]] = []
    governed_count = 0
    partial_count = 0
    legacy_count = 0

    for repo_cfg in governed_repos:
        repo_id = str(repo_cfg.get("id", ""))
        tier = str(repo_cfg.get("tier", "governed"))
        raw_path = str(repo_cfg.get("path", ""))
        repo_path = Path(raw_path).expanduser().resolve()

        classification = _audit_repo(repo_root, repo_path)

        repo_statuses.append({
            "id": repo_id,
            "tier": tier,
            "classification": classification,
        })

        if classification == "governed":
            governed_count += 1
        elif classification == "partial":
            partial_count += 1
        elif classification in ("legacy", "not_found", "error"):
            legacy_count += 1

    # Plan stats
    in_progress_list, blocked_list = _collect_plan_lists(plan_registry)

    # Dep map stats
    dep_repos = dep_map.get("repos", [])
    cross_repo_edges = dep_map.get("cross_repo_edges", 0)

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "fleet": {
            "repo_count": len(governed_repos),
            "governed_count": governed_count,
            "partial_count": partial_count,
            "legacy_count": legacy_count,
            "repos": repo_statuses,
        },
        "plans": {
            "total": plan_registry.get("total_plans", 0),
            "complete": plan_registry.get("complete", 0),
            "in_progress": plan_registry.get("in_progress", 0),
            "planned": plan_registry.get("planned", 0),
            "blocked": plan_registry.get("blocked", 0),
            "in_progress_list": in_progress_list,
            "blocked_list": blocked_list,
        },
        "dependencies": {
            "repo_count": len(dep_repos),
            "cross_repo_edges": cross_repo_edges,
        },
    }


def render_markdown(status: dict[str, Any]) -> str:
    """Render a human-readable Markdown summary from the status payload."""
    generated_at = status.get("generated_at", "unknown")
    fleet = status.get("fleet", {})
    plans = status.get("plans", {})
    deps = status.get("dependencies", {})

    lines: list[str] = []
    lines.append("# Ecosystem Status")
    lines.append("")
    lines.append(f"Generated: {generated_at}")
    lines.append("")

    # Fleet summary
    lines.append("## Fleet")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total repos | {fleet.get('repo_count', 0)} |")
    lines.append(f"| Governed | {fleet.get('governed_count', 0)} |")
    lines.append(f"| Partial | {fleet.get('partial_count', 0)} |")
    lines.append(f"| Legacy / not found / error | {fleet.get('legacy_count', 0)} |")
    lines.append("")

    repos = fleet.get("repos", [])
    if repos:
        lines.append("### Repo Classification")
        lines.append("")
        lines.append("| Repo | Tier | Classification |")
        lines.append("|------|------|----------------|")
        for r in repos:
            lines.append(
                f"| {r.get('id', '')} | {r.get('tier', '')} | {r.get('classification', '')} |"
            )
        lines.append("")

    # Plans summary
    lines.append("## Plans")
    lines.append("")
    lines.append(f"| Status | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total | {plans.get('total', 0)} |")
    lines.append(f"| Complete | {plans.get('complete', 0)} |")
    lines.append(f"| In Progress | {plans.get('in_progress', 0)} |")
    lines.append(f"| Planned | {plans.get('planned', 0)} |")
    lines.append(f"| Blocked | {plans.get('blocked', 0)} |")
    lines.append("")

    in_progress_list = plans.get("in_progress_list", [])
    if in_progress_list:
        lines.append("### In Progress")
        lines.append("")
        for p in in_progress_list:
            lines.append(f"- [{p.get('project', '')} #{p.get('number', '')}] {p.get('title', '')}")
        lines.append("")

    blocked_list = plans.get("blocked_list", [])
    if blocked_list:
        lines.append("### Blocked")
        lines.append("")
        for p in blocked_list:
            lines.append(f"- [{p.get('project', '')} #{p.get('number', '')}] {p.get('title', '')}")
        lines.append("")

    # Dependencies
    lines.append("## Dependencies")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Repos in dep map | {deps.get('repo_count', 0)} |")
    lines.append(f"| Cross-repo edges | {deps.get('cross_repo_edges', 0)} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_This file is generated by `make ecosystem-status`. Do not edit manually._")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    """Entry point: build ecosystem status and render Markdown."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Path to the enforced-planning repo root (default: script's parent)",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.exists():
        print(f"Error: repo root not found: {repo_root}", file=sys.stderr)
        return 1

    print("Building ecosystem status...")
    status = build_status(repo_root)

    # Write JSON
    json_out = repo_root / "generated" / "ecosystem_status.json"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print(f"Wrote {json_out}")

    # Write Markdown
    md_out = repo_root / "docs" / "ops" / "ECOSYSTEM_STATUS.md"
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(render_markdown(status), encoding="utf-8")
    print(f"Wrote {md_out}")

    # Print summary
    fleet = status["fleet"]
    plans = status["plans"]
    deps = status["dependencies"]
    print(
        f"\nFleet: {fleet['repo_count']} repos "
        f"({fleet['governed_count']} governed, "
        f"{fleet['partial_count']} partial, "
        f"{fleet['legacy_count']} legacy/error)"
    )
    print(
        f"Plans: {plans['total']} total "
        f"({plans['in_progress']} in-progress, "
        f"{plans['blocked']} blocked)"
    )
    print(f"Deps: {deps['cross_repo_edges']} cross-repo edges across {deps['repo_count']} repos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
