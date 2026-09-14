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
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enforced_planning import coordination_claims
from enforced_planning.governed_repo_audit import _refresh_agents, audit_repo
from enforced_planning.hook_wiring import (
    TargetRepo,
    context_runtime_error,
    plan_coordination_message_generation,
    plan_merge_guard_generation,
)
from enforced_planning.hook_wiring import apply_generation as apply_hook_generation
from enforced_planning.hook_wiring import plan_generation as plan_hook_generation
from enforced_planning.installed_framework import drop_vendored_package_files

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
    "enforced_planning/claim_mutation_receipts.py": "enforced_planning/claim_mutation_receipts.py",
    "enforced_planning/claim_bootstrap.py": "enforced_planning/claim_bootstrap.py",
    "enforced_planning/blocker_policy.py": "enforced_planning/blocker_policy.py",
    "scripts/meta/claim_bootstrap.py": "scripts/claim_bootstrap.py",
    "enforced_planning/client_session_metadata.py": "enforced_planning/client_session_metadata.py",
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
    "enforced_planning/concurrent_writers.py": "enforced_planning/concurrent_writers.py",
    "enforced_planning/mailbox_execution_identity.py": "enforced_planning/mailbox_execution_identity.py",
    "enforced_planning/coordination_messages.py": "enforced_planning/coordination_messages.py",
    "enforced_planning/outcome_admission.py": "enforced_planning/outcome_admission.py",
    "enforced_planning/outcome_continuation.py": "enforced_planning/outcome_continuation.py",
    "enforced_planning/outcome_completion.py": "enforced_planning/outcome_completion.py",
    "enforced_planning/outcome_portfolio.py": "enforced_planning/outcome_portfolio.py",
    "enforced_planning/outcome_selection.py": "enforced_planning/outcome_selection.py",
    "enforced_planning/prewrite_claim_fast.py": "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/pr_review_signoff.py": "enforced_planning/pr_review_signoff.py",
    "enforced_planning/integration_authority.py": "enforced_planning/integration_authority.py",
    "enforced_planning/repository_authority.py": "enforced_planning/repository_authority.py",
    "enforced_planning/session_target.py": "enforced_planning/session_target.py",
    "enforced_planning/prewrite_claim_projection.py": "enforced_planning/prewrite_claim_projection.py",
    "enforced_planning/artifact_creation.py": "enforced_planning/artifact_creation.py",
    "enforced_planning/plan_readiness.py": "enforced_planning/plan_readiness.py",
    "enforced_planning/plan_close.py": "enforced_planning/plan_close.py",
    "enforced_planning/doc_authority.py": "enforced_planning/doc_authority.py",
    "enforced_planning/file_context.py": "enforced_planning/file_context.py",
    "enforced_planning/relationship_context.py": "enforced_planning/relationship_context.py",
    "enforced_planning/context_packet.py": "enforced_planning/context_packet.py",
    "enforced_planning/impact_obligations.py": "enforced_planning/impact_obligations.py",
    "enforced_planning/verification_batch.py": "enforced_planning/verification_batch.py",
    "enforced_planning/docstring_wiki.py": "enforced_planning/docstring_wiki.py",
    "enforced_planning/effective_project_profile.py": "enforced_planning/effective_project_profile.py",
    "enforced_planning/test_relationships.py": "enforced_planning/test_relationships.py",
    "enforced_planning/worktree_paths.py": "enforced_planning/worktree_paths.py",
    "enforced_planning/notebook_registry_validation.py": "enforced_planning/notebook_registry_validation.py",
    "enforced_planning/plan_validation.py": "enforced_planning/plan_validation.py",
    "enforced_planning/push_safety.py": "enforced_planning/push_safety.py",
    "enforced_planning/repository_status.py": "enforced_planning/repository_status.py",
    "enforced_planning/session_contracts.py": "enforced_planning/session_contracts.py",
    "enforced_planning/session_continuity.py": "enforced_planning/session_continuity.py",
    "enforced_planning/session_lifecycle.py": "enforced_planning/session_lifecycle.py",
    "enforced_planning/session_process_fencing.py": "enforced_planning/session_process_fencing.py",
    "enforced_planning/surface_runtime.py": "enforced_planning/surface_runtime.py",
    "enforced_planning/worktree_lifecycle.yaml": "enforced_planning/worktree_lifecycle.yaml",
    "hooks/pre-push": "hooks/git/pre-push",
    "scripts/check_doc_coupling.py": "scripts/check_doc_coupling.py",
    "scripts/check_dead_code.py": "scripts/check_dead_code.py",
    "scripts/check_push_safety.py": "scripts/check_push_safety.py",
    "scripts/check_markdown_links.py": "scripts/check_markdown_links.py",
    "scripts/audit_dead_code.py": "scripts/audit_dead_code.py",
    "scripts/check_reachability.py": "scripts/check_reachability.py",
    "scripts/repo_stats_block.py": "scripts/repo_stats_block.py",
    "scripts/meta/session_finish.py": "scripts/session_finish.py",
    "scripts/meta/session_close.py": "scripts/session_close.py",
    "scripts/meta/session_continuity.py": "scripts/session_continuity.py",
    "scripts/meta/session_heartbeat.py": "scripts/session_heartbeat.py",
    "scripts/meta/session_narrow.py": "scripts/session_narrow.py",
    "scripts/meta/apply_blocker_disposition.py": "scripts/apply_blocker_disposition.py",
    "scripts/meta/outcome_completion_hook.py": "scripts/outcome_completion_hook.py",
    "scripts/meta/session_start.py": "scripts/session_start.py",
    "scripts/meta/session_status.py": "scripts/session_status.py",
    "scripts/meta/session_end.py": "scripts/session_end.py",
    "scripts/meta/project_status.py": "scripts/project_status.py",
    "scripts/meta/pr_auto.py": "scripts/pr_auto.py",
    "scripts/meta/pr_review_signoff_runtime.py": "enforced_planning/pr_review_signoff.py",
    "scripts/meta/session_resume.py": "scripts/session_resume.py",
    "scripts/meta/surface_runtime.py": "scripts/surface_runtime.py",
    "scripts/coordination_inbox.py": "scripts/coordination_inbox.py",
    "scripts/coordination_hook.py": "scripts/coordination_hook.py",
    "scripts/coordination_messages.py": "scripts/coordination_messages.py",
    "scripts/coordination_operator_status.py": "scripts/coordination_operator_status.py",
    "scripts/hook_receipts.py": "scripts/hook_receipts.py",
    "scripts/meta/coordination_inbox.py": "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_hook.py": "scripts/meta/coordination_hook.py",
    "scripts/meta/coordination_messages.py": "scripts/meta/coordination_messages.py",
    "scripts/meta/coordination_operator_status.py": "scripts/coordination_operator_status.py",
    "scripts/meta/hook_receipts.py": "scripts/hook_receipts.py",
    "scripts/sync_plan_status.py": "scripts/sync_plan_status.py",
    "scripts/meta/check_coordination_claims.py": "scripts/check_coordination_claims.py",
    "scripts/refresh_prewrite_claim_projection.py": "scripts/refresh_prewrite_claim_projection.py",
    "scripts/artifact_creation.py": "scripts/artifact_creation.py",
    "scripts/meta/check_agents_sync.py": "scripts/check_agents_sync.py",
    "scripts/meta/audit_dead_code.py": "scripts/audit_dead_code.py",
    "scripts/meta/check_doc_coupling.py": "scripts/check_doc_coupling.py",
    "scripts/meta/check_dead_code.py": "scripts/check_dead_code.py",
    "scripts/meta/check_push_safety.py": "scripts/check_push_safety.py",
    "scripts/meta/check_plan_readiness.py": "scripts/check_plan_readiness.py",
    "scripts/meta/plan_close.py": "scripts/plan_close.py",
    "scripts/meta/file_context.py": "scripts/file_context.py",
    "scripts/meta/relationship_context.py": "scripts/relationship_context.py",
    "scripts/meta/context_packet.py": "scripts/context_packet.py",
    "scripts/meta/impact_obligations.py": "scripts/impact_obligations.py",
    "scripts/meta/verification_batch.py": "scripts/verification_batch.py",
    "scripts/meta/docstring_wiki.py": "scripts/docstring_wiki.py",
    "scripts/meta/effective_project_profile.py": "scripts/effective_project_profile.py",
    "scripts/meta/test_relationships.py": "scripts/test_relationships.py",
    "scripts/meta/render_agents_md.py": "scripts/render_agents_md.py",
    "scripts/meta/sync_plan_status.py": "scripts/sync_plan_status.py",
    "scripts/meta/validate_dead_code_audit.py": "scripts/validate_dead_code_audit.py",
    "scripts/meta/validate_doc_authority.py": "scripts/validate_doc_authority.py",
    "scripts/meta/validate_plan.py": "scripts/validate_plan.py",
    "scripts/meta/canonical_lock.py": "scripts/worktree-coordination/canonical_lock.py",
    "scripts/meta/worktree-coordination/create_worktree.py": "scripts/worktree-coordination/create_worktree.py",
    "scripts/meta/worktree-coordination/finish_pr.py": "scripts/worktree-coordination/finish_pr.py",
    "scripts/meta/worktree-coordination/integration_authority.py": "scripts/worktree-coordination/integration_authority.py",
    "scripts/meta/worktree-coordination/create_publish_worktree.py": "scripts/worktree-coordination/create_publish_worktree.py",
    "scripts/meta/worktree-coordination/create_review_claim.py": "scripts/worktree-coordination/create_review_claim.py",
    "scripts/meta/worktree-coordination/raise_concern.py": "scripts/worktree-coordination/raise_concern.py",
    "scripts/meta/worktree-coordination/safe_worktree_remove.py": "scripts/worktree-coordination/safe_worktree_remove.py",
    "contracts/pr-review-signoff.schema.json": "contracts/pr-review-signoff.schema.json",
    "meta-process/templates/agents.md.template": "templates/agents.md.template",
}

WORKTREE_ONLY_SYNC_SUPPORT_FILES: dict[str, str] = {
    "enforced_planning/__init__.py": "enforced_planning/__init__.py",
    "enforced_planning/pr_review_signoff.py": "enforced_planning/pr_review_signoff.py",
    "enforced_planning/integration_authority.py": "enforced_planning/integration_authority.py",
    "enforced_planning/concern_routing.py": "enforced_planning/concern_routing.py",
    "enforced_planning/claim_mutation_receipts.py": "enforced_planning/claim_mutation_receipts.py",
    "enforced_planning/claim_bootstrap.py": "enforced_planning/claim_bootstrap.py",
    "enforced_planning/blocker_policy.py": "enforced_planning/blocker_policy.py",
    "enforced_planning/client_session_metadata.py": "enforced_planning/client_session_metadata.py",
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
    "enforced_planning/concurrent_writers.py": "enforced_planning/concurrent_writers.py",
    "enforced_planning/mailbox_execution_identity.py": "enforced_planning/mailbox_execution_identity.py",
    "enforced_planning/coordination_messages.py": "enforced_planning/coordination_messages.py",
    "enforced_planning/outcome_admission.py": "enforced_planning/outcome_admission.py",
    "enforced_planning/outcome_continuation.py": "enforced_planning/outcome_continuation.py",
    "enforced_planning/outcome_portfolio.py": "enforced_planning/outcome_portfolio.py",
    "enforced_planning/outcome_selection.py": "enforced_planning/outcome_selection.py",
    "enforced_planning/prewrite_claim_fast.py": "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/session_target.py": "enforced_planning/session_target.py",
    "enforced_planning/prewrite_claim_projection.py": "enforced_planning/prewrite_claim_projection.py",
    "enforced_planning/artifact_creation.py": "enforced_planning/artifact_creation.py",
    "enforced_planning/file_context.py": "enforced_planning/file_context.py",
    "enforced_planning/plan_readiness.py": "enforced_planning/plan_readiness.py",
    "enforced_planning/plan_validation.py": "enforced_planning/plan_validation.py",
    "enforced_planning/plan_close.py": "enforced_planning/plan_close.py",
    "enforced_planning/repository_authority.py": "enforced_planning/repository_authority.py",
    "enforced_planning/doc_authority.py": "enforced_planning/doc_authority.py",
    "enforced_planning/notebook_registry_validation.py": "enforced_planning/notebook_registry_validation.py",
    "enforced_planning/push_safety.py": "enforced_planning/push_safety.py",
    "enforced_planning/repository_status.py": "enforced_planning/repository_status.py",
    "enforced_planning/session_contracts.py": "enforced_planning/session_contracts.py",
    "enforced_planning/session_continuity.py": "enforced_planning/session_continuity.py",
    "enforced_planning/session_lifecycle.py": "enforced_planning/session_lifecycle.py",
    "enforced_planning/session_process_fencing.py": "enforced_planning/session_process_fencing.py",
    "enforced_planning/surface_runtime.py": "enforced_planning/surface_runtime.py",
    "enforced_planning/verification_batch.py": "enforced_planning/verification_batch.py",
    "enforced_planning/worktree_lifecycle.yaml": "enforced_planning/worktree_lifecycle.yaml",
    "enforced_planning/worktree_paths.py": "enforced_planning/worktree_paths.py",
    "hooks/pre-push": "hooks/git/pre-push",
    "scripts/meta/check_coordination_claims.py": "scripts/check_coordination_claims.py",
    "scripts/meta/claim_bootstrap.py": "scripts/claim_bootstrap.py",
    "scripts/refresh_prewrite_claim_projection.py": "scripts/refresh_prewrite_claim_projection.py",
    "scripts/artifact_creation.py": "scripts/artifact_creation.py",
    "scripts/meta/session_finish.py": "scripts/session_finish.py",
    "scripts/meta/session_close.py": "scripts/session_close.py",
    "scripts/meta/session_continuity.py": "scripts/session_continuity.py",
    "scripts/meta/session_heartbeat.py": "scripts/session_heartbeat.py",
    "scripts/meta/session_narrow.py": "scripts/session_narrow.py",
    "scripts/meta/apply_blocker_disposition.py": "scripts/apply_blocker_disposition.py",
    "scripts/meta/session_start.py": "scripts/session_start.py",
    "scripts/meta/session_status.py": "scripts/session_status.py",
    "scripts/meta/session_end.py": "scripts/session_end.py",
    "scripts/meta/project_status.py": "scripts/project_status.py",
    "scripts/meta/pr_auto.py": "scripts/pr_auto.py",
    "scripts/meta/pr_review_signoff_runtime.py": "enforced_planning/pr_review_signoff.py",
    "scripts/meta/session_resume.py": "scripts/session_resume.py",
    "scripts/meta/surface_runtime.py": "scripts/surface_runtime.py",
    "scripts/meta/verification_batch.py": "scripts/verification_batch.py",
    "scripts/meta/validate_doc_authority.py": "scripts/validate_doc_authority.py",
    "scripts/meta/canonical_lock.py": "scripts/worktree-coordination/canonical_lock.py",
    "scripts/coordination_inbox.py": "scripts/coordination_inbox.py",
    "scripts/coordination_messages.py": "scripts/coordination_messages.py",
    "scripts/coordination_operator_status.py": "scripts/coordination_operator_status.py",
    "scripts/meta/coordination_inbox.py": "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_messages.py": "scripts/meta/coordination_messages.py",
    "scripts/meta/coordination_operator_status.py": "scripts/coordination_operator_status.py",
    "scripts/meta/check_push_safety.py": "scripts/check_push_safety.py",
    "scripts/meta/check_plan_readiness.py": "scripts/check_plan_readiness.py",
    "scripts/meta/plan_close.py": "scripts/plan_close.py",
    "scripts/meta/worktree-coordination/create_worktree.py": "scripts/worktree-coordination/create_worktree.py",
    "scripts/meta/worktree-coordination/finish_pr.py": "scripts/worktree-coordination/finish_pr.py",
    "scripts/meta/worktree-coordination/integration_authority.py": "scripts/worktree-coordination/integration_authority.py",
    "scripts/meta/worktree-coordination/create_publish_worktree.py": "scripts/worktree-coordination/create_publish_worktree.py",
    "scripts/meta/worktree-coordination/create_review_claim.py": "scripts/worktree-coordination/create_review_claim.py",
    "scripts/meta/worktree-coordination/raise_concern.py": "scripts/worktree-coordination/raise_concern.py",
    "scripts/meta/worktree-coordination/safe_worktree_remove.py": "scripts/worktree-coordination/safe_worktree_remove.py",
    "contracts/pr-review-signoff.schema.json": "contracts/pr-review-signoff.schema.json",
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
    "scripts/meta/canonical_lock.py": "scripts/worktree-coordination/canonical_lock.py",
    "scripts/hook_receipts.py": "scripts/hook_receipts.py",
    "scripts/meta/hook_receipts.py": "scripts/hook_receipts.py",
    "scripts/coordination_inbox.py": "scripts/coordination_inbox.py",
    "scripts/coordination_hook.py": "scripts/coordination_hook.py",
    "scripts/coordination_messages.py": "scripts/coordination_messages.py",
    "scripts/coordination_operator_status.py": "scripts/coordination_operator_status.py",
    "scripts/meta/coordination_inbox.py": "scripts/meta/coordination_inbox.py",
    "scripts/meta/coordination_hook.py": "scripts/meta/coordination_hook.py",
    "scripts/meta/coordination_messages.py": "scripts/meta/coordination_messages.py",
    "scripts/meta/coordination_operator_status.py": "scripts/coordination_operator_status.py",
    "scripts/meta/session_heartbeat.py": "scripts/session_heartbeat.py",
    "scripts/meta/session_narrow.py": "scripts/session_narrow.py",
    "scripts/meta/apply_blocker_disposition.py": "scripts/apply_blocker_disposition.py",
    "scripts/meta/outcome_completion_hook.py": "scripts/outcome_completion_hook.py",
    "scripts/meta/session_close.py": "scripts/session_close.py",
    "scripts/meta/session_continuity.py": "scripts/session_continuity.py",
    "scripts/meta/session_resume.py": "scripts/session_resume.py",
    "scripts/meta/session_start.py": "scripts/session_start.py",
}

COORDINATION_MESSAGES_LOCAL_PACKAGE_FILES: dict[str, str] = {
    "enforced_planning/blocker_policy.py": "enforced_planning/blocker_policy.py",
    "enforced_planning/claim_mutation_receipts.py": "enforced_planning/claim_mutation_receipts.py",
    "enforced_planning/client_session_metadata.py": "enforced_planning/client_session_metadata.py",
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
    "enforced_planning/concurrent_writers.py": "enforced_planning/concurrent_writers.py",
    "enforced_planning/concern_routing.py": "enforced_planning/concern_routing.py",
    "enforced_planning/mailbox_execution_identity.py": "enforced_planning/mailbox_execution_identity.py",
    "enforced_planning/coordination_messages.py": "enforced_planning/coordination_messages.py",
    "enforced_planning/outcome_admission.py": "enforced_planning/outcome_admission.py",
    "enforced_planning/outcome_completion.py": "enforced_planning/outcome_completion.py",
    "enforced_planning/outcome_continuation.py": "enforced_planning/outcome_continuation.py",
    "enforced_planning/outcome_portfolio.py": "enforced_planning/outcome_portfolio.py",
    "enforced_planning/outcome_selection.py": "enforced_planning/outcome_selection.py",
    "enforced_planning/prewrite_claim_fast.py": "enforced_planning/prewrite_claim_fast.py",
    "enforced_planning/session_target.py": "enforced_planning/session_target.py",
    "enforced_planning/prewrite_claim_projection.py": "enforced_planning/prewrite_claim_projection.py",
    "enforced_planning/file_context.py": "enforced_planning/file_context.py",
    "enforced_planning/notebook_registry_validation.py": "enforced_planning/notebook_registry_validation.py",
    "enforced_planning/plan_validation.py": "enforced_planning/plan_validation.py",
    "enforced_planning/doc_authority.py": "enforced_planning/doc_authority.py",
    "enforced_planning/push_safety.py": "enforced_planning/push_safety.py",
    "enforced_planning/session_contracts.py": "enforced_planning/session_contracts.py",
    "enforced_planning/session_continuity.py": "enforced_planning/session_continuity.py",
    "enforced_planning/session_lifecycle.py": "enforced_planning/session_lifecycle.py",
    "enforced_planning/session_process_fencing.py": "enforced_planning/session_process_fencing.py",
    "enforced_planning/surface_runtime.py": "enforced_planning/surface_runtime.py",
    "enforced_planning/worktree_lifecycle.yaml": "enforced_planning/worktree_lifecycle.yaml",
    "enforced_planning/worktree_paths.py": "enforced_planning/worktree_paths.py",
    "scripts/refresh_prewrite_claim_projection.py": "scripts/refresh_prewrite_claim_projection.py",
}

CLAIM_PROJECTION_SHARED_FILES: dict[str, str] = {
    "scripts/meta/canonical_lock.py": "scripts/worktree-coordination/canonical_lock.py",
    "scripts/meta/check_coordination_claims.py": "scripts/check_coordination_claims.py",
    "scripts/meta/worktree-coordination/create_worktree.py": "scripts/worktree-coordination/create_worktree.py",
    "scripts/meta/session_close.py": "scripts/session_close.py",
    "scripts/meta/session_continuity.py": "scripts/session_continuity.py",
    "scripts/meta/session_end.py": "scripts/session_end.py",
    "scripts/meta/session_finish.py": "scripts/session_finish.py",
    "scripts/meta/session_heartbeat.py": "scripts/session_heartbeat.py",
    "scripts/meta/session_narrow.py": "scripts/session_narrow.py",
    "scripts/meta/apply_blocker_disposition.py": "scripts/apply_blocker_disposition.py",
    "scripts/meta/session_resume.py": "scripts/session_resume.py",
    "scripts/meta/session_start.py": "scripts/session_start.py",
}

# Lifecycle mutation and projection refresh are one import/runtime boundary. Keep
# the complete local dependency closure compatible while leaving hook wiring and
# mailbox client configuration outside this bounded installer profile.
# concern_routing.py (push_safety.py's best-effort, dynamically-imported
# conflict-notification helper) is excluded the same way: push_safety.py
# degrades gracefully without it (see its ModuleNotFoundError handling), and
# this profile stays free of the mailbox-notification surface on purpose.
CLAIM_PROJECTION_LOCAL_PACKAGE_FILES: dict[str, str] = {
    target: source
    for target, source in COORDINATION_MESSAGES_LOCAL_PACKAGE_FILES.items()
    if target
    not in {
        "enforced_planning/outcome_completion.py",
        "enforced_planning/concern_routing.py",
    }
}

COORDINATION_CLAIMS_SHARED_FILES: dict[str, str] = {
    "scripts/meta/check_coordination_claims.py": "scripts/check_coordination_claims.py",
}
COORDINATION_CLAIMS_LOCAL_PACKAGE_FILES: dict[str, str] = {
    "enforced_planning/coordination_claims.py": "enforced_planning/coordination_claims.py",
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
    mode.add_argument(
        "--check",
        action="store_true",
        help=("Check installer-managed drift without writing; exit non-zero when repair actions are required."),
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
        help=("Only sync the sanctioned Makefile worktree block plus the local worktree-coordination scripts."),
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
    scope.add_argument(
        "--claim-projection-refresh-only",
        action="store_true",
        help=(
            "Only sync claim mutation adapters and the digest-bound projection "
            "runtime; do not change hooks, Makefiles, or unrelated governance."
        ),
    )
    scope.add_argument(
        "--coordination-claims-only",
        action="store_true",
        help="Only sync the coordination-claims module and its stable CLI facade.",
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
        end = template.index(MAKEFILE_RELATIONSHIP_BLOCK_END) + len(MAKEFILE_RELATIONSHIP_BLOCK_END)
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
                f"malformed relationship-context Makefile markers: starts={start_count}, ends={end_count}",
            )
        start = normalized.index(MAKEFILE_RELATIONSHIP_BLOCK_START)
        end_start = normalized.index(MAKEFILE_RELATIONSHIP_BLOCK_END)
        if end_start < start:
            return (
                current_makefile,
                None,
                "malformed relationship-context Makefile markers: end precedes start",
            )
        end = end_start + len(MAKEFILE_RELATIONSHIP_BLOCK_END)
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
        if any(line.startswith(f"{target}:") for line in normalized.splitlines())
    ]
    if collisions:
        return (
            current_makefile,
            None,
            "unmarked relationship-context Make targets already exist: " + ", ".join(collisions),
        )
    prefix = normalized + "\n\n" if normalized else ""
    return prefix + block + "\n", "append:Makefile.relationship-context", None


def _sync_makefile_worktree_block(
    current_makefile: str,
) -> tuple[str, str | None, str | None]:
    """Return synced Makefile text, action, and any unsafe target collision."""
    block = _render_makefile_worktree_block("scripts/meta/worktree-coordination").rstrip()
    normalized = current_makefile.rstrip("\n")
    if MAKEFILE_WORKTREE_BLOCK_START in normalized:
        start = normalized.index(MAKEFILE_WORKTREE_BLOCK_START)
        end = normalized.index(MAKEFILE_WORKTREE_BLOCK_END) + len(MAKEFILE_WORKTREE_BLOCK_END)
        outside_block = normalized[:start] + "\n" + normalized[end:]
        collisions = [
            target
            for target in ("merge", "finish")
            if any(line.startswith(f"{target}:") for line in outside_block.splitlines())
        ]
        if collisions:
            return (
                current_makefile,
                None,
                "legacy PR Make targets outside the generated worktree block conflict with "
                "sanctioned finish: " + ", ".join(collisions),
            )
        existing_block = normalized[start:end].rstrip()
        if existing_block == block:
            return normalized + "\n", None, None
        updated = normalized[:start].rstrip()
        if updated:
            updated += "\n\n"
        updated += block
        trailing = normalized[end:].strip("\n")
        if trailing:
            updated += "\n\n" + trailing
        return updated + "\n", "sync:Makefile.worktree", None

    collisions = [
        target
        for target in ("merge", "finish")
        if any(line.startswith(f"{target}:") for line in normalized.splitlines())
    ]
    if collisions:
        return (
            current_makefile,
            None,
            "unmarked legacy PR Make targets conflict with sanctioned finish: "
            + ", ".join(collisions),
        )

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
        return updated + "\n", "append:Makefile.worktree", None

    before = normalized[:insertion_index].rstrip("\n")
    after = normalized[insertion_index:].lstrip("\n")
    updated = before
    if updated:
        updated += "\n\n"
    updated += block
    if after:
        updated += "\n\n" + after
    return updated + "\n", "append:Makefile.worktree", None


def _sync_makefile_status_target(
    current_makefile: str,
) -> tuple[str, str | None, str | None]:
    """Replace the exact legacy status recipe with fail-closed freshness status."""

    canonical_lines = [
        "PROJECT_STATUS_PYTHON ?= $(if $(strip $(PYTHON)),$(PYTHON),$(if $(wildcard .venv/bin/python),.venv/bin/python,python3))",
        "PROJECT_STATUS_SCRIPT ?= scripts/meta/project_status.py",
        "status:  ## Verify repository authority freshness and show branch status",
        "\t@$(PROJECT_STATUS_PYTHON) $(PROJECT_STATUS_SCRIPT) --repo-root .",
    ]
    canonical = "\n".join(canonical_lines)
    if canonical in current_makefile:
        return current_makefile, None, None

    lines = current_makefile.splitlines()
    status_indexes = [index for index, line in enumerate(lines) if line.startswith("status:")]
    if not status_indexes:
        prefix = current_makefile.rstrip()
        updated = f"{prefix}\n\n{canonical}\n" if prefix else f"{canonical}\n"
        return updated, "append:Makefile.status", None
    if len(status_indexes) != 1:
        return current_makefile, None, f"multiple status Make targets: {len(status_indexes)}"

    index = status_indexes[0]
    legacy_recipe = "\t@git status --short --branch"
    if index + 1 >= len(lines) or lines[index + 1] != legacy_recipe:
        return current_makefile, None, "unrecognized status Make target; refusing to overwrite"
    lines[index : index + 2] = canonical_lines
    return "\n".join(lines).rstrip() + "\n", "sync:Makefile.status", None


def _plan_static_support(
    repo_root: Path,
    *,
    worktree_only: bool,
    relationship_context_only: bool,
    coordination_messages_only: bool = False,
    claim_projection_refresh_only: bool = False,
    coordination_claims_only: bool = False,
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

    if (
        not worktree_only
        and not relationship_context_only
        and not coordination_messages_only
        and not claim_projection_refresh_only
        and not coordination_claims_only
    ):
        for target_relpath, source_relpath in SCAFFOLD_TEMPLATES.items():
            target_path = repo_root / target_relpath
            if target_path.exists():
                continue
            actions.append(f"scaffold:{target_relpath}")
            scaffolded_files.append(target_relpath)
            file_writes[target_path] = _load_source_text(source_relpath)

    if worktree_only:
        support_files = WORKTREE_ONLY_SYNC_SUPPORT_FILES
        reduced = drop_vendored_package_files(support_files, repo_root)
        if reduced != support_files:
            support_files = reduced
            actions.append("mode:installed-package")
    elif relationship_context_only:
        support_files = RELATIONSHIP_CONTEXT_SYNC_SUPPORT_FILES
    elif coordination_messages_only:
        support_files = dict(COORDINATION_MESSAGES_SHARED_FILES)
        if (repo_root / "enforced_planning").is_dir():
            support_files.update(COORDINATION_MESSAGES_LOCAL_PACKAGE_FILES)
    elif claim_projection_refresh_only:
        support_files = dict(CLAIM_PROJECTION_SHARED_FILES)
        if (repo_root / "enforced_planning").is_dir():
            support_files.update(CLAIM_PROJECTION_LOCAL_PACKAGE_FILES)
    elif coordination_claims_only:
        support_files = dict(COORDINATION_CLAIMS_SHARED_FILES)
        if (repo_root / "enforced_planning").is_dir():
            support_files.update(COORDINATION_CLAIMS_LOCAL_PACKAGE_FILES)
    else:
        support_files = SYNC_SUPPORT_FILES
        reduced = drop_vendored_package_files(support_files, repo_root)
        if reduced != support_files:
            support_files = reduced
            actions.append("mode:installed-package")
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
        elif target_relpath == "hooks/pre-push" and not os.access(target_path, os.X_OK):
            actions.append("chmod:hooks/pre-push")
            drift_files.append(target_relpath)
            file_writes[target_path] = canonical

    if coordination_messages_only or claim_projection_refresh_only or coordination_claims_only:
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
            with_worktree, _, makefile_blocker = _sync_makefile_worktree_block(makefile_template)
            if makefile_blocker:
                blockers.append(makefile_blocker)
            file_writes[makefile_path] = with_worktree
    else:
        current_makefile = makefile_path.read_text(encoding="utf-8")
        makefile_action: str | None = None
        status_action: str | None = None
        if relationship_context_only:
            synced_makefile, makefile_action, makefile_blocker = _sync_makefile_relationship_block(current_makefile)
            if makefile_blocker:
                blockers.append(makefile_blocker)
        else:
            status_synced, status_action, status_blocker = _sync_makefile_status_target(current_makefile)
            if status_blocker:
                blockers.append(status_blocker)
                synced_makefile, makefile_action = current_makefile, None
            else:
                synced_makefile, makefile_action, makefile_blocker = _sync_makefile_worktree_block(
                    status_synced
                )
                if makefile_blocker:
                    blockers.append(makefile_blocker)
                if status_action:
                    actions.append(status_action)
        if makefile_action:
            actions.append(makefile_action)
        if makefile_action or status_action:
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
        if path.suffix == ".sh" or path.name in {"pre-commit", "commit-msg", "post-commit", "pre-push"}:
            path.chmod(0o755)


def _plan_git_hook_activation(repo_root: Path) -> tuple[str | None, str | None]:
    """Plan safe activation of the versioned ``hooks/`` directory."""

    inside = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if inside.returncode != 0:
        return None, None

    configured = subprocess.run(
        ["git", "config", "--local", "--get", "core.hooksPath"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    current = configured.stdout.strip() if configured.returncode == 0 else ""
    if current:
        configured_path = Path(current).expanduser()
        if not configured_path.is_absolute():
            configured_path = repo_root / configured_path
        if configured_path.resolve() == (repo_root / "hooks").resolve():
            return None, None
    if current:
        return (
            None,
            f"core.hooksPath is already {current!r}; refusing to replace custom Git hooks",
        )
    return "configure:git.core.hooksPath=hooks", None


def _activate_git_hooks(repo_root: Path) -> None:
    """Point this repository at the installed, versioned hook directory."""

    configured = subprocess.run(
        ["git", "config", "--local", "core.hooksPath", "hooks"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if configured.returncode != 0:
        raise RuntimeError((configured.stderr or configured.stdout).strip() or "failed to configure core.hooksPath")


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


def _claim_runtime_downgrade_blockers(
    repo_root: Path,
    *,
    candidate_schema_version: int,
    session_narrow_available: bool,
    claims_dir: Path | None = None,
) -> list[str]:
    """Reject a runtime downgrade while a live typed broad lease depends on v6.

    The bootstrap sentinel remains a second fail-closed control for an older
    reader, but installation must not knowingly remove the only runtime that
    understands the typed lease or its owner-bound narrowing operation.
    """

    target = repo_root.expanduser().resolve()

    def git_common_dir(path: Path) -> Path | None:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        common = Path(result.stdout.strip())
        if not common.is_absolute():
            common = path / common
        return common.resolve()

    target_common = git_common_dir(target)
    live_broad = []
    for claim in coordination_claims.list_claims(claims_dir=claims_dir):
        if claim.schema_version < 6 or claim.broad_scope_mode not in coordination_claims.BROAD_SCOPE_MODES:
            continue
        if not claim.repo_root:
            continue
        claim_root = Path(claim.repo_root).expanduser().resolve()
        same_repository = claim_root == target
        if not same_repository and target_common is not None:
            same_repository = git_common_dir(claim_root) == target_common
        if not same_repository:
            continue
        live_broad.append(claim)
    if not live_broad:
        return []
    required_schema = max(claim.schema_version for claim in live_broad)
    if candidate_schema_version >= required_schema and session_narrow_available:
        return []
    lanes = ", ".join(
        sorted(f"{claim.primary_project()}:{claim.scope}" for claim in live_broad)
    )
    missing = []
    if candidate_schema_version < required_schema:
        missing.append(
            f"candidate claim schema {candidate_schema_version} is older than required schema {required_schema}"
        )
    if not session_narrow_available:
        missing.append("candidate runtime lacks scripts/session_narrow.py")
    return [
        "claim runtime downgrade denied while live typed broad claims exist "
        f"({lanes}): {'; '.join(missing)}"
    ]


def install_or_plan(
    repo_root: Path,
    *,
    write: bool,
    skip_hook_wiring: bool,
    worktree_only: bool,
    relationship_context_only: bool,
    coordination_messages_only: bool = False,
    claim_projection_refresh_only: bool = False,
    coordination_claims_only: bool = False,
) -> dict[str, Any]:
    """Plan or apply the governed-repo installer actions for one repo."""
    static_plan = _plan_static_support(
        repo_root,
        worktree_only=worktree_only,
        relationship_context_only=relationship_context_only,
        coordination_messages_only=coordination_messages_only,
        claim_projection_refresh_only=claim_projection_refresh_only,
        coordination_claims_only=coordination_claims_only,
    )
    actions = list(static_plan.actions)
    scaffolded_files = list(static_plan.scaffolded_files)
    drift_files = list(static_plan.drift_files)
    blockers = list(static_plan.blockers)
    if not relationship_context_only:
        blockers.extend(
            _claim_runtime_downgrade_blockers(
                repo_root,
                candidate_schema_version=coordination_claims.CURRENT_CLAIM_SCHEMA_VERSION,
                session_narrow_available=(FRAMEWORK_ROOT / "scripts" / "session_narrow.py").is_file(),
            )
        )
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
    if coordination_messages_only or claim_projection_refresh_only or coordination_claims_only:
        local_package = (repo_root / "enforced_planning").is_dir()
        upstream_bootstrap = (repo_root / "scripts/_upstream_enforced_planning.py").is_file()
        if not local_package and not upstream_bootstrap:
            if coordination_messages_only:
                profile = "coordination-messages-only"
            elif claim_projection_refresh_only:
                profile = "claim-projection-refresh-only"
            else:
                profile = "coordination-claims-only"
            blockers.append(
                f"{profile} rollout requires either a local "
                "enforced_planning package or scripts/_upstream_enforced_planning.py"
            )
    file_writes = dict(static_plan.file_writes)
    install_git_push_gate = (
        not relationship_context_only
        and not coordination_messages_only
        and not claim_projection_refresh_only
        and not coordination_claims_only
    )
    git_hook_action: str | None = None
    if install_git_push_gate:
        git_hook_action, git_hook_blocker = _plan_git_hook_activation(repo_root)
        if git_hook_action:
            actions.append(git_hook_action)
        if git_hook_blocker:
            blockers.append(git_hook_blocker)
    relationships_will_change = any(path == repo_root / "scripts" / "relationships.yaml" for path in file_writes)

    pre_audit = audit_repo(
        repo_root,
        claude_file="CLAUDE.md",
        relationships_file="scripts/relationships.yaml",
        agents_file="AGENTS.md",
        plans_dir="docs/plans",
    )

    if not skip_hook_wiring and not claim_projection_refresh_only and not coordination_claims_only:
        if worktree_only:
            hook_actions, hook_writes, _ = plan_merge_guard_generation(
                _hook_target(repo_root)
            )
        elif coordination_messages_only:
            hook_actions, hook_writes, _ = plan_coordination_message_generation(_hook_target(repo_root))
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
            action for action in hook_actions if repo_root / action.split(":", 1)[1] not in duplicate_hook_paths
        )
        hook_writes = {path: content for path, content in hook_writes.items() if path not in duplicate_hook_paths}
        file_writes.update(hook_writes)

    if (
        not worktree_only
        and not relationship_context_only
        and not coordination_messages_only
        and not claim_projection_refresh_only
        and not coordination_claims_only
    ):
        agent_actions, agent_blockers = _plan_agents_refresh(
            repo_root,
            relationships_present_or_planned=(
                (repo_root / "scripts" / "relationships.yaml").exists() or relationships_will_change
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
            if git_hook_action:
                _activate_git_hooks(repo_root)
            if not skip_hook_wiring and not claim_projection_refresh_only and not coordination_claims_only:
                apply_hook_generation(_hook_target(repo_root), hook_writes)
            if (
                not worktree_only
                and not relationship_context_only
                and not coordination_messages_only
                and not claim_projection_refresh_only
                and not coordination_claims_only
                and _needs_agents_refresh(
                    pre_audit,
                    relationships_will_change=relationships_will_change,
                )
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
        "claim_projection_refresh_only_mode": claim_projection_refresh_only,
        "coordination_claims_only_mode": coordination_claims_only,
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
        claim_projection_refresh_only=args.claim_projection_refresh_only,
        coordination_claims_only=args.coordination_claims_only,
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
    # The installed-package marker describes custody, not a pending write.
    pending_actions = [action for action in payload["actions"] if action != "mode:installed-package"]
    if args.check and (pending_actions or payload["blockers"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
