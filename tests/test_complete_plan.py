"""Tests for scripts/complete_plan.py pure and mock-friendly functions."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml  # type: ignore[import-untyped]

import scripts.complete_plan as complete_plan_module
from enforced_planning import coordination_claims
from scripts.complete_plan import (
    _verification_status,
    find_plan_file,
    get_declared_execution_profile,
    get_git_info,
    get_human_review_section,
    get_plan_status,
    resolve_verification_profile,
    run_focused_plan_tests,
    run_unit_tests,
    sync_coordination_closeout,
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


def test_execution_profile_parser_handles_bold_plan_metadata(tmp_path: Path) -> None:
    """Read the canonical execution-profile token without depending on one template."""

    plan = tmp_path / "01_plan.md"
    plan.write_text("- **Execution profile:** `production-internal` pilot.\n")

    assert get_declared_execution_profile(plan) == "production-internal"


def test_auto_verification_is_focused_for_poc_or_undeclared_plan(tmp_path: Path) -> None:
    """PoC and legacy plans should not inherit broad terminal verification."""

    poc = tmp_path / "01_poc.md"
    poc.write_text("- **Execution profile:** `poc`\n")
    legacy = tmp_path / "02_legacy.md"
    legacy.write_text("# Legacy plan\n")

    assert resolve_verification_profile(poc, "auto") == "focused"
    assert resolve_verification_profile(legacy, "auto") == "focused"


def test_auto_verification_is_broad_for_production_plan(tmp_path: Path) -> None:
    """An explicitly consequential plan retains broad terminal checks."""

    plan = tmp_path / "01_plan.md"
    plan.write_text("execution_profile: production-external\n")

    assert resolve_verification_profile(plan, "auto") == "broad"


def test_explicit_verification_profile_overrides_plan_metadata(tmp_path: Path) -> None:
    """The operator can deliberately strengthen or select documentation closeout."""

    plan = tmp_path / "01_plan.md"
    plan.write_text("- Execution profile: `poc`\n")

    assert resolve_verification_profile(plan, "broad") == "broad"
    assert resolve_verification_profile(plan, "docs") == "docs"


def test_verification_status_does_not_report_unrun_checks_as_passed() -> None:
    """Deferred and skipped checks stay visibly distinct from passing evidence."""

    assert _verification_status(True, "deferred (focused profile)") == "DEFER"
    assert _verification_status(True, "skipped (docs profile)") == "SKIP"
    assert _verification_status(True, "12 passed") == "PASS"
    assert _verification_status(False, "1 failed") == "FAIL"


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


def test_update_plan_index_live_updates_only_status_cell(tmp_path: Path) -> None:
    """Live update should preserve every non-status cell in the matching row."""
    index = tmp_path / "CLAUDE.md"
    original = (
        "# Implementation Plans\n\n"
        "| # | Name | Priority | Status | Blocks |\n"
        "|---|------|----------|--------|--------|\n"
        "| 126 | [Worktree entrypoint contract parity](126_worktree-entrypoint-contract-parity.md) | Critical | 🚧 In Progress | 120, 121 |\n"
        "| 127 | [Research synthesis forward cutover and alias enforcement](127_research-synthesis-forward-cutover-and-alias-enforcement.md) | High | 🚧 In Progress | - |\n"
    )
    index.write_text(original, encoding="utf-8")

    result = update_plan_index(126, tmp_path, dry_run=False)

    assert result is True
    updated = index.read_text(encoding="utf-8").splitlines()
    assert (
        "| 126 | [Worktree entrypoint contract parity](126_worktree-entrypoint-contract-parity.md) | "
        "Critical | ✅ Complete | 120, 121 |"
    ) in updated
    assert (
        "| 127 | [Research synthesis forward cutover and alias enforcement](127_research-synthesis-forward-cutover-and-alias-enforcement.md) | "
        "High | 🚧 In Progress | - |"
    ) in updated


def test_update_plan_index_does_not_mutate_status_key_table(tmp_path: Path) -> None:
    """Only the numbered plan row should change; status-key rows are not plan rows."""
    index = tmp_path / "CLAUDE.md"
    original = (
        "# Implementation Plans\n\n"
        "| # | Name | Priority | Status | Blocks |\n"
        "|---|------|----------|--------|--------|\n"
        "| 126 | [Worktree entrypoint contract parity](126_worktree-entrypoint-contract-parity.md) | Critical | 🚧 In Progress | 120, 121 |\n"
        "\n"
        "## Status Key\n\n"
        "| Status | Meaning |\n"
        "|--------|---------|\n"
        "| ✅ Complete | Implemented and verified |\n"
    )
    index.write_text(original, encoding="utf-8")

    result = update_plan_index(126, tmp_path, dry_run=False)

    assert result is True
    updated = index.read_text(encoding="utf-8")
    assert "| ✅ Complete | Implemented and verified |" in updated
    assert updated.count("| ✅ Complete |") == 2


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


def test_run_unit_tests_uses_interpreter_qualified_pytest(tmp_path: Path) -> None:
    """Unit-test runner should invoke pytest through the current interpreter."""
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs):
        commands.append(command)
        result = MagicMock()
        result.returncode = 0
        result.stdout = "=== 42 passed in 1.23s ==="
        result.stderr = ""
        return result

    with patch("scripts.complete_plan.subprocess.run", side_effect=fake_run):
        passed, summary = run_unit_tests(tmp_path, verbose=False)

    assert passed is True
    assert "42 passed" in summary
    assert commands
    assert commands[0][:3] == [sys.executable, "-m", "pytest"]


def test_run_focused_plan_tests_uses_installed_checker(tmp_path: Path) -> None:
    """Focused verification executes the plan checker through the current interpreter."""

    checker = tmp_path / "scripts" / "meta" / "check_plan_tests.py"
    checker.parent.mkdir(parents=True)
    checker.write_text(
        "import sys\n"
        "assert sys.argv[1:] == ['--plan', '41']\n"
        "print('focused plan tests passed')\n",
        encoding="utf-8",
    )

    passed, summary = run_focused_plan_tests(tmp_path, 41, verbose=False)

    assert passed is True
    assert summary == "focused plan tests passed"


def test_run_focused_plan_tests_fails_loud_without_checker(tmp_path: Path) -> None:
    """A missing focused-test boundary must not silently become a green closeout."""

    passed, summary = run_focused_plan_tests(tmp_path, 41, verbose=False)

    assert passed is False
    assert "missing" in summary


def test_run_e2e_tests_uses_interpreter_qualified_pytest(tmp_path: Path) -> None:
    """Smoke-test runner should also invoke pytest through the current interpreter."""
    commands: list[list[str]] = []
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")

    def fake_run(command: list[str], **_kwargs):
        commands.append(command)
        result = MagicMock()
        result.returncode = 0
        result.stdout = "=== 1 passed in 0.01s ==="
        result.stderr = ""
        return result

    with patch("scripts.complete_plan.subprocess.run", side_effect=fake_run):
        from scripts.complete_plan import run_e2e_tests

        passed, summary = run_e2e_tests(tmp_path, verbose=False)

    assert passed is True
    assert "PASSED" in summary
    assert commands
    assert commands[0][:3] == [sys.executable, "-m", "pytest"]


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


def test_sync_coordination_closeout_marks_matching_claims_completed_and_refreshes_registry(
    tmp_path: Path, monkeypatch
) -> None:
    """Completing a plan should close matching live claims and refresh derived registry outputs."""
    project_root = tmp_path / "project-meta"
    project_root.mkdir()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    matching_claim = claims_dir / "matching.yaml"
    matching_claim.write_text(
        yaml.safe_dump(
            {
                "agent": "codex",
                "claimed_at": "2026-04-05T00:00:00+00:00",
                "expires_at": "2099-04-05T12:00:00+00:00",
                "projects": ["project-meta"],
                "scope": "lifecycle-automation",
                "intent": "Implement lane lifecycle automation",
                "claim_type": "write",
                "write_paths": ["scripts/complete_plan.py"],
                "branch": "plan-111-lifecycle-automation",
                "worktree_path": str(project_root / "worktrees" / "plan-111"),
                "session_id": "codex:session",
                "plan_ref": "Plan #111",
                "status": "active",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    other_claim = claims_dir / "other.yaml"
    other_claim.write_text(
        yaml.safe_dump(
            {
                "agent": "claude-code",
                "claimed_at": "2026-04-05T00:00:00+00:00",
                "expires_at": "2099-04-05T12:00:00+00:00",
                "projects": ["project-meta"],
                "scope": "another-lane",
                "intent": "Unrelated active lane",
                "claim_type": "write",
                "write_paths": ["scripts/other.py"],
                "branch": "plan-112-other",
                "worktree_path": str(project_root / "worktrees" / "plan-112"),
                "session_id": "claude:session",
                "plan_ref": "Plan #112",
                "status": "active",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    closed_count, scopes, payload = sync_coordination_closeout(
        plan_number=111,
        project_root=project_root,
        dry_run=False,
        verbose=False,
    )

    assert closed_count == 1
    assert scopes == ["lifecycle-automation"]
    updated_matching = yaml.safe_load(matching_claim.read_text(encoding="utf-8"))
    assert updated_matching["status"] == "completed"
    assert "closed automatically by scripts/complete_plan.py for Plan #111" in updated_matching["notes"]
    assert payload is not None
    assert payload["claim_count"] == 1
    assert payload["claims"][0]["scope"] == "another-lane"
    assert (project_root / "generated" / "runtime" / "active_work_registry.json").exists()


def test_sync_coordination_closeout_dry_run_reports_without_mutating_claims(
    tmp_path: Path, monkeypatch
) -> None:
    """Dry-run closeout should report matching claims without changing them."""
    project_root = tmp_path / "project-meta"
    project_root.mkdir()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    claim_path = claims_dir / "matching.yaml"
    original = {
        "agent": "codex",
        "claimed_at": "2026-04-05T00:00:00+00:00",
        "expires_at": "2099-04-05T12:00:00+00:00",
        "projects": ["project-meta"],
        "scope": "lifecycle-automation",
        "intent": "Implement lane lifecycle automation",
        "claim_type": "write",
        "write_paths": ["scripts/complete_plan.py"],
        "branch": "plan-111-lifecycle-automation",
        "worktree_path": str(project_root / "worktrees" / "plan-111"),
        "session_id": "codex:session",
        "plan_ref": "Plan #111",
        "status": "active",
    }
    claim_path.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")

    closed_count, scopes, payload = sync_coordination_closeout(
        plan_number=111,
        project_root=project_root,
        dry_run=True,
        verbose=False,
    )

    assert closed_count == 1
    assert scopes == ["lifecycle-automation"]
    assert payload is None
    assert yaml.safe_load(claim_path.read_text(encoding="utf-8")) == original


def test_complete_plan_does_not_transition_status_when_owned_lane_is_unresolved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A failed atomic plan close must stop before plan or index mutation."""
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    plan_file = plans_dir / "12_example.md"
    original = "# Plan #12\n\n**Status:** In Progress\n\n## Plan\n\n1. Finish.\n"
    plan_file.write_text(original, encoding="utf-8")
    (plans_dir / "CLAUDE.md").write_text(
        "| # | Gap | Priority | Status | Blocks |\n"
        "|---|---|---|---|---|\n"
        "| 12 | Example | High | 🚧 In Progress | — |\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        complete_plan_module,
        "check_doc_coupling",
        lambda project_root, verbose: (True, "passed"),
    )
    monkeypatch.setattr(
        complete_plan_module,
        "_check_trace_evaluable_advisory",
        lambda plan_file, verbose: None,
    )
    monkeypatch.setattr(
        complete_plan_module,
        "get_git_info",
        lambda project_root: ("abc123", "main"),
    )
    monkeypatch.setattr(
        complete_plan_module.plan_close,
        "close_plan_lanes",
        lambda **kwargs: type(
            "CloseResult",
            (),
            {"success": False, "failures": ["dirty-lane: Worktree is dirty"]},
        )(),
    )

    result = complete_plan_module.complete_plan(
        12,
        tmp_path,
        verification_profile="docs",
        verbose=False,
    )

    assert result is False
    assert plan_file.read_text(encoding="utf-8") == original
    assert "In Progress" in (plans_dir / "CLAUDE.md").read_text(encoding="utf-8")
