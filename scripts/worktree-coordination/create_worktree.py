#!/usr/bin/env python3
"""Create a git worktree and fail loud if the fresh checkout is unsafe.

This wrapper exists because raw ``git worktree add`` does not provide any
ecosystem-level guarantee that the created checkout is actually usable for
agent work. A freshly created worktree should be clean. If it is not, that is
already enough to block autonomous execution. The wrapper records the immediate
status, classifies stronger split-brain-like symptoms, and optionally cleans up
the failed worktree instead of leaving an ambiguous checkout in circulation.

When strict coordination enforcement is enabled, the wrapper also requires an
active scoped claim with explicit write authority before the worktree is
created. Narrow ``write`` claims and bounded ``program`` claims with exact
``write_paths`` both carry that authority.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_WORKTREE_EXCLUDE = "/worktrees/"
WRITE_AUTHORIZING_CLAIM_TYPES = frozenset({"write", "program"})
PROVISIONING_MARKER_PREFIX = ".worktree-provisioning-"


@dataclass(frozen=True)
class StatusEntry:
    """One porcelain status entry from a worktree checkout."""

    code: str
    path: str


@dataclass(frozen=True)
class WorktreeStatusSummary:
    """Summarize the immediate status of a freshly created worktree."""

    branch_line: str | None
    entries: list[StatusEntry]
    deleted_count: int
    untracked_count: int
    split_brain_like: bool
    clean: bool


@dataclass(frozen=True)
class WorktreeCreationResult:
    """Structured result for worktree creation and first-status verification."""

    ok: bool
    repo_root: str
    worktree_path: str
    branch: str
    created_branch: bool
    classification: str
    cleanup_performed: bool
    message: str
    status: WorktreeStatusSummary | None
    coordination_checked: bool
    coordination_message: str | None
    import_provenance_warning: str | None = None
    write_path_recent_history: str | None = None


@dataclass(frozen=True)
class CheckoutStateSummary:
    """Summarize whether one checkout is safe to use as a control surface."""

    clean: bool
    unmerged: bool
    entries: list[StatusEntry]
    modified_count: int
    untracked_count: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for worktree creation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Git repo root")
    parser.add_argument("--path", help="Path for the new worktree")
    parser.add_argument("--branch", help="Branch to create or attach")
    parser.add_argument(
        "--start-point",
        default="HEAD",
        help="Commit-ish to branch from when the branch does not already exist",
    )
    parser.add_argument(
        "--split-brain-threshold",
        type=int,
        default=5,
        help="Deleted/untracked count threshold for split-brain-like classification",
    )
    parser.add_argument(
        "--keep-failed-worktree",
        action="store_true",
        help="Leave a failed worktree on disk for manual diagnosis",
    )
    parser.add_argument(
        "--require-write-claim",
        action="store_true",
        help="Require a matching scoped write claim before creating the worktree.",
    )
    parser.add_argument(
        "--require-clean-main-root",
        action="store_true",
        help="Require the canonical main checkout to be clean before creating the worktree.",
    )
    parser.add_argument(
        "--allow-stale-start-point",
        action="store_true",
        help=(
            "Skip the default check that --start-point is not behind its configured upstream. "
            "Without this, branching from a stale start point fails loud instead of silently "
            "producing a branch that cannot fast-forward push later."
        ),
    )
    parser.add_argument("--claim-agent", help="Agent name expected on the scoped write claim.")
    parser.add_argument(
        "--claim-project",
        help="Claim project name. Defaults to the canonical repo root name when omitted.",
    )
    parser.add_argument(
        "--claim-write-path",
        action="append",
        default=[],
        help="Repo-relative write path required by the scoped claim. Repeat as needed.",
    )
    parser.add_argument(
        "--claim-start-revision",
        help="Full Git revision the matching plan-bound claim must retain.",
    )
    parser.add_argument(
        "--claims-dir",
        help="Override the coordination claims directory instead of ~/.claude/coordination/claims/.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON output",
    )
    parser.add_argument(
        "--print-default-worktree-dir",
        action="store_true",
        help="Print the canonical default worktrees/ directory inside the repo and exit.",
    )
    parser.add_argument(
        "--print-canonical-project",
        action="store_true",
        help="Print the canonical main repository directory name and exit.",
    )
    parser.add_argument(
        "--print-fresh-start-revision",
        action="store_true",
        help="Fetch the configured upstream for --start-point and print the exact fresh revision.",
    )
    return parser.parse_args(argv)


def run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run one git command and capture stdout/stderr for diagnosis."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def provisioning_marker_path(worktree_path: Path) -> Path:
    """Return the collision-resistant sibling marker for one target path."""
    digest = hashlib.sha256(str(worktree_path.resolve()).encode("utf-8")).hexdigest()
    return worktree_path.parent / f"{PROVISIONING_MARKER_PREFIX}{digest}.json"


def write_provisioning_marker(*, worktree_path: Path, branch: str) -> Path:
    """Make an in-progress worktree creation discoverable before Git mutates it."""
    marker = provisioning_marker_path(worktree_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "branch": branch,
        "pid": os.getpid(),
        "target_worktree_path": str(worktree_path.resolve()),
    }
    try:
        with marker.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError(
            f"Worktree provisioning is already active or was not reconciled: {marker}"
        ) from exc
    return marker


def clear_provisioning_marker(marker: Path) -> None:
    """Remove the marker only after creation has reached a terminal result."""
    marker.unlink(missing_ok=True)


def branch_exists(repo_root: Path, branch: str) -> bool:
    """Return whether a local branch already exists in the target repo."""
    result = run_git(["show-ref", "--verify", f"refs/heads/{branch}"], cwd=repo_root)
    return result.returncode == 0


def resolve_fresh_start_revision(*, repo_root: Path, start_point: str) -> str:
    """Resolve a start revision after refreshing its configured upstream.

    Branching a new worktree from a start point that is behind its upstream
    silently produces a branch that cannot fast-forward push once real work is
    committed on top of it -- the push failure surfaces late, disconnected from
    its actual cause. This has no effect when start_point has no configured
    upstream (detached ref, no tracking branch, or a bare commit-ish): there is
    nothing to compare against, so nothing is flagged.
    """
    local = run_git(["rev-parse", "--verify", f"{start_point}^{{commit}}"], cwd=repo_root)
    local_revision = local.stdout.strip()
    if local.returncode != 0 or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", local_revision) is None:
        raise ValueError(f"Unable to resolve one full Git start revision from {start_point!r}")

    upstream = run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", f"{start_point}@{{upstream}}"],
        cwd=repo_root,
    )
    remotes_result = run_git(["remote"], cwd=repo_root)
    remotes = set(remotes_result.stdout.split()) if remotes_result.returncode == 0 else set()
    explicit_remote = start_point.split("/", 1)[0] if "/" in start_point else None
    remote_name = explicit_remote if explicit_remote in remotes else None
    upstream_ref = upstream.stdout.strip() if upstream.returncode == 0 else ""
    if remote_name is None and "/" in upstream_ref:
        candidate = upstream_ref.split("/", 1)[0]
        remote_name = candidate if candidate in remotes else None
    if remote_name is None and start_point == "HEAD":
        if "origin" in remotes:
            remote_name = "origin"
        elif len(remotes) == 1:
            remote_name = next(iter(remotes))
        elif len(remotes) > 1:
            raise ValueError(
                "Unable to choose a remote default: multiple remotes exist and none is named 'origin'"
            )
    if remote_name is None:
        return local_revision
    if remote_name:
        # This updates only remote-tracking refs. A failed fetch must not leave
        # claim bootstrap silently pinned to a cached revision.
        fetched = run_git(["fetch", remote_name], cwd=repo_root)
        if fetched.returncode != 0:
            detail = (fetched.stderr or fetched.stdout).strip()
            raise ValueError(f"Unable to refresh upstream {upstream_ref!r}: {detail}")
    advertised_revision: str | None = None
    if start_point == "HEAD":
        advertised = run_git(["ls-remote", "--symref", remote_name, "HEAD"], cwd=repo_root)
        match = re.search(r"^ref:\s+refs/heads/([^\s]+)\s+HEAD$", advertised.stdout, re.MULTILINE)
        revisions = re.findall(r"^([0-9a-f]{40}|[0-9a-f]{64})\s+HEAD$", advertised.stdout, re.MULTILINE)
        if advertised.returncode != 0 or match is None or len(revisions) != 1:
            detail = (advertised.stderr or advertised.stdout).strip()
            raise ValueError(f"Unable to resolve remote default for {remote_name!r}: {detail}")
        upstream_ref = f"{remote_name}/{match.group(1)}"
        advertised_revision = revisions[0]
    elif explicit_remote == remote_name:
        upstream_ref = start_point
    if not upstream_ref:
        return local_revision
    fresh = run_git(["rev-parse", "--verify", f"{upstream_ref}^{{commit}}"], cwd=repo_root)
    fresh_revision = fresh.stdout.strip()
    if fresh.returncode != 0 or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", fresh_revision) is None:
        raise ValueError(f"Unable to resolve refreshed upstream revision from {upstream_ref!r}")
    if advertised_revision is not None and fresh_revision != advertised_revision:
        raise ValueError(
            f"Refreshed remote-tracking revision {fresh_revision} does not match advertised HEAD {advertised_revision}"
        )
    return fresh_revision


def resolve_main_repo_root(repo_root: Path) -> Path:
    """Resolve the canonical main repo root from either a root checkout or worktree."""
    result = run_git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=repo_root,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Unable to resolve canonical repo root from git common dir:\n{result.stderr or result.stdout}".strip()
        )
    git_common_dir = Path(result.stdout.strip())
    return git_common_dir.parent


def get_default_worktree_dir(repo_root: Path) -> Path:
    """Return the canonical worktrees/ directory inside this repo."""
    main_repo_root = resolve_main_repo_root(repo_root.resolve())
    return main_repo_root / "worktrees"


def get_canonical_project_name(repo_root: Path) -> str:
    """Return a stable project name from root or linked-worktree context."""

    return resolve_main_repo_root(repo_root.resolve()).name


def ensure_default_worktree_container_excluded(
    repo_root: Path,
    worktree_path: Path,
) -> bool:
    """Keep the required nested worktree container out of canonical status.

    The workspace contract places governed worktrees below ``<repo>/worktrees``.
    Git otherwise reports that container and every linked checkout below it as
    untracked content in the canonical checkout.  Record the exclusion in the
    repository-local Git info file rather than changing a portable ``.gitignore``.
    """

    main_repo_root = resolve_main_repo_root(repo_root.resolve())
    default_dir = get_default_worktree_dir(main_repo_root)
    try:
        worktree_path.resolve().relative_to(default_dir)
    except ValueError:
        return False

    exclude_result = run_git(
        ["rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
        cwd=main_repo_root,
    )
    if exclude_result.returncode != 0:
        raise RuntimeError(
            "Unable to resolve repository-local Git excludes file:\n"
            f"{exclude_result.stderr or exclude_result.stdout}".strip()
        )
    exclude_path = Path(exclude_result.stdout.strip())
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8") if exclude_path.is_file() else ""
    if DEFAULT_WORKTREE_EXCLUDE in {line.strip() for line in existing.splitlines()}:
        return True

    separator = "" if not existing or existing.endswith("\n") else "\n"
    with exclude_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{separator}{DEFAULT_WORKTREE_EXCLUDE}\n")
    return True


def _load_claims_module() -> Any:
    """Load the sibling coordination-claims script as a module."""
    module_path = Path(__file__).resolve().parents[1] / "check_coordination_claims.py"
    spec = importlib.util.spec_from_file_location("coordination_claims_for_worktree", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load coordination claims module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_status_porcelain(
    porcelain: str,
    *,
    split_brain_threshold: int,
) -> WorktreeStatusSummary:
    """Parse porcelain status output into a deterministic summary."""
    branch_line: str | None = None
    entries: list[StatusEntry] = []
    deleted_count = 0
    untracked_count = 0

    for raw_line in porcelain.splitlines():
        if not raw_line:
            continue
        if raw_line.startswith("## "):
            branch_line = raw_line[3:]
            continue
        if raw_line.startswith("?? "):
            code = "??"
            path = raw_line[3:]
            untracked_count += 1
        else:
            code = raw_line[:2]
            path = raw_line[3:]
            if "D" in code:
                deleted_count += 1
        entries.append(StatusEntry(code=code, path=path))

    split_brain_like = deleted_count >= split_brain_threshold and untracked_count >= split_brain_threshold
    return WorktreeStatusSummary(
        branch_line=branch_line,
        entries=entries,
        deleted_count=deleted_count,
        untracked_count=untracked_count,
        split_brain_like=split_brain_like,
        clean=len(entries) == 0,
    )


def inspect_worktree_state(
    worktree_path: Path,
    *,
    split_brain_threshold: int,
) -> WorktreeStatusSummary:
    """Inspect immediate worktree status after creation."""
    result = run_git(
        ["status", "--porcelain", "--untracked-files=all", "--branch"],
        cwd=worktree_path,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to inspect fresh worktree status:\n{result.stderr or result.stdout}".strip())
    return parse_status_porcelain(
        result.stdout,
        split_brain_threshold=split_brain_threshold,
    )


def classify_summary(summary: WorktreeStatusSummary) -> str:
    """Classify the immediate worktree state for operator-facing messages."""
    if summary.clean:
        return "clean"
    if summary.split_brain_like:
        return "split-brain-like"
    return "dirty"


def inspect_checkout_state(checkout_path: Path) -> CheckoutStateSummary:
    """Inspect whether one checkout is safe to use as a control surface."""

    result = run_git(
        ["status", "--porcelain", "--untracked-files=all"],
        cwd=checkout_path,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Unable to inspect checkout status:\n{result.stderr or result.stdout}".strip())

    entries: list[StatusEntry] = []
    modified_count = 0
    untracked_count = 0
    unmerged = False

    for raw_line in result.stdout.splitlines():
        if not raw_line:
            continue
        if raw_line.startswith("?? "):
            entries.append(StatusEntry(code="??", path=raw_line[3:]))
            untracked_count += 1
            continue
        code = raw_line[:2]
        path = raw_line[3:]
        entries.append(StatusEntry(code=code, path=path))
        if code in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
            unmerged = True
        else:
            modified_count += 1

    return CheckoutStateSummary(
        clean=len(entries) == 0,
        unmerged=unmerged,
        entries=entries,
        modified_count=modified_count,
        untracked_count=untracked_count,
    )


def verify_clean_main_root(repo_root: Path) -> tuple[bool, str]:
    """Require the canonical main checkout to be clean before publish-worktree creation."""

    main_repo_root = resolve_main_repo_root(repo_root)
    summary = inspect_checkout_state(main_repo_root)
    if summary.clean:
        return True, f"Canonical main checkout is clean: {main_repo_root}"

    classification = "main-root-unmerged" if summary.unmerged else "main-root-dirty"
    sample_entries = ", ".join(f"{entry.code} {entry.path}" for entry in summary.entries[:8])
    return (
        False,
        "Publish worktree creation blocked: canonical main checkout is not clean. "
        f"classification={classification}; "
        f"path={main_repo_root}; "
        f"modified={summary.modified_count}; "
        f"untracked={summary.untracked_count}; "
        f"sample=[{sample_entries}]. "
        "Do not create a publish lane from a dirty primary checkout; either clear the blocker first or keep the verified branch unpublished on trunk.",
    )


def cleanup_failed_worktree(
    repo_root: Path,
    worktree_path: Path,
    *,
    branch: str,
    created_branch: bool,
) -> tuple[bool, str]:
    """Attempt to remove a failed worktree and delete its just-created branch."""
    remove_result = run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=repo_root)
    if remove_result.returncode != 0 and worktree_path.exists():
        return False, (remove_result.stderr or remove_result.stdout).strip()
    if created_branch:
        delete_result = run_git(["branch", "-D", branch], cwd=repo_root)
        if delete_result.returncode != 0:
            return False, (delete_result.stderr or delete_result.stdout).strip()
    return True, "cleanup complete"


def ensure_safe_target_path(worktree_path: Path) -> None:
    """Reject non-empty target paths before invoking git worktree add."""
    if not worktree_path.exists():
        return
    if worktree_path.is_dir() and not any(worktree_path.iterdir()):
        return
    raise ValueError(f"Target worktree path already exists and is not empty: {worktree_path}")


def _claim_project(repo_root: Path, explicit_project: str | None) -> str:
    """Resolve the project name used for scoped claim matching."""
    if explicit_project:
        return explicit_project
    return resolve_main_repo_root(repo_root).name


def _write_paths_are_covered(*, claims_module: Any, required_paths: list[str], claim_paths: list[str]) -> bool:
    """Return whether a scoped claim covers every required write path."""
    for required in required_paths:
        if not any(claims_module._paths_overlap(required, existing) for existing in claim_paths):
            return False
    return True


def verify_scoped_write_claim(
    *,
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    claim_agent: str | None,
    claim_project: str | None,
    claim_write_paths: list[str],
    claims_dir: Path | None,
    expected_start_revision: str | None = None,
) -> tuple[bool, str]:
    """Require matching explicit write authority and reject conflicting claims."""
    if not claim_agent:
        return False, "Scoped write-claim enforcement requires --claim-agent."
    if not claim_write_paths:
        return False, (
            "Scoped write-claim enforcement requires at least one --claim-write-path, "
            "so this lane cannot be created without a declared write boundary.\n"
            '  Through Make:  SESSION_WRITE_PATHS="path/one path/two"\n'
            "  Use the narrowest set of paths this lane will actually write; "
            '"." claims the whole repository and is rarely what you want.'
        )

    claims_module = _load_claims_module()
    if claims_dir is not None:
        claims_module.CLAIMS_DIR = claims_dir.resolve()

    project_name = _claim_project(repo_root, claim_project)
    claims_owner = getattr(claims_module, "_impl", claims_module)
    native_session_id = claims_owner.resolve_session_id(claim_agent)
    normalized_paths = [claims_module._normalize_repo_path(path) for path in claim_write_paths]
    candidate = claims_module.build_candidate_claim(
        agent=claim_agent,
        project=project_name,
        scope=f"worktree:{branch}",
        intent=f"Create sanctioned worktree {branch}",
        claim_type="write",
        write_paths=normalized_paths,
        repo_root=str(repo_root),
        branch=branch,
        worktree_path=str(worktree_path),
    )
    active_claims = claims_module.check_claims(project_name)

    matching_claims = [
        claim
        for claim in active_claims
        if claim.agent == claim_agent
        and claim.claim_type in WRITE_AUTHORIZING_CLAIM_TYPES
        and project_name in claim.projects
        and (
            (claim.target_worktree_path or claim.worktree_path) is None
            or Path(str(claim.target_worktree_path or claim.worktree_path)).expanduser().resolve()
            == worktree_path.resolve()
        )
        and _write_paths_are_covered(
            claims_module=claims_module,
            required_paths=normalized_paths,
            claim_paths=claim.write_paths,
        )
        and (claim.branch in (None, branch))
        and (
            expected_start_revision is None
            or not claims_module.requires_work_graph(claim.plan_ref)
            or claim.start_revision == expected_start_revision
        )
    ]
    if not matching_claims:
        joined_paths = ", ".join(normalized_paths)
        return (
            False,
            "Scoped write-claim enforcement failed: no active matching write claim for "
            f"agent={claim_agent}, project={project_name}, branch={branch}, "
            f"write_paths=[{joined_paths}], "
            f"start_revision={expected_start_revision or 'not-required'}. "
            "Create the narrow revision-bound write claim first.",
        )

    weak_matching_claims = []
    for claim in matching_claims:
        issues = claims_module.claim_health_issues(claim)
        # staged_plan_reservation / staged_unplanned_reservation below tolerate
        # claim.tracker_path is None as a legitimate mid-bootstrap state, not
        # a defect. See "tracker_path's three lifecycle states" in
        # docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md before touching
        # this exemption or coordination_claims.py's CREATION_BLOCKING set.
        staged_plan_reservation = (
            claim.tracker_path is None
            and claims_module.requires_work_graph(claim.plan_ref)
            and claim.schema_version >= 4
            and claim.start_revision == expected_start_revision
            and claim.branch == branch
            and (claim.target_worktree_path or claim.worktree_path) is not None
            and Path(str(claim.target_worktree_path or claim.worktree_path)).expanduser().resolve()
            == worktree_path.resolve()
            and bool(claim.session_id and claim.session_name and claim.broader_goal)
        )
        staged_unplanned_reservation = (
            claim.tracker_path is None
            and isinstance(claim.plan_ref, str)
            and claim.plan_ref.strip() == "UNPLANNED"
            and claim.branch == branch
            and (claim.target_worktree_path or claim.worktree_path) is not None
            and Path(str(claim.target_worktree_path or claim.worktree_path)).expanduser().resolve()
            == worktree_path.resolve()
            and bool(claim.session_id and claim.session_name and claim.broader_goal)
        )
        staged_goal_reservation = (
            claim.tracker_path is None
            and claim.schema_version >= 6
            and isinstance(claim.plan_ref, str)
            and claim.plan_ref.strip().startswith("goal:")
            and bool(claim.plan_ref.strip().removeprefix("goal:").strip())
            and claim.session_id == native_session_id
            and claim.branch == branch
            and (claim.target_worktree_path or claim.worktree_path) is not None
            and Path(str(claim.target_worktree_path or claim.worktree_path)).expanduser().resolve()
            == worktree_path.resolve()
            and bool(claim.session_id and claim.session_name and claim.broader_goal)
        )
        if staged_plan_reservation or staged_unplanned_reservation or staged_goal_reservation:
            issues = [issue for issue in issues if issue != "missing_tracker_path"]
        if claim.broad_scope_mode == "bootstrap":
            issues = [issue for issue in issues if issue != "bootstrap_broad_claim_requires_narrowing"]
        if issues:
            weak_matching_claims.append((claim, issues))
    if weak_matching_claims:
        claim, issues = weak_matching_claims[0]
        return (
            False,
            "Scoped write-claim enforcement failed: matching active write claim is weak — "
            f"agent={claim.agent}, project={project_name}, scope={claim.scope}, "
            f"issues=[{', '.join(issues)}]. Refresh the claim with explicit live ownership metadata first.",
        )

    matched_claim = matching_claims[0]
    check_result = claims_module.evaluate_claim(
        candidate,
        active_claims=[claim for claim in active_claims if claim is not matched_claim],
    )
    hard_conflicts = check_result.hard_conflicts
    if hard_conflicts:
        formatted = "; ".join(
            f"{item.other_agent} ({item.other_scope}: {', '.join(item.overlapping_write_paths)})"
            for item in hard_conflicts
        )
        return (
            False,
            f"Scoped write-claim enforcement failed: conflicting active write claim(s) detected — {formatted}",
        )

    message = (
        f"Scoped write claim verified via {claim_agent}:{project_name}:{matched_claim.scope} "
        f"({matched_claim.claim_type} claim)."
    )
    return True, message


def create_worktree(
    *,
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    start_point: str,
    split_brain_threshold: int,
    keep_failed_worktree: bool,
    require_write_claim: bool = False,
    claim_agent: str | None = None,
    claim_project: str | None = None,
    claim_write_paths: list[str] | None = None,
    claims_dir: Path | None = None,
    require_clean_main_root: bool = False,
    claim_start_revision: str | None = None,
    allow_stale_start_point: bool = False,
) -> WorktreeCreationResult:
    """Create a worktree, inspect it immediately, and fail loud on unsafe state."""
    repo_root = repo_root.resolve()
    worktree_path = worktree_path.resolve()
    if allow_stale_start_point:
        resolved_start = run_git(["rev-parse", "--verify", f"{start_point}^{{commit}}"], cwd=repo_root)
        start_revision = resolved_start.stdout.strip()
        if resolved_start.returncode != 0 or re.fullmatch(
            r"(?:[0-9a-f]{40}|[0-9a-f]{64})", start_revision
        ) is None:
            raise ValueError(f"Unable to resolve one full Git start revision from {start_point!r}")
    else:
        start_revision = resolve_fresh_start_revision(repo_root=repo_root, start_point=start_point)
    if claim_start_revision is not None and claim_start_revision != start_revision:
        raise ValueError(
            "Requested claim custody does not match the resolved worktree start revision: "
            f"claim={claim_start_revision}, worktree={start_revision}"
        )
    coordination_checked = require_write_claim
    coordination_message: str | None = None

    if require_write_claim:
        claim_ok, coordination_message = verify_scoped_write_claim(
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
            claim_agent=claim_agent,
            claim_project=claim_project,
            claim_write_paths=claim_write_paths or [],
            claims_dir=claims_dir,
            expected_start_revision=start_revision,
        )
        if not claim_ok:
            return WorktreeCreationResult(
                ok=False,
                repo_root=str(repo_root),
                worktree_path=str(worktree_path),
                branch=branch,
                created_branch=False,
                classification="coordination-error",
                cleanup_performed=False,
                message=coordination_message,
                status=None,
                coordination_checked=coordination_checked,
                coordination_message=coordination_message,
            )

    if require_clean_main_root:
        clean_main_root, root_message = verify_clean_main_root(repo_root)
        if not clean_main_root:
            return WorktreeCreationResult(
                ok=False,
                repo_root=str(repo_root),
                worktree_path=str(worktree_path),
                branch=branch,
                created_branch=False,
                classification="main-root-dirty",
                cleanup_performed=False,
                message=root_message,
                status=None,
                coordination_checked=coordination_checked,
                coordination_message=coordination_message,
            )

    ensure_safe_target_path(worktree_path)
    ensure_default_worktree_container_excluded(repo_root, worktree_path)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    branch_already_exists = branch_exists(repo_root, branch)
    if branch_already_exists:
        branch_revision = run_git(
            ["rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}"],
            cwd=repo_root,
        )
        if branch_revision.returncode != 0 or branch_revision.stdout.strip() != start_revision:
            raise ValueError(f"Existing branch {branch!r} does not match requested start revision {start_revision}")

    add_args = ["worktree", "add", str(worktree_path)]
    if branch_already_exists:
        add_args.append(branch)
        created_branch = False
    else:
        add_args.extend(["-b", branch, start_revision])
        created_branch = True

    add_result = run_git(add_args, cwd=repo_root)
    if add_result.returncode != 0:
        return WorktreeCreationResult(
            ok=False,
            repo_root=str(repo_root),
            worktree_path=str(worktree_path),
            branch=branch,
            created_branch=created_branch,
            classification="git-error",
            cleanup_performed=False,
            message=(add_result.stderr or add_result.stdout).strip(),
            status=None,
            coordination_checked=coordination_checked,
            coordination_message=coordination_message,
        )

    created_revision = run_git(
        ["rev-parse", "--verify", "HEAD^{commit}"],
        cwd=worktree_path,
    )
    if created_revision.returncode != 0 or created_revision.stdout.strip() != start_revision:
        cleanup_performed = False
        cleanup_note = "failed worktree retained by operator request"
        if not keep_failed_worktree:
            cleanup_performed, cleanup_note = cleanup_failed_worktree(
                repo_root,
                worktree_path,
                branch=branch,
                created_branch=created_branch,
            )
        return WorktreeCreationResult(
            ok=False,
            repo_root=str(repo_root),
            worktree_path=str(worktree_path),
            branch=branch,
            created_branch=created_branch,
            classification="revision-mismatch",
            cleanup_performed=cleanup_performed,
            message=(f"Created worktree did not retain start revision {start_revision}. Cleanup: {cleanup_note}"),
            status=None,
            coordination_checked=coordination_checked,
            coordination_message=coordination_message,
        )

    summary = inspect_worktree_state(
        worktree_path,
        split_brain_threshold=split_brain_threshold,
    )
    classification = classify_summary(summary)
    if classification == "clean":
        return WorktreeCreationResult(
            ok=True,
            repo_root=str(repo_root),
            worktree_path=str(worktree_path),
            branch=branch,
            created_branch=created_branch,
            classification=classification,
            cleanup_performed=False,
            message="Worktree created cleanly.",
            status=summary,
            coordination_checked=coordination_checked,
            coordination_message=coordination_message,
            import_provenance_warning=_import_provenance_warning(worktree_path),
            write_path_recent_history=_recent_write_path_history(worktree_path, claim_write_paths or []),
        )

    cleanup_performed = False
    cleanup_note = ""
    if not keep_failed_worktree:
        cleanup_ok, cleanup_note = cleanup_failed_worktree(
            repo_root,
            worktree_path,
            branch=branch,
            created_branch=created_branch,
        )
        cleanup_performed = cleanup_ok
        if not cleanup_ok and worktree_path.exists():
            cleanup_note = f" Cleanup failed: {cleanup_note}"

    sample_entries = ", ".join(f"{entry.code} {entry.path}" for entry in summary.entries[:8])
    return WorktreeCreationResult(
        ok=False,
        repo_root=str(repo_root),
        worktree_path=str(worktree_path),
        branch=branch,
        created_branch=created_branch,
        classification=classification,
        cleanup_performed=cleanup_performed,
        message=(
            "Fresh worktree was not clean immediately after creation. "
            f"classification={classification}; "
            f"deleted={summary.deleted_count}; "
            f"untracked={summary.untracked_count}; "
            f"sample=[{sample_entries}].{cleanup_note}"
        ),
        status=summary,
        coordination_checked=coordination_checked,
        coordination_message=coordination_message,
    )



def _recent_write_path_history(worktree_path: Path, write_paths: list[str], *, limit: int = 3) -> str | None:
    """One-line-per-commit recent history for each claimed write path, read at
    this worktree's own fresh HEAD -- so a diagnosis formed before the
    worktree existed doesn't go stale before the first edit.

    A coordination claim answers "is anyone else about to write here." It
    never answers "has someone already written this." Found 2026-09-14: a
    session diagnosed a bug, claimed a worktree, and started writing the fix
    -- discovering only when an Edit call's old_string failed to match that
    commit 831e09fa5a8 had already shipped the identical fix minutes earlier.
    The claim was clean; the content had simply moved. Printing each claimed
    path's last few commits, unprompted, right after worktree creation, puts
    exactly that fact in front of the agent before it writes anything.
    """
    if not write_paths:
        return None
    lines: list[str] = []
    for path in write_paths:
        result = run_git(["log", f"-{limit}", "--oneline", "--", path], cwd=worktree_path)
        if result.returncode == 0 and result.stdout.strip():
            lines.append(f"{path}:")
            lines.extend(f"  {line}" for line in result.stdout.strip().splitlines())
    return "\n".join(lines) if lines else None


def _import_provenance_warning(worktree_path: Path) -> str | None:
    """Report, without blocking, when this worktree's packages resolve elsewhere.

    A clean git status says the checkout is isolated. It says nothing about
    which code Python will import when tests run here. Those are different
    isolations, and only the second one decides whether a green suite means
    anything.

    Measured, not Enforced: at creation the worktree has no environment yet, so
    a hard failure here would deny a lane for a condition that is not yet true.
    Enforce it where a repository is about to trust a result.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from import_provenance import (  # noqa: PLC0415
            ImportProvenanceError,
            check_import_provenance,
            render_warning,
        )
    except ImportError:
        return None
    try:
        return render_warning(check_import_provenance(worktree_path))
    except ImportProvenanceError:
        # The repository ships no discoverable package, so there is nothing this
        # check can speak to. Silence here is honest; silence on a real leak is
        # not, which is why check_import_provenance raises instead of passing.
        return None


def _print_human(result: WorktreeCreationResult) -> None:
    """Print a concise operator summary."""
    state = "OK" if result.ok else "FAIL"
    print(f"{state}: {result.message}")
    print(f"repo: {result.repo_root}")
    print(f"path: {result.worktree_path}")
    print(f"branch: {result.branch}")
    if result.coordination_checked and result.coordination_message:
        print(f"coordination: {result.coordination_message}")
    if result.status is not None:
        print(f"classification: {result.classification}")
        print(
            "status-counts: "
            f"deleted={result.status.deleted_count} "
            f"untracked={result.status.untracked_count} "
            f"entries={len(result.status.entries)}"
        )
    if result.write_path_recent_history:
        print(
            "\nRecent history of claimed write paths -- read this before your "
            "first edit, not just before merging. A coordination claim answers "
            "who else is about to write here; it does not answer whether "
            "someone already has:"
        )
        print(result.write_path_recent_history)
    if result.import_provenance_warning:
        # stdout is block-buffered when piped; without the flush this warning
        # lands above the lane summary it qualifies.
        sys.stdout.flush()
        print(f"\n{result.import_provenance_warning}", file=sys.stderr)


def _canonical_lock_module_path(script_path: Path | None = None) -> Path:
    """Resolve the helper in both source and installed worktree layouts."""

    current = (script_path or Path(__file__)).resolve()
    candidates = (
        current.parent / "canonical_lock.py",
        current.parents[1] / "canonical_lock.py",
        current.parents[2] / "worktree-coordination" / "canonical_lock.py",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), candidates[0])


def _lock_canonical_checkout(repo_root: Path, *, as_json: bool) -> None:
    """Make the canonical checkout read-only now that a lane exists.

    This is the primary trigger for the canonical lock. It fires here because
    creating a lane is the moment the canonical checkout stops being a safe
    place to write, and because this wrapper is the sanctioned entry point that
    agents already use -- nobody has to remember a separate command.

    A failure to lock is reported loudly and does not fail worktree creation:
    the lane is already usable, and a missing lock is a weaker state, not a
    corrupt one. It must never be silent, which is why it prints either way.
    """
    module_path = _canonical_lock_module_path()
    if not module_path.exists():
        print(
            f"WARNING: canonical lock unavailable ({module_path} missing); canonical checkout stays writable",
            file=sys.stderr,
        )
        return
    result = subprocess.run(
        [sys.executable, str(module_path), "--reconcile", "--repo", str(repo_root), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # stderr, never stdout: this wrapper's stdout is parsed as JSON by the
        # installed make/session machinery, and an extra line there breaks the
        # caller's rollback path.
        print(
            "WARNING: canonical checkout could not be locked; it remains writable and a "
            f"concurrent write there can still destroy this lane's work.\n{result.stdout}{result.stderr}",
            file=sys.stderr,
        )
        return
    if not as_json:
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            payload = {}
        actions = payload.get("actions") or []
        locked = [a for a in actions if a.get("action") in {"locked", "already_locked", "relocked"}]
        if locked:
            print(f"canonical checkout is now read-only: {repo_root} (lane work belongs in the worktree above)")
        # A repair is the one case the operator most needs to hear about: the
        # boundary was reported as holding while it had silently stopped.
        for repaired in (a for a in actions if a.get("action") == "relocked"):
            print(f"canonical lock had DECAYED and was repaired: {repaired.get('repo_root')} — {repaired.get('reason', 'drift')}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for safe worktree creation."""
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    if args.print_default_worktree_dir:
        default_dir = get_default_worktree_dir(repo_root)
        if args.json:
            print(json.dumps({"default_worktree_dir": str(default_dir)}, indent=2))
        else:
            print(default_dir)
        return 0
    if args.print_canonical_project:
        project_name = get_canonical_project_name(repo_root)
        if args.json:
            print(json.dumps({"canonical_project": project_name}, indent=2))
        else:
            print(project_name)
        return 0
    if args.print_fresh_start_revision:
        try:
            revision = resolve_fresh_start_revision(repo_root=repo_root, start_point=args.start_point)
        except (RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(revision)
        return 0

    if not args.path or not args.branch:
        missing = []
        if not args.path:
            missing.append("--path")
        if not args.branch:
            missing.append("--branch")
        raise SystemExit(f"Missing required arguments for worktree creation: {', '.join(missing)}")

    # Claim metadata is consumed only by verify_scoped_write_claim, which runs
    # only under --require-write-claim. Accepting these flags without it silently
    # discarded them, so a caller who supplied claim identity and write paths got
    # an UNCLAIMED worktree while believing it was claimed -- and the JSON reports
    # coordination_checked: false, which reads as "the check ran and found nothing"
    # rather than "no check was requested". Three unclaimed lanes were created that
    # way on 2026-09-08 across two repositories before anyone read this function.
    supplied_claim_flags = [
        name
        for name, value in (
            ("--claim-agent", args.claim_agent),
            ("--claim-project", args.claim_project),
            ("--claim-write-path", args.claim_write_path),
            ("--claim-start-revision", args.claim_start_revision),
        )
        if value
    ]
    if supplied_claim_flags and not args.require_write_claim:
        raise SystemExit(
            "Refusing to create an unclaimed worktree while claim metadata was "
            f"supplied: {', '.join(supplied_claim_flags)}. These are read only under "
            "--require-write-claim, so without it they would be discarded and the "
            "worktree would carry no claim. Add --require-write-claim to enforce the "
            "claim, or drop the claim flags to state plainly that this lane is "
            "unclaimed. Prefer the repository's own entry point (`make worktree` / "
            "`make maintenance-worktree`), which passes --require-write-claim for you."
        )

    worktree_path = Path(args.path).expanduser().resolve()
    claims_dir = Path(args.claims_dir).expanduser().resolve() if args.claims_dir else None
    marker: Path | None = None
    try:
        marker = write_provisioning_marker(worktree_path=worktree_path, branch=args.branch)
        result = create_worktree(
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=args.branch,
            start_point=args.start_point,
            split_brain_threshold=args.split_brain_threshold,
            keep_failed_worktree=args.keep_failed_worktree,
            require_write_claim=args.require_write_claim,
            claim_agent=args.claim_agent,
            claim_project=args.claim_project,
            claim_write_paths=args.claim_write_path,
            claims_dir=claims_dir,
            require_clean_main_root=args.require_clean_main_root,
            claim_start_revision=args.claim_start_revision,
            allow_stale_start_point=args.allow_stale_start_point,
        )
    except (RuntimeError, ValueError) as exc:
        error_result = WorktreeCreationResult(
            ok=False,
            repo_root=str(repo_root),
            worktree_path=str(worktree_path),
            branch=args.branch,
            created_branch=False,
            classification="error",
            cleanup_performed=False,
            message=str(exc),
            status=None,
            coordination_checked=args.require_write_claim,
            coordination_message=None,
        )
        if args.json:
            print(json.dumps(asdict(error_result), indent=2))
        else:
            _print_human(error_result)
        return 1
    finally:
        if marker is not None:
            clear_provisioning_marker(marker)

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        _print_human(result)

    if result.ok:
        _lock_canonical_checkout(repo_root, as_json=args.json)

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
