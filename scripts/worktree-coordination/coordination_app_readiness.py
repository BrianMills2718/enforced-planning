#!/usr/bin/env python3
"""Read-only readiness check for the coordination-approver GitHub App.

The command observes branch protection and, optionally, one commit's check
runs.  It never mutates GitHub.  Its deterministic negative probes demonstrate
that a same-named check from a different App and a success for an old head do
not satisfy the configured identity boundary.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

APPROVAL_CONTEXT = "coordination-approval"
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    repo: str
    branch: str
    expected_app_id: int
    observed_app_id: int | None
    strict_required_checks: bool
    enforce_admins: bool
    exact_head_success: bool | None
    same_name_wrong_app_rejected: bool
    old_head_rejected: bool
    problems: tuple[str, ...]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("App ID must be a positive integer")
    return parsed


def _repo_slug(value: str) -> str:
    if not REPO_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("repository must be OWNER/NAME")
    return value


def _head_sha(value: str) -> str:
    normalized = value.lower()
    if not FULL_SHA_RE.fullmatch(normalized):
        raise argparse.ArgumentTypeError("head SHA must be 40 lowercase hex characters")
    return normalized


def _gh_json(
    endpoint: str, *, gh_command: str = "gh", env: Mapping[str, str] | None = None
) -> Any:
    result = subprocess.run(
        [gh_command, "api", endpoint],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"{gh_command} api {endpoint} failed: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"gh api {endpoint} returned invalid JSON: {exc}") from exc


def _bound_app_id(protection: Mapping[str, object]) -> tuple[int | None, list[str]]:
    problems: list[str] = []
    required = protection.get("required_status_checks")
    if not isinstance(required, Mapping):
        return None, ["branch protection has no required_status_checks object"]
    checks = required.get("checks")
    if not isinstance(checks, list):
        return None, ["required_status_checks has no checks list"]
    matches = [
        row for row in checks
        if isinstance(row, Mapping) and row.get("context") == APPROVAL_CONTEXT
    ]
    if len(matches) != 1:
        problems.append(
            f"branch protection must bind exactly one {APPROVAL_CONTEXT} check; found {len(matches)}"
        )
        return None, problems
    app_id = matches[0].get("app_id")
    if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
        problems.append(f"{APPROVAL_CONTEXT} has no positive App ID binding")
        return None, problems
    return app_id, problems


def _run_is_authoritative(
    run: Mapping[str, object], *, expected_app_id: int, expected_head: str
) -> bool:
    app = run.get("app")
    app_id = app.get("id") if isinstance(app, Mapping) else None
    return (
        run.get("name") == APPROVAL_CONTEXT
        and app_id == expected_app_id
        and run.get("head_sha") == expected_head
        and str(run.get("status", "")).upper() == "COMPLETED"
        and str(run.get("conclusion", "")).upper() == "SUCCESS"
    )


def evaluate_readiness(
    *,
    repo: str,
    branch: str,
    expected_app_id: int,
    protection: Mapping[str, object],
    head_sha: str | None = None,
    check_runs: Sequence[object] = (),
) -> ReadinessReport:
    problems: list[str] = []
    observed_app_id, binding_problems = _bound_app_id(protection)
    problems.extend(binding_problems)
    if observed_app_id is not None and observed_app_id != expected_app_id:
        problems.append(
            f"{APPROVAL_CONTEXT} is bound to App {observed_app_id}, expected {expected_app_id}"
        )

    required = protection.get("required_status_checks")
    strict = isinstance(required, Mapping) and required.get("strict") is True
    if not strict:
        problems.append("required status checks are not strict")

    admins = protection.get("enforce_admins")
    enforce_admins = isinstance(admins, Mapping) and admins.get("enabled") is True
    if not enforce_admins:
        problems.append("branch protection does not enforce rules for administrators")

    exact_head_success: bool | None = None
    if head_sha is not None:
        matching_runs = [
            row
            for row in check_runs
            if isinstance(row, Mapping) and row.get("name") == APPROVAL_CONTEXT
        ]
        exact_head_success = bool(matching_runs) and _run_is_authoritative(
            matching_runs[0],
            expected_app_id=expected_app_id,
            expected_head=head_sha,
        )
        if not exact_head_success:
            problems.append(
                f"no completed successful {APPROVAL_CONTEXT} from App {expected_app_id} on {head_sha}"
            )

    probe_head = head_sha or ("a" * 40)
    good_run = {
        "name": APPROVAL_CONTEXT,
        "head_sha": probe_head,
        "status": "completed",
        "conclusion": "success",
        "app": {"id": expected_app_id},
    }
    wrong_app = {
        **good_run,
        "app": {"id": expected_app_id + 1},
    }
    old_head = {
        **good_run,
        "head_sha": "b" * 40 if probe_head != "b" * 40 else "c" * 40,
    }
    wrong_app_rejected = not _run_is_authoritative(
        wrong_app, expected_app_id=expected_app_id, expected_head=probe_head
    )
    old_head_rejected = not _run_is_authoritative(
        old_head, expected_app_id=expected_app_id, expected_head=probe_head
    )
    if not wrong_app_rejected:
        problems.append("negative probe failed: same-name wrong-App check was accepted")
    if not old_head_rejected:
        problems.append("negative probe failed: old-head check was accepted")

    return ReadinessReport(
        ready=not problems,
        repo=repo,
        branch=branch,
        expected_app_id=expected_app_id,
        observed_app_id=observed_app_id,
        strict_required_checks=strict,
        enforce_admins=enforce_admins,
        exact_head_success=exact_head_success,
        same_name_wrong_app_rejected=wrong_app_rejected,
        old_head_rejected=old_head_rejected,
        problems=tuple(problems),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=_repo_slug)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--app-id", required=True, type=_positive_int)
    parser.add_argument("--head-sha", type=_head_sha)
    parser.add_argument(
        "--gh-command",
        default="gh",
        help="GitHub CLI executable or account-routing wrapper (default: gh)",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    protection = _gh_json(
        f"repos/{args.repo}/branches/{args.branch}/protection",
        gh_command=args.gh_command,
    )
    if not isinstance(protection, Mapping):
        raise TypeError("branch protection response must be an object")
    runs: Sequence[object] = ()
    if args.head_sha:
        payload = _gh_json(
            f"repos/{args.repo}/commits/{args.head_sha}/check-runs",
            gh_command=args.gh_command,
        )
        if not isinstance(payload, Mapping) or not isinstance(payload.get("check_runs"), list):
            raise TypeError("check-runs response must contain a check_runs list")
        runs = payload["check_runs"]
    report = evaluate_readiness(
        repo=args.repo,
        branch=args.branch,
        expected_app_id=args.app_id,
        protection=protection,
        head_sha=args.head_sha,
        check_runs=runs,
    )
    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
    else:
        print("READY" if report.ready else "NOT READY")
        for problem in report.problems:
            print(f"- {problem}")
    return 0 if report.ready else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
