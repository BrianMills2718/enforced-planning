#!/usr/bin/env python3
"""Build a consolidated cross-repo dependency map from per-repo inferred_deps.json files.

Reads all generated/inferred_*.json files produced by infer_dependencies.py and
produces an ecosystem-level dependency graph: which repos import which other repos,
with edge counts and edge lists.

Output: generated/ecosystem_dep_map.json
    {
        "repos": [...],          # all repos scanned
        "total_edges": int,      # total intra+inter repo edges
        "cross_repo_edges": int, # count of inter-repo edges
        "dep_graph": {           # repo -> {count, targets: {repo: count}}
            "source_repo": {
                "total_edges": int,
                "cross_repo_edges": int,
                "depends_on": {"target_repo": count, ...}
            }
        },
        "reverse_graph": {       # repo -> {repos that depend on it: count}
            "llm_client": {"sam_gov": 36, "prompt_eval": 13, ...}
        },
    }

Usage:
    python build_ecosystem_dep_map.py
    python build_ecosystem_dep_map.py --gen-dir generated/ --output generated/ecosystem_dep_map.json
    python build_ecosystem_dep_map.py --summary
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def build_dep_map(gen_dir: Path) -> dict[str, Any]:
    """Aggregate per-repo inferred_deps.json files into an ecosystem dep map."""
    dep_graph: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    repo_totals: dict[str, int] = {}
    repos: list[str] = []
    total_edges = 0

    for f in sorted(gen_dir.glob("inferred_*.json")):
        repo_name = f.stem.removeprefix("inferred_")
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        edges = data.get("edges", [])
        repos.append(repo_name)
        repo_totals[repo_name] = len(edges)
        total_edges += len(edges)
        for e in edges:
            target = e.get("target", "")
            if target.startswith("[cross-project:"):
                # "[cross-project:llm_client]" -> "llm_client"
                cross_target = target.removeprefix("[cross-project:").rstrip("]")
                dep_graph[repo_name][cross_target] += 1

    # Build final dep_graph structure
    dep_graph_out: dict[str, Any] = {}
    for repo in repos:
        cross_deps = dict(dep_graph.get(repo, {}))
        cross_count = sum(cross_deps.values())
        dep_graph_out[repo] = {
            "total_edges": repo_totals.get(repo, 0),
            "cross_repo_edges": cross_count,
            "depends_on": cross_deps,
        }

    # Build reverse graph: who depends on this repo
    reverse_graph: dict[str, dict[str, int]] = defaultdict(dict)
    for repo, info in dep_graph_out.items():
        for target, count in info["depends_on"].items():
            reverse_graph[target][repo] = count

    total_cross_edges = sum(
        info["cross_repo_edges"] for info in dep_graph_out.values()
    )

    return {
        "repos": sorted(repos),
        "total_edges": total_edges,
        "cross_repo_edges": total_cross_edges,
        "dep_graph": dep_graph_out,
        "reverse_graph": {k: dict(v) for k, v in sorted(reverse_graph.items())},
    }


def format_summary(dep_map: dict[str, Any]) -> str:
    """Human-readable summary of the ecosystem dep map."""
    lines = ["# Ecosystem Dependency Map\n"]
    lines.append(f"Repos scanned: {len(dep_map['repos'])}")
    lines.append(f"Total inferred edges: {dep_map['total_edges']}")
    lines.append(f"Cross-repo edges: {dep_map['cross_repo_edges']}\n")

    lines.append("## Most depended-on repos (reverse graph)")
    reverse = dep_map["reverse_graph"]
    # Sort by number of dependents
    sorted_targets = sorted(reverse.items(), key=lambda x: -sum(x[1].values()))
    for target, dependents in sorted_targets:
        total = sum(dependents.values())
        dep_list = ", ".join(
            f"{r}({n})" for r, n in sorted(dependents.items(), key=lambda x: -x[1])
        )
        lines.append(f"  {target}: {total} edges from {len(dependents)} repos — {dep_list}")

    lines.append("\n## Per-repo cross-repo dependencies")
    for repo, info in sorted(dep_map["dep_graph"].items()):
        if info["depends_on"]:
            deps = ", ".join(
                f"{t}({n})" for t, n in sorted(info["depends_on"].items(), key=lambda x: -x[1])
            )
            lines.append(f"  {repo}: {deps}")

    repos_with_no_cross = [
        r for r, info in dep_map["dep_graph"].items()
        if not info["depends_on"]
    ]
    if repos_with_no_cross:
        lines.append(f"\n## Isolated repos (no cross-repo deps): {', '.join(sorted(repos_with_no_cross))}")

    return "\n".join(lines)


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Build ecosystem dependency map")
    parser.add_argument(
        "--gen-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "generated",
        help="Directory containing inferred_*.json files",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output JSON file (default: generated/ecosystem_dep_map.json)",
    )
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary")
    args = parser.parse_args()

    gen_dir = args.gen_dir.expanduser().resolve()
    if not gen_dir.is_dir():
        print(f"Error: {gen_dir} is not a directory")
        return 1

    dep_map = build_dep_map(gen_dir)

    if args.summary or not args.output:
        print(format_summary(dep_map))
        if not args.output:
            return 0

    output = args.output or gen_dir / "ecosystem_dep_map.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(dep_map, f, indent=2)
    print(
        f"Wrote ecosystem dep map to {output} "
        f"({len(dep_map['repos'])} repos, {dep_map['cross_repo_edges']} cross-repo edges)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
