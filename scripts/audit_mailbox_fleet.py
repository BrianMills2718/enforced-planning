#!/usr/bin/env python3
"""Audit every explicit governed repository for mailbox compatibility without writes."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enforced_planning.mailbox_fleet_audit import (  # noqa: E402
    MailboxFleetAuditError,
    MailboxFleetAuditRequestV1,
    audit_mailbox_fleet,
)


def _revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(ROOT / "governed_repos.yaml"))
    parser.add_argument("--framework-root", default=str(ROOT))
    parser.add_argument(
        "--workspace-root",
        help="Optional immediate-child scan root for unregistered governed repositories; read-only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Assert the default read-only mode explicitly; no write mode exists.",
    )
    parser.add_argument("--json", action="store_true", help="Emit stable machine-readable JSON (default).")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        report = audit_mailbox_fleet(
            MailboxFleetAuditRequestV1(
                registry_path=args.registry,
                framework_root=args.framework_root,
                workspace_root=args.workspace_root,
                framework_revision=_revision(Path(args.framework_root)),
            )
        )
    except MailboxFleetAuditError as exc:
        print(f"mailbox fleet audit failed: {exc}", file=sys.stderr)
        return 2
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
