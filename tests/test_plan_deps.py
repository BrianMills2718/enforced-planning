"""Tests for check_plan_deps.py — plan dependency format validation."""

import textwrap
from pathlib import Path

import pytest

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_plan_deps import (
    _parse_dep_refs,
    _find_plans_in_dir,
    check_plan,
    SAME_PROJECT_REF,
    CROSS_PROJECT_REF,
    FUTURE_REF,
)


class TestPatternMatching:
    """Test regex patterns for dependency reference formats."""

    def test_same_project_hash(self):
        assert SAME_PROJECT_REF.match("#5")

    def test_same_project_plan_hash(self):
        assert SAME_PROJECT_REF.match("Plan #5")

    def test_same_project_bare_number(self):
        assert SAME_PROJECT_REF.match("5")

    def test_same_project_with_condition(self):
        assert SAME_PROJECT_REF.match("#5 — must finish first")

    def test_same_project_plan_with_prose(self):
        assert SAME_PROJECT_REF.match("Plan #7 execution sprint")

    def test_cross_project(self):
        m = CROSS_PROJECT_REF.match("llm_client#17")
        assert m
        assert m.group(1) == "llm_client"
        assert m.group(2) == "17"

    def test_cross_project_with_condition(self):
        m = CROSS_PROJECT_REF.match("llm_client#17 — API must ship")
        assert m

    def test_future_ref(self):
        assert FUTURE_REF.match("[future] improved benchmarks")

    def test_future_ref_case_insensitive(self):
        assert FUTURE_REF.match("[Future] better tooling")

    def test_prose_does_not_match_plan_ref(self):
        assert not SAME_PROJECT_REF.match("ecosystem-ops boundary audit")

    def test_prose_does_not_match_cross_ref(self):
        assert not CROSS_PROJECT_REF.match("ecosystem-ops boundary audit")


class TestParseDepRefs:
    """Test extraction of individual references from field values."""

    def test_single_ref(self):
        assert _parse_dep_refs("#5") == ["#5"]

    def test_comma_separated(self):
        refs = _parse_dep_refs("#5, #6, #7")
        assert len(refs) == 3

    def test_bullet_list(self):
        refs = _parse_dep_refs("- #5\n- #6\n- #7")
        assert len(refs) == 3
        assert refs[0] == "#5"

    def test_none_value(self):
        assert _parse_dep_refs("None") == []

    def test_dash_value(self):
        assert _parse_dep_refs("—") == []

    def test_mixed_formats(self):
        refs = _parse_dep_refs("#5\n- llm_client#17\n- [future] better infra")
        assert len(refs) == 3


class TestCheckPlan:
    """Test plan checking against a local plan index."""

    @pytest.fixture
    def plans_dir(self, tmp_path):
        """Create a temp plans directory with numbered plans."""
        d = tmp_path / "docs" / "plans"
        d.mkdir(parents=True)
        (d / "01_first.md").write_text("# Plan #1: First\n**Status:** Planned\n**Blocked By:** None\n**Blocks:** None\n")
        (d / "02_second.md").write_text("# Plan #2: Second\n**Status:** Planned\n**Blocked By:** #1\n**Blocks:** None\n")
        (d / "03_third.md").write_text("# Plan #3: Third\n**Status:** Planned\n**Blocked By:** #99\n**Blocks:** [future] better tooling\n")
        (d / "04_cross.md").write_text("# Plan #4: Cross\n**Status:** Planned\n**Blocked By:** llm_client#17\n**Blocks:** None\n")
        return d

    def test_valid_same_project_ref(self, plans_dir):
        local = _find_plans_in_dir(plans_dir)
        findings = check_plan(plans_dir / "02_second.md", local)
        assert len(findings) == 1
        assert findings[0]["status"] == "ok"

    def test_dangling_same_project_ref(self, plans_dir):
        local = _find_plans_in_dir(plans_dir)
        findings = check_plan(plans_dir / "03_third.md", local)
        # Should have an error for #99 and an ok for [future]
        errors = [f for f in findings if f["status"] == "error"]
        futures = [f for f in findings if f["type"] == "future"]
        assert len(errors) == 1
        assert "#99" in errors[0]["ref"]
        assert len(futures) == 1

    def test_cross_project_ref_without_scan(self, plans_dir):
        local = _find_plans_in_dir(plans_dir)
        findings = check_plan(plans_dir / "04_cross.md", local)
        assert len(findings) == 1
        assert findings[0]["status"] == "skip"  # Can't validate without --scan-dir

    def test_none_blocked_by(self, plans_dir):
        local = _find_plans_in_dir(plans_dir)
        findings = check_plan(plans_dir / "01_first.md", local)
        assert len(findings) == 0  # None = no deps to check

    def test_non_plan_file_skipped(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# Not a plan\nJust a readme.\n")
        findings = check_plan(readme, {})
        assert len(findings) == 0


class TestFindPlans:
    """Test plan directory scanning."""

    def test_finds_numbered_plans(self, tmp_path):
        (tmp_path / "01_first.md").write_text("")
        (tmp_path / "02_second.md").write_text("")
        (tmp_path / "README.md").write_text("")
        plans = _find_plans_in_dir(tmp_path)
        assert 1 in plans
        assert 2 in plans
        assert len(plans) == 2

    def test_empty_dir(self, tmp_path):
        plans = _find_plans_in_dir(tmp_path)
        assert len(plans) == 0
