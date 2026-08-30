"""Compile report-only document lifecycle coverage and archive blockers.

The compiler inventories narrative Markdown exhaustively, validates exact-path
document declarations, and projects archive effects from the relationship
graph. It deliberately stops before semantic archive eligibility: a document
with no mechanical blocker is marked ``semantic_review_required``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
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
TERMINAL_LIFECYCLES = {
    "completed",
    "archive_candidate",
    "archived",
    "superseded",
    "deprecated",
    "mistaken",
    "deferred",
}
STATUS_SCAN_LINE_LIMIT = 40
ARCHIVE_MANIFEST_SCHEMA_VERSION = "archive-disposition-v1"
ARCHIVE_MANIFEST_DISPOSITIONS = {
    "superseded",
    "deprecated",
    "deferred",
    "mistaken",
    "candidate-for-resurrection",
}
ARCHIVE_MANIFEST_LIFECYCLE: DocumentLifecycle = "archive_candidate"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class ArchiveLifecycleError(RuntimeError):
    """Report malformed lifecycle declarations or unresolved report inputs."""


def _hash_path(path: Path) -> str:
    """Match the archive executor's stable hash for one file or directory."""

    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for child in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        digest.update(child.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(child.read_bytes())
    return digest.hexdigest()


def _archive_manifest_lifecycle(
    manifest_path: Path,
    *,
    repo_root: Path,
    narrative_documents: tuple[str, ...],
) -> dict[str, DocumentLifecycle]:
    """Read candidate identity and exact bytes from the ecosystem archive manifest.

    The manifest supplies only the candidate lifecycle for this report.
    Repository declarations and relationship effects remain independent.
    """

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArchiveLifecycleError(f"archive manifest does not exist: {manifest_path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArchiveLifecycleError(f"archive manifest is not valid JSON: {manifest_path}") from exc
    if not isinstance(raw, dict):
        raise ArchiveLifecycleError("archive manifest root must be an object")
    if raw.get("schema_version") != ARCHIVE_MANIFEST_SCHEMA_VERSION:
        raise ArchiveLifecycleError(
            "archive manifest has unsupported schema_version "
            f"{raw.get('schema_version')!r}"
        )
    manifest_repo_root = raw.get("repo_root")
    if not isinstance(manifest_repo_root, str) or not manifest_repo_root.strip():
        raise ArchiveLifecycleError("archive manifest.repo_root must be a non-empty path")
    if Path(manifest_repo_root).expanduser().resolve() != repo_root:
        raise ArchiveLifecycleError("archive manifest.repo_root does not match --repo-root")
    candidates = raw.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ArchiveLifecycleError("archive manifest.candidates must be a non-empty list")

    overrides: dict[str, DocumentLifecycle] = {}
    for index, candidate in enumerate(candidates):
        provenance = f"archive manifest.candidates[{index}]"
        if not isinstance(candidate, dict):
            raise ArchiveLifecycleError(f"{provenance} must be an object")
        path = _exact_path(candidate.get("path"), provenance=provenance, field="path")
        source = (repo_root / path).resolve()
        try:
            source.relative_to(repo_root)
        except ValueError as exc:
            raise ArchiveLifecycleError(
                f"{provenance}.path escapes archive manifest.repo_root: {path}"
            ) from exc
        if not source.exists():
            raise ArchiveLifecycleError(f"{provenance}.path does not exist: {path}")
        source_sha256 = candidate.get("expected_source_sha256")
        if not isinstance(source_sha256, str) or SHA256_PATTERN.fullmatch(source_sha256) is None:
            raise ArchiveLifecycleError(
                f"{provenance}.expected_source_sha256 must be a lowercase SHA-256 digest"
            )
        disposition = candidate.get("disposition")
        if disposition not in ARCHIVE_MANIFEST_DISPOSITIONS:
            raise ArchiveLifecycleError(
                f"{provenance}.disposition must be one of {sorted(ARCHIVE_MANIFEST_DISPOSITIONS)}"
            )
        if _hash_path(source) != source_sha256:
            raise ArchiveLifecycleError(f"{provenance}.expected_source_sha256 mismatch for {path}")
        manifest_root = PurePosixPath(path)
        affected_documents = (
            (path,)
            if source.is_file() and path in narrative_documents
            else tuple(
                document
                for document in narrative_documents
                if PurePosixPath(document).is_relative_to(manifest_root)
            )
            if source.is_dir()
            else ()
        )
        for document in affected_documents:
            if document in overrides:
                raise ArchiveLifecycleError(
                    f"{provenance}.path overlaps another archive manifest candidate at {document!r}"
                )
            overrides[document] = ARCHIVE_MANIFEST_LIFECYCLE
    return overrides


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
        (("active", "accepted", "in progress", "executing"), "active"),
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
    lifecycle_overrides: dict[str, DocumentLifecycle],
) -> ArchiveCandidate:
    """Compile one candidate's mechanical blockers and semantic-review boundary."""

    owned = tuple(item for item in declarations if item.path == path)
    lifecycle = lifecycle_overrides.get(path, document_lifecycle(repo_root / path))
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
    archive_manifest: Path | None = None,
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
    lifecycle_overrides = (
        _archive_manifest_lifecycle(
            archive_manifest,
            repo_root=root,
            narrative_documents=narrative_documents,
        )
        if archive_manifest is not None
        else {}
    )
    selected = (
        tuple(sorted(set(candidates)))
        if candidates
        else tuple(sorted(lifecycle_overrides))
        if archive_manifest is not None
        else narrative_documents
    )
    unknown_candidates = tuple(path for path in selected if path not in narrative_documents)
    if unknown_candidates:
        raise ArchiveLifecycleError(
            "candidate is not a tracked narrative Markdown document: " + ", ".join(unknown_candidates)
        )
    missing_manifest_candidates = tuple(path for path in selected if archive_manifest is not None and path not in lifecycle_overrides)
    if missing_manifest_candidates:
        raise ArchiveLifecycleError(
            "candidate is not present in archive manifest: " + ", ".join(missing_manifest_candidates)
        )
    compiled = tuple(
        _candidate(root, path, declarations, tracked, relationships, lifecycle_overrides) for path in selected
    )
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
    parser.add_argument(
        "--archive-manifest",
        type=Path,
        help="Ecosystem archive-disposition manifest binding candidates to exact source hashes",
    )
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        relationships = _load_relationships(args.repo_root, args.config)
        manifest_path = args.archive_manifest
        if manifest_path is not None and not manifest_path.is_absolute():
            manifest_path = args.repo_root / manifest_path
        report = build_archive_lifecycle_report(
            args.repo_root,
            relationships,
            candidates=tuple(args.candidate),
            archive_manifest=manifest_path,
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
