#!/usr/bin/env python3
"""Read-only audit of Codex and Claude host mailbox hook configuration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enforced_planning.mailbox_delivery import (  # noqa: E402
    HostAdapterSpecV1,
    HostInstallationAuditRequestV1,
    MailboxInstallationError,
    audit_host_installation,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-config", default="~/.codex/config.toml")
    parser.add_argument("--claude-config", default="~/.claude/settings.json")
    parser.add_argument("--codex-command", required=True)
    parser.add_argument("--claude-command", required=True)
    parser.add_argument("--codex-adapter", required=True)
    parser.add_argument("--claude-adapter", required=True)
    parser.add_argument("--repository-root")
    parser.add_argument("--framework-revision", default="unknown")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        receipt = audit_host_installation(
            HostInstallationAuditRequestV1(
                codex_config_path=args.codex_config,
                claude_config_path=args.claude_config,
                codex_adapter=HostAdapterSpecV1(command=args.codex_command, adapter_path=args.codex_adapter),
                claude_adapter=HostAdapterSpecV1(command=args.claude_command, adapter_path=args.claude_adapter),
                repository_root=args.repository_root,
                framework_revision=args.framework_revision,
            )
        )
    except MailboxInstallationError as exc:
        print(f"mailbox installation audit failed: {exc}", file=sys.stderr)
        return 2
    print(receipt.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
