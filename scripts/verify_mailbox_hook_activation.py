#!/usr/bin/env python3
"""Fail loud until Codex hook config is loaded and a mailbox canary is acknowledged."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enforced_planning.mailbox_delivery import (  # noqa: E402
    MailboxInstallationError,
    check_mailbox_hook_activation,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-config", default="~/.codex/config.toml")
    parser.add_argument("--proc-root", default="/proc", help=argparse.SUPPRESS)
    parser.add_argument("--clock-ticks", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--canary-message-id")
    parser.add_argument("--mailbox-root", default="~/.claude/coordination/messages-v1")
    parser.add_argument("--claims-dir", default="~/.claude/coordination/claims")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        receipt = check_mailbox_hook_activation(
            codex_config_path=args.codex_config,
            proc_root=Path(args.proc_root),
            clock_ticks=args.clock_ticks,
            canary_message_id=args.canary_message_id,
            mailbox_root=Path(args.mailbox_root),
            claims_dir=Path(args.claims_dir),
        )
    except (MailboxInstallationError, OSError, ValueError) as exc:
        print(f"mailbox hook activation check failed: {exc}", file=sys.stderr)
        return 2
    print(receipt.model_dump_json(indent=2))
    if receipt.restart_required:
        pids = ", ".join(str(process.pid) for process in receipt.stale_codex_processes)
        print(
            f"RESTART REQUIRED: Codex process(es) {pids} started before the hook config changed. "
            "Restart or resume those clients, then rerun this check with an acknowledged canary message ID.",
            file=sys.stderr,
        )
        return 3
    if not receipt.canary_acknowledged:
        print(
            "CANARY REQUIRED: send one exact-session coordination message, allow the restarted hook "
            "to surface it, acknowledge it, then rerun with --canary-message-id.",
            file=sys.stderr,
        )
        return 4
    print("MAILBOX HOOK ACTIVATION VERIFIED: processes are fresh and the exact canary is acknowledged.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
