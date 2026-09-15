#!/usr/bin/env python3
"""Validate the Plan #289 plan dependency contract.

Two modes:

  --repo <path> --staged   validate staged open plans in one repository (pre-commit);
                           ids resolve and cycles are checked against the full corpus.
                           Exits 1 on contract errors, 2 when the corpus cannot be loaded.
  --corpus                 report every active PROJECT_GRAPH repository as JSON.
                           Always exits 0: corpus numbers trigger follow-up, never block.

PROJECT_GRAPH.json comes from --project-graph, else $PROJECT_GRAPH_PATH, else
~/code/project-meta/PROJECT_GRAPH.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


def _detect_repo_root(script_path: Path) -> Path:
    """Resolve repo root for both canonical and installed script layouts."""
    if script_path.parent.name == "meta" and script_path.parent.parent.name == "scripts":
        return script_path.parents[2]
    return script_path.parents[1]


ROOT = _detect_repo_root(Path(__file__).resolve())
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enforced_planning.plan_dependencies import (  # noqa: E402
    ParsedPlan,
    PlanFile,
    build_dependency_graph,
    build_known_ids,
    is_plan_path,
    iter_plan_paths,
    parse_plan,
    validate_plan_dependencies,
)

DEFAULT_PROJECT_GRAPH = Path("~/code/project-meta/PROJECT_GRAPH.json")


class CorpusError(RuntimeError):
    """The corpus needed for resolution could not be loaded."""


def resolve_project_graph(explicit: str | None) -> Path:
    raw = explicit or os.environ.get("PROJECT_GRAPH_PATH") or str(DEFAULT_PROJECT_GRAPH)
    path = Path(raw).expanduser()
    if not path.is_file():
        raise CorpusError(f"PROJECT_GRAPH.json not found at {path} (set PROJECT_GRAPH_PATH or --project-graph)")
    return path


def load_projects(graph_path: Path) -> list[dict[str, Any]]:
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    projects = data.get("projects", []) if isinstance(data, dict) else data
    if not isinstance(projects, list):
        raise CorpusError(f"{graph_path} has no project list")
    return [p for p in projects if isinstance(p, dict)]


def project_id(record: dict[str, Any]) -> str | None:
    identifier = record.get("id") or record.get("name")
    return identifier.strip() if isinstance(identifier, str) and identifier.strip() else None


def project_root(record: dict[str, Any], graph_path: Path) -> Path | None:
    raw = record.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw.strip()).expanduser()
    if not path.is_absolute():
        # Relative registry paths are relative to the workspace holding project-meta.
        path = graph_path.resolve().parent.parent / path
    return path


def active_projects(graph_path: Path) -> list[tuple[str, Path]]:
    """Active registry records with an existing root, first owner of a root wins."""
    selected: list[tuple[str, Path]] = []
    seen_roots: set[Path] = set()
    for record in load_projects(graph_path):
        if record.get("status") != "active":
            continue
        identifier = project_id(record)
        root = project_root(record, graph_path)
        if identifier is None or root is None or not root.is_dir():
            continue
        resolved = root.resolve()
        if resolved in seen_roots:
            continue
        seen_roots.add(resolved)
        selected.append((identifier, root))
    return selected


def _read_plans(identifier: str, root: Path) -> list[ParsedPlan]:
    plans: list[ParsedPlan] = []
    for path in iter_plan_paths(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # parse_plans.py skips unreadable files the same way
        parsed = parse_plan(PlanFile(identifier, path.relative_to(root).as_posix(), content))
        if parsed is not None:
            plans.append(parsed)
    return plans


def _git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise CorpusError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout


def _last_commit_epoch(root: Path) -> int | None:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%ct"], cwd=root, capture_output=True, text=True, check=False
    )
    text = result.stdout.strip()
    return int(text) if result.returncode == 0 and text.isdigit() else None


# --- staged mode ---------------------------------------------------------------


def run_staged(repo: Path, graph_path: Path, explicit_project_id: str | None) -> int:
    repo_root = Path(_git(["rev-parse", "--show-toplevel"], repo).strip())
    common_dir = Path(_git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo).strip())
    canonical_root = common_dir.parent.resolve()

    staged = [
        line
        for line in _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"], repo_root).splitlines()
        if is_plan_path(line)
    ]
    if not staged:
        return 0

    projects = active_projects(graph_path)
    repo_project_id = explicit_project_id
    if repo_project_id is None:
        for identifier, root in projects:
            if root.resolve() in {canonical_root, repo_root.resolve()}:
                repo_project_id = identifier
                break
    if repo_project_id is None:
        raise CorpusError(
            f"{canonical_root} is not an active project in {graph_path}; pass --project-id to validate its plans"
        )

    corpus: list[ParsedPlan] = []
    for identifier, root in projects:
        if identifier == repo_project_id or root.resolve() in {canonical_root, repo_root.resolve()}:
            continue
        corpus.extend(_read_plans(identifier, root))

    # This repository: working tree, with staged blobs overriding their paths.
    local = {plan.source.relative_path: plan for plan in _read_plans(repo_project_id, repo_root)}
    staged_sources: list[PlanFile] = []
    for relative in staged:
        content = _git(["show", f":{relative}"], repo_root)
        source = PlanFile(repo_project_id, relative, content)
        staged_sources.append(source)
        parsed = parse_plan(source)
        if parsed is None:
            local.pop(relative, None)
        else:
            local[relative] = parsed
    corpus.extend(local.values())

    errors = validate_plan_dependencies(
        staged_sources,
        build_known_ids(corpus),
        repo_project_id=repo_project_id,
        graph=build_dependency_graph(corpus),
    )
    if not errors:
        print(f"Plan dependency contract: {len(staged_sources)} staged plan file(s) OK.")
        return 0
    print(f"Plan dependency contract: {len(errors)} error(s) in staged plans (Plan #289).")
    for error in errors:
        print(f"  {error.path}: [{error.code}] {error.message}")
    print(
        "Contract: YAML frontmatter plan_id, dependencies (list; [] needs dependencies_reviewed),\n"
        "and dependency_evidence text for every dependency."
    )
    return 1


# --- corpus mode ---------------------------------------------------------------


def run_corpus(graph_path: Path, active_within_days: int) -> dict[str, Any]:
    projects = active_projects(graph_path)
    plans_by_project = {identifier: _read_plans(identifier, root) for identifier, root in projects}
    all_plans = [plan for plans in plans_by_project.values() for plan in plans]
    known_ids = build_known_ids(all_plans)
    graph = build_dependency_graph(all_plans)
    cutoff = time.time() - active_within_days * 86400 if active_within_days > 0 else None

    repos: list[dict[str, Any]] = []
    skipped_inactive: list[str] = []
    for identifier, root in projects:
        plans = plans_by_project[identifier]
        if cutoff is not None:
            last = _last_commit_epoch(root)
            if last is None or last < cutoff:
                skipped_inactive.append(identifier)
                continue
        if not plans:
            continue
        errors = validate_plan_dependencies(
            [plan.source for plan in plans], known_ids, repo_project_id=identifier, graph=graph
        )
        open_plans = [plan for plan in plans if plan.is_open]
        repos.append(
            {
                "project_id": identifier,
                "path": str(root),
                "plans": len(plans),
                "open_plans": len(open_plans),
                "converted_open_plans": sum(
                    1 for plan in open_plans if plan.frontmatter and "plan_id" in plan.frontmatter
                ),
                "errors_by_type": dict(sorted(Counter(error.code for error in errors).items())),
                "errors": [error.model_dump() for error in errors],
            }
        )
    repos.sort(key=lambda repo: (-repo["open_plans"], repo["project_id"]))
    totals: Counter[str] = Counter()
    for repo in repos:
        totals.update(repo["errors_by_type"])
    return {
        "project_graph": str(graph_path),
        "active_within_days": active_within_days,
        "repos_reported": len(repos),
        "repos_skipped_no_recent_commit": sorted(skipped_inactive),
        "known_ids": len(known_ids),
        "open_plans": sum(repo["open_plans"] for repo in repos),
        "converted_open_plans": sum(repo["converted_open_plans"] for repo in repos),
        "errors_by_type": dict(sorted(totals.items())),
        "repos": repos,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--repo", help="repository to validate (use with --staged)")
    mode.add_argument("--corpus", action="store_true", help="report all active repositories as JSON")
    parser.add_argument("--staged", action="store_true", help="validate staged plan files in --repo")
    parser.add_argument("--project-id", help="PROJECT_GRAPH id for --repo when its path is not registered")
    parser.add_argument("--project-graph", help="path to PROJECT_GRAPH.json")
    parser.add_argument(
        "--active-within-days",
        type=int,
        default=30,
        help="corpus report includes repos with a commit in this many days (0 = all active repos)",
    )
    parser.add_argument("--output", help="write the corpus JSON report here instead of stdout")
    args = parser.parse_args(argv)

    if args.repo is not None and not args.staged:
        parser.error("--repo requires --staged")
    try:
        graph_path = resolve_project_graph(args.project_graph)
        if args.corpus:
            report = json.dumps(run_corpus(graph_path, args.active_within_days), indent=2)
            if args.output:
                Path(args.output).write_text(report + "\n", encoding="utf-8")
            else:
                print(report)
            return 0
        return run_staged(Path(args.repo), graph_path, args.project_id)
    except CorpusError as exc:
        print(f"ERROR: plan dependency validation could not run: {exc}", file=sys.stderr)
        return 0 if args.corpus else 2


if __name__ == "__main__":
    sys.exit(main())
