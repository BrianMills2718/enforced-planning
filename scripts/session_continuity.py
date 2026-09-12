#!/usr/bin/env python3
"""Observe one claim owner and report resume-first continuity action."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
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
    session_lifecycle,
    session_process_fencing,
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


def _resolve_native_predecessor_process(
    offer: session_continuity.SuccessorCustodyOfferV1,
    *,
    codex: str,
) -> session_process_fencing.PredecessorProcessIdentityV1:
    codex_path = shutil.which(codex)
    if codex_path is None:
        raise ValueError("native successor launch cannot resolve the configured Codex executable")
    return session_process_fencing.resolve_predecessor_process(
        predecessor_session_id=offer.predecessor_session_id,
        worktree_path=offer.worktree_path,
        trusted_codex_executable=Path(codex_path),
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
    mode.add_argument(
        "--reconcile-native-resume-consumption",
        action="store_true",
        help="Reconcile and report exact transcript consumption without scanning or queuing.",
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
        "--launch-native-successors",
        action="store_true",
        help=(
            "Opt in to idempotent transient launch for exact verified native offers; "
            "launch acknowledgement is not custody acceptance."
        ),
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
        and not args.reconcile_native_resume_consumption
        and (not args.project or not args.scope)
    ):
        parser.error("exact assessment requires --project and --scope")
    if args.scan_all_live_claims and (args.project or args.scope):
        parser.error("--scan-all-live-claims cannot be combined with --project or --scope")
    if args.reconcile_native_resume_consumption and (
        args.project or args.scope or args.deliver_native_resume_offers
    ):
        parser.error(
            "--reconcile-native-resume-consumption cannot assess claims or deliver prompts"
        )
    if (
        args.scan_all_live_claims
        or args.install_observe_timer
        or args.install_native_delivery_timer
        or args.reconcile_native_resume_consumption
    ) and (
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
    if args.launch_native_successors and not (
        args.install_native_delivery_timer
        or (args.scan_all_live_claims and args.deliver_native_resume_offers)
    ):
        parser.error(
            "--launch-native-successors requires native delivery installation or sweep"
        )
    if args.notify_minutes <= 0 or args.timer_minutes <= 0:
        parser.error("notification and timer intervals must be positive")
    return args


def _assess_claim(claim: coordination_claims.ClaimRecord, *, notify_minutes: int) -> dict[str, Any]:
    """Produce one fail-visible observation without creating takeover authority."""

    worktree_path = getattr(claim, "worktree_path", None)
    claim_source_file = getattr(claim, "source_file", None)
    base = {
        "agent": claim.agent,
        "project": claim.primary_project(),
        "scope": claim.scope,
        "session_id": claim.session_id,
        "next_action": claim.next_action,
        "progress_at": claim.progress_at,
        "worktree_path": str(worktree_path) if worktree_path else None,
        "branch": getattr(claim, "branch", None),
        "claim_source_file": str(claim_source_file) if claim_source_file else None,
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
    actionable_by_session: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        assessment = item.get("assessment")
        session_id = item.get("session_id")
        if (
            isinstance(session_id, str)
            and isinstance(assessment, dict)
            and assessment.get("action") == "notify_owner"
        ):
            actionable_by_session.setdefault(session_id, []).append(item)
    for session_items in actionable_by_session.values():
        if len(session_items) <= 1:
            continue
        competing_claims = sorted(
            f"{item.get('project')}:{item.get('scope')}" for item in session_items
        )
        for item in session_items:
            assessment = item["assessment"]
            assessment.update(
                {
                    "continuity_disposition": "circuit_breaker",
                    "action": "fail_visible",
                    "reason_code": "multiple_auto_resume_claims_for_session",
                    "resume_condition": (
                        "narrow automatic resume custody to one active claim for this session"
                    ),
                }
            )
            item["competing_auto_resume_claims"] = competing_claims
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
        progress_fingerprint=offer.progress_fingerprint,
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


def _native_successor_launch_states(
    receipt_path: Path,
) -> dict[str, session_continuity.NativeCodexSuccessorLaunchJournalV1]:
    """Load the latest typed launch state for every exact successor offer."""

    resolved = receipt_path.expanduser().resolve()
    if not resolved.exists():
        return {}
    states: dict[str, session_continuity.NativeCodexSuccessorLaunchJournalV1] = {}
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
                "native_codex_successor_launch"
            ):
                continue
            entry = session_continuity.NativeCodexSuccessorLaunchJournalV1.model_validate(
                record
            )
            states[entry.offer_id] = entry
    return states


def _append_native_successor_launch_state(
    *,
    receipt_path: Path,
    launch: session_continuity.CodexSuccessorLaunchV1,
    state: Literal["intent", "started", "failed"],
    launch_receipt: session_continuity.CodexSuccessorLaunchReceiptV1 | None = None,
    error: str | None = None,
) -> session_continuity.NativeCodexSuccessorLaunchJournalV1:
    entry = session_continuity.NativeCodexSuccessorLaunchJournalV1(
        offer_id=launch.offer_id,
        offer_sha256=launch.offer_sha256,
        systemd_unit=launch.systemd_unit,
        state=state,
        recorded_at=datetime.now(UTC),
        launch_receipt=launch_receipt,
        error=error,
    )
    _append_receipt(receipt_path, entry.model_dump(mode="json"))
    return entry


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
    git_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    max_consumed_attempts_without_progress: int = 2,
) -> list[dict[str, Any]]:
    """Queue bounded consumed attempts per unchanged durable progress fingerprint."""

    if max_consumed_attempts_without_progress <= 0:
        raise ValueError("native resume consumed-attempt bound must be positive")
    states = _delivery_journal_states(receipt_path)
    consumed = _native_consumption_receipts(receipt_path)
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
            supplied_fingerprint = item.get("progress_fingerprint")
            if supplied_fingerprint is None:
                worktree_path = item.get("worktree_path")
                if not isinstance(worktree_path, str) or not worktree_path.strip():
                    raise ValueError("native resume delivery lacks an exact worktree")
                head = git_run(
                    (
                        "git",
                        "-C",
                        str(Path(worktree_path).expanduser().resolve()),
                        "rev-parse",
                        "--verify",
                        "HEAD^{commit}",
                    ),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if head.returncode != 0:
                    detail = (head.stderr or head.stdout).strip() or "Git revision unavailable"
                    raise ValueError(
                        f"native resume progress cannot resolve worktree revision: {detail}"
                    )
                progress_fingerprint = (
                    session_continuity.native_resume_progress_fingerprint(
                        progress_at=(
                            str(item["progress_at"])
                            if item.get("progress_at") is not None
                            else None
                        ),
                        head_revision=head.stdout.strip(),
                        next_action=str(item.get("next_action") or ""),
                    )
                )
            else:
                progress_fingerprint = str(supplied_fingerprint)
                if re.fullmatch(r"[0-9a-f]{64}", progress_fingerprint) is None:
                    raise ValueError("native resume delivery has an invalid progress fingerprint")
            consumed_correlations = sorted(
                (
                    correlation_id
                    for correlation_id, state in states.items()
                    if correlation_id in consumed
                    and state.progress_fingerprint == progress_fingerprint
                ),
                key=lambda correlation_id: (
                    consumed[correlation_id].consumed_at,
                    correlation_id,
                ),
            )
            consumed_without_progress = len(consumed_correlations)
            if consumed_without_progress >= max_consumed_attempts_without_progress:
                results.append(
                    {
                        **base,
                        "progress_fingerprint": progress_fingerprint,
                        "consumed_attempt_count": consumed_without_progress,
                        "consumed_correlation_ids": consumed_correlations,
                        "latest_consumed_correlation_id": consumed_correlations[-1],
                        "action": "circuit_breaker",
                        "reason_code": "native_resume_progress_not_observed",
                        "resume_condition": (
                            "record a changed Git revision, claim progress timestamp, or exact "
                            "next action before another automatic owner resume"
                        ),
                    }
                )
                continue
            offer = session_continuity.build_native_codex_resume_offer(
                assessment=assessment,
                project=str(item.get("project") or ""),
                scope=str(item.get("scope") or ""),
                next_action=str(item.get("next_action") or ""),
                progress_fingerprint=progress_fingerprint,
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


def prepare_native_successor_offers(
    *,
    sweep: Mapping[str, Any],
    deliveries: Sequence[Mapping[str, Any]],
    receipt_path: Path,
    offer_dir: Path = DEFAULT_SUCCESSOR_OFFER_DIR,
    git_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    offer_verifier: Callable[..., Mapping[str, Any]] = (
        session_lifecycle.verify_successor_custody_offer_state
    ),
) -> list[dict[str, Any]]:
    """Persist and verify exhausted-retry custody offers without launching."""

    states = _delivery_journal_states(receipt_path)
    consumed = _native_consumption_receipts(receipt_path)
    items = {
        (item.get("session_id"), item.get("project"), item.get("scope")): item
        for item in sweep.get("items", [])
        if isinstance(item, dict)
    }
    results: list[dict[str, Any]] = []
    for delivery_result in deliveries:
        if delivery_result.get("reason_code") != "native_resume_progress_not_observed":
            continue
        base = {
            "project": delivery_result.get("project"),
            "scope": delivery_result.get("scope"),
            "session_id": delivery_result.get("session_id"),
        }
        item = items.get((base["session_id"], base["project"], base["scope"]))
        try:
            if item is None:
                raise ValueError("native successor offer lacks its exact sweep claim")
            latest = str(delivery_result.get("latest_consumed_correlation_id") or "")
            state = states.get(latest)
            consumption = consumed.get(latest)
            if state is None or consumption is None:
                raise ValueError("native successor offer lacks exact consumed delivery evidence")
            claim_source = item.get("claim_source_file")
            worktree_path = item.get("worktree_path")
            branch = item.get("branch")
            if not all(isinstance(value, str) and value.strip() for value in (
                claim_source,
                worktree_path,
                branch,
            )):
                raise ValueError("native successor offer lacks exact claim, worktree, or branch")
            claim_bytes = Path(str(claim_source)).expanduser().resolve().read_bytes()
            resolved_worktree = Path(str(worktree_path)).expanduser().resolve()
            head = git_run(
                ("git", "-C", str(resolved_worktree), "rev-parse", "--verify", "HEAD^{commit}"),
                capture_output=True,
                text=True,
                check=False,
            )
            if head.returncode != 0:
                detail = (head.stderr or head.stdout).strip() or "Git revision unavailable"
                raise ValueError(f"native successor offer cannot resolve worktree revision: {detail}")
            current_fingerprint = session_continuity.native_resume_progress_fingerprint(
                progress_at=(
                    str(item["progress_at"])
                    if item.get("progress_at") is not None
                    else None
                ),
                head_revision=head.stdout.strip(),
                next_action=str(item.get("next_action") or ""),
            )
            if current_fingerprint != delivery_result.get("progress_fingerprint"):
                raise ValueError("native successor offer progress changed after retry review")
            offer = session_continuity.build_native_successor_custody_offer(
                delivery=state,
                consumption=consumption,
                consumed_attempt_count=int(delivery_result.get("consumed_attempt_count") or 0),
                project=str(item.get("project") or ""),
                scope=str(item.get("scope") or ""),
                branch=str(branch),
                worktree_path=str(resolved_worktree),
                claim_epoch_sha256=hashlib.sha256(claim_bytes).hexdigest(),
                head_revision=head.stdout.strip(),
                next_action=str(item.get("next_action") or ""),
            )
            offer_path = persist_successor_offer(offer, offer_dir=offer_dir)
            verification = offer_verifier(
                agent=str(item.get("agent") or ""),
                project=offer.project,
                scope=offer.scope,
                worktree_path=offer.worktree_path,
                branch=offer.branch,
                successor_custody_offer=offer,
            )
            safe_verification = (
                verification.get("action") == "successor_custody_offer_verified"
                and verification.get("record_type")
                == "successor_custody_offer_verification"
                and verification.get("successor_acceptance_required") is True
                and verification.get("successor_launch_allowed") is False
                and verification.get("custody_mutation_performed") is False
                and verification.get("transfer_eligible") is False
            )
            if not safe_verification:
                raise ValueError(
                    "native successor offer verifier returned an unsafe or invalid result"
                )
            results.append(
                {
                    **base,
                    "action": "successor_offer_prepared",
                    "reason_code": "bounded_native_retry_offer_preserved",
                    "offer_id": offer.offer_id,
                    "offer_sha256": (
                        session_continuity.successor_custody_offer_sha256(offer)
                    ),
                    "offer_path": str(offer_path),
                    "owner_resume_correlation_id": offer.owner_resume_correlation_id,
                    "successor_offer_verified": True,
                    "verification_record_type": verification["record_type"],
                    "verified_head_revision": verification.get("head_revision"),
                    "successor_acceptance_required": True,
                    "successor_launch_allowed": False,
                    "custody_mutation_performed": False,
                    "transfer_eligible": False,
                }
            )
        except (OSError, TypeError, ValueError) as exc:
            results.append(
                {
                    **base,
                    "action": "fail_visible",
                    "reason_code": "native_successor_offer_invalid",
                    "error": str(exc),
                }
            )
    return results


def launch_verified_native_successors(
    *,
    successor_offers: Sequence[Mapping[str, Any]],
    receipt_path: Path,
    resume_script: Path = DEFAULT_INSTALLED_RESUME_SCRIPT,
    codex: str = "codex",
    systemd_run: str = "systemd-run",
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    process_resolver: Callable[
        [session_continuity.SuccessorCustodyOfferV1],
        session_process_fencing.PredecessorProcessIdentityV1,
    ]
    | None = None,
) -> list[dict[str, Any]]:
    """Launch each exact verified offer at most once; never claim acceptance."""

    states = _native_successor_launch_states(receipt_path)
    results: list[dict[str, Any]] = []
    for prepared in successor_offers:
        if (
            prepared.get("action") != "successor_offer_prepared"
            or prepared.get("successor_offer_verified") is not True
        ):
            continue
        base = {
            "project": prepared.get("project"),
            "scope": prepared.get("scope"),
            "session_id": prepared.get("session_id"),
            "offer_id": prepared.get("offer_id"),
        }
        launch: session_continuity.CodexSuccessorLaunchV1 | None = None
        intent_written = False
        try:
            offer_path = Path(str(prepared.get("offer_path") or "")).expanduser().resolve()
            offer = session_continuity.SuccessorCustodyOfferV1.model_validate_json(
                offer_path.read_text(encoding="utf-8")
            )
            if offer.offer_id != prepared.get("offer_id"):
                raise ValueError("verified native successor result names a different offer")
            if session_continuity.successor_custody_offer_sha256(offer) != prepared.get(
                "offer_sha256"
            ):
                raise ValueError("verified native successor offer bytes changed before launch")
            predecessor_process = (
                process_resolver(offer)
                if process_resolver is not None
                else _resolve_native_predecessor_process(offer, codex=codex)
            )
            if (
                predecessor_process.predecessor_session_id
                != offer.predecessor_session_id
                or Path(predecessor_process.worktree_path).expanduser().resolve()
                != Path(offer.worktree_path).expanduser().resolve()
            ):
                raise ValueError(
                    "resolved predecessor process belongs to different offered custody"
                )
            launch = session_continuity.build_codex_successor_launch(
                offer=offer,
                offer_path=str(offer_path),
                resume_script=str(resume_script.expanduser().resolve()),
                predecessor_process_pid=predecessor_process.pid,
                predecessor_process_start_ticks=(
                    predecessor_process.process_start_ticks
                ),
                codex=codex,
                systemd_run=systemd_run,
            )
            prior = states.get(offer.offer_id)
            if prior is not None:
                if (
                    prior.offer_sha256 != launch.offer_sha256
                    or prior.systemd_unit != launch.systemd_unit
                ):
                    raise ValueError("prior successor launch belongs to different offer bytes")
                if prior.state == "started":
                    results.append(
                        {
                            **base,
                            "action": "successor_launch_already_started",
                            "reason_code": "exact_successor_launch_receipt_exists",
                            "launch_started": True,
                            "successor_session_id": None,
                            "successor_accepted": False,
                            "transfer_eligible": False,
                        }
                    )
                    continue
                results.append(
                    {
                        **base,
                        "action": "fail_visible",
                        "reason_code": (
                            "prior_successor_launch_outcome_indeterminate"
                            if prior.state == "intent"
                            else "prior_successor_launch_failed"
                        ),
                        "error": prior.error,
                    }
                )
                continue
            states[offer.offer_id] = _append_native_successor_launch_state(
                receipt_path=receipt_path,
                launch=launch,
                state="intent",
            )
            intent_written = True
            launch_receipt = launch_codex_successor(launch, run=run)
            states[offer.offer_id] = _append_native_successor_launch_state(
                receipt_path=receipt_path,
                launch=launch,
                state="started",
                launch_receipt=launch_receipt,
            )
            results.append(
                {
                    **base,
                    "action": "successor_launch_started",
                    "reason_code": "verified_native_successor_launch_acknowledged",
                    "launch_receipt": launch_receipt.model_dump(mode="json"),
                    "launch_started": True,
                    "successor_session_id": None,
                    "successor_accepted": False,
                    "transfer_eligible": False,
                }
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            if launch is not None and intent_written:
                states[launch.offer_id] = _append_native_successor_launch_state(
                    receipt_path=receipt_path,
                    launch=launch,
                    state="failed",
                    error=str(exc),
                )
            results.append(
                {
                    **base,
                    "action": "fail_visible",
                    "reason_code": "native_successor_launch_invalid",
                    "error": str(exc),
                }
            )
    return results


def run_native_delivery_sweep(
    *,
    notify_minutes: int,
    receipt_path: Path,
    codex: str = "codex",
    successor_offer_dir: Path = DEFAULT_SUCCESSOR_OFFER_DIR,
    launch_native_successors: bool = False,
    installed_resume_script: Path = DEFAULT_INSTALLED_RESUME_SCRIPT,
    systemd_run: str = "systemd-run",
    launch_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
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
        successor_offers = prepare_native_successor_offers(
            sweep=payload,
            deliveries=deliveries,
            receipt_path=receipt_path,
            offer_dir=successor_offer_dir,
        )
        successor_launches = (
            launch_verified_native_successors(
                successor_offers=successor_offers,
                receipt_path=receipt_path,
                resume_script=installed_resume_script,
                codex=codex,
                systemd_run=systemd_run,
                run=launch_run,
            )
            if launch_native_successors
            else []
        )
        payload["mode"] = "native_resume_delivery"
        payload["native_resume_deliveries"] = deliveries
        payload["native_resume_consumptions"] = consumptions
        payload["native_successor_offers"] = successor_offers
        payload["native_successor_launch_enabled"] = launch_native_successors
        payload["native_successor_launches"] = successor_launches
        payload["native_successor_offer_prepared_count"] = sum(
            item["action"] == "successor_offer_prepared" for item in successor_offers
        )
        payload["native_successor_offer_verified_count"] = sum(
            item.get("successor_offer_verified") is True for item in successor_offers
        )
        payload["native_successor_offer_fail_visible_count"] = sum(
            item["action"] == "fail_visible" for item in successor_offers
        )
        payload["native_successor_launch_started_count"] = sum(
            item["action"] in {"successor_launch_started", "successor_launch_already_started"}
            for item in successor_launches
        )
        payload["native_successor_launch_fail_visible_count"] = sum(
            item["action"] == "fail_visible" for item in successor_launches
        )
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


def run_native_consumption_reconciliation(*, receipt_path: Path) -> dict[str, Any]:
    """Reconcile exact owner turns and report all durable receipts without delivery."""

    with _exclusive_sweep(receipt_path):
        newly_reconciled = reconcile_native_resume_consumption(receipt_path=receipt_path)
        consumed = _native_consumption_receipts(receipt_path)
        payload = {
            "schema_version": "1.0",
            "record_type": "native_resume_consumption_reconciliation",
            "observed_at": datetime.now(UTC).isoformat(),
            "newly_reconciled": newly_reconciled,
            "consumed_count": len(consumed),
            "consumed_correlations": sorted(consumed),
            "native_queue_invoked": False,
            "successor_launch_allowed": False,
            "transfer_eligible": False,
        }
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
    successor_launch_enabled: bool = False,
    codex_path: Path | None = None,
) -> tuple[str, str]:
    """Render one shared oneshot service and its bounded observe timer."""

    if timer_minutes <= 0 or notify_minutes <= 0:
        raise ValueError("timer and notification intervals must be positive")
    if successor_launch_enabled and not delivery_enabled:
        raise ValueError("successor launch requires native delivery mode")
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
        if successor_launch_enabled:
            command_parts.append("--launch-native-successors")
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
    successor_launch_enabled: bool = False,
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
        successor_launch_enabled=successor_launch_enabled,
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
        "successor_launch_enabled": successor_launch_enabled,
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
    if args.reconcile_native_resume_consumption:
        payload = run_native_consumption_reconciliation(
            receipt_path=args.receipt_jsonl
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.install_observe_timer or args.install_native_delivery_timer:
        payload = install_observe_timer(
            unit_dir=args.unit_dir,
            receipt_path=args.receipt_jsonl,
            timer_minutes=args.timer_minutes,
            notify_minutes=args.notify_minutes,
            delivery_enabled=args.install_native_delivery_timer,
            successor_launch_enabled=args.launch_native_successors,
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
                launch_native_successors=args.launch_native_successors,
                installed_resume_script=args.installed_resume_script,
                systemd_run=args.systemd_run,
            )
        else:
            payload = run_observe_sweep(
                notify_minutes=args.notify_minutes,
                receipt_path=args.receipt_jsonl,
            )
        print(json.dumps(payload, indent=2, sort_keys=True))
        if args.deliver_native_resume_offers and (
            payload.get("native_resume_fail_visible_count", 0)
            or payload.get("native_successor_offer_fail_visible_count", 0)
            or payload.get("native_successor_launch_fail_visible_count", 0)
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
        worktree_path = getattr(claim, "worktree_path", None)
        if not isinstance(worktree_path, str) or not worktree_path.strip():
            raise ValueError("native resume delivery lacks an exact worktree")
        head = subprocess.run(
            (
                "git",
                "-C",
                str(Path(worktree_path).expanduser().resolve()),
                "rev-parse",
                "--verify",
                "HEAD^{commit}",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        if head.returncode != 0:
            detail = (head.stderr or head.stdout).strip() or "Git revision unavailable"
            raise ValueError(
                f"native resume progress cannot resolve worktree revision: {detail}"
            )
        offer = session_continuity.build_native_codex_resume_offer(
            assessment=assessment,
            project=args.project,
            scope=args.scope,
            next_action=claim.next_action or "reach the next verified checkpoint",
            progress_fingerprint=session_continuity.native_resume_progress_fingerprint(
                progress_at=claim.progress_at,
                head_revision=head.stdout.strip(),
                next_action=claim.next_action or "reach the next verified checkpoint",
            ),
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
                predecessor_process = _resolve_native_predecessor_process(
                    successor_offer,
                    codex=args.codex,
                )
                launch = session_continuity.build_codex_successor_launch(
                    offer=successor_offer,
                    offer_path=str(offer_path),
                    resume_script=str(args.installed_resume_script),
                    predecessor_process_pid=predecessor_process.pid,
                    predecessor_process_start_ticks=(
                        predecessor_process.process_start_ticks
                    ),
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
