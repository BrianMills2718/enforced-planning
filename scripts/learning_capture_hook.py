#!/usr/bin/env python3
# scope: global_by_design - the portable framework owns this client-neutral
# lifecycle adapter; the learning-disposition requirement applies to
# completed work in any governed project, not one project specifically
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

from pydantic import ValidationError  # noqa: E402

from enforced_planning.correction_learning import CorrectionAuditReceiptV1  # noqa: E402

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
    parser.add_argument(
        "--check-full-format",
        action="store_true",
        help=(
            "On an otherwise-allowed completed-work report, emit a non-blocking "
            "systemMessage naming any mandated closing-format field beyond "
            "Done/Learnings that is missing. Never blocks; default off so "
            "existing installs and tests are unaffected until explicitly opted in."
        ),
    )
    parser.add_argument(
        "--check-implicit-completion",
        action="store_true",
        help=(
            "On a report classified not_completed_work (no Done marker), emit a "
            "non-blocking systemMessage in either of two cases: (1) the "
            "transcript shows this turn committed, pushed, or merged (a Bash "
            "call containing 'git commit', 'git push', or 'gh pr merge') -- "
            "catching a completed-work turn that omitted the closing format "
            "entirely, which --check-full-format alone cannot see (it only runs "
            "when a report already passed the Done-marker gate); or (2) this is "
            "the 10th+ consecutive tool-using turn since the last turn that "
            "recorded a Learnings-shaped disposition -- catching a long "
            "investigation arc that ends in a bare ask with no commits anywhere "
            "in it, the shape case (1) structurally cannot see. Deliberately "
            "narrower than 'any tool used this turn': replayed against 489 real "
            "historical turns, that broader signal fired on 73% of them; the "
            "investigation-arc threshold was separately calibrated against 598 "
            "real not_completed_work turns and fires on 2.3% of them. Never "
            "blocks; default off. Silently skips when transcript_path is "
            "missing or unreadable."
        ),
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
    "Verification",
    "Policy",
    "Concerns",
    "Learnings",
    "Decisions",
    "Recommended next",
    "Need anything from human",
)
# Fields checked by --check-full-format beyond what classify_report() already
# enforces on its own (Done gates completed-work detection; Learnings has its
# own dedicated block_* checks). This tuple is deliberately the remainder.
_FULL_FORMAT_REMAINING_FIELDS = tuple(
    name for name in REPORT_FIELD_NAMES if name not in ("Done", "Learnings")
)
_REPORT_FIELD_PATTERN = re.compile(
    rf"^[ \t]*(?:[-*][ \t]+)?(?:"
    rf"\*\*(?P<bold>{'|'.join(map(re.escape, REPORT_FIELD_NAMES))}):?\*\*"
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


def missing_closing_fields(report: str) -> tuple[str, ...]:
    """Which mandated closing-format fields, beyond Done/Learnings, are absent.

    Presence-only: this checks whether a field marker exists, not whether its
    content is substantively correct (e.g. whether a Decision-typed "Need
    anything from human" actually states a confidence level). Judging content
    quality is a meaning question the no-prose-string-matching policy reserves
    for a light LLM, not a regex; this function stays mechanical on purpose.
    """
    return tuple(
        name for name in _FULL_FORMAT_REMAINING_FIELDS if report_field(report, name) is None
    )


_RECOMMENDATION_COMPLETE = re.compile(r"\bcomplete\b", re.IGNORECASE)
_RECOMMENDATION_OPEN = re.compile(r"\b(continuing|blocked)\b", re.IGNORECASE)
_SUBGOALS_EFFECTIVELY_NONE = re.compile(r"^\**none\**\.?$", re.IGNORECASE)


def contradictory_recommendation(report: str) -> str | None:
    """Return a detail string if Recommended-next and Active-subgoals disagree.

    Structural cross-field check only -- comparing two explicit field values
    against each other, not inferring what either one *means* -- so it stays
    inside the no-prose-string-matching policy the same way missing_closing_fields
    does. It will not catch a hedge that avoids these four words entirely; that
    broader problem needs a light-LLM classifier, a deliberately separate and
    more careful build.

    Motivating instance (2026-09-14): a closing report said `Recommended next:
    Complete for tonight.` while `Active subgoals: Other` still listed an
    unresolved item -- the exact contradiction this function is built to catch.
    """
    recommended = report_field(report, "Recommended next")
    subgoals = report_field(report, "Active subgoals")
    if recommended is None or subgoals is None:
        return None

    subgoals_are_none = bool(
        _SUBGOALS_EFFECTIVELY_NONE.match(subgoals.strip().strip("*_` "))
    )
    says_complete = bool(_RECOMMENDATION_COMPLETE.search(recommended))
    says_open = bool(_RECOMMENDATION_OPEN.search(recommended))

    if says_complete and not subgoals_are_none:
        return (
            "`Recommended next` claims completion while `Active subgoals` lists "
            "unresolved items. Resolve every listed subgoal and set `Active "
            "subgoals: None`, or change `Recommended next` to `continuing`/"
            "`blocked` and move any human-owned item into `Need anything from "
            "human` as a properly typed Decision or Action."
        )
    if subgoals_are_none and says_open and not says_complete:
        return (
            "`Active subgoals` is None but `Recommended next` says "
            "continuing/blocked -- these disagree on whether the session goal "
            "is done. State completion if it is, or name the remaining "
            "subgoal in `Active subgoals` if it is not."
        )
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


# enforced-planning/project-meta closeout-disposition-must-cover-ask-only-turns
# (proposal filed 2026-09-02, strengthened 2026-09-14): classify_report()'s
# "not_completed_work" branch fires whenever a response has no literal Done
# marker -- including a completed-work turn that simply never used that exact
# marker syntax. That branch skips every downstream check, so such a turn is
# currently invisible to the whole mechanism, not merely exempt from one
# field. This detector adds an independent, orthogonal signal so main() can
# still raise a (non-blocking) flag on that case. It intentionally does not
# touch classify_report() itself: that function stays a pure string->decision
# mapping, unit-testable without a transcript fixture, matching how every
# other check in this file is structured.
#
# First cut used "any tool beyond Read/Grep/Glob/WebFetch/WebSearch" as the
# signal and was replaced before landing: replayed against 15 real historical
# transcripts (489 real turns), it fired on 324/442 (73%) of
# not_completed_work turns -- almost every ordinary mid-task turn touches a
# file or runs a command, so that signal mostly detects "did anything at
# all," not "completed work that needed a closing report." CLAUDE.md's own
# framing of the completion boundary is narrower: "Commit coherent authorized
# increments and push recoverable checkpoints" -- a durable, published change,
# not any tool call. Scoped to that instead: a git commit, a git push, or a
# PR merge in the current turn.
_DURABLE_ACTION_BASH_MARKERS = ("git commit", "git push", "gh pr merge")

# Calibrated against 598 real not_completed_work turns sampled from 15 real
# transcripts (2026-09-14): count distribution 0:158 1:154 2:97 3:58 4:38
# 5:24 6:16 7:16 8:13 9:10 10:5 11:4 12:3 13:2. Threshold 10 fires on 2.3%
# (14/598) -- rare enough to stay a real signal, not noise, and manual review
# of the count>=8 sample fires showed genuine long investigation arcs
# (including ones that read as completed work described in prose without a
# formal Done/Learnings marker), not routine mid-task narration.
_INVESTIGATION_ARC_THRESHOLD = 10


def _is_tool_result_only_content(content: object) -> bool:
    """Return whether a transcript event's message content is pure tool output.

    A real user turn's content is a string, or a list containing at least one
    non-tool_result block (text, image, document). A list of nothing but
    tool_result blocks is the transcript's own representation of tool output
    being handed back to the assistant, not a new prompt -- see the Claude
    Code transcript schema `assertion_evidence_gate.py` (agent-skills) already
    parses the same way for a different purpose.
    """
    return isinstance(content, list) and bool(content) and all(
        isinstance(item, dict) and item.get("type") == "tool_result" for item in content
    )


def _bash_command_took_durable_action(command: object) -> bool:
    """Return whether a Bash tool_use's command committed, pushed, or merged.

    Substring match, not a shell parse -- deliberately coarse. A false
    positive (e.g. the phrase "git commit" inside a quoted string being
    grepped for) only produces an unwanted advisory nudge, never a block; a
    false negative just means this specific turn goes unflagged, same as
    today. Precision is not worth the complexity for a non-blocking signal.
    """
    return isinstance(command, str) and any(
        marker in command for marker in _DURABLE_ACTION_BASH_MARKERS
    )


def turn_took_durable_action(transcript_path: str | Path | None) -> bool | None:
    """Return whether the turn since the last real user prompt committed,
    pushed, or merged (a Bash tool_use containing "git commit", "git push",
    or "gh pr merge").

    Returns ``None`` when the transcript is missing, unreadable, or contains
    no parseable JSON lines -- callers must treat that as "unknown, do not
    flag" and never silently coerce it to False.
    """
    if not transcript_path:
        return None
    try:
        raw = Path(transcript_path).expanduser().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    if not events:
        return None
    boundary = 0
    for index, event in enumerate(events):
        if event.get("type") != "user":
            continue
        content = event.get("message", {}).get("content")
        if not _is_tool_result_only_content(content):
            boundary = index
    took_action = False
    for event in events[boundary:]:
        if event.get("type") != "assistant":
            continue
        content = event.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "Bash":
                continue
            if _bash_command_took_durable_action(block.get("input", {}).get("command")):
                took_action = True
    return took_action


def _is_human_prompt_event(event: dict[str, Any]) -> bool:
    """Whether a ``user`` event is a prompt a person sent, as opposed to text the
    harness injected into the same turn: Stop-hook feedback, system reminders and
    peer-session messages carry ``isMeta``; background-task notices carry a
    non-human ``origin.kind``. Events with neither marker (older transcripts)
    count as prompts."""
    if event.get("isMeta"):
        return False
    origin = event.get("origin")
    kind = origin.get("kind") if isinstance(origin, dict) else None
    return kind in (None, "human")


def _split_transcript_into_turns(transcript_path: str | Path | None) -> list[list[dict[str, Any]]] | None:
    """Split a transcript into turns, each starting at one real user-prompt
    boundary (inclusive) and running up to the next one (exclusive).

    Returns ``None`` (never an empty list standing in for it) on any read,
    parse, or no-real-boundary failure -- callers must treat that as
    "unknown", not "zero turns".
    """
    if not transcript_path:
        return None
    try:
        raw = Path(transcript_path).expanduser().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    if not events:
        return None
    boundaries: list[int] = []
    for index, event in enumerate(events):
        if event.get("type") != "user" or not _is_human_prompt_event(event):
            continue
        content = event.get("message", {}).get("content")
        if not _is_tool_result_only_content(content):
            boundaries.append(index)
    if not boundaries:
        return None
    return [
        events[start : boundaries[i + 1] if i + 1 < len(boundaries) else len(events)]
        for i, start in enumerate(boundaries)
    ]


def _turn_used_any_tool(turn_events: list[dict[str, Any]]) -> bool:
    for event in turn_events:
        if event.get("type") != "assistant":
            continue
        content = event.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        if any(isinstance(block, dict) and block.get("type") == "tool_use" for block in content):
            return True
    return False


def _turn_assistant_text(turn_events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for event in turn_events:
        if event.get("type") != "assistant":
            continue
        content = event.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(parts)


def investigation_turns_since_last_disposition(transcript_path: str | Path | None) -> int | None:
    """How many consecutive recent turns used a tool and recorded no
    Learnings-shaped disposition of their own, counted backward from the
    current (most recent) turn.

    Targets the shape --check-implicit-completion's commit/push/merge
    signal structurally cannot see at all: a multi-turn investigation that
    produces a genuine finding and correctly ends in a bare decision-ask
    (per the human-decision-gets-its-own-turn policy) with no commits
    anywhere in it -- the exact original 2026-09-02 incident
    closeout-disposition-must-cover-ask-only-turns was proposed for. A
    turn with no tool use at all (a pure read-and-answer exchange) breaks
    the count; a turn that already carries its own Learnings-shaped
    disposition also breaks it, in both cases treating that point as
    "already accounted for" rather than counting through it.

    Returns ``None`` (never 0-as-unknown) when the transcript cannot be
    split into turns at all.
    """
    turns = _split_transcript_into_turns(transcript_path)
    if turns is None:
        return None
    count = 0
    for turn_events in reversed(turns):
        text = _turn_assistant_text(turn_events)
        if text and report_field(text, "Learnings") is not None:
            break
        if not _turn_used_any_tool(turn_events):
            break
        count += 1
    return count


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
        # A re-fired Stop (stop_hook_active) used to blanket-allow here on the
        # assumption that the first refusal already delivered the recovery
        # instruction and nothing could change before the next check. That
        # assumption is false: the forced continuation's own response is new
        # input, and reprocessing it through the same classify_report/
        # correction-mode logic below is what step 1 of the contest/rebuttal
        # re-fire flow (135_correction_learning_gate_contest_design.md
        # section 3) requires -- a deterministic, zero-LLM-cost check that
        # the flagged problem was actually fixed, not a second free pass.
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
        else:
            output: dict[str, Any] = {}
            if args.emit_result:
                output["decision"] = "allow"
                output["classification"] = decision
                output["detail"] = detail
            if args.check_full_format and decision != "not_completed_work":
                advisories: list[str] = []
                missing = missing_closing_fields(report)
                if missing:
                    advisories.append("Closing format incomplete: missing " + ", ".join(missing) + ".")
                contradiction = contradictory_recommendation(report)
                if contradiction:
                    advisories.append(f"Closing format inconsistent: {contradiction}")
                if advisories:
                    output["systemMessage"] = (
                        " ".join(advisories) + " This is advisory only -- it never blocks the turn."
                    )
            if args.check_implicit_completion and decision == "not_completed_work":
                if turn_took_durable_action(payload.get("transcript_path")):
                    output["systemMessage"] = (
                        "This turn committed, pushed, or merged but the response has no "
                        "**Done** marker, so the mandated closing-format check never ran on "
                        "it. If this was completed work, add the closing format (Session "
                        "goal/Active subgoals/Done/Policy/Concerns/Learnings/Decisions/"
                        "Recommended next/Need anything from human). This is advisory only -- "
                        "it never blocks the turn."
                    )
                else:
                    investigation_count = investigation_turns_since_last_disposition(
                        payload.get("transcript_path")
                    )
                    if (
                        investigation_count is not None
                        and investigation_count >= _INVESTIGATION_ARC_THRESHOLD
                    ):
                        output["systemMessage"] = (
                            f"This is the {investigation_count}th consecutive turn that used "
                            "a tool without recording a Learnings-shaped disposition -- a "
                            "long investigation arc with no closing format anywhere in it. "
                            "If this reached a real finding, a completed fix, or a genuine "
                            "decision-ask, it should still close with the mandated format "
                            "(Session goal/Active subgoals/Done/Policy/Concerns/Learnings/"
                            "Decisions/Recommended next/Need anything from human), even when "
                            "the turn correctly ends in a bare ask with no commits. This is "
                            "advisory only -- it never blocks the turn."
                        )
            if output:
                print(json.dumps(output, sort_keys=True))
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        reason = f"learning-capture gate unavailable: {type(exc).__name__}: {exc}"
        print(json.dumps({"decision": "block", "reason": reason}))
    finally:
        if invocation is not None:
            invocation.complete(decision=telemetry_decision, reason_code=telemetry_reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
