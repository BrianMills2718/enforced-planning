"""Build bounded edit-context packets from source summaries and relationship edges.

The packet compiler joins actual docstrings and Markdown summaries from
``relationship_context`` with reviewed or legacy declarations from
``relationships.yaml``. It never copies summary prose from the registry and it
reports unresolved or budget-omitted context explicitly.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import stat
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias

import yaml  # type: ignore[import-untyped]

from enforced_planning.relationship_context import (
    ArtifactRecord,
    Diagnostic,
    InventoryReport,
    classify_artifact,
    classify_format,
    inventory_repository,
)

Direction: TypeAlias = Literal["self", "outgoing", "incoming"]
MaintenanceAction: TypeAlias = Literal["regenerate", "reconcile", "block", "lineage_only"]
ArchiveEffect: TypeAlias = Literal[
    "blocks_archive",
    "redirect_before_archive",
    "lineage_only",
    "review_required",
]

ALLOWED_RELATIONS = {
    "acceptance_evidence",
    "decides",
    "documents_current",
    "generated_from",
    "governed_by",
    "implements",
    "planned_by",
    "required_reading",
    "supersedes",
    "targets",
    "tests",
    "updates",
}
ALLOWED_MAINTENANCE = {"regenerate", "reconcile", "block", "lineage_only"}
ALLOWED_ARCHIVE_EFFECTS = {
    "blocks_archive",
    "redirect_before_archive",
    "lineage_only",
    "review_required",
}
CONTEXT_PACKET_SCHEMA_VERSION = 2
CONTEXT_PACKET_V3_SCHEMA_VERSION = 3
CONTEXT_RECEIPT_SCHEMA_VERSION = 1
RELATION_PRIORITY = {
    "self": 0,
    "governed_by": 10,
    "decides": 20,
    "planned_by": 30,
    "required_reading": 40,
    "tests": 50,
    "acceptance_evidence": 60,
    "implements": 70,
    "documents_current": 80,
    "updates": 90,
    "targets": 100,
    "generated_from": 110,
    "supersedes": 120,
}


class ContextPacketError(RuntimeError):
    """Report malformed relationships or a target that cannot be resolved."""


@dataclass(frozen=True)
class RelationshipSpec:
    """Normalize one reviewed or legacy relationship declaration."""

    sources: tuple[str, ...]
    targets: tuple[str, ...]
    relation: str
    reason: str
    maintenance: MaintenanceAction
    archive_effect: ArchiveEffect
    provenance: str


@dataclass(frozen=True)
class ContextDiagnostic:
    """Describe context that could not be resolved or included."""

    code: str
    message: str
    selector: str | None = None


@dataclass(frozen=True)
class ContextItem:
    """Carry one provenance-bound source summary in an edit context packet."""

    node_id: str
    path: str
    symbol: str | None
    relation: str
    direction: Direction
    reason: str
    maintenance: str
    archive_effect: str
    provenance: str
    summary: str | None
    summary_source: str | None
    line: int | None
    summary_complete: bool


@dataclass(frozen=True)
class ContextPacket:
    """Provide deterministic bounded context for one file or Python symbol edit."""

    schema_version: int
    target: str
    max_items: int
    max_chars: int
    included_chars: int
    omitted_count: int
    items: tuple[ContextItem, ...]
    diagnostics: tuple[ContextDiagnostic, ...]

    def to_json(self, *, pretty: bool = False) -> str:
        """Serialize the packet deterministically for hooks and agents."""

        return json.dumps(
            asdict(self),
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            sort_keys=True,
            ensure_ascii=True,
        ) + "\n"


@dataclass(frozen=True)
class RequiredContextAtom:
    """Carry one complete required file and its exact source identity."""

    path: str
    content: str
    content_sha256: str
    revision: str | None
    working_tree_state: Literal["clean", "working_copy"]
    byte_count: int
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class RequiredAtomReceipt:
    """Describe one expected atom without archiving its payload."""

    path: str
    content_sha256: str
    revision: str | None
    working_tree_state: Literal["clean", "working_copy"]
    byte_count: int
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class ContextPacketV3(ContextPacket):
    """Separate unclipped required files from bounded optional summaries."""

    required_capacity_bytes: int
    required_bytes: int
    required_atoms: tuple[RequiredContextAtom, ...]


@dataclass(frozen=True)
class ContextReceipt:
    """Bind expected context to an action without claiming host delivery."""

    schema_version: int
    packet_sha256: str
    session_id: str
    context_epoch: str
    action: str
    target: str
    adapter_id: str
    adapter_version: str
    visibility: Literal["expected"]
    required_atoms: tuple[RequiredAtomReceipt, ...]

    def to_json(self, *, pretty: bool = False) -> str:
        """Serialize the expected receipt deterministically."""

        return (
            json.dumps(
                asdict(self),
                indent=2 if pretty else None,
                separators=None if pretty else (",", ":"),
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


def _to_strings(value: Any) -> tuple[str, ...]:
    """Normalize one selector field without accepting broad arbitrary values."""

    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(item for item in value if item.strip())
    raise ContextPacketError(f"relationship selector must be a string or list of strings, got {type(value).__name__}")


def _to_refs(value: Any) -> tuple[str, ...]:
    """Normalize ADR and plan reference identifiers that may be numeric in V1."""

    if value is None:
        return ()
    if isinstance(value, (str, int)):
        return (str(value),)
    if isinstance(value, list) and all(isinstance(item, (str, int)) for item in value):
        return tuple(str(item) for item in value)
    raise ContextPacketError(f"relationship references must be strings or integers, got {type(value).__name__}")


def _validate_spec(spec: RelationshipSpec) -> RelationshipSpec:
    """Fail loudly when an edge cannot produce predictable context behavior."""

    if not spec.sources or not spec.targets:
        raise ContextPacketError(f"{spec.provenance} must declare non-empty sources and targets")
    if spec.relation not in ALLOWED_RELATIONS:
        raise ContextPacketError(f"{spec.provenance} has unsupported relation {spec.relation!r}")
    if spec.maintenance not in ALLOWED_MAINTENANCE:
        raise ContextPacketError(f"{spec.provenance} has unsupported maintenance action {spec.maintenance!r}")
    if spec.archive_effect not in ALLOWED_ARCHIVE_EFFECTS:
        raise ContextPacketError(f"{spec.provenance} has unsupported archive effect {spec.archive_effect!r}")
    if not spec.reason.strip():
        raise ContextPacketError(f"{spec.provenance} must explain why the relationship exists")
    return spec


def relationship_specs(relationships: dict[str, Any]) -> tuple[RelationshipSpec, ...]:
    """Normalize explicit V2 edges and existing relationship sections."""

    specs: list[RelationshipSpec] = []
    explicit_edges = relationships.get("relationships", relationships.get("edges", [])) or []
    if not isinstance(explicit_edges, list):
        raise ContextPacketError("relationships/edges must be a list")
    for index, edge in enumerate(explicit_edges):
        provenance = f"relationships[{index}]"
        if not isinstance(edge, dict):
            raise ContextPacketError(f"{provenance} must be a mapping")
        if "summary" in edge or "description_summary" in edge:
            raise ContextPacketError(f"{provenance} duplicates source summary prose; summaries must be extracted")
        relation = str(edge.get("relation", "")).strip()
        maintenance = str(edge.get("maintenance", "reconcile")).strip()
        archive_effect = str(edge.get("archive_effect", "review_required")).strip()
        spec = RelationshipSpec(
            sources=_to_strings(edge.get("sources", edge.get("source", edge.get("from")))),
            targets=_to_strings(edge.get("targets", edge.get("target", edge.get("to")))),
            relation=relation,
            reason=str(edge.get("reason", "")).strip(),
            maintenance=maintenance,  # type: ignore[arg-type]
            archive_effect=archive_effect,  # type: ignore[arg-type]
            provenance=provenance,
        )
        specs.append(_validate_spec(spec))

    for index, edge in enumerate(relationships.get("couplings", []) or []):
        if not isinstance(edge, dict):
            continue
        specs.append(
            _validate_spec(
                RelationshipSpec(
                    sources=_to_strings(edge.get("sources", edge.get("source"))),
                    targets=_to_strings(edge.get("docs")),
                    relation="updates",
                    reason=str(edge.get("description") or "Source change may require coupled documentation review."),
                    maintenance="reconcile",
                    archive_effect="review_required",
                    provenance=f"couplings[{index}]",
                )
            )
        )

    adrs = relationships.get("adrs", {}) or {}
    for index, edge in enumerate(relationships.get("governance", []) or []):
        if not isinstance(edge, dict):
            continue
        governance_targets: list[str] = []
        for adr in _to_refs(edge.get("adrs")):
            raw = adrs.get(adr, adrs.get(int(adr), {}) if adr.isdigit() else {}) if isinstance(adrs, dict) else {}
            if isinstance(raw, dict) and raw.get("file"):
                governance_targets.append(str(raw["file"]))
        if not governance_targets:
            continue
        specs.append(
            _validate_spec(
                RelationshipSpec(
                    sources=_to_strings(edge.get("sources", edge.get("source"))),
                    targets=tuple(governance_targets),
                    relation="governed_by",
                    reason=str(edge.get("context") or "Governing architecture decision."),
                    maintenance="reconcile",
                    archive_effect="review_required",
                    provenance=f"governance[{index}]",
                )
            )
        )

    architecture_fields = (
        (("current_docs", "current"), "documents_current", "Current architecture truth."),
        (("target_docs", "target"), "targets", "Target architecture direction."),
        (("gap_docs", "gaps"), "updates", "Known gap affecting this surface."),
        (("plan_refs",), "planned_by", "Active or historical plan for this surface."),
    )
    for index, edge in enumerate(relationships.get("architecture", []) or []):
        if not isinstance(edge, dict):
            continue
        sources = _to_strings(edge.get("source_patterns", edge.get("sources", edge.get("source"))))
        for fields, relation, reason in architecture_fields:
            declared_fields = [field for field in fields if edge.get(field) is not None]
            if len(declared_fields) > 1:
                raise ContextPacketError(
                    f"architecture[{index}] declares duplicate aliases {', '.join(fields)}"
                )
            architecture_targets = _to_strings(
                edge.get(declared_fields[0]) if declared_fields else None
            )
            if architecture_targets:
                specs.append(
                    _validate_spec(
                        RelationshipSpec(
                            sources=sources,
                            targets=architecture_targets,
                            relation=relation,
                            reason=reason,
                            maintenance="reconcile" if relation != "targets" else "lineage_only",
                            archive_effect="review_required",
                            provenance=f"architecture[{index}].{declared_fields[0]}",
                        )
                    )
                )

    defaults = _to_strings((relationships.get("required_reading", {}) or {}).get("defaults"))
    if defaults:
        specs.append(
            RelationshipSpec(
                sources=("**",),
                targets=defaults,
                relation="required_reading",
                reason="Repository-default context required before edits.",
                maintenance="lineage_only",
                archive_effect="review_required",
                provenance="required_reading.defaults",
            )
        )
    return tuple(specs)


def _split_selector(selector: str) -> tuple[str, str | None]:
    """Split a file or ``file::qualified.symbol`` selector."""

    path, separator, symbol = selector.partition("::")
    return path, symbol if separator else None


def _glob_matches(value: str, pattern: str) -> bool:
    """Match recursive globs with ``**/`` also representing zero directories."""

    variants = {pattern}
    pending = [pattern]
    while pending:
        candidate = pending.pop()
        if "/**/" in candidate:
            collapsed = candidate.replace("/**/", "/", 1)
            if collapsed not in variants:
                variants.add(collapsed)
                pending.append(collapsed)
        if candidate.startswith("**/"):
            collapsed = candidate[3:]
            if collapsed not in variants:
                variants.add(collapsed)
                pending.append(collapsed)
    return any(fnmatch.fnmatch(value, variant) for variant in variants)


def _selector_matches(selector: str, path: str, symbol: str | None) -> bool:
    """Match one path/symbol selector against a requested target node."""

    selector_path, selector_symbol = _split_selector(selector)
    if not _glob_matches(path, selector_path):
        return False
    return selector_symbol is None or fnmatch.fnmatch(symbol or "", selector_symbol)


def _expand_selectors(selectors: tuple[str, ...], inventory: InventoryReport) -> tuple[tuple[str, str | None], ...]:
    """Expand declared selectors deterministically against tracked artifacts and symbols."""

    found: set[tuple[str, str | None]] = set()
    for selector in selectors:
        selector_path, selector_symbol = _split_selector(selector)
        for artifact in inventory.artifacts:
            if not _glob_matches(artifact.path, selector_path):
                continue
            if selector_symbol is None:
                found.add((artifact.path, None))
            elif any(symbol.qualified_name == selector_symbol for symbol in artifact.symbols):
                found.add((artifact.path, selector_symbol))
    return tuple(sorted(found, key=lambda item: (item[0], item[1] or "")))


def expand_selectors(selectors: tuple[str, ...], inventory: InventoryReport) -> tuple[tuple[str, str | None], ...]:
    """Expand file/symbol selectors for context and reconciliation consumers."""

    return _expand_selectors(selectors, inventory)


def selector_path_matches(selector: str, path: str) -> bool:
    """Match only the file component of a selector for file-level change sets."""

    selector_path, _symbol = _split_selector(selector)
    return _glob_matches(path, selector_path)


def _required_selector_provenance(
    target_path: str,
    target_symbol: str | None,
    relationships: dict[str, Any],
) -> dict[str, set[str]]:
    """Resolve applicable required-reading declarations to selectors and provenance."""

    selected: dict[str, set[str]] = {}

    def add(selectors: tuple[str, ...], provenance: str) -> None:
        for selector in selectors:
            selected.setdefault(selector, set()).add(provenance)

    for spec in relationship_specs(relationships):
        if spec.relation != "required_reading":
            continue
        source_match = any(_selector_matches(item, target_path, target_symbol) for item in spec.sources)
        target_match = any(_selector_matches(item, target_path, target_symbol) for item in spec.targets)
        if source_match:
            add(spec.targets, spec.provenance)
        elif target_match:
            add(spec.sources, spec.provenance)

    required_reading = relationships.get("required_reading", {}) or {}
    if not isinstance(required_reading, dict):
        raise ContextPacketError("required_reading must be a mapping")
    gates = required_reading.get("gates", []) or []
    if not isinstance(gates, list):
        raise ContextPacketError("required_reading.gates must be a list")
    for index, gate in enumerate(gates):
        provenance = f"required_reading.gates[{index}]"
        if not isinstance(gate, dict):
            raise ContextPacketError(f"{provenance} must be a mapping")
        applies_to = _to_strings(gate.get("applies_to"))
        documents = _to_strings(gate.get("documents"))
        if not applies_to or not documents:
            raise ContextPacketError(f"{provenance} requires non-empty applies_to and documents")
        if any(_selector_matches(selector, target_path, target_symbol) for selector in applies_to):
            add(documents, provenance)
    return selected


def _required_paths(
    inventory: InventoryReport,
    selector_provenance: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Expand required full-file selectors without accepting symbol fragments."""

    paths: dict[str, set[str]] = {}
    for selector, provenance in selector_provenance.items():
        selector_path, selector_symbol = _split_selector(selector)
        parts = PurePosixPath(selector_path)
        if not selector_path or parts.is_absolute() or ".." in parts.parts:
            raise ContextPacketError(f"required context selector must be repository-relative: {selector!r}")
        if selector_symbol is not None:
            raise ContextPacketError(f"required context must select a full file, not a symbol: {selector!r}")
        if any(character in selector_path for character in "*?["):
            matches = sorted(
                artifact.path for artifact in inventory.artifacts if _glob_matches(artifact.path, selector_path)
            )
            if not matches:
                raise ContextPacketError(f"required context selector resolved no files: {selector!r}")
        else:
            matches = [selector_path]
        for path in matches:
            paths.setdefault(path, set()).update(provenance)
    return paths


def _git_output(repo_root: Path, args: list[str]) -> str:
    """Run one bounded read-only Git query and return stripped stdout."""

    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ContextPacketError(f"Git context identity query failed: {detail}")
    return result.stdout.strip()


def _git_bytes(repo_root: Path, args: list[str]) -> bytes:
    """Run one bounded read-only Git query that must preserve exact bytes."""

    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise ContextPacketError(f"Git context byte query failed: {detail}")
    return result.stdout


def _required_atoms(
    repo_root: Path,
    target_path: str,
    target_symbol: str | None,
    relationships: dict[str, Any],
    inventory: InventoryReport,
    required_capacity_bytes: int,
) -> tuple[RequiredContextAtom, ...]:
    """Read every applicable required file whole or block compilation."""

    if required_capacity_bytes < 1:
        raise ContextPacketError("required_capacity_bytes must be positive")
    selectors = _required_selector_provenance(target_path, target_symbol, relationships)
    paths = _required_paths(inventory, selectors)
    atoms: list[RequiredContextAtom] = []
    for relative_path in sorted(paths):
        path = repo_root / relative_path
        try:
            mode = path.stat().st_mode
        except FileNotFoundError as exc:
            raise ContextPacketError(f"required context file is missing: {relative_path}") from exc
        except OSError as exc:
            raise ContextPacketError(f"required context file is unreadable: {relative_path}: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise ContextPacketError(f"required context path is not a regular file: {relative_path}")
        state_before = _git_output(repo_root, ["status", "--porcelain=v1", "--", relative_path])
        try:
            raw = path.read_bytes()
            content = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ContextPacketError(f"required context file is unreadable UTF-8: {relative_path}: {exc}") from exc
        state_after = _git_output(repo_root, ["status", "--porcelain=v1", "--", relative_path])
        if state_before != state_after:
            raise ContextPacketError(f"required context changed during observation: {relative_path}")
        dirty = bool(state_after)
        revision: str | None = None
        if not dirty:
            revision = _git_output(repo_root, ["log", "-1", "--format=%H", "--", relative_path])
            if not revision:
                raise ContextPacketError(f"required context has no source revision: {relative_path}")
            committed = _git_bytes(repo_root, ["show", f"{revision}:{relative_path}"])
            if committed != raw:
                raise ContextPacketError(f"required context does not match its source revision: {relative_path}")
        atoms.append(
            RequiredContextAtom(
                path=relative_path,
                content=content,
                content_sha256=hashlib.sha256(raw).hexdigest(),
                revision=revision,
                working_tree_state="working_copy" if dirty else "clean",
                byte_count=len(raw),
                provenance=tuple(sorted(paths[relative_path])),
            )
        )
    required_bytes = sum(atom.byte_count for atom in atoms)
    if required_bytes > required_capacity_bytes:
        raise ContextPacketError(
            f"required context needs {required_bytes} bytes but capacity is {required_capacity_bytes}; "
            "required atoms cannot be clipped"
        )
    return tuple(atoms)


def _context_item(
    artifact: ArtifactRecord,
    *,
    symbol_name: str | None,
    relation: str,
    direction: Direction,
    reason: str,
    maintenance: str,
    archive_effect: str,
    provenance: str,
) -> ContextItem:
    """Bind one artifact or symbol's actual source summary to an edge."""

    if symbol_name is None:
        return ContextItem(
            node_id=artifact.path,
            path=artifact.path,
            symbol=None,
            relation=relation,
            direction=direction,
            reason=reason,
            maintenance=maintenance,
            archive_effect=archive_effect,
            provenance=provenance,
            summary=artifact.summary,
            summary_source=artifact.summary_source,
            line=None,
            summary_complete=True,
        )
    symbol = next((item for item in artifact.symbols if item.qualified_name == symbol_name), None)
    if symbol is None:
        raise ContextPacketError(f"symbol {artifact.path}::{symbol_name} is not present in static inventory")
    return ContextItem(
        node_id=symbol.symbol_id,
        path=artifact.path,
        symbol=symbol_name,
        relation=relation,
        direction=direction,
        reason=reason,
        maintenance=maintenance,
        archive_effect=archive_effect,
        provenance=provenance,
        summary=symbol.docstring,
        summary_source="python:symbol-docstring" if symbol.docstring else None,
        line=symbol.line,
        summary_complete=True,
    )


def _item_chars(item: ContextItem) -> int:
    """Measure exactly the serialized context contribution of one item."""

    return len(json.dumps(asdict(item), sort_keys=True, ensure_ascii=True, separators=(",", ":")))


def _fit_target(item: ContextItem, max_chars: int) -> ContextItem:
    """Keep the target present by truncating only its source summary when required."""

    if _item_chars(item) <= max_chars:
        return item
    if item.summary is None:
        raise ContextPacketError("context character budget is too small for target metadata")
    empty = replace(item, summary="", summary_complete=False)
    available = max_chars - _item_chars(empty)
    if available < 0:
        raise ContextPacketError("context character budget is too small for target metadata")
    return replace(item, summary=item.summary[:available], summary_complete=False)


def build_context_packet(
    repo_root: Path,
    target_path: str,
    relationships: dict[str, Any],
    *,
    target_symbol: str | None = None,
    max_items: int = 20,
    max_chars: int = 8_000,
    allow_untracked_target: bool = False,
) -> ContextPacket:
    """Resolve and budget source-derived context for one edit target."""

    if max_items < 1:
        raise ContextPacketError("max_items must be at least 1")
    if max_chars < 1:
        raise ContextPacketError("max_chars must be positive")
    target_parts = PurePosixPath(target_path)
    if not target_path or target_parts.is_absolute() or ".." in target_parts.parts:
        raise ContextPacketError("target must be a repository-relative path without traversal")
    inventory = inventory_repository(repo_root)
    by_path = {artifact.path: artifact for artifact in inventory.artifacts}
    target_artifact = by_path.get(target_path)
    if target_artifact is None:
        if not allow_untracked_target:
            raise ContextPacketError(f"target {target_path!r} is not Git-tracked")
        if target_symbol is not None:
            raise ContextPacketError("an untracked target cannot resolve a Python symbol")
        target_artifact = ArtifactRecord(
            path=target_path,
            format=classify_format(target_path),
            classification=classify_artifact(target_path),
            working_tree_state="missing",
            summary=None,
            summary_source=None,
            symbols=(),
            diagnostics=(
                Diagnostic(
                    code="target-untracked-new-file",
                    message="Edit target is not Git-tracked yet; relationship context is path-derived.",
                ),
            ),
        )

    candidates: list[ContextItem] = [
        _context_item(
            target_artifact,
            symbol_name=target_symbol,
            relation="self",
            direction="self",
            reason="Source-local context for the requested edit target.",
            maintenance="lineage_only",
            archive_effect="lineage_only",
            provenance="inventory",
        )
    ]
    diagnostics: list[ContextDiagnostic] = []
    if target_path not in by_path:
        diagnostics.append(
            ContextDiagnostic(
                code="target-untracked-new-file",
                message="Edit target is not Git-tracked yet; relationship context is path-derived.",
                selector=target_path,
            )
        )
    for spec in relationship_specs(relationships):
        source_match = any(_selector_matches(selector, target_path, target_symbol) for selector in spec.sources)
        target_match = any(_selector_matches(selector, target_path, target_symbol) for selector in spec.targets)
        if not source_match and not target_match:
            continue
        neighbor_selectors = spec.targets if source_match else spec.sources
        expanded = _expand_selectors(neighbor_selectors, inventory)
        if not expanded:
            diagnostics.append(
                ContextDiagnostic(
                    "relationship-target-unresolved",
                    f"{spec.provenance} matched the edit target but no neighbor artifact resolved",
                    selector=", ".join(neighbor_selectors),
                )
            )
            continue
        for path, symbol_name in expanded:
            if path == target_path and symbol_name == target_symbol:
                continue
            candidates.append(
                _context_item(
                    by_path[path],
                    symbol_name=symbol_name,
                    relation=spec.relation,
                    direction="outgoing" if source_match else "incoming",
                    reason=spec.reason,
                    maintenance=spec.maintenance,
                    archive_effect=spec.archive_effect,
                    provenance=spec.provenance,
                )
            )

    deduplicated: dict[tuple[str, str, str], ContextItem] = {}
    for item in candidates:
        key = (item.node_id, item.relation, item.direction)
        deduplicated.setdefault(key, item)
    ordered = sorted(
        deduplicated.values(),
        key=lambda item: (
            RELATION_PRIORITY.get(item.relation, 999),
            0 if item.provenance.startswith("relationships[") else 1,
            item.path,
            item.symbol or "",
            item.direction,
        ),
    )
    included: list[ContextItem] = []
    omitted = 0
    used_chars = 0
    for index, item in enumerate(ordered):
        if index == 0:
            item = _fit_target(item, max_chars)
        item_chars = _item_chars(item)
        if len(included) >= max_items or used_chars + item_chars > max_chars:
            omitted += 1
            continue
        included.append(item)
        used_chars += item_chars
    if omitted:
        diagnostics.append(
            ContextDiagnostic(
                "context-budget-omitted",
                f"{omitted} relationship context item(s) omitted by deterministic budget",
            )
        )
    return ContextPacket(
        schema_version=CONTEXT_PACKET_SCHEMA_VERSION,
        target=f"{target_path}::{target_symbol}" if target_symbol else target_path,
        max_items=max_items,
        max_chars=max_chars,
        included_chars=used_chars,
        omitted_count=omitted,
        items=tuple(included),
        diagnostics=tuple(diagnostics),
    )


def build_context_packet_with_receipt(
    repo_root: Path,
    target_path: str,
    relationships: dict[str, Any],
    *,
    required_capacity_bytes: int,
    session_id: str,
    context_epoch: str,
    action: str,
    adapter_id: str,
    adapter_version: str,
    target_symbol: str | None = None,
    max_items: int = 20,
    max_chars: int = 8_000,
    allow_untracked_target: bool = False,
) -> tuple[ContextPacketV3, ContextReceipt]:
    """Build V3 required context and an honest expected-visibility receipt."""

    identities = {
        "session_id": session_id,
        "context_epoch": context_epoch,
        "action": action,
        "adapter_id": adapter_id,
        "adapter_version": adapter_version,
    }
    empty = [name for name, value in identities.items() if not value.strip()]
    if empty:
        raise ContextPacketError(f"receipt identity fields must be non-empty: {', '.join(empty)}")
    base = build_context_packet(
        repo_root,
        target_path,
        relationships,
        target_symbol=target_symbol,
        max_items=max_items,
        max_chars=max_chars,
        allow_untracked_target=allow_untracked_target,
    )
    inventory = inventory_repository(repo_root)
    atoms = _required_atoms(
        repo_root,
        target_path,
        target_symbol,
        relationships,
        inventory,
        required_capacity_bytes,
    )
    packet = ContextPacketV3(
        schema_version=CONTEXT_PACKET_V3_SCHEMA_VERSION,
        target=base.target,
        max_items=base.max_items,
        max_chars=base.max_chars,
        included_chars=base.included_chars,
        omitted_count=base.omitted_count,
        items=base.items,
        diagnostics=base.diagnostics,
        required_capacity_bytes=required_capacity_bytes,
        required_bytes=sum(atom.byte_count for atom in atoms),
        required_atoms=atoms,
    )
    receipt_atoms = tuple(
        RequiredAtomReceipt(
            path=atom.path,
            content_sha256=atom.content_sha256,
            revision=atom.revision,
            working_tree_state=atom.working_tree_state,
            byte_count=atom.byte_count,
            provenance=atom.provenance,
        )
        for atom in atoms
    )
    receipt = ContextReceipt(
        schema_version=CONTEXT_RECEIPT_SCHEMA_VERSION,
        packet_sha256=hashlib.sha256(packet.to_json().encode("utf-8")).hexdigest(),
        session_id=session_id,
        context_epoch=context_epoch,
        action=action,
        target=packet.target,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        visibility="expected",
        required_atoms=receipt_atoms,
    )
    return packet, receipt


def _load_relationships(repo_root: Path, config_path: str | Path) -> dict[str, Any]:
    """Load one repository relationship graph without legacy module coupling."""

    path = Path(config_path)
    if not path.is_absolute():
        path = repo_root / path
    if not path.exists():
        raise ContextPacketError(f"relationship config does not exist: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ContextPacketError(f"relationship config root must be a mapping: {path}")
    return loaded


def main(argv: list[str] | None = None) -> int:
    """Run the portable context-packet CLI for one edit target."""

    parser = argparse.ArgumentParser(description="Build bounded source-derived context for one tracked artifact")
    parser.add_argument("target", help="Repository-relative tracked path")
    parser.add_argument("--symbol", help="Qualified Python symbol within the target path")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", default="scripts/relationships.yaml")
    parser.add_argument("--max-items", type=int, default=20)
    parser.add_argument("--max-chars", type=int, default=8_000)
    parser.add_argument(
        "--required-capacity-bytes",
        type=int,
        help="Opt into V3 and reserve this separate capacity for complete required files.",
    )
    parser.add_argument("--receipt-path", type=Path, help="Write the V3 expected-context receipt here.")
    parser.add_argument("--session-id", help="Exact native session identity for a V3 receipt.")
    parser.add_argument("--context-epoch", help="Action epoch invalidated by compaction or context reset.")
    parser.add_argument("--action", help="Dependent action named by the V3 receipt.")
    parser.add_argument("--adapter-id", help="Context adapter producing the expected packet.")
    parser.add_argument("--adapter-version", help="Exact adapter contract or implementation version.")
    parser.add_argument(
        "--allow-untracked-target",
        action="store_true",
        help="Resolve path-level context for a new file that is not Git-tracked yet.",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    v3_values = {
        "required_capacity_bytes": args.required_capacity_bytes,
        "receipt_path": args.receipt_path,
        "session_id": args.session_id,
        "context_epoch": args.context_epoch,
        "action": args.action,
        "adapter_id": args.adapter_id,
        "adapter_version": args.adapter_version,
    }
    supplied_v3 = [name for name, value in v3_values.items() if value is not None]
    missing_v3 = [name for name, value in v3_values.items() if value is None]
    if supplied_v3 and missing_v3:
        parser.error(
            "V3 receipt mode requires all of: --required-capacity-bytes, --receipt-path, "
            "--session-id, --context-epoch, --action, --adapter-id, --adapter-version"
        )
    try:
        relationships = _load_relationships(args.repo_root, args.config)
        if supplied_v3:
            assert args.required_capacity_bytes is not None
            assert args.receipt_path is not None
            assert args.session_id is not None
            assert args.context_epoch is not None
            assert args.action is not None
            assert args.adapter_id is not None
            assert args.adapter_version is not None
            packet, receipt = build_context_packet_with_receipt(
                args.repo_root,
                args.target,
                relationships,
                target_symbol=args.symbol,
                max_items=args.max_items,
                max_chars=args.max_chars,
                required_capacity_bytes=args.required_capacity_bytes,
                session_id=args.session_id,
                context_epoch=args.context_epoch,
                action=args.action,
                adapter_id=args.adapter_id,
                adapter_version=args.adapter_version,
                allow_untracked_target=args.allow_untracked_target,
            )
            args.receipt_path.parent.mkdir(parents=True, exist_ok=True)
            args.receipt_path.write_text(receipt.to_json(pretty=args.pretty), encoding="utf-8")
        else:
            packet = build_context_packet(
                args.repo_root,
                args.target,
                relationships,
                target_symbol=args.symbol,
                max_items=args.max_items,
                max_chars=args.max_chars,
                allow_untracked_target=args.allow_untracked_target,
            )
    except (ContextPacketError, OSError) as exc:
        parser.exit(2, f"context-packet: {exc}\n")
    print(packet.to_json(pretty=args.pretty), end="")
    return 0


__all__ = [
    "ArchiveEffect",
    "ContextDiagnostic",
    "ContextItem",
    "ContextPacket",
    "ContextPacketError",
    "ContextPacketV3",
    "ContextReceipt",
    "RelationshipSpec",
    "RequiredAtomReceipt",
    "RequiredContextAtom",
    "build_context_packet",
    "build_context_packet_with_receipt",
    "expand_selectors",
    "main",
    "relationship_specs",
    "selector_path_matches",
]
