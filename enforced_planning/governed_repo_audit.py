#!/usr/bin/env python3
"""Audit mechanical governed-repo contract signals and legacy AGENTS projections.

This tool is the first executable rollout slice for Plan 09. It does not try
to invent missing repo-specific governance. Instead, it checks whether the
mechanical pieces of the governed-repo contract are present and, for legacy
repositories with ``CLAUDE.md``, deterministically refresh ``AGENTS.md``.

The audit is intentionally conservative:

- it reports missing or drifting contract pieces
- it does not silently author ``CLAUDE.md`` or ``relationships.yaml``
- it does not claim semantic OpenClaw-readiness
- it fails loudly when an explicit refresh request cannot be satisfied
"""

from __future__ import annotations

from enforced_planning.installed_framework import declares_installed_framework

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
if str(FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_ROOT))

from enforced_planning.agents_rendering import build_renderer  # noqa: E402
from enforced_planning.effective_project_profile import load_effective_project_profile
from enforced_planning.worktree_paths import resolve_canonical_repo_root  # noqa: E402

_FRAMEWORK_RENDERER = build_renderer(FRAMEWORK_ROOT / "scripts" / "render_agents_md.py")
DEFAULT_SHARED_CAPABILITY_REGISTRY = (
    FRAMEWORK_ROOT / "scripts" / "capability_ownership_registry.yaml"
)

VALIDATOR_CANDIDATES: dict[str, tuple[str, ...]] = {
    "file_context": ("scripts/meta/file_context.py",),
    "validate_plan": ("scripts/meta/validate_plan.py", "scripts/validate_plan.py"),
    "check_doc_coupling": (
        "scripts/meta/check_doc_coupling.py",
        "scripts/check_doc_coupling.py",
    ),
    "sync_plan_status": (
        "scripts/meta/sync_plan_status.py",
        "scripts/sync_plan_status.py",
    ),
    "check_markdown_links": ("scripts/check_markdown_links.py",),
}


def _load_repo_render_module(repo_root: Path) -> tuple[Any, Any]:
    """Return the truthful render helpers for one repo layout.

    Governed repos install the renderer at ``scripts/meta/render_agents_md.py``.
    The framework repo keeps the canonical renderer at ``scripts/render_agents_md.py``.
    When the repo has an installed local renderer, use it so generated provenance
    markers match the repo-local maintenance surface.
    """

    candidates = (
        repo_root / "scripts" / "meta" / "render_agents_md.py",
        repo_root / "scripts" / "render_agents_md.py",
    )
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            module_name = "_repo_render_agents_md"
            spec = importlib.util.spec_from_file_location(module_name, candidate)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            finally:
                sys.modules.pop(module_name, None)
            return module.resolve_inputs, module.render_agents_markdown
        except (AttributeError, ImportError, OSError, SyntaxError):
            # A canonical framework audit must still diagnose a stale installed
            # renderer. The installer plan reports the exact managed-file drift.
            continue
    return _FRAMEWORK_RENDERER.resolve_inputs, _FRAMEWORK_RENDERER.render_agents_markdown


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for governed-repo auditing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repo root to audit.",
    )
    parser.add_argument(
        "--claude-file",
        default="CLAUDE.md",
        help="Repo-relative path to legacy canonical CLAUDE.md, when present.",
    )
    parser.add_argument(
        "--relationships-file",
        default="scripts/relationships.yaml",
        help="Repo-relative path to canonical relationships.yaml.",
    )
    parser.add_argument(
        "--agents-file",
        default="AGENTS.md",
        help="Repo-relative path to AGENTS.md.",
    )
    parser.add_argument(
        "--plans-dir",
        default="docs/plans",
        help="Repo-relative path to the plans directory.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument(
        "--refresh-agents",
        action="store_true",
        help="Deterministically refresh AGENTS.md from canonical inputs when available.",
    )
    parser.add_argument(
        "--strict-governed",
        action="store_true",
        help="Exit non-zero when the repo does not satisfy the mechanical governed-repo contract.",
    )
    parser.add_argument(
        "--strict-linkage",
        action="store_true",
        help="Require relationships.yaml to include actionable linkages beyond bootstrap defaults.",
    )
    parser.add_argument(
        "--shared-capability-registry",
        help=(
            "Optional path to advisory shared capability ownership data. "
            "When omitted, the audit runs without shared-registry advice unless "
            "a local framework default exists."
        ),
    )
    return parser.parse_args()


HOOK_FILES: tuple[str, ...] = (
    ".claude/hooks/gate-edit.sh",
    ".claude/hooks/track-reads.sh",
    ".claude/hooks/check-hook-enabled.sh",
)

HOOK_COMMANDS: tuple[str, ...] = (
    "bash .claude/hooks/gate-edit.sh",
    "bash .claude/hooks/track-reads.sh",
)

PREWRITE_HOOK_FILES: tuple[str, ...] = (
    ".claude/hooks/prewrite-claim-gate.sh",
    ".codex/hooks/prewrite-claim-gate.sh",
    "scripts/prewrite_claim_gate.py",
    "scripts/refresh_prewrite_claim_projection.py",
    "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/prewrite_claim_projection.py",
)

PREWRITE_HOOK_COMMANDS: tuple[str, ...] = (
    "bash .claude/hooks/prewrite-claim-gate.sh",
    'bash "$(git rev-parse --show-toplevel)/.codex/hooks/prewrite-claim-gate.sh"',
)


def _prewrite_mode(config: dict[str, Any] | None) -> str:
    if not isinstance(config, dict):
        return "off"
    meta_process = config.get("meta_process")
    if not isinstance(meta_process, dict):
        return "off"
    claims = meta_process.get("claims")
    if not isinstance(claims, dict):
        return "off"
    mode = claims.get("prewrite_mode", "off")
    return str(mode) if mode in {"off", "observe", "enforce"} else "invalid"


def _audit_prewrite_claim_gate(repo_root: Path, config: dict[str, Any] | None) -> dict[str, Any]:
    """Audit opt-in adapter files and commands without promoting off mode."""

    mode = _prewrite_mode(config)
    expected = mode in {"observe", "enforce"}
    installs_framework = declares_installed_framework(repo_root)
    files_missing = [
        path
        for path in PREWRITE_HOOK_FILES
        if not _resolve_repo_surface_path(repo_root, path)[0].is_file()
        and not (installs_framework and path.startswith("enforced_planning/"))
    ]
    installed_commands: set[str] = set()
    for relpath in (".claude/settings.json", ".codex/hooks.json"):
        settings_path, _used_fallback = _resolve_repo_surface_path(repo_root, relpath)
        if settings_path.is_file():
            try:
                settings: object = json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            pending = [settings]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    command = value.get("command")
                    if isinstance(command, str):
                        installed_commands.add(command)
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
    commands_missing = [
        command for command in PREWRITE_HOOK_COMMANDS if command not in installed_commands
    ]
    return {
        "mode": mode,
        "expected": expected,
        "present": not files_missing and not commands_missing if expected else True,
        "files_missing": files_missing if expected else [],
        "commands_missing": commands_missing if expected else [],
    }

WORKTREE_TARGETS: tuple[str, ...] = (
    "worktree",
    "worktree-list",
    "worktree-remove",
    "session-start",
    "session-heartbeat",
    "session-status",
    "session-finish",
    "session-end",
    "session-close",
)

WORKTREE_SCRIPT_PATHS: dict[str, tuple[str, ...]] = {
    "create_worktree": ("scripts/meta/worktree-coordination/create_worktree.py",),
    "check_coordination_claims": (
        "scripts/meta/check_coordination_claims.py",
        "scripts/meta/worktree-coordination/check_claims.py",
    ),
    "session_start": ("scripts/meta/session_start.py",),
    "session_heartbeat": ("scripts/meta/session_heartbeat.py",),
    "session_status": ("scripts/meta/session_status.py",),
    "session_finish": ("scripts/meta/session_finish.py",),
    "session_close": ("scripts/meta/session_close.py",),
    "safe_worktree_remove": ("scripts/meta/worktree-coordination/safe_worktree_remove.py",),
}


def _check_paths(repo_root: Path, relpaths: tuple[str, ...]) -> dict[str, Any]:
    """Return presence information for one or more repo-relative candidate paths."""
    present = [relpath for relpath in relpaths if (repo_root / relpath).exists()]
    return {
        "present": bool(present),
        "candidates": list(relpaths),
        "resolved": present,
    }


def _resolve_repo_surface_path(repo_root: Path, relpath: str) -> tuple[Path, bool]:
    """Resolve one repo-mechanical surface from a worktree or canonical root."""
    repo_root = repo_root.resolve()
    local_path = repo_root / relpath
    if local_path.exists():
        return local_path, False

    canonical_repo_root = resolve_canonical_repo_root(repo_root)
    if canonical_repo_root == repo_root:
        return local_path, False

    canonical_path = canonical_repo_root / relpath
    if canonical_path.exists():
        return canonical_path, True
    return local_path, False


def _audit_read_gating(repo_root: Path) -> dict[str, Any]:
    """Check that read-gating hooks and settings.json wiring are present.

    Per GOVERNED_REPO_CONTRACT.md section 6, read-gating hooks are a Level 1
    requirement. This checks:
    - .claude/hooks/gate-edit.sh exists
    - .claude/hooks/track-reads.sh exists
    - .claude/settings.json exists and contains entries for both hooks
    """
    hook_source_paths: dict[str, str] = {}
    present_files: list[str] = []
    missing_files: list[str] = []
    canonical_fallback_used = False
    for relpath in HOOK_FILES:
        resolved_path, used_fallback = _resolve_repo_surface_path(repo_root, relpath)
        if resolved_path.exists():
            present_files.append(relpath)
            hook_source_paths[relpath] = str(resolved_path)
            canonical_fallback_used = canonical_fallback_used or used_fallback
        else:
            missing_files.append(relpath)

    settings_path, settings_used_fallback = _resolve_repo_surface_path(
        repo_root,
        ".claude/settings.json",
    )
    canonical_fallback_used = canonical_fallback_used or settings_used_fallback
    settings_present = settings_path.exists()
    missing_commands: list[str] = []

    if settings_present:
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            # Collect all hook commands across all event blocks
            all_commands: set[str] = set()
            hooks = settings.get("hooks", {})
            if isinstance(hooks, dict):
                for _event, blocks in hooks.items():
                    if isinstance(blocks, list):
                        for block in blocks:
                            if isinstance(block, dict):
                                for hook in block.get("hooks", []):
                                    if isinstance(hook, dict):
                                        cmd = hook.get("command", "")
                                        if cmd:
                                            all_commands.add(cmd)
            missing_commands = [c for c in HOOK_COMMANDS if c not in all_commands]
        except (json.JSONDecodeError, ValueError):
            missing_commands = list(HOOK_COMMANDS)

    wired = settings_present and not missing_files and not missing_commands
    return {
        "present": wired,
        "canonical_fallback_used": canonical_fallback_used,
        "hook_source_paths": hook_source_paths,
        "settings_source_path": str(settings_path) if settings_present else None,
        "settings_present": settings_present,
        "hook_files_present": present_files,
        "hook_files_missing": missing_files,
        "commands_wired": [c for c in HOOK_COMMANDS if c not in missing_commands],
        "commands_missing": missing_commands,
    }


def _audit_agents(
    repo_root: Path,
    *,
    claude_file: str,
    relationships_file: str,
    agents_file: str,
) -> dict[str, Any]:
    """Return AGENTS.md presence, drift, and refreshability information."""
    output_path = repo_root / agents_file
    result: dict[str, Any] = {
        "present": output_path.exists(),
        "path": agents_file,
        "refreshable": False,
        "in_sync": None,
        "error": None,
    }

    claude_path = repo_root / claude_file
    if not claude_path.exists():
        if output_path.is_symlink() or not output_path.is_file():
            result["error"] = f"Authored AGENTS file is missing: {output_path}"
            result["in_sync"] = False
            return result
        if "<!-- GENERATED FILE: DO NOT EDIT DIRECTLY -->" in output_path.read_text(encoding="utf-8"):
            result["error"] = f"AGENTS file still declares itself generated without a source: {output_path}"
            result["in_sync"] = False
            return result
        result["in_sync"] = True
        return result

    resolve_inputs, render_agents_markdown = _load_repo_render_module(repo_root)
    try:
        expected = render_agents_markdown(
            resolve_inputs(
                repo_root=repo_root,
                claude_file=claude_file,
                relationships_file=relationships_file,
                output_file=agents_file,
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        result["error"] = str(exc)
        result["in_sync"] = False
        return result
    result["refreshable"] = True
    if not output_path.exists():
        result["in_sync"] = False
        return result

    actual = output_path.read_text(encoding="utf-8")
    result["in_sync"] = actual == expected
    return result


def _load_capability_registry_entries(
    shared_registry_path: Path | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return advisory shared capability-registry entries when available."""
    if shared_registry_path is None:
        return [], None
    if not shared_registry_path.exists():
        return [], f"shared capability registry not found: {shared_registry_path}"
    try:
        raw = yaml.safe_load(shared_registry_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return [], f"shared capability registry could not be parsed: {shared_registry_path}"
    if not isinstance(raw, dict):
        return [], f"shared capability registry must be a YAML mapping: {shared_registry_path}"
    entries = raw.get("entries") or []
    if not isinstance(entries, list):
        return [], f"shared capability registry entries must be a list: {shared_registry_path}"
    return [entry for entry in entries if isinstance(entry, dict)], None


def _load_meta_process_config(repo_root: Path) -> tuple[Path, dict[str, Any] | None, str | None]:
    """Load repo-local meta-process config when present.

    Returns the config path, parsed mapping, and an optional parse error.
    """
    repo_root = repo_root.resolve()
    config_path = repo_root / "meta-process.yaml"
    if not config_path.exists():
        canonical_repo_root = resolve_canonical_repo_root(repo_root)
        if canonical_repo_root != repo_root:
            fallback_path = canonical_repo_root / "meta-process.yaml"
            if fallback_path.exists():
                config_path = fallback_path
    if not config_path.exists():
        return config_path, None, None
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return config_path, None, str(exc)
    if not isinstance(raw, dict):
        return config_path, None, "meta-process.yaml must be a YAML mapping"
    return config_path, raw, None


def _normalize_registry_source_of_record(
    raw_path: str,
    *,
    source_project: str,
) -> str:
    """Normalize registry source paths to repo-relative form when possible."""
    path_text = raw_path.strip()
    if not path_text:
        return ""
    candidate = Path(path_text).expanduser()
    projects_root = Path.home() / "projects" / source_project
    try:
        return str(candidate.resolve().relative_to(projects_root.resolve()))
    except ValueError:
        return path_text


def _audit_capability_ownership(
    repo_root: Path,
    *,
    shared_capability_registry: Path | None,
) -> dict[str, Any]:
    """Audit advisory capability-ownership configuration for one repo.

    This check is intentionally advisory-only in the first rollout slice.
    It warns when repos already referenced by the shared registry do not declare
    a repo-local capability-ownership source of record, and when a declaration
    exists but is incomplete or inconsistent with the shared registry.
    """
    repo_name = repo_root.name
    registry_entries, registry_error = _load_capability_registry_entries(
        shared_capability_registry
    )
    config_path, config, config_error = _load_meta_process_config(repo_root)
    registry_entries_for_repo = [
        entry
        for entry in registry_entries
        if str(entry.get("source_project", "")).strip() == repo_name
    ]

    result: dict[str, Any] = {
        "config_present": config is not None,
        "config_path": "meta-process.yaml",
        "declared": False,
        "enabled": None,
        "source_of_record": None,
        "source_exists": None,
        "shared_registry_required": None,
        "source_project": None,
        "shared_registry_match_count": len(registry_entries_for_repo),
        "multi_capability_monorepo": len(registry_entries_for_repo) > 1,
        "shared_registry_matches": [
            str(entry.get("capability_id", "")).strip()
            for entry in registry_entries_for_repo
            if str(entry.get("capability_id", "")).strip()
        ],
        "warnings": [],
        "error": config_error or registry_error,
        "shared_registry_path": (
            str(shared_capability_registry) if shared_capability_registry else None
        ),
    }

    if config_error:
        result["warnings"].append(
            "meta-process.yaml exists but could not be parsed for capability ownership"
        )
        return result

    if registry_error:
        result["warnings"].append(registry_error)

    if config is None:
        if registry_entries_for_repo:
            result["warnings"].append(
                "Repo appears in project-meta capability registry but has no meta-process.yaml capability_ownership declaration"
            )
        return result

    meta_process = config.get("meta_process")
    if not isinstance(meta_process, dict):
        if registry_entries_for_repo:
            result["warnings"].append(
                "meta-process.yaml is missing a meta_process mapping required for capability ownership declaration"
            )
        return result

    declaration = meta_process.get("capability_ownership")
    if not isinstance(declaration, dict):
        if registry_entries_for_repo:
            result["warnings"].append(
                "Repo appears in project-meta capability registry but meta_process.capability_ownership is missing"
            )
        return result

    enabled = bool(declaration.get("enabled", False))
    source_of_record_raw = declaration.get("source_of_record", "")
    source_of_record = str(source_of_record_raw).strip() if source_of_record_raw else ""
    shared_registry_required = bool(
        declaration.get("shared_registry_required", False)
    )
    source_project_raw = declaration.get("source_project", "")
    source_project = str(source_project_raw).strip() if source_project_raw else repo_name
    source_exists = (repo_root / source_of_record).exists() if source_of_record else False
    shared_registry_matches = [
        entry
        for entry in registry_entries
        if str(entry.get("source_project", "")).strip() == source_project
    ]

    result.update(
        {
            "declared": True,
            "enabled": enabled,
            "source_of_record": source_of_record or None,
            "source_exists": source_exists if source_of_record else None,
            "shared_registry_required": shared_registry_required,
            "source_project": source_project,
            "shared_registry_match_count": len(shared_registry_matches),
            "multi_capability_monorepo": len(shared_registry_matches) > 1,
            "shared_registry_matches": [
                str(entry.get("capability_id", "")).strip()
                for entry in shared_registry_matches
                if str(entry.get("capability_id", "")).strip()
            ],
        }
    )

    if registry_entries_for_repo and not enabled:
        result["warnings"].append(
            "Repo appears in project-meta capability registry but capability_ownership is not enabled locally"
        )
    if enabled and not source_of_record:
        result["warnings"].append(
            "capability_ownership is enabled but source_of_record is empty"
        )
    if enabled and source_of_record and not source_exists:
        result["warnings"].append(
            "capability_ownership source_of_record does not exist in the repo"
        )
    if shared_registry_required and not shared_registry_matches:
        result["warnings"].append(
            "capability_ownership requires shared registry coverage but no matching source_project entry exists in project-meta"
        )
    shared_row_source_paths = {
        _normalize_registry_source_of_record(
            str(entry.get("source_of_record", "")).strip(),
            source_project=source_project,
        )
        for entry in shared_registry_matches
        if str(entry.get("source_of_record", "")).strip()
    }
    if (
        enabled
        and source_of_record
        and len(shared_registry_matches) > 1
        and source_of_record in shared_row_source_paths
    ):
        result["warnings"].append(
            "Multiple shared capability rows exist for this source_project; repo-local capability_ownership.source_of_record should point at a monorepo umbrella ownership memo rather than a single capability detail doc"
        )

    return result


def _audit_worktree_entrypoints(repo_root: Path) -> dict[str, Any]:
    """Audit sanctioned repo-local worktree entrypoints when coordination is enabled."""
    config_path, config, config_error = _load_meta_process_config(repo_root)
    result: dict[str, Any] = {
        "config_present": config is not None,
        "config_path": "meta-process.yaml",
        "expected": False,
        "claims_enabled": None,
        "claims_require_for_worktree": None,
        "worktrees_enabled": None,
        "makefile_present": False,
        "makefile_path": "Makefile",
        "meta_block_present": False,
        "targets_present": {target: False for target in WORKTREE_TARGETS},
        "scripts_present": {
            key: _check_paths(repo_root, candidates)["present"]
            for key, candidates in WORKTREE_SCRIPT_PATHS.items()
        },
        "script_candidates": {
            key: list(candidates) for key, candidates in WORKTREE_SCRIPT_PATHS.items()
        },
        "warnings": [],
        "error": config_error,
    }

    if config_error:
        result["warnings"].append(
            "meta-process.yaml exists but could not be parsed for worktree entrypoint audit"
        )
        return result

    meta_process = config.get("meta_process") if isinstance(config, dict) else None
    if isinstance(meta_process, dict):
        claims = meta_process.get("claims")
        worktrees = meta_process.get("worktrees")
        claims_enabled = False
        claims_require_for_worktree = False
        worktrees_enabled = False
        if isinstance(claims, dict):
            claims_enabled = bool(claims.get("enabled", False))
            claims_require_for_worktree = bool(
                claims.get("require_for_worktree", False)
            )
        if isinstance(worktrees, dict):
            worktrees_enabled = bool(worktrees.get("enabled", False))
        result["claims_enabled"] = claims_enabled
        result["claims_require_for_worktree"] = claims_require_for_worktree
        result["worktrees_enabled"] = worktrees_enabled
        result["expected"] = claims_require_for_worktree or worktrees_enabled
        if worktrees_enabled and not claims_enabled:
            result["warnings"].append(
                "worktrees.enabled is true but claims.enabled is not true; sanctioned worktree opt-in expects both"
            )

    makefile_path = repo_root / "Makefile"
    if not makefile_path.exists():
        if result["expected"]:
            result["warnings"].append(
                "worktree coordination is enabled but Makefile does not expose sanctioned worktree entrypoints"
            )
        return result

    makefile_text = makefile_path.read_text(encoding="utf-8")
    result["makefile_present"] = True
    result["meta_block_present"] = "# === META-PROCESS TARGETS ===" in makefile_text
    result["targets_present"] = {
        target: bool(re.search(rf"(?m)^{re.escape(target)}\s*:", makefile_text))
        for target in WORKTREE_TARGETS
    }

    if result["expected"]:
        missing_targets = [
            target
            for target, present in result["targets_present"].items()
            if not present
        ]
        if missing_targets:
            result["warnings"].append(
                "sanctioned worktree entrypoints missing from Makefile: "
                + ", ".join(missing_targets)
            )
        missing_scripts = [
            key
            for key, present in result["scripts_present"].items()
            if not present
        ]
        if missing_scripts:
            result["warnings"].append(
                "worktree coordination scripts missing for sanctioned entrypoints: "
                + ", ".join(missing_scripts)
            )

    return result


def _analyze_relationships_linkage(
    repo_root: Path,
    relationships_file: str,
) -> dict[str, Any]:
    """Return a lightweight linkage quality assessment from relationships.yaml."""
    path = repo_root / relationships_file
    if not path.exists():
        return {
            "status": "missing",
            "governance_rules": 0,
            "coupling_rules": 0,
            "architecture_rules": 0,
            "required_reading_defaults": [],
            "actionable_rules": 0,
            "error": "relationships file not found",
        }

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {
            "status": "invalid",
            "governance_rules": 0,
            "coupling_rules": 0,
            "architecture_rules": 0,
            "required_reading_defaults": [],
            "actionable_rules": 0,
            "error": str(exc),
        }

    if not isinstance(raw, dict):
        return {
            "status": "invalid",
            "governance_rules": 0,
            "coupling_rules": 0,
            "architecture_rules": 0,
            "required_reading_defaults": [],
            "actionable_rules": 0,
            "error": "relationships YAML must be a mapping",
        }

    governance_rules = len(raw.get("governance") or [])
    coupling_rules = len(raw.get("couplings") or [])
    architecture_rules = len(raw.get("architecture") or [])
    required_reading = raw.get("required_reading") or {}
    defaults = required_reading.get("defaults") if isinstance(required_reading, dict) else []

    if defaults is None:
        defaults = []
    defaults = [str(item) for item in defaults if str(item).strip()]

    actionable_rules = governance_rules + coupling_rules + architecture_rules
    status = (
        "actionable"
        if actionable_rules > 0
        else "minimal"
    )

    return {
        "status": status,
        "governance_rules": governance_rules,
        "coupling_rules": coupling_rules,
        "architecture_rules": architecture_rules,
        "required_reading_defaults": defaults,
        "actionable_rules": actionable_rules,
    }


def _refresh_agents(
    repo_root: Path,
    *,
    claude_file: str,
    relationships_file: str,
    agents_file: str,
) -> str:
    """Render legacy AGENTS.md, preserving an authored AGENTS-only source."""
    if not (repo_root / claude_file).is_file():
        state = _audit_agents(
            repo_root,
            claude_file=claude_file,
            relationships_file=relationships_file,
            agents_file=agents_file,
        )
        if state["in_sync"] is True and state["refreshable"] is False:
            return f"preserved:{agents_file}"
        raise ValueError(state["error"] or f"Cannot refresh {agents_file} without {claude_file}")
    resolve_inputs, render_agents_markdown = _load_repo_render_module(repo_root)
    inputs = resolve_inputs(
        repo_root=repo_root,
        claude_file=claude_file,
        relationships_file=relationships_file,
        output_file=agents_file,
    )
    rendered = render_agents_markdown(inputs)
    inputs.output_path.write_text(rendered, encoding="utf-8")
    return f"rendered:{agents_file}"


def audit_repo(
    repo_root: Path,
    *,
    claude_file: str,
    relationships_file: str,
    agents_file: str,
    plans_dir: str,
    require_linkage: bool = False,
    shared_capability_registry: Path | None = None,
) -> dict[str, Any]:
    """Audit a repo against the mechanical governed-repo contract surface."""
    plans_path = repo_root / plans_dir
    instruction_source = claude_file if (repo_root / claude_file).is_file() else agents_file
    plan_instruction = "CLAUDE.md" if instruction_source == claude_file else "AGENTS.md"
    plan_index = plans_path / plan_instruction
    config_path, config, config_error = _load_meta_process_config(repo_root)
    relationships_state = _analyze_relationships_linkage(
        repo_root, relationships_file=relationships_file
    )
    try:
        effective_profile: dict[str, Any] = load_effective_project_profile(repo_root).model_dump(mode="json")
    except ValueError as exc:
        effective_profile = {"schema_version": "1.0.0", "error": str(exc)}
    checks: dict[str, Any] = {
        "claude_md": {
            "present": (repo_root / claude_file).exists(),
            "path": claude_file,
        },
        "instruction_source": {
            "present": (repo_root / instruction_source).is_file(),
            "path": instruction_source,
        },
        "meta_process_yaml": {
            "present": config_path.exists(),
            "path": "meta-process.yaml",
            "parse_error": config_error,
            "valid": config_path.exists() and config_error is None,
            "configured": config is not None,
        },
        "relationships_yaml": {
            "present": (repo_root / relationships_file).exists(),
            "path": relationships_file,
            "linkage": relationships_state,
        },
        "plans_dir": {
            "present": plans_path.is_dir(),
            "path": plans_dir,
        },
        "plans_index": {
            "present": plan_index.exists(),
            "path": f"{plans_dir}/{plan_instruction}",
        },
        "agents_md": _audit_agents(
            repo_root,
            claude_file=claude_file,
            relationships_file=relationships_file,
            agents_file=agents_file,
        ),
        "capability_ownership": _audit_capability_ownership(
            repo_root,
            shared_capability_registry=shared_capability_registry,
        ),
        "worktree_entrypoints": _audit_worktree_entrypoints(repo_root),
    }
    validators = {
        name: _check_paths(repo_root, candidates)
        for name, candidates in VALIDATOR_CANDIDATES.items()
    }
    read_gating = _audit_read_gating(repo_root)
    checks["read_gating"] = read_gating
    prewrite_gate = _audit_prewrite_claim_gate(repo_root, config)
    checks["prewrite_claim_gate"] = prewrite_gate

    optional = {
        "hooks_dir": {
            "present": (repo_root / "hooks").is_dir(),
            "path": "hooks/",
        },
        "acceptance_gates": {
            "present": (repo_root / "acceptance_gates").is_dir(),
            "path": "acceptance_gates/",
        },
    }

    missing_required: list[str] = []
    if not checks["instruction_source"]["present"]:
        missing_required.append("canonical CLAUDE.md or authored AGENTS.md")
    meta_process = checks["meta_process_yaml"]
    if not meta_process["present"]:
        missing_required.append("meta-process.yaml")
    elif not meta_process["valid"]:
        missing_required.append("meta-process.yaml valid parseable mapping")
    if not checks["relationships_yaml"]["present"]:
        missing_required.append("scripts/relationships.yaml")
    elif relationships_state["status"] == "invalid":
        missing_required.append("relationships.yaml valid parseable mapping")
    elif relationships_state["status"] == "minimal" and require_linkage:
        missing_required.append("relationships.yaml has no actionable governance/coupling/architecture entries")
    if not checks["plans_dir"]["present"]:
        missing_required.append("docs/plans/")
    if not checks["plans_index"]["present"]:
        missing_required.append(checks["plans_index"]["path"])

    agents = checks["agents_md"]
    if not agents["present"]:
        missing_required.append("AGENTS.md")
    elif agents["in_sync"] is not True:
        missing_required.append("in-sync AGENTS.md")

    for validator_name, validator_state in validators.items():
        if not validator_state["present"]:
            missing_required.append(f"validator:{validator_name}")

    if not read_gating["present"]:
        for f in read_gating["hook_files_missing"]:
            missing_required.append(f"hook:{f}")
        if not read_gating["settings_present"]:
            missing_required.append("hook:.claude/settings.json")
        for c in read_gating["commands_missing"]:
            missing_required.append(f"hook-wiring:{c}")

    if prewrite_gate["mode"] == "invalid":
        missing_required.append("meta-process.yaml claims.prewrite_mode valid enum")
    elif prewrite_gate["expected"] and not prewrite_gate["present"]:
        for path in prewrite_gate["files_missing"]:
            missing_required.append(f"prewrite-hook:{path}")
        for command in prewrite_gate["commands_missing"]:
            missing_required.append(f"prewrite-hook-wiring:{command}")

    worktree_entrypoints = checks["worktree_entrypoints"]
    if worktree_entrypoints["expected"]:
        if worktree_entrypoints["claims_enabled"] is False:
            missing_required.append("meta-process.yaml claims.enabled for worktree opt-in")
        if not all(worktree_entrypoints["targets_present"].values()):
            missing_required.append("sanctioned Makefile worktree entrypoints")
        if not all(worktree_entrypoints["scripts_present"].values()):
            missing_required.append("sanctioned worktree coordination scripts")

    master_disabled = effective_profile.get("master_enabled") is False
    suppressed_missing_required = list(missing_required) if master_disabled else []
    if master_disabled:
        missing_required = []
        classification = "disabled"
    else:
        classification = "governed" if not missing_required else "partial"
    if relationships_state["status"] == "minimal":
        checks["relationships_yaml"]["warnings"] = [
            "relationships.yaml currently defines only bootstrap defaults",
            "edit-gating still works, but coupling/linkage enforcement is shallow",
        ]

    status = "PASS" if classification in {"governed", "disabled"} else "FAIL"

    return {
        "scope": "mechanical-governed-repo-audit",
        "repo_root": str(repo_root),
        "status": status,
        "classification": classification,
        "effective_project_profile": effective_profile,
        "suppressed_missing_required": suppressed_missing_required,
        "checks": checks,
        "validators": validators,
        "optional_signals": optional,
        "missing_required": missing_required,
        "limitations": [
            "This audit checks mechanical governed-repo signals only.",
            "It does not prove repo-local success criteria or full OpenClaw-readiness.",
            "It does not author missing repo-specific governance files.",
        ],
    }


def _print_human(report: dict[str, Any]) -> None:
    """Print a short human-readable audit summary."""
    print(f"Repo: {report['repo_root']}")
    print(f"Mechanical governed-repo status: {report['status']}")
    print(f"Classification: {report['classification']}")
    missing = report["missing_required"]
    if not missing:
        print("All required mechanical governed-repo signals are present.")
        return
    print("Missing or drifting required signals:")
    for item in missing:
        print(f"- {item}")


def main() -> int:
    """Audit one repo and optionally refresh its generated AGENTS.md file."""
    args = parse_args()
    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.exists():
        print(f"Repo root not found: {repo_root}", file=sys.stderr)
        return 2

    shared_capability_registry: Path | None = None
    if args.shared_capability_registry:
        shared_capability_registry = (
            Path(args.shared_capability_registry).expanduser().resolve()
        )
    elif DEFAULT_SHARED_CAPABILITY_REGISTRY.exists():
        shared_capability_registry = DEFAULT_SHARED_CAPABILITY_REGISTRY

    actions: list[str] = []
    if args.refresh_agents:
        try:
            action = _refresh_agents(
                repo_root,
                claude_file=args.claude_file,
                relationships_file=args.relationships_file,
                agents_file=args.agents_file,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        actions.append(action)

    report = audit_repo(
        repo_root,
        claude_file=args.claude_file,
        relationships_file=args.relationships_file,
        agents_file=args.agents_file,
        plans_dir=args.plans_dir,
        require_linkage=args.strict_linkage,
        shared_capability_registry=shared_capability_registry,
    )
    if actions:
        report["actions"] = actions

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
        for action in actions:
            print(f"Action: {action}")

    if args.strict_governed and report["classification"] != "governed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
