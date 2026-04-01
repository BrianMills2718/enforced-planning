"""Tests for doc-coupling acknowledgment mechanism."""

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "meta"))

from check_doc_coupling import filter_violations_with_acks, load_ack_file


@pytest.fixture
def tmp_ack_file(tmp_path):
    """Create a temporary ack file and return its path."""

    def _write(content: str) -> Path:
        p = tmp_path / ".doc-coupling-acks"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    return _write


class TestLoadAckFile:
    """Tests for loading and parsing the ack file."""

    def test_missing_file_returns_empty(self, tmp_path):
        """Missing ack file returns empty dict."""
        result = load_ack_file(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_valid_entries_loaded(self, tmp_ack_file):
        """Valid entries with path and reason are loaded."""
        p = tmp_ack_file("""\
            - path: docs/foo.md
              reason: Already verified in sync
            - path: generated/bar.md
              reason: Regenerated, no content change
        """)
        result = load_ack_file(p)
        assert len(result) == 2
        assert result["docs/foo.md"] == "Already verified in sync"
        assert result["generated/bar.md"] == "Regenerated, no content change"

    def test_empty_reason_skipped(self, tmp_ack_file):
        """Entries with empty reason are not loaded."""
        p = tmp_ack_file("""\
            - path: docs/foo.md
              reason: ""
            - path: docs/bar.md
              reason: Valid reason
        """)
        result = load_ack_file(p)
        assert len(result) == 1
        assert "docs/foo.md" not in result
        assert "docs/bar.md" in result

    def test_missing_reason_skipped(self, tmp_ack_file):
        """Entries with no reason field are not loaded."""
        p = tmp_ack_file("""\
            - path: docs/foo.md
        """)
        result = load_ack_file(p)
        assert result == {}

    def test_missing_path_skipped(self, tmp_ack_file):
        """Entries with no path field are not loaded."""
        p = tmp_ack_file("""\
            - reason: Some reason but no path
        """)
        result = load_ack_file(p)
        assert result == {}

    def test_non_list_yaml_returns_empty(self, tmp_ack_file):
        """Non-list YAML content returns empty dict."""
        p = tmp_ack_file("key: value\n")
        result = load_ack_file(p)
        assert result == {}

    def test_non_dict_entries_skipped(self, tmp_ack_file):
        """Non-dict list entries are skipped."""
        p = tmp_ack_file("""\
            - just a string
            - path: docs/foo.md
              reason: Valid
        """)
        result = load_ack_file(p)
        assert len(result) == 1


class TestFilterViolationsWithAcks:
    """Tests for filtering violations against acknowledgments."""

    def _make_violation(self, desc: str, sources: list[str], docs: list[str]) -> dict:
        return {
            "description": desc,
            "changed_sources": sources,
            "expected_docs": docs,
            "soft": False,
        }

    def test_no_acks_returns_all_violations(self):
        """With no acks, all violations remain."""
        violations = [self._make_violation("test", ["a.py"], ["docs/a.md"])]
        remaining, acked = filter_violations_with_acks(violations, {})
        assert len(remaining) == 1
        assert len(acked) == 0

    def test_matching_ack_suppresses_violation(self):
        """Violation with all expected docs acknowledged is suppressed."""
        violations = [self._make_violation("test", ["a.py"], ["docs/a.md"])]
        acks = {"docs/a.md": "Already correct"}
        remaining, acked = filter_violations_with_acks(violations, acks)
        assert len(remaining) == 0
        assert len(acked) == 1

    def test_partial_ack_does_not_suppress(self):
        """Violation with only some expected docs acknowledged is NOT suppressed."""
        violations = [
            self._make_violation("test", ["a.py"], ["docs/a.md", "docs/b.md"])
        ]
        acks = {"docs/a.md": "Checked"}
        remaining, acked = filter_violations_with_acks(violations, acks)
        assert len(remaining) == 1
        assert len(acked) == 0

    def test_full_ack_of_multi_doc_violation(self):
        """Violation with all expected docs acknowledged is suppressed."""
        violations = [
            self._make_violation("test", ["a.py"], ["docs/a.md", "docs/b.md"])
        ]
        acks = {"docs/a.md": "Checked a", "docs/b.md": "Checked b"}
        remaining, acked = filter_violations_with_acks(violations, acks)
        assert len(remaining) == 0
        assert len(acked) == 1

    def test_unrelated_ack_does_not_suppress(self):
        """Ack for a different path does not suppress the violation."""
        violations = [self._make_violation("test", ["a.py"], ["docs/a.md"])]
        acks = {"docs/other.md": "Not relevant"}
        remaining, acked = filter_violations_with_acks(violations, acks)
        assert len(remaining) == 1
        assert len(acked) == 0

    def test_glob_ack_matches_glob_doc(self):
        """Ack path can match glob patterns in expected docs."""
        violations = [
            self._make_violation(
                "test", ["CLAUDE.md"], ["generated/agent_docs/subtrees/**/*.md"]
            )
        ]
        acks = {"generated/agent_docs/subtrees/**/*.md": "Regenerated, in sync"}
        remaining, acked = filter_violations_with_acks(violations, acks)
        assert len(remaining) == 0
        assert len(acked) == 1

    def test_mixed_acked_and_unacked(self):
        """Some violations acked, some not — correct split."""
        violations = [
            self._make_violation("acked", ["a.py"], ["docs/a.md"]),
            self._make_violation("not acked", ["b.py"], ["docs/b.md"]),
        ]
        acks = {"docs/a.md": "Verified"}
        remaining, acked = filter_violations_with_acks(violations, acks)
        assert len(remaining) == 1
        assert remaining[0]["description"] == "not acked"
        assert len(acked) == 1
        assert acked[0]["description"] == "acked"
