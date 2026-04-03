"""Tests for hook_log.py gate/read event construction."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "hook_log.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("hook_log_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(SCRIPT.parent))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_build_gate_entry_records_required_reads_and_completion(tmp_path: Path) -> None:
    """Gate entries should reflect the required-read state from real relationships input."""
    module = _load()
    repo_root = tmp_path
    config_path = repo_root / "scripts" / "relationships.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "required_reading:\n"
        "  defaults:\n"
        "    - CLAUDE.md\n"
        "governance: []\n"
        "couplings: []\n"
        "architecture: []\n",
        encoding="utf-8",
    )
    reads_file = repo_root / ".claude" / "reads.txt"
    reads_file.parent.mkdir(parents=True, exist_ok=True)
    reads_file.write_text("CLAUDE.md\n", encoding="utf-8")

    entry = module._build_gate_entry(  # type: ignore[attr-defined]
        repo_root=repo_root,
        file_path="scripts/demo.py",
        tool_name="Edit",
        decision="allow",
        reads_file=reads_file,
        config_path=config_path,
        reason="all required docs were read",
        context_emitted=True,
        context_bytes=21,
        experiment_id="exp-1",
        variant_id="variant-a",
        downstream_run_id="run-1",
    )

    assert entry["hook"] == "gate-edit"
    assert entry["required_reads"] == ["CLAUDE.md"]
    assert entry["reads_completed"] == ["CLAUDE.md"]
    assert entry["missing_reads"] == []
    assert entry["scope_violations"] == []
    assert entry["scope_warnings"] == []
    assert entry["context_emitted"] is True
    assert entry["experiment_id"] == "exp-1"


def test_write_entry_appends_jsonl_record(tmp_path: Path) -> None:
    """Log writes should append one stable JSON line to disk."""
    module = _load()
    log_file = tmp_path / ".claude" / "hook_log.jsonl"

    module._write_entry(  # type: ignore[attr-defined]
        log_file,
        {"hook": "track-reads", "file_path": "CLAUDE.md", "decision": "recorded"},
    )

    payload = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert payload == [
        {"hook": "track-reads", "file_path": "CLAUDE.md", "decision": "recorded"}
    ]
