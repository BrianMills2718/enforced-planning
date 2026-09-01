#!/usr/bin/env python3
"""Emit or validate one native-session, canonical-claim integration assertion."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path


def _framework_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "enforced_planning").is_dir():
            return candidate
    raise RuntimeError("cannot locate the installed enforced_planning package")


ROOT = _framework_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enforced_planning.integration_authority import (
    IntegrationAuthorityAssertionV1,
    IntegrationAuthorityError,
    IntegrationTargetV1,
    assert_integration_authority,
    review_spec_sha256,
    validate_integration_authority,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate canonical branch-claim custody for make finish."
    )
    parser.add_argument("operation", choices=("assert", "validate"))
    parser.add_argument("--agent", choices=("codex", "claude-code", "openclaw"), required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--assertion", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--project")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--branch")
    parser.add_argument("--base-sha")
    parser.add_argument("--head-sha")
    parser.add_argument("--review-spec", type=Path)
    parser.add_argument("--validity-seconds", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.claims_dir is not None and os.environ.get(
        "ENFORCED_PLANNING_INTEGRATION_AUTHORITY_TESTING"
    ) != "1":
        print("custom claim registries are test-only", file=sys.stderr)
        return 2
    try:
        required = {
            "--repository": args.repository,
            "--project": args.project,
            "--pr": args.pr,
            "--branch": args.branch,
            "--base-sha": args.base_sha,
            "--head-sha": args.head_sha,
            "--review-spec": args.review_spec,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise IntegrationAuthorityError(
                f"{args.operation} requires {', '.join(missing)}"
            )
        target = IntegrationTargetV1(
            repository=args.repository,
            project=args.project,
            pr_number=args.pr,
            branch=args.branch,
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            review_spec_sha256=review_spec_sha256(args.review_spec),
        )
        if args.operation == "assert":
            assertion = assert_integration_authority(
                target=target,
                agent=args.agent,
                repo_root=args.repo_root,
                claims_dir=args.claims_dir,
                validity=timedelta(seconds=args.validity_seconds),
            )
            print(assertion.model_dump_json())
            return 0
        if args.assertion is None:
            raise IntegrationAuthorityError("validate requires --assertion")
        assertion = IntegrationAuthorityAssertionV1.model_validate_json(
            args.assertion.read_text("utf-8")
        )
        validate_integration_authority(
            assertion,
            expected_target=target,
            agent=args.agent,
            repo_root=args.repo_root,
            claims_dir=args.claims_dir,
        )
        print(json.dumps({"ok": True, "assertion_sha256": assertion.assertion_sha256}, sort_keys=True))
        return 0
    except (IntegrationAuthorityError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
