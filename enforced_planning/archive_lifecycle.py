"""Compile report-only document lifecycle coverage and archive blockers.

The compiler inventories narrative Markdown exhaustively, validates exact-path
document declarations, and projects archive effects from the relationship
graph. It deliberately stops before semantic archive eligibility: a document
with no mechanical blocker is marked ``semantic_review_required``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias

import yaml  # type: ignore[import-untyped]

from enforced_planning.context_packet import ContextPacketError
from enforced_planning.context_packet import relationship_specs
from enforced_planning.context_packet import selector_path_matches
from enforced_planning.relationship_context import inventory_repository


DocumentRole: TypeAlias = Literal[
    "authority",
    "execution",
    "current_evidence",
    "historical_evidence",
    "navigation",
    "generated_projection",
    "recovery",
]
DocumentLifecycle: TypeAlias = Literal[
    "draft",
    "active",
    "blocked",
    "completed",
    "archive_candidate",
    "archived",
    "superseded",
    "deprecated",
    "mistaken",
    "deferred",
    "unknown",
]
CandidateReadiness: TypeAlias = Literal["blocked", "semantic_review_required"]

ALLOWED_DOCUMENT_ROLES = {
    "authority",
    "execution",
    "current_evidence",
    "historical_evidence",
    "navigation",
    "generated_projection",
    "recovery",
}
TERMINAL_LIFECYCLES = {"completed", "archived", "superseded", "deprecated", "mistaken", "deferred"}
STATUS_SCAN_LINE_LIMIT = 40


class ArchiveLifecycleError(RuntimeError):
    """Report malformed lifecycle declarations or unresolved report inputs."""


@dataclass(frozen=True)
class DocumentDeclaration:
    """Represent one reviewed role and purpose-bearing path for a document."""

    path: str
    role: DocumentRole
    anchored_to: str
    reason: str
    lifecycle_source: str
    provenance: str


@dataclass(frozen=True)
class ArchiveEdgeImpact:
    """Expose how one relationship affects a candidate retirement transition."""

    relation: str
    direction: Literal["outgoing", "incoming"]
    archive_effect: str
    other_selectors: tuple[str, ...]
    reason: str
    provenance: str


@dataclass(frozen=True)
class ArchiveBlocker:
    """Name one deterministic condition that prevents semantic review."""

    code: str
    message: str
    provenance: str | None = None


@dataclass(frozen=True)
class ArchiveCandidate:
    """Summarize mechanical readiness without making an archive judgment."""

    path: str
    lifecycle: DocumentLifecycle
    declared: bool
    roles: tuple[str, ...]
    declarations: tuple[DocumentDeclaration, ...]
    readiness: CandidateReadiness
    edge_impacts: tuple[ArchiveEdgeImpact, ...]
    blockers: tuple[ArchiveBlocker, ...]


@dataclass(frozen=True)
class ArchiveLifecycleReport:
    """Provide deterministic document coverage and candidate blocker counts."""

    schema_version: int
    tracked_document_count: int
    declared_document_count: int
    undeclared_documents: tuple[str, ...]
    candidate_count: int
    blocked_count: int
    semantic_review_required_count: int
    candidates: tuple[ArchiveCandidate, ...]

    def to_json(self, *, pretty: bool = False) -> str:
        """Serialize without timestamps, absolute roots, or approval fields."""

        return json.dumps(
            asdict(self),
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
            ensure_ascii=True,
        ) + "\n"


def _exact_path(value: object, *, provenance: str, field: str) -> str:
    """Validate one repository-relative exact path rather than a selector."""

    if not isinstance(value, str) or not value.strip():
        raise ArchiveLifecycleError(f"{provenance}.{field} must be a non-empty string")
    path = value.strip()
    parts = PurePosixPath(path)
    if parts.is_absolute() or ".." in parts.parts or "::" in path or any(character in path for character in "*?["):
        raise ArchiveLifecycleError(f"{provenance}.{field} must be an exact repository-relative path")
    return path


def document_declarations(relationships: dict[str, Any]) -> tuple[DocumentDeclaration, ...]:
    """Validate exact-path role declarations without copying source-local status."""

    raw_documents = relationships.get("documents", []) or []
    if not isinstance(raw_documents, list):
        raise ArchiveLifecycleError("documents must be a list")
    declarations: list[DocumentDeclaration] = []
    for index, raw in enumerate(raw_documents):
        provenance = f"documents[{index}]"
        if not isinstance(raw, dict):
            raise ArchiveLifecycleError(f"{provenance} must be a mapping")
        path = _exact_path(raw.get("path"), provenance=provenance, field="path")
        role = str(raw.get("role", "")).strip()
        if role not in ALLOWED_DOCUMENT_ROLES:
            raise ArchiveLifecycleError(f"{provenance} has unsupported role {role!r}")
        justification = raw.get("justification")
        if not isinstance(justification, dict):
            raise ArchiveLifecycleError(f"{provenance}.justification must be a mapping")
        anchored_to = _exact_path(
            justification.get("anchored_to"),
            provenance=f"{provenance}.justification",
            field="anchored_to",
        )
        if anchored_to == path:
            raise ArchiveLifecycleError(f"{provenance}.justification.anchored_to cannot point to itself")
        reason = str(justification.get("reason", "")).strip()
        if not reason:
            raise ArchiveLifecycleError(f"{provenance}.justification.reason must explain the document's purpose")
        lifecycle_source = str(raw.get("lifecycle_source", "document_status")).strip()
        if lifecycle_source != "document_status":
            raise ArchiveLifecycleError(
                f"{provenance} has unsupported lifecycle_source {lifecycle_source!r}; use source-local document_status"
            )
        declarations.append(
            DocumentDeclaration(
                path=path,
                role=role,  # type: ignore[arg-type]
                anchored_to=anchored_to,
                reason=reason,
                lifecycle_source=lifecycle_source,
                provenance=provenance,
            )
        )
    return tuple(declarations)


def _status_value(path: Path) -> str:
    """Read an explicitly labeled status field without interpreting document prose."""

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in text.splitlines()[:STATUS_SCAN_LINE_LIMIT]:
        stripped = line.strip()
        folded = stripped.casefold()
        if folded.startswith("**status:**"):
            return stripped.split(":**", 1)[1].strip().casefold()
        if folded.startswith("status:"):
            return stripped.split(":", 1)[1].strip().casefold()
    return ""


def document_lifecycle(path: Path) -> DocumentLifecycle:
    """Normalize only an explicit source-local status label into lifecycle vocabulary."""

    value = _status_value(path)
    for marker in ("✅", "🚧", "📋", "⏸️"):
        value = value.replace(marker, "")
    value = value.strip().replace("_", " ").replace("-", " ")
    prefixes: tuple[tuple[tuple[str, ...], DocumentLifecycle], ...] = (
        (("archive candidate",), "archive_candidate"),
        (("superseded",), "superseded"),
        (("archived",), "archived"),
        (("deprecated",), "deprecated"),
        (("mistaken",), "mistaken"),
        (("deferred",), "deferred"),
        (("complete", "completed", "done"), "completed"),
        (("blocked", "paused"), "blocked"),
        (("planned", "draft", "proposed"), "draft"),
        (("active", "in progress", "executing"), "active"),
    )
    for candidates, lifecycle in prefixes:
        if any(value == candidate or value.startswith(candidate + " ") or value.startswith(candidate + " (") for candidate in candidates):
            return lifecycle
    return "unknown"


def _edge_impacts(path: str, relationships: dict[str, Any]) -> tuple[ArchiveEdgeImpact, ...]:
    """Project every matching edge with its explicit or fail-safe archive effect."""

    impacts: list[ArchiveEdgeImpact] = []
    try:
        specs = relationship_specs(relationships)
    except ContextPacketError as exc:
        raise ArchiveLifecycleError(str(exc)) from exc
    for spec in specs:
        source_match = any(selector_path_matches(selector, path) for selector in spec.sources)
        target_match = any(selector_path_matches(selector, path) for selector in spec.targets)
        if target_match:
            impacts.append(
                ArchiveEdgeImpact(
                    relation=spec.relation,
                    direction="incoming",
                    archive_effect=spec.archive_effect,
                    other_selectors=spec.sources,
                    reason=spec.reason,
                    provenance=spec.provenance,
                )
            )
        elif source_match:
            impacts.append(
                ArchiveEdgeImpact(
                    relation=spec.relation,
                    direction="outgoing",
                    archive_effect=spec.archive_effect,
                    other_selectors=spec.targets,
                    reason=spec.reason,
                    provenance=spec.provenance,
                )
            )
    return tuple(
        sorted(
            impacts,
            key=lambda item: (item.provenance, item.direction, item.relation, item.other_selectors),
        )
    )


def _candidate(
    repo_root: Path,
    path: str,
    declarations: tuple[DocumentDeclaration, ...],
    tracked_paths: set[str],
    relationships: dict[str, Any],
) -> ArchiveCandidate:
    """Compile one candidate's mechanical blockers and semantic-review boundary."""

    owned = tuple(item for item in declarations if item.path == path)
    lifecycle = document_lifecycle(repo_root / path)
    impacts = _edge_impacts(path, relationships)
    blockers: list[ArchiveBlocker] = []
    if not owned:
        blockers.append(
            ArchiveBlocker(
                code="document-undeclared",
                message="Document has no reviewed role and purpose-bearing justification.",
            )
        )
    if lifecycle not in TERMINAL_LIFECYCLES:
        blockers.append(
            ArchiveBlocker(
                code="lifecycle-not-terminal",
                message=f"Source-local lifecycle {lifecycle!r} is not terminal for active use.",
            )
        )
    for declaration in owned:
        if declaration.anchored_to not in tracked_paths:
            blockers.append(
                ArchiveBlocker(
                    code="justification-anchor-unresolved",
                    message=f"Purpose anchor {declaration.anchored_to!r} is not Git-tracked.",
                    provenance=declaration.provenance,
                )
            )
    effect_blockers = {
        "blocks_archive": (
            "archive-edge-blocks",
            "A current operational, authority, work, or evidence edge blocks archival.",
        ),
        "redirect_before_archive": (
            "archive-redirect-required",
            "A reader or index must be redirected before archival.",
        ),
        "review_required": (
            "archive-effect-review-required",
            "The relationship's archive meaning requires semantic classification.",
        ),
    }
    for impact in impacts:
        blocker = effect_blockers.get(impact.archive_effect)
        if blocker is not None:
            blockers.append(ArchiveBlocker(blocker[0], blocker[1], impact.provenance))
    ordered_blockers = tuple(sorted(blockers, key=lambda item: (item.code, item.provenance or "", item.message)))
    return ArchiveCandidate(
        path=path,
        lifecycle=lifecycle,
        declared=bool(owned),
        roles=tuple(sorted({item.role for item in owned})),
        declarations=owned,
        readiness="blocked" if ordered_blockers else "semantic_review_required",
        edge_impacts=impacts,
        blockers=ordered_blockers,
    )


def build_archive_lifecycle_report(
    repo_root: Path,
    relationships: dict[str, Any],
    *,
    candidates: tuple[str, ...] = (),
) -> ArchiveLifecycleReport:
    """Report exhaustive narrative-document coverage and candidate blockers."""

    root = repo_root.resolve()
    inventory = inventory_repository(root)
    narrative_documents = tuple(
        artifact.path
        for artifact in inventory.artifacts
        if artifact.format == "markdown" and artifact.classification == "documentation"
    )
    tracked = {artifact.path for artifact in inventory.artifacts}
    declarations = document_declarations(relationships)
    for declaration in declarations:
        if declaration.path not in narrative_documents:
            raise ArchiveLifecycleError(
                f"{declaration.provenance}.path is not a tracked narrative Markdown document: {declaration.path}"
            )
    selected = tuple(sorted(set(candidates))) if candidates else narrative_documents
    unknown_candidates = tuple(path for path in selected if path not in narrative_documents)
    if unknown_candidates:
        raise ArchiveLifecycleError(
            "candidate is not a tracked narrative Markdown document: " + ", ".join(unknown_candidates)
        )
    compiled = tuple(_candidate(root, path, declarations, tracked, relationships) for path in selected)
    declared_paths = {item.path for item in declarations}
    undeclared = tuple(path for path in narrative_documents if path not in declared_paths)
    return ArchiveLifecycleReport(
        schema_version=1,
        tracked_document_count=len(narrative_documents),
        declared_document_count=len(declared_paths),
        undeclared_documents=undeclared,
        candidate_count=len(compiled),
        blocked_count=sum(item.readiness == "blocked" for item in compiled),
        semantic_review_required_count=sum(item.readiness == "semantic_review_required" for item in compiled),
        candidates=compiled,
    )


def _load_relationships(repo_root: Path, config_path: str | Path) -> dict[str, Any]:
    """Load one lifecycle graph as a mapping and fail loudly on malformed YAML."""

    path = Path(config_path)
    if not path.is_absolute():
        path = repo_root / path
    if not path.exists():
        raise ArchiveLifecycleError(f"relationship config does not exist: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ArchiveLifecycleError(f"relationship config root must be a mapping: {path}")
    return loaded


def main(argv: list[str] | None = None) -> int:
    """Run the portable report-only document lifecycle CLI."""

    parser = argparse.ArgumentParser(description="Report document lifecycle coverage and archive blockers")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", default="scripts/relationships.yaml")
    parser.add_argument("--candidate", action="append", default=[], help="Exact document path; repeat as needed")
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        relationships = _load_relationships(args.repo_root, args.config)
        report = build_archive_lifecycle_report(
            args.repo_root,
            relationships,
            candidates=tuple(args.candidate),
        )
    except (ArchiveLifecycleError, OSError) as exc:
        parser.exit(2, f"archive-lifecycle: {exc}\n")
    payload = report.to_json(pretty=args.pretty)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


__all__ = [
    "ArchiveBlocker",
    "ArchiveCandidate",
    "ArchiveEdgeImpact",
    "ArchiveLifecycleError",
    "ArchiveLifecycleReport",
    "DocumentDeclaration",
    "build_archive_lifecycle_report",
    "document_declarations",
    "document_lifecycle",
    "main",
]
