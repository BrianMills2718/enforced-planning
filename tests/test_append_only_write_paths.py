"""Append-only stores must not create write-claim contention between lanes.

Entries under ``learnings/entries`` are immutable files created with an atomic
exclusive open under a unique id, so two lanes appending there cannot collide.
Before this, both lanes declaring that directory conflicted and the second one
could not be created at all, which is how learnings capture kept failing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enforced_planning import coordination_claims as cc  # noqa: E402


def _claim(scope: str, write_paths: list[str]) -> cc.ClaimRecord:
    return cc.ClaimRecord(
        agent="claude-code",
        claimed_at=None,
        expires_at=None,
        projects=["project-meta"],
        scope=scope,
        intent="test",
        claim_type="program",
        write_paths=write_paths,
        read_paths=[],
        worktree_path=None,
        repo_root=None,
        branch=scope,
        session_name=scope,
        broader_goal=None,
        tracker_path=None,
        session_id=scope,
        heartbeat_at=None,
        status="active",
        updated_at=None,
        parent_scope=None,
        notes=None,
        plan_ref=None,
        source_file=None,
        schema_version="2.0.0",
    )


def test_two_lanes_recording_learnings_do_not_conflict() -> None:
    """The case that blocked recording: both lanes claim the entry store."""
    left = _claim("record-a", ["learnings/entries"])
    right = _claim("record-b", ["learnings/entries"])
    assert cc._compute_overlapping_write_paths(left, right) == []


def test_nested_paths_inside_the_store_do_not_conflict() -> None:
    left = _claim("record-a", ["learnings/entries/2026"])
    right = _claim("record-b", ["learnings/entries"])
    assert cc._compute_overlapping_write_paths(left, right) == []


def test_the_shared_front_door_still_conflicts() -> None:
    """learnings.md is rewritten, not appended, so it stays exclusive."""
    left = _claim("render-a", ["learnings.md"])
    right = _claim("render-b", ["learnings.md"])
    assert cc._compute_overlapping_write_paths(left, right) == [
        "learnings.md <-> learnings.md"
    ]


def test_claiming_the_parent_directory_still_conflicts() -> None:
    """`learnings` reaches learnings.md, so it is not append-only."""
    left = _claim("broad-a", ["learnings"])
    right = _claim("broad-b", ["learnings"])
    assert cc._compute_overlapping_write_paths(left, right) == [
        "learnings <-> learnings"
    ]


def test_an_ordinary_shared_path_still_conflicts() -> None:
    """The guard must not weaken exclusivity anywhere else."""
    left = _claim("code-a", ["scripts/log_learning.py"])
    right = _claim("code-b", ["scripts"])
    assert cc._compute_overlapping_write_paths(left, right) == [
        "scripts/log_learning.py <-> scripts"
    ]


def test_a_mixed_claim_still_conflicts_on_its_mutable_half() -> None:
    """One append-only path does not launder the rest of a claim."""
    left = _claim("mixed-a", ["learnings/entries", "learnings.md"])
    right = _claim("mixed-b", ["learnings/entries", "learnings.md"])
    assert cc._compute_overlapping_write_paths(left, right) == [
        "learnings.md <-> learnings.md"
    ]


@pytest.mark.parametrize(
    "path,expected",
    [
        ("learnings/entries", True),
        ("learnings/entries/", True),
        ("learnings/entries/lrn-1.json", True),
        ("learnings/invalid_entries", True),
        ("learnings", False),
        ("learnings.md", False),
        ("learnings/entries-archive", False),
        ("scripts", False),
    ],
)
def test_append_only_classification(path: str, expected: bool) -> None:
    assert cc._is_append_only_path(path) is expected
