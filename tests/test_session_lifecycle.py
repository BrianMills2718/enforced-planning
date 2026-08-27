"""Lifecycle behaviour that is not covered by the session CLI or contract tests."""

from __future__ import annotations

import pytest

from enforced_planning import coordination_messages, session_lifecycle


def test_mailbox_poll_without_a_live_claim_degrades_instead_of_raising() -> None:
    """`session-resume` is the recovery a preserved lane names, and it crashed.

    The preserved-lane check refuses a new claim and tells the operator to
    resume or take over the lane. A fresh runtime therefore arrives holding no
    live claim, the poll could not resolve its session, and `UnknownSessionError`
    escaped as an unhandled traceback -- leaving closing the lane as the only
    named route that worked, and making the recovery circular.
    """

    notice = session_lifecycle._poll_mailbox(
        agent="claude-code",
        project="project-meta",
        session_id="claude-code:no-live-claim-owns-this",
    )

    assert notice["polled"] is False
    assert notice["degraded_reason"] == "no_live_claim_owns_session"
    assert notice["active_count"] == 0
    assert notice["message_ids"] == []


def test_a_degraded_poll_is_not_reported_as_an_empty_inbox() -> None:
    """The guide forbids both halves of the obvious shortcut.

    An adapter failure "cannot truthfully assert mailbox debt or manufacture a
    block", so it must not crash; and it must not fabricate the opposite either.
    "no active messages" is what a successful empty poll says, so a failed poll
    must not be indistinguishable from one.
    """

    notice = session_lifecycle._poll_mailbox(
        agent="claude-code",
        project="project-meta",
        session_id="claude-code:no-live-claim-owns-this",
    )

    summary = notice["summary"]
    assert "NOT POLLED" in summary
    assert "no active messages" not in summary
    assert "may be pending" in summary


def test_other_mailbox_failures_still_surface() -> None:
    """Only the unresolvable-session case degrades; real faults stay loud."""

    def explode(**_: object) -> None:
        raise coordination_messages.CoordinationMessageError("store corrupt")

    original = coordination_messages.poll_session_inbox
    coordination_messages.poll_session_inbox = explode  # type: ignore[assignment]
    try:
        with pytest.raises(coordination_messages.CoordinationMessageError):
            session_lifecycle._poll_mailbox(
                agent="claude-code", project="project-meta", session_id="s"
            )
    finally:
        coordination_messages.poll_session_inbox = original  # type: ignore[assignment]
