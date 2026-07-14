"""Both-sign tests for requirement-linked test relationship auditing (Plan 64)."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from enforced_planning.test_relationships import TestRelationshipError as RelationshipAuditError
from enforced_planning.test_relationships import audit_includes
from enforced_planning.test_relationships import audit_test_relationships
from enforced_planning.test_relationships import parse_requirements
from enforced_planning.test_relationships import parse_test_edges


def _repo(tmp_path: Path) -> Path:
    """Create a tracked mini-repository with authored tests and no imports."""

    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "src" / "service.py").write_text(
        '"""Service boundary."""\n\ndef run() -> None:\n    """Run."""\n',
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_service.py").write_text(
        '''"""Service tests."""

def test_positive() -> None:
    """Positive path."""

class TestFailures:
    """Failure controls."""

    def test_rejected(self) -> None:
        """Negative path."""

def helper() -> None:
    """Not a test."""
''',
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_orphan.py").write_text(
        '"""Orphan suite."""\n\ndef test_orphan() -> None:\n    """Unlinked."""\n',
        encoding="utf-8",
    )
    (tmp_path / "docs" / "plans" / "001.md").write_text(
        "# Plan\n\n## Goal\n\nProve behavior.\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    return tmp_path


def _complete_edge(*, selector: str = "tests/test_service.py") -> dict[str, object]:
    """Return one semantically complete reviewed edge."""

    return {
        "source": selector,
        "target": "src/service.py::run",
        "relation": "tests",
        "requirement_refs": ["REQ-1"],
        "level": "integration",
        "polarity": "negative_control",
        "execution_realism": "isolated_runtime",
        "failure_modes": ["unsupported_state_accepted"],
        "risk_level": "high",
        "reason": "Proves the service rejects unsupported state.",
    }


def test_legacy_file_edge_remains_parseable_but_reports_missing_semantics(tmp_path: Path) -> None:
    """Compatibility edges produce debt findings instead of breaking consumers."""

    repo = _repo(tmp_path)
    data = {
        "relationships": [
            {
                "source": "src/service.py",
                "target": "tests/test_service.py",
                "relation": "tests",
                "reason": "Legacy suite relationship.",
            }
        ]
    }
    report = audit_test_relationships(repo, data)
    assert report.scoped_test_count == 3
    assert report.linked_test_count == 2
    assert report.semantically_linked_test_count == 0
    assert report.reviewed_edge_count == 1
    incomplete = [finding for finding in report.findings if finding.code == "TEST_EDGE_INCOMPLETE"]
    assert len(incomplete) == 1
    assert "requirement_refs" in incomplete[0].message
    assert "TEST_UNLINKED" in {finding.code for finding in report.findings}


def test_symbol_edge_links_exactly_one_authored_test(tmp_path: Path) -> None:
    """Symbol granularity does not accidentally claim the entire test file."""

    repo = _repo(tmp_path)
    report = audit_test_relationships(
        repo,
        {"relationships": [_complete_edge(selector="tests/test_service.py::test_positive")]},
    )
    assert report.linked_test_count == 1
    assert report.semantically_linked_test_count == 1
    unlinked = [finding.subject for finding in report.findings if finding.code == "TEST_UNLINKED"]
    assert "tests/test_service.py::TestFailures.test_rejected" in unlinked
    assert "tests/test_orphan.py::test_orphan" in unlinked


def test_edges_outside_selected_scope_do_not_create_false_empty_findings(tmp_path: Path) -> None:
    """A bounded pilot ignores reviewed suites deliberately outside its include scope."""

    repo = _repo(tmp_path)
    outside = _complete_edge(selector="tests/elsewhere/test_other.py")
    report = audit_test_relationships(
        repo,
        {"relationships": [outside]},
        includes=("tests/test_service.py",),
    )
    assert report.scoped_test_count == 2
    assert report.reviewed_edge_count == 0
    assert "TEST_SELECTOR_EMPTY" not in {finding.code for finding in report.findings}


def test_implementation_to_test_direction_is_supported(tmp_path: Path) -> None:
    """Existing implementation-to-test edges normalize like new test-to-code edges."""

    repo = _repo(tmp_path)
    edge = _complete_edge()
    edge["source"], edge["target"] = edge["target"], edge["source"]
    report = audit_test_relationships(repo, {"relationships": [edge]})
    assert report.linked_test_count == 2
    assert report.edges[0].implementation_boundaries == ("src/service.py::run",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("level", "component"),
        ("polarity", "bad_path"),
        ("execution_realism", "kind_of_real"),
        ("risk_level", "urgent"),
    ],
)
def test_unknown_semantic_enums_fail_loud(field: str, value: str) -> None:
    """Misspelled semantics cannot silently become misleading evidence."""

    edge = _complete_edge()
    edge[field] = value
    with pytest.raises(RelationshipAuditError, match="unsupported value"):
        parse_test_edges({"relationships": [edge]})


def test_tests_edge_must_connect_test_and_non_test_sides() -> None:
    """A test-to-test edge cannot masquerade as implementation coverage."""

    edge = _complete_edge()
    edge["target"] = "tests/test_other.py"
    with pytest.raises(RelationshipAuditError, match="test selector to a non-test boundary"):
        parse_test_edges({"relationships": [edge]})


def test_audit_scope_is_report_only() -> None:
    """Configuration cannot quietly turn the visibility tool into a hard gate."""

    assert audit_includes({"test_audit": {"include": ["tests/core/*.py"]}}) == (
        "tests/core/*.py",
    )
    with pytest.raises(RelationshipAuditError, match="must remain report_only"):
        audit_includes({"test_audit": {"mode": "hard_fail"}})


def test_requirement_records_reference_source_prose_instead_of_copying_it() -> None:
    """Requirement IDs point at authority; YAML cannot become duplicate prose."""

    with pytest.raises(RelationshipAuditError, match="duplicates authority prose"):
        parse_requirements(
            {
                "requirements": [
                    {
                        "id": "REQ-1",
                        "source": "docs/plans/001.md#requirements",
                        "risk_level": "high",
                        "description": "Duplicated requirement.",
                    }
                ]
            }
        )


def test_report_finds_unproved_mock_only_unit_only_and_missing_negative(tmp_path: Path) -> None:
    """Risk and evidence-level findings derive from declared authority, not count."""

    repo = _repo(tmp_path)
    positive_unit = _complete_edge(selector="tests/test_service.py::test_positive")
    positive_unit.update(
        {
            "level": "unit",
            "polarity": "positive",
            "execution_realism": "mock",
            "failure_modes": ["happy_path_regression"],
        }
    )
    data = {
        "requirements": [
            {"id": "REQ-1", "source": "docs/plans/001.md#req-1", "risk_level": "high"},
            {"id": "REQ-2", "source": "docs/plans/001.md#req-2", "risk_level": "medium"},
        ],
        "relationships": [positive_unit],
    }
    report = audit_test_relationships(repo, data)
    codes = {finding.code for finding in report.findings}
    assert "REQUIREMENT_UNPROVED" in codes
    assert "AUTHORITY_SYNTHETIC_ONLY" in codes
    assert "AUTHORITY_UNIT_ONLY" in codes
    assert "HIGH_RISK_NO_NEGATIVE_CONTROL" in codes
    assert report.proved_requirement_count == 1
    assert report.declared_requirement_count == 2


def test_complete_mixed_proof_avoids_false_risk_findings(tmp_path: Path) -> None:
    """Runtime negative proof closes synthetic/unit/negative-control findings."""

    repo = _repo(tmp_path)
    unit_edge = _complete_edge(selector="tests/test_service.py::test_positive")
    unit_edge.update({"level": "unit", "polarity": "positive", "execution_realism": "mock"})
    runtime_edge = _complete_edge(selector="tests/test_service.py::TestFailures.test_rejected")
    data = {
        "requirements": [
            {"id": "REQ-1", "source": "docs/plans/001.md#req-1", "risk_level": "high"}
        ],
        "relationships": [unit_edge, runtime_edge],
    }
    report = audit_test_relationships(repo, data)
    codes = {finding.code for finding in report.findings}
    assert "AUTHORITY_SYNTHETIC_ONLY" not in codes
    assert "AUTHORITY_UNIT_ONLY" not in codes
    assert "HIGH_RISK_NO_NEGATIVE_CONTROL" not in codes


def test_duplicate_shape_is_review_candidate_not_deletion_instruction(tmp_path: Path) -> None:
    """Three equivalent edges produce one explicitly bounded review signal."""

    repo = _repo(tmp_path)
    edges = [
        _complete_edge(selector="tests/test_service.py::test_positive"),
        _complete_edge(selector="tests/test_service.py::TestFailures.test_rejected"),
        _complete_edge(selector="tests/test_orphan.py::test_orphan"),
    ]
    report = audit_test_relationships(repo, {"relationships": edges})
    findings = [
        finding for finding in report.findings if finding.code == "POSSIBLE_DUPLICATE_EDGE_CLUSTER"
    ]
    assert len(findings) == 1
    assert "do not delete automatically" in findings[0].message


def test_report_output_is_deterministic_and_workspace_neutral(tmp_path: Path) -> None:
    """JSON and Markdown contain no absolute temporary workspace path or clock."""

    repo = _repo(tmp_path)
    data = {
        "requirements": [
            {"id": "REQ-1", "source": "docs/plans/001.md#req-1", "risk_level": "high"}
        ],
        "relationships": [_complete_edge()],
    }
    first = audit_test_relationships(repo, data)
    second = audit_test_relationships(repo, data)
    assert first.to_json(pretty=True) == second.to_json(pretty=True)
    assert first.to_markdown() == second.to_markdown()
    assert str(tmp_path) not in first.to_json(pretty=True)
    assert str(tmp_path) not in first.to_markdown()
