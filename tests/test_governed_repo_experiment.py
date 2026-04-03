"""Tests for scripts/governed_repo_experiment.py."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Generator
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "governed_repo_experiment_module", SCRIPTS_DIR / "governed_repo_experiment.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(autouse=True)
def _isolate_llm_client_io_log(tmp_path: Path) -> Generator[None, None, None]:
    """Isolate llm_client observability so report tests remain deterministic."""
    import llm_client.io_log as io_log  # type: ignore[import-not-found]

    old_enabled = io_log._enabled
    old_root = io_log._data_root
    old_project = io_log._project
    old_db_path = io_log._db_path
    old_db_conn = io_log._db_conn
    old_last_cleanup = io_log._last_cleanup_date

    io_log._enabled = True
    io_log._data_root = tmp_path / "io_data"
    io_log._project = "enforced_planning_test"
    io_log._db_path = tmp_path / "observability.db"
    io_log._db_conn = None
    io_log._last_cleanup_date = None

    yield

    if io_log._db_conn is not None:
        io_log._db_conn.close()
    io_log._enabled = old_enabled
    io_log._data_root = old_root
    io_log._project = old_project
    io_log._db_path = old_db_path
    io_log._db_conn = old_db_conn
    io_log._last_cleanup_date = old_last_cleanup


def _scaffold_governed_repo(repo_root: Path) -> None:
    """Create the minimum governed-repo surface required by the helper."""
    (repo_root / ".claude" / "hooks").mkdir(parents=True, exist_ok=True)
    (repo_root / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (repo_root / ".claude" / "hooks" / "gate-edit.sh").write_text(
        "#!/bin/bash\n", encoding="utf-8"
    )
    (repo_root / ".claude" / "hooks" / "track-reads.sh").write_text(
        "#!/bin/bash\n", encoding="utf-8"
    )
    (repo_root / "scripts" / "meta").mkdir(parents=True, exist_ok=True)
    (repo_root / "scripts" / "check_required_reading.py").write_text(
        '"""stub"""\n',
        encoding="utf-8",
    )
    (repo_root / "scripts" / "meta" / "hook_log.py").write_text(
        '"""stub"""\n',
        encoding="utf-8",
    )


def test_prepare_experiment_archives_existing_log_and_writes_env_file(tmp_path: Path) -> None:
    """Prepare should archive the active hook log and create a sourceable env file."""
    module = _load()
    repo_root = tmp_path / "sample_repo"
    _scaffold_governed_repo(repo_root)
    hook_log = repo_root / ".claude" / "hook_log.jsonl"
    hook_log.write_text('{"schema_version": 1}\n', encoding="utf-8")

    payload = module.prepare_experiment(  # type: ignore[attr-defined]
        repo_roots=[str(repo_root)],
        experiment_id="govhook-baseline-2026-03-20",
        variant_id="baseline-no-block-context",
    )

    prepared = payload["prepared_repos"][0]
    env_file = repo_root / prepared["env_file"]
    assert prepared["repo_name"] == "sample_repo"
    assert prepared["archived_log"] is not None
    assert env_file.exists()
    env_text = env_file.read_text(encoding="utf-8")
    assert "export CLAUDE_HOOK_EXPERIMENT_ID=govhook-baseline-2026-03-20" in env_text
    assert "export CLAUDE_HOOK_VARIANT_ID=baseline-no-block-context" in env_text
    assert "CLAUDE_SESSION_READS_FILE" in env_text
    assert not hook_log.exists()
    assert (repo_root / prepared["archived_log"]).exists()


@pytest.mark.skip(
    reason="llm_client.import_governed_repo_hook_log not yet implemented — "
    "report path depends on upstream functions in llm_client that will be "
    "added when the observation phase produces enough data to analyze"
)
def test_report_experiment_imports_logs_and_returns_repo_summary(tmp_path: Path) -> None:
    """Report should import hook logs into llm_client and expose the summary/comparison view."""
    module = _load()
    repo_root = tmp_path / "sample_repo"
    _scaffold_governed_repo(repo_root)
    hook_log = repo_root / ".claude" / "hook_log.jsonl"
    hook_log.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "timestamp": "2026-03-20T00:00:00+00:00",
                "hook": "gate-edit",
                "tool_name": "Edit",
                "file_path": "src/sample_repo/cli.py",
                "decision": "block",
                "decision_reason": "missing required reads",
                "reads_file": ".claude/session_reads.txt",
                "required_reads": ["CLAUDE.md"],
                "reads_completed": [],
                "missing_reads": ["CLAUDE.md"],
                "coupled_docs": [],
                "context_emitted": False,
                "context_bytes": 0,
                "experiment_id": "govhook-baseline-2026-03-20",
                "variant_id": "baseline-no-block-context",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    payload = module.report_experiment(  # type: ignore[attr-defined]
        repo_roots=[str(repo_root)],
        experiment_id="govhook-baseline-2026-03-20",
        days=14,
        limit=10,
    )

    assert payload["imports"][0]["imported_events"] == 1
    summary = payload["repo_summaries"][0]
    assert summary["repo_name"] == "sample_repo"
    assert summary["decision_counts"] == {"block": 1}
    assert summary["session_quality_counts"] == {"stable": 1}
    comparison = payload["comparison"]
    assert comparison["experiment_id"] == "govhook-baseline-2026-03-20"
    assert comparison["variant_count"] == 1
    assert comparison["variants"][0]["variant_id"] == "baseline-no-block-context"
