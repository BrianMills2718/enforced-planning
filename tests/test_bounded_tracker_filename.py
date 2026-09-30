"""A tracker must never be written under a name it cannot later be updated under.

_atomic_write_session_tracker rewrites a tracker through a sibling named
".{filename}.XXXXXXXX.tmp" -- fourteen bytes the generator did not budget for. On
2026-09-09 a 242-byte tracker produced a 256-byte temp name against Linux's
255-byte limit, so every attempt to close that lane died with "OSError: [Errno 36]
File name too long" and the claim became permanent. The overrun came from
session_name, which is a slug of free-text goal wording.
"""

from __future__ import annotations

import errno
from dataclasses import replace
from pathlib import Path

import pytest

from enforced_planning import session_contracts

LONG_GOAL = (
    "make the company planning plugin dashboard loop close without hand maintained "
    "allowlist edits before inside success teammates install the plugin and then keep "
    "it closing every two hours without anyone pressing a button"
)


def _contract(*, broader_goal: str, session_id: str = "claude-code:2c211b0f-a13a-4948"):
    return session_contracts.SessionContract.build(
        agent="claude-code",
        project="initiative-roadmap-dashboard",
        scope="feat/scheduled-refresh",
        intent="close the dashboard refresh loop",
        plan_ref=None,
        allow_unplanned=True,
        repo_root="~/code/inside-success/repos/initiative-roadmap-dashboard",
        worktree_path="~/code/inside-success/repos/initiative-roadmap-dashboard/worktrees/x",
        branch="feat/scheduled-refresh",
        session_id=session_id,
        broader_goal=broader_goal,
    )


def _temp_name_length(filename: str) -> int:
    """What _atomic_write_session_tracker will actually try to create."""
    return len(f".{filename}.XXXXXXXX.tmp".encode())


def test_a_long_goal_still_yields_an_updatable_filename(tmp_path) -> None:
    contract = _contract(broader_goal=LONG_GOAL)
    path = session_contracts.session_tracker_path(contract, tracker_dir=tmp_path)
    assert len(path.name.encode()) <= session_contracts.MAX_TRACKER_NAME_BYTES
    assert _temp_name_length(path.name) <= session_contracts.MAX_TRACKER_FILENAME_BYTES


def test_the_unbounded_name_would_have_overflowed(tmp_path) -> None:
    """Pin the defect itself, so a regression is visible rather than theoretical."""
    contract = _contract(broader_goal=LONG_GOAL)
    unbounded = (
        f"{contract.agent}__{contract.project}__"
        f"{contract.session_id.replace(':', '-')}__{contract.session_name}.yaml"
    )
    assert _temp_name_length(unbounded) > session_contracts.MAX_TRACKER_FILENAME_BYTES


def test_identity_prefix_survives_truncation(tmp_path) -> None:
    """find_session_tracker_path globs this prefix; truncation must not touch it."""
    contract = _contract(broader_goal=LONG_GOAL)
    path = session_contracts.session_tracker_path(contract, tracker_dir=tmp_path)
    expected_prefix = (
        f"{contract.agent}__{contract.project}__{contract.session_id.replace(':', '-')}__"
    )
    assert path.name.startswith(expected_prefix)
    assert path.name.endswith(".yaml")


def test_a_short_name_is_left_exactly_alone(tmp_path) -> None:
    contract = _contract(broader_goal="Short Goal")
    path = session_contracts.session_tracker_path(contract, tracker_dir=tmp_path)
    assert path.name.endswith(f"__{contract.session_name}.yaml")


def test_an_existing_legacy_long_tracker_keeps_its_own_path(tmp_path) -> None:
    """A record written before the bound existed must not be stranded.

    The name has to sit in the window the defect actually occupied: longer than the
    new bound so it would be shortened, but still creatable. The real one was 242
    bytes against a 255-byte limit, so 250 is representative.
    """
    contract = _contract(broader_goal="Short Goal")
    safe_session_id = contract.session_id.replace(":", "-")
    prefix = f"{contract.agent}__{contract.project}__{safe_session_id}__"
    padding = 250 - len(prefix.encode()) - len(".yaml".encode())
    assert padding > session_contracts.MAX_TRACKER_NAME_BYTES - len(prefix.encode()) - 5, (
        "fixture must exceed the bound or it proves nothing"
    )
    contract = replace(contract, session_name="g" * padding)

    legacy_name = f"{prefix}{contract.session_name}.yaml"
    assert len(legacy_name.encode()) == 250
    directory = tmp_path / contract.project
    directory.mkdir(parents=True)
    legacy = directory / legacy_name
    legacy.write_text("claim: {}\n")

    resolved = session_contracts.session_tracker_path(contract, tracker_dir=tmp_path)
    assert resolved == legacy, "the live tracker must keep its path, not start a second one"


def test_a_new_tracker_at_that_same_length_is_shortened(tmp_path) -> None:
    """Same length, no existing file: the bound applies rather than being skipped."""
    contract = _contract(broader_goal="Short Goal")
    safe_session_id = contract.session_id.replace(":", "-")
    prefix = f"{contract.agent}__{contract.project}__{safe_session_id}__"
    padding = 250 - len(prefix.encode()) - len(".yaml".encode())
    contract = replace(contract, session_name="g" * padding)

    resolved = session_contracts.session_tracker_path(contract, tracker_dir=tmp_path)
    assert len(resolved.name.encode()) <= session_contracts.MAX_TRACKER_NAME_BYTES
    assert _temp_name_length(resolved.name) <= session_contracts.MAX_TRACKER_FILENAME_BYTES


def test_an_unrepresentably_long_legacy_name_is_not_probed(tmp_path, monkeypatch) -> None:
    """A full goal slug can make the legacy-path existence check itself fail."""
    contract = _contract(broader_goal="long session goal " * 40)
    safe_session_id = contract.session_id.replace(":", "-")
    legacy = (
        tmp_path
        / contract.project
        / f"{contract.agent}__{contract.project}__{safe_session_id}__{contract.session_name}.yaml"
    )
    assert len(legacy.name.encode()) > session_contracts.MAX_TRACKER_FILENAME_BYTES

    original_is_file = Path.is_file
    probes = []

    def is_file(path: Path) -> bool:
        if path == legacy:
            probes.append(path)
            raise OSError(errno.ENAMETOOLONG, "File name too long", str(path))
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", is_file)
    resolved = session_contracts.session_tracker_path(contract, tracker_dir=tmp_path)

    assert not probes
    assert len(resolved.name.encode()) <= session_contracts.MAX_TRACKER_NAME_BYTES
    assert _temp_name_length(resolved.name) <= session_contracts.MAX_TRACKER_FILENAME_BYTES


def test_an_impossible_identity_prefix_fails_loud(tmp_path) -> None:
    """Truncating session_name cannot save a prefix that is itself too long."""
    with pytest.raises(ValueError, match="identity prefix alone exceeds"):
        session_contracts._bounded_tracker_filename(
            agent="a" * 120,
            project="p" * 120,
            safe_session_id="s" * 40,
            session_name="anything",
        )


def test_the_atomic_write_that_failed_now_succeeds(tmp_path) -> None:
    """Replay the exact operation that raised OSError 36, not a nearby variant."""
    contract = _contract(broader_goal=LONG_GOAL)
    path = session_contracts.session_tracker_path(contract, tracker_dir=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    session_contracts._atomic_write_session_tracker(path, {"claim": {"agent": contract.agent}})

    assert path.is_file()
    # And again, because the failure was on rewrite of an existing tracker.
    session_contracts._atomic_write_session_tracker(path, {"claim": {"agent": contract.agent}})
    assert path.is_file()
