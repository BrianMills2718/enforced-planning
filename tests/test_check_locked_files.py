"""Tests for check_locked_files.py — acceptance-gate lock enforcement.

Covers the pure-function layer: extract_locked_criteria and
compare_locked_criteria.  Git-dependent helpers (get_file_at_ref,
get_changed_feature_files) are not tested here.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "check_locked_files_module", SCRIPTS_DIR / "check_locked_files.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# extract_locked_criteria
# ---------------------------------------------------------------------------


def test_extract_locked_criteria_returns_locked_entries() -> None:
    """Only criteria with locked: true are returned."""
    m = _load()
    data = {
        "acceptance_criteria": [
            {"id": "AC-1", "scenario": "Happy path", "locked": True, "given": "X"},
            {"id": "AC-2", "scenario": "Edge case", "locked": False},
            {"id": "AC-3", "scenario": "Error case"},  # no locked key
        ]
    }
    result = m.extract_locked_criteria(data)  # type: ignore[attr-defined]
    assert "AC-1" in result
    assert "AC-2" not in result
    assert "AC-3" not in result


def test_extract_locked_criteria_empty_list() -> None:
    """No criteria means empty result."""
    m = _load()
    data: dict = {"acceptance_criteria": []}
    result = m.extract_locked_criteria(data)  # type: ignore[attr-defined]
    assert result == {}


def test_extract_locked_criteria_missing_key() -> None:
    """Data without acceptance_criteria key is safe."""
    m = _load()
    result = m.extract_locked_criteria({})  # type: ignore[attr-defined]
    assert result == {}


def test_extract_locked_criteria_uses_scenario_as_fallback_id() -> None:
    """When 'id' is absent, 'scenario' is used as the dict key."""
    m = _load()
    data = {
        "acceptance_criteria": [
            {"scenario": "No ID criterion", "locked": True},
        ]
    }
    result = m.extract_locked_criteria(data)  # type: ignore[attr-defined]
    assert "No ID criterion" in result


# ---------------------------------------------------------------------------
# compare_locked_criteria
# ---------------------------------------------------------------------------


def _locked_criterion(**kwargs: object) -> dict:
    base: dict = {"id": "AC-1", "locked": True, "scenario": "Baseline", "given": "G", "when": "W", "then": "T"}
    base.update(kwargs)
    return base


def test_compare_locked_criteria_no_changes_returns_empty() -> None:
    """Identical base and current criteria produce no violations."""
    m = _load()
    c = _locked_criterion()
    violations = m.compare_locked_criteria(  # type: ignore[attr-defined]
        {"AC-1": c}, {"AC-1": c}, "feat"
    )
    assert violations == []


def test_compare_locked_criteria_modified_field_is_violation() -> None:
    """Changing a locked field (e.g. 'then') is a violation."""
    m = _load()
    base = _locked_criterion(then="Original outcome")
    current = _locked_criterion(then="Changed outcome")
    violations = m.compare_locked_criteria(  # type: ignore[attr-defined]
        {"AC-1": base}, {"AC-1": current}, "feat"
    )
    assert len(violations) == 1
    assert "then" in violations[0].section


def test_compare_locked_criteria_removed_criterion_is_violation() -> None:
    """Removing a locked criterion is a violation."""
    m = _load()
    base = _locked_criterion()
    violations = m.compare_locked_criteria(  # type: ignore[attr-defined]
        {"AC-1": base}, {}, "feat"
    )
    assert len(violations) == 1
    assert "removed" in violations[0].details.lower()


def test_compare_locked_criteria_new_locked_criterion_is_not_violation() -> None:
    """Adding a new locked criterion (not in base) is allowed."""
    m = _load()
    new_criterion = _locked_criterion(id="AC-new")
    violations = m.compare_locked_criteria(  # type: ignore[attr-defined]
        {}, {"AC-new": new_criterion}, "feat"
    )
    assert violations == []


def test_compare_locked_criteria_multiple_fields_changed() -> None:
    """Each changed field generates a separate violation."""
    m = _load()
    base = _locked_criterion(given="G1", when="W1", then="T1")
    current = _locked_criterion(given="G2", when="W2", then="T2")
    violations = m.compare_locked_criteria(  # type: ignore[attr-defined]
        {"AC-1": base}, {"AC-1": current}, "feat"
    )
    changed_fields = {v.section.split("/")[-1] for v in violations}
    assert changed_fields == {"given", "when", "then"}


# ---------------------------------------------------------------------------
# find_all_feature_files
# ---------------------------------------------------------------------------


def test_find_all_feature_files_returns_yaml_files(tmp_path: Path) -> None:
    """Returns .yaml and .yml files in the given directory."""
    m = _load()
    (tmp_path / "gate1.yaml").write_text("x: 1", encoding="utf-8")
    (tmp_path / "gate2.yml").write_text("y: 2", encoding="utf-8")
    (tmp_path / "ignore.md").write_text("# not a gate", encoding="utf-8")
    result = m.find_all_feature_files(tmp_path)  # type: ignore[attr-defined]
    names = {p.name for p in result}
    assert "gate1.yaml" in names
    assert "gate2.yml" in names
    assert "ignore.md" not in names


def test_find_all_feature_files_nonexistent_dir_returns_empty(tmp_path: Path) -> None:
    """Non-existent directory returns empty list."""
    m = _load()
    result = m.find_all_feature_files(tmp_path / "nonexistent")  # type: ignore[attr-defined]
    assert result == []
