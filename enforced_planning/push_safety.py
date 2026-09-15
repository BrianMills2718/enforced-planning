"""Pre-push coordination checks for governed worktree branches.

The push gate exists to keep publish actions aligned with the coordination
layer. It blocks obvious unsafe cases mechanically and surfaces softer
coordination context for human review before shared state changes.
"""

from __future__ import annotations

import importlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from enforced_planning import coordination_claims
from enforced_planning.worktree_paths import resolve_canonical_repo_root


@dataclass(frozen=True)
class PushCheckFinding:
    """One push-safety issue or warning with enough detail to act on it."""

    code: str
    message: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for CLI and tests."""

        return asdict(self)


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one git command inside the repo and capture the result."""

    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _git_stdout(repo_root: Path, args: list[str]) -> str:
    """Return stdout for one successful git command or fail loudly."""

    result = _run_git(repo_root, args)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def resolve_repo_root(start_path: str | Path = ".") -> Path:
    """Resolve the canonical git toplevel for the current repo."""

    start = Path(start_path).resolve()
    return Path(_git_stdout(start, ["rev-parse", "--show-toplevel"]))


def resolve_default_branch(repo_root: Path) -> str | None:
    """Resolve the repo's default branch from local refs and origin/HEAD."""

    remote_head = _run_git(repo_root, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])
    if remote_head.returncode == 0:
        value = remote_head.stdout.strip()
        if value.startswith("origin/"):
            return value.split("/", 1)[1]
        if value:
            return value
    for candidate in ("main", "master"):
        exists = _run_git(repo_root, ["show-ref", "--verify", f"refs/heads/{candidate}"])
        if exists.returncode == 0:
            return candidate
    return None


def current_branch(repo_root: Path) -> str:
    """Return the current symbolic branch name or fail on detached HEAD."""

    branch = _run_git(repo_root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    if branch.returncode != 0:
        raise RuntimeError("Detached HEAD is not eligible for push-check.")
    value = branch.stdout.strip()
    if not value:
        raise RuntimeError("Unable to resolve current branch name.")
    return value


def current_upstream(repo_root: Path) -> str | None:
    """Return the configured upstream for HEAD when one exists."""

    upstream = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    if upstream.returncode != 0:
        return None
    value = upstream.stdout.strip()
    return value or None


def ahead_behind(repo_root: Path, upstream_ref: str) -> tuple[int, int]:
    """Return ahead/behind counts for HEAD relative to its upstream."""

    counts = _git_stdout(repo_root, ["rev-list", "--left-right", "--count", f"{upstream_ref}...HEAD"])
    behind_text, ahead_text = counts.split()
    return int(ahead_text), int(behind_text)


def changed_paths_since_default(repo_root: Path, default_branch: str) -> list[str]:
    """Return repo-relative paths changed on this branch against default."""

    remote_default = f"refs/remotes/origin/{default_branch}"
    remote_exists = _run_git(repo_root, ["show-ref", "--verify", remote_default])
    default_ref = remote_default if remote_exists.returncode == 0 else f"refs/heads/{default_branch}"
    base = _git_stdout(repo_root, ["merge-base", "HEAD", default_ref])
    diff = _git_stdout(repo_root, ["diff", "--name-only", f"{base}..HEAD"])
    if not diff:
        return []
    return [coordination_claims._normalize_repo_path(line) for line in diff.splitlines() if line.strip()]


def _working_tree_dirty(repo_root: Path) -> bool:
    """Return whether tracked content could make the published delta ambiguous."""

    return (
        _run_git(repo_root, ["diff", "--quiet"]).returncode != 0
        or _run_git(repo_root, ["diff", "--cached", "--quiet"]).returncode != 0
    )


def _branch_claims(project: str, branch: str) -> list[coordination_claims.ClaimRecord]:
    """Return live claims attached to one project branch."""

    return [
        claim
        for claim in coordination_claims.check_claims(project)
        if claim.branch == branch
    ]


def _healthy_branch_claims(
    claims: list[coordination_claims.ClaimRecord],
) -> list[coordination_claims.ClaimRecord]:
    """Return branch claims that still confer live push ownership.

    A stalled progress lease is report-only: it requests advancement or
    handoff but does not revoke claim ownership.
    """

    return [
        claim
        for claim in claims
        if coordination_claims.claim_runtime_status(claim) in {"healthy", "stalled"}
    ]


def _extract_json_block(raw_text: str) -> str:
    """Strip CLI noise before the first JSON token so parsing stays deterministic."""

    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            return stripped
    return raw_text


def load_active_decisions(project: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Read active architectural decisions from agent_memory as raw JSON."""

    result = subprocess.run(
        [
            "agent-memory",
            "recall",
            "active decisions",
            "--project",
            project,
            "--raw",
            "--limit",
            str(limit),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "agent-memory recall failed")
    payload = _extract_json_block(result.stdout.strip())
    if not payload:
        return []
    decoded = json.loads(payload)
    if not isinstance(decoded, list):
        raise RuntimeError("agent-memory recall --raw must return a JSON array")
    return [item for item in decoded if isinstance(item, dict)]


def _claim_overlap_for_paths(
    changed_paths: list[str],
    claim: coordination_claims.ClaimRecord,
) -> list[str]:
    """Return normalized changed-path overlaps against one active claim.

    Append-only stores are excluded on both sides, exactly as claim-vs-claim
    evaluation excludes them. Each lane creates its own immutable file there,
    so publishing one is not contention with a lane that declared the store.
    Without this the exemption existed at claim creation and vanished at push,
    which let a lane be created and then refused publication of its own entry.
    """

    overlaps: list[str] = []
    for changed_path in changed_paths:
        for write_path in claim.write_paths:
            if not coordination_claims._paths_overlap(changed_path, write_path):
                continue
            if coordination_claims._is_append_only_path(
                changed_path
            ) and coordination_claims._is_append_only_path(write_path):
                continue
            overlaps.append(f"{changed_path} <-> {write_path}")
    return sorted(set(overlaps))


def _predicts_clean_merge(repo_root: Path, ref_a: str, ref_b: str) -> bool | None:
    """Predict whether the eventual integration of ref_a and ref_b would conflict.

    `git merge-tree --write-tree` simulates a three-way merge with no side
    effects (no working-tree change, no new commit, no ref update), so this is
    safe to run purely for prediction. Returns True for a clean predicted
    merge, False for a predicted real conflict, and None when the prediction
    itself could not be made (for example `ref_b` no longer resolves, because
    its owning worktree/branch was removed). Callers must treat None as
    "unknown," not as license to relax the existing conservative behavior --
    fail closed on the unknown case, exactly as an unresolved-details case
    elsewhere in this module keeps blocking rather than guessing.
    """

    if _run_git(repo_root, ["rev-parse", "--verify", "--quiet", ref_b]).returncode != 0:
        return None
    result = _run_git(repo_root, ["merge-tree", "--write-tree", ref_a, ref_b])
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    return None


def _is_overbroad_undeclared_claim(claim: "coordination_claims.ClaimRecord") -> bool:
    """True when a claim holds the whole repository without deliberately reserving it.

    A `bounded` broad scope is a deliberate reservation and still blocks. A
    `bootstrap` scope is a lane that has not narrowed yet, and an unclassified one
    is legacy: in both cases the owner declared no paths, so treating the overlap
    as a hard conflict blocks work over a scope nobody chose.
    """
    if claim.write_paths not in (["."], ["./"]):
        return False
    if claim.broad_scope_mode == "bounded":
        return False
    return True


def _is_same_session_default_integration(
    repo_root: Path,
    *,
    canonical_repo_root: Path,
    resolved_branch: str,
    default_branch: str,
    changed_paths: list[str],
    claim: coordination_claims.ClaimRecord,
) -> bool:
    """Return whether HEAD safely contains one current-session source lane.

    The source claim must remain live until its integration is published.  A
    default-branch push may therefore overlap that claim only when native
    runtime identity proves the same owner, the claimed branch is already an
    ancestor of HEAD, and HEAD has not changed any claimed path after that
    branch tip.
    """

    if resolved_branch != default_branch or not claim.branch or not claim.session_id:
        return False
    if not claim.repo_root or Path(claim.repo_root).expanduser().resolve() != canonical_repo_root:
        return False
    if coordination_claims.resolve_session_id(claim.agent) != claim.session_id:
        return False
    claim_ref = f"refs/heads/{claim.branch}"
    if _run_git(repo_root, ["show-ref", "--verify", claim_ref]).returncode != 0:
        return False
    if _run_git(repo_root, ["merge-base", "--is-ancestor", claim_ref, "HEAD"]).returncode != 0:
        return False
    claimed_changed_paths = sorted(
        path
        for path in changed_paths
        if any(coordination_claims._paths_overlap(path, write_path) for write_path in claim.write_paths)
    )
    if not claimed_changed_paths:
        return False
    return (
        _run_git(repo_root, ["diff", "--quiet", claim_ref, "HEAD", "--", *claimed_changed_paths]).returncode
        == 0
    )


def evaluate_push_safety(
    repo_root: str | Path = ".",
    *,
    project: str | None = None,
    branch: str | None = None,
    include_active_decisions: bool = False,
    fail_on_active_decisions: bool = False,
) -> dict[str, Any]:
    """Evaluate whether the current branch is safe to push as-is."""

    resolved_repo_root = resolve_repo_root(repo_root)
    canonical_repo_root = resolve_canonical_repo_root(resolved_repo_root)
    resolved_project = project or canonical_repo_root.name
    resolved_branch = branch or current_branch(resolved_repo_root)
    default_branch = resolve_default_branch(resolved_repo_root)
    if not default_branch:
        raise RuntimeError("Unable to resolve the default branch for push-check.")

    issues: list[PushCheckFinding] = []
    warnings: list[PushCheckFinding] = []
    live_write_overlap_paths: set[str] = set()
    integration_owners: set[tuple[str, str]] = set()

    if _working_tree_dirty(resolved_repo_root):
        issues.append(
            PushCheckFinding(
                code="dirty_worktree",
                message="Push-check requires a clean working tree so the published delta is unambiguous.",
                details={},
            )
        )

    if resolved_branch == default_branch:
        warnings.append(
            PushCheckFinding(
                code="default_branch_push",
                message=(
                    "Direct default-branch pushes require repository governance that permits "
                    "recoverable Git publication; this generic coordination check cannot establish ownership."
                ),
                details={"branch": resolved_branch, "default_branch": default_branch},
            )
        )

    branch_claims = _branch_claims(resolved_project, resolved_branch)
    if not branch_claims:
        findings = warnings if resolved_branch == default_branch else issues
        findings.append(
            PushCheckFinding(
                code="missing_branch_claim",
                message=(
                    "No live coordination claim is attached to the default branch; "
                    "verify that the published integration came from a claimed lane."
                    if resolved_branch == default_branch
                    else "No live coordination claim is attached to the current branch."
                ),
                details={"branch": resolved_branch, "project": resolved_project},
            )
        )
    elif not _healthy_branch_claims(branch_claims):
        causes = sorted(
            {
                issue
                for claim in branch_claims
                for issue in (
                    coordination_claims.claim_lifecycle_issues(claim)
                    + coordination_claims.claim_health_issues(claim)
                    + coordination_claims.claim_liveness_issues(claim)
                    + coordination_claims.claim_progress_issues(claim)
                )
            }
        )
        issues.append(
            PushCheckFinding(
                code="no_healthy_branch_claim",
                message=(
                    "The current branch has no healthy or report-only stalled canonical "
                    "claim with complete session identity. Resume or recreate the lane before pushing."
                    + (f" Claim issues: {', '.join(causes)}." if causes else "")
                ),
                details={
                    "branch": resolved_branch,
                    "project": resolved_project,
                    "claims": [
                        {
                            "scope": claim.scope,
                            "session_id": claim.session_id,
                            "session_name": claim.session_name,
                            "lifecycle_issues": coordination_claims.claim_lifecycle_issues(claim),
                            "health_issues": coordination_claims.claim_health_issues(claim),
                            "liveness_issues": coordination_claims.claim_liveness_issues(claim),
                            "progress_issues": coordination_claims.claim_progress_issues(claim),
                        }
                        for claim in branch_claims
                    ],
                },
            )
        )

    upstream = current_upstream(resolved_repo_root)
    ahead = 0
    behind = 0
    if upstream is None:
        warnings.append(
            PushCheckFinding(
                code="missing_upstream",
                message="Current branch has no upstream; first push will establish the remote tracking branch.",
                details={"branch": resolved_branch},
            )
        )
    else:
        ahead, behind = ahead_behind(resolved_repo_root, upstream)
        if behind > 0:
            issues.append(
                PushCheckFinding(
                    code="behind_upstream",
                    message="Local branch is behind its upstream; reconcile before pushing new commits.",
                    details={"branch": resolved_branch, "upstream": upstream, "behind": behind},
                )
            )

    changed_paths = changed_paths_since_default(resolved_repo_root, default_branch)
    if not changed_paths:
        warnings.append(
            PushCheckFinding(
                code="no_branch_delta",
                message="Current branch has no file delta relative to the default branch.",
                details={"branch": resolved_branch, "default_branch": default_branch},
            )
        )

    for claim in coordination_claims.check_claims(resolved_project):
        if claim.branch == resolved_branch:
            continue
        overlaps = _claim_overlap_for_paths(changed_paths, claim)
        if not overlaps:
            continue
        claim_details = {
            "other_agent": claim.agent,
            "other_scope": claim.scope,
            "other_branch": claim.branch,
            "other_claim_type": claim.claim_type,
            "other_session_id": claim.session_id,
            "other_contact_ref": claim.contact_ref,
            "overlaps": overlaps,
            "source_file": claim.source_file,
        }
        runtime_status = coordination_claims.claim_runtime_status(claim)
        if runtime_status == "stale":
            warnings.append(
                PushCheckFinding(
                    code="stale_overlapping_claim",
                    message="A stale overlapping claim still exists; prune or resolve it before treating the registry as clean.",
                    details=claim_details,
                )
            )
            continue
        if claim.claim_type in {"write", "program"} and claim.write_paths:
            if runtime_status in {"healthy", "stalled"} and _is_same_session_default_integration(
                resolved_repo_root,
                canonical_repo_root=canonical_repo_root,
                resolved_branch=resolved_branch,
                default_branch=default_branch,
                changed_paths=changed_paths,
                claim=claim,
            ):
                warnings.append(
                    PushCheckFinding(
                        code="same_session_integrated_claim",
                        message=(
                            "The current native session still owns this source claim, and its branch is "
                            "integrated without later changes to the claimed paths."
                        ),
                        details=claim_details,
                    )
                )
                continue
            # An overbroad claim is one whose owner never declared these paths: it
            # holds the whole repository because a scope was omitted, not chosen.
            # coordination_claims already tells these apart from a deliberate
            # bounded reservation and the distinction was computed, stored, printed
            # and read by nothing, so a seven-hour lockout on 2026-09-08 was
            # enforced with the same weight as a real conflict. Blocking on
            # undeclared scope is what caused the harm, so it warns instead.
            if _is_overbroad_undeclared_claim(claim):
                warnings.append(
                    PushCheckFinding(
                        code="overbroad_overlapping_claim",
                        message=(
                            "Changed files overlap a claim that holds the whole repository without "
                            "declaring these paths. Its owner has not reserved them deliberately, so "
                            "this is a warning rather than a block; coordinate before writing shared files."
                        ),
                        details=claim_details,
                    )
                )
                continue
            # A declared write_paths overlap is a metadata-level signal, not
            # proof the two branches actually collide: two lanes can each
            # append a different, non-overlapping line to the same file (a
            # table, a log) and integrate cleanly. `git merge-tree` simulates
            # the eventual three-way merge with no side effects and tells us
            # whether it would really conflict. Predicted-clean overlaps warn
            # instead of blocking, so a real conflict is not serialized away
            # to something git itself would reconcile without help.
            #
            # Scoped to non-default-branch pushes only. A default-branch push
            # is a real integration, and an overlapping claim there is an
            # ownership/identity question (who is allowed to publish this),
            # not a content-conflict question -- see
            # _is_same_session_default_integration just above, which already
            # owns that case. Predicting a merge between HEAD and a claim's
            # branch is also close to tautological once that branch is an
            # ancestor of the current default-branch HEAD (the common case
            # here): it is trivially "clean" by construction, which would
            # silently defeat the ownership check this exists to preserve
            # rather than duplicate.
            #
            # A claim with no branch, or whose branch no longer resolves,
            # cannot be simulated -- that stays a hard block, the same
            # conservative default as before this check existed.
            if resolved_branch != default_branch and claim.branch:
                predicted_clean = _predicts_clean_merge(
                    resolved_repo_root, resolved_branch, claim.branch
                )
                if predicted_clean:
                    warnings.append(
                        PushCheckFinding(
                            code="overlapping_write_claim_predicted_clean",
                            message=(
                                "Changed files overlap another live claim's declared write ownership, "
                                "but a merge-tree simulation predicts no actual content conflict. "
                                "Warning instead of blocking; re-check if the other lane's content "
                                "changes before you integrate."
                            ),
                            details=claim_details,
                        )
                    )
                    continue
            live_write_overlap_paths.update(
                overlap.split(" <-> ", 1)[0] for overlap in overlaps
            )
            integration_owners.add((claim.agent, claim.scope))
            # A real predicted conflict lands here with the colliding
            # ClaimRecord already in hand -- session_id and branch included.
            # Blocking the pusher without telling the other lane's owner is
            # only half the fix: they cannot act on a conflict they never
            # hear about. `concern_routing.route_concern` already does this
            # exact delivery (PR comment if one exists, else the durable
            # coordination mailbox) and needs only the identifiers this loop
            # already has. This must never change whether the push blocks --
            # a delivery failure (stale recipient past the mailbox's 24h
            # reachability window, a transient `gh`/filesystem error) is
            # recorded on the finding and swallowed, not raised.
            notification: dict[str, Any] = {"attempted": False}
            if claim.branch and branch_claims:
                notification["attempted"] = True
                try:
                    # Imported by module name, not `from enforced_planning
                    # import concern_routing`: concern_routing.py ships only
                    # in the broader COORDINATION_MESSAGES installer profile,
                    # not the narrower CLAIM_PROJECTION one that also ships
                    # this file. A literal import statement would make
                    # scripts/check_facade_sync_completeness.py's static
                    # import-graph walk treat it as a hard requirement of
                    # every profile shipping push_safety.py; this is a
                    # best-effort capability instead, and the except clause
                    # below already covers it being absent (ModuleNotFoundError).
                    concern_routing = importlib.import_module(
                        "enforced_planning.concern_routing"
                    )

                    overlapping_paths = sorted(
                        overlap.split(" <-> ", 1)[0] for overlap in overlaps
                    )
                    pusher_claim = branch_claims[0]
                    route = concern_routing.route_concern(
                        repo_root=resolved_repo_root,
                        agent=pusher_claim.agent,
                        project=resolved_project,
                        target_branch=claim.branch,
                        recipient=claim.session_id,
                        subject=(
                            f"Push blocked: `{resolved_branch}` overlaps your claim "
                            f"`{claim.scope}` on `{claim.branch}`"
                        ),
                        content=(
                            f"Branch `{resolved_branch}` (claim `{pusher_claim.scope}`, "
                            f"session `{pusher_claim.session_id}`) tried to push changes "
                            "overlapping your live write claim on:\n"
                            + "\n".join(f"- {path}" for path in overlapping_paths)
                            + "\n\nThe push was blocked pending resolution."
                        ),
                        idempotency_key=(
                            "overlapping_write_claim:"
                            + "|".join([resolved_branch, claim.scope, *overlapping_paths])
                        ),
                    )
                    notification["ok"] = True
                    notification["route"] = route.get("route")
                    notification["destination"] = route.get("destination")
                except Exception as exc:  # noqa: BLE001 - notify best-effort, block always stands
                    notification["ok"] = False
                    notification["error"] = f"{type(exc).__name__}: {exc}"
            claim_details["notification"] = notification
            issues.append(
                PushCheckFinding(
                    code="overlapping_write_claim",
                    message=(
                        "Changed files overlap another live claim with write ownership. Publication is "
                        "waiting on those paths; this is not evidence that the whole goal "
                        "is blocked. Its owner's session_id is in `other_session_id`; if the claim "
                        "declared `contact_ref`, that peer-messaging identity is in `other_contact_ref` "
                        "-- check `ListAgents` for a matching entry before treating the owner as "
                        "unreachable."
                    ),
                    details=claim_details,
                )
            )
            continue
        if claim.claim_type == "review":
            warnings.append(
                PushCheckFinding(
                    code="overlapping_review_claim",
                    message="Changed files overlap an active review claim.",
                    details=claim_details,
                )
            )

    active_decisions = (
        load_active_decisions(resolved_project)
        if include_active_decisions or fail_on_active_decisions
        else []
    )
    if active_decisions:
        decision_finding = PushCheckFinding(
            code="active_decisions_present",
            message="Active architectural decisions exist for this repo; review them before publishing.",
            details={"decision_count": len(active_decisions), "records": active_decisions},
        )
        if fail_on_active_decisions:
            issues.append(decision_finding)
        else:
            warnings.append(decision_finding)

    blocked_paths = sorted(live_write_overlap_paths)
    writable_paths = sorted(path for path in changed_paths if path not in live_write_overlap_paths)
    if blocked_paths and writable_paths:
        recommended_next_action = (
            "Split or defer the blocked paths, publish a claim-compatible checkpoint, "
            "and continue another authorized ready work unit."
        )
    elif blocked_paths:
        recommended_next_action = (
            "This branch publication is path-blocked. Preserve the checkpoint and move "
            "to another authorized ready work unit; report the whole goal blocked only "
            "after evaluating its complete ready queue."
        )
    else:
        recommended_next_action = "Proceed with normal push-safety handling."

    return {
        "ok": not issues,
        "repo_root": str(resolved_repo_root),
        "project": resolved_project,
        "branch": resolved_branch,
        "default_branch": default_branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "changed_paths": changed_paths,
        "branch_claim_count": len(branch_claims),
        "continuation": {
            "state": "integration_wait" if blocked_paths else "ready",
            "goal_blocked": False,
            "blocked_paths": blocked_paths,
            "writable_paths": writable_paths,
            "integration_owners": [
                {"agent": agent, "scope": scope}
                for agent, scope in sorted(integration_owners)
            ],
            "recommended_next_action": recommended_next_action,
        },
        "issues": [item.to_dict() for item in issues],
        "warnings": [item.to_dict() for item in warnings],
    }
