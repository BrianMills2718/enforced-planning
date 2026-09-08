"""Sessions sharing a declared goal are grouped by identity, never by similarity.

parent_scope links a session's second lane to its first, so it is empty whenever
every session holds one lane -- the normal case, measured 0/12 on 2026-09-08. The
adjacency that does exist is between sessions, and broader_goal already carries
it: five separate sessions on one project declared a byte-identical goal.
"""
from __future__ import annotations

import dataclasses

import pytest

from enforced_planning.coordination_claims import (
    ClaimRecord,
    peer_claims_by_goal,
    render_peer_claim_groups,
)

GOAL = "Consolidate the validated product-design grammar into one canonical analyst runtime."


def _claim(scope: str, goal: str | None, *, agent: str = "chatgpt") -> ClaimRecord:
    """Build one claim with only the fields this behaviour reads varying."""
    values: dict[str, object] = {}
    for field in dataclasses.fields(ClaimRecord):
        if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            continue
        values[field.name] = [] if field.name in {"projects", "write_paths", "read_paths"} else ""
    values.update(
        agent=agent, scope=scope, broader_goal=goal, projects=["dodaf"],
        claim_type="write", intent=f"intent for {scope}", status="active",
    )
    return ClaimRecord(**values)  # type: ignore[arg-type]


def test_identical_goals_group_and_singletons_do_not_appear() -> None:
    claims = [_claim("a", GOAL), _claim("b", GOAL), _claim("c", "A different goal entirely.")]
    groups = peer_claims_by_goal(claims)
    assert list(groups) == [GOAL]
    assert {c.scope for c in groups[GOAL]} == {"a", "b"}


def test_a_near_miss_does_not_merge() -> None:
    """The safe direction to fail: a typo shows as no group, not as a false one."""
    claims = [_claim("a", GOAL), _claim("b", GOAL.replace("canonical", "canoncial"))]
    assert peer_claims_by_goal(claims) == {}


def test_claims_without_a_declared_goal_are_excluded() -> None:
    claims = [_claim("a", None), _claim("b", None), _claim("c", "   "), _claim("d", "")]
    assert peer_claims_by_goal(claims) == {}


def test_surrounding_whitespace_does_not_split_a_real_group() -> None:
    claims = [_claim("a", GOAL), _claim("b", f"  {GOAL}  ")]
    assert len(peer_claims_by_goal(claims)[GOAL]) == 2


def test_render_is_silent_when_nothing_is_shared() -> None:
    assert render_peer_claim_groups([_claim("a", GOAL)]) == []
    assert render_peer_claim_groups([]) == []


def test_render_names_every_member_of_a_group() -> None:
    claims = [_claim("a", GOAL), _claim("b", GOAL), _claim("c", GOAL, agent="claude-code")]
    text = "\n".join(render_peer_claim_groups(claims))
    for scope in ("a", "b", "c"):
        assert f"dodaf:{scope}" in text
    assert GOAL in text
    assert "claude-code" in text and "chatgpt" in text


def test_grouping_is_by_identity_not_membership_count() -> None:
    """Non-vacuity: substituting one member must change the rendered output.

    A test that only counted groups would pass on a substituted set, so assert
    the members themselves appear.
    """
    original = render_peer_claim_groups([_claim("a", GOAL), _claim("b", GOAL)])
    substituted = render_peer_claim_groups([_claim("a", GOAL), _claim("z", GOAL)])
    assert original != substituted
    assert "dodaf:b" in "\n".join(original)
    assert "dodaf:b" not in "\n".join(substituted)
