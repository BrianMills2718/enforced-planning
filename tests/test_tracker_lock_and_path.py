"""Governance-tooling defects that made lanes impossible to close.

All three were observed on 2026-09-06 in one session, and none of them was an
agent contending with another agent. The claim registry did exactly what it
promises; these are the coordination machinery interfering with itself. Each
test is pinned to the observed failure rather than to the shape of the fix.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
# APPEND, never insert at 0. conftest.py puts scripts/ and scripts/meta/ at the
# front of sys.path so this repository's standalone scripts import each other;
# putting the repo root ahead of them shadows that and breaks collection for
# unrelated modules.
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from enforced_planning import session_contracts  # noqa: E402
from enforced_planning.coordination_claims import (  # noqa: E402
    _tracker_path_yaml_error,
)


class TestTrackerLockLivesOutsideTheRepository:
    """Closing a project-meta lane was impossible while its lock was healthy.

    `session_close.py` mutates the session tracker, which took a lock named
    beside the tracker file. `learnings.md` is in the repository root, so that
    sibling landed inside a tree a live lane claim had deliberately made
    read-only, and every closeout died on
    `PermissionError: '.learnings.md.lock'`. The identical closeout ran cleanly
    five times in the same session against a repository whose tracker was not
    in a locked root: the failure was the lock's LOCATION.
    """

    def test_the_lock_is_not_beside_the_tracker(self, tmp_path):
        tracker = tmp_path / "learnings.md"
        tracker.write_text("# not yaml\n", encoding="utf-8")
        lock = session_contracts.tracker_lock_path(tracker)
        assert lock.parent != tracker.parent, (
            "the lock is still a sibling of the tracker, so a tracker inside a "
            "read-only canonical checkout cannot be locked and its lane cannot "
            "be closed"
        )

    def test_locking_works_when_the_tracker_directory_is_read_only(self, tmp_path):
        """The exact condition: the tree is read-only, the lock must still take."""
        holder = tmp_path / "repo"
        holder.mkdir()
        tracker = holder / "learnings.md"
        tracker.write_text("schema_version: 1\n", encoding="utf-8")
        holder.chmod(0o555)
        try:
            with session_contracts.session_tracker_lock(tracker):
                pass
        finally:
            holder.chmod(0o755)

    def test_two_trackers_do_not_share_one_lock(self, tmp_path):
        a, b = tmp_path / "one.yaml", tmp_path / "two.yaml"
        a.write_text("x: 1\n", encoding="utf-8")
        b.write_text("x: 1\n", encoding="utf-8")
        assert session_contracts.tracker_lock_path(a) != session_contracts.tracker_lock_path(b)

    def test_the_same_tracker_always_resolves_to_the_same_lock(self, tmp_path):
        t = tmp_path / "one.yaml"
        t.write_text("x: 1\n", encoding="utf-8")
        assert session_contracts.tracker_lock_path(t) == session_contracts.tracker_lock_path(
            Path(str(t))
        )


class TestABadTrackerPathIsRefusedWhenTheClaimIsMade:
    """A Markdown tracker path was accepted, then killed the closeout.

    `--tracker-path learnings.md` was recorded without complaint. Every lane
    closeout reads and rewrites its tracker as YAML, so the lane could be
    created and then never closed: it died on a bare
    `yaml.scanner.ScannerError` pointing at a line of English prose, after its
    work was already merged.
    """

    def test_a_markdown_tracker_is_rejected(self, tmp_path):
        doc = tmp_path / "learnings.md"
        doc.write_text(
            "# Learnings Register\n\n"
            "This is the counterpart to\n"
            "`policy_friction.md`: that file records where *policy* misfits reality.\n",
            encoding="utf-8",
        )
        problem = _tracker_path_yaml_error(str(doc))
        assert problem, "the exact document that stranded a lane is still accepted"
        assert "YAML" in problem

    def test_a_yaml_mapping_is_accepted(self, tmp_path):
        good = tmp_path / "tracker.yaml"
        good.write_text("schema_version: 1\nsession_name: x\n", encoding="utf-8")
        assert _tracker_path_yaml_error(str(good)) is None

    def test_a_missing_tracker_is_not_an_error(self, tmp_path):
        """A claim may legitimately name a tracker a later step will write."""
        assert _tracker_path_yaml_error(str(tmp_path / "not-yet.yaml")) is None

    def test_no_tracker_path_is_not_an_error(self):
        assert _tracker_path_yaml_error(None) is None

    def test_a_yaml_scalar_is_accepted_at_claim_time(self, tmp_path):
        """Deliberately permitted here, and caught later if it ever matters.

        A scalar placeholder is common in fixtures and in trackers a later step
        overwrites. Refusing it at claim time broke claim creation for cases
        that were never the problem; the Markdown document that actually
        stranded a lane fails to PARSE, so the narrower rule still catches it.
        """
        scalar = tmp_path / "scalar.yaml"
        scalar.write_text("just a string\n", encoding="utf-8")
        assert _tracker_path_yaml_error(str(scalar)) is None

    def test_a_non_mapping_is_still_reported_clearly_when_read(self, tmp_path):
        """The second line of defence, so the scalar case is not simply ignored."""
        scalar = tmp_path / "scalar.yaml"
        scalar.write_text("just a string\n", encoding="utf-8")
        with pytest.raises(session_contracts.TrackerPathNotYAML) as caught:
            session_contracts.read_session_tracker(scalar)
        assert "mapping" in str(caught.value)

    def test_the_real_learnings_front_door_would_be_rejected(self):
        """Not a synthetic fixture: the actual file that caused this."""
        front_door = REPO / "learnings.md"
        if not front_door.exists():
            pytest.skip("learnings.md absent from this checkout")
        assert _tracker_path_yaml_error(str(front_door)), (
            "learnings.md is the document that stranded a lane and it is still "
            "an acceptable tracker path"
        )


class TestTheReaderAndWriterAgreeOnWhereTheLockIs:
    """Moving the lock without moving its reader would silently stop serialising.

    `session_lifecycle` built the sibling path independently. Had it kept doing
    so, it would look where no lock is ever written again, find nothing, fall
    through to its fingerprint path, and stop serialising against live writers
    without any error.
    """

    def test_the_lifecycle_reader_uses_the_shared_function(self):
        source = (REPO / "enforced_planning/session_lifecycle.py").read_text(
            encoding="utf-8"
        )
        assert "session_contracts.tracker_lock_path(" in source
        assert 'lock_path = resolved.parent / f".{resolved.name}.lock"' not in source, (
            "a second, independent lock-path construction survives; the reader "
            "and the writer can disagree about where the lock is"
        )
