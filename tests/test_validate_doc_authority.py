"""Tests for authority-drift validation and closeout gates."""

from __future__ import annotations

import subprocess
from pathlib import Path

from enforced_planning import coordination_claims
from enforced_planning import doc_authority
from enforced_planning import session_lifecycle


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_plan(path: Path, *, status: str = "📋 Planned") -> None:
    _write(
        path,
        f"""# Plan #{path.name.split('_', 1)[0]}: Example

**Status:** {status}
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** None

## Gap

Example gap.

## Plan

Example plan.

## Required Tests

| Command | What It Verifies |
|---|---|
| `pytest -q` | example |
""",
    )


def _write_plan_index(path: Path, *, plan_rows: list[tuple[str, str]]) -> None:
    rows = "\n".join(
        f"| {plan_number} | Example | High | {status} | — |"
        for plan_number, status in plan_rows
    )
    _write(
        path,
        "# Implementation Plans\n\n"
        "## Gap Summary\n\n"
        "| # | Gap | Priority | Status | Blocks |\n"
        "|---|-----|----------|--------|--------|\n"
        f"{rows}\n",
    )


def _write_config(repo_root: Path) -> None:
    _write(
        repo_root / "scripts" / "doc_authority.yaml",
        """schema_version: 1
indexed_authority_surfaces:
  - concern: active-plan-index
    kind: plan_index
    authority_surface: docs/plans/CLAUDE.md
    source_glob: docs/plans/[0-9]*_*.md
    resolution_mode: manual
""",
    )


def _write_doc_spine_fixture(repo_root: Path) -> None:
    _write(repo_root / "EXECUTION_BRIEF.md", "brief\n")
    _write(repo_root / "PLANNING_OPERATING_MODEL.md", "north star\n")
    _write(repo_root / "docs/overview/CURRENT_STATE.md", "current\n")
    _write(repo_root / "docs/overview/GAP_SUMMARY.md", "gap\n")
    _write(repo_root / "docs/plans/CLAUDE.md", "# Plans\n")
    _write(repo_root / "docs/plans/55_test.md", "# Plan #55: Test\n")
    _write(repo_root / "adr/0009-doc-authority-governance-and-enforcement.md", "adr 9\n")
    _write(repo_root / "adr/0010-agent-memory-as-planning-input.md", "adr 10\n")


def _write_doc_spine_config(repo_root: Path, body: str) -> None:
    _write(repo_root / "scripts" / "doc_authority.yaml", body)


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "codex@example.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "Codex"], cwd=repo_root, check=True)


def _create_write_claim(
    *,
    repo_root: Path,
    claims_dir: Path,
    scope: str,
    write_paths: list[str],
    claim_type: str = "write",
) -> None:
    coordination_claims.CLAIMS_DIR = claims_dir
    ok, message = coordination_claims.create_claim(
        agent="codex",
        project=repo_root.name,
        scope=scope,
        intent="test claim",
        plan_ref="UNPLANNED",
        claim_type=claim_type,
        write_paths=write_paths,
        worktree_path=str(repo_root),
        repo_root=str(repo_root),
        branch="main",
        session_id="codex:test-session",
        session_name="test-authority-obligation",
    )
    assert ok, message


def test_validate_doc_authority_fails_for_unowned_plan_index_drift(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    _write_config(repo_root)
    _write_plan(repo_root / "docs/plans/41_example.md")
    _write_plan_index(repo_root / "docs/plans/CLAUDE.md", plan_rows=[])

    issues = doc_authority.validate_doc_authority(repo_root)

    assert [issue.code for issue in issues] == ["unowned_authority_drift"]
    assert issues[0].artifact_path == "docs/plans/41_example.md"


def test_validate_doc_authority_matches_artifact_status_when_plan_numbers_repeat(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    _write_config(repo_root)
    _write_plan(
        repo_root / "docs/plans/51_partial.md",
        status="🟡 Partial — dry-run shipped",
    )
    _write_plan(
        repo_root / "docs/plans/66_design.md",
        status="Design complete; awaiting disposition",
    )
    _write_plan(
        repo_root / "docs/plans/66_design_mockup.md",
        status="Proposed design seam",
    )
    _write(
        repo_root / "docs/plans/CLAUDE.md",
        """# Implementation Plans

| # | Gap | Priority | Status | Blocks |
|---|-----|----------|--------|--------|
| 51 | Partial (`51_partial.md`) | High | 🟡 Partial — dry-run shipped | — |
| 66 | Design (`66_design.md`) | High | ✅ Design complete | — |
| — | Design mockup (`66_design_mockup.md`) | High | 🟡 Proposed design seam | — |
""",
    )

    issues = doc_authority.validate_doc_authority(repo_root)

    assert issues == []


def test_validate_doc_authority_prefers_in_progress_over_later_complete_detail(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    _write_config(repo_root)
    _write_plan(
        repo_root / "docs/plans/55_mixed_status.md",
        status="In Progress — implementation complete; reconciliation pending",
    )
    _write_plan_index(
        repo_root / "docs/plans/CLAUDE.md",
        plan_rows=[("55", "🚧 In Progress")],
    )

    issues = doc_authority.validate_doc_authority(repo_root)

    assert issues == []


def test_validate_doc_authority_reads_candidate_worktree_surfaces(tmp_path: Path, monkeypatch) -> None:
    canonical_repo = tmp_path / "canonical" / "demo"
    candidate_worktree = tmp_path / "worktree" / "demo"
    _write_config(candidate_worktree)
    _write_plan(candidate_worktree / "docs/plans/41_example.md")
    _write_plan_index(
        candidate_worktree / "docs/plans/CLAUDE.md",
        plan_rows=[("41", "📋 Planned")],
    )
    _write_plan(canonical_repo / "docs/plans/41_example.md")
    _write_plan_index(canonical_repo / "docs/plans/CLAUDE.md", plan_rows=[])
    monkeypatch.setattr(
        doc_authority,
        "resolve_canonical_repo_root",
        lambda _repo_root: canonical_repo,
    )

    issues = doc_authority.validate_doc_authority(candidate_worktree)

    assert issues == []


def test_validate_doc_authority_requires_obligation_when_owner_claim_exists(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    claims_dir = tmp_path / "claims"
    _write_config(repo_root)
    _write_plan(repo_root / "docs/plans/41_example.md")
    _write_plan_index(repo_root / "docs/plans/CLAUDE.md", plan_rows=[])
    _create_write_claim(
        repo_root=repo_root,
        claims_dir=claims_dir,
        scope="plan-index-owner",
        write_paths=["docs/plans/CLAUDE.md"],
    )

    issues = doc_authority.validate_doc_authority(repo_root)

    assert [issue.code for issue in issues] == ["missing_reconciliation_obligation"]
    assert issues[0].evidence["owner_scopes"] == ["plan-index-owner"]


def test_validate_doc_authority_recognizes_program_claim_write_ownership(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    claims_dir = tmp_path / "claims"
    _write_config(repo_root)
    _write_plan(repo_root / "docs/plans/41_example.md")
    _write_plan_index(repo_root / "docs/plans/CLAUDE.md", plan_rows=[])
    _create_write_claim(
        repo_root=repo_root,
        claims_dir=claims_dir,
        scope="program-plan-index-owner",
        write_paths=["docs/plans/CLAUDE.md"],
        claim_type="program",
    )

    issues = doc_authority.validate_doc_authority(repo_root)

    assert [issue.code for issue in issues] == ["missing_reconciliation_obligation"]
    assert issues[0].evidence["owner_scopes"] == ["program-plan-index-owner"]


def test_validate_doc_authority_accepts_recorded_obligation(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    claims_dir = tmp_path / "claims"
    obligations_dir = tmp_path / "authority_obligations"
    _write_config(repo_root)
    _write_plan(repo_root / "docs/plans/41_example.md")
    _write_plan_index(repo_root / "docs/plans/CLAUDE.md", plan_rows=[])
    _create_write_claim(
        repo_root=repo_root,
        claims_dir=claims_dir,
        scope="plan-index-owner",
        write_paths=["docs/plans/CLAUDE.md"],
    )
    doc_authority.AUTHORITY_OBLIGATIONS_DIR = obligations_dir
    obligation = doc_authority.record_obligation(
        project=repo_root.name,
        concern="active-plan-index",
        authority_surface="docs/plans/CLAUDE.md",
        artifact_path="docs/plans/41_example.md",
        required_action="add Plan #41 to docs/plans/CLAUDE.md",
        created_by_agent="codex",
        created_by_scope="plan-38",
        plan_ref="Plan #41",
        owner_scope="plan-index-owner",
    )

    issues = doc_authority.validate_doc_authority(repo_root)

    assert [issue.code for issue in issues] == ["recorded_reconciliation_obligation"]
    assert issues[0].severity == "info"
    assert issues[0].evidence["obligation_ids"] == [obligation.obligation_id]


def test_finish_session_fails_when_lane_owns_unresolved_authority_obligation(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    claims_dir = tmp_path / "claims"
    obligations_dir = tmp_path / "authority_obligations"
    repo_root.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo_root)
    _write(repo_root / "README.md", "demo\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True)
    _create_write_claim(
        repo_root=repo_root,
        claims_dir=claims_dir,
        scope="authority-owner",
        write_paths=["docs/plans/CLAUDE.md"],
    )
    doc_authority.AUTHORITY_OBLIGATIONS_DIR = obligations_dir
    doc_authority.record_obligation(
        project=repo_root.name,
        concern="active-plan-index",
        authority_surface="docs/plans/CLAUDE.md",
        artifact_path="docs/plans/41_example.md",
        required_action="add Plan #41 to docs/plans/CLAUDE.md",
        created_by_agent="codex",
        created_by_scope="plan-41",
        owner_scope="authority-owner",
    )

    try:
        session_lifecycle.finish_session(
            agent="codex",
            project=repo_root.name,
            scope="authority-owner",
            worktree_path=str(repo_root),
            actor_session_id="codex:test-session",
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected finish_session to fail on unresolved authority obligations")

    assert "unresolved reconciliation obligations" in message
    assert "docs/plans/CLAUDE.md" in message


def test_validate_doc_authority_fails_when_required_concern_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    _write_doc_spine_fixture(repo_root)
    _write_doc_spine_config(
        repo_root,
        """schema_version: 2
indexed_authority_surfaces: []
doc_spine:
  root_doc: EXECUTION_BRIEF.md
  required_concerns: [execution_brief, north_star, current_state, gap_summary, roadmap, active_plan_index]
role_budgets: {}
docs:
  - path: EXECUTION_BRIEF.md
    authority: canonical
    doc_status: active
    concerns: [execution_brief]
    role: execution_brief
    primary_parent: null
  - path: PLANNING_OPERATING_MODEL.md
    authority: canonical
    doc_status: active
    concerns: [north_star]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/overview/CURRENT_STATE.md
    authority: canonical
    doc_status: active
    concerns: [current_state]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: ROADMAP.md
    authority: canonical
    doc_status: active
    concerns: [roadmap]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/plans/CLAUDE.md
    authority: canonical
    doc_status: active
    concerns: [active_plan_index]
    role: reference
    primary_parent: EXECUTION_BRIEF.md
code_surfaces: []
""",
    )
    _write(repo_root / "ROADMAP.md", "roadmap\n")

    issues = doc_authority.validate_doc_authority(repo_root)

    assert any(issue.code == "required_concern_missing" and issue.concern == "gap_summary" for issue in issues)


def test_validate_doc_authority_fails_on_primary_parent_cycle(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    _write_doc_spine_fixture(repo_root)
    _write(repo_root / "ROADMAP.md", "roadmap\n")
    _write_doc_spine_config(
        repo_root,
        """schema_version: 2
indexed_authority_surfaces: []
doc_spine:
  root_doc: EXECUTION_BRIEF.md
  required_concerns: [execution_brief, north_star, current_state, gap_summary, roadmap, active_plan_index]
role_budgets: {}
docs:
  - path: EXECUTION_BRIEF.md
    authority: canonical
    doc_status: active
    concerns: [execution_brief]
    role: execution_brief
    primary_parent: null
  - path: PLANNING_OPERATING_MODEL.md
    authority: canonical
    doc_status: active
    concerns: [north_star]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/overview/CURRENT_STATE.md
    authority: canonical
    doc_status: active
    concerns: [current_state]
    role: summary
    primary_parent: docs/overview/GAP_SUMMARY.md
  - path: docs/overview/GAP_SUMMARY.md
    authority: canonical
    doc_status: active
    concerns: [gap_summary]
    role: summary
    primary_parent: docs/overview/CURRENT_STATE.md
  - path: ROADMAP.md
    authority: canonical
    doc_status: active
    concerns: [roadmap]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/plans/CLAUDE.md
    authority: canonical
    doc_status: active
    concerns: [active_plan_index]
    role: reference
    primary_parent: EXECUTION_BRIEF.md
code_surfaces: []
""",
    )

    issues = doc_authority.validate_doc_authority(repo_root)

    assert any(issue.code == "doc_spine_cycle" for issue in issues)


def test_validate_doc_authority_fails_when_code_surface_primary_spec_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    _write_doc_spine_fixture(repo_root)
    _write(repo_root / "ROADMAP.md", "roadmap\n")
    _write_doc_spine_config(
        repo_root,
        """schema_version: 2
indexed_authority_surfaces: []
doc_spine:
  root_doc: EXECUTION_BRIEF.md
  required_concerns: [execution_brief, north_star, current_state, gap_summary, roadmap, active_plan_index]
role_budgets: {}
docs:
  - path: EXECUTION_BRIEF.md
    authority: canonical
    doc_status: active
    concerns: [execution_brief]
    role: execution_brief
    primary_parent: null
  - path: PLANNING_OPERATING_MODEL.md
    authority: canonical
    doc_status: active
    concerns: [north_star]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/overview/CURRENT_STATE.md
    authority: canonical
    doc_status: active
    concerns: [current_state]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/overview/GAP_SUMMARY.md
    authority: canonical
    doc_status: active
    concerns: [gap_summary]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: ROADMAP.md
    authority: canonical
    doc_status: active
    concerns: [roadmap]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/plans/CLAUDE.md
    authority: canonical
    doc_status: active
    concerns: [active_plan_index]
    role: reference
    primary_parent: EXECUTION_BRIEF.md
code_surfaces:
  - paths: [enforced_planning/doc_authority.py]
    primary_spec: docs/plans/missing.md
""",
    )

    issues = doc_authority.validate_doc_authority(repo_root)

    assert any(issue.code == "code_surface_primary_spec_missing" for issue in issues)


def test_validate_doc_authority_warns_when_required_read_budget_exceeded(tmp_path: Path) -> None:
    repo_root = tmp_path / "demo"
    _write_doc_spine_fixture(repo_root)
    _write(repo_root / "ROADMAP.md", "roadmap\n")
    _write(repo_root / "enforced_planning/doc_authority.py", "code\n")
    _write_doc_spine_config(
        repo_root,
        """schema_version: 2
indexed_authority_surfaces: []
doc_spine:
  root_doc: EXECUTION_BRIEF.md
  required_concerns: [execution_brief, north_star, current_state, gap_summary, roadmap, active_plan_index]
  max_required_read_docs: 2
role_budgets: {}
docs:
  - path: EXECUTION_BRIEF.md
    authority: canonical
    doc_status: active
    concerns: [execution_brief]
    role: execution_brief
    primary_parent: null
  - path: PLANNING_OPERATING_MODEL.md
    authority: canonical
    doc_status: active
    concerns: [north_star]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/overview/CURRENT_STATE.md
    authority: canonical
    doc_status: active
    concerns: [current_state]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/overview/GAP_SUMMARY.md
    authority: canonical
    doc_status: active
    concerns: [gap_summary]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
    required_context:
      - path: docs/overview/CURRENT_STATE.md
        reason: current context
  - path: ROADMAP.md
    authority: canonical
    doc_status: active
    concerns: [roadmap]
    role: summary
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/plans/CLAUDE.md
    authority: canonical
    doc_status: active
    concerns: [active_plan_index]
    role: reference
    primary_parent: EXECUTION_BRIEF.md
  - path: docs/plans/55_test.md
    authority: canonical
    doc_status: active
    concerns: []
    role: plan
    primary_parent: docs/overview/GAP_SUMMARY.md
code_surfaces:
  - paths: [enforced_planning/doc_authority.py]
    primary_spec: docs/plans/55_test.md
""",
    )

    issues = doc_authority.validate_doc_authority(repo_root)

    budget_issues = [issue for issue in issues if issue.code == "required_read_budget_exceeded"]
    assert budget_issues
    assert all(issue.severity == "warn" for issue in budget_issues)
