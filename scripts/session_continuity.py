#!/usr/bin/env python3
"""Observe one claim owner and report resume-first continuity action."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import secrets
import shlex
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _bootstrap_package() -> None:
    """Load vendored support at either source or installed script depth."""

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    import importlib.util

    if importlib.util.find_spec("enforced_planning") is not None:
        return
    raise RuntimeError("Unable to locate local or installed enforced_planning support")


_bootstrap_package()

from enforced_planning import (  # noqa: I001
    coordination_claims,
    coordination_messages,
    session_continuity,
)


DEFAULT_RECEIPT_PATH = (
    Path.home() / ".local/state/enforced-planning/session-continuity-sweeps.jsonl"
)
DEFAULT_UNIT_NAME = "enforced-planning-session-continuity"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--scan-all-live-claims",
        action="store_true",
        help="Observe every live Codex claim in one bounded sweep; never transfer custody.",
    )
    mode.add_argument(
        "--install-observe-timer",
        action="store_true",
        help="Install one shared user timer that runs observe-only continuity sweeps.",
    )
    parser.add_argument("--agent", default="codex", choices=("codex",))
    parser.add_argument("--project")
    parser.add_argument("--scope")
    parser.add_argument("--notify-minutes", type=int, default=15)
    parser.add_argument(
        "--send-resume-offer",
        action="store_true",
        help="Persist one idempotent exact-session resume offer when the assessment requests it.",
    )
    parser.add_argument(
        "--queue-native-resume-offer",
        action="store_true",
        help="Queue one typed resume prompt to the exact idle Codex thread.",
    )
    parser.add_argument("--codex", default="codex", help=argparse.SUPPRESS)
    parser.add_argument("--sender-session-id")
    parser.add_argument(
        "--resume-offer-message-id",
        help="Review one exact prior resume offer against current owner activity and receipts.",
    )
    parser.add_argument("--successor-after-minutes", type=int, default=30)
    parser.add_argument("--receipt-jsonl", type=Path, default=DEFAULT_RECEIPT_PATH)
    parser.add_argument("--timer-minutes", type=int, default=10)
    parser.add_argument(
        "--unit-dir",
        type=Path,
        default=Path.home() / ".config/systemd/user",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if (
        not args.scan_all_live_claims
        and not args.install_observe_timer
        and (not args.project or not args.scope)
    ):
        parser.error("exact assessment requires --project and --scope")
    if args.scan_all_live_claims and (args.project or args.scope):
        parser.error("--scan-all-live-claims cannot be combined with --project or --scope")
    if (args.scan_all_live_claims or args.install_observe_timer) and (
        args.send_resume_offer or args.queue_native_resume_offer or args.resume_offer_message_id
    ):
        parser.error("shared observe mode cannot send or review resume offers")
    if args.send_resume_offer and args.queue_native_resume_offer:
        parser.error("select only one resume-offer delivery path")
    if args.notify_minutes <= 0 or args.timer_minutes <= 0:
        parser.error("notification and timer intervals must be positive")
    return args


def _assess_claim(claim: coordination_claims.ClaimRecord, *, notify_minutes: int) -> dict[str, Any]:
    """Produce one fail-visible observation without creating takeover authority."""

    base = {
        "agent": claim.agent,
        "project": claim.primary_project(),
        "scope": claim.scope,
        "session_id": claim.session_id,
    }
    try:
        transcript = coordination_claims.session_transcript_path(claim.session_id)
        activity = (
            session_continuity.read_codex_activity(
                session_id=claim.session_id or "unknown",
                transcript_path=transcript,
            )
            if transcript is not None and claim.session_id is not None
            else None
        )
        assessment = session_continuity.assess_continuity(
            claim=claim,
            activity=activity,
            notify_after=timedelta(minutes=notify_minutes),
        )
        return {**base, "assessment": assessment.model_dump(mode="json"), "error": None}
    except (OSError, TypeError, ValueError) as exc:
        return {
            **base,
            "assessment": None,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def build_observe_sweep(*, notify_minutes: int) -> dict[str, Any]:
    """Observe every live Codex claim through one shared, non-mutating pass."""

    observed_at = datetime.now(UTC)
    claims = [
        claim
        for claim in coordination_claims.check_claims()
        if claim.agent == "codex" and claim.is_live()
    ]
    items = [_assess_claim(claim, notify_minutes=notify_minutes) for claim in claims]
    actionable = sum(
        item["assessment"] is not None and item["assessment"]["action"] == "notify_owner"
        for item in items
    )
    fail_visible = sum(
        item["error"] is not None
        or (
            item["assessment"] is not None
            and item["assessment"]["action"] == "fail_visible"
        )
        for item in items
    )
    return {
        "schema_version": "1.0",
        "record_type": "session_continuity_sweep",
        "mode": "observe",
        "observed_at": observed_at.isoformat(),
        "claim_count": len(items),
        "notify_owner_count": actionable,
        "fail_visible_count": fail_visible,
        "transfer_eligible": False,
        "successor_launch_allowed": False,
        "items": items,
    }


def _append_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Append one fsynced sweep receipt while excluding overlapping sweeps."""

    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = resolved.with_suffix(resolved.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another session continuity sweep is still active") from exc
        with resolved.open("a", encoding="utf-8") as receipt:
            resolved.chmod(0o600)
            receipt.write(json.dumps(payload, sort_keys=True) + "\n")
            receipt.flush()
            os.fsync(receipt.fileno())


@contextmanager
def _exclusive_sweep(receipt_path: Path) -> Iterator[None]:
    """Prevent two shared timer invocations from scanning concurrently."""

    resolved = receipt_path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = resolved.with_suffix(resolved.suffix + ".sweep.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another session continuity sweep is still active") from exc
        yield


def run_observe_sweep(*, notify_minutes: int, receipt_path: Path) -> dict[str, Any]:
    """Run and receipt one full observe sweep under the shared process lock."""

    with _exclusive_sweep(receipt_path):
        payload = build_observe_sweep(notify_minutes=notify_minutes)
        _append_receipt(receipt_path, payload)
        return payload


def render_observe_timer(
    *,
    script_path: Path,
    python_path: Path,
    receipt_path: Path,
    timer_minutes: int,
    notify_minutes: int,
) -> tuple[str, str]:
    """Render one shared oneshot service and its bounded observe timer."""

    if timer_minutes <= 0 or notify_minutes <= 0:
        raise ValueError("timer and notification intervals must be positive")
    command = shlex.join(
        (
            str(python_path.expanduser().resolve()),
            str(script_path.expanduser().resolve()),
            "--scan-all-live-claims",
            "--agent",
            "codex",
            "--notify-minutes",
            str(notify_minutes),
            "--receipt-jsonl",
            str(receipt_path.expanduser().resolve()),
            "--json",
        )
    )
    service = (
        "[Unit]\n"
        "Description=Observe authorized Codex work continuity\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={command}\n"
        "Nice=10\n"
    )
    timer = (
        "[Unit]\n"
        "Description=Periodically observe authorized Codex work continuity\n\n"
        "[Timer]\n"
        "OnBootSec=5m\n"
        f"OnUnitActiveSec={timer_minutes}m\n"
        "AccuracySec=1m\n"
        "Persistent=true\n"
        f"Unit={DEFAULT_UNIT_NAME}.service\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


def install_observe_timer(
    *,
    unit_dir: Path,
    receipt_path: Path,
    timer_minutes: int,
    notify_minutes: int,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Install and enable one shared observe-only timer with retirement metadata."""

    service, timer = render_observe_timer(
        script_path=Path(__file__),
        python_path=Path(sys.executable),
        receipt_path=receipt_path,
        timer_minutes=timer_minutes,
        notify_minutes=notify_minutes,
    )
    resolved_dir = unit_dir.expanduser().resolve()
    service_path = resolved_dir / f"{DEFAULT_UNIT_NAME}.service"
    timer_path = resolved_dir / f"{DEFAULT_UNIT_NAME}.timer"
    metadata_path = resolved_dir / f"{DEFAULT_UNIT_NAME}.json"
    if (service_path.exists() or timer_path.exists()) and not metadata_path.is_file():
        raise ValueError("continuity timer unit name is occupied without owner metadata")
    if metadata_path.is_file():
        current_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(current_metadata, dict) or current_metadata.get("owner") != "enforced-planning":
            raise ValueError("continuity timer owner metadata does not authorize replacement")

    preflight = run(
        ("systemctl", "--user", "show-environment"),
        capture_output=True,
        text=True,
        check=False,
    )
    if preflight.returncode != 0:
        raise RuntimeError(
            "systemd user manager is unavailable: "
            + (preflight.stderr or preflight.stdout).strip()
        )

    resolved_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = {
        "schema_version": "1.0",
        "mode": "observe",
        "owner": "enforced-planning",
        "review_after": (datetime.now(UTC) + timedelta(days=14)).date().isoformat(),
        "retirement_condition": (
            "replace when delivered owner-resume triggering is enforced, or retire after "
            "30 days with no decision-changing idle-owner observations"
        ),
        "timer_minutes": timer_minutes,
        "notify_minutes": notify_minutes,
        "receipt_path": str(receipt_path.expanduser().resolve()),
    }

    def atomic_write(path: Path, content: str) -> None:
        temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    atomic_write(service_path, service)
    atomic_write(timer_path, timer)
    atomic_write(metadata_path, json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    for command in (
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", f"{DEFAULT_UNIT_NAME}.timer"),
        ("systemctl", "--user", "is-enabled", f"{DEFAULT_UNIT_NAME}.timer"),
        ("systemctl", "--user", "is-active", f"{DEFAULT_UNIT_NAME}.timer"),
    ):
        result = run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"{' '.join(command)} failed: {(result.stderr or result.stdout).strip()}"
            )
    return {
        **metadata,
        "service_path": str(service_path),
        "timer_path": str(timer_path),
        "metadata_path": str(metadata_path),
        "enabled": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.install_observe_timer:
        payload = install_observe_timer(
            unit_dir=args.unit_dir,
            receipt_path=args.receipt_jsonl,
            timer_minutes=args.timer_minutes,
            notify_minutes=args.notify_minutes,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.scan_all_live_claims:
        payload = run_observe_sweep(
            notify_minutes=args.notify_minutes,
            receipt_path=args.receipt_jsonl,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    matches = [
        claim
        for claim in coordination_claims.check_claims()
        if claim.agent == args.agent
        and args.project in claim.projects
        and claim.scope == args.scope
    ]
    if len(matches) != 1:
        raise ValueError("session continuity requires one exact live claim")
    claim = matches[0]
    transcript = coordination_claims.session_transcript_path(claim.session_id)
    activity = (
        session_continuity.read_codex_activity(
            session_id=claim.session_id or "unknown",
            transcript_path=transcript,
        )
        if transcript is not None and claim.session_id is not None
        else None
    )
    assessment = session_continuity.assess_continuity(
        claim=claim,
        activity=activity,
        notify_after=timedelta(minutes=args.notify_minutes),
    )
    payload = assessment.model_dump(mode="json")
    payload["resume_offer"] = None
    payload["native_resume_offer"] = None
    payload["resume_offer_review"] = None
    store = coordination_messages.CoordinationMessageStore(
        root=coordination_messages.default_message_root(coordination_claims.CLAIMS_DIR),
        claims_dir=coordination_claims.CLAIMS_DIR,
    )
    if args.send_resume_offer and assessment.action == "notify_owner":
        resolved_sender = coordination_claims.resolve_session_id(args.agent, args.sender_session_id)
        if resolved_sender != args.sender_session_id:
            raise ValueError("resume offer sender must equal the current native session")
        request = session_continuity.build_resume_offer_request(
            assessment=assessment,
            sender_session_id=resolved_sender,
            project=args.project,
            scope=args.scope,
            next_action=claim.next_action or "reach the next verified checkpoint",
        )
        sent = store.send(request, require_live_claim=False)
        payload["resume_offer"] = {
            "message_id": sent.message.message_id,
            "recipient_session_id": sent.message.recipient_session_id,
            "idempotent_replay": sent.idempotent_replay,
            "delivery_mode": sent.local_host_delivery_capability.delivery_mode,
            "delivery_enforced": (
                sent.local_host_delivery_capability.delivery_mode == "enforced"
            ),
            "message_path": sent.message_path,
        }
    if args.queue_native_resume_offer and assessment.action == "notify_owner":
        offer = session_continuity.build_native_codex_resume_offer(
            assessment=assessment,
            project=args.project,
            scope=args.scope,
            next_action=claim.next_action or "reach the next verified checkpoint",
        )
        queued = subprocess.run(
            (
                args.codex,
                "queue",
                "--thread",
                offer.thread_id,
                "--message",
                offer.prompt,
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if queued.returncode != 0:
            detail = (queued.stderr or queued.stdout).strip()
            raise RuntimeError(f"native Codex resume queue failed: {detail}")
        receipt = session_continuity.parse_native_codex_queue_receipt(
            offer=offer,
            stdout=queued.stdout,
        )
        payload["native_resume_offer"] = receipt.model_dump(mode="json")
    if args.resume_offer_message_id:
        status = store.status(
            coordination_messages.MessageStatusRequest(
                message_id=args.resume_offer_message_id
            )
        )
        review = session_continuity.assess_resume_offer(
            assessment=assessment,
            status=status,
            successor_after=timedelta(minutes=args.successor_after_minutes),
        )
        payload["resume_offer_review"] = review.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['activity_state']}: {payload['reason_code']}; "
            f"action={payload['action']}; transfer_eligible=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
