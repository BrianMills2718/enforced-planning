#!/usr/bin/env python3
"""Prove every governed-repo sync profile ships its own transitive imports.

Prevents the recurring class of friction where a shipped ``scripts/meta/*.py``
facade (or an ``enforced_planning`` module it depends on) imports an
``enforced_planning`` module that a given installer sync profile never copies
into consumer repos -- e.g. process_tracing/qualitative_coding/project-meta
hit ``ImportError: enforced_planning.coordination_claims`` and later
``session_lifecycle`` on ``make worktree``/session-close across 2026-07-16 to
2026-08-03 (policy_friction.md cluster ``coordination-claims-wrapper``)
because the sync map that ships a facade did not also ship every module that
facade (transitively) imports.

Each ``*_SYNC_SUPPORT_FILES``/``*_LOCAL_PACKAGE_FILES`` dict in
``install_governed_repo.py`` maps a consumer-relative dest path to a
framework-relative source path. For every profile, this script walks the
import graph starting from every shipped ``.py`` file (facades and any
``enforced_planning`` modules already included) and confirms every
``enforced_planning`` module reachable from that closure is also a key in the
same profile's dict. A gap here means: ship this profile today, and the
consumer crashes with ImportError the first time the affected code path runs.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import install_governed_repo as installer  # noqa: E402


def _enforced_planning_imports(source_text: str) -> set[str]:
    """Return every top-level ``enforced_planning.<module>`` name imported."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "enforced_planning":
                modules.update(alias.name for alias in node.names)
            elif node.module and node.module.startswith("enforced_planning."):
                modules.add(node.module.split(".", 1)[1].split(".", 1)[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("enforced_planning."):
                    modules.add(alias.name.split(".", 1)[1].split(".", 1)[0])
    return modules


def profile_gaps(profile: dict[str, str], *, framework_root: Path) -> list[str]:
    """Return the sorted enforced_planning module names this profile ships a
    facade for the import of, but never syncs, given its own dest->source map."""
    frontier = {source for dest, source in profile.items() if dest.endswith(".py")}
    seen: set[str] = set()
    required: set[str] = set()
    stack = list(frontier)
    while stack:
        rel = stack.pop()
        if rel in seen:
            continue
        seen.add(rel)
        path = framework_root / rel
        if not path.exists():
            continue
        for module in _enforced_planning_imports(path.read_text(encoding="utf-8")):
            required.add(module)
            child = f"enforced_planning/{module}.py"
            if child not in seen:
                stack.append(child)
    return sorted(module for module in required if f"enforced_planning/{module}.py" not in profile)


def named_profiles() -> dict[str, dict[str, str]]:
    """Every sync profile install_governed_repo.py can ship to a consumer."""
    return {
        "SYNC_SUPPORT_FILES": installer.SYNC_SUPPORT_FILES,
        "WORKTREE_ONLY_SYNC_SUPPORT_FILES": installer.WORKTREE_ONLY_SYNC_SUPPORT_FILES,
        "RELATIONSHIP_CONTEXT_SYNC_SUPPORT_FILES": installer.RELATIONSHIP_CONTEXT_SYNC_SUPPORT_FILES,
        "COORDINATION_MESSAGES (shared+local)": {
            **installer.COORDINATION_MESSAGES_SHARED_FILES,
            **installer.COORDINATION_MESSAGES_LOCAL_PACKAGE_FILES,
        },
        "CLAIM_PROJECTION (shared+local)": {
            **installer.CLAIM_PROJECTION_SHARED_FILES,
            **installer.CLAIM_PROJECTION_LOCAL_PACKAGE_FILES,
        },
    }


def check_all(*, framework_root: Path | None = None) -> dict[str, list[str]]:
    """Return {profile_name: [missing_module, ...]} for every profile with a gap."""
    root = framework_root or installer.FRAMEWORK_ROOT
    violations: dict[str, list[str]] = {}
    for name, profile in named_profiles().items():
        missing = profile_gaps(profile, framework_root=root)
        if missing:
            violations[name] = missing
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    violations = check_all()
    if not violations:
        print("check_facade_sync_completeness: OK - every sync profile ships its own transitive enforced_planning imports")
        return 0
    print("check_facade_sync_completeness: FAIL - a sync profile ships a facade that imports a module it never syncs", file=sys.stderr)
    for name, missing in violations.items():
        print(f"  {name}: missing {missing}", file=sys.stderr)
        print(f"    add \"enforced_planning/<module>.py\": \"enforced_planning/<module>.py\" for {missing} to this profile's dict", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
