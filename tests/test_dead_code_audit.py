"""Tests for reviewed dead-code audit generation and validation."""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_modules() -> tuple[object, object, object]:
    check_module = import_module("check_dead_code")
    audit_module = import_module("audit_dead_code")
    validate_module = import_module("validate_dead_code_audit")
    return check_module, audit_module, validate_module


def test_build_audit_payload_preserves_existing_reviewer_notes(
    tmp_path: Path, monkeypatch
) -> None:
    """Refreshing the audit keeps reviewer annotations for matching signatures."""
    check_module, audit_module, _ = _load_modules()
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n"
        "  quality:\n"
        "    dead_code:\n"
        "      enabled: true\n",
        encoding="utf-8",
    )
    (tmp_path / "dead_code_audit.json").write_text(
        json.dumps(
            {
                "version": 1,
                "findings": [
                    {
                        "file": "src/mod.py",
                        "line": 1,
                        "name": "orphan",
                        "kind": "unused-function",
                        "detector": "vulture",
                        "confidence": 90,
                        "disposition": "keep_false_positive",
                        "note": "kept for plugin lookup",
                        "plan_ref": None,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        check_module,
        "scan_dead_code",
        lambda repo_root: check_module.Result(
            passed=True,
            findings=[
                check_module.Finding(
                    file="src/mod.py",
                    line=12,
                    name="orphan",
                    kind="unused-function",
                    confidence=90,
                )
            ],
            actionable_findings=[],
            detector="vulture",
        ),
    )

    payload = audit_module.build_audit_payload(tmp_path, "dead_code_audit.json")
    assert payload["findings_count"] == 1
    assert payload["findings"][0]["line"] == 12
    assert payload["findings"][0]["disposition"] == "keep_false_positive"
    assert payload["findings"][0]["note"] == "kept for plugin lookup"


def test_validate_dead_code_audit_accepts_active_planned_feature(
    tmp_path: Path, monkeypatch
) -> None:
    """Retained planned features must point at a live numbered plan."""
    check_module, _, validate_module = _load_modules()
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n"
        "  quality:\n"
        "    dead_code:\n"
        "      enabled: true\n"
        "      audit_file: dead_code_audit.json\n",
        encoding="utf-8",
    )
    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True)
    (plans_dir / "12_feature.md").write_text(
        "# Feature\n\n**Status:** In Progress\n",
        encoding="utf-8",
    )
    (tmp_path / "dead_code_audit.json").write_text(
        json.dumps(
            {
                "version": 1,
                "findings": [
                    {
                        "file": "src/mod.py",
                        "line": 12,
                        "name": "orphan",
                        "kind": "unused-function",
                        "detector": "vulture",
                        "confidence": 90,
                        "disposition": "keep_planned_feature",
                        "note": "waiting on planned rollout",
                        "plan_ref": "Plan #12",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        check_module,
        "scan_dead_code",
        lambda repo_root: check_module.Result(
            passed=True,
            findings=[
                check_module.Finding(
                    file="src/mod.py",
                    line=12,
                    name="orphan",
                    kind="unused-function",
                    confidence=90,
                )
            ],
            actionable_findings=[],
            detector="vulture",
        ),
    )

    payload = validate_module.validate_dead_code_audit(tmp_path, "dead_code_audit.json")
    assert payload["passed"] is True


def test_validate_dead_code_audit_fails_on_stale_or_unreviewed_entries(
    tmp_path: Path, monkeypatch
) -> None:
    """Validation fails on stale reviewed entries and on missing review coverage."""
    check_module, _, validate_module = _load_modules()
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n"
        "  quality:\n"
        "    dead_code:\n"
        "      enabled: true\n",
        encoding="utf-8",
    )
    (tmp_path / "dead_code_audit.json").write_text(
        json.dumps(
            {
                "version": 1,
                "findings": [
                    {
                        "file": "src/old.py",
                        "line": 1,
                        "name": "old",
                        "kind": "unused-function",
                        "detector": "vulture",
                        "confidence": 90,
                        "disposition": "keep_false_positive",
                        "note": "stale entry",
                        "plan_ref": None,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        check_module,
        "scan_dead_code",
        lambda repo_root: check_module.Result(
            passed=True,
            findings=[
                check_module.Finding(
                    file="src/new.py",
                    line=5,
                    name="new",
                    kind="unused-function",
                    confidence=90,
                )
            ],
            actionable_findings=[],
            detector="vulture",
        ),
    )

    payload = validate_module.validate_dead_code_audit(tmp_path, "dead_code_audit.json")
    assert payload["passed"] is False
    assert any("stale reviewed finding" in error for error in payload["errors"])
    assert any("no reviewed disposition" in error for error in payload["errors"])
