#!/usr/bin/env python3
"""Generate and sync Claude read-gating hook wiring into a governed repo.

This generator is the first repeatable rollout tool for Plan 08. It does not
invent repo-specific governance, but it does install the small generic support
artifacts required for read-gating to work:

- `.claude/hooks/gate-edit.sh`
- `.claude/hooks/track-reads.sh`
- `scripts/check_required_reading.py`
- `scripts/meta/hook_log.py`
- `scripts/meta/context_packet.py` and its static inventory support
- `.claude/settings.json` hook entries for `Read` and `Edit|Write`

The target repo must already expose a machine-readable relationships graph and
`scripts/meta/file_context.py`; without those, the gate would be present but
non-functional.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from enforced_planning.installed_framework import drop_vendored_package_files

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]

# Hook shell scripts sourced from the extracted enforced-planning framework.
HOOK_FILES: dict[str, str] = {
    ".claude/hooks/gate-edit.sh": "hooks/claude/gate-edit.sh",
    ".claude/hooks/track-reads.sh": "hooks/claude/track-reads.sh",
    # Required by worktree-coordination hooks (block-cd-worktree, warn-worktree-cwd).
    # Install unconditionally so repos that later add worktree hooks don't break.
    ".claude/hooks/check-hook-enabled.sh": "hooks/claude/check-hook-enabled.sh",
}

PREWRITE_HOOK_FILES: dict[str, str] = {
    ".claude/hooks/prewrite-claim-gate.sh": "hooks/claude/prewrite-claim-gate.sh",
    ".codex/hooks/prewrite-claim-gate.sh": "hooks/codex/prewrite-claim-gate.sh",
}

ARTIFACT_CREATION_HOOK_FILES: dict[str, str] = {
    ".claude/hooks/artifact-creation-gate.sh": "hooks/claude/artifact-creation-gate.sh",
    ".codex/hooks/artifact-creation-gate.sh": "hooks/codex/artifact-creation-gate.sh",
}

MAILBOX_HOOK_FILES: dict[str, str] = {
    ".claude/hooks/notify-coordination-messages.sh": "hooks/claude/notify-coordination-messages.sh",
    ".codex/hooks/notify-coordination-messages.sh": "hooks/codex/notify-coordination-messages.sh",
}

# Canonical-checkout lock. The hook itself only explains a denial and repairs a
# stale lock at session start; the enforcement is the checkout's permission
# bits, so a repo that has not installed this is still protected by any other
# repo's session start -- reconcile is estate-wide, not repo-local.
CANONICAL_LOCK_HOOK_FILES: dict[str, str] = {
    ".claude/hooks/reconcile-canonical-locks.sh": (
        "hooks/claude/worktree-coordination/reconcile-canonical-locks.sh"
    ),
}

MERGE_GUARD_HOOK_FILES: dict[str, str] = {
    ".claude/hooks/worktree-coordination/check-hook-enabled.sh": (
        "hooks/claude/check-hook-enabled.sh"
    ),
    ".claude/hooks/worktree-coordination/enforce-make-merge.sh": (
        "hooks/claude/worktree-coordination/enforce-make-merge.sh"
    ),
    ".codex/hooks/enforce-make-merge.sh": (
        "hooks/claude/worktree-coordination/enforce-make-merge.sh"
    ),
}

CANONICAL_LOCK_SUPPORT_FILES: dict[str, str] = {
    "scripts/meta/canonical_lock.py": "scripts/worktree-coordination/canonical_lock.py",
}

# Support Python scripts sourced from this canonical framework.
SUPPORT_FILES: dict[str, str] = {
    "scripts/check_required_reading.py": "scripts/check_required_reading.py",
    "scripts/meta/hook_log.py": "scripts/hook_log.py",
    "scripts/meta/context_packet.py": "scripts/context_packet.py",
    "enforced_planning/context_packet.py": "enforced_planning/context_packet.py",
    "enforced_planning/relationship_context.py": "enforced_planning/relationship_context.py",
}

PREWRITE_SUPPORT_FILES: dict[str, str] = {
    "scripts/prewrite_claim_gate.py": "scripts/prewrite_claim_gate.py",
    "scripts/refresh_prewrite_claim_projection.py": "scripts/refresh_prewrite_claim_projection.py",
    # A directory of modules without __init__.py is only a namespace-package
    # candidate.  An older regular package in site-packages then wins import
    # resolution and silently supplies stale enforcement code to the installed
    # hook.  Install the package marker so the consumer-local runtime owns the
    # import boundary.
    "enforced_planning/__init__.py": "enforced_planning/__init__.py",
    "enforced_planning/claim_bootstrap.py": "enforced_planning/claim_bootstrap.py",
    "enforced_planning/prewrite_claim_fast.py": "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/prewrite_claim_projection.py": "enforced_planning/prewrite_claim_projection.py",
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
    "enforced_planning/coordination_messages.py": "enforced_planning/coordination_messages.py",
    "enforced_planning/claim_mutation_receipts.py": "enforced_planning/claim_mutation_receipts.py",
    "enforced_planning/doc_authority.py": "enforced_planning/doc_authority.py",
    "enforced_planning/file_context.py": "enforced_planning/file_context.py",
    "enforced_planning/notebook_registry_validation.py": "enforced_planning/notebook_registry_validation.py",
    "enforced_planning/outcome_admission.py": "enforced_planning/outcome_admission.py",
    "enforced_planning/outcome_continuation.py": "enforced_planning/outcome_continuation.py",
    "enforced_planning/outcome_portfolio.py": "enforced_planning/outcome_portfolio.py",
    "enforced_planning/outcome_prewrite_observation.py": "enforced_planning/outcome_prewrite_observation.py",
    "enforced_planning/outcome_selection.py": "enforced_planning/outcome_selection.py",
    "enforced_planning/plan_validation.py": "enforced_planning/plan_validation.py",
    "enforced_planning/push_safety.py": "enforced_planning/push_safety.py",
    "enforced_planning/read_target.py": "enforced_planning/read_target.py",
    "enforced_planning/repository_authority.py": "enforced_planning/repository_authority.py",
    "enforced_planning/session_contracts.py": "enforced_planning/session_contracts.py",
    "enforced_planning/session_lifecycle.py": "enforced_planning/session_lifecycle.py",
    "enforced_planning/session_target.py": "enforced_planning/session_target.py",
    "enforced_planning/surface_runtime.py": "enforced_planning/surface_runtime.py",
    "enforced_planning/worktree_lifecycle.yaml": "enforced_planning/worktree_lifecycle.yaml",
    "enforced_planning/worktree_paths.py": "enforced_planning/worktree_paths.py",
}

ARTIFACT_CREATION_SUPPORT_FILES: dict[str, str] = {
    "scripts/artifact_creation.py": "scripts/artifact_creation.py",
    "enforced_planning/artifact_creation.py": "enforced_planning/artifact_creation.py",
    "enforced_planning/prewrite_claim_fast.py": "enforced_planning/prewrite_claim_fast.py",
}

MAILBOX_SUPPORT_FILES: dict[str, str] = {
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
    "enforced_planning/coordination_messages.py": "enforced_planning/coordination_messages.py",
    "enforced_planning/prewrite_claim_fast.py": "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/prewrite_claim_projection.py": "enforced_planning/prewrite_claim_projection.py",
    "scripts/refresh_prewrite_claim_projection.py": "scripts/refresh_prewrite_claim_projection.py",
    "scripts/coordination_inbox.py": "scripts/coordination_inbox.py",
    "scripts/coordination_hook.py": "scripts/coordination_hook.py",
    "scripts/meta/coordination_inbox.py": "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_hook.py": "scripts/meta/coordination_hook.py",
}

READ_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/track-reads.sh",
    "timeout": 1000,
}

MAILBOX_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/notify-coordination-messages.sh",
    "timeout": 3000,
}

# Session start is the stale-lock repair; the tool events supply the escape
# hatch when a lock blocks something. UserPromptSubmit and Stop carry no path
# information, so wiring them would only add cost.
CANONICAL_LOCK_EVENTS = frozenset({"SessionStart", "PreToolUse", "PostToolUse"})

CANONICAL_LOCK_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/reconcile-canonical-locks.sh",
    "timeout": 10000,
}

MERGE_GUARD_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/worktree-coordination/enforce-make-merge.sh",
    "timeout": 3000,
}

CODEX_MAILBOX_HOOK = {
    "type": "command",
    "command": (
        'bash "$(git rev-parse --show-toplevel)/.codex/hooks/'
        'notify-coordination-messages.sh"'
    ),
    "timeout": 3,
    "statusMessage": "Checking coordination requests",
}

CODEX_MERGE_GUARD_HOOK = {
    "type": "command",
    "command": (
        'bash "$(git rev-parse --show-toplevel)/.codex/hooks/'
        'enforce-make-merge.sh"'
    ),
    "timeout": 3,
    "statusMessage": "Checking sanctioned merge path",
}

GATE_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/gate-edit.sh",
    "timeout": 5000,
}

PREWRITE_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/prewrite-claim-gate.sh",
    "timeout": 1,
}

CODEX_PREWRITE_HOOK = {
    "type": "command",
    "command": (
        'bash "$(git rev-parse --show-toplevel)/.codex/hooks/'
        'prewrite-claim-gate.sh"'
    ),
    "timeout": 1,
    "statusMessage": "Checking write ownership",
}

ARTIFACT_CREATION_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/artifact-creation-gate.sh",
    "timeout": 5,
}

CODEX_ARTIFACT_CREATION_HOOK = {
    "type": "command",
    "command": (
        'bash "$(git rev-parse --show-toplevel)/.codex/hooks/'
        'artifact-creation-gate.sh"'
    ),
    "timeout": 5,
    "statusMessage": "Checking new artifact policy",
}


@dataclass(frozen=True)
class TargetRepo:
    """Resolved target repo plus the minimal prerequisites for wiring."""

    root: Path
    relationships_file: Path
    file_context_file: Path
    settings_file: Path


def context_runtime_error(repo_root: Path, *, require_pydantic: bool = True) -> str | None:
    """Return a fail-loud prerequisite error for the hook's actual Python runtime.

    Installed context tools parse ``relationships.yaml`` with PyYAML. Tests run
    under the framework interpreter can mask a target virtualenv that lacks the
    dependency, so probe the same interpreter selected by ``gate-edit.sh``.
    """

    venv_python = repo_root / ".venv" / "bin" / "python"
    interpreter = (
        str(venv_python)
        if venv_python.is_file() and os.access(venv_python, os.X_OK)
        else shutil.which("python3")
    )
    if interpreter is None:
        return "relationship context requires python3 or a repo-local .venv/bin/python"
    try:
        imports = "import yaml, pydantic" if require_pydantic else "import yaml"
        result = subprocess.run(
            [interpreter, "-c", imports],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return f"relationship context runtime {interpreter} cannot execute: {exc}"
    if result.returncode:
        dependencies = "PyYAML and Pydantic" if require_pydantic else "PyYAML"
        requirement = "PyYAML>=6.0 and Pydantic>=2.0" if require_pydantic else "PyYAML>=6.0"
        return (
            f"governance hook runtime {interpreter} cannot import {dependencies}; "
            f"declare/install {requirement} before hook rollout"
        )
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for hook-wiring generation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repo root to update.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply the generated wiring instead of printing the planned actions.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument(
        "--profile",
        choices=("full", "artifact-creation", "prewrite-claim"),
        default="full",
        help=(
            "Install the complete read/coordination wiring or only the "
            "artifact-creation or pre-write-claim gate and their support files."
        ),
    )
    return parser.parse_args(argv)


def _resolve_target(repo_root_arg: str) -> TargetRepo:
    """Resolve the target repo and fail loudly if required inputs are missing."""

    repo_root = Path(repo_root_arg).expanduser().resolve()
    if not repo_root.exists():
        raise FileNotFoundError(f"Repo root not found: {repo_root}")

    relationships_file = repo_root / "scripts" / "relationships.yaml"
    if not relationships_file.exists():
        raise FileNotFoundError(
            f"Missing machine-readable governance file: {relationships_file}"
        )

    file_context_file = repo_root / "scripts" / "meta" / "file_context.py"
    if not file_context_file.exists():
        raise FileNotFoundError(
            f"Missing file-context resolver required for read-gating: {file_context_file}"
        )

    runtime_error = context_runtime_error(repo_root)
    if runtime_error:
        raise FileNotFoundError(runtime_error)

    settings_file = repo_root / ".claude" / "settings.json"
    return TargetRepo(
        root=repo_root,
        relationships_file=relationships_file,
        file_context_file=file_context_file,
        settings_file=settings_file,
    )


def _resolve_artifact_target(repo_root_arg: str) -> TargetRepo:
    """Resolve only the prerequisites needed by the artifact-creation profile."""

    repo_root = Path(repo_root_arg).expanduser().resolve()
    if not repo_root.exists():
        raise FileNotFoundError(f"Repo root not found: {repo_root}")

    relationships_file = repo_root / "scripts" / "relationships.yaml"
    if not relationships_file.exists():
        raise FileNotFoundError(
            f"Missing machine-readable governance file: {relationships_file}"
        )

    runtime_error = context_runtime_error(repo_root)
    if runtime_error:
        raise FileNotFoundError(runtime_error)

    return TargetRepo(
        root=repo_root,
        relationships_file=relationships_file,
        # This profile does not use read-gating, but retaining a concrete path
        # keeps the shared target contract simple and makes absence explicit.
        file_context_file=repo_root / "scripts" / "meta" / "file_context.py",
        settings_file=repo_root / ".claude" / "settings.json",
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk or return an empty object when absent."""

    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _ensure_event_block(settings: dict[str, Any], event_name: str) -> list[dict[str, Any]]:
    """Return the mutable hook blocks for one hook event, creating them if absent."""

    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings.json field `hooks` must be an object")
    blocks = hooks.setdefault(event_name, [])
    if not isinstance(blocks, list):
        raise ValueError(f"settings.json hooks.{event_name} must be a list")
    return blocks


def _ensure_matcher_block(
    settings: dict[str, Any],
    *,
    event_name: str,
    matcher: str,
) -> list[dict[str, Any]]:
    """Return the hook list for one event+matcher block, creating it if absent."""

    blocks = _ensure_event_block(settings, event_name)
    for block in blocks:
        if isinstance(block, dict) and block.get("matcher") == matcher:
            hooks = block.setdefault("hooks", [])
            if not isinstance(hooks, list):
                raise ValueError(f"settings.json hooks.{event_name} matcher {matcher} has non-list hooks")
            return hooks

    new_block: dict[str, Any] = {"matcher": matcher, "hooks": []}
    blocks.append(new_block)
    new_hooks = new_block["hooks"]
    if not isinstance(new_hooks, list):
        raise ValueError(f"settings.json hooks.{event_name} matcher {matcher} has non-list hooks")
    return new_hooks


def _ensure_hook_command(
    hooks: list[dict[str, Any]],
    desired_hook: dict[str, Any],
    *,
    after_command: str | None = None,
) -> bool:
    """Ensure one hook command exists in a matcher block without duplication."""

    command = desired_hook["command"]
    for existing in hooks:
        if isinstance(existing, dict) and existing.get("command") == command:
            if existing != desired_hook:
                existing.clear()
                existing.update(desired_hook)
                return True
            return False

    if after_command is not None:
        for index, existing in enumerate(hooks):
            if isinstance(existing, dict) and existing.get("command") == after_command:
                hooks.insert(index + 1, dict(desired_hook))
                return True

    hooks.append(dict(desired_hook))
    return True


def _remove_hook_command_from_matcher(
    settings: dict[str, Any],
    *,
    event_name: str,
    matcher: str,
    command: str,
) -> bool:
    """Remove only one generator-owned command from an existing matcher block."""

    changed = False
    for block in _ensure_event_block(settings, event_name):
        if not isinstance(block, dict) or block.get("matcher") != matcher:
            continue
        hooks = block.get("hooks", [])
        if not isinstance(hooks, list):
            raise ValueError(
                f"settings.json hooks.{event_name} matcher {matcher} has non-list hooks"
            )
        retained = [
            hook
            for hook in hooks
            if not (isinstance(hook, dict) and hook.get("command") == command)
        ]
        if len(retained) != len(hooks):
            hooks[:] = retained
            changed = True
    return changed


def _render_settings(settings: dict[str, Any]) -> str:
    """Render deterministic pretty JSON for `.claude/settings.json`."""

    return json.dumps(settings, indent=2, sort_keys=False) + "\n"


def _configured_prewrite_mode(repo_root: Path) -> str:
    """Return the explicit portable mode without enabling absent configuration."""

    path = repo_root / "meta-process.yaml"
    if not path.is_file():
        return "off"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("meta-process.yaml must be a mapping")
    meta_process = payload.get("meta_process", payload)
    if not isinstance(meta_process, dict):
        raise ValueError("meta-process.yaml meta_process must be a mapping")
    claims = meta_process.get("claims", {}) or {}
    if not isinstance(claims, dict):
        raise ValueError("meta-process.yaml claims must be a mapping")
    mode = claims.get("prewrite_mode", "off")
    if mode not in {"off", "observe", "enforce"}:
        raise ValueError("claims.prewrite_mode must be off, observe, or enforce")
    return str(mode)


def _configured_artifact_creation_mode(repo_root: Path) -> str:
    """Return the explicit artifact-creation mode without enabling it implicitly."""

    path = repo_root / "meta-process.yaml"
    if not path.is_file():
        return "off"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("meta-process.yaml must be a mapping")
    meta_process = payload.get("meta_process", payload)
    if not isinstance(meta_process, dict):
        raise ValueError("meta-process.yaml meta_process must be a mapping")
    settings = meta_process.get("artifact_creation", {}) or {}
    if not isinstance(settings, dict):
        raise ValueError("meta-process.yaml artifact_creation must be a mapping")
    mode = settings.get("mode", "off")
    if mode not in {"off", "observe", "enforce"}:
        raise ValueError("artifact_creation.mode must be off, observe, or enforce")
    return str(mode)


def _merge_codex_mailbox_hooks(
    settings: dict[str, Any],
    *,
    include_prewrite: bool = False,
    include_artifact_creation: bool = False,
    include_merge_guard: bool = True,
) -> bool:
    """Install mailbox polling on supported Codex lifecycle boundaries."""

    changed = False
    for event_name, matcher in (
        ("SessionStart", "startup|resume|clear|compact"),
        ("UserPromptSubmit", ""),
        ("PostToolUse", "*"),
        ("PreToolUse", "Bash|apply_patch"),
        ("Stop", ""),
    ):
        hooks = _ensure_matcher_block(settings, event_name=event_name, matcher=matcher)
        if _ensure_hook_command(hooks, CODEX_MAILBOX_HOOK):
            changed = True
    if include_merge_guard:
        merge_hooks = _ensure_matcher_block(
            settings,
            event_name="PreToolUse",
            matcher="Bash",
        )
        if _ensure_hook_command(merge_hooks, CODEX_MERGE_GUARD_HOOK):
            changed = True
    if include_prewrite:
        prewrite_command = cast(str, CODEX_PREWRITE_HOOK["command"])
        for legacy_matcher in ("Edit|Write", "apply_patch"):
            if _remove_hook_command_from_matcher(
                settings,
                event_name="PreToolUse",
                matcher=legacy_matcher,
                command=prewrite_command,
            ):
                changed = True
        hooks = _ensure_matcher_block(
            settings,
            event_name="PreToolUse",
            matcher="Bash|apply_patch",
        )
        if _ensure_hook_command(hooks, CODEX_PREWRITE_HOOK):
            changed = True
    if include_artifact_creation:
        hooks = _ensure_matcher_block(settings, event_name="PreToolUse", matcher="Edit|Write")
        if _ensure_hook_command(
            hooks,
            CODEX_ARTIFACT_CREATION_HOOK,
            after_command=(cast(str, CODEX_PREWRITE_HOOK["command"]) if include_prewrite else None),
        ):
            changed = True
    return changed


def _plan_codex_settings(
    target: TargetRepo, *, include_merge_guard: bool = True
) -> tuple[list[str], dict[Path, str]]:
    """Plan a preserving merge into the target's native Codex hooks file."""

    path = target.root / ".codex" / "hooks.json"
    settings = _read_json_file(path)
    changed = _merge_codex_mailbox_hooks(
        settings,
        include_prewrite=_configured_prewrite_mode(target.root) != "off",
        include_artifact_creation=_configured_artifact_creation_mode(target.root) != "off",
        include_merge_guard=include_merge_guard,
    )
    rendered = _render_settings(settings)
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current != rendered or changed:
        return ["sync:.codex/hooks.json"], {path: rendered}
    return [], {}


def plan_merge_guard_generation(
    target: TargetRepo,
) -> tuple[list[str], dict[Path, str], str]:
    """Plan only the fast sanctioned-merge guard for bounded worktree rollout."""
    actions: list[str] = []
    writes: dict[Path, str] = {}
    for target_relpath, source_relpath in MERGE_GUARD_HOOK_FILES.items():
        target_path = target.root / target_relpath
        content = (FRAMEWORK_ROOT / source_relpath).read_text(encoding="utf-8")
        current = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if current != content:
            actions.append(f"sync:{target_relpath}")
            writes[target_path] = content

    claude = _read_json_file(target.settings_file)
    claude_hooks = _ensure_matcher_block(
        claude, event_name="PreToolUse", matcher="Bash"
    )
    _ensure_hook_command(claude_hooks, MERGE_GUARD_HOOK)
    rendered_claude = _render_settings(claude)
    if not target.settings_file.exists() or target.settings_file.read_text(
        encoding="utf-8"
    ) != rendered_claude:
        actions.append("sync:.claude/settings.json")
        writes[target.settings_file] = rendered_claude

    codex_path = target.root / ".codex" / "hooks.json"
    codex = _read_json_file(codex_path)
    codex_hooks = _ensure_matcher_block(
        codex, event_name="PreToolUse", matcher="Bash"
    )
    _ensure_hook_command(codex_hooks, CODEX_MERGE_GUARD_HOOK)
    rendered_codex = _render_settings(codex)
    if not codex_path.exists() or codex_path.read_text(encoding="utf-8") != rendered_codex:
        actions.append("sync:.codex/hooks.json")
        writes[codex_path] = rendered_codex
    return actions, writes, rendered_claude


def _plan_codex_artifact_creation_settings(
    target: TargetRepo,
) -> tuple[list[str], dict[Path, str]]:
    """Plan only the Codex artifact-creation hook without unrelated wiring."""

    path = target.root / ".codex" / "hooks.json"
    settings = _read_json_file(path)
    hooks = _ensure_matcher_block(
        settings,
        event_name="PreToolUse",
        matcher="Edit|Write",
    )
    changed = _ensure_hook_command(hooks, CODEX_ARTIFACT_CREATION_HOOK)
    rendered = _render_settings(settings)
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current != rendered or changed:
        return ["sync:.codex/hooks.json"], {path: rendered}
    return [], {}


def _plan_codex_prewrite_settings(target: TargetRepo) -> tuple[list[str], dict[Path, str]]:
    """Plan only Codex's native shell and apply-patch pre-write gate."""

    path = target.root / ".codex" / "hooks.json"
    settings = _read_json_file(path)
    changed = False
    prewrite_command = cast(str, CODEX_PREWRITE_HOOK["command"])
    for legacy_matcher in ("Edit|Write", "apply_patch"):
        if _remove_hook_command_from_matcher(
            settings,
            event_name="PreToolUse",
            matcher=legacy_matcher,
            command=prewrite_command,
        ):
            changed = True
    hooks = _ensure_matcher_block(settings, event_name="PreToolUse", matcher="Bash|apply_patch")
    if _ensure_hook_command(hooks, CODEX_PREWRITE_HOOK):
        changed = True
    rendered = _render_settings(settings)
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current != rendered or changed:
        return ["sync:.codex/hooks.json"], {path: rendered}
    return [], {}


def _relative(path: Path, repo_root: Path) -> str:
    """Return a repo-relative POSIX display path."""

    return path.relative_to(repo_root).as_posix()


def plan_generation(
    target: TargetRepo,
    *,
    include_coordination_messages: bool = True,
) -> tuple[list[str], dict[Path, str], str]:
    """Compute file writes and settings content for the target repo."""

    actions: list[str] = []
    file_writes: dict[Path, str] = {}

    prewrite_enabled = _configured_prewrite_mode(target.root) != "off"
    artifact_creation_enabled = _configured_artifact_creation_mode(target.root) != "off"
    source_files = {**HOOK_FILES, **SUPPORT_FILES}
    if prewrite_enabled:
        source_files.update(PREWRITE_HOOK_FILES)
        source_files.update(PREWRITE_SUPPORT_FILES)
    if artifact_creation_enabled:
        source_files.update(ARTIFACT_CREATION_HOOK_FILES)
        source_files.update(ARTIFACT_CREATION_SUPPORT_FILES)
    if include_coordination_messages:
        source_files.update(MERGE_GUARD_HOOK_FILES)
        source_files.update(MAILBOX_HOOK_FILES)
        source_files.update(CANONICAL_LOCK_HOOK_FILES)
        source_files.update(CANONICAL_LOCK_SUPPORT_FILES)
        source_files.update(MAILBOX_SUPPORT_FILES)
    source_files = drop_vendored_package_files(source_files, target.root)
    for target_relpath, source_relpath in source_files.items():
        source_path = FRAMEWORK_ROOT / source_relpath
        target_path = target.root / target_relpath
        content = source_path.read_text(encoding="utf-8")
        current = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if current != content:
            actions.append(f"sync:{target_relpath}")
            file_writes[target_path] = content

    # If worktree-coordination hooks are present, ensure check-hook-enabled.sh is
    # also present there — those hooks source it from their own $SCRIPT_DIR.
    wt_hooks_dir = target.root / ".claude" / "hooks" / "worktree-coordination"
    if wt_hooks_dir.exists():
        wt_enabled = wt_hooks_dir / "check-hook-enabled.sh"
        source_enabled = FRAMEWORK_ROOT / "hooks" / "claude" / "check-hook-enabled.sh"
        content = source_enabled.read_text(encoding="utf-8")
        current = wt_enabled.read_text(encoding="utf-8") if wt_enabled.exists() else None
        if current != content:
            rel = ".claude/hooks/worktree-coordination/check-hook-enabled.sh"
            actions.append(f"sync:{rel}")
            file_writes[wt_enabled] = content

    settings = _read_json_file(target.settings_file)
    read_hooks = _ensure_matcher_block(settings, event_name="PostToolUse", matcher="Read")
    edit_hooks = _ensure_matcher_block(settings, event_name="PreToolUse", matcher="Edit|Write")

    changed = False
    if _ensure_hook_command(read_hooks, READ_HOOK):
        changed = True
    if include_coordination_messages:
        for event_name, matcher in (
            ("SessionStart", "startup|resume|clear|compact"),
            ("UserPromptSubmit", ""),
            ("PostToolUse", "*"),
            ("PreToolUse", "Bash|Edit|Write"),
            ("Stop", ""),
        ):
            mailbox_hooks = _ensure_matcher_block(
                settings,
                event_name=event_name,
                matcher=matcher,
            )
            if _ensure_hook_command(mailbox_hooks, MAILBOX_HOOK):
                changed = True
            if event_name in CANONICAL_LOCK_EVENTS and _ensure_hook_command(
                mailbox_hooks, CANONICAL_LOCK_HOOK
            ):
                changed = True
    if _ensure_hook_command(
        edit_hooks,
        GATE_HOOK,
        after_command="bash .claude/hooks/protect-main.sh",
    ):
        changed = True
    if include_coordination_messages:
        merge_hooks = _ensure_matcher_block(
            settings,
            event_name="PreToolUse",
            matcher="Bash",
        )
        if _ensure_hook_command(merge_hooks, MERGE_GUARD_HOOK):
            changed = True
    if prewrite_enabled and _ensure_hook_command(
        edit_hooks,
        PREWRITE_HOOK,
        after_command="bash .claude/hooks/gate-edit.sh",
    ):
        changed = True
    if artifact_creation_enabled and _ensure_hook_command(
        edit_hooks,
        ARTIFACT_CREATION_HOOK,
        after_command=(
            cast(str, PREWRITE_HOOK["command"] if prewrite_enabled else GATE_HOOK["command"])
        ),
    ):
        changed = True

    rendered_settings = _render_settings(settings)
    current_settings = (
        target.settings_file.read_text(encoding="utf-8")
        if target.settings_file.exists()
        else None
    )
    if current_settings != rendered_settings or changed:
        actions.append("sync:.claude/settings.json")
        file_writes[target.settings_file] = rendered_settings

    if include_coordination_messages:
        codex_actions, codex_writes = _plan_codex_settings(target)
        actions.extend(codex_actions)
        file_writes.update(codex_writes)

    return actions, file_writes, rendered_settings


def plan_coordination_message_generation(
    target: TargetRepo,
) -> tuple[list[str], dict[Path, str], str]:
    """Plan only the mailbox hook, adapters, and one settings entry.

    Fleet rollout uses this bounded profile so adopting coordination messages
    cannot silently refresh unrelated read-gating or relationship-context files.
    """

    actions: list[str] = []
    file_writes: dict[Path, str] = {}
    for target_relpath, source_relpath in {
        **MAILBOX_HOOK_FILES,
        **CANONICAL_LOCK_HOOK_FILES,
        **CANONICAL_LOCK_SUPPORT_FILES,
    }.items():
        source_path = FRAMEWORK_ROOT / source_relpath
        target_path = target.root / target_relpath
        content = source_path.read_text(encoding="utf-8")
        current = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if current != content:
            actions.append(f"sync:{target_relpath}")
            file_writes[target_path] = content

    settings = _read_json_file(target.settings_file)
    changed = False
    for event_name, matcher in (
        ("SessionStart", "startup|resume|clear|compact"),
        ("UserPromptSubmit", ""),
        ("PostToolUse", "*"),
        ("PreToolUse", "Bash|Edit|Write"),
        ("Stop", ""),
    ):
        hooks = _ensure_matcher_block(settings, event_name=event_name, matcher=matcher)
        if _ensure_hook_command(hooks, MAILBOX_HOOK):
            changed = True
        if event_name in CANONICAL_LOCK_EVENTS and _ensure_hook_command(hooks, CANONICAL_LOCK_HOOK):
            changed = True
    rendered_settings = _render_settings(settings)
    current_settings = (
        target.settings_file.read_text(encoding="utf-8")
        if target.settings_file.exists()
        else None
    )
    if current_settings != rendered_settings or changed:
        actions.append("sync:.claude/settings.json")
        file_writes[target.settings_file] = rendered_settings
    codex_actions, codex_writes = _plan_codex_settings(
        target, include_merge_guard=False
    )
    actions.extend(codex_actions)
    file_writes.update(codex_writes)
    return actions, file_writes, rendered_settings


def plan_artifact_creation_generation(
    target: TargetRepo,
) -> tuple[list[str], dict[Path, str], str]:
    """Plan the standalone artifact-creation gate and no unrelated hooks."""

    if _configured_artifact_creation_mode(target.root) == "off":
        raise ValueError(
            "artifact-creation profile requires meta_process.artifact_creation.mode "
            "to be observe or enforce"
        )

    actions: list[str] = []
    file_writes: dict[Path, str] = {}
    source_files = {
        **ARTIFACT_CREATION_HOOK_FILES,
        **ARTIFACT_CREATION_SUPPORT_FILES,
    }
    for target_relpath, source_relpath in source_files.items():
        source_path = FRAMEWORK_ROOT / source_relpath
        target_path = target.root / target_relpath
        content = source_path.read_text(encoding="utf-8")
        current = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if current != content:
            actions.append(f"sync:{target_relpath}")
            file_writes[target_path] = content

    settings = _read_json_file(target.settings_file)
    edit_hooks = _ensure_matcher_block(
        settings,
        event_name="PreToolUse",
        matcher="Edit|Write",
    )
    changed = _ensure_hook_command(edit_hooks, ARTIFACT_CREATION_HOOK)
    rendered_settings = _render_settings(settings)
    current_settings = (
        target.settings_file.read_text(encoding="utf-8")
        if target.settings_file.exists()
        else None
    )
    if current_settings != rendered_settings or changed:
        actions.append("sync:.claude/settings.json")
        file_writes[target.settings_file] = rendered_settings

    codex_actions, codex_writes = _plan_codex_artifact_creation_settings(target)
    actions.extend(codex_actions)
    file_writes.update(codex_writes)
    return actions, file_writes, rendered_settings


def plan_prewrite_claim_generation(
    target: TargetRepo,
) -> tuple[list[str], dict[Path, str], str]:
    """Plan the standalone native pre-write claim gate and no unrelated hooks."""

    if _configured_prewrite_mode(target.root) == "off":
        raise ValueError(
            "prewrite-claim profile requires meta_process.claims.prewrite_mode "
            "to be observe or enforce"
        )

    actions: list[str] = []
    file_writes: dict[Path, str] = {}
    for target_relpath, source_relpath in {**PREWRITE_HOOK_FILES, **PREWRITE_SUPPORT_FILES}.items():
        source_path = FRAMEWORK_ROOT / source_relpath
        target_path = target.root / target_relpath
        content = source_path.read_text(encoding="utf-8")
        current = target_path.read_text(encoding="utf-8") if target_path.exists() else None
        if current != content:
            actions.append(f"sync:{target_relpath}")
            file_writes[target_path] = content

    settings = _read_json_file(target.settings_file)
    edit_hooks = _ensure_matcher_block(settings, event_name="PreToolUse", matcher="Edit|Write")
    changed = _ensure_hook_command(edit_hooks, PREWRITE_HOOK)
    rendered_settings = _render_settings(settings)
    current_settings = target.settings_file.read_text(encoding="utf-8") if target.settings_file.exists() else None
    if current_settings != rendered_settings or changed:
        actions.append("sync:.claude/settings.json")
        file_writes[target.settings_file] = rendered_settings

    codex_actions, codex_writes = _plan_codex_prewrite_settings(target)
    actions.extend(codex_actions)
    file_writes.update(codex_writes)
    return actions, file_writes, rendered_settings


def apply_generation(target: TargetRepo, file_writes: dict[Path, str]) -> None:
    """Write the generated files to disk."""

    for path, content in file_writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if path.suffix == ".sh":
            path.chmod(0o755)


def validate_hooks(target: TargetRepo) -> list[str]:
    """Syntax-check every installed .sh hook with bash -n. Returns error strings."""

    import subprocess

    errors: list[str] = []
    for hooks_dir in (target.root / ".claude" / "hooks", target.root / ".codex" / "hooks"):
        if not hooks_dir.exists():
            continue
        for sh_file in sorted(hooks_dir.rglob("*.sh")):
            result = subprocess.run(
                ["bash", "-n", str(sh_file)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                rel = _relative(sh_file, target.root)
                errors.append(f"syntax error in {rel}: {result.stderr.strip()}")
    return errors


def main(argv: list[str] | None = None) -> int:
    """Entry point for dry-run or applied hook-wiring generation."""

    args = parse_args(argv)
    try:
        if args.profile == "artifact-creation":
            target = _resolve_artifact_target(args.repo_root)
            actions, file_writes, _ = plan_artifact_creation_generation(target)
        elif args.profile == "prewrite-claim":
            target = _resolve_artifact_target(args.repo_root)
            actions, file_writes, _ = plan_prewrite_claim_generation(target)
        else:
            target = _resolve_target(args.repo_root)
            actions, file_writes, _ = plan_generation(target)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    validation_errors: list[str] = []
    if args.write:
        apply_generation(target, file_writes)
        validation_errors = validate_hooks(target)

    payload = {
        "repo_root": str(target.root),
        "status": "FAIL" if validation_errors else "PASS",
        "write_mode": args.write,
        "actions": actions,
        "changed_files": [
            _relative(path, target.root)
            for path in sorted(file_writes.keys())
        ],
        "profile": args.profile,
        "required_inputs": (
            [_relative(target.relationships_file, target.root)]
            if args.profile in {"artifact-creation", "prewrite-claim"}
            else [
                _relative(target.relationships_file, target.root),
                _relative(target.file_context_file, target.root),
            ]
        ),
        "validation_errors": validation_errors,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Repo: {target.root}")
        if actions:
            print("Planned actions:")
            for action in actions:
                print(f"- {action}")
        else:
            print("No changes needed.")
        if validation_errors:
            print("Hook validation errors:", file=sys.stderr)
            for err in validation_errors:
                print(f"  {err}", file=sys.stderr)

    return 1 if validation_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
