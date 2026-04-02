#!/usr/bin/env python3
"""Dependency inference engine — scans a repo and builds an inferred dependency graph.

Layer 1 of the relationships.yaml V2 architecture. Programmatic scanning for
coverage; relationships.yaml serves as the override layer.

Scans for:
1. Markdown links: [text](path) → source depends on target
2. File path references: any recognized file path in code/docs
3. Import statements: from X import Y → cross-project dependency
4. Plan references: Plan #N, ADR-N → plan-to-plan or plan-to-ADR dependency
5. YAML references: file paths in YAML config files

Inline suppression: <!-- governance: no-dep --> or # governance: no-dep

Usage:
    python infer_dependencies.py /path/to/repo
    python infer_dependencies.py /path/to/repo --output inferred.json
    python infer_dependencies.py /path/to/repo --format markdown
    python infer_dependencies.py /path/to/repo --summary
"""

import argparse
import json
import re
import sys
from pathlib import Path


# Files to scan
SCANNABLE_EXTENSIONS = {
    ".md", ".py", ".yaml", ".yml", ".toml", ".cfg", ".json", ".sh", ".txt",
}
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "repos", ".tox",
}

# Suppression markers
SUPPRESSION_PATTERNS = [
    re.compile(r"<!--\s*governance:\s*no-dep\s*-->"),
    re.compile(r"#\s*governance:\s*no-dep"),
]

# Markdown link: [text](path)
MD_LINK = re.compile(r"\[(?:[^\]]*)\]\(([^)]+)\)")

# Import statements
PY_IMPORT = re.compile(
    r"^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
    re.MULTILINE,
)

# Plan references: Plan #N, Plan#N, #N (in context)
PLAN_REF = re.compile(r"(?:Plan\s+)?#(\d+)", re.IGNORECASE)

# ADR references: ADR-N, ADR #N
ADR_REF = re.compile(r"ADR[- ](\d+)", re.IGNORECASE)

# File path references (heuristic): looks like a relative path with extension
FILE_PATH_REF = re.compile(
    r"(?:^|[\s\"'`(,])((?:\.\.?/)?(?:[\w.-]+/)*[\w.-]+\.(?:md|py|yaml|yml|json|toml|sh))\b",
)

# Known top-level packages that indicate cross-project dependencies
KNOWN_PACKAGES = {
    "llm_client", "prompt_eval", "open_web_retrieval", "osint_tools",
    "data_contracts", "agentic_scaffolding", "onto_canon6", "moltbot",
}


def _is_suppressed(line: str) -> bool:
    """Check if a line has an inline suppression marker."""
    return any(p.search(line) for p in SUPPRESSION_PATTERNS)


def _resolve_path(source_file: Path, ref: str, repo_root: Path) -> Path | None:
    """Resolve a relative path reference to an absolute path."""
    if ref.startswith("http://") or ref.startswith("https://"):
        return None
    if ref.startswith("#"):  # Anchor link
        return None

    # Try relative to source file
    candidate = (source_file.parent / ref).resolve()
    if candidate.exists() and str(candidate).startswith(str(repo_root)):
        return candidate

    # Try relative to repo root
    candidate = (repo_root / ref).resolve()
    if candidate.exists() and str(candidate).startswith(str(repo_root)):
        return candidate

    return None


def scan_file(file_path: Path, repo_root: Path) -> list[dict]:
    """Scan a single file for dependency references.

    Returns list of {source, target, type, evidence, line_number}.
    """
    edges = []
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return []

    rel_source = str(file_path.relative_to(repo_root))
    is_python = file_path.suffix == ".py"
    is_markdown = file_path.suffix == ".md"
    is_yaml = file_path.suffix in (".yaml", ".yml")

    for line_num, line in enumerate(text.splitlines(), 1):
        if _is_suppressed(line):
            continue

        # Markdown links
        if is_markdown:
            for m in MD_LINK.finditer(line):
                ref = m.group(1).split("#")[0]  # Strip anchor
                if not ref:
                    continue
                resolved = _resolve_path(file_path, ref, repo_root)
                if resolved:
                    rel_target = str(resolved.relative_to(repo_root))
                    edges.append({
                        "source": rel_source,
                        "target": rel_target,
                        "type": "markdown_link",
                        "evidence": line.strip()[:120],
                        "line": line_num,
                    })

        # Python imports
        if is_python:
            for m in PY_IMPORT.finditer(line):
                module = m.group(1) or m.group(2)
                top_package = module.split(".")[0]
                if top_package in KNOWN_PACKAGES:
                    edges.append({
                        "source": rel_source,
                        "target": f"[cross-project:{top_package}]",
                        "type": "python_import",
                        "evidence": line.strip()[:120],
                        "line": line_num,
                    })

        # Plan references (in markdown and YAML)
        if is_markdown or is_yaml:
            for m in PLAN_REF.finditer(line):
                edges.append({
                    "source": rel_source,
                    "target": f"[plan:#{m.group(1)}]",
                    "type": "plan_reference",
                    "evidence": line.strip()[:120],
                    "line": line_num,
                })

        # ADR references
        for m in ADR_REF.finditer(line):
            edges.append({
                "source": rel_source,
                "target": f"[adr:{m.group(1)}]",
                "type": "adr_reference",
                "evidence": line.strip()[:120],
                "line": line_num,
            })

        # File path references (in code and config, not markdown — those are caught above)
        if is_python or is_yaml:
            for m in FILE_PATH_REF.finditer(line):
                ref = m.group(1)
                resolved = _resolve_path(file_path, ref, repo_root)
                if resolved:
                    rel_target = str(resolved.relative_to(repo_root))
                    if rel_target != rel_source:  # Skip self-references
                        edges.append({
                            "source": rel_source,
                            "target": rel_target,
                            "type": "file_path_reference",
                            "evidence": line.strip()[:120],
                            "line": line_num,
                        })

    return edges


def scan_repo(repo_root: Path) -> list[dict]:
    """Scan an entire repo for dependencies."""
    repo_root = repo_root.resolve()
    all_edges = []

    for path in repo_root.rglob("*"):
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if not path.is_file():
            continue
        if path.suffix not in SCANNABLE_EXTENSIONS:
            continue

        all_edges.extend(scan_file(path, repo_root))

    # Deduplicate (same source→target pair with same type)
    seen = set()
    unique_edges = []
    for edge in all_edges:
        key = (edge["source"], edge["target"], edge["type"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    return unique_edges


def format_summary(edges: list[dict], repo_name: str) -> str:
    """Format a summary of the inferred graph."""
    lines = [f"# Inferred Dependencies — {repo_name}\n"]
    lines.append(f"Total edges: {len(edges)}\n")

    # By type
    by_type: dict[str, int] = {}
    for e in edges:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    lines.append("## By Type\n")
    for t, count in sorted(by_type.items(), key=lambda x: -x[1]):
        lines.append(f"- {t}: {count}")

    # Cross-project imports
    cross_project = [e for e in edges if e["type"] == "python_import"]
    if cross_project:
        lines.append("\n## Cross-Project Imports\n")
        targets = set(e["target"] for e in cross_project)
        for t in sorted(targets):
            sources = sorted(set(e["source"] for e in cross_project if e["target"] == t))
            lines.append(f"- **{t}** ← {', '.join(sources)}")

    # Most-referenced files
    target_counts: dict[str, int] = {}
    for e in edges:
        if not e["target"].startswith("["):
            target_counts[e["target"]] = target_counts.get(e["target"], 0) + 1
    if target_counts:
        lines.append("\n## Most Referenced Files\n")
        for target, count in sorted(target_counts.items(), key=lambda x: -x[1])[:15]:
            lines.append(f"- {target}: {count} references")

    return "\n".join(lines)


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description="Infer dependency graph from repo")
    parser.add_argument("repo", type=Path, help="Repository root to scan")
    parser.add_argument("--output", "-o", type=Path, help="Output JSON file")
    parser.add_argument("--format", choices=["json", "markdown", "summary"], default="summary")
    args = parser.parse_args()

    repo_root = args.repo.resolve()
    if not repo_root.is_dir():
        print(f"Error: {repo_root} is not a directory", file=sys.stderr)
        sys.exit(1)

    edges = scan_repo(repo_root)
    repo_name = repo_root.name

    if args.format == "json" or args.output:
        output = {
            "repo": repo_name,
            "repo_path": str(repo_root),
            "total_edges": len(edges),
            "edges": edges,
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                json.dump(output, f, indent=2)
            print(f"Wrote {len(edges)} edges to {args.output}")
        else:
            print(json.dumps(output, indent=2))
    elif args.format == "markdown":
        print(format_summary(edges, repo_name))
    else:
        print(format_summary(edges, repo_name))


if __name__ == "__main__":
    main()
