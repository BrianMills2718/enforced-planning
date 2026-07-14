"""Tests for scripts/complete_plan.py pure and mock-friendly functions."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml  # type: ignore[import-untyped]

from enforced_planning import coordination_claims
from scripts.complete_plan import (
    RepositoryHealthComparison,
    TestRunResult as RepositoryTestRunResult,
    complete_plan,
    check_doc_coupling,
    find_plan_file,
    get_git_info,
    get_human_review_section,
    get_plan_status,
    run_required_plan_tests,
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


def test_run_required_plan_tests_uses_companion_script(tmp_path: Path) -> None:
    """The blocking change gate uses the portable required-test runner."""
    mock_result = MagicMock(returncode=0, stdout="All required tests pass!", stderr="")

    # mock-ok: this verifies the exact subprocess boundary; real required tests
    # are exercised by check_plan_tests.py's own suite.
    with patch("scripts.complete_plan.subprocess.run", return_value=mock_result) as run:
        passed, summary = run_required_plan_tests(tmp_path, 64, verbose=False)

    assert passed is True
    assert "required tests pass" in summary.lower()
    command = run.call_args.args[0]
    assert command[0] == sys.executable
    assert command[-2:] == ["--plan", "64"]


def test_doc_coupling_unavailable_is_blocking(tmp_path: Path) -> None:
    """A missing or crashed doc-coupling runner cannot be reported as pass."""
    failed = MagicMock(returncode=2, stdout="", stderr="missing script")

    # mock-ok: fail-loud subprocess handling is the behavior under test.
    with patch("scripts.complete_plan.subprocess.run", return_value=failed) as run:
        passed, summary = check_doc_coupling(tmp_path, verbose=False)

    assert passed is False
    assert "exit 2" in summary
    assert run.call_args.args[0][0] == sys.executable


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


def _green_test_run() -> RepositoryTestRunResult:
    """Return compact green repository evidence for orchestration tests."""
    return RepositoryTestRunResult(
        available=True,
        commit="abc1234",
        command=(sys.executable, "-m", "pytest", "tests/"),
        returncode=0,
        summary="2 passed",
        test_count=2,
        passed_count=2,
        skipped_count=0,
        failures=(),
        error=None,
    )


def _degraded_comparison() -> RepositoryHealthComparison:
    """Return an allowed baseline-degraded comparison for wiring tests."""
    run = _green_test_run()
    return RepositoryHealthComparison(
        status="baseline_degraded",
        allowed=True,
        reason="one unchanged baseline failure",
        baseline_ref="origin/main",
        baseline_commit="abc1234",
        current=run,
        baseline=run,
        changed_paths=("docs/example.md",),
        new_failures=(),
        changed_baseline_failures=(),
    )


def test_required_plan_tests_block_before_repository_health(tmp_path: Path) -> None:
    """A failed declared change gate stops before the global suite runs."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "66_plan.md").write_text("**Status:** 🚧 In Progress\n", encoding="utf-8")

    # mock-ok: orchestration order is the behavior under test; the runners have
    # separate real-process controls.
    with (
        patch("scripts.complete_plan.run_required_plan_tests", return_value=(False, "failed")),
        patch("scripts.complete_plan.compare_repository_health") as repository_health,
    ):
        result = complete_plan(66, tmp_path, verbose=False)

    assert result is False
    repository_health.assert_not_called()


def test_degraded_repository_writes_scoped_status(tmp_path: Path) -> None:
    """Allowed baseline debt is preserved in the plan's completion label."""
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    plan = plans / "66_plan.md"
    plan.write_text("**Status:** 🚧 In Progress\n", encoding="utf-8")
    (plans / "CLAUDE.md").write_text(
        "| 66 | Plan | High | 🚧 In Progress | — |\n",
        encoding="utf-8",
    )

    # mock-ok: verifies final verdict wiring and mutation after independently
    # tested runner/comparator contracts.
    with (
        patch("scripts.complete_plan.run_required_plan_tests", return_value=(True, "2 passed")),
        patch("scripts.complete_plan.compare_repository_health", return_value=_degraded_comparison()),
        patch("scripts.complete_plan.run_e2e_tests", return_value=(True, "skipped")),
        patch("scripts.complete_plan.run_real_e2e_tests", return_value=(True, "skipped")),
        patch("scripts.complete_plan.check_doc_coupling", return_value=(True, "passed")),
        patch("scripts.complete_plan.write_repository_health_evidence", return_value=Path("docs/evidence/plan66.json")),
        patch("scripts.complete_plan.sync_coordination_closeout", return_value=(0, [], {"claim_count": 0})),
    ):
        result = complete_plan(66, tmp_path, verbose=False)

    assert result is True
    updated = plan.read_text(encoding="utf-8")
    assert "✅ Complete (scoped; repository baseline degraded)" in updated
    assert "status: baseline_degraded" in updated
    assert "required: 2 passed" in updated


def test_policy_surfaces_separate_change_gate_from_repository_health() -> None:
    """Canonical active guidance must not restore unconditional full-green closure."""
    repo_root = Path(__file__).resolve().parents[1]
    operating_model = (repo_root / "PLANNING_OPERATING_MODEL.md").read_text(encoding="utf-8")
    verification_pattern = (repo_root / "patterns" / "17_verification-enforcement.md").read_text(
        encoding="utf-8"
    )
    for template in (
        repo_root / "templates" / "plan.md.template",
        repo_root / "docs" / "plans" / "TEMPLATE.md",
    ):
        assert "Full test suite passes" not in template.read_text(encoding="utf-8")

    assert "change gate" in operating_model
    assert "repository health" in operating_model
    assert "baseline-degraded" in operating_model
    assert "required tests as an always-blocking change gate" in verification_pattern
    assert "--require-repository-green" in verification_pattern
