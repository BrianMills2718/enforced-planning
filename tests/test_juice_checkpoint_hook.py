from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "juice_checkpoint_hook.py"


def invoke(
    *,
    agent: str,
    state_dir: Path,
    session_id: str,
    event_name: str,
    now_epoch: int,
) -> subprocess.CompletedProcess[str]:
    """Run one deterministic native hook callback."""

    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--agent",
            agent,
            "--state-dir",
            str(state_dir),
            "--now-epoch",
            str(now_epoch),
        ],
        input=json.dumps(
            {
                "session_id": session_id,
                "hook_event_name": event_name,
                "event_id": f"{session_id}-{event_name}-{now_epoch}",
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )


def test_codex_injects_once_per_45_minutes_at_post_tool_boundary(tmp_path: Path) -> None:
    """The timer stays silent before the interval and suppresses immediate repeats."""

    state_dir = tmp_path / "state"
    first = invoke(
        agent="codex", state_dir=state_dir, session_id="codex-one", event_name="PostToolUse", now_epoch=1_000
    )
    early = invoke(
        agent="codex", state_dir=state_dir, session_id="codex-one", event_name="PostToolUse", now_epoch=3_699
    )
    due = invoke(
        agent="codex", state_dir=state_dir, session_id="codex-one", event_name="PostToolUse", now_epoch=3_700
    )
    repeat = invoke(
        agent="codex", state_dir=state_dir, session_id="codex-one", event_name="PostToolUse", now_epoch=3_701
    )
    due_again = invoke(
        agent="codex", state_dir=state_dir, session_id="codex-one", event_name="PostToolUse", now_epoch=6_400
    )

    assert first.returncode == 0 and first.stdout == ""
    assert early.returncode == 0 and early.stdout == ""
    message = json.loads(due.stdout)["systemMessage"]
    assert "JUICE CHECK (non-blocking)" in message
    assert "substantially more impressive or useful" in message
    assert "switch now without asking" in message
    assert repeat.returncode == 0 and repeat.stdout == ""
    assert "JUICE CHECK (non-blocking)" in json.loads(due_again.stdout)["systemMessage"]


def test_session_start_resets_timer_and_claude_uses_additional_context(tmp_path: Path) -> None:
    """A resumed session gets a fresh interval and Claude receives its native envelope."""

    state_dir = tmp_path / "state"
    assert invoke(
        agent="claude-code",
        state_dir=state_dir,
        session_id="claude-one",
        event_name="SessionStart",
        now_epoch=1_000,
    ).stdout == ""
    assert invoke(
        agent="claude-code",
        state_dir=state_dir,
        session_id="claude-one",
        event_name="PostToolUse",
        now_epoch=3_699,
    ).stdout == ""
    due = invoke(
        agent="claude-code",
        state_dir=state_dir,
        session_id="claude-one",
        event_name="PostToolUse",
        now_epoch=3_700,
    )
    payload = json.loads(due.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "JUICE CHECK (non-blocking)" in payload["hookSpecificOutput"]["additionalContext"]


def test_user_prompt_is_silent_and_malformed_input_warns_without_failing(tmp_path: Path) -> None:
    """The reminder does not interrupt a user turn, while broken state remains visible."""

    prompt = invoke(
        agent="codex",
        state_dir=tmp_path / "state",
        session_id="codex-two",
        event_name="UserPromptSubmit",
        now_epoch=10_000,
    )
    malformed = subprocess.run(
        [sys.executable, str(SCRIPT), "--agent", "codex", "--state-dir", str(tmp_path / "state")],
        input="{}",
        capture_output=True,
        text=True,
        check=False,
    )

    assert prompt.returncode == 0 and prompt.stdout == ""
    assert malformed.returncode == 0
    assert "juice checkpoint unavailable" in json.loads(malformed.stdout)["systemMessage"]
