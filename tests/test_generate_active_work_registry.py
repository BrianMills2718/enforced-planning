"""Tests for generated active-work registry outputs."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "generate_active_work_registry.py"
)


def _load_module():
    """Load the standalone registry generator script as a module."""
    module_name = "generate_active_work_registry_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_claim(claims_dir: Path, name: str, payload: dict) -> None:
    """Write one YAML claim fixture for registry-generation tests."""
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_generate_registry_outputs_json_and_markdown(tmp_path: Path) -> None:
    """Registry generation should emit machine-readable and compact markdown views."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    json_output = tmp_path / "generated" / "runtime" / "active_work_registry.json"
    markdown_output = tmp_path / "generated" / "runtime" / "active_work_registry.md"

    _write_claim(
        claims_dir,
        "write-a.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "coordination-v2-a",
            "intent": "Patch claims tool",
            "claim_type": "write",
            "write_paths": ["scripts"],
            "plan_ref": "Plan #62",
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "write-b.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-02T08:10:00+00:00",
            "expires_at": "2099-04-02T09:10:00+00:00",
            "projects": ["project-meta"],
            "scope": "coordination-v2-b",
            "intent": "Generate registry",
            "claim_type": "write",
            "write_paths": ["scripts/generate_active_work_registry.py"],
            "plan_ref": "Plan #62",
            "branch": "plan-62-coordination-v2",
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "program.yaml",
        {
            "agent": "openclaw",
            "claimed_at": "2026-04-02T08:20:00+00:00",
            "expires_at": "2099-04-02T09:20:00+00:00",
            "project": "project-meta",
            "scope": "phase-6-ops-and-governance",
            "intent": "Broad governance sweep",
        },
    )

    exit_code = module.main(
        [
            "--claims-dir",
            str(claims_dir),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["claim_count"] == 3
    assert payload["claims_by_type"] == {"program": 1, "write": 2}
    codex_entry = next(entry for entry in payload["claims"] if entry["agent"] == "codex")
    assert codex_entry["interaction_summary"]["hard_conflict_count"] == 1
    assert any(note["severity"] == "hard_conflict" for note in codex_entry["conflict_notes"])
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "# Active Work Registry" in markdown
    assert "coordination-v2-b" in markdown
    assert "hard=1" in markdown


def test_generate_registry_handles_empty_claim_set(tmp_path: Path) -> None:
    """Registry generation should still emit valid empty outputs when no claims exist."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    json_output = tmp_path / "generated" / "runtime" / "active_work_registry.json"
    markdown_output = tmp_path / "generated" / "runtime" / "active_work_registry.md"

    exit_code = module.main(
        [
            "--claims-dir",
            str(claims_dir),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["claim_count"] == 0
    assert payload["claims"] == []
    assert "No live claims." in markdown_output.read_text(encoding="utf-8")
