#!/usr/bin/env python3
"""Require a learning disposition when an agent reports completed work.

The hook does not try to decide whether a reusable learning exists. It enforces
the observable boundary around that judgment: a completed-work report must say
either where the learning was recorded or why no cross-agent learning emerged.
Each accepted or blocked disposition leaves a small machine-local receipt. The
portable framework owns this client-neutral lifecycle adapter; Project Meta owns
the learning register and policy.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from hook_receipts import DEFAULT_RECEIPT_ROOT, HookInvocation, start_hook_invocation
except ModuleNotFoundError:  # package-style tests import scripts.learning_capture_hook
    from scripts.hook_receipts import DEFAULT_RECEIPT_ROOT, HookInvocation, start_hook_invocation

DEFAULT_STATE_DIR = Path("~/.claude/coordination/learning-capture-v1")
DEFAULT_CODEX_CONFIG = Path("~/.codex/config.toml")
DEFAULT_CLAUDE_SETTINGS = Path("~/.claude/settings.json")
DEFAULT_OPENCLAW_RUNNER = Path("~/.openclaw/bin/run_task.py")
SUPPORTED_AGENTS = ("claude-code", "codex", "openclaw")
SCRIPT_PATH = Path(__file__).resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the client identity and deterministic state override."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=SUPPORTED_AGENTS)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--hook-receipt-dir", type=Path, default=DEFAULT_RECEIPT_ROOT)
    parser.add_argument(
        "--emit-result",
        action="store_true",
        help="Emit an allow result for lifecycle adapters that need an explicit response.",
    )
    parser.add_argument(
        "--check-install",
        action="store_true",
        help="Check that configured coding-agent completion paths use this policy gate.",
    )
    parser.add_argument("--codex-config", type=Path, default=DEFAULT_CODEX_CONFIG)
    parser.add_argument("--claude-settings", type=Path, default=DEFAULT_CLAUDE_SETTINGS)
    parser.add_argument("--openclaw-runner", type=Path, default=DEFAULT_OPENCLAW_RUNNER)
    return parser.parse_args(argv)


def _contains_command(value: object, expected: str) -> bool:
    """Return whether a parsed client config contains one exact command."""
    if isinstance(value, dict):
        return any(_contains_command(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_command(item, expected) for item in value)
    return value == expected


def check_install(
    codex_config: Path,
    claude_settings: Path,
    openclaw_runner: Path,
) -> dict[str, object]:
    """Parse client configs and report exact shared-gate wiring."""
    codex_path = codex_config.expanduser()
    claude_path = claude_settings.expanduser()
    with codex_path.open("rb") as handle:
        codex_payload = tomllib.load(handle)
    claude_payload = json.loads(claude_path.read_text(encoding="utf-8"))
    openclaw_path = openclaw_runner.expanduser().resolve()
    openclaw_source = openclaw_path.read_text(encoding="utf-8")
    codex_command = f"python3 {SCRIPT_PATH} --agent codex"
    claude_command = f"python3 {SCRIPT_PATH} --agent claude-code"
    codex_live = _contains_command(codex_payload.get("hooks", {}).get("Stop", []), codex_command)
    claude_live = _contains_command(claude_payload.get("hooks", {}).get("Stop", []), claude_command)
    openclaw_live = all(
        marker in openclaw_source
        for marker in (
            "OPENCLAW_LEARNING_CAPTURE_HOOK",
            "_apply_learning_capture_gate",
            "OPENCLAW_LEARNING_CAPTURE_REQUIRED",
        )
    )
    return {
        "schema_version": 1,
        "live": codex_live and claude_live and openclaw_live,
        "codex_stop_hook": codex_live,
        "claude_code_stop_hook": claude_live,
        "openclaw_completion_gate": openclaw_live,
        "openclaw_runner": str(openclaw_path),
        "script": str(SCRIPT_PATH),
    }


def read_event() -> dict[str, Any]:
    """Read the shared subset of native Claude Code and Codex Stop payloads."""
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise TypeError("hook input must be a JSON object")
    if payload.get("hook_event_name") != "Stop":
        raise ValueError("learning capture hook requires hook_event_name=Stop")
    for field in ("session_id", "last_assistant_message"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"Stop payload requires non-empty {field!r}")
    return payload


def report_field(report: str, name: str) -> str | None:
    """Return one CommonMark closing-report bullet by bold field name."""
    pattern = rf"[-*]\s*\*\*{re.escape(name)}\*\*\s*[-—:]?\s*(.+?)(?=\n[-*]\s*\*\*|\Z)"
    match = re.search(pattern, report, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


# A decline is only checkable when it points at something. These are the shapes a
# reference actually takes in practice: a register entry id, a commit sha, an
# agent-memory slug, or a path. Anything else is an assertion.
REFERENCE_PATTERNS = (
    r"\blrn-\d{8}T\d{6,}",              # learnings register entry id
    r"\b[0-9a-f]{7,40}\b",               # commit sha
    r"\b(?:project|feedback|user|reference)_[a-z0-9_]+\b",  # agent-memory slug
    r"\b[\w./-]+\.(?:md|json|ya?ml|py)\b",  # file path
    r"#\d+",                              # pull request or issue
)


def _names_a_reference(reason: str) -> bool:
    """Return whether a decline points at something a reader could open."""
    return any(re.search(pattern, reason, re.IGNORECASE) for pattern in REFERENCE_PATTERNS)


def classify_report(report: str) -> tuple[str, str]:
    """Return ``(decision, detail)`` for one final assistant report."""
    if report_field(report, "Done") is None:
        return "not_completed_work", "No completed-work report was present."

    disposition = report_field(report, "Learnings")
    if disposition is None:
        return (
            "block_missing",
            (
                "Completed work requires a Learnings disposition: record a reusable finding or lesson "
                "through /learned and cite project-meta/learnings.md, or state "
                "`None — <specific reason>`. "
            ),
        )

    # Strip markdown emphasis AND code spans: a disposition written as
    # `Recorded` -- correct content, ordinary formatting -- failed the
    # startswith check twice in one session and cost two round-trips.
    normalized = disposition.strip().strip("*_` ")
    if re.match(r"^recorded\b", normalized, re.IGNORECASE):
        if "learnings.md" not in normalized.casefold():
            return (
                "block_unverifiable_record",
                "A `Recorded` learning disposition must cite the canonical project-meta/learnings.md register.",
            )
        return "recorded", normalized

    none_match = re.match(r"^(none|no reusable learning)\b(?:\s*[-—:]\s*)?(.*)$", normalized, re.IGNORECASE | re.DOTALL)
    if none_match:
        reason = none_match.group(2).strip()
        if len(reason) < 20:
            return (
                "block_empty_none",
                (
                    "A `None` learning disposition requires a concrete reason of at least 20 characters; "
                    "do not use it as an empty bypass."
                ),
            )
        prior_claim = re.search(
            r"already\s+(?:been\s+)?(?:recorded|captured|covered|logged|filed)|"
            r"belongs\s+(?:in|to|elsewhere)|lives\s+in|covered\s+by",
            reason,
            re.IGNORECASE,
        )
        if prior_claim and not _names_a_reference(reason):
            return (
                "block_unreferenced_decline",
                (
                    "A decline that claims something is already recorded must name it: an entry id "
                    "(lrn-...), a commit sha, a memory slug, or a file path. Measured across 296 closing "
                    "reports, 51% of `already recorded` declines cited nothing at all, which makes the "
                    "reason unfalsifiable. Cite what you are deferring to, or record the finding."
                ),
            )
        return "none", reason

    return (
        "block_invalid",
        (
            "Learnings must start with `Recorded` and cite project-meta/learnings.md, or start with "
            "`None` and give a concrete reason. "
            # This sentence exists because the gate was read as a work order.
            # On 2026-08-28 a session answered a refusal on form by recording the
            # entry: it invoked a skill, tripped three read-first gates, created a
            # coordination claim and a worktree, pushed a commit to project-meta
            # main, and closed the lane -- while nominally blocked awaiting the
            # user, who had not spoken since before the refusal. Rewriting one
            # line would have cleared it equally. A control whose cheapest
            # satisfying action is also its largest is pointed the wrong way, and
            # this is the moment the agent is trying to stop, which is the worst
            # moment to start anything.
            #
            # The first fix overcorrected. It told the agent to defer whenever
            # recording "would need a worktree, a claim, a push" -- which is the
            # only way to record anything, so it read as never record. Within two
            # turns the agent that wrote it had declined twice on those grounds,
            # once for a finding the user then asked why it had not written down.
            # The condition is being blocked on someone else, not the ordinary
            # cost of the register.
            "Fixing the line is a complete response. Recording costs a lane and a push; that is "
            "the ordinary price of the register and not a reason to skip it -- if you learned "
            "something, write it down. The one case to defer is being blocked: if you are waiting "
            "on the user and they have not answered, do not start work to clear this gate. Write "
            "`None -- not recorded because <reason>` and stop."
        ),
    )


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Write one private receipt atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_receipt(
    *,
    state_dir: Path,
    agent: str,
    session_id: str,
    report: str,
    decision: str,
    detail: str,
) -> Path:
    """Persist one digest-addressed disposition without storing transcript text."""
    state_root = state_dir.expanduser().resolve()
    session_digest = hashlib.sha256(f"{agent}\0{session_id}".encode()).hexdigest()[:32]
    report_digest = hashlib.sha256(report.encode()).hexdigest()
    receipt_path = state_root / session_digest / f"{report_digest[:32]}.json"
    lock_path = state_root / f".{session_digest}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        _atomic_write(
            receipt_path,
            {
                "schema_version": 1,
                "agent": agent,
                "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest(),
                "report_sha256": report_digest,
                "decision": decision,
                "detail": detail[:500],
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )
    return receipt_path


def prior_recorded_receipt(
    *, state_dir: Path, agent: str, session_id: str
) -> Path | None:
    """Resolve an earlier accepted Recorded disposition for this exact session."""

    state_root = state_dir.expanduser().resolve()
    session_digest = hashlib.sha256(f"{agent}\0{session_id}".encode()).hexdigest()[:32]
    session_dir = state_root / session_digest
    if not session_dir.is_dir():
        return None
    for path in sorted(session_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (
            payload.get("agent") == agent
            and payload.get("decision") in {"recorded", "recorded_prior_receipt"}
        ):
            return path
    return None


def main(argv: list[str] | None = None) -> int:
    """Block an incomplete learning disposition and record the observed result."""
    args = parse_args(argv)
    if args.check_install:
        try:
            result = check_install(
                args.codex_config,
                args.claude_settings,
                args.openclaw_runner,
            )
        except (json.JSONDecodeError, OSError, tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
            print(json.dumps({"schema_version": 1, "live": False, "error": f"{type(exc).__name__}: {exc}"}))
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0 if result["live"] else 1
    if args.agent is None:
        raise SystemExit("--agent is required unless --check-install is used")
    invocation: HookInvocation | None = None
    telemetry_decision = "block"
    telemetry_reason = "hook_unavailable"
    emitted_output: list[str] = []

    def emit(value: str) -> None:
        emitted_output.append(value + "\n")
        print(value)

    try:
        payload = read_event()
        if payload.get("stop_hook_active"):
            # A re-fired Stop must not depend on receipt or state availability.
            # The first refusal already delivered the recovery instruction.
            return 0
        invocation = start_hook_invocation(
            hook_name="learning-capture",
            hook_version="2",
            script_path=Path(__file__).resolve(),
            payload=payload,
            receipt_root=args.hook_receipt_dir,
        )
        report = payload["last_assistant_message"]
        decision, detail = classify_report(report)
        disposition = report_field(report, "Learnings") or ""
        if decision == "block_invalid" and re.match(
            r"^already\s+recorded\b", disposition.strip().strip("*_` "), re.IGNORECASE
        ):
            prior = prior_recorded_receipt(
                state_dir=args.state_dir,
                agent=args.agent,
                session_id=payload["session_id"],
            )
            if prior is not None:
                decision = "recorded_prior_receipt"
                detail = f"Verified by earlier learning-capture receipt {prior.name}."
        telemetry_decision = "block" if decision.startswith("block_") else "allow"
        telemetry_reason = decision
        if decision != "not_completed_work":
            write_receipt(
                state_dir=args.state_dir,
                agent=args.agent,
                session_id=payload["session_id"],
                report=report,
                decision=decision,
                detail=detail,
            )
        if decision.startswith("block_"):
            emit(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": f"{detail} Receipt: {invocation.receipt_id}.",
                    }
                )
            )
        elif args.emit_result:
            emit(
                json.dumps(
                    {
                        "decision": "allow",
                        "classification": decision,
                        "detail": detail,
                    },
                    sort_keys=True,
                )
            )
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        reason = f"learning-capture gate unavailable: {type(exc).__name__}: {exc}"
        emit(json.dumps({"decision": "block", "reason": reason}))
    finally:
        if invocation is not None:
            invocation.complete(
                decision=telemetry_decision,
                reason_code=telemetry_reason,
                output="".join(emitted_output),
                client=args.agent,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
