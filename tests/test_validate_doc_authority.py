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
) -> None:
    coordination_claims.CLAIMS_DIR = claims_dir
    ok, message = coordination_claims.create_claim(
        agent="codex",
        project=repo_root.name,
        scope=scope,
        intent="test claim",
        plan_ref="Plan #38",
        claim_type="write",
        write_paths=write_paths,
        worktree_path=str(repo_root),
        repo_root=str(repo_root),
        branch="main",
        session_id="codex:test-session",
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
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected finish_session to fail on unresolved authority obligations")

    assert "unresolved reconciliation obligations" in message
    assert "docs/plans/CLAUDE.md" in message
