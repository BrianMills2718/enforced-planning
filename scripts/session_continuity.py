#!/usr/bin/env python3
"""Observe one claim owner and report resume-first continuity action."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal


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
DEFAULT_SUCCESSOR_OFFER_DIR = (
    Path.home() / ".local/state/enforced-planning/successor-custody-offers"
)
DEFAULT_INSTALLED_RESUME_SCRIPT = (
    Path.home() / ".codex/runtime/enforced-planning/scripts/session_resume.py"
)


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
    mode.add_argument(
        "--install-native-delivery-timer",
        action="store_true",
        help="Install one shared timer that queues bounded exact-owner Codex resume prompts.",
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
    parser.add_argument(
        "--deliver-native-resume-offers",
        action="store_true",
        help="During a shared sweep, durably queue at most one prompt per activity boundary.",
    )
    parser.add_argument("--codex", default="codex", help=argparse.SUPPRESS)
    parser.add_argument("--sender-session-id")
    parser.add_argument(
        "--resume-offer-message-id",
        help="Review one exact prior resume offer against current owner activity and receipts.",
    )
    parser.add_argument("--successor-after-minutes", type=int, default=30)
    parser.add_argument(
        "--launch-successor",
        action="store_true",
        help="Start one transient Codex fork only after the exact review permits launch.",
    )
    parser.add_argument(
        "--successor-offer-dir",
        type=Path,
        default=DEFAULT_SUCCESSOR_OFFER_DIR,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--installed-resume-script",
        type=Path,
        default=DEFAULT_INSTALLED_RESUME_SCRIPT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--systemd-run", default="systemd-run", help=argparse.SUPPRESS)
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
        and not args.install_native_delivery_timer
        and (not args.project or not args.scope)
    ):
        parser.error("exact assessment requires --project and --scope")
    if args.scan_all_live_claims and (args.project or args.scope):
        parser.error("--scan-all-live-claims cannot be combined with --project or --scope")
    if (args.scan_all_live_claims or args.install_observe_timer or args.install_native_delivery_timer) and (
        args.send_resume_offer
        or args.queue_native_resume_offer
        or args.resume_offer_message_id
        or args.launch_successor
    ):
        parser.error("shared observe mode cannot send or review resume offers")
    if args.deliver_native_resume_offers and not args.scan_all_live_claims:
        parser.error("--deliver-native-resume-offers requires --scan-all-live-claims")
    if args.install_observe_timer and args.deliver_native_resume_offers:
        parser.error("observe timer cannot enable native resume delivery")
    if args.send_resume_offer and args.queue_native_resume_offer:
        parser.error("select only one resume-offer delivery path")
    if args.launch_successor and not args.resume_offer_message_id:
        parser.error("--launch-successor requires --resume-offer-message-id")
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
        "next_action": claim.next_action,
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
        return {
            **base,
            "thread_source": activity.thread_source if activity is not None else "unknown",
            "parent_thread_id": activity.parent_thread_id if activity is not None else None,
            "assessment": assessment.model_dump(mode="json"),
            "error": None,
        }
    except (OSError, TypeError, ValueError) as exc:
        return {
            **base,
            "assessment": None,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def build_successor_offer_for_claim(
    *,
    review: session_continuity.ResumeOfferReviewV1,
    claim: coordination_claims.ClaimRecord,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> session_continuity.SuccessorCustodyOfferV1:
    """Resolve exact durable claim and Git state for a launch-eligible offer."""

    if not claim.source_file or not claim.worktree_path or not claim.branch:
        raise ValueError("successor custody offer requires claim file, worktree, and branch")
    if not claim.next_action:
        raise ValueError("successor custody offer requires an exact next action")
    claim_bytes = Path(claim.source_file).expanduser().resolve().read_bytes()
    resolved_worktree = Path(claim.worktree_path).expanduser().resolve()
    head = run(
        ("git", "-C", str(resolved_worktree), "rev-parse", "--verify", "HEAD^{commit}"),
        capture_output=True,
        text=True,
        check=False,
    )
    if head.returncode != 0:
        detail = (head.stderr or head.stdout).strip() or "Git revision unavailable"
        raise ValueError(f"successor custody offer cannot resolve worktree revision: {detail}")
    return session_continuity.build_successor_custody_offer(
        review=review,
        project=claim.primary_project(),
        scope=claim.scope,
        branch=claim.branch,
        worktree_path=str(resolved_worktree),
        claim_epoch_sha256=hashlib.sha256(claim_bytes).hexdigest(),
        head_revision=head.stdout.strip(),
        next_action=claim.next_action,
    )


def persist_successor_offer(
    offer: session_continuity.SuccessorCustodyOfferV1,
    *,
    offer_dir: Path = DEFAULT_SUCCESSOR_OFFER_DIR,
) -> Path:
    """Persist one immutable exact offer before any successor process starts."""

    target_dir = offer_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = target_dir / f"{offer.offer_id}.json"
    content = (offer.model_dump_json(indent=2) + "\n").encode("utf-8")
    if target.exists():
        if target.read_bytes() != content:
            raise RuntimeError(f"successor offer collision at {target}")
        return target
    temporary = target_dir / f".{offer.offer_id}.{secrets.token_hex(6)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def launch_codex_successor(
    launch: session_continuity.CodexSuccessorLaunchV1,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> session_continuity.CodexSuccessorLaunchReceiptV1:
    """Start one transient unit; launch acknowledgement is not custody acceptance."""

    completed = run(
        launch.argv,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or "no runtime detail"
        raise RuntimeError(f"Codex successor launch failed visibly: {detail}")
    stdout = completed.stdout.strip()
    if launch.systemd_unit not in stdout:
        raise RuntimeError("successor launcher did not acknowledge the exact transient unit")
    return session_continuity.CodexSuccessorLaunchReceiptV1(
        offer_id=launch.offer_id,
        offer_sha256=launch.offer_sha256,
        systemd_unit=launch.systemd_unit,
        runtime_stdout=stdout,
    )


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


def _delivery_journal_states(
    receipt_path: Path,
) -> dict[str, session_continuity.NativeCodexDeliveryJournalV1]:
    """Load the latest valid write-ahead state for every delivery correlation."""

    resolved = receipt_path.expanduser().resolve()
    if not resolved.exists():
        return {}
    states: dict[str, session_continuity.NativeCodexDeliveryJournalV1] = {}
    with resolved.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"continuity receipt journal has malformed JSON at line {line_number}"
                ) from exc
            if not isinstance(record, dict) or record.get("record_type") != "native_codex_resume_delivery":
                continue
            entry = session_continuity.NativeCodexDeliveryJournalV1.model_validate(record)
            states[entry.correlation_id] = entry
    return states


def _append_delivery_state(
    *,
    receipt_path: Path,
    offer: session_continuity.NativeCodexResumeOfferV1,
    state: Literal["intent", "accepted", "failed"],
    queued_submission_id: str | None = None,
    error: str | None = None,
) -> session_continuity.NativeCodexDeliveryJournalV1:
    entry = session_continuity.NativeCodexDeliveryJournalV1(
        owner_session_id=offer.owner_session_id,
        thread_id=offer.thread_id,
        correlation_id=offer.correlation_id,
        state=state,
        recorded_at=datetime.now(UTC),
        queued_submission_id=queued_submission_id,
        error=error,
    )
    _append_receipt(receipt_path, entry.model_dump(mode="json"))
    return entry


def _native_consumption_receipts(
    receipt_path: Path,
) -> dict[str, session_continuity.NativeCodexConsumptionReceiptV1]:
    """Load one immutable active-client consumption receipt per correlation."""

    resolved = receipt_path.expanduser().resolve()
    if not resolved.exists():
        return {}
    receipts: dict[str, session_continuity.NativeCodexConsumptionReceiptV1] = {}
    with resolved.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"continuity receipt journal has malformed JSON at line {line_number}"
                ) from exc
            if not isinstance(record, dict) or record.get("record_type") != (
                "native_codex_resume_consumption"
            ):
                continue
            receipt = session_continuity.NativeCodexConsumptionReceiptV1.model_validate(
                record
            )
            receipts[receipt.correlation_id] = receipt
    return receipts


def reconcile_native_resume_consumption(*, receipt_path: Path) -> list[dict[str, Any]]:
    """Promote queue acceptance only when the exact owner transcript consumed it."""

    deliveries = _delivery_journal_states(receipt_path)
    consumed = _native_consumption_receipts(receipt_path)
    results: list[dict[str, Any]] = []
    for correlation_id, delivery in deliveries.items():
        if delivery.state != "accepted" or correlation_id in consumed:
            continue
        transcript = coordination_claims.session_transcript_path(delivery.owner_session_id)
        if transcript is None:
            results.append(
                {
                    "correlation_id": correlation_id,
                    "action": "fail_visible",
                    "reason_code": "owner_transcript_unavailable",
                }
            )
            continue
        try:
            receipt = session_continuity.read_native_codex_consumption(
                owner_session_id=delivery.owner_session_id,
                correlation_id=correlation_id,
                queued_submission_id=delivery.queued_submission_id or "",
                transcript_path=transcript,
            )
        except (OSError, ValueError) as exc:
            results.append(
                {
                    "correlation_id": correlation_id,
                    "action": "fail_visible",
                    "reason_code": "owner_transcript_consumption_invalid",
                    "error": str(exc),
                }
            )
            continue
        if receipt is None:
            results.append(
                {
                    "correlation_id": correlation_id,
                    "action": "await_owner_consumption",
                    "reason_code": "native_queue_accepted_not_consumed",
                }
            )
            continue
        _append_receipt(receipt_path, receipt.model_dump(mode="json"))
        results.append(
            {
                "correlation_id": correlation_id,
                "action": "owner_resume_consumed",
                "reason_code": "correlated_owner_user_turn_observed",
                "queued_submission_id": receipt.queued_submission_id,
                "consumed_at": receipt.consumed_at.isoformat(),
            }
        )
    return results


def deliver_native_resume_offers(
    *,
    sweep: Mapping[str, Any],
    receipt_path: Path,
    codex: str = "codex",
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    """Queue once per unchanged owner activity boundary, failing closed on uncertainty."""

    states = _delivery_journal_states(receipt_path)
    results: list[dict[str, Any]] = []
    for item in sweep.get("items", []):
        assessment_data = item.get("assessment") if isinstance(item, dict) else None
        if not isinstance(assessment_data, dict) or assessment_data.get("action") != "notify_owner":
            continue
        base = {
            "project": item.get("project"),
            "scope": item.get("scope"),
            "session_id": item.get("session_id"),
        }
        thread_source = item.get("thread_source")
        if thread_source != "user":
            spawned = thread_source == "subagent"
            results.append(
                {
                    **base,
                    "action": "circuit_breaker",
                    "reason_code": (
                        "spawned_agent_native_queue_unsupported"
                        if spawned
                        else "thread_origin_not_verified_top_level"
                    ),
                    "parent_thread_id": item.get("parent_thread_id"),
                    "resume_condition": (
                        "resume from the exact parent when the active resource boundary "
                        "permits sub-agent execution"
                        if spawned
                        else "record valid top-level Codex session metadata before delivery"
                    ),
                }
            )
            continue
        try:
            assessment = session_continuity.ContinuityAssessmentV1.model_validate(
                assessment_data
            )
            offer = session_continuity.build_native_codex_resume_offer(
                assessment=assessment,
                project=str(item.get("project") or ""),
                scope=str(item.get("scope") or ""),
                next_action=str(item.get("next_action") or ""),
            )
            prior = states.get(offer.correlation_id)
            if prior is not None:
                reason = {
                    "accepted": "already_accepted_for_activity_boundary",
                    "intent": "prior_delivery_outcome_indeterminate",
                    "failed": "prior_delivery_failed_for_activity_boundary",
                }[prior.state]
                results.append(
                    {
                        **base,
                        "correlation_id": offer.correlation_id,
                        "action": "none" if prior.state == "accepted" else "fail_visible",
                        "reason_code": reason,
                        "queued_submission_id": prior.queued_submission_id,
                    }
                )
                continue
            _append_delivery_state(receipt_path=receipt_path, offer=offer, state="intent")
            queued = run(
                (codex, "queue", "--thread", offer.thread_id, "--message", offer.prompt),
                capture_output=True,
                text=True,
                check=False,
            )
            if queued.returncode != 0:
                detail = (queued.stderr or queued.stdout).strip() or "Codex queue exited nonzero"
                _append_delivery_state(
                    receipt_path=receipt_path,
                    offer=offer,
                    state="failed",
                    error=detail,
                )
                results.append(
                    {
                        **base,
                        "correlation_id": offer.correlation_id,
                        "action": "fail_visible",
                        "reason_code": "native_queue_rejected",
                        "error": detail,
                    }
                )
                continue
            receipt = session_continuity.parse_native_codex_queue_receipt(
                offer=offer,
                stdout=queued.stdout,
            )
            accepted_entry = _append_delivery_state(
                receipt_path=receipt_path,
                offer=offer,
                state="accepted",
                queued_submission_id=receipt.queued_submission_id,
            )
            states[offer.correlation_id] = accepted_entry
            results.append(
                {
                    **base,
                    "correlation_id": offer.correlation_id,
                    "action": "queued_owner_resume",
                    "reason_code": "native_queue_runtime_accepted",
                    "queued_submission_id": receipt.queued_submission_id,
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            results.append(
                {
                    **base,
                    "action": "fail_visible",
                    "reason_code": "native_queue_delivery_invalid",
                    "error": str(exc),
                }
            )
    return results


def run_native_delivery_sweep(
    *, notify_minutes: int, receipt_path: Path, codex: str = "codex"
) -> dict[str, Any]:
    """Observe and deliver owner-first prompts under one shared process lock."""

    with _exclusive_sweep(receipt_path):
        payload = build_observe_sweep(notify_minutes=notify_minutes)
        consumptions = reconcile_native_resume_consumption(receipt_path=receipt_path)
        deliveries = deliver_native_resume_offers(
            sweep=payload,
            receipt_path=receipt_path,
            codex=codex,
        )
        payload["mode"] = "native_resume_delivery"
        payload["native_resume_deliveries"] = deliveries
        payload["native_resume_consumptions"] = consumptions
        payload["native_resume_consumed_count"] = sum(
            item["action"] == "owner_resume_consumed" for item in consumptions
        )
        payload["native_resume_awaiting_consumption_count"] = sum(
            item["action"] == "await_owner_consumption" for item in consumptions
        )
        payload["native_resume_queued_count"] = sum(
            item["action"] == "queued_owner_resume" for item in deliveries
        )
        payload["native_resume_fail_visible_count"] = sum(
            item["action"] == "fail_visible" for item in deliveries
        )
        payload["native_resume_circuit_breaker_count"] = sum(
            item["action"] == "circuit_breaker" for item in deliveries
        )
        _append_receipt(receipt_path, payload)
        return payload


def render_observe_timer(
    *,
    script_path: Path,
    python_path: Path,
    receipt_path: Path,
    timer_minutes: int,
    notify_minutes: int,
    delivery_enabled: bool = False,
    codex_path: Path | None = None,
) -> tuple[str, str]:
    """Render one shared oneshot service and its bounded observe timer."""

    if timer_minutes <= 0 or notify_minutes <= 0:
        raise ValueError("timer and notification intervals must be positive")
    command_parts = [
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
    ]
    if delivery_enabled:
        if codex_path is None:
            raise ValueError("native delivery timer requires an exact Codex executable")
        command_parts.extend(
            (
                "--deliver-native-resume-offers",
                "--codex",
                str(codex_path.expanduser().resolve()),
            )
        )
    command = shlex.join(command_parts)
    description = (
        "Deliver bounded Codex owner-resume prompts"
        if delivery_enabled
        else "Observe authorized Codex work continuity"
    )
    service = (
        "[Unit]\n"
        f"Description={description}\n\n"
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
    delivery_enabled: bool = False,
    codex: str = "codex",
) -> dict[str, Any]:
    """Install one shared observe or bounded native-delivery timer."""

    resolved_codex: Path | None = None
    if delivery_enabled:
        discovered_codex = shutil.which(codex)
        if discovered_codex is None:
            raise ValueError(f"Codex executable is unavailable: {codex}")
        resolved_codex = Path(discovered_codex)
    service, timer = render_observe_timer(
        script_path=Path(__file__),
        python_path=Path(sys.executable),
        receipt_path=receipt_path,
        timer_minutes=timer_minutes,
        notify_minutes=notify_minutes,
        delivery_enabled=delivery_enabled,
        codex_path=resolved_codex,
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
        "mode": "native_resume_delivery" if delivery_enabled else "observe",
        "owner": "enforced-planning",
        "review_after": (datetime.now(UTC) + timedelta(days=14)).date().isoformat(),
        "retirement_condition": (
            "retire after 30 days with no decision-changing idle-owner observations, or replace "
            "when accepted-successor transfer is independently enforced"
        ),
        "timer_minutes": timer_minutes,
        "notify_minutes": notify_minutes,
        "receipt_path": str(receipt_path.expanduser().resolve()),
        "codex_path": str(resolved_codex.resolve()) if resolved_codex else None,
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
    if args.install_observe_timer or args.install_native_delivery_timer:
        payload = install_observe_timer(
            unit_dir=args.unit_dir,
            receipt_path=args.receipt_jsonl,
            timer_minutes=args.timer_minutes,
            notify_minutes=args.notify_minutes,
            delivery_enabled=args.install_native_delivery_timer,
            codex=args.codex,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.scan_all_live_claims:
        if args.deliver_native_resume_offers:
            payload = run_native_delivery_sweep(
                notify_minutes=args.notify_minutes,
                receipt_path=args.receipt_jsonl,
                codex=args.codex,
            )
        else:
            payload = run_observe_sweep(
                notify_minutes=args.notify_minutes,
                receipt_path=args.receipt_jsonl,
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.deliver_native_resume_offers and payload.get(
            "native_resume_fail_visible_count", 0
        ):
            return 1
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
    payload["successor_custody_offer"] = None
    payload["successor_launch"] = None
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
        if review.action == "launch_successor":
            successor_offer = build_successor_offer_for_claim(
                review=review,
                claim=claim,
            )
            payload["successor_custody_offer"] = successor_offer.model_dump(mode="json")
            if args.launch_successor:
                offer_path = persist_successor_offer(
                    successor_offer,
                    offer_dir=args.successor_offer_dir,
                )
                launch = session_continuity.build_codex_successor_launch(
                    offer=successor_offer,
                    offer_path=str(offer_path),
                    resume_script=str(args.installed_resume_script),
                    codex=args.codex,
                    systemd_run=args.systemd_run,
                )
                receipt = launch_codex_successor(launch)
                payload["successor_launch"] = receipt.model_dump(mode="json")
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
