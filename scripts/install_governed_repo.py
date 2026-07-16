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
from enforced_planning.hook_wiring import context_runtime_error
from enforced_planning.hook_wiring import plan_coordination_message_generation
from enforced_planning.hook_wiring import plan_generation as plan_hook_generation


FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_META_MARKER = "# === META-PROCESS TARGETS ==="
MAKEFILE_TEMPLATE = "templates/Makefile.meta"
MAKEFILE_WORKTREE_TEMPLATE = "templates/Makefile.worktree.block.template"
MAKEFILE_WORKTREE_BLOCK_START = "# >>> META-PROCESS WORKTREE TARGETS >>>"
MAKEFILE_WORKTREE_BLOCK_END = "# <<< META-PROCESS WORKTREE TARGETS <<<"
MAKEFILE_RELATIONSHIP_BLOCK_START = "# >>> RELATIONSHIP CONTEXT TARGETS >>>"
MAKEFILE_RELATIONSHIP_BLOCK_END = "# <<< RELATIONSHIP CONTEXT TARGETS <<<"
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
    "enforced_planning/concern_routing.py": "enforced_planning/concern_routing.py",
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
    "enforced_planning/coordination_messages.py": "enforced_planning/coordination_messages.py",
    "enforced_planning/doc_authority.py": "enforced_planning/doc_authority.py",
    "enforced_planning/file_context.py": "enforced_planning/file_context.py",
    "enforced_planning/relationship_context.py": "enforced_planning/relationship_context.py",
    "enforced_planning/context_packet.py": "enforced_planning/context_packet.py",
    "enforced_planning/impact_obligations.py": "enforced_planning/impact_obligations.py",
    "enforced_planning/verification_batch.py": "enforced_planning/verification_batch.py",
    "enforced_planning/docstring_wiki.py": "enforced_planning/docstring_wiki.py",
    "enforced_planning/test_relationships.py": "enforced_planning/test_relationships.py",
    "enforced_planning/worktree_paths.py": "enforced_planning/worktree_paths.py",
    "enforced_planning/notebook_registry_validation.py": "enforced_planning/notebook_registry_validation.py",
    "enforced_planning/plan_validation.py": "enforced_planning/plan_validation.py",
    "enforced_planning/push_safety.py": "enforced_planning/push_safety.py",
    "enforced_planning/session_contracts.py": "enforced_planning/session_contracts.py",
    "enforced_planning/session_lifecycle.py": "enforced_planning/session_lifecycle.py",
    "enforced_planning/worktree_lifecycle.yaml": "enforced_planning/worktree_lifecycle.yaml",
    "scripts/check_doc_coupling.py": "scripts/check_doc_coupling.py",
    "scripts/check_dead_code.py": "scripts/check_dead_code.py",
    "scripts/check_push_safety.py": "scripts/check_push_safety.py",
    "scripts/check_markdown_links.py": "scripts/check_markdown_links.py",
    "scripts/audit_dead_code.py": "scripts/audit_dead_code.py",
    "scripts/meta/session_finish.py": "scripts/session_finish.py",
    "scripts/meta/session_close.py": "scripts/session_close.py",
    "scripts/meta/session_heartbeat.py": "scripts/session_heartbeat.py",
    "scripts/meta/session_start.py": "scripts/session_start.py",
    "scripts/meta/session_status.py": "scripts/session_status.py",
    "scripts/meta/session_resume.py": "scripts/session_resume.py",
    "scripts/coordination_inbox.py": "scripts/coordination_inbox.py",
    "scripts/coordination_hook.py": "scripts/coordination_hook.py",
    "scripts/coordination_messages.py": "scripts/coordination_messages.py",
    "scripts/meta/coordination_inbox.py": "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_hook.py": "scripts/meta/coordination_hook.py",
    "scripts/meta/coordination_messages.py": "scripts/meta/coordination_messages.py",
    "scripts/sync_plan_status.py": "scripts/sync_plan_status.py",
    "scripts/meta/check_coordination_claims.py": "scripts/check_coordination_claims.py",
    "scripts/meta/check_agents_sync.py": "scripts/check_agents_sync.py",
    "scripts/meta/audit_dead_code.py": "scripts/audit_dead_code.py",
    "scripts/meta/check_doc_coupling.py": "scripts/check_doc_coupling.py",
    "scripts/meta/check_dead_code.py": "scripts/check_dead_code.py",
    "scripts/meta/check_push_safety.py": "scripts/check_push_safety.py",
    "scripts/meta/file_context.py": "scripts/file_context.py",
    "scripts/meta/relationship_context.py": "scripts/relationship_context.py",
    "scripts/meta/context_packet.py": "scripts/context_packet.py",
    "scripts/meta/impact_obligations.py": "scripts/impact_obligations.py",
    "scripts/meta/verification_batch.py": "scripts/verification_batch.py",
    "scripts/meta/docstring_wiki.py": "scripts/docstring_wiki.py",
    "scripts/meta/test_relationships.py": "scripts/test_relationships.py",
    "scripts/meta/render_agents_md.py": "scripts/render_agents_md.py",
    "scripts/meta/sync_plan_status.py": "scripts/sync_plan_status.py",
    "scripts/meta/validate_dead_code_audit.py": "scripts/validate_dead_code_audit.py",
    "scripts/meta/validate_plan.py": "scripts/validate_plan.py",
    "scripts/meta/worktree-coordination/create_worktree.py": "scripts/worktree-coordination/create_worktree.py",
    "scripts/meta/worktree-coordination/create_publish_worktree.py": "scripts/worktree-coordination/create_publish_worktree.py",
    "scripts/meta/worktree-coordination/create_review_claim.py": "scripts/worktree-coordination/create_review_claim.py",
    "scripts/meta/worktree-coordination/raise_concern.py": "scripts/worktree-coordination/raise_concern.py",
    "scripts/meta/worktree-coordination/safe_worktree_remove.py": "scripts/worktree-coordination/safe_worktree_remove.py",
    "meta-process/templates/agents.md.template": "templates/agents.md.template",
}

WORKTREE_ONLY_SYNC_SUPPORT_FILES: dict[str, str] = {
    "enforced_planning/__init__.py": "enforced_planning/__init__.py",
    "enforced_planning/concern_routing.py": "enforced_planning/concern_routing.py",
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
    "enforced_planning/coordination_messages.py": "enforced_planning/coordination_messages.py",
    "enforced_planning/doc_authority.py": "enforced_planning/doc_authority.py",
    "enforced_planning/push_safety.py": "enforced_planning/push_safety.py",
    "enforced_planning/session_contracts.py": "enforced_planning/session_contracts.py",
    "enforced_planning/session_lifecycle.py": "enforced_planning/session_lifecycle.py",
    "enforced_planning/verification_batch.py": "enforced_planning/verification_batch.py",
    "enforced_planning/worktree_lifecycle.yaml": "enforced_planning/worktree_lifecycle.yaml",
    "enforced_planning/worktree_paths.py": "enforced_planning/worktree_paths.py",
    "scripts/meta/check_coordination_claims.py": "scripts/check_coordination_claims.py",
    "scripts/meta/session_finish.py": "scripts/session_finish.py",
    "scripts/meta/session_close.py": "scripts/session_close.py",
    "scripts/meta/session_heartbeat.py": "scripts/session_heartbeat.py",
    "scripts/meta/session_start.py": "scripts/session_start.py",
    "scripts/meta/session_status.py": "scripts/session_status.py",
    "scripts/meta/session_resume.py": "scripts/session_resume.py",
    "scripts/meta/verification_batch.py": "scripts/verification_batch.py",
    "scripts/coordination_inbox.py": "scripts/coordination_inbox.py",
    "scripts/coordination_messages.py": "scripts/coordination_messages.py",
    "scripts/meta/coordination_inbox.py": "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_messages.py": "scripts/meta/coordination_messages.py",
    "scripts/meta/check_push_safety.py": "scripts/check_push_safety.py",
    "scripts/meta/worktree-coordination/create_worktree.py": "scripts/worktree-coordination/create_worktree.py",
    "scripts/meta/worktree-coordination/create_publish_worktree.py": "scripts/worktree-coordination/create_publish_worktree.py",
    "scripts/meta/worktree-coordination/create_review_claim.py": "scripts/worktree-coordination/create_review_claim.py",
    "scripts/meta/worktree-coordination/raise_concern.py": "scripts/worktree-coordination/raise_concern.py",
    "scripts/meta/worktree-coordination/safe_worktree_remove.py": "scripts/worktree-coordination/safe_worktree_remove.py",
}

RELATIONSHIP_CONTEXT_SYNC_SUPPORT_FILES: dict[str, str] = {
    "enforced_planning/relationship_context.py": "enforced_planning/relationship_context.py",
    "enforced_planning/context_packet.py": "enforced_planning/context_packet.py",
    "enforced_planning/impact_obligations.py": "enforced_planning/impact_obligations.py",
    "enforced_planning/docstring_wiki.py": "enforced_planning/docstring_wiki.py",
    "enforced_planning/test_relationships.py": "enforced_planning/test_relationships.py",
    "scripts/meta/relationship_context.py": "scripts/relationship_context.py",
    "scripts/meta/context_packet.py": "scripts/context_packet.py",
    "scripts/meta/impact_obligations.py": "scripts/impact_obligations.py",
    "scripts/meta/docstring_wiki.py": "scripts/docstring_wiki.py",
    "scripts/meta/test_relationships.py": "scripts/test_relationships.py",
}

COORDINATION_MESSAGES_SHARED_FILES: dict[str, str] = {
    "scripts/coordination_inbox.py": "scripts/coordination_inbox.py",
    "scripts/coordination_hook.py": "scripts/coordination_hook.py",
    "scripts/coordination_messages.py": "scripts/coordination_messages.py",
    "scripts/meta/coordination_inbox.py": "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_hook.py": "scripts/meta/coordination_hook.py",
    "scripts/meta/coordination_messages.py": "scripts/meta/coordination_messages.py",
    "scripts/meta/session_heartbeat.py": "scripts/session_heartbeat.py",
    "scripts/meta/session_resume.py": "scripts/session_resume.py",
    "scripts/meta/session_start.py": "scripts/session_start.py",
}

COORDINATION_MESSAGES_LOCAL_PACKAGE_FILES: dict[str, str] = {
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
    "enforced_planning/coordination_messages.py": "enforced_planning/coordination_messages.py",
    "enforced_planning/doc_authority.py": "enforced_planning/doc_authority.py",
    "enforced_planning/push_safety.py": "enforced_planning/push_safety.py",
    "enforced_planning/session_contracts.py": "enforced_planning/session_contracts.py",
    "enforced_planning/session_lifecycle.py": "enforced_planning/session_lifecycle.py",
    "enforced_planning/worktree_lifecycle.yaml": "enforced_planning/worktree_lifecycle.yaml",
    "enforced_planning/worktree_paths.py": "enforced_planning/worktree_paths.py",
}

RELATIONSHIP_CONTEXT_TARGETS = (
    "relationship-context",
    "context-packet",
    "impact-obligations",
    "docstring-wiki",
    "docstring-wiki-check",
    "test-relationships",
)

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
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--worktree-only",
        action="store_true",
        help=(
            "Only sync the sanctioned Makefile worktree block plus the local "
            "worktree-coordination scripts."
        ),
    )
    scope.add_argument(
        "--relationship-context-only",
        action="store_true",
        help=(
            "Only sync the relationship inventory, context packet, impact, "
            "docstring-wiki, Make, and read-gating hook surfaces."
        ),
    )
    scope.add_argument(
        "--coordination-messages-only",
        action="store_true",
        help="Only sync the canonical mailbox core, lifecycle adapters, and Claude/Codex hooks.",
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


def _render_makefile_relationship_block() -> str:
    """Extract the canonical marked relationship-context block."""

    template = _load_source_text(MAKEFILE_TEMPLATE)
    try:
        start = template.index(MAKEFILE_RELATIONSHIP_BLOCK_START)
        end = template.index(MAKEFILE_RELATIONSHIP_BLOCK_END) + len(
            MAKEFILE_RELATIONSHIP_BLOCK_END
        )
    except ValueError as exc:
        raise RuntimeError("canonical Makefile template lacks relationship-context markers") from exc
    return template[start:end].rstrip()


def _sync_makefile_relationship_block(
    current_makefile: str,
) -> tuple[str, str | None, str | None]:
    """Sync the bounded relationship block or report an unmarked collision."""

    block = _render_makefile_relationship_block()
    normalized = current_makefile.rstrip("\n")
    start_count = normalized.count(MAKEFILE_RELATIONSHIP_BLOCK_START)
    end_count = normalized.count(MAKEFILE_RELATIONSHIP_BLOCK_END)
    if start_count or end_count:
        if start_count != 1 or end_count != 1:
            return (
                current_makefile,
                None,
                "malformed relationship-context Makefile markers: "
                f"starts={start_count}, ends={end_count}",
            )
        start = normalized.index(MAKEFILE_RELATIONSHIP_BLOCK_START)
        end_start = normalized.index(MAKEFILE_RELATIONSHIP_BLOCK_END)
        if end_start < start:
            return (
                current_makefile,
                None,
                "malformed relationship-context Makefile markers: end precedes start",
            )
        end = end_start + len(
            MAKEFILE_RELATIONSHIP_BLOCK_END
        )
        existing = normalized[start:end].rstrip()
        if existing == block:
            return normalized + "\n", None, None
        updated = normalized[:start].rstrip()
        if updated:
            updated += "\n\n"
        updated += block
        trailing = normalized[end:].strip("\n")
        if trailing:
            updated += "\n\n" + trailing
        return updated + "\n", "sync:Makefile.relationship-context", None

    collisions = [
        target
        for target in RELATIONSHIP_CONTEXT_TARGETS
        if any(
            line.startswith(f"{target}:")
            for line in normalized.splitlines()
        )
    ]
    if collisions:
        return (
            current_makefile,
            None,
            "unmarked relationship-context Make targets already exist: "
            + ", ".join(collisions),
        )
    prefix = normalized + "\n\n" if normalized else ""
    return prefix + block + "\n", "append:Makefile.relationship-context", None


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


def _plan_static_support(
    repo_root: Path,
    *,
    worktree_only: bool,
    relationship_context_only: bool,
    coordination_messages_only: bool = False,
) -> InstallPlan:
    """Plan scaffold and sync writes for static support files."""
    actions: list[str] = []
    scaffolded_files: list[str] = []
    drift_files: list[str] = []
    file_writes: dict[Path, str] = {}
    blockers: list[str] = []

    claude_path = repo_root / "CLAUDE.md"
    if not claude_path.exists():
        blockers.append("missing canonical CLAUDE.md")

    if not worktree_only and not relationship_context_only and not coordination_messages_only:
        for target_relpath, source_relpath in SCAFFOLD_TEMPLATES.items():
            target_path = repo_root / target_relpath
            if target_path.exists():
                continue
            actions.append(f"scaffold:{target_relpath}")
            scaffolded_files.append(target_relpath)
            file_writes[target_path] = _load_source_text(source_relpath)

    if worktree_only:
        support_files = WORKTREE_ONLY_SYNC_SUPPORT_FILES
    elif relationship_context_only:
        support_files = RELATIONSHIP_CONTEXT_SYNC_SUPPORT_FILES
    elif coordination_messages_only:
        support_files = dict(COORDINATION_MESSAGES_SHARED_FILES)
        if (repo_root / "enforced_planning").is_dir():
            support_files.update(COORDINATION_MESSAGES_LOCAL_PACKAGE_FILES)
    else:
        support_files = SYNC_SUPPORT_FILES
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

    if coordination_messages_only:
        return InstallPlan(
            actions=actions,
            scaffolded_files=scaffolded_files,
            drift_files=drift_files,
            file_writes=file_writes,
            blockers=blockers,
        )

    makefile_path = repo_root / "Makefile"
    makefile_template = _load_source_text(MAKEFILE_TEMPLATE)
    if not makefile_path.exists():
        if worktree_only or relationship_context_only:
            mode = "--worktree-only" if worktree_only else "--relationship-context-only"
            blockers.append(f"missing Makefile for {mode} rollout")
        else:
            actions.append("scaffold:Makefile")
            scaffolded_files.append("Makefile")
            # Include worktree block so the Makefile is complete on first install.
            with_worktree, _ = _sync_makefile_worktree_block(makefile_template)
            file_writes[makefile_path] = with_worktree
    else:
        current_makefile = makefile_path.read_text(encoding="utf-8")
        if relationship_context_only:
            synced_makefile, makefile_action, makefile_blocker = (
                _sync_makefile_relationship_block(current_makefile)
            )
            if makefile_blocker:
                blockers.append(makefile_blocker)
        else:
            synced_makefile, makefile_action = _sync_makefile_worktree_block(
                current_makefile
            )
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
    relationship_context_only: bool,
    coordination_messages_only: bool = False,
) -> dict[str, Any]:
    """Plan or apply the governed-repo installer actions for one repo."""
    static_plan = _plan_static_support(
        repo_root,
        worktree_only=worktree_only,
        relationship_context_only=relationship_context_only,
        coordination_messages_only=coordination_messages_only,
    )
    actions = list(static_plan.actions)
    scaffolded_files = list(static_plan.scaffolded_files)
    drift_files = list(static_plan.drift_files)
    blockers = list(static_plan.blockers)
    if not worktree_only:
        runtime_error = context_runtime_error(
            repo_root,
            require_pydantic=not relationship_context_only,
        )
        if runtime_error:
            blockers.append(runtime_error)
    if relationship_context_only:
        relationships_path = repo_root / "scripts" / "relationships.yaml"
        if not relationships_path.exists():
            blockers.append("missing scripts/relationships.yaml for relationship-context rollout")
        if not skip_hook_wiring and not (repo_root / "scripts" / "meta" / "file_context.py").exists():
            blockers.append("missing scripts/meta/file_context.py for relationship-context hook rollout")
        if not skip_hook_wiring and not (repo_root / "enforced_planning" / "file_context.py").exists():
            blockers.append("missing enforced_planning/file_context.py for relationship-context hook rollout")
    if coordination_messages_only:
        local_package = (repo_root / "enforced_planning").is_dir()
        upstream_bootstrap = (repo_root / "scripts/_upstream_enforced_planning.py").is_file()
        if not local_package and not upstream_bootstrap:
            blockers.append(
                "coordination-messages-only rollout requires either a local "
                "enforced_planning package or scripts/_upstream_enforced_planning.py"
            )
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
        if coordination_messages_only:
            hook_actions, hook_writes, _ = plan_coordination_message_generation(
                _hook_target(repo_root)
            )
        else:
            hook_actions, hook_writes, _ = plan_hook_generation(
                _hook_target(repo_root),
                include_coordination_messages=not relationship_context_only,
            )
        duplicate_hook_paths = set(file_writes).intersection(hook_writes)
        for path in duplicate_hook_paths:
            if file_writes[path] != hook_writes[path]:
                raise RuntimeError(f"conflicting canonical installer content for {path}")
        actions.extend(
            action
            for action in hook_actions
            if repo_root / action.split(":", 1)[1] not in duplicate_hook_paths
        )
        hook_writes = {
            path: content
            for path, content in hook_writes.items()
            if path not in duplicate_hook_paths
        }
        file_writes.update(hook_writes)

    if not worktree_only and not relationship_context_only and not coordination_messages_only:
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
            if not worktree_only and not relationship_context_only and not coordination_messages_only and _needs_agents_refresh(
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
        "relationship_context_only_mode": relationship_context_only,
        "coordination_messages_only_mode": coordination_messages_only,
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
        relationship_context_only=args.relationship_context_only,
        coordination_messages_only=args.coordination_messages_only,
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
