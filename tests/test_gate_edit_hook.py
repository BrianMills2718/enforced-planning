"""Integration tests for report-only relationship context in the edit gate."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "claude" / "gate-edit.sh"


def _repo(tmp_path: Path, *, context_script: str) -> Path:
    """Create a Git repo with successful read gating and a controlled packet CLI."""

    repo = tmp_path / "repo"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    (repo / "scripts" / "meta").mkdir(parents=True)
    (repo / "src").mkdir()
    shutil.copy2(HOOK, repo / ".claude" / "hooks" / "gate-edit.sh")
    (repo / "scripts" / "check_required_reading.py").write_text(
        '"""Test read gate that permits the edit."""\n',
        encoding="utf-8",
    )
    (repo / "scripts" / "meta" / "context_packet.py").write_text(
        context_script,
        encoding="utf-8",
    )
    (repo / "scripts" / "relationships.yaml").write_text(
        "required_reading:\n  defaults: []\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def _invoke(repo: Path, target: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the canonical shell hook with one Write request."""

    return subprocess.run(
        ["bash", str(repo / ".claude" / "hooks" / "gate-edit.sh")],
        input=json.dumps(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(target)},
            }
        ),
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gate_injects_report_only_packet_for_untracked_write(tmp_path: Path) -> None:
    """A new file gets packet context while the existing allow decision remains intact."""

    repo = _repo(
        tmp_path,
        context_script=(
            '"""Controlled context packet CLI."""\n'
            "import json, sys\n"
            "print(json.dumps({'target': sys.argv[1], 'diagnostics': "
            "[{'code': 'target-untracked-new-file'}]}))\n"
        ),
    )

    result = _invoke(repo, repo / "src" / "new_service.py")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "RELATIONSHIP CONTEXT PACKET" in context
    assert '"target": "src/new_service.py"' in context
    assert "target-untracked-new-file" in context


def test_gate_surfaces_packet_failure_without_blocking_report_only_edit(tmp_path: Path) -> None:
    """Compiler defects stay visible but do not become a premature enforcement gate."""

    repo = _repo(
        tmp_path,
        context_script=(
            '"""Controlled failing context packet CLI."""\n'
            "import sys\n"
            "print('malformed relationship graph', file=sys.stderr)\n"
            "raise SystemExit(2)\n"
        ),
    )

    result = _invoke(repo, repo / "src" / "service.py")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "RELATIONSHIP CONTEXT ERROR (report-only; edit allowed)" in context
    assert "malformed relationship graph" in context
