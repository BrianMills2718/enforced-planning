#!/usr/bin/env python3
"""Prompt for and require a learning disposition around completed work.

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
import shlex
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError

from enforced_planning.correction_learning import CorrectionAuditReceiptV1

try:
    from hook_receipts import DEFAULT_RECEIPT_ROOT, HookInvocation, start_hook_invocation
except ModuleNotFoundError:  # package-style tests import scripts.learning_capture_hook
    from scripts.hook_receipts import DEFAULT_RECEIPT_ROOT, HookInvocation, start_hook_invocation

DEFAULT_STATE_DIR = Path("~/.claude/coordination/learning-capture-v1")
DEFAULT_CODEX_CONFIG = Path("~/.codex/config.toml")
DEFAULT_CLAUDE_SETTINGS = Path("~/.claude/settings.json")
DEFAULT_OPENCLAW_RUNNER = Path("~/.openclaw/bin/run_task.py")
DEFAULT_CORRECTION_RECEIPT_DIR = Path("~/.claude/coordination/correction-learning-v1")
SUPPORTED_AGENTS = ("claude-code", "codex", "openclaw")
SCRIPT_PATH = Path(__file__).resolve()
ATTENTION_MESSAGE = (
    "Learning checkpoint: decide now whether this user message corrects a claim, "
    "assumption, action, or handling mistake from the preceding assistant turn. "
    "If it does, record the reusable lesson through the learned skill in this turn; "
    "do not defer it to session close. If it does not, continue normally."
)


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
    parser.add_argument(
        "--correction-mode",
        choices=("off", "observe", "block"),
        default=os.environ.get("ENFORCED_PLANNING_CORRECTION_MODE", "off"),
    )
    parser.add_argument(
        "--correction-receipt-dir",
        type=Path,
        default=DEFAULT_CORRECTION_RECEIPT_DIR,
    )
    return parser.parse_args(argv)


def correction_receipt_path(root: Path, *, agent: str, session_id: str) -> Path:
    """Return the collision-resistant correction receipt for one native session."""
    digest = hashlib.sha256(f"{agent}\0{session_id}".encode()).hexdigest()[:32]
    return root.expanduser().resolve() / f"{digest}.json"


def read_correction_receipt(
    root: Path, *, agent: str, session_id: str
) -> CorrectionAuditReceiptV1 | None:
    """Load one validated correction receipt without inspecting transcript prose."""
    path = correction_receipt_path(root, agent=agent, session_id=session_id)
    if not path.is_file():
        return None
    receipt = CorrectionAuditReceiptV1.model_validate_json(path.read_text(encoding="utf-8"))
    if receipt.agent != agent or receipt.session_id != session_id:
        raise ValueError("correction receipt identity does not match Stop event")
    return receipt


def _is_learning_hook_command(value: object, agent: str) -> bool:
    """Return whether one config value invokes this hook for ``agent``."""
    if not isinstance(value, str):
        return False
    try:
        tokens = shlex.split(value)
    except ValueError:
        return False
    if len(tokens) != 4 or tokens[0] != "python3" or tokens[2:] != ["--agent", agent]:
        return False
    return Path(tokens[1]).expanduser().resolve() == SCRIPT_PATH


def _contains_command(value: object, agent: str) -> bool:
    """Return whether a parsed client config contains this hook command."""
    if isinstance(value, dict):
        return any(_contains_command(item, agent) for item in value.values())
    if isinstance(value, list):
        return any(_contains_command(item, agent) for item in value)
    return _is_learning_hook_command(value, agent)


def _codex_hook_hash(event_name: str, group: dict[str, Any], handler: dict[str, Any]) -> str:
    """Reproduce Codex's normalized command-hook trust fingerprint."""
    timeout = handler.get("timeout", 600)
    normalized_handler: dict[str, Any] = {
        "type": "command",
        "command": handler["command"],
        "timeout": max(1, int(timeout)),
        "async": bool(handler.get("async", False)),
    }
    if handler.get("statusMessage") is not None:
        normalized_handler["statusMessage"] = handler["statusMessage"]
    context_limit = handler.get("additionalContextLimit")
    if context_limit not in (None, 2500) and event_name == "UserPromptSubmit":
        normalized_handler["additionalContextLimit"] = context_limit
    identity: dict[str, Any] = {
        "event_name": re.sub(r"(?<!^)(?=[A-Z])", "_", event_name).lower(),
        "hooks": [normalized_handler],
    }
    matcher = group.get("matcher")
    if matcher:
        identity["matcher"] = matcher
    serialized = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def _codex_hook_operational_status(
    payload: dict[str, Any], config_path: Path, event_name: str
) -> dict[str, object]:
    """Report whether an exact configured Codex hook is enabled and trusted."""
    states = payload.get("hooks", {}).get("state", {})
    candidates: list[dict[str, object]] = []
    for group_index, group in enumerate(payload.get("hooks", {}).get(event_name, [])):
        if not isinstance(group, dict):
            continue
        for handler_index, handler in enumerate(group.get("hooks", [])):
            if not isinstance(handler, dict) or not _is_learning_hook_command(
                handler.get("command"), "codex"
            ):
                continue
            key = (
                f"{config_path.resolve()}:"
                f"{re.sub(r'(?<!^)(?=[A-Z])', '_', event_name).lower()}:"
                f"{group_index}:{handler_index}"
            )
            state = states.get(key, {}) if isinstance(states, dict) else {}
            current_hash = _codex_hook_hash(event_name, group, handler)
            enabled = state.get("enabled") is not False
            trusted = state.get("trusted_hash") == current_hash
            candidates.append(
                {
                    "key": key,
                    "enabled": enabled,
                    "trusted": trusted,
                    "current_hash": current_hash,
                }
            )
    return {
        "configured": bool(candidates),
        "operational": any(item["enabled"] and item["trusted"] for item in candidates),
        "candidates": candidates,
    }


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
    codex_stop = _codex_hook_operational_status(codex_payload, codex_path, "Stop")
    claude_stop_live = _contains_command(
        claude_payload.get("hooks", {}).get("Stop", []), "claude-code"
    )
    codex_prompt = _codex_hook_operational_status(
        codex_payload, codex_path, "UserPromptSubmit"
    )
    claude_prompt_live = _contains_command(
        claude_payload.get("hooks", {}).get("UserPromptSubmit", []), "claude-code"
    )
    openclaw_live = all(
        marker in openclaw_source
        for marker in (
            "OPENCLAW_LEARNING_CAPTURE_HOOK",
            "_apply_learning_capture_gate",
            "OPENCLAW_LEARNING_CAPTURE_REQUIRED",
        )
    )
    return {
        "schema_version": 2,
        "live": (
            codex_stop["operational"]
            and claude_stop_live
            and codex_prompt["operational"]
            and claude_prompt_live
            and openclaw_live
        ),
        "codex_stop_hook": codex_stop["configured"],
        "codex_stop_operational": codex_stop["operational"],
        "codex_stop_candidates": codex_stop["candidates"],
        "claude_code_stop_hook": claude_stop_live,
        "codex_prompt_hook": codex_prompt["configured"],
        "codex_prompt_operational": codex_prompt["operational"],
        "codex_prompt_candidates": codex_prompt["candidates"],
        "claude_code_prompt_hook": claude_prompt_live,
        "openclaw_completion_gate": openclaw_live,
        "openclaw_runner": str(openclaw_path),
        "script": str(SCRIPT_PATH),
    }


def read_event() -> dict[str, Any]:
    """Read a native Claude Code or Codex prompt/Stop payload."""
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise TypeError("hook input must be a JSON object")
    event_name = payload.get("hook_event_name")
    if event_name not in {"Stop", "UserPromptSubmit"}:
        raise ValueError(
            "learning capture hook requires hook_event_name=Stop or UserPromptSubmit"
        )
    required = ("session_id", "last_assistant_message") if event_name == "Stop" else ("session_id", "prompt")
    for field in required:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"{event_name} payload requires non-empty {field!r}")
    return payload


def write_attention_receipt(
    *, state_dir: Path, agent: str, session_id: str, payload: dict[str, Any]
) -> Path:
    """Persist a privacy-reduced prompt-time checkpoint for later liveness audit."""

    state_root = state_dir.expanduser().resolve()
    session_digest = hashlib.sha256(f"{agent}\0{session_id}".encode()).hexdigest()[:32]
    turn_identity = str(payload.get("turn_id") or payload["prompt"])
    event_digest = hashlib.sha256(
        f"{agent}\0{session_id}\0{turn_identity}".encode()
    ).hexdigest()[:32]
    receipt_path = state_root / session_digest / "attention" / f"{event_digest}.json"
    _atomic_write(
        receipt_path,
        {
            "schema_version": 1,
            "record_type": "learning_attention",
            "agent": agent,
            "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest(),
            "event_id_sha256": event_digest,
            "event_name": "UserPromptSubmit",
            "observed_at": datetime.now(UTC).isoformat(),
        },
    )
    return receipt_path


def attention_receipt_count(*, state_dir: Path, agent: str, session_id: str) -> int:
    """Count valid prompt-time checkpoints for one exact session."""

    state_root = state_dir.expanduser().resolve()
    session_digest = hashlib.sha256(f"{agent}\0{session_id}".encode()).hexdigest()[:32]
    attention_dir = state_root / session_digest / "attention"
    if not attention_dir.is_dir():
        return 0
    count = 0
    for path in attention_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (
            payload.get("record_type") == "learning_attention"
            and payload.get("agent") == agent
            and payload.get("session_id_sha256")
            == hashlib.sha256(session_id.encode()).hexdigest()
        ):
            count += 1
    return count


REPORT_FIELD_NAMES = (
    "Session goal",
    "Active subgoals",
    "Done",
    "Policy",
    "Concerns",
    "Learnings",
    "Decisions",
    "Recommended next",
    "Need anything from human",
)
_REPORT_FIELD_PATTERN = re.compile(
    rf"^[ \t]*(?:[-*][ \t]+)?(?:"
    rf"\*\*(?P<bold>{'|'.join(map(re.escape, REPORT_FIELD_NAMES))})\*\*"
    rf"[ \t]*(?:[-—:][ \t]*)?"
    rf"|(?P<plain>{'|'.join(map(re.escape, REPORT_FIELD_NAMES))})"
    rf"[ \t]*[-—:][ \t]*"
    rf")(?P<value>.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def report_field(report: str, name: str) -> str | None:
    """Return one closing-report field in Markdown or simple ``Name: value`` form."""
    matches = list(
        _REPORT_FIELD_PATTERN.finditer(report)  # prose-matching-exempt: parses explicit closeout field grammar
    )
    for index, match in enumerate(matches):
        field_name = match.group("bold") or match.group("plain")
        if field_name.casefold() != name.casefold():
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(report)
        return report[match.start("value") : end].strip()
    return None


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


def _actionable_failure(code: str, why: str, next_action: str) -> str:
    """Render one stable, copyable recovery contract for a blocking outcome."""
    return (
        f"[{code}] Why: {why} Next: {next_action} "
        "Verify: submit the corrected closing report; fixing the line is a complete response."
    )


# A closing report can state the "already recorded elsewhere" disposition
# unambiguously with a structured trailer placed right after the Learnings
# bullet, instead of leaving the hook to infer intent from the free-text
# prose below it -- the failure mode this file has hit before: a value
# wrapped in backticks or an unrecognized phrasing defeating a string/regex
# guess (see the `Recorded` normalization above). When this marker is
# present and well-formed it is trusted directly and the prior_claim /
# _names_a_reference prose heuristic below is never consulted for that
# report. When it is absent -- or present but malformed -- classification
# falls back completely unchanged to that prose heuristic: this hook fires
# for every other live session right now, and none of them know this syntax
# yet.
LEARNINGS_STATUS_MARKER = re.compile(
    r"<!--\s*learnings-status:\s*(?P<body>[^>]*?)\s*-->",
    re.IGNORECASE,
)


class MalformedLearningsStatusMarker(Exception):
    """A ``learnings-status`` marker was attempted but its syntax is invalid.

    This is deliberately a distinct outcome from "no marker present at all" --
    silently treating a broken attempt the same as a genuine absence would
    reproduce, in the new structured path, the exact silent-degradation
    failure this marker exists to remove from the old prose path. A reader
    who typed the marker and got it wrong needs to be told, not guessed past.
    """


def _parse_learnings_status_marker(disposition: str) -> dict[str, str] | None:
    """Return the structured trailer's fields, or ``None`` if no marker is present.

    Raises ``MalformedLearningsStatusMarker`` if a marker was attempted (the
    literal ``<!-- learnings-status:`` prefix is present) but does not parse
    into a valid ``status``/``ref`` pair -- that case must never fall back to
    the prose heuristic as if nothing had been written.
    """
    match = LEARNINGS_STATUS_MARKER.search(  # prose-matching-exempt: parses an explicit HTML status marker
        disposition
    )
    if match is None:
        return None
    tokens = match.group("body").split()
    if not tokens:
        raise MalformedLearningsStatusMarker("marker body is empty")
    fields = {"status": tokens[0]}
    for token in tokens[1:]:
        key, sep, value = token.partition("=")
        if sep and key and value:
            fields[key] = value
    if fields.get("status") == "prior-record" and fields.get("ref"):
        return fields
    raise MalformedLearningsStatusMarker(
        f"expected 'prior-record ref=<entry-id>', found status={fields.get('status')!r} "
        f"ref={fields.get('ref')!r}"
    )


def classify_report(report: str) -> tuple[str, str]:
    """Return ``(decision, detail)`` for one final assistant report."""
    if report_field(report, "Done") is None:
        return "not_completed_work", "No completed-work report was present."

    disposition = report_field(report, "Learnings")
    if disposition is None:
        return (
            "block_missing",
            _actionable_failure(
                "learning_capture.block_missing",
                "completed work has no Learnings disposition.",
                "Add exactly one line: `Learnings: recorded <lrn-entry-id>` or "
                "`Learnings: none — <concrete reason of at least 20 characters>`.",
            ),
        )

    # Strip markdown emphasis AND code spans: a disposition written as
    # `Recorded` -- correct content, ordinary formatting -- failed the
    # startswith check twice in one session and cost two round-trips.
    normalized = disposition.strip().strip("*_` ")
    if re.match(r"^recorded\b", normalized, re.IGNORECASE):
        if "learnings.md" not in normalized.casefold() and not re.search(
            REFERENCE_PATTERNS[0], normalized, re.IGNORECASE
        ):
            return (
                "block_unverifiable_record",
                _actionable_failure(
                    "learning_capture.block_unverifiable_record",
                    "the Recorded disposition does not identify a verifiable register entry.",
                    "Use `Learnings: recorded <lrn-entry-id>` (preferred) or cite "
                    "`project-meta/learnings.md`.",
                ),
            )
        return "recorded", normalized

    none_match = re.match(r"^(none|no reusable learning)\b(?:\s*[-—:]\s*)?(.*)$", normalized, re.IGNORECASE | re.DOTALL)
    if none_match:
        reason = none_match.group(2).strip()
        if len(reason) < 20:
            return (
                "block_empty_none",
                _actionable_failure(
                    "learning_capture.block_empty_none",
                    "the None disposition has no concrete reason of at least 20 characters.",
                    "Use `Learnings: none — <concrete reason of at least 20 characters>`.",
                ),
            )
        try:
            marker = _parse_learnings_status_marker(disposition)
        except MalformedLearningsStatusMarker as exc:
            return (
                "block_malformed_learnings_marker",
                _actionable_failure(
                    "learning_capture.block_malformed_learnings_marker",
                    f"the learnings-status marker is invalid: {exc}.",
                    "Use `<!-- learnings-status: prior-record ref=<entry-id> -->` "
                    "or remove the marker and use a plain-text disposition.",
                ),
            )
        if marker is not None:
            # Structured-first path: the report has unambiguously declared
            # this is a prior-record decline and named its reference. Trust
            # it directly -- no prose regex-guessing needed to reach the
            # decision.
            return "none", f"{reason} (learnings-status ref: {marker['ref']})"

        prior_claim = re.search(
            r"already\s+(?:been\s+)?(?:recorded|captured|covered|logged|filed)|"
            r"belongs\s+(?:in|to|elsewhere)|lives\s+in|covered\s+by",
            reason,
            re.IGNORECASE,
        )
        if prior_claim and not _names_a_reference(reason):
            return (
                "block_unreferenced_decline",
                _actionable_failure(
                    "learning_capture.block_unreferenced_decline",
                    "the disposition says the learning was already recorded but names no verifiable reference.",
                    "To name it, add its `lrn-...` entry id, commit SHA, memory slug, or file path; "
                    "otherwise record the finding.",
                ),
            )
        return "none", reason

    return (
        "block_invalid",
        _actionable_failure(
            "learning_capture.block_invalid",
            "the Learnings disposition is neither a recorded entry nor a concrete none reason.",
            (
            "Replace it with `Learnings: recorded <lrn-entry-id>` or "
            "`Learnings: none — <concrete reason of at least 20 characters>`. "
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
            "Recording costs a lane and a push; that is "
            "the ordinary price of the register and not a reason to skip it -- if you learned "
            "something, write it down. The one case to defer is being blocked: if you are waiting "
            "on the user and they have not answered, do not start work to clear this gate. Write "
            "`None -- not recorded because <reason>` and stop."
            ),
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
    attention_events: int = 0,
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
                "attention_events": attention_events,
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
            print(json.dumps({"schema_version": 2, "live": False, "error": f"{type(exc).__name__}: {exc}"}))
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0 if result["live"] else 1
    if args.agent is None:
        raise SystemExit("--agent is required unless --check-install is used")
    invocation: HookInvocation | None = None
    telemetry_decision = "block"
    telemetry_reason = "hook_unavailable"
    try:
        payload = read_event()
        if payload["hook_event_name"] == "UserPromptSubmit":
            attention_message = ATTENTION_MESSAGE
            attention_receipt_available = True
            try:
                invocation = start_hook_invocation(
                    hook_name="learning-attention",
                    hook_version="1",
                    script_path=Path(__file__).resolve(),
                    payload=payload,
                    receipt_root=args.hook_receipt_dir,
                )
                write_attention_receipt(
                    state_dir=args.state_dir,
                    agent=args.agent,
                    session_id=payload["session_id"],
                    payload=payload,
                )
            except (OSError, TypeError, ValueError) as exc:
                attention_receipt_available = False
                attention_message += (
                    " The attention receipt was unavailable; assess and record the "
                    f"learning manually ({type(exc).__name__})."
                )
            telemetry_decision = "allow"
            telemetry_reason = (
                "attention_injected"
                if attention_receipt_available
                else "attention_receipt_unavailable"
            )
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": attention_message,
                        }
                    },
                    sort_keys=True,
                )
            )
            return 0
        if payload.get("stop_hook_active"):
            # A re-fired Stop must not depend on receipt or state availability.
            # The first refusal already delivered the recovery instruction.
            return 0
        invocation = start_hook_invocation(
            hook_name="learning-capture",
            hook_version="3",
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
        if (
            args.correction_mode != "off"
            and decision != "not_completed_work"
            and not decision.startswith("block_")
        ):
            try:
                correction_receipt = read_correction_receipt(
                    args.correction_receipt_dir,
                    agent=args.agent,
                    session_id=payload["session_id"],
                )
            except (OSError, ValidationError, ValueError):
                correction_receipt = None
            if (
                correction_receipt is not None
                and correction_receipt.status == "correction_unresolved"
                and args.correction_mode == "block"
            ):
                decision = "block_unresolved_correction"
                detail = _actionable_failure(
                    "learning_capture.block_unresolved_correction",
                    "a validated correction audit found a user correction without a "
                    "matching same-session immutable learning.",
                    "Record it with the learned skill, then cite the new `lrn-...` entry id.",
                )
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
                attention_events=attention_receipt_count(
                    state_dir=args.state_dir,
                    agent=args.agent,
                    session_id=payload["session_id"],
                ),
            )
        if decision.startswith("block_"):
            print(
                json.dumps(
                    {
                        "decision": "block",
                        "reason": f"{detail} Receipt: {invocation.receipt_id}.",
                    }
                )
            )
        elif args.emit_result:
            print(
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
        print(json.dumps({"decision": "block", "reason": reason}))
    finally:
        if invocation is not None:
            invocation.complete(decision=telemetry_decision, reason_code=telemetry_reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
