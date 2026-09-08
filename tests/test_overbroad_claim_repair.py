"""An undeclared whole-repository claim warns; a deliberate reservation still blocks.

A claim holding ["."] because a scope was omitted has an owner who never reserved
those paths. coordination_claims already separates that from a bounded, deliberate
reservation, and push_safety previously ignored the distinction -- enforcing a
seven-hour lockout on 2026-09-08 with the same weight as a real conflict.
"""
from __future__ import annotations

import dataclasses

import pytest

from enforced_planning import push_safety
from enforced_planning.coordination_claims import ClaimRecord


def _claim(write_paths: list[str], broad_scope_mode: str | None) -> ClaimRecord:
    values: dict[str, object] = {}
    for field in dataclasses.fields(ClaimRecord):
        if field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            continue
        values[field.name] = [] if field.name in {"projects", "write_paths", "read_paths"} else ""
    values.update(agent="other-agent", scope="their-lane", projects=["repo"], claim_type="program",
                  intent="their work", status="active", write_paths=write_paths,
                  broad_scope_mode=broad_scope_mode)
    return ClaimRecord(**values)  # type: ignore[arg-type]


def test_undeclared_whole_repo_claim_is_overbroad() -> None:
    assert push_safety._is_overbroad_undeclared_claim(_claim(["."], None)) is True
    assert push_safety._is_overbroad_undeclared_claim(_claim(["."], "bootstrap")) is True


def test_a_deliberate_bounded_reservation_is_not_overbroad() -> None:
    """The whole point: someone who chose the whole repo keeps their block."""
    assert push_safety._is_overbroad_undeclared_claim(_claim(["."], "bounded")) is False


def test_a_narrow_claim_is_never_overbroad_whatever_its_mode() -> None:
    for mode in (None, "bootstrap", "bounded"):
        assert push_safety._is_overbroad_undeclared_claim(_claim(["scripts/x.py"], mode)) is False


def test_bounded_and_unclassified_are_distinguishable() -> None:
    """Non-vacuity: the two must not collapse, since collapsing them is the bug."""
    undeclared = push_safety._is_overbroad_undeclared_claim(_claim(["."], None))
    deliberate = push_safety._is_overbroad_undeclared_claim(_claim(["."], "bounded"))
    assert undeclared != deliberate
