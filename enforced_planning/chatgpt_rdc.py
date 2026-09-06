"""Compatibility bridge for ChatGPT sessions operating through Remote Desktop Commander.

Remote Desktop Commander does not expose a native per-conversation identifier to
remote shell processes. This adapter therefore requires one explicit, non-secret
``CHATGPT_SESSION_ID`` marker for the lifetime of a ChatGPT work lane, then
reuses the framework's existing typed claim-bootstrap transactions.

The package recognizes ChatGPT as a portable claim owner so persisted claims
remain readable by ordinary governance processes. The bridge still does not
register ChatGPT as a native hook client and exposes only the subset needed to
create and maintain governed worktree lanes.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Final

from enforced_planning import claim_bootstrap, coordination_claims

CHATGPT_AGENT: Final = "chatgpt"
CHATGPT_SESSION_ENV: Final = "CHATGPT_SESSION_ID"
CHATGPT_TRANSPORT: Final = "remote-desktop-commander"
SAFE_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "maintenance_worktree",
        "goal_worktree",
        "session_start_or_update",
        "heartbeat",
        "progress",
    }
)
_SESSION_MARKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{7,127}$")


class ChatGPTRDCError(claim_bootstrap.ClaimBootstrapError):
    """The ChatGPT/RDC compatibility boundary rejected a request."""


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Preserve the canonical bootstrap's fail-closed duplicate-key behavior."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ChatGPTRDCError(f"request-json contains duplicate object key {key!r}")
        result[key] = value
    return result


def _session_marker() -> str:
    """Return one explicit non-secret lane identity supplied by the RDC caller."""

    marker = os.environ.get(CHATGPT_SESSION_ENV, "").strip()
    if not marker:
        raise ChatGPTRDCError(
            f"{CHATGPT_SESSION_ENV} is required for ChatGPT/RDC work; set one stable non-secret lane id"
        )
    if _SESSION_MARKER.fullmatch(marker) is None:
        raise ChatGPTRDCError(
            f"{CHATGPT_SESSION_ENV} must be 8-128 characters using only letters, digits, '.', '_', or '-'"
        )
    return marker


def enable_chatgpt_runtime() -> str:
    """Require the RDC lane marker and ensure portable claim-owner registration.

    Package initialization registers the ChatGPT owner label and session-marker
    mapping for ordinary governance processes. These assignments are repeated
    defensively so vendored or partially upgraded installations fail toward the
    same explicit identity rather than borrowing another client's runtime.
    Native hook-client dispatch remains unchanged.
    """

    marker = _session_marker()
    if CHATGPT_AGENT not in coordination_claims.SUPPORTED_AGENTS:
        coordination_claims.SUPPORTED_AGENTS = (*coordination_claims.SUPPORTED_AGENTS, CHATGPT_AGENT)
    coordination_claims.SESSION_ENV_KEYS[CHATGPT_AGENT] = (CHATGPT_SESSION_ENV,)
    coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS[CHATGPT_AGENT] = CHATGPT_SESSION_ENV
    return f"{CHATGPT_AGENT}:{marker}"


def parse_request_json(raw_json: str) -> claim_bootstrap.ClaimBootstrapRequest:
    """Parse a strict canonical bootstrap request with ChatGPT as its owner.

    ``claim_bootstrap`` deliberately models only native clients. We preserve all
    of its field and operation validation by validating an otherwise identical
    request through that schema, then replace only the already-checked owner
    field with the compatibility identity.
    """

    try:
        payload = json.loads(raw_json, object_pairs_hook=_reject_duplicate_object_keys)
    except ChatGPTRDCError:
        raise
    except json.JSONDecodeError as exc:
        raise ChatGPTRDCError(f"request-json is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ChatGPTRDCError("request-json must be one JSON object")

    requested_agent = payload.get("agent")
    if requested_agent not in {None, CHATGPT_AGENT}:
        raise ChatGPTRDCError("ChatGPT/RDC requests cannot borrow another agent identity")
    operation = payload.get("operation")
    if operation not in SAFE_OPERATIONS:
        allowed = ", ".join(sorted(SAFE_OPERATIONS))
        raise ChatGPTRDCError(f"operation {operation!r} is outside the ChatGPT/RDC safety surface: {allowed}")

    canonical_payload = dict(payload)
    canonical_payload["agent"] = "codex"
    try:
        request = claim_bootstrap.parse_request_json(
            json.dumps(canonical_payload, separators=(",", ":"), sort_keys=True)
        )
    except claim_bootstrap.ClaimBootstrapError as exc:
        raise ChatGPTRDCError(str(exc)) from exc
    return request.model_copy(update={"agent": CHATGPT_AGENT})


def execute_request(request: claim_bootstrap.ClaimBootstrapRequest) -> dict[str, Any]:
    """Execute one approved ChatGPT/RDC request through canonical transactions."""

    if request.operation not in SAFE_OPERATIONS:
        raise ChatGPTRDCError(f"operation {request.operation!r} is outside the ChatGPT/RDC safety surface")
    if request.agent != CHATGPT_AGENT:
        raise ChatGPTRDCError("request owner must be chatgpt at the compatibility boundary")

    expected_session_id = enable_chatgpt_runtime()
    payload = claim_bootstrap.execute_request(request)
    if payload.get("agent") != CHATGPT_AGENT or payload.get("session_id") != expected_session_id:
        raise ChatGPTRDCError("canonical bootstrap returned a different owner identity")
    return {**payload, "transport": CHATGPT_TRANSPORT}


__all__ = [
    "CHATGPT_AGENT",
    "CHATGPT_SESSION_ENV",
    "CHATGPT_TRANSPORT",
    "SAFE_OPERATIONS",
    "ChatGPTRDCError",
    "enable_chatgpt_runtime",
    "execute_request",
    "parse_request_json",
]
