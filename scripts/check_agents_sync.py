#!/usr/bin/env python3
"""Check that generated AGENTS.md is in sync with canonical governance inputs.

This validator compares the checked-in ``AGENTS.md`` file against the
deterministic output of ``render_agents_md.py``. It is intended for local
verification, hooks, and CI gates where manual drift must fail loudly.
"""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path

from render_agents_md import render_agents_md


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the sync checker."""

    parser = argparse.ArgumentParser(
        description="Check whether AGENTS.md matches canonical governance inputs",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repo root containing CLAUDE.md and scripts/relationships.yaml",
    )
    parser.add_argument(
        "--claude-file",
        default="CLAUDE.md",
        help="Repo-relative path to canonical CLAUDE.md",
    )
    parser.add_argument(
        "--relationships-file",
        default="scripts/relationships.yaml",
        help="Repo-relative path to canonical relationships.yaml",
    )
    parser.add_argument(
        "--output-file",
        default="AGENTS.md",
        help="Repo-relative path to generated AGENTS.md",
    )
    parser.add_argument(
        "--template",
        default="",
        help="Accepted for compatibility; the canonical renderer chooses its own template logic.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Accepted for consistency with other repo checkers; check mode is the default",
    )
    return parser.parse_args()


def main() -> int:
    """Compare current AGENTS.md to the deterministic rendered output."""

    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    claude_path = repo_root / args.claude_file
    output_path = repo_root / args.output_file
    if not claude_path.exists():
        print(f"Canonical CLAUDE file is missing: {claude_path}")
        return 1

    if not output_path.exists():
        print(f"Generated AGENTS file is missing: {output_path}")
        print(
            "Run: "
            f"python {repo_root / 'scripts' / 'meta' / 'render_agents_md.py'} --repo-root {repo_root}"
        )
        return 1

    expected = render_agents_md(claude_path)
    actual = output_path.read_text(encoding="utf-8")
    if actual == expected:
        print(f"AGENTS.md is in sync: {output_path}")
        return 0

    diff = "\n".join(
        difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=str(output_path),
            tofile=f"{output_path} (expected)",
            lineterm="",
        )
    )
    print("AGENTS.md drift detected.")
    print(
        "Regenerate with: "
        f"python {repo_root / 'scripts' / 'meta' / 'render_agents_md.py'} --repo-root {repo_root}"
    )
    if diff:
        print(diff)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
