"""The launcher must prefer published safe code without risking a Stop loop."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "evidence_sample_launcher.sh"


def _payload(*, stop_hook_active: bool) -> str:
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "session_id": "launcher-test",
            "last_assistant_message": (
                "- **Done** — measured it.\n"
                "- **Concerns** — 20 mismatches remain without a sample."
            ),
            "stop_hook_active": stop_hook_active,
        }
    )


def test_launcher_preserves_stdin_and_the_refire_escape() -> None:
    env = {
        **os.environ,
        "EVIDENCE_SAMPLE_REPO": str(ROOT),
        "EVIDENCE_SAMPLE_REF": "HEAD",
    }

    first = subprocess.run(
        ["bash", str(LAUNCHER), "--agent", "claude-code"],
        input=_payload(stop_hook_active=False),
        capture_output=True,
        text=True,
        env=env,
    )
    repeated = subprocess.run(
        ["bash", str(LAUNCHER), "--agent", "claude-code"],
        input=_payload(stop_hook_active=True),
        capture_output=True,
        text=True,
        env=env,
    )

    assert first.returncode == 2
    assert repeated.returncode == 0
    assert repeated.stderr == ""


def test_launcher_fails_open_for_a_published_hook_without_the_refire_guard(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "scripts" / "evidence_sample_hook.py").write_text(
        "raise SystemExit(2)\n", encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "unsafe hook"], check=True)

    result = subprocess.run(
        ["bash", str(LAUNCHER), "--agent", "claude-code"],
        input=_payload(stop_hook_active=False),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "EVIDENCE_SAMPLE_REPO": str(repo),
            "EVIDENCE_SAMPLE_REF": "HEAD",
        },
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
