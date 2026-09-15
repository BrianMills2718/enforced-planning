"""Plan dependency contract validator (project-meta Plan #289).

Every open plan declares, in leading YAML frontmatter::

    ---
    plan_id: "project-meta#288"
    dependencies: ["project-meta#280"]
    dependency_evidence: {"project-meta#280": "quoted text justifying the link"}
    dependencies_reviewed: "2026-09-15"   # required when dependencies is []
    ---

The frontmatter split, plan-file discovery, and identity rules mirror
ecosystem-ops ``parse_plans.py`` and ``plan_graph.py`` (``_split_yaml_frontmatter``,
``PLAN_SUBDIRS``/``SHALLOW_PLAN_SUBDIRS``, ``_normalize_project_name``,
``_normalize_plan_number``, ``_plan_identity``), so a plan this module accepts is
one the dashboard graph parses the same way. Status extraction reuses
``plan_validation.parse_plan_status``.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict

from enforced_planning.plan_validation import parse_plan_status

# Same directory set and depth rule as ecosystem-ops parse_plans.py.
PLAN_SUBDIRS: tuple[str, ...] = ("plans", "docs/plans", "plan", "docs/planning", "claude_code_planning")
SHALLOW_PLAN_SUBDIRS = frozenset({"plan", "docs/planning"})
NON_PLAN_FILENAMES = frozenset({"CLAUDE.md", "AGENTS.md", "TEMPLATE.md", "INDEX.md"})

CLOSED_STATUS_WORDS: tuple[str, ...] = (
    "complete",
    "completed",
    "done",
    "cancelled",
    "canceled",
    "superseded",
    "historical",
    "retired",
    "deferred",
    "archived",
)
_CLOSED_STATUS_SYMBOLS = ("✅",)

_PLAN_NUMBER_RE = re.compile(r"\d+(?:\.\d+)*")
_QUALIFIED_PLAN_ID_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)#([A-Za-z0-9_.-]+)\s*$")
_FILENAME_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)(?:[_\-]|$)")
_TITLE_NUMBER_RE = re.compile(r"\bPlan\s*#?\s*(\d+(?:\.\d+)*)\b", re.IGNORECASE)

ErrorCode = Literal[
    "invalid_frontmatter",
    "missing_status",
    "missing_plan_id",
    "invalid_plan_id",
    "plan_id_mismatch",
    "missing_dependencies",
    "invalid_dependencies",
    "missing_dependency_evidence",
    "missing_dependencies_reviewed",
    "unresolved_dependency",
    "dependency_cycle",
]


class PlanDependencyError(BaseModel):
    """One contract violation, addressed by file and (when known) plan id."""

    model_config = ConfigDict(frozen=True)

    code: ErrorCode
    path: str
    message: str
    plan_id: str | None = None


@dataclass(frozen=True)
class PlanFile:
    """One plan document and the project that owns it.

    ``relative_path`` is repository-relative (POSIX) so staged and on-disk
    sources address the same plan identically.
    """

    project_id: str
    relative_path: str
    content: str


@dataclass
class ParsedPlan:
    """Plan fields the dependency contract needs."""

    source: PlanFile
    title: str
    status: str | None
    is_open: bool
    derived_id: str
    frontmatter: dict[str, Any] | None
    frontmatter_error: str | None
    declared_plan_id: str | None = None
    dependencies: list[str] = field(default_factory=list)


def normalize_project_name(name: str) -> str:
    """Normalize a project id exactly as plan_graph._normalize_project_name."""

    normalized = (name or "").strip().lower().replace("_", "-").replace(" ", "-")
    return re.sub(r"-+", "-", normalized)


def _normalize_plan_number(raw: str) -> str | None:
    if not _PLAN_NUMBER_RE.fullmatch(raw):
        return None
    return ".".join(str(int(segment)) for segment in raw.split("."))


def normalize_qualified_id(value: str) -> str | None:
    """Return the canonical ``project#plan`` form, or None when malformed."""

    match = _QUALIFIED_PLAN_ID_RE.fullmatch(value)
    if match is None:
        return None
    project = normalize_project_name(match.group(1))
    raw_plan = match.group(2)
    plan = _normalize_plan_number(raw_plan) or normalize_project_name(raw_plan)
    if not project or not plan:
        return None
    return f"{project}#{plan}"


def split_yaml_frontmatter(content: str) -> tuple[dict[str, Any] | None, str, str | None]:
    """Split a leading ``---`` YAML block; mirrors parse_plans._split_yaml_frontmatter."""

    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, content, None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            try:
                loaded = yaml.safe_load(raw)
            except yaml.YAMLError as exc:
                return None, body, f"invalid YAML frontmatter: {exc}"
            if loaded is None:
                return {}, body, None
            if not isinstance(loaded, dict):
                return None, body, f"YAML frontmatter must be a mapping, got {type(loaded).__name__}"
            return loaded, body, None
    return None, content, "YAML frontmatter opened with '---' but never closed"


def is_plan_path(relative_path: str) -> bool:
    """Return whether a repo-relative path is a plan file under the five plan dirs."""

    path = PurePosixPath(relative_path)
    if path.suffix != ".md" or path.name in NON_PLAN_FILENAMES:
        return False
    parent = path.parent.as_posix()
    for subdir in PLAN_SUBDIRS:
        if subdir in SHALLOW_PLAN_SUBDIRS:
            if parent == subdir:
                return True
        elif parent == subdir or parent.startswith(subdir + "/"):
            return True
    return False


def iter_plan_paths(repo_root: Path) -> list[Path]:
    """List plan files on disk, using the parse_plans depth rule per directory."""

    found: list[Path] = []
    for subdir in PLAN_SUBDIRS:
        plan_dir = repo_root / subdir
        if not plan_dir.is_dir():
            continue
        pattern = plan_dir.glob("*.md") if subdir in SHALLOW_PLAN_SUBDIRS else plan_dir.rglob("*.md")
        for path in sorted(pattern):
            if path.name in NON_PLAN_FILENAMES or not path.is_file():
                continue
            found.append(path)
    return found


def classify_status(raw_status: str | None) -> tuple[str | None, bool]:
    """Return ``(status, is_open)``; a missing status is reported, never exempt."""

    if raw_status is None:
        return None, True
    value = raw_status.strip().strip("*").strip()
    if not value or value.lower() == "unknown":
        return None, True
    if any(symbol in value for symbol in _CLOSED_STATUS_SYMBOLS):
        return value, False
    lowered = re.sub(r"^[^\w]+", "", value.lower())
    first_word = re.split(r"[^a-z]+", lowered, maxsplit=1)[0]
    return value, first_word not in CLOSED_STATUS_WORDS


def _title(body: str) -> str:
    for line in body.split("\n"):
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return ""


def derive_plan_id(project_id: str, relative_path: str, title: str) -> str | None:
    """Derive ``project#N`` the way plan_graph._plan_identity does for unconverted plans."""

    project = normalize_project_name(project_id)
    if not project:
        return None
    filename = PurePosixPath(relative_path).name
    match = _FILENAME_NUMBER_RE.match(filename) or _TITLE_NUMBER_RE.search(title)
    number = _normalize_plan_number(match.group(1)) if match else None
    plan = number or normalize_project_name(PurePosixPath(filename).stem)
    return f"{project}#{plan}" if plan else None


def parse_plan(source: PlanFile) -> ParsedPlan | None:
    """Parse one plan; returns None for a Markdown file with no title (not a plan)."""

    frontmatter, body, frontmatter_error = split_yaml_frontmatter(source.content)
    title = _title(body)
    if not title:
        return None
    _, raw_status = parse_plan_status(source.content)
    status, is_open = classify_status(raw_status)
    derived = derive_plan_id(source.project_id, source.relative_path, title) or ""
    parsed = ParsedPlan(
        source=source,
        title=title,
        status=status,
        is_open=is_open,
        derived_id=derived,
        frontmatter=frontmatter,
        frontmatter_error=frontmatter_error,
    )
    if frontmatter:
        raw_id = frontmatter.get("plan_id")
        if isinstance(raw_id, str):
            parsed.declared_plan_id = normalize_qualified_id(raw_id)
        deps = frontmatter.get("dependencies")
        if isinstance(deps, list):
            parsed.dependencies = [d.strip() for d in deps if isinstance(d, str) and d.strip()]
    return parsed


def plan_identity(plan: ParsedPlan) -> str:
    """Known id: the declared plan_id when valid for this project, else the derived id."""

    if plan.declared_plan_id and plan.declared_plan_id == plan.derived_id:
        return plan.declared_plan_id
    return plan.derived_id


def build_known_ids(plans: Iterable[ParsedPlan]) -> set[str]:
    """Every resolvable id: converted plans by plan_id, unconverted by derived id."""

    return {plan_identity(plan) for plan in plans if plan_identity(plan)}


def build_dependency_graph(plans: Iterable[ParsedPlan]) -> dict[str, list[str]]:
    """Edges from each converted plan to its normalized dependencies."""

    graph: dict[str, list[str]] = {}
    for plan in plans:
        if plan.frontmatter is None or "plan_id" not in plan.frontmatter:
            continue
        node = plan_identity(plan)
        edges = [normalize_qualified_id(dep) or dep for dep in plan.dependencies]
        graph.setdefault(node, []).extend(edges)
    return graph


def check_cycles(graph: Mapping[str, Sequence[str]], *, through: Iterable[str] | None = None) -> list[str] | None:
    """Return the first cycle path (``[a, b, a]``) or None.

    With ``through``, only cycles containing one of those nodes are reported, so a
    commit is not blamed for a cycle elsewhere in the corpus. Traversal order is
    sorted, so the reported path is deterministic.
    """

    starts = sorted(set(through)) if through is not None else sorted(graph)
    for start in starts:
        # Depth-first search for a path from start back to start.
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        visited: set[str] = set()
        while stack:
            node, path = stack.pop()
            for nxt in sorted(graph.get(node, ()), reverse=True):
                if nxt == start:
                    return [*path, start]
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append((nxt, [*path, nxt]))
    return None


def _date_text(value: Any) -> Any:
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _contract_errors(plan: ParsedPlan, known_ids: set[str], repo_project_id: str) -> list[PlanDependencyError]:
    path = plan.source.relative_path
    errors: list[PlanDependencyError] = []

    def err(code: ErrorCode, message: str) -> None:
        errors.append(PlanDependencyError(code=code, path=path, message=message, plan_id=plan.declared_plan_id))

    if plan.status is None:
        err("missing_status", "plan has no status line; triage it to a real status first")
    if plan.frontmatter_error:
        err("invalid_frontmatter", plan.frontmatter_error)
        return errors
    fm = plan.frontmatter or {}
    if "plan_id" not in fm:
        err("missing_plan_id", f"frontmatter plan_id is missing (expected {plan.derived_id!r})")
    else:
        raw_id = fm["plan_id"]
        if not isinstance(raw_id, str) or plan.declared_plan_id is None:
            err("invalid_plan_id", f"plan_id must be a qualified 'project-id#N' string, got {raw_id!r}")
        else:
            expected_project = normalize_project_name(repo_project_id)
            if plan.declared_plan_id != plan.derived_id or not plan.declared_plan_id.startswith(expected_project + "#"):
                err(
                    "plan_id_mismatch",
                    f"plan_id {raw_id!r} does not match this repository and filename (expected {plan.derived_id!r})",
                )
    if "dependencies" not in fm:
        err("missing_dependencies", "frontmatter dependencies is missing; use [] plus dependencies_reviewed for none")
        return errors
    deps = fm["dependencies"]
    if not isinstance(deps, list) or not all(isinstance(d, str) and d.strip() for d in deps):
        err("invalid_dependencies", "dependencies must be a list of non-empty 'project-id#N' strings")
        return errors
    evidence = fm.get("dependency_evidence") or {}
    if not isinstance(evidence, dict):
        err("missing_dependency_evidence", "dependency_evidence must be a mapping of dependency id to quoted text")
        evidence = {}
    reviewed = _date_text(fm.get("dependencies_reviewed"))
    if not deps and not (isinstance(reviewed, str) and reviewed.strip()):
        err("missing_dependencies_reviewed", "dependencies: [] requires a dependencies_reviewed date")
    for dep in deps:
        text = evidence.get(dep)
        if not (isinstance(text, str) and text.strip()):
            err("missing_dependency_evidence", f"dependency {dep!r} has no dependency_evidence text")
        normalized = normalize_qualified_id(dep)
        if normalized is None or normalized not in known_ids:
            err("unresolved_dependency", f"dependency {dep!r} does not resolve to any known plan")
    return errors


def validate_plan_dependencies(
    plan_files: Iterable[PlanFile],
    known_ids: set[str],
    *,
    repo_project_id: str,
    graph: Mapping[str, Sequence[str]] | None = None,
) -> list[PlanDependencyError]:
    """Validate the Plan #289 contract for each open plan in ``plan_files``.

    Closed plans are exempt. ``known_ids`` should cover the full corpus. When a
    ``graph`` (the full-corpus dependency graph) is given, cycles through the
    validated plans are reported; otherwise the graph of ``plan_files`` alone is used.
    """

    parsed = [plan for plan in (parse_plan(source) for source in plan_files) if plan is not None]
    errors: list[PlanDependencyError] = []
    validated_ids: list[str] = []
    for plan in parsed:
        if not plan.is_open:
            continue
        errors.extend(_contract_errors(plan, known_ids, repo_project_id))
        if plan.declared_plan_id:
            validated_ids.append(plan_identity(plan))
    cycle_graph = graph if graph is not None else build_dependency_graph(parsed)
    reported: set[frozenset[str]] = set()
    for node in sorted(set(validated_ids)):
        cycle = check_cycles(cycle_graph, through=[node])
        if cycle is None or frozenset(cycle) in reported:
            continue
        reported.add(frozenset(cycle))
        owner = next(p for p in parsed if plan_identity(p) == node)
        errors.append(
            PlanDependencyError(
                code="dependency_cycle",
                path=owner.source.relative_path,
                message="dependency cycle: " + " -> ".join(cycle),
                plan_id=node,
            )
        )
    return errors


def errors_to_json(errors: Sequence[PlanDependencyError]) -> str:
    """Serialize errors for CLI output."""

    return json.dumps([error.model_dump() for error in errors], indent=2)
