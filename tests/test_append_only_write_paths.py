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
        "yours=learnings.md <-> theirs=learnings.md"
    ]


def test_claiming_the_parent_directory_still_conflicts() -> None:
    """`learnings` reaches learnings.md, so it is not append-only."""
    left = _claim("broad-a", ["learnings"])
    right = _claim("broad-b", ["learnings"])
    assert cc._compute_overlapping_write_paths(left, right) == [
        "yours=learnings <-> theirs=learnings"
    ]


def test_an_ordinary_shared_path_still_conflicts() -> None:
    """The guard must not weaken exclusivity anywhere else."""
    left = _claim("code-a", ["scripts/log_learning.py"])
    right = _claim("code-b", ["scripts"])
    assert cc._compute_overlapping_write_paths(left, right) == [
        "yours=scripts/log_learning.py <-> theirs=scripts"
    ]


def test_a_mixed_claim_still_conflicts_on_its_mutable_half() -> None:
    """One append-only path does not launder the rest of a claim."""
    left = _claim("mixed-a", ["learnings/entries", "learnings.md"])
    right = _claim("mixed-b", ["learnings/entries", "learnings.md"])
    assert cc._compute_overlapping_write_paths(left, right) == [
        "yours=learnings.md <-> theirs=learnings.md"
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
        ("policy/proposals", True),
        ("policy/proposals/", True),
        ("policy/proposals/2026-09-02-a-thing.yaml", True),
        ("policy/proposals-archive", False),
        ("policy", False),
        ("policy/registry.yaml", False),
    ],
)
def test_append_only_classification(path: str, expected: bool) -> None:
    assert cc._is_append_only_path(path) is expected


def test_two_lanes_filing_different_proposals_do_not_contend() -> None:
    """Observed 2026-09-02: two sessions each adding a new proposal file blocked
    each other, while the refusal text said an append-only store never contends.
    """
    left = _claim("propose-a", ["policy/proposals"])
    right = _claim("propose-b", ["policy/proposals"])
    assert cc._compute_overlapping_write_paths(left, right) == []


def test_the_policy_registry_itself_still_contends() -> None:
    """registry.yaml is rewritten in place, so it must keep conflicting."""
    left = _claim("promote-a", ["policy/proposals", "policy/registry.yaml"])
    right = _claim("promote-b", ["policy/proposals", "policy/registry.yaml"])
    assert cc._compute_overlapping_write_paths(left, right) == [
        "yours=policy/registry.yaml <-> theirs=policy/registry.yaml"
    ]


def test_overlap_labels_say_which_side_is_yours() -> None:
    """The candidate's own path must be identifiable in a conflict message.

    Recorded twice in the register: an agent reads
    ``codex (their-lane: learnings <-> learnings/entries)``, sees another
    agent's name wrapped around both paths, and reports that the other lane is
    blocking it. The first path is its own. Labelling the sides is what makes
    the message readable without knowing the argument order of an internal
    function.
    """

    left = _claim("mine", ["learnings"])
    right = _claim("theirs", ["learnings/entries"])
    overlaps = cc._compute_overlapping_write_paths(left, right)

    assert overlaps == ["yours=learnings <-> theirs=learnings/entries"]
    # The candidate's path is the one prefixed "yours=", never the other's.
    assert overlaps[0].startswith("yours=learnings <->")
    assert "theirs=learnings/entries" in overlaps[0]
