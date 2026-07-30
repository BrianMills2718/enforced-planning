#!/usr/bin/env python3
"""Plan, fingerprint, or explicitly apply canonical host mailbox hooks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from enforced_planning.mailbox_delivery import (  # noqa: E402
    HostAdapterSpecV1,
    HostInstallationApplyError,
    HostInstallationPlanRequestV1,
    MailboxInstallationError,
    StoredHostInstallationCandidateV1,
    apply_host_installation_candidate,
    generate_host_installation_candidate,
    plan_host_installation,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-config", default="~/.codex/config.toml")
    parser.add_argument("--claude-config", default="~/.claude/settings.json")
    parser.add_argument("--codex-command", required=True)
    parser.add_argument("--claude-command", required=True)
    parser.add_argument("--codex-adapter", required=True)
    parser.add_argument("--claude-adapter", required=True)
    parser.add_argument("--codex-adapter-sha256", required=True)
    parser.add_argument("--claude-adapter-sha256", required=True)
    parser.add_argument("--repository-root")
    parser.add_argument("--framework-revision", default="unknown")
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="Emit the MF-03A digest-bound read-only candidate instead of the legacy dry-run plan.",
    )
    parser.add_argument("--apply-candidate", help="Apply this exact MF-03A candidate after digest approval.")
    parser.add_argument("--approved-payload-sha256", help="Exact readiness-approved candidate payload digest.")
    parser.add_argument(
        "--backup-root",
        default="~/.claude/coordination/backups/mailbox-host",
        help="Durable directory for exact pre-apply host-config backups.",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        request = HostInstallationPlanRequestV1(
            codex_config_path=args.codex_config,
            claude_config_path=args.claude_config,
            codex_adapter=HostAdapterSpecV1(
                command=args.codex_command,
                adapter_path=args.codex_adapter,
                expected_sha256=args.codex_adapter_sha256,
            ),
            claude_adapter=HostAdapterSpecV1(
                command=args.claude_command,
                adapter_path=args.claude_adapter,
                expected_sha256=args.claude_adapter_sha256,
            ),
            repository_root=args.repository_root,
            framework_revision=args.framework_revision,
        )
        if args.candidate and args.apply_candidate:
            raise MailboxInstallationError("--candidate and --apply-candidate are mutually exclusive")
        if args.apply_candidate:
            if not args.approved_payload_sha256:
                raise MailboxInstallationError("--apply-candidate requires --approved-payload-sha256")
            candidate = StoredHostInstallationCandidateV1.model_validate_json(
                Path(args.apply_candidate).expanduser().read_text(encoding="utf-8")
            )
            apply_receipt = apply_host_installation_candidate(
                candidate=candidate,
                approved_payload_sha256=args.approved_payload_sha256,
                request=request,
                backup_root=args.backup_root,
            )
            output_json = apply_receipt.model_dump_json(indent=2)
        else:
            output_json = (
                generate_host_installation_candidate(request).model_dump_json(indent=2)
                if args.candidate
                else plan_host_installation(request).model_dump_json(indent=2)
            )
    except HostInstallationApplyError as exc:
        print(exc.receipt.model_dump_json(indent=2), file=sys.stderr)
        return 3
    except (OSError, ValueError) as exc:
        print(f"mailbox host installation input failed: {exc}", file=sys.stderr)
        return 2
    except MailboxInstallationError as exc:
        print(f"mailbox host installation planning failed: {exc}", file=sys.stderr)
        return 2
    print(output_json)
    if args.apply_candidate:
        print(
            "RESTART REQUIRED: running clients do not reload newly installed hooks. "
            "After restart, send and acknowledge one exact-session mailbox canary, then run "
            "scripts/verify_mailbox_hook_activation.py --canary-message-id <message-id>.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
