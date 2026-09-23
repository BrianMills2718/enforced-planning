#!/usr/bin/env python3
"""Orchestrate governed-repo upgrades across the fleet.

Reads ``governed_repos.yaml`` and runs the install + audit pipeline for each
repo. Composes the existing primitives:

    1. Load registry entry from governed_repos.yaml
    2. Verify repo is eligible (exists, no local dirt in --write mode)
    3. Run ``scripts/install_governed_repo.py --write`` (or --dry-run)
    4. Run ``scripts/audit_governed_repo.py --strict-governed``
    5. Emit a per-repo upgrade report

Usage::

    # Preview what would change — never modifies files
    python scripts/upgrade_governed_repos.py --registry governed_repos.yaml --dry-run

    # Sync one repo through its own claimed linked worktree: creates the
    # worktree via `make maintenance-worktree`, runs install --write + audit
    # inside it (never the primary checkout), and pushes a branch/PR if the
    # sync produced a diff. Never merges. --repo is mandatory for --write --
    # this slice is intentionally one repo at a time (see "Minimal First
    # Slice" in the design doc); batch write-mode is a later slice.
    python scripts/upgrade_governed_repos.py --registry governed_repos.yaml --repo llm_client --write

    # Output machine-readable report
    python scripts/upgrade_governed_repos.py --registry governed_repos.yaml --dry-run --json

Design: docs/designs/GOVERNED_REPO_UPGRADE_AUTOMATION.md
Plan: docs/plans/51_upgrade-automation-implementation-and-write-mode-rollout.md
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = FRAMEWORK_ROOT / "scripts" / "install_governed_repo.py"
AUDIT_SCRIPT = FRAMEWORK_ROOT / "scripts" / "audit_governed_repo.py"
CLAIM_BOOTSTRAP_SCRIPT = FRAMEWORK_ROOT / "scripts" / "claim_bootstrap.py"
SESSION_NARROW_SCRIPT = FRAMEWORK_ROOT / "scripts" / "session_narrow.py"

sys.path.insert(0, str(FRAMEWORK_ROOT))
from enforced_planning import coordination_claims, session_contracts  # noqa: E402


def _repair_missing_plan_ref(*, agent: str, project: str, scope: str) -> None:
    """Fix a claim's `plan_ref: null` in place if the target repo's own
    installed Makefile is too old to set it itself.

    `make maintenance-worktree`/`worktree` in a target repo run *that repo's
    own* vendored Makefile and coordination_claims copy, not this repo's
    current one -- the whole reason the sync exists is that copy may be old.
    Consumer Makefiles observed missing the `ALLOW_UNPLANNED -> --plan
    UNPLANNED` fallback at the initial --claim step (orgchart, llm_client,
    2026-09-02, fixed at the source in enforced-planning#388) produce a claim
    with `plan_ref: null`, which later fails push-check with
    `no_healthy_branch_claim`. Fixing the template does not retroactively fix
    a claim a stale copy already created; repair it here, using this
    (current, canonical) coordination_claims module, so write-mode does not
    depend on the target repo's own tooling being current -- the one
    invariant it cannot assume, by construction.
    """

    claim_path = coordination_claims.CLAIMS_DIR / coordination_claims._claim_filename(agent, project, scope)
    with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
        if not claim_path.is_file():
            return
        payload = yaml.safe_load(claim_path.read_bytes())
        if not isinstance(payload, dict) or payload.get("plan_ref"):
            return
        payload["plan_ref"] = session_contracts.UNPLANNED_PLAN_REF
        claim_path.write_text(yaml.safe_dump(payload, default_flow_style=False, sort_keys=False), encoding="utf-8")


@dataclass
class RepoUpgradeResult:
    """Per-repo result from an upgrade run."""

    repo_id: str
    repo_root: Path
    tier: str
    skipped: bool = False
    skip_reason: str = ""
    install_rc: int = -1
    install_stdout: str = ""
    install_stderr: str = ""
    audit_rc: int = -1
    audit_stdout: str = ""
    audit_stderr: str = ""
    classification: str = "unknown"
    blockers: list[str] = field(default_factory=list)
    # write-mode only
    branch: str = ""
    had_diff: bool = False
    pr_url: str = ""
    write_error: str = ""

    @property
    def success(self) -> bool:
        if self.skipped:
            return False
        if self.write_error:
            return False
        return self.install_rc == 0 and self.audit_rc == 0

    def summary_line(self) -> str:
        if self.skipped:
            return f"  SKIP  {self.repo_id}: {self.skip_reason}"
        if self.write_error:
            return f"  FAIL  {self.repo_id}: {self.write_error}"
        status = "OK  " if self.success else "FAIL"
        tail = ""
        if self.pr_url:
            tail = f" -> {self.pr_url}"
        elif self.branch and not self.had_diff:
            tail = " (already in sync, no PR needed)"
        return f"  {status}  {self.repo_id} [{self.classification}]{tail}"


def _expand(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _has_local_dirt(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _single_line(text: str, limit: int) -> str:
    """Collapse to one line for safe embedding as a Makefile recipe argument.

    A multi-line value (e.g. captured subprocess stderr) breaks Make's
    `"$(VAR)"` recipe-line expansion once it contains an embedded newline --
    the shell sees the rest as separate commands. Found live: this silently
    made the session-close retry after an abandoned write never actually run.
    """
    return " ".join(text.split())[:limit]


def _native_agent() -> str:
    """Return the one agent identity proved by this process environment."""

    detected = [
        agent
        for agent, env_key in coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS.items()
        if os.environ.get(env_key, "").strip()
    ]
    if len(detected) != 1:
        raise ValueError(f"write-mode requires exactly one native agent runtime marker; detected {len(detected)}")
    return detected[0]


def _source_revision_tag() -> str:
    """Return a stable revision tag so retained trackers never block retries."""

    resolved = subprocess.run(
        ["git", "-C", str(FRAMEWORK_ROOT), "rev-parse", "--short=12", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    revision = resolved.stdout.strip()
    if resolved.returncode != 0 or not revision:
        raise ValueError("unable to resolve the canonical enforced-planning source revision")
    return revision


def write_repo(
    repo_id: str,
    repo_root: Path,
    tier: str,
    owner: str,
    *,
    authorized_owners: frozenset[str] = frozenset({"brian"}),
    github_cli: str = "gh",
) -> RepoUpgradeResult:
    """Sync one repo through its own claimed linked worktree.

    Never touches repo_root's primary checkout. Sequence:
      1. `make maintenance-worktree` in repo_root creates a claimed branch +
         worktree via that repo's own sanctioned entrypoint (installed by
         install_governed_repo.py, so every eligible repo already has it).
      2. install_governed_repo.py --write, then audit_governed_repo.py
         --strict-governed, both run *inside the worktree*.
      3. If the worktree has no diff, the sync was a no-op: close the lane
         with disposition=merged (nothing unique) and report "already in
         sync." If it has a diff, commit + push + open a PR. Never merges.
      4. On any failure, abandon the worktree (`make worktree-remove`) rather
         than leave partial state or touch the primary checkout.
    """
    result = RepoUpgradeResult(repo_id=repo_id, repo_root=repo_root, tier=tier)

    if owner and owner not in authorized_owners:
        result.skipped = True
        result.skip_reason = (
            f"owner={owner!r}: write-mode for a non-Brian-owned repo needs its own "
            "explicit authorization, not blanket fleet write-mode. Pass "
            f"--authorize-owner {owner} only when that authority exists."
        )
        return result

    if not repo_root.exists():
        result.skipped = True
        result.skip_reason = f"repo root does not exist: {repo_root}"
        return result

    if not (repo_root / "Makefile").exists():
        result.skipped = True
        result.skip_reason = "no Makefile -- cannot use the sanctioned maintenance-worktree entrypoint"
        return result

    try:
        native_agent = _native_agent()
    except ValueError as exc:
        result.write_error = str(exc)
        return result

    try:
        source_revision = _source_revision_tag()
    except ValueError as exc:
        result.write_error = str(exc)
        return result
    attempt = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S%f")
    branch = f"sync-enforced-planning-{attempt}-{source_revision}"
    result.branch = branch
    worktree_path = repo_root / "worktrees" / branch

    makefile_text = (repo_root / "Makefile").read_text(encoding="utf-8", errors="ignore")
    task = "Sync installer-declared coordination consumer files from canonical enforced-planning"
    goal = "Close installer-declared drift from canonical enforced-planning"
    # Named, not ".": the actual directories install_governed_repo.py's
    # closure writes to. A repo whose Makefile requires an explicit narrow
    # scope (some do -- SESSION_WRITE_PATHS_REQUIRED-style policy) rejects a
    # bootstrap "." claim outright, and this is genuinely what gets touched.
    write_path_list = [
        "enforced_planning/coordination_claims.py",
        "scripts/meta/check_coordination_claims.py",
    ]
    write_paths = " ".join(write_path_list)
    bootstrap_requires_narrowing = True
    if "\nmaintenance-worktree:" in makefile_text or makefile_text.startswith("maintenance-worktree:"):
        # Bootstrap with the temporary whole-repository authority every
        # supported maintenance wrapper understands. The claim is narrowed to
        # the exact installer closure below before install --write can run.
        make_cmd = [
            "make",
            "-C",
            str(repo_root),
            "maintenance-worktree",
            f"BRANCH={branch}",
            f"TASK={task}",
            f"SESSION_GOAL={goal}",
            "SESSION_PHASE=sync",
            f"WORKTREE_AGENT={native_agent}",
            "SESSION_ALLOW_PARALLEL=1",
            "SESSION_WRITE_PATHS=.",
        ]
    elif "\nworktree:" in makefile_text or makefile_text.startswith("worktree:"):
        # Older installs may expose only the base target. Its whole-repository
        # bootstrap follows the same narrow-before-write contract.
        make_cmd = [
            "make",
            "-C",
            str(repo_root),
            "worktree",
            f"BRANCH={branch}",
            f"TASK={task}",
            f"SESSION_GOAL={goal}",
            "SESSION_PHASE=sync",
            f"WORKTREE_AGENT={native_agent}",
            "SESSION_ALLOW_PARALLEL=1",
            "ALLOW_UNPLANNED=1",
            "SESSION_WRITE_PATHS=.",
        ]
    else:
        # Some legacy governed consumers predate both Make entrypoints. Use
        # the current atomic transaction as the documented isolated fallback,
        # starting with the final two-file authority so unrelated owners do
        # not become blockers merely because an intermediate broad claim was
        # needed for older wrappers.
        request = {
            "schema_version": "1.0",
            "operation": "maintenance_worktree",
            "agent": native_agent,
            "project": repo_id,
            "scope": branch,
            "repo_root": str(repo_root),
            "branch": branch,
            "claim_type": "program",
            "write_paths": write_path_list,
        }
        make_cmd = [
            sys.executable,
            str(CLAIM_BOOTSTRAP_SCRIPT),
            "--request-json",
            json.dumps(request, separators=(",", ":")),
        ]
        bootstrap_requires_narrowing = False
    make_proc = _run(make_cmd, cwd=repo_root if not bootstrap_requires_narrowing else None)
    make_output = "\n".join(part for part in (make_proc.stdout, make_proc.stderr) if part).strip()
    if (
        make_proc.returncode != 0
        and "broad_scope_mode_required" in make_output
        and "broad_scope_reason_required" in make_output
        and ("\nworktree:" in makefile_text or makefile_text.startswith("worktree:"))
        and not worktree_path.exists()
    ):
        make_cmd = [
            "make",
            "-C",
            str(repo_root),
            "worktree",
            f"BRANCH={branch}",
            f"TASK={task}",
            f"SESSION_GOAL={goal}",
            "SESSION_PHASE=sync",
            f"WORKTREE_AGENT={native_agent}",
            "SESSION_ALLOW_PARALLEL=1",
            "ALLOW_UNPLANNED=1",
            "SESSION_BROAD_SCOPE_MODE=bootstrap",
            "SESSION_BROAD_SCOPE_REASON=construct fleet sync lane then narrow before installer mutation",
            f"SESSION_TARGET_WORKTREE_PATH={worktree_path}",
            "SESSION_WRITE_PATHS=.",
        ]
        make_proc = _run(make_cmd)
        make_output = "\n".join(part for part in (make_proc.stdout, make_proc.stderr) if part).strip()
    if (
        make_proc.returncode != 0
        and "Plan-start gate failed: coordinated work requires a qualified plan identity" in make_output
        and not worktree_path.exists()
    ):
        # Some governed repos have an intermediate-generation base `worktree`
        # target: it accepts the broad-scope bootstrap metadata but rejects an
        # unplanned maintenance lane at its plan gate. Use the current atomic
        # bootstrap transaction to cross that version-skew boundary. This is
        # not a raw Git escape hatch: the transaction independently verifies
        # repository authority, native-session ownership, claim availability,
        # fresh remote default, tracker creation, and worktree creation. The
        # broad claim is still narrowed below before installer mutation.
        request = {
            "schema_version": "1.0",
            "operation": "maintenance_worktree",
            "agent": native_agent,
            "project": repo_id,
            "scope": branch,
            "repo_root": str(repo_root),
            "branch": branch,
            "claim_type": "program",
            "write_paths": ["."],
        }
        make_proc = _run(
            [
                sys.executable,
                str(CLAIM_BOOTSTRAP_SCRIPT),
                "--request-json",
                json.dumps(request, separators=(",", ":")),
            ],
            cwd=repo_root,
        )
        make_output = "\n".join(part for part in (make_proc.stdout, make_proc.stderr) if part).strip()
    if make_proc.returncode != 0:
        result.write_error = f"make maintenance-worktree failed: {make_output[:1000]}"
        return result

    if not worktree_path.exists():
        result.write_error = f"maintenance-worktree reported success but {worktree_path} does not exist"
        return result

    _repair_missing_plan_ref(agent=native_agent, project=repo_id, scope=branch)

    def _abandon(reason: str) -> None:
        result.write_error = reason
        # session-close refuses to touch a dirty worktree at all (not even
        # with WORKTREE_ALLOW_DISCARD_UNIQUE, which governs unique *commits*,
        # not uncommitted working-tree state). A failure between install
        # --write and the eventual commit (e.g. a repo-local pre-commit hook
        # rejecting the sync) leaves real uncommitted output sitting there.
        # Stash it -- never discard -- so a human can recover exactly what
        # the sync produced, then close cleanly.
        status = _run(["git", "status", "--porcelain"], cwd=worktree_path)
        if status.stdout.strip():
            _run(
                ["git", "stash", "push", "-u", "-m", f"upgrade_governed_repos.py --write abandoned: {reason[:150]}"],
                cwd=worktree_path,
            )
        remove_proc = _run(
            [
                "make",
                "-C",
                str(repo_root),
                "worktree-remove",
                f"BRANCH={branch}",
                f"WORKTREE_AGENT={native_agent}",
                "WORKTREE_DISPOSITION=abandoned",
                f"WORKTREE_DISPOSITION_REASON=upgrade_governed_repos.py --write failed: {_single_line(reason, 200)}",
            ]
        )
        if remove_proc.returncode != 0:
            # Empty-after-stash branches read as "already integrated" by the
            # closeout preflight; retry as the disposition it actually wants.
            # A retry fired immediately (machine-speed, not human-paced) can
            # still observe a lock/registry write from the failed attempt in
            # flight; a short wait made this reliably succeed in testing.
            time.sleep(1.5)
            _run(
                [
                    "make",
                    "-C",
                    str(repo_root),
                    "worktree-remove",
                    f"BRANCH={branch}",
                    f"WORKTREE_AGENT={native_agent}",
                    "WORKTREE_DISPOSITION=merged",
                    f"WORKTREE_DISPOSITION_REASON=no unique commit; sync attempt failed: {_single_line(reason, 150)}",
                ]
            )

    if bootstrap_requires_narrowing:
        narrow_proc = _run(
            [
                "make",
                "-C",
                str(repo_root),
                "session-narrow",
                f"BRANCH={branch}",
                f"WORKTREE_AGENT={native_agent}",
                f"SESSION_WRITE_PATHS={write_paths}",
            ]
        )
        narrow_output = "\n".join(part for part in (narrow_proc.stdout, narrow_proc.stderr) if part).strip()
        if narrow_proc.returncode != 0 and "No rule to make target 'session-narrow'." in narrow_output:
            # An older target can have the narrowing implementation installed but
            # not yet expose its Make facade. Invoke the current stable CLI against
            # the same owner/session-bound claim; its subset and worktree-identity
            # validation is the contract the Make target delegates to.
            narrow_proc = _run(
                [
                    sys.executable,
                    str(SESSION_NARROW_SCRIPT),
                    "--agent",
                    native_agent,
                    "--project",
                    repo_id,
                    "--scope",
                    branch,
                    *[
                        argument
                        for path in write_path_list
                        for argument in ("--write-path", path)
                    ],
                    "--json",
                ],
                cwd=worktree_path,
            )
            narrow_output = "\n".join(part for part in (narrow_proc.stdout, narrow_proc.stderr) if part).strip()
        if narrow_proc.returncode != 0:
            _abandon(
                "session-narrow failed before installer mutation: "
                f"{narrow_output[:500]}"
            )
            return result

    install_proc = _run(
        [
            sys.executable,
            str(INSTALL_SCRIPT),
            "--repo-root",
            str(worktree_path),
            "--write",
            "--coordination-claims-only",
        ]
    )
    result.install_rc = install_proc.returncode
    result.install_stdout = install_proc.stdout
    result.install_stderr = install_proc.stderr
    if install_proc.returncode != 0:
        _abandon(f"install --write failed inside worktree: {install_proc.stderr.strip()[:500]}")
        return result

    audit_proc = _run(
        [sys.executable, str(AUDIT_SCRIPT), "--repo-root", str(worktree_path), "--strict-governed", "--json"]
    )
    result.audit_rc = audit_proc.returncode
    result.audit_stdout = audit_proc.stdout
    result.audit_stderr = audit_proc.stderr
    try:
        audit_data = json.loads(audit_proc.stdout)
        result.classification = audit_data.get("classification", "unknown")
        result.blockers = audit_data.get("blockers", [])
    except (json.JSONDecodeError, AttributeError):
        result.classification = "unknown"
    if audit_proc.returncode != 0:
        _abandon(f"audit --strict-governed failed inside worktree: {audit_proc.stderr.strip()[:500]}")
        return result

    status_proc = _run(["git", "status", "--porcelain"], cwd=worktree_path)
    if not status_proc.stdout.strip():
        result.had_diff = False
        close_proc = _run(
            [
                "make",
                "-C",
                str(repo_root),
                "session-close",
                f"BRANCH={branch}",
                f"WORKTREE_AGENT={native_agent}",
                "WORKTREE_DISPOSITION=merged",
                "WORKTREE_DISPOSITION_REASON=install --write produced no diff; already in sync with canonical enforced-planning",
            ]
        )
        if close_proc.returncode != 0:
            result.write_error = f"already in sync, but session-close failed: {close_proc.stderr.strip()[:500]}"
            return result
        return result

    result.had_diff = True
    add_proc = _run(["git", "add", "-A"], cwd=worktree_path)
    commit_proc = _run(
        [
            "git",
            "commit",
            "-m",
            (
                "[Unplanned] Sync coordination consumer files from canonical enforced-planning\n\n"
                "Automated via upgrade_governed_repos.py --write, Plan #51."
            ),
        ],
        cwd=worktree_path,
    )
    if add_proc.returncode != 0 or commit_proc.returncode != 0:
        _abandon(f"git commit failed: {(commit_proc.stderr or add_proc.stderr).strip()[:500]}")
        return result

    push_proc = _run(["git", "push", "-u", "origin", branch], cwd=worktree_path)
    if push_proc.returncode != 0:
        _abandon(f"git push failed: {push_proc.stderr.strip()[:500]}")
        return result

    pr_proc = _run(
        [
            github_cli,
            "pr",
            "create",
            "--title",
            (
                "Sync coordination consumer files from canonical enforced-planning "
                f"({datetime.now(UTC).date().isoformat()})"
            ),
            "--body",
            (
                "Automated via `scripts/upgrade_governed_repos.py --write` (Plan #51). "
                "Not auto-merged -- review before merging.\n\n"
                f"Generated by the native {native_agent} rollout session."
            ),
        ],
        cwd=worktree_path,
    )
    if pr_proc.returncode == 0:
        result.pr_url = pr_proc.stdout.strip()
    else:
        result.write_error = f"pushed but PR creation failed: {pr_proc.stderr.strip()[:500]}"

    return result


def upgrade_repo(
    repo_id: str,
    repo_root: Path,
    tier: str,
    dry_run: bool,
) -> RepoUpgradeResult:
    """Run install + audit for one repo and return the result."""
    result = RepoUpgradeResult(repo_id=repo_id, repo_root=repo_root, tier=tier)

    if not repo_root.exists():
        result.skipped = True
        result.skip_reason = f"repo root does not exist: {repo_root}"
        return result

    if not dry_run and _has_local_dirt(repo_root):
        result.skipped = True
        result.skip_reason = "local dirt detected; --write mode requires a clean working tree"
        return result

    if not any((repo_root / name).is_file() for name in ("AGENTS.md", "CLAUDE.md")):
        result.blockers.append("missing root AGENTS.md or CLAUDE.md (hard blocker)")
        result.classification = "legacy"
        result.skipped = True
        result.skip_reason = "missing root AGENTS.md or CLAUDE.md"
        return result

    # Run install
    install_cmd = [
        sys.executable,
        str(INSTALL_SCRIPT),
        "--repo-root",
        str(repo_root),
    ]
    if not dry_run:
        install_cmd.append("--write")

    install_proc = subprocess.run(
        install_cmd,
        capture_output=True,
        text=True,
    )
    result.install_rc = install_proc.returncode
    result.install_stdout = install_proc.stdout
    result.install_stderr = install_proc.stderr

    # Run audit
    audit_cmd = [
        sys.executable,
        str(AUDIT_SCRIPT),
        "--repo-root",
        str(repo_root),
        "--json",
    ]
    audit_proc = subprocess.run(
        audit_cmd,
        capture_output=True,
        text=True,
    )
    result.audit_rc = audit_proc.returncode
    result.audit_stdout = audit_proc.stdout
    result.audit_stderr = audit_proc.stderr

    # Parse classification from audit JSON if available
    try:
        audit_data = json.loads(audit_proc.stdout)
        result.classification = audit_data.get("classification", "unknown")
        result.blockers = audit_data.get("blockers", [])
    except (json.JSONDecodeError, AttributeError):
        result.classification = "unknown"

    return result


def load_registry(registry_path: Path) -> list[dict[str, Any]]:
    """Load governed_repos.yaml and return the repos list."""
    data = yaml.safe_load(registry_path.read_text())
    return data.get("repos", [])


def run_upgrade(
    registry_path: Path,
    target_repo: str | None,
    dry_run: bool,
    as_json: bool,
    authorized_owners: frozenset[str] = frozenset({"brian"}),
    github_cli: str = "gh",
) -> int:
    """Main upgrade loop. Returns exit code."""
    repos = load_registry(registry_path)

    if target_repo:
        repos = [r for r in repos if (r.get("repo_id") or r.get("id")) == target_repo]
        if not repos:
            print(f"ERROR: repo '{target_repo}' not found in registry", file=sys.stderr)
            return 1

    mode = "DRY-RUN" if dry_run else "WRITE"
    if not as_json:
        print(f"upgrade_governed_repos — {mode} mode — {len(repos)} repo(s)")
        print()

    results: list[RepoUpgradeResult] = []
    for entry in repos:
        repo_id = entry.get("repo_id") or entry["id"]
        repo_root = _expand(entry.get("repo_root") or entry["path"])
        tier = entry.get("tier", "governed")

        if not as_json:
            print(f"  → {repo_id} ({tier}) at {repo_root}")

        if dry_run:
            result = upgrade_repo(repo_id, repo_root, tier, dry_run)
        else:
            result = write_repo(
                repo_id,
                repo_root,
                tier,
                entry.get("owner", "brian"),
                authorized_owners=authorized_owners,
                github_cli=github_cli,
            )
        results.append(result)

        if not as_json:
            print(result.summary_line())
            if result.blockers:
                for b in result.blockers:
                    print(f"       blocker: {b}")

    ok = sum(1 for r in results if r.success)
    skipped = sum(1 for r in results if r.skipped)
    failed = len(results) - ok - skipped

    if as_json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "total": len(results),
                    "ok": ok,
                    "skipped": skipped,
                    "failed": failed,
                    "repos": [
                        {
                            "repo_id": r.repo_id,
                            "tier": r.tier,
                            "success": r.success,
                            "skipped": r.skipped,
                            "skip_reason": r.skip_reason,
                            "classification": r.classification,
                            "blockers": r.blockers,
                            "install_rc": r.install_rc,
                            "audit_rc": r.audit_rc,
                            "branch": r.branch,
                            "had_diff": r.had_diff,
                            "pr_url": r.pr_url,
                            "write_error": r.write_error,
                        }
                        for r in results
                    ],
                },
                indent=2,
            )
        )
    else:
        print()
        print(f"  Result: {ok} ok, {skipped} skipped, {failed} failed of {len(results)} total")

    return 0 if failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Orchestrate governed-repo upgrades across the fleet.",
    )
    parser.add_argument(
        "--registry",
        default="governed_repos.yaml",
        help="Path to governed_repos.yaml (default: governed_repos.yaml)",
    )
    parser.add_argument(
        "--repo",
        metavar="REPO_ID",
        help="Upgrade only this repo (by repo_id). Omit for all repos.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview actions without modifying any files (default if --write not given).",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=False,
        help=(
            "Sync one repo (requires --repo) through its own claimed linked "
            "worktree: make maintenance-worktree, install --write, audit "
            "--strict-governed, then commit+push+PR if there was a diff. "
            "Never touches the primary checkout and never auto-merges."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output machine-readable JSON report.",
    )
    parser.add_argument(
        "--authorize-owner",
        action="append",
        default=[],
        metavar="OWNER",
        help=(
            "Explicitly authorize write-mode for a non-Brian owner named in the registry. "
            "Repeat for multiple owners; omitted owners remain fail-closed."
        ),
    )
    parser.add_argument(
        "--github-cli",
        choices=("gh", "gh-personal", "gh-insidesuccess"),
        default="gh",
        help="Credential-routed GitHub CLI used only to create the resulting PR.",
    )
    args = parser.parse_args(argv)

    if args.write and not args.repo:
        print(
            "ERROR: --write requires --repo REPO_ID. This slice is intentionally "
            "one repo at a time (see the design doc's 'Minimal First Slice'); "
            "batch fleet write-mode is a later slice, not this command's default.",
            file=sys.stderr,
        )
        return 2

    dry_run = not args.write  # default is dry-run; --write enables apply mode
    registry_path = _expand(args.registry)

    if not registry_path.exists():
        print(f"ERROR: registry not found: {registry_path}", file=sys.stderr)
        return 1

    return run_upgrade(
        registry_path=registry_path,
        target_repo=args.repo,
        dry_run=dry_run,
        as_json=args.json,
        authorized_owners=frozenset({"brian", *args.authorize_owner}),
        github_cli=args.github_cli,
    )


if __name__ == "__main__":
    raise SystemExit(main())
