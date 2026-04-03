#!/usr/bin/env python3
"""Audit nested subtree instruction coverage and CLAUDE.md presence.

This validator enforces the subtree-instruction contract for any governed repo:

1. meaningful operational directories are classified explicitly,
2. included directories carry a local ``CLAUDE.md``,
3. excluded or unclassified directories do not silently drift into the system.

``AGENTS.md`` is a **root-level artifact only** — it is generated (not
symlinked) at the repo root by ``render_agents_md.py``.  Subdirectories
must NOT have ``AGENTS.md`` files (neither symlinks nor regular files).
The ``--sync-agents`` flag is retained for backward compatibility but is
now a no-op that emits a deprecation warning.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "scripts" / "subtree_instruction_registry.yaml"


@dataclass(frozen=True)
class RegistryEntry:
    """One included or excluded subtree declaration from the registry."""

    path: str
    reason: str


@dataclass(frozen=True)
class SubtreeRegistry:
    """Normalized subtree-instruction registry data."""

    classification_depth: int
    included: tuple[RegistryEntry, ...]
    excluded: tuple[RegistryEntry, ...]

    @property
    def included_paths(self) -> tuple[str, ...]:
        """Return all included directory paths in declaration order."""

        return tuple(entry.path for entry in self.included)

    @property
    def excluded_paths(self) -> tuple[str, ...]:
        """Return all excluded directory paths in declaration order."""

        return tuple(entry.path for entry in self.excluded)


@dataclass
class DirectoryAudit:
    """Audit details for one included subtree."""

    path: str
    claude_present: bool
    agents_present: bool
    agents_is_symlink: bool
    agents_target: str | None
    ok: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class SubtreeAuditResult:
    """JSON-serializable result for subtree instruction checks."""

    repo_root: str
    registry_path: str
    classification_depth: int
    included_paths: list[str]
    excluded_paths: list[str]
    actions: list[str] = field(default_factory=list)
    directories: list[DirectoryAudit] = field(default_factory=list)
    excluded_conflicts: list[str] = field(default_factory=list)
    unclassified_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return ``True`` when the audit found no hard failures."""

        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the audit result."""

        return {
            "repo_root": self.repo_root,
            "registry_path": self.registry_path,
            "classification_depth": self.classification_depth,
            "included_paths": self.included_paths,
            "excluded_paths": self.excluded_paths,
            "actions": self.actions,
            "directories": [asdict(directory) for directory in self.directories],
            "excluded_conflicts": self.excluded_conflicts,
            "unclassified_paths": self.unclassified_paths,
            "errors": self.errors,
            "warnings": self.warnings,
            "ok": self.ok,
        }


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for subtree instruction auditing."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repo root to audit.",
    )
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="Path to the subtree instruction registry YAML file.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument(
        "--sync-agents",
        action="store_true",
        help="[DEPRECATED] No-op. AGENTS.md is root-level only; subdirectory symlinks are no longer created.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Accepted for consistency with other checkers; check mode is the default.",
    )
    return parser.parse_args()


def _normalize_registry_path(raw_path: str) -> str:
    """Normalize a repo-relative registry path and reject unsafe forms."""

    normalized = PurePosixPath(raw_path).as_posix().strip()
    if not normalized or normalized == ".":
        raise ValueError("Registry paths must not be empty or '.'")
    if normalized.startswith("/"):
        raise ValueError(f"Registry paths must be repo-relative, found absolute path: {raw_path}")
    if normalized.startswith("../") or "/../" in normalized:
        raise ValueError(f"Registry paths must not escape the repo root: {raw_path}")
    return normalized


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from disk and fail loudly on invalid root types."""

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Registry root must be a mapping: {path}")
    return data


def _load_registry_entries(
    payload: dict[str, Any],
    key: str,
) -> tuple[RegistryEntry, ...]:
    """Load and validate a list of registry entries from a YAML mapping."""

    raw_entries = payload.get(key)
    if raw_entries is None:
        return ()
    if not isinstance(raw_entries, list):
        raise ValueError(f"Registry field {key!r} must be a list.")

    entries: list[RegistryEntry] = []
    seen_paths: set[str] = set()
    for item in raw_entries:
        if not isinstance(item, dict):
            raise ValueError(f"Registry field {key!r} must contain mappings.")
        raw_path = item.get("path")
        reason = item.get("reason")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"Registry field {key!r} entries must define a non-empty path.")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(
                f"Registry field {key!r} entry {raw_path!r} must define a non-empty reason."
            )
        path = _normalize_registry_path(raw_path)
        if path in seen_paths:
            raise ValueError(f"Duplicate registry entry in {key!r}: {path}")
        seen_paths.add(path)
        entries.append(RegistryEntry(path=path, reason=reason.strip()))
    return tuple(entries)


def load_registry(path: Path) -> SubtreeRegistry:
    """Load and validate the subtree instruction registry from disk."""

    payload = _load_yaml_mapping(path)
    version = payload.get("version")
    if version != 1:
        raise ValueError(f"Unsupported registry version {version!r}; expected 1.")

    classification_depth = payload.get("classification_depth", 3)
    if not isinstance(classification_depth, int) or classification_depth < 1:
        raise ValueError("classification_depth must be an integer >= 1.")

    included = _load_registry_entries(payload, "included")
    excluded = _load_registry_entries(payload, "excluded")

    overlap = {entry.path for entry in included} & {entry.path for entry in excluded}
    if overlap:
        raise ValueError(
            "Registry paths cannot be both included and excluded: "
            + ", ".join(sorted(overlap))
        )

    return SubtreeRegistry(
        classification_depth=classification_depth,
        included=included,
        excluded=excluded,
    )


def _relative_dir_paths(repo_root: Path, max_depth: int) -> list[str]:
    """Return repo-relative directory paths up to a fixed depth."""

    relpaths: list[str] = []
    for path in sorted(repo_root.rglob("*")):
        if not path.is_dir():
            continue
        relpath = path.relative_to(repo_root).as_posix()
        if relpath == ".":
            continue
        if relpath.count("/") + 1 > max_depth:
            continue
        relpaths.append(relpath)
    return relpaths


def _matches_excluded_path(relpath: str, pattern: str) -> bool:
    """Return whether a repo-relative path matches one excluded registry pattern."""

    if any(char in pattern for char in "*?[]"):
        return fnmatch.fnmatch(relpath, pattern)
    return relpath == pattern or relpath.startswith(f"{pattern}/")


def _classify_unclassified_paths(
    registry: SubtreeRegistry,
    relpaths: list[str],
) -> list[str]:
    """Return directories within audit depth that were not explicitly classified."""

    included_paths = set(registry.included_paths)
    excluded_paths = registry.excluded_paths

    unclassified: list[str] = []
    for relpath in relpaths:
        if relpath in included_paths:
            continue
        if any(_matches_excluded_path(relpath, pattern) for pattern in excluded_paths):
            continue
        unclassified.append(relpath)
    return unclassified


def _cleanup_subdirectory_agents(dir_path: Path, relpath: str) -> str | None:
    """Remove stale ``AGENTS.md`` symlinks from subdirectories.

    AGENTS.md is a root-level artifact only.  Subdirectories should never
    have one.  This function removes symlink-based AGENTS.md files that
    were created by older versions of this script.  Regular files are left
    alone with a warning (they may be hand-authored).
    """

    agents_path = dir_path / "AGENTS.md"

    if agents_path.is_symlink():
        agents_path.unlink()
        return f"removed-stale-symlink:{relpath}/AGENTS.md"

    if agents_path.exists():
        warnings.warn(
            f"{relpath}/AGENTS.md exists as a regular file in a subdirectory; "
            "AGENTS.md should only exist at the repo root. Remove it manually.",
            stacklevel=2,
        )
    return None


def _audit_included_directory(
    repo_root: Path,
    relpath: str,
    *,
    actions: list[str],
) -> DirectoryAudit:
    """Audit one included subtree directory and clean up stale AGENTS.md."""

    dir_path = repo_root / relpath
    errors: list[str] = []

    if not dir_path.is_dir():
        errors.append(f"{relpath}: registry includes a directory that does not exist")
        return DirectoryAudit(
            path=relpath,
            claude_present=False,
            agents_present=False,
            agents_is_symlink=False,
            agents_target=None,
            ok=False,
            errors=errors,
        )

    # Clean up stale AGENTS.md symlinks left by older versions of this script.
    # AGENTS.md is a root-level artifact only; subdirectories must not have one.
    action = _cleanup_subdirectory_agents(dir_path, relpath)
    if action is not None:
        actions.append(action)

    claude_path = dir_path / "CLAUDE.md"
    agents_path = dir_path / "AGENTS.md"
    claude_present = claude_path.exists()
    agents_present = agents_path.exists() or agents_path.is_symlink()
    agents_is_symlink = agents_path.is_symlink()
    agents_target = os.readlink(agents_path) if agents_path.is_symlink() else None

    if not claude_present:
        errors.append(f"{relpath}: missing CLAUDE.md")
    # AGENTS.md in subdirectories is no longer required or expected.
    # If one exists as a regular file, warn but don't fail.
    if agents_present:
        errors.append(
            f"{relpath}: AGENTS.md should not exist in subdirectories "
            "(root-level artifact only); remove it"
        )

    return DirectoryAudit(
        path=relpath,
        claude_present=claude_present,
        agents_present=agents_present,
        agents_is_symlink=agents_is_symlink,
        agents_target=agents_target,
        ok=not errors,
        errors=errors,
    )


def audit_subtree_instructions(
    repo_root: Path,
    registry_path: Path,
    *,
    sync_agents: bool = False,
) -> SubtreeAuditResult:
    """Audit subtree instruction coverage for one repo root.

    The ``sync_agents`` parameter is accepted for backward compatibility
    but is now a no-op (with deprecation warning).  AGENTS.md is a
    root-level artifact only; subdirectories should not have one.
    """

    if sync_agents:
        warnings.warn(
            "--sync-agents is deprecated and now a no-op. "
            "AGENTS.md is a root-level artifact only; subdirectory "
            "AGENTS.md symlinks are no longer created. Existing stale "
            "symlinks will be cleaned up automatically during audit.",
            DeprecationWarning,
            stacklevel=2,
        )

    registry = load_registry(registry_path)
    result = SubtreeAuditResult(
        repo_root=str(repo_root),
        registry_path=str(registry_path),
        classification_depth=registry.classification_depth,
        included_paths=list(registry.included_paths),
        excluded_paths=list(registry.excluded_paths),
    )

    relpaths = _relative_dir_paths(repo_root, registry.classification_depth)
    result.unclassified_paths = _classify_unclassified_paths(registry, relpaths)
    for relpath in result.unclassified_paths:
        result.errors.append(f"Unclassified directory within audit depth: {relpath}")

    for entry in registry.excluded:
        if any(char in entry.path for char in "*?[]"):
            continue
        directory_path = repo_root / entry.path
        if not directory_path.is_dir():
            continue
        # Only check for CLAUDE.md in excluded dirs; AGENTS.md is root-only.
        if (directory_path / "CLAUDE.md").exists():
            conflict = f"{entry.path}: excluded directory should not contain CLAUDE.md"
            result.excluded_conflicts.append(conflict)
            result.errors.append(conflict)

    for entry in registry.included:
        directory_audit = _audit_included_directory(
            repo_root,
            entry.path,
            actions=result.actions,
        )
        result.directories.append(directory_audit)
        result.errors.extend(directory_audit.errors)

    return result


def main() -> int:
    """Run the subtree instruction audit and emit human or JSON output."""

    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    registry_path = Path(args.registry).resolve()

    try:
        result = audit_subtree_instructions(
            repo_root,
            registry_path,
            sync_agents=args.sync_agents,
        )
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "repo_root": str(repo_root),
                        "registry_path": str(registry_path),
                        "ok": False,
                        "errors": [str(exc)],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(str(exc))
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        if result.ok:
            print(
                f"Subtree instructions OK for {repo_root} using {registry_path}."
            )
        else:
            print(
                f"Subtree instruction issues found for {repo_root} using {registry_path}."
            )
        for action in result.actions:
            print(f"ACTION {action}")
        for error in result.errors:
            print(f"ERROR {error}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
