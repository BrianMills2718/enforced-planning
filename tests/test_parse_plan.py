"""Tests for parse_plan.py — plan file parsing utilities.

Covers the pure-function layer: parse_files_affected, parse_references_reviewed,
parse_research_basis, check_file_in_scope, and get_plan_number_from_branch.
Git-dependent helpers (find_plan_file, get_active_plan_number) are not tested
here because they require a real repository context.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "parse_plan_module", SCRIPTS_DIR / "parse_plan.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# get_plan_number_from_branch
# ---------------------------------------------------------------------------


def test_branch_with_plan_prefix_returns_number() -> None:
    """plan-15-feature-name should yield 15."""
    m = _load()
    assert m.get_plan_number_from_branch("plan-15-feature-name") == 15  # type: ignore[attr-defined]


def test_branch_single_digit_plan_returns_number() -> None:
    """plan-7-foo should yield 7."""
    m = _load()
    assert m.get_plan_number_from_branch("plan-7-foo") == 7  # type: ignore[attr-defined]


def test_branch_without_plan_prefix_returns_none() -> None:
    """main and feature branches have no plan number."""
    m = _load()
    assert m.get_plan_number_from_branch("main") is None  # type: ignore[attr-defined]
    assert m.get_plan_number_from_branch("feature-xyz") is None  # type: ignore[attr-defined]
    assert m.get_plan_number_from_branch("") is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# parse_files_affected
# ---------------------------------------------------------------------------


def test_parse_files_affected_basic_entries() -> None:
    """Standard Files Affected section parses all entries."""
    m = _load()
    content = (
        "## Files Affected\n"
        "- src/foo.py (modify)\n"
        "- src/bar.py (create)\n"
        "- tests/test_foo.py (create)\n"
    )
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 3
    assert result[0] == {"path": "src/foo.py", "action": "modify"}
    assert result[1] == {"path": "src/bar.py", "action": "create"}
    assert result[2] == {"path": "tests/test_foo.py", "action": "create"}


def test_parse_files_affected_default_action_is_modify() -> None:
    """Entry without an action defaults to 'modify'."""
    m = _load()
    content = "## Files Affected\n- src/foo.py\n"
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["action"] == "modify"


def test_parse_files_affected_stops_at_next_heading() -> None:
    """Parser must not bleed into the next ## section."""
    m = _load()
    content = (
        "## Files Affected\n"
        "- src/a.py (modify)\n"
        "\n"
        "## Steps\n"
        "- Do something\n"
    )
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "src/a.py"


def test_parse_files_affected_missing_section_returns_empty() -> None:
    """When no Files Affected section exists, return an empty list."""
    m = _load()
    content = "## Steps\n- Do something\n"
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert result == []


def test_parse_files_affected_ignores_comment_lines() -> None:
    """Lines starting with # inside the section are skipped."""
    m = _load()
    content = (
        "## Files Affected\n"
        "# this is a comment\n"
        "- src/real.py (modify)\n"
    )
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "src/real.py"


def test_parse_files_affected_asterisk_bullet() -> None:
    """Both * and - bullets work."""
    m = _load()
    content = "## Files Affected\n* src/star.py (delete)\n"
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0] == {"path": "src/star.py", "action": "delete"}


# ---------------------------------------------------------------------------
# parse_references_reviewed
# ---------------------------------------------------------------------------


def test_parse_references_reviewed_with_line_range() -> None:
    """Line ranges are captured as start/end dicts."""
    m = _load()
    content = (
        "## References Reviewed\n"
        "- src/executor.py:45-89 - existing action handling\n"
    )
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "src/executor.py"
    assert result[0]["lines"] == {"start": 45, "end": 89}
    assert result[0]["description"] == "existing action handling"


def test_parse_references_reviewed_without_lines() -> None:
    """References without line numbers have no 'lines' key."""
    m = _load()
    content = "## References Reviewed\n- docs/architecture.md - overview\n"
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert "lines" not in result[0]
    assert result[0]["path"] == "docs/architecture.md"
    assert result[0]["description"] == "overview"


def test_parse_references_reviewed_strips_markdown_backticks() -> None:
    """Backticked paths should parse to the raw path."""
    m = _load()
    content = "## References Reviewed\n- `docs/architecture.md` - overview\n"
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "docs/architecture.md"


def test_parse_references_reviewed_without_description() -> None:
    """References without a description have no 'description' key."""
    m = _load()
    content = "## References Reviewed\n- docs/README.md\n"
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert "description" not in result[0] or result[0].get("description") == ""


def test_parse_references_reviewed_missing_section_returns_empty() -> None:
    """When no References Reviewed section exists, return an empty list."""
    m = _load()
    content = "## Files Affected\n- src/foo.py\n"
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert result == []


def test_parse_references_reviewed_multiple_entries() -> None:
    """Multiple reference entries are all captured."""
    m = _load()
    content = (
        "## References Reviewed\n"
        "- src/a.py:1-10 - first file\n"
        "- docs/b.md - second file\n"
        "- src/c.py\n"
    )
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 3


# ---------------------------------------------------------------------------
# parse_research_basis
# ---------------------------------------------------------------------------


def test_parse_research_basis_with_line_range() -> None:
    """Line ranges are captured for research references too."""
    m = _load()
    content = (
        "## Research Basis For This Slice\n"
        "- investigations/cross-project/example.md:12-30 - compared options\n"
    )
    result = m.parse_research_basis(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "investigations/cross-project/example.md"
    assert result[0]["lines"] == {"start": 12, "end": 30}
    assert result[0]["description"] == "compared options"


def test_parse_research_basis_without_description() -> None:
    """Bare research references parse without a description."""
    m = _load()
    content = "## Research Basis For This Slice\n- research/topic/SYNTHESIS.md\n"
    result = m.parse_research_basis(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "research/topic/SYNTHESIS.md"
    assert "description" not in result[0] or result[0].get("description") == ""


def test_parse_research_basis_strips_markdown_backticks() -> None:
    """Backticked research references should parse to the raw path."""
    m = _load()
    content = "## Research Basis For This Slice\n- `research/topic/SYNTHESIS.md` - reusable guidance\n"
    result = m.parse_research_basis(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "research/topic/SYNTHESIS.md"


def test_parse_research_basis_ignores_explicit_skip_statements() -> None:
    """Explicit skip statements should not be treated as file references."""
    m = _load()
    content = (
        "## Research Basis For This Slice\n"
        "- No additional research beyond References Reviewed.\n"
    )
    result = m.parse_research_basis(content)  # type: ignore[attr-defined]
    assert result == []


def test_parse_research_basis_missing_section_returns_empty() -> None:
    """When no research basis section exists, return an empty list."""
    m = _load()
    content = "## References Reviewed\n- docs/README.md\n"
    result = m.parse_research_basis(content)  # type: ignore[attr-defined]
    assert result == []


# ---------------------------------------------------------------------------
# parse_research_citations
# ---------------------------------------------------------------------------


def test_parse_research_citations_reads_header_list() -> None:
    """Header list values should parse as citation strings."""
    m = _load()
    content = '**research_citations:** ["agent_memory:sm-0123", "agent_memory:ep-0456"]\n'
    result = m.parse_research_citations(content)  # type: ignore[attr-defined]
    assert result == ["agent_memory:sm-0123", "agent_memory:ep-0456"]


def test_parse_research_citations_missing_field_returns_empty() -> None:
    """Absent metadata should normalize to an empty list."""
    m = _load()
    result = m.parse_research_citations("# Plan\n")  # type: ignore[attr-defined]
    assert result == []


def test_parse_research_citations_ignores_invalid_yaml() -> None:
    """Malformed values should not crash the parser surface."""
    m = _load()
    content = "**research_citations:** [agent_memory:sm-0123\n"
    result = m.parse_research_citations(content)  # type: ignore[attr-defined]
    assert result == []


# ---------------------------------------------------------------------------
# check_file_in_scope
# ---------------------------------------------------------------------------


def test_file_in_scope_exact_match() -> None:
    """Exact path match is in scope."""
    m = _load()
    files = [{"path": "src/foo.py", "action": "modify"}]
    in_scope, reason = m.check_file_in_scope("src/foo.py", files)  # type: ignore[attr-defined]
    assert in_scope
    assert "modify" in reason


def test_file_in_scope_directory_prefix() -> None:
    """File under a declared directory is in scope."""
    m = _load()
    files = [{"path": "src", "action": "modify"}]
    in_scope, _ = m.check_file_in_scope("src/nested/file.py", files)  # type: ignore[attr-defined]
    assert in_scope


def test_file_not_in_scope() -> None:
    """File that is not declared and not under a declared directory is out of scope."""
    m = _load()
    files = [{"path": "src/foo.py", "action": "modify"}]
    in_scope, reason = m.check_file_in_scope("tests/test_other.py", files)  # type: ignore[attr-defined]
    assert not in_scope
    assert "Not in Files Affected" in reason


def test_file_scope_empty_files_list() -> None:
    """Empty files list means nothing is in scope."""
    m = _load()
    in_scope, _ = m.check_file_in_scope("src/anything.py", [])  # type: ignore[attr-defined]
    assert not in_scope


def test_file_scope_does_not_match_partial_name() -> None:
    """src/foo_extra.py should not match declared path src/foo.py (exact only)."""
    m = _load()
    files = [{"path": "src/foo.py", "action": "modify"}]
    in_scope, _ = m.check_file_in_scope("src/foo_extra.py", files)  # type: ignore[attr-defined]
    assert not in_scope


# ---------------------------------------------------------------------------
# parse_steps / parse_acceptance_criteria
# ---------------------------------------------------------------------------


def test_parse_steps_reads_checkbox_plan_section() -> None:
    """Checkbox lists in a Plan section should produce numbered step records."""
    m = _load()
    content = (
        "## Plan\n"
        "- [x] Freeze the scope\n"
        "- [ ] Port the code\n"
    )
    result = m.parse_steps(content)  # type: ignore[attr-defined]
    assert result == [
        {"number": 1, "description": "Freeze the scope", "status": "done"},
        {"number": 2, "description": "Port the code", "status": "not_started"},
    ]


def test_parse_steps_reads_pipe_table_statuses() -> None:
    """Pipe-table steps should normalize their status strings."""
    m = _load()
    content = (
        "## Steps\n"
        "| Step | What | Status |\n"
        "|------|------|--------|\n"
        "| 1 | Freeze scope | Complete |\n"
        "| 2 | Port code | In Progress |\n"
    )
    result = m.parse_steps(content)  # type: ignore[attr-defined]
    assert result == [
        {"number": 1, "description": "Freeze scope", "status": "done"},
        {"number": 2, "description": "Port code", "status": "in_progress"},
    ]


def test_parse_acceptance_criteria_reads_checkbox_items() -> None:
    """Acceptance-criteria checkboxes should preserve met/unmet state."""
    m = _load()
    content = (
        "## Acceptance Criteria\n"
        "- [x] Docs are truthful\n"
        "- [ ] Tests pass upstream\n"
    )
    result = m.parse_acceptance_criteria(content)  # type: ignore[attr-defined]
    assert result == [
        {"description": "Docs are truthful", "met": True},
        {"description": "Tests pass upstream", "met": False},
    ]


def _write_canonical_claim(claims_dir: Path, *, branch: str, plan_ref: str) -> None:
    import yaml  # type: ignore[import-untyped]

    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / "claim.yaml").write_text(
        yaml.safe_dump(
            {
                "agent": "codex",
                "claimed_at": "2026-04-05T00:00:00+00:00",
                "expires_at": "2099-04-05T12:00:00+00:00",
                "projects": ["sample"],
                "scope": branch,
                "intent": "test",
                "claim_type": "write",
                "write_paths": ["scripts/x.py"],
                "branch": branch,
                "session_id": "codex:session",
                "plan_ref": plan_ref,
                "status": "active",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _legacy_active_work(main_root: Path, *, branch: str, plan: int) -> None:
    (main_root / ".claude").mkdir(parents=True, exist_ok=True)
    (main_root / ".claude" / "active-work.yaml").write_text(
        f"claims:\n  - cc_id: {branch}\n    plan: {plan}\n",
        encoding="utf-8",
    )


def test_active_plan_number_comes_from_canonical_claim(tmp_path: Path, monkeypatch) -> None:
    """Issue #610: the claim fallback reads the canonical registry, not active-work.yaml."""
    from enforced_planning import coordination_claims

    m = _load()
    _write_canonical_claim(tmp_path / "claims", branch="fix-lane", plan_ref="Plan #42")
    _legacy_active_work(tmp_path / "repo", branch="fix-lane", plan=7)
    monkeypatch.setattr(m, "get_current_branch", lambda: "fix-lane")
    monkeypatch.setattr(m, "get_main_repo_root", lambda: tmp_path / "repo")
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", tmp_path / "claims")

    assert m.get_active_plan_number() == 42  # type: ignore[attr-defined]


def test_legacy_active_work_yaml_alone_yields_no_plan(tmp_path: Path, monkeypatch) -> None:
    from enforced_planning import coordination_claims

    m = _load()
    (tmp_path / "claims").mkdir()
    _legacy_active_work(tmp_path / "repo", branch="fix-lane", plan=7)
    monkeypatch.setattr(m, "get_current_branch", lambda: "fix-lane")
    monkeypatch.setattr(m, "get_main_repo_root", lambda: tmp_path / "repo")
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", tmp_path / "claims")

    assert m.get_active_plan_number() is None  # type: ignore[attr-defined]
