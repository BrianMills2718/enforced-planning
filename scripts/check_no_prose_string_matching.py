#!/usr/bin/env python3
"""Refuse code that infers meaning by string-matching prose.

Policy `no-prose-string-matching`. A check that decides what a report *means* by
looking for words in it cannot distinguish a claim from a receipt. Three Stop
gates in this ecosystem were switched off on 2026-09-04 for exactly that, with
false blocks and false passes both confirmed; the coordination hook lost a
fourth to a related failure the day before. Nobody noticed while it was
happening, which is why this is a check and not a paragraph.

The rule, in the owner's words: never string-match prose. Where a decision is
semantically related, a light LLM is the default. Parsing structured output is
allowed only where the owner has approved it for that gate -- and approval means
the producer is told to emit the fields, because a structured path nothing emits
is a dead branch behind a prose fallback, which is how the learning gate ended
up here.

What is flagged: a regex, membership test, or string-predicate method applied to
a value this file recognises as carrying model or human prose. Taint is tracked
by name within a module -- direct reads of a known prose key, assignments from
them, and parameters named for them -- one hop, no cross-module flow.

**This under-detects on purpose.** It cannot see prose arriving under a name it
does not know, so a clean run is not proof that a module is free of the defect;
it is proof that no known prose source reaches a matcher. The non-vacuity guard
below is what stops that from degrading into a check that passes by matching
nothing at all.

Exit codes:
  0 -- no violations
  1 -- violations found
  2 -- the check could not run, or its prose vocabulary matched nothing
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path


# Portable: governed repos install this at `scripts/` or `scripts/meta/`, so a
# fixed `parents[N]` is wrong in one of the two layouts. Ask Git, and fall back
# to the layout only when there is no repository to ask.
def _project_root() -> Path:
    import subprocess

    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(Path(__file__).resolve().parent),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return Path(completed.stdout.strip())
    here = Path(__file__).resolve().parent
    return here.parent.parent if here.name == "meta" else here.parent


PROJECT_ROOT = _project_root()

# Names that carry prose written by a model or a person. Every entry here is a
# real field or parameter observed in this ecosystem's hooks, not a guess:
# `last_assistant_message` is the Stop payload field Claude Code documents, and
# the rest are the local names the disabled gates gave it.
PROSE_NAMES: frozenset[str] = frozenset(
    {
        "last_assistant_message",
        "assistant_message",
        "final_message",
        "closeout",
        "closeout_text",
        "report",
        "report_text",
        "disposition",
        "prose",
        "narrative",
        "commit_message",
        "pr_body",
        "summary_text",
        "model_output",
        "completion_text",
        "answer_text",
    }
)

# String operations that turn text into a semantic decision.
PREDICATE_METHODS: frozenset[str] = frozenset(
    {"startswith", "endswith", "find", "rfind", "index", "count"}
)
RE_FUNCTIONS: frozenset[str] = frozenset(
    {"search", "match", "fullmatch", "findall", "finditer", "sub", "subn", "split"}
)

EXEMPT_MARKER = "prose-matching-exempt:"


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    name: str
    operation: str
    snippet: str


@dataclass(frozen=True)
class ScanResult:
    violations: tuple[Violation, ...]
    files_scanned: int
    prose_names_seen: frozenset[str]


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return path.as_posix()


def _exempt_lines(source_lines: list[str]) -> set[int]:
    """Lines carrying a reasoned exemption.

    Matching source text for a marker is not what this policy forbids: the
    subject is code, which has a grammar, not prose. A bare marker is ignored --
    an exemption without a reason is the same silent pass the policy exists to
    stop.
    """

    exempt: set[int] = set()
    for index, line in enumerate(source_lines, start=1):
        position = line.find(EXEMPT_MARKER)
        if position == -1:
            continue
        if line[position + len(EXEMPT_MARKER) :].strip():
            exempt.add(index)
    return exempt


class _ProseTaint(ast.NodeVisitor):
    """Collect names that hold prose, then the operations applied to them."""

    def __init__(self, path: Path, source_lines: list[str], exempt: set[int]) -> None:
        self.path = path
        self.source_lines = source_lines
        self.exempt = exempt
        self.tainted: set[str] = set()
        self.violations: list[Violation] = []
        self.seen_prose_names: set[str] = set()

    # -- taint sources ---------------------------------------------------

    def _is_prose_expression(self, node: ast.AST) -> str | None:
        """Return the prose name this expression reads, if any."""

        if isinstance(node, ast.Name) and node.id in self.tainted:
            return node.id
        if isinstance(node, ast.Name) and node.id in PROSE_NAMES:
            return node.id
        if isinstance(node, ast.Attribute) and node.attr in PROSE_NAMES:
            return node.attr
        # payload["last_assistant_message"] / payload.get("report")
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in PROSE_NAMES
        ):
            return str(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
        ):
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value in PROSE_NAMES:
                return str(first.value)
        return None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for argument in [*node.args.args, *node.args.kwonlyargs]:
            if argument.arg in PROSE_NAMES:
                self.tainted.add(argument.arg)
                self.seen_prose_names.add(argument.arg)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_Assign(self, node: ast.Assign) -> None:
        origin = self._is_prose_expression(node.value)
        if origin is not None:
            self.seen_prose_names.add(origin)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.tainted.add(target.id)
        self.generic_visit(node)

    # -- taint sinks -----------------------------------------------------

    def _record(self, node: ast.AST, name: str, operation: str) -> None:
        line = getattr(node, "lineno", 0)
        if line in self.exempt:
            return
        snippet = self.source_lines[line - 1].strip() if 0 < line <= len(self.source_lines) else ""
        self.violations.append(
            Violation(
                path=_display_path(self.path),
                line=line,
                name=name,
                operation=operation,
                snippet=snippet[:140],
            )
        )

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if isinstance(function, ast.Attribute):
            # re.search(pattern, report)
            if (
                isinstance(function.value, ast.Name)
                and function.value.id == "re"
                and function.attr in RE_FUNCTIONS
            ):
                for argument in node.args:
                    origin = self._is_prose_expression(argument)
                    if origin is not None:
                        self.seen_prose_names.add(origin)
                        self._record(node, origin, f"re.{function.attr}")
            # compiled_pattern.search(report)
            elif function.attr in RE_FUNCTIONS:
                for argument in node.args:
                    origin = self._is_prose_expression(argument)
                    if origin is not None:
                        self.seen_prose_names.add(origin)
                        self._record(node, origin, f"pattern.{function.attr}")
            # report.startswith("Done")
            elif function.attr in PREDICATE_METHODS:
                origin = self._is_prose_expression(function.value)
                if origin is not None:
                    self.seen_prose_names.add(origin)
                    self._record(node, origin, f".{function.attr}")
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        for operator, comparator in zip(node.ops, node.comparators):
            if not isinstance(operator, (ast.In, ast.NotIn)):
                continue
            origin = self._is_prose_expression(comparator)
            if origin is not None and isinstance(node.left, ast.Constant):
                self.seen_prose_names.add(origin)
                self._record(node, origin, "in")
        self.generic_visit(node)


def scan_file(path: Path) -> tuple[list[Violation], set[str]]:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], set()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [], set()
    lines = source.splitlines()
    visitor = _ProseTaint(path, lines, _exempt_lines(lines))
    visitor.visit(tree)
    return visitor.violations, visitor.seen_prose_names


def scan_paths(roots: list[Path]) -> ScanResult:
    violations: list[Violation] = []
    seen: set[str] = set()
    scanned = 0
    for root in roots:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for python_file in candidates:
            if python_file.suffix != ".py":
                continue
            # Exclusions are relative to the scan root, not absolute. Matching
            # absolute path parts scanned zero files the first time this ran,
            # because the lane it was written in lives under `worktrees/`. The
            # non-vacuity guard below is what surfaced that: without it the
            # check would have reported a clean run over an empty corpus.
            try:
                relative_parts = python_file.relative_to(root).parts
            except ValueError:
                relative_parts = python_file.parts
            if any(
                part in (".venv", "venv", "__pycache__", ".git", "node_modules", "worktrees", "build")
                for part in relative_parts
            ):
                continue
            scanned += 1
            found, names = scan_file(python_file)
            violations.extend(found)
            seen |= names
    return ScanResult(tuple(violations), scanned, frozenset(seen))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--roots", nargs="*", default=["scripts"], help="files or directories to scan")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--allow-vacuous",
        action="store_true",
        help="do not fail when no prose name appears anywhere in the corpus (tests and fixtures only)",
    )
    args = parser.parse_args(argv)

    roots = [Path(root) if Path(root).is_absolute() else PROJECT_ROOT / root for root in args.roots]
    result = scan_paths(roots)

    if args.json:
        print(
            json.dumps(
                {
                    "files_scanned": result.files_scanned,
                    "prose_names_seen": sorted(result.prose_names_seen),
                    "violations": [v.__dict__ for v in result.violations],
                },
                indent=2,
            )
        )
    elif result.violations:
        print(f"prose matched as though it had a grammar ({len(result.violations)} site(s)):")
        for violation in result.violations:
            print(f"  {violation.path}:{violation.line}  {violation.operation} on {violation.name}")
            print(f"      {violation.snippet}")
        print()
        print("Policy no-prose-string-matching: a check that reads words to infer meaning")
        print("cannot tell a claim from a receipt. Use a light LLM (claude-code/haiku,")
        print("codex/gpt-5.6-luna) for the semantic judgement. Parsing structured output")
        print("is allowed only where Brian approved it for that gate, and approval means")
        print("the producer is instructed to emit the fields.")
        print("Reasoned exception: append '# prose-matching-exempt: <why>' on the line.")
    else:
        print(
            f"No prose string-matching found in {result.files_scanned} file(s); "
            f"{len(result.prose_names_seen)} prose name(s) reached the scanner."
        )

    # Second non-vacuity guard, and the one --allow-vacuous cannot switch off.
    # Roots were named and nothing was read: the paths did not resolve. Observed
    # once during this check's own first commit, where the hook reported "0
    # file(s)" over three staged files and the run still exited 0. A scanner that
    # reports success over nothing is the defect this whole policy is about, so
    # it is loud whichever mode it runs in.
    if roots and result.files_scanned == 0:
        print(
            f"\nNOT_CHECKED: {len(roots)} root(s) were named and no file was read. "
            "The paths did not resolve from "
            f"{PROJECT_ROOT}. Nothing was checked, so nothing is clean.",
            file=sys.stderr,
        )
        return 2

    # Non-vacuity. A name-based scanner whose vocabulary does not intersect the
    # corpus reports a clean run while matching nothing -- the failure mode that
    # has already shipped three times in this ecosystem. A corpus with no prose
    # name at all is unproven, not clean.
    if not result.prose_names_seen and not args.allow_vacuous:
        print(
            "\nNOT_CHECKED: no known prose name appears in the scanned corpus, so this "
            "run proves nothing. Either the scope is wrong, or a prose source is "
            "arriving under a name PROSE_NAMES does not list -- add it.",
            file=sys.stderr,
        )
        return 2

    return 1 if result.violations else 0


if __name__ == "__main__":
    sys.exit(main())
