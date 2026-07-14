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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]

# Hook shell scripts sourced from the extracted enforced-planning framework.
HOOK_FILES: dict[str, str] = {
    ".claude/hooks/gate-edit.sh": "hooks/claude/gate-edit.sh",
    ".claude/hooks/track-reads.sh": "hooks/claude/track-reads.sh",
    # Required by worktree-coordination hooks (block-cd-worktree, warn-worktree-cwd).
    # Install unconditionally so repos that later add worktree hooks don't break.
    ".claude/hooks/check-hook-enabled.sh": "hooks/claude/check-hook-enabled.sh",
}

# Support Python scripts sourced from this canonical framework.
SUPPORT_FILES: dict[str, str] = {
    "scripts/check_required_reading.py": "scripts/check_required_reading.py",
    "scripts/meta/hook_log.py": "scripts/hook_log.py",
    "scripts/meta/context_packet.py": "scripts/context_packet.py",
    "enforced_planning/context_packet.py": "enforced_planning/context_packet.py",
    "enforced_planning/relationship_context.py": "enforced_planning/relationship_context.py",
}

READ_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/track-reads.sh",
    "timeout": 1000,
}

GATE_HOOK = {
    "type": "command",
    "command": "bash .claude/hooks/gate-edit.sh",
    "timeout": 5000,
}


@dataclass(frozen=True)
class TargetRepo:
    """Resolved target repo plus the minimal prerequisites for wiring."""

    root: Path
    relationships_file: Path
    file_context_file: Path
    settings_file: Path


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

    settings_file = repo_root / ".claude" / "settings.json"
    return TargetRepo(
        root=repo_root,
        relationships_file=relationships_file,
        file_context_file=file_context_file,
        settings_file=settings_file,
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


def _render_settings(settings: dict[str, Any]) -> str:
    """Render deterministic pretty JSON for `.claude/settings.json`."""

    return json.dumps(settings, indent=2, sort_keys=False) + "\n"


def _relative(path: Path, repo_root: Path) -> str:
    """Return a repo-relative POSIX display path."""

    return path.relative_to(repo_root).as_posix()


def plan_generation(target: TargetRepo) -> tuple[list[str], dict[Path, str], str]:
    """Compute file writes and settings content for the target repo."""

    actions: list[str] = []
    file_writes: dict[Path, str] = {}

    for target_relpath, source_relpath in {**HOOK_FILES, **SUPPORT_FILES}.items():
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
    if _ensure_hook_command(
        edit_hooks,
        GATE_HOOK,
        after_command="bash .claude/hooks/protect-main.sh",
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
    hooks_dir = target.root / ".claude" / "hooks"
    if not hooks_dir.exists():
        return errors
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
        "required_inputs": [
            _relative(target.relationships_file, target.root),
            _relative(target.file_context_file, target.root),
        ],
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
