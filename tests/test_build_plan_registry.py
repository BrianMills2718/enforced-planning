"""Tests for build_plan_registry.py — cross-repo plan registry builder."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_plan_registry import (
    _extract_plan_title,
    _extract_status,
    build_registry,
    discover_governed_repos,
    find_plan_index,
    parse_plan_index,
)


# ---------------------------------------------------------------------------
# Helper: create a minimal governed repo in tmp_path
# ---------------------------------------------------------------------------

def make_governed_repo(root: Path, name: str, plans: str = "") -> Path:
    """Create a minimal governed repo structure for testing."""
    repo = root / name
    repo.mkdir()
    (repo / "meta-process.yaml").write_text("meta_process:\n  version: '1.0'\n")
    plans_dir = repo / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    default_claude = "# Plans\n\n| # | Title | Priority | Status | Blocks |\n|---|-------|----------|--------|--------|\n"
    (plans_dir / "CLAUDE.md").write_text(default_claude + plans)
    return repo


# ---------------------------------------------------------------------------
# _extract_plan_title
# ---------------------------------------------------------------------------

class TestExtractPlanTitle:
    def test_plain_text(self):
        assert _extract_plan_title("My Plan Title ") == "My Plan Title"

    def test_strips_markdown_link(self):
        assert _extract_plan_title("[My Plan](path/to/plan.md)") == "My Plan"

    def test_strips_backticks(self):
        assert _extract_plan_title("`plan_name.md`") == "plan_name.md"


# ---------------------------------------------------------------------------
# _extract_status
# ---------------------------------------------------------------------------

class TestExtractStatus:
    def test_complete_emoji(self):
        assert _extract_status("✅ Complete") == "complete"

    def test_in_progress_emoji(self):
        assert _extract_status("🚧 In Progress") == "in_progress"

    def test_planned_emoji(self):
        assert _extract_status("📋 Planned") == "planned"

    def test_blocked_emoji(self):
        assert _extract_status("⏸ Blocked") == "blocked"

    def test_complete_text_only(self):
        assert _extract_status("Complete") == "complete"

    def test_unknown_returns_lowercase(self):
        assert _extract_status("Some Custom Status") == "some custom status"


# ---------------------------------------------------------------------------
# parse_plan_index
# ---------------------------------------------------------------------------

class TestParsePlanIndex:
    def test_parses_table_rows(self, tmp_path):
        plan_index = tmp_path / "CLAUDE.md"
        plan_index.write_text(
            "# Plans\n\n"
            "| # | Title | Priority | Status | Blocks |\n"
            "|---|-------|----------|--------|--------|\n"
            "| 1 | First Plan | High | ✅ Complete | #2 |\n"
            "| 2 | Second Plan | Medium | 📋 Planned | None |\n"
        )
        plans = parse_plan_index(plan_index, "my-project")
        assert len(plans) == 2
        assert plans[0]["plan_num"] == 1
        assert plans[0]["status"] == "complete"
        assert plans[1]["plan_num"] == 2
        assert plans[1]["status"] == "planned"

    def test_project_name_set(self, tmp_path):
        plan_index = tmp_path / "CLAUDE.md"
        plan_index.write_text(
            "| # | Title | Priority | Status | Blocks |\n"
            "| 1 | Plan A | High | ✅ Complete | None |\n"
        )
        plans = parse_plan_index(plan_index, "test-project")
        assert plans[0]["project"] == "test-project"

    def test_skips_separator_rows(self, tmp_path):
        plan_index = tmp_path / "CLAUDE.md"
        plan_index.write_text(
            "| # | Title | Priority | Status | Blocks |\n"
            "|---|-------|----------|--------|--------|\n"
            "| 1 | Plan A | High | ✅ Complete | None |\n"
        )
        plans = parse_plan_index(plan_index, "proj")
        assert len(plans) == 1

    def test_empty_file(self, tmp_path):
        plan_index = tmp_path / "CLAUDE.md"
        plan_index.write_text("# Just a heading, no table rows\n")
        plans = parse_plan_index(plan_index, "proj")
        assert plans == []

    def test_handles_linked_title(self, tmp_path):
        plan_index = tmp_path / "CLAUDE.md"
        plan_index.write_text(
            "| 1 | [My Plan](01_my_plan.md) | High | ✅ Complete | None |\n"
        )
        plans = parse_plan_index(plan_index, "proj")
        assert plans[0]["title"] == "My Plan"


# ---------------------------------------------------------------------------
# discover_governed_repos
# ---------------------------------------------------------------------------

class TestDiscoverGovernedRepos:
    def test_finds_repos_with_meta_process(self, tmp_path):
        make_governed_repo(tmp_path, "repo-a")
        make_governed_repo(tmp_path, "repo-b")
        (tmp_path / "not-governed").mkdir()  # no meta-process.yaml
        repos = discover_governed_repos(tmp_path)
        names = {r.name for r in repos}
        assert "repo-a" in names
        assert "repo-b" in names
        assert "not-governed" not in names

    def test_skips_hidden_dirs(self, tmp_path):
        (tmp_path / ".hidden" / "docs" / "plans").mkdir(parents=True)
        (tmp_path / ".hidden" / "meta-process.yaml").write_text("")
        repos = discover_governed_repos(tmp_path)
        names = {r.name for r in repos}
        assert ".hidden" not in names


# ---------------------------------------------------------------------------
# find_plan_index
# ---------------------------------------------------------------------------

class TestFindPlanIndex:
    def test_finds_claude_md(self, tmp_path):
        repo = make_governed_repo(tmp_path, "my-repo")
        result = find_plan_index(repo)
        assert result is not None
        assert result.name == "CLAUDE.md"

    def test_returns_none_if_no_plans_dir(self, tmp_path):
        repo = tmp_path / "no-plans"
        repo.mkdir()
        (repo / "meta-process.yaml").write_text("")
        result = find_plan_index(repo)
        assert result is None


# ---------------------------------------------------------------------------
# build_registry
# ---------------------------------------------------------------------------

class TestBuildRegistry:
    def test_counts_plans(self, tmp_path):
        make_governed_repo(
            tmp_path, "repo-a",
            "| 1 | Plan A | High | ✅ Complete | None |\n"
            "| 2 | Plan B | Medium | 📋 Planned | None |\n"
        )
        make_governed_repo(
            tmp_path, "repo-b",
            "| 1 | Plan C | High | 🚧 In Progress | None |\n"
        )
        registry = build_registry(tmp_path)
        assert registry["total_plans"] == 3
        assert registry["complete"] == 1
        assert registry["in_progress"] == 1
        assert registry["planned"] == 1

    def test_project_names_in_registry(self, tmp_path):
        make_governed_repo(tmp_path, "repo-x", "| 1 | Plan X | High | ✅ Complete | None |\n")
        registry = build_registry(tmp_path)
        assert "repo-x" in registry["projects"]

    def test_empty_scan_dir(self, tmp_path):
        registry = build_registry(tmp_path)
        assert registry["total_plans"] == 0
        assert registry["projects"] == {}

    def test_skips_repos_without_plans(self, tmp_path):
        """Governed repos with no plan table produce no entries."""
        repo = tmp_path / "no-plans-content"
        repo.mkdir()
        (repo / "meta-process.yaml").write_text("")
        (repo / "docs" / "plans").mkdir(parents=True)
        (repo / "docs" / "plans" / "CLAUDE.md").write_text("# Plans\n\nNo table here.\n")
        registry = build_registry(tmp_path)
        # Repo exists but has no plans — should not appear in projects
        assert registry["total_plans"] == 0
