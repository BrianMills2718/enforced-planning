"""Tests for scripts/complete_plan.py pure and mock-friendly functions."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.complete_plan import (
    find_plan_file,
    get_git_info,
    get_human_review_section,
    get_plan_status,
    run_unit_tests,
    update_plan_file,
    update_plan_index,
)


# ---------------------------------------------------------------------------
# find_plan_file
# ---------------------------------------------------------------------------


def test_find_plan_file_zero_padded(tmp_path: Path) -> None:
    """Finds plan file with zero-padded two-digit number."""
    plan = tmp_path / "05_my-plan.md"
    plan.write_text("content")
    result = find_plan_file(5, tmp_path)
    assert result == plan


def test_find_plan_file_non_padded(tmp_path: Path) -> None:
    """Falls back to non-padded glob when zero-padded form not found."""
    plan = tmp_path / "12_another-plan.md"
    plan.write_text("content")
    result = find_plan_file(12, tmp_path)
    assert result == plan


def test_find_plan_file_missing(tmp_path: Path) -> None:
    """Returns None when no matching plan file exists."""
    result = find_plan_file(99, tmp_path)
    assert result is None


def test_find_plan_file_prefers_zero_padded(tmp_path: Path) -> None:
    """Zero-padded pattern is tried first; returns first match."""
    plan = tmp_path / "07_plan.md"
    plan.write_text("content")
    result = find_plan_file(7, tmp_path)
    assert result == plan


# ---------------------------------------------------------------------------
# get_plan_status
# ---------------------------------------------------------------------------


def test_get_plan_status_complete(tmp_path: Path) -> None:
    """Extracts 'Complete' status from plan file."""
    plan = tmp_path / "01_plan.md"
    plan.write_text("# Plan\n\n**Status:** ✅ Complete\n\nMore content.")
    assert get_plan_status(plan) == "✅ Complete"


def test_get_plan_status_in_progress(tmp_path: Path) -> None:
    """Extracts 'In Progress' status."""
    plan = tmp_path / "01_plan.md"
    plan.write_text("**Status:** In Progress")
    assert get_plan_status(plan) == "In Progress"


def test_get_plan_status_missing(tmp_path: Path) -> None:
    """Returns 'Unknown' when no Status field found."""
    plan = tmp_path / "01_plan.md"
    plan.write_text("# Plan without status field\n")
    assert get_plan_status(plan) == "Unknown"


# ---------------------------------------------------------------------------
# get_human_review_section
# ---------------------------------------------------------------------------


def test_get_human_review_section_present(tmp_path: Path) -> None:
    """Returns section content when Human Review Required section exists."""
    plan = tmp_path / "01_plan.md"
    plan.write_text(
        "# Plan\n\n"
        "## Human Review Required\n\n"
        "- [ ] Verify UI looks correct\n"
        "- [ ] Check error messages\n\n"
        "## Next Section\n\nOther content."
    )
    result = get_human_review_section(plan)
    assert result is not None
    assert "Verify UI looks correct" in result
    assert "Check error messages" in result
    # Should not bleed into the next section
    assert "Next Section" not in result


def test_get_human_review_section_absent(tmp_path: Path) -> None:
    """Returns None when no Human Review Required section."""
    plan = tmp_path / "01_plan.md"
    plan.write_text("# Plan\n\n**Status:** Planned\n\n## Implementation\n\nDo stuff.")
    assert get_human_review_section(plan) is None


def test_get_human_review_section_case_insensitive(tmp_path: Path) -> None:
    """Section header match is case-insensitive."""
    plan = tmp_path / "01_plan.md"
    plan.write_text("## human review required\n\n- [ ] Something important\n")
    result = get_human_review_section(plan)
    assert result is not None
    assert "Something important" in result


# ---------------------------------------------------------------------------
# update_plan_file (dry_run=True only — no file writes)
# ---------------------------------------------------------------------------


def test_update_plan_file_dry_run_returns_true(tmp_path: Path) -> None:
    """Dry-run mode returns True without modifying the file."""
    plan = tmp_path / "01_plan.md"
    plan.write_text("# Plan\n\n**Status:** Planned\n")
    original = plan.read_text()

    result = update_plan_file(
        plan_file=plan,
        unit_summary="5 passed",
        e2e_smoke_summary="skipped",
        e2e_real_summary="skipped",
        doc_summary="passed",
        commit="abc1234",
        dry_run=True,
    )

    assert result is True
    # File must not be modified in dry-run mode
    assert plan.read_text() == original


def test_update_plan_file_dry_run_prints_info(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """Dry-run mode prints DRY RUN notice with status and commit."""
    plan = tmp_path / "02_plan.md"
    plan.write_text("**Status:** Planned\n")

    update_plan_file(
        plan_file=plan,
        unit_summary="10 passed",
        e2e_smoke_summary="skipped",
        e2e_real_summary="skipped",
        doc_summary="passed",
        commit="deadbeef",
        dry_run=True,
    )

    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out
    assert "deadbeef" in captured.out


def test_update_plan_file_live_updates_status(tmp_path: Path) -> None:
    """Live mode updates Status line to Complete and records evidence."""
    plan = tmp_path / "03_plan.md"
    plan.write_text("# Plan\n\n**Status:** Planned\n\n## Body\n")

    result = update_plan_file(
        plan_file=plan,
        unit_summary="7 passed",
        e2e_smoke_summary="skipped",
        e2e_real_summary="skipped",
        doc_summary="passed",
        commit="cafe0123",
        dry_run=False,
    )

    assert result is True
    updated = plan.read_text()
    assert "✅ Complete" in updated
    assert "cafe0123" in updated
    assert "Verified:" in updated


# ---------------------------------------------------------------------------
# update_plan_index (dry_run=True)
# ---------------------------------------------------------------------------


def test_update_plan_index_returns_false_without_index(tmp_path: Path) -> None:
    """Returns False when CLAUDE.md index does not exist."""
    result = update_plan_index(5, tmp_path, dry_run=True)
    assert result is False


def test_update_plan_index_dry_run_no_change(tmp_path: Path) -> None:
    """Dry-run mode does not modify CLAUDE.md."""
    index = tmp_path / "CLAUDE.md"
    index.write_text("| 7 | [My Plan](07_plan.md) | High | Planned | — |\n")
    original = index.read_text()

    update_plan_index(7, tmp_path, dry_run=True)

    assert index.read_text() == original


# ---------------------------------------------------------------------------
# run_unit_tests (mock subprocess)
# ---------------------------------------------------------------------------


def test_run_unit_tests_success(tmp_path: Path) -> None:
    """Returns (True, summary) when pytest exits 0."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "=== 42 passed in 1.23s ==="
    mock_result.stderr = ""

    with patch("scripts.complete_plan.subprocess.run", return_value=mock_result):
        passed, summary = run_unit_tests(tmp_path, verbose=False)

    assert passed is True
    assert "42 passed" in summary


def test_run_unit_tests_failure(tmp_path: Path) -> None:
    """Returns (False, summary) when pytest exits non-zero."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = "=== 1 failed, 41 passed in 1.23s ==="
    mock_result.stderr = ""

    with patch("scripts.complete_plan.subprocess.run", return_value=mock_result):
        passed, _ = run_unit_tests(tmp_path, verbose=False)

    assert passed is False


# ---------------------------------------------------------------------------
# get_git_info (mock subprocess)
# ---------------------------------------------------------------------------


def test_get_git_info_returns_commit_and_branch(tmp_path: Path) -> None:
    """Returns (commit, branch) tuple from git subprocess calls."""
    def fake_run(cmd, **_kwargs):
        result = MagicMock()
        if "rev-parse" in cmd and "--short" in cmd:
            result.stdout = "abc1234\n"
        elif "rev-parse" in cmd and "--abbrev-ref" in cmd:
            result.stdout = "main\n"
        return result

    with patch("scripts.complete_plan.subprocess.run", side_effect=fake_run):
        commit, branch = get_git_info(tmp_path)

    assert commit == "abc1234"
    assert branch == "main"


def test_get_git_info_handles_exception(tmp_path: Path) -> None:
    """Returns ('unknown', 'unknown') when git command fails."""
    with patch("scripts.complete_plan.subprocess.run", side_effect=Exception("no git")):
        commit, branch = get_git_info(tmp_path)

    assert commit == "unknown"
    assert branch == "unknown"
