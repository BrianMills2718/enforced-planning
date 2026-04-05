#!/usr/bin/env python3
"""Install or refresh the minimum governed-repo contract in a target repo.

This tool composes the existing governed-repo rollout primitives:

- scaffolds the minimum plan/doc graph surface when absent
- syncs canonical local validators into the target repo
- installs read-gating hook wiring
- refreshes generated ``AGENTS.md`` from canonical inputs
- re-audits the repo so rollout ends with an explicit governed/partial result

It does not invent a repo-specific ``CLAUDE.md``. The target repo must already
declare its canonical governance source.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enforced_planning.governed_repo_audit import _refresh_agents
from enforced_planning.governed_repo_audit import audit_repo
from enforced_planning.hook_wiring import TargetRepo
from enforced_planning.hook_wiring import apply_generation as apply_hook_generation
from enforced_planning.hook_wiring import plan_generation as plan_hook_generation


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_META_MARKER = "# === META-PROCESS TARGETS ==="
MAKEFILE_TEMPLATE = "templates/Makefile.meta"
MAKEFILE_WORKTREE_TEMPLATE = "templates/Makefile.worktree.block.template"
MAKEFILE_WORKTREE_BLOCK_START = "# >>> META-PROCESS WORKTREE TARGETS >>>"
MAKEFILE_WORKTREE_BLOCK_END = "# <<< META-PROCESS WORKTREE TARGETS <<<"
MAKEFILE_WORKTREE_INSERTION_ANCHORS = (
    "# --- During Implementation ---",
    "# --- PR Workflow ---",
    "# --- Plans ---",
    "# --- Quality ---",
    "# --- Help ---",
)

SYNC_SUPPORT_FILES: dict[str, str] = {
    "enforced_planning/__init__.py": "enforced_planning/__init__.py",
    "enforced_planning/agents_rendering.py": "enforced_planning/agents_rendering.py",
    "enforced_planning/create_worktree.py": "enforced_planning/create_worktree.py",
    "enforced_planning/file_context.py": "enforced_planning/file_context.py",
    "enforced_planning/notebook_registry_validation.py": "enforced_planning/notebook_registry_validation.py",
    "enforced_planning/plan_validation.py": "enforced_planning/plan_validation.py",
    "scripts/check_doc_coupling.py": "scripts/check_doc_coupling.py",
    "scripts/check_markdown_links.py": "scripts/check_markdown_links.py",
    "scripts/sync_plan_status.py": "scripts/sync_plan_status.py",
    "scripts/meta/check_agents_sync.py": "scripts/check_agents_sync.py",
    "scripts/meta/check_doc_coupling.py": "scripts/check_doc_coupling.py",
    "scripts/meta/file_context.py": "scripts/file_context.py",
    "scripts/meta/render_agents_md.py": "scripts/render_agents_md.py",
    "scripts/meta/sync_plan_status.py": "scripts/sync_plan_status.py",
    "scripts/meta/validate_plan.py": "scripts/validate_plan.py",
    "scripts/meta/worktree-coordination/check_claims.py": "scripts/worktree-coordination/check_claims.py",
    "scripts/meta/worktree-coordination/create_worktree.py": "scripts/worktree-coordination/create_worktree.py",
    "scripts/meta/worktree-coordination/safe_worktree_remove.py": "scripts/worktree-coordination/safe_worktree_remove.py",
    "meta-process/templates/agents.md.template": "templates/agents.md.template",
}

WORKTREE_ONLY_SYNC_SUPPORT_FILES: dict[str, str] = {
    "scripts/meta/worktree-coordination/check_claims.py": "scripts/worktree-coordination/check_claims.py",
    "scripts/meta/worktree-coordination/create_worktree.py": "scripts/worktree-coordination/create_worktree.py",
    "scripts/meta/worktree-coordination/safe_worktree_remove.py": "scripts/worktree-coordination/safe_worktree_remove.py",
}

SCAFFOLD_TEMPLATES: dict[str, str] = {
    "meta-process.yaml": "templates/meta-process.yaml.example",
    "docs/plans/CLAUDE.md": "templates/plans-index.md.template",
    "docs/plans/TEMPLATE.md": "templates/plan.md.template",
    "scripts/relationships.yaml": "templates/relationships.yaml.minimal",
}


@dataclass(frozen=True)
class InstallPlan:
    """Computed installer actions plus the file writes needed to realize them."""

    actions: list[str]
    scaffolded_files: list[str]
    drift_files: list[str]
    file_writes: dict[Path, str]
    blockers: list[str]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for governed-repo installation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repo root to upgrade.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--write",
        action="store_true",
        help="Apply the planned bootstrap/sync actions.",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned bootstrap/sync actions without applying them.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument(
        "--skip-hook-wiring",
        action="store_true",
        help="Do not sync the generic read-gating hook stack.",
    )
    parser.add_argument(
        "--worktree-only",
        action="store_true",
        help=(
            "Only sync the sanctioned Makefile worktree block plus the local "
            "worktree-coordination scripts."
        ),
    )
    parser.add_argument(
        "--strict-governed",
        action="store_true",
        help="Exit non-zero when the resulting repo is still not mechanically governed.",
    )
    return parser.parse_args(argv)


def _load_source_text(source_relpath: str) -> str:
    """Load one canonical support file or template from the local framework repo."""
    source_path = FRAMEWORK_ROOT / source_relpath
    return source_path.read_text(encoding="utf-8")


def _render_makefile_worktree_block(script_root: str) -> str:
    """Render the sanctioned worktree block for one Makefile consumer."""
    template = _load_source_text(MAKEFILE_WORKTREE_TEMPLATE)
    return template.replace("__WORKTREE_SCRIPT_ROOT__", script_root)


def _sync_makefile_worktree_block(current_makefile: str) -> tuple[str, str | None]:
    """Return synced Makefile text plus the installer action needed, if any."""
    block = _render_makefile_worktree_block("scripts/meta/worktree-coordination").rstrip()
    normalized = current_makefile.rstrip("\n")
    if MAKEFILE_WORKTREE_BLOCK_START in normalized:
        start = normalized.index(MAKEFILE_WORKTREE_BLOCK_START)
        end = normalized.index(MAKEFILE_WORKTREE_BLOCK_END) + len(MAKEFILE_WORKTREE_BLOCK_END)
        existing_block = normalized[start:end].rstrip()
        if existing_block == block:
            return normalized + "\n", None
        updated = normalized[:start].rstrip()
        if updated:
            updated += "\n\n"
        updated += block
        trailing = normalized[end:].strip("\n")
        if trailing:
            updated += "\n\n" + trailing
        return updated + "\n", "sync:Makefile.worktree"

    insertion_index: int | None = None
    for anchor in MAKEFILE_WORKTREE_INSERTION_ANCHORS:
        index = normalized.find(anchor)
        if index != -1:
            insertion_index = index
            break

    if insertion_index is None:
        updated = normalized
        if updated:
            updated += "\n\n"
        updated += block
        return updated + "\n", "append:Makefile.worktree"

    before = normalized[:insertion_index].rstrip("\n")
    after = normalized[insertion_index:].lstrip("\n")
    updated = before
    if updated:
        updated += "\n\n"
    updated += block
    if after:
        updated += "\n\n" + after
    return updated + "\n", "append:Makefile.worktree"


def _plan_static_support(repo_root: Path, *, worktree_only: bool) -> InstallPlan:
    """Plan scaffold and sync writes for static support files."""
    actions: list[str] = []
    scaffolded_files: list[str] = []
    drift_files: list[str] = []
    file_writes: dict[Path, str] = {}
    blockers: list[str] = []

    claude_path = repo_root / "CLAUDE.md"
    if not claude_path.exists():
        blockers.append("missing canonical CLAUDE.md")

    if not worktree_only:
        for target_relpath, source_relpath in SCAFFOLD_TEMPLATES.items():
            target_path = repo_root / target_relpath
            if target_path.exists():
                continue
            actions.append(f"scaffold:{target_relpath}")
            scaffolded_files.append(target_relpath)
            file_writes[target_path] = _load_source_text(source_relpath)

    support_files = (
        WORKTREE_ONLY_SYNC_SUPPORT_FILES if worktree_only else SYNC_SUPPORT_FILES
    )
    for target_relpath, source_relpath in support_files.items():
        target_path = repo_root / target_relpath
        canonical = _load_source_text(source_relpath)
        if not target_path.exists():
            actions.append(f"install:{target_relpath}")
            file_writes[target_path] = canonical
            continue
        current = target_path.read_text(encoding="utf-8")
        if current != canonical:
            actions.append(f"sync:{target_relpath}")
            drift_files.append(target_relpath)
            file_writes[target_path] = canonical

    makefile_path = repo_root / "Makefile"
    makefile_template = _load_source_text(MAKEFILE_TEMPLATE)
    if not makefile_path.exists():
        if worktree_only:
            blockers.append("missing Makefile for --worktree-only rollout")
        else:
            actions.append("scaffold:Makefile")
            scaffolded_files.append("Makefile")
            # Include worktree block so the Makefile is complete on first install.
            with_worktree, _ = _sync_makefile_worktree_block(makefile_template)
            file_writes[makefile_path] = with_worktree
    else:
        current_makefile = makefile_path.read_text(encoding="utf-8")
        synced_makefile, makefile_action = _sync_makefile_worktree_block(current_makefile)
        if makefile_action:
            actions.append(makefile_action)
            file_writes[makefile_path] = synced_makefile

    return InstallPlan(
        actions=actions,
        scaffolded_files=scaffolded_files,
        drift_files=drift_files,
        file_writes=file_writes,
        blockers=blockers,
    )


def _hook_target(repo_root: Path) -> TargetRepo:
    """Build a synthetic hook-generation target for dry-run or write mode."""
    return TargetRepo(
        root=repo_root,
        relationships_file=repo_root / "scripts" / "relationships.yaml",
        file_context_file=repo_root / "scripts" / "meta" / "file_context.py",
        settings_file=repo_root / ".claude" / "settings.json",
    )


def _plan_agents_refresh(
    repo_root: Path,
    *,
    relationships_present_or_planned: bool,
) -> tuple[list[str], list[str]]:
    """Plan AGENTS.md refresh work and return actions plus blockers.

    The installer may scaffold ``scripts/relationships.yaml`` in the same run,
    so AGENTS planning must treat a planned write as satisfying the generation
    prerequisite instead of blocking on the pre-install filesystem state.
    """
    actions: list[str] = []
    blockers: list[str] = []
    claude_path = repo_root / "CLAUDE.md"
    if not claude_path.exists():
        blockers.append("missing canonical CLAUDE.md")
        return actions, blockers
    if not relationships_present_or_planned:
        blockers.append("missing scripts/relationships.yaml for AGENTS generation")
        return actions, blockers
    actions.append("render:AGENTS.md")
    return actions, blockers


def _needs_agents_refresh(
    pre_audit: dict[str, Any],
    *,
    relationships_will_change: bool,
) -> bool:
    """Return True when AGENTS.md should be refreshed for the target repo."""
    agents = pre_audit["checks"]["agents_md"]
    if relationships_will_change:
        return True
    if not agents["present"]:
        return True
    return agents["in_sync"] is not True


def _apply_file_writes(file_writes: dict[Path, str]) -> None:
    """Write planned text files to disk, creating parents as needed."""
    for path, content in file_writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if path.suffix == ".sh":
            path.chmod(0o755)


def _write_agents(repo_root: Path) -> str:
    """Refresh AGENTS.md, removing the old CLAUDE symlink when present."""
    agents_path = repo_root / "AGENTS.md"
    claude_path = repo_root / "CLAUDE.md"
    if agents_path.is_symlink() and agents_path.resolve() == claude_path.resolve():
        agents_path.unlink()
    return _refresh_agents(
        repo_root,
        claude_file="CLAUDE.md",
        relationships_file="scripts/relationships.yaml",
        agents_file="AGENTS.md",
    )


def install_or_plan(
    repo_root: Path,
    *,
    write: bool,
    skip_hook_wiring: bool,
    worktree_only: bool,
) -> dict[str, Any]:
    """Plan or apply the governed-repo installer actions for one repo."""
    static_plan = _plan_static_support(repo_root, worktree_only=worktree_only)
    actions = list(static_plan.actions)
    scaffolded_files = list(static_plan.scaffolded_files)
    drift_files = list(static_plan.drift_files)
    blockers = list(static_plan.blockers)
    file_writes = dict(static_plan.file_writes)
    relationships_will_change = any(
        path == repo_root / "scripts" / "relationships.yaml" for path in file_writes
    )

    pre_audit = audit_repo(
        repo_root,
        claude_file="CLAUDE.md",
        relationships_file="scripts/relationships.yaml",
        agents_file="AGENTS.md",
        plans_dir="docs/plans",
    )

    if not skip_hook_wiring and not worktree_only:
        hook_actions, hook_writes, _ = plan_hook_generation(_hook_target(repo_root))
        actions.extend(hook_actions)
        file_writes.update(hook_writes)

    if not worktree_only:
        agent_actions, agent_blockers = _plan_agents_refresh(
            repo_root,
            relationships_present_or_planned=(
                (repo_root / "scripts" / "relationships.yaml").exists()
                or relationships_will_change
            ),
        )
        if _needs_agents_refresh(
            pre_audit,
            relationships_will_change=relationships_will_change,
        ):
            actions.extend(agent_actions)
        blockers.extend(agent_blockers)

    applied_actions: list[str] = []
    post_audit = pre_audit
    if write:
        if not blockers:
            _apply_file_writes(file_writes)
            applied_actions.extend(actions)
            if not skip_hook_wiring and not worktree_only:
                apply_hook_generation(_hook_target(repo_root), hook_writes)
            if not worktree_only and _needs_agents_refresh(
                pre_audit,
                relationships_will_change=relationships_will_change,
            ):
                applied_actions.append(_write_agents(repo_root))
            post_audit = audit_repo(
                repo_root,
                claude_file="CLAUDE.md",
                relationships_file="scripts/relationships.yaml",
                agents_file="AGENTS.md",
                plans_dir="docs/plans",
            )

    return {
        "repo_root": str(repo_root),
        "write_mode": write,
        "dry_run_mode": not write,
        "worktree_only_mode": worktree_only,
        "actions": actions,
        "applied_actions": applied_actions,
        "scaffolded_files": scaffolded_files,
        "drift_files": drift_files,
        "blockers": blockers,
        "pre_audit": pre_audit,
        "post_audit": post_audit,
    }


def _print_human(payload: dict[str, Any]) -> None:
    """Print a short human-readable summary for operator use."""
    print(f"Governed repo installer: {payload['repo_root']}")
    print(f"Mode: {'write' if payload['write_mode'] else 'dry-run'}")
    actions = payload["actions"]
    if actions:
        print("Planned actions:")
        for action in actions:
            print(f"  - {action}")
    else:
        print("Planned actions: none")

    blockers = payload["blockers"]
    if blockers:
        print("Blockers:")
        for blocker in blockers:
            print(f"  - {blocker}")

    post_audit = payload["post_audit"]
    print(f"Audit classification: {post_audit['classification']}")
    if post_audit["missing_required"]:
        print("Missing required signals:")
        for item in post_audit["missing_required"]:
            print(f"  - {item}")


def main(argv: list[str] | None = None) -> int:
    """Entry point for governed-repo installer planning and application."""
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    if not repo_root.exists():
        print(f"Repo root not found: {repo_root}", file=sys.stderr)
        return 1

    payload = install_or_plan(
        repo_root,
        write=args.write,
        skip_hook_wiring=args.skip_hook_wiring,
        worktree_only=args.worktree_only,
    )

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)

    final_audit = payload["post_audit"]
    if args.write and payload["blockers"]:
        return 1
    if args.strict_governed and final_audit["classification"] != "governed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
