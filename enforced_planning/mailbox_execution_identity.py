"""Classify mailbox callbacks by proven native root/child identity.

Codex and Claude subagent callbacks retain the root ``session_id`` but expose
the child through ``agent_id``. Hook receipt correlation IDs are deliberately
excluded: they identify one callback, not one stable execution run.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from enforced_planning.session_target import SessionTargetError, effective_session_id

ExecutionRole = Literal["primary", "secondary"]


class PrimaryExecutionDecisionV1(BaseModel):
    """Root/child classification consumed before any mailbox access."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    role: ExecutionRole
    reason: Literal[
        "root_agent_id_absent",
        "root_agent_id_matches_session",
        "child_agent_id",
        "invalid_agent_identity",
    ]


def classify_hook_execution(
    payload: dict[str, object], *, client: Literal["codex", "claude-code"]
) -> PrimaryExecutionDecisionV1:
    """Classify one callback from stable native identity fields only.

    Root callbacks either omit ``agent_id`` or repeat the session identity.
    A distinct child ``agent_id`` is secondary. Invalid explicit agent
    identities fail closed as secondary. Every callback is classified from
    its current payload, so no stale binding cache can grant mailbox access.
    """

    raw_agent = payload.get("agent_id")
    if not isinstance(raw_agent, str) or not raw_agent.strip():
        return PrimaryExecutionDecisionV1(
            role="primary",
            reason="root_agent_id_absent",
        )

    parent_payload = dict(payload)
    parent_payload.pop("agent_id", None)
    try:
        effective_agent = effective_session_id(payload, client)
        effective_parent = effective_session_id(parent_payload, client)
    except SessionTargetError:
        return PrimaryExecutionDecisionV1(
            role="secondary",
            reason="invalid_agent_identity",
        )
    if effective_agent == effective_parent:
        return PrimaryExecutionDecisionV1(
            role="primary",
            reason="root_agent_id_matches_session",
        )
    return PrimaryExecutionDecisionV1(
        role="secondary",
        reason="child_agent_id",
    )


__all__ = ["PrimaryExecutionDecisionV1", "classify_hook_execution"]
