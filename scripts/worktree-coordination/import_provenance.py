#!/usr/bin/env python3
"""Check that a worktree's own packages import from inside that worktree.

A linked worktree isolates the git checkout. It does not isolate Python's
import path. When a worktree has no environment of its own, ``import <pkg>``
resolves to whatever the active interpreter already has installed -- normally
an editable install pointing at the canonical checkout. The worktree's test
suite then passes against code that is not in the worktree, and reports green
for the wrong revision.

Observed 2026-08-23 in ``graph_application_toolkit``: running its suite from
``worktrees/document-analysis-v1-20260822`` under the shared virtualenv
resolved ``graph_application_toolkit`` to ``<canonical>/src/graph_application_toolkit``.
A backend suite was reported as passing from that worktree; OpenAPI generation
then erased the endpoint under test and the frontend build disproved the claim.

Enforcement tier: **Measured**. This module reports; it does not block. The
leak is a property of the environment the tests will run under, not of the
worktree at the moment it is created, so a creation-time hard failure would
deny a lane for a condition that is not yet true. Wire it as ``Enforced`` at
the point a repository is about to *trust* a test result.

Run it with the same interpreter the tests will use, and do not let it modify
``sys.path``: stacking the path manufactures the pass it exists to detect.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Directories that never hold a repository's own importable package, and whose
# presence would otherwise produce a confident answer about the wrong subject.
NON_PACKAGE_DIRS = frozenset(
    {
        "build",
        "dist",
        "docs",
        "node_modules",
        "scripts",
        "site-packages",
        "tests",
        "worktrees",
    }
)


class ImportProvenanceError(RuntimeError):
    """Raised when the check cannot identify what it is supposed to verify."""


@dataclass(frozen=True)
class PackageOrigin:
    """Where one declared package actually resolved from."""

    package: str
    origin: str | None
    inside_worktree: bool


@dataclass(frozen=True)
class ImportProvenanceReport:
    """Resolution evidence for every package a worktree declares."""

    worktree: str
    interpreter: str
    packages: tuple[PackageOrigin, ...] = field(default=())

    @property
    def leaked(self) -> tuple[str, ...]:
        """Packages that resolved outside the worktree."""
        return tuple(
            entry.package
            for entry in self.packages
            if entry.origin is not None and not entry.inside_worktree
        )

    @property
    def unimportable(self) -> tuple[str, ...]:
        """Packages the active interpreter could not resolve at all."""
        return tuple(entry.package for entry in self.packages if entry.origin is None)

    @property
    def ok(self) -> bool:
        """True only when every declared package resolved inside the worktree."""
        return not self.leaked and not self.unimportable


def declared_packages(root: Path) -> list[str]:
    """Return the import names this repository ships.

    Read from build configuration rather than by scanning directories. A scan
    misses a ``src/`` layout, and the first version of this check did exactly
    that: it examined three unrelated top-level packages, never looked at the
    one that was leaking, and reported success on the known-bad worktree.
    """
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return []
    text = pyproject.read_text(encoding="utf-8", errors="replace")
    names: set[str] = set()
    for block in re.finditer(r"packages\s*=\s*\[(.*?)\]", text, re.S):
        for raw in re.findall(r"[\"']([^\"']+)[\"']", block.group(1)):
            candidate = Path(raw).name
            if candidate and candidate not in NON_PACKAGE_DIRS:
                names.add(candidate)
    if not names:
        match = re.search(r"^\s*name\s*=\s*[\"']([^\"']+)[\"']", text, re.M)
        if match:
            names.add(match.group(1).replace("-", "_"))
    return sorted(names)


def resolve_origin(name: str) -> str | None:
    """Return the real path the active interpreter would import, or None."""
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, ModuleNotFoundError):
        return None
    if spec is None or not spec.origin:
        return None
    return os.path.realpath(spec.origin)


def check_import_provenance(
    worktree: Path, packages: list[str] | None = None
) -> ImportProvenanceReport:
    """Resolve every declared package and record whether it is inside the worktree.

    Raises rather than returning a clean report when the packages cannot be
    determined. A check that cannot identify its subject must fail; passing
    vacuously is the failure mode this replaces.
    """
    root = Path(os.path.realpath(worktree))
    if not root.is_dir():
        raise ImportProvenanceError(f"not a directory: {root}")

    selected = packages or declared_packages(root)
    if not selected:
        raise ImportProvenanceError(
            f"cannot determine which packages {root} ships; pass them explicitly "
            f"rather than reporting a pass that verified nothing"
        )

    prefix = str(root) + os.sep
    entries = []
    for name in selected:
        origin = resolve_origin(name)
        entries.append(
            PackageOrigin(
                package=name,
                origin=origin,
                inside_worktree=bool(origin) and origin.startswith(prefix),
            )
        )
    return ImportProvenanceReport(
        worktree=str(root),
        interpreter=sys.executable,
        packages=tuple(entries),
    )


def render_warning(report: ImportProvenanceReport) -> str | None:
    """Return an operator-facing warning, or None when provenance is sound."""
    if report.ok:
        return None
    lines = []
    if report.leaked:
        lines.append(
            f"WARNING: {', '.join(report.leaked)} resolve outside this worktree "
            f"under {report.interpreter}. A test run here would validate the "
            f"canonical checkout, not this branch."
        )
    if report.unimportable:
        lines.append(
            f"WARNING: {', '.join(report.unimportable)} are not importable by "
            f"{report.interpreter}, so a test run here proves nothing either."
        )
    for entry in report.packages:
        if not entry.inside_worktree:
            lines.append(f"  {entry.package} -> {entry.origin}")
    lines.append(
        "  Give this worktree its own environment, or install the package "
        "editable against this path, before trusting any result from it."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", required=True, help="Worktree root to check.")
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="Explicit import name; repeatable. Overrides build-config discovery.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Exit 0 even when provenance is unsound. For creation-time reporting.",
    )
    args = parser.parse_args(argv)

    try:
        report = check_import_provenance(Path(args.worktree), args.package or None)
    except ImportProvenanceError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "worktree": report.worktree,
                    "interpreter": report.interpreter,
                    "packages": [
                        {
                            "package": entry.package,
                            "origin": entry.origin,
                            "inside_worktree": entry.inside_worktree,
                        }
                        for entry in report.packages
                    ],
                    "leaked": list(report.leaked),
                    "unimportable": list(report.unimportable),
                    "ok": report.ok,
                },
                indent=2,
            )
        )
    else:
        for entry in report.packages:
            mark = "ok  " if entry.inside_worktree else ("MISS" if entry.origin is None else "LEAK")
            print(f"{mark}  {entry.package:<32} -> {entry.origin}")
        warning = render_warning(report)
        if warning:
            # stdout is block-buffered when piped and stderr is not, so without
            # this flush the warning prints before the resolution table it
            # explains.
            sys.stdout.flush()
            print(f"\n{warning}", file=sys.stderr)

    if report.ok or args.warn_only:
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
