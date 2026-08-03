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

    # Write mode is fail-closed until claimed-worktree orchestration is implemented.
    # Apply one reviewed dry-run through install_governed_repo.py inside that
    # repository's own claimed linked worktree instead.

    # Output machine-readable report
    python scripts/upgrade_governed_repos.py --registry governed_repos.yaml --dry-run --json

Design: docs/designs/GOVERNED_REPO_UPGRADE_AUTOMATION.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = FRAMEWORK_ROOT / "scripts" / "install_governed_repo.py"
AUDIT_SCRIPT = FRAMEWORK_ROOT / "scripts" / "audit_governed_repo.py"


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

    @property
    def success(self) -> bool:
        if self.skipped:
            return False
        return self.install_rc == 0 and self.audit_rc == 0

    def summary_line(self) -> str:
        if self.skipped:
            return f"  SKIP  {self.repo_id}: {self.skip_reason}"
        status = "OK  " if self.success else "FAIL"
        return f"  {status}  {self.repo_id} [{self.classification}]"


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

    if not (repo_root / "CLAUDE.md").exists():
        result.blockers.append("missing root CLAUDE.md (hard blocker)")
        result.classification = "legacy"
        result.skipped = True
        result.skip_reason = "missing root CLAUDE.md"
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

        result = upgrade_repo(repo_id, repo_root, tier, dry_run)
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
        print(json.dumps({
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
                }
                for r in results
            ],
        }, indent=2))
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
        help="Reserved; currently fails closed until claimed-worktree write orchestration exists.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output machine-readable JSON report.",
    )
    args = parser.parse_args(argv)

    if args.write:
        print(
            "ERROR: fleet --write is disabled because this command does not yet "
            "create claimed linked worktrees, commits, publication receipts, or "
            "sanctioned closeout. Run the fleet dry-run, then apply the selected "
            "installer profile inside each repository's own claimed worktree.",
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
    )


if __name__ == "__main__":
    raise SystemExit(main())
