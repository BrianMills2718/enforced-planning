"""Focused tests for the portable cross-client completed-work learning gate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "learning_capture_hook.py"


def run_hook(tmp_path: Path, report: str, *, agent: str = "codex") -> subprocess.CompletedProcess[str]:
    """Run one native-shaped Stop event through the hook."""
    return subprocess.run(
        ["python3", str(SCRIPT), "--agent", agent, "--state-dir", str(tmp_path)],
        input=json.dumps(
            {
                "session_id": "session-123",
                "hook_event_name": "Stop",
                "last_assistant_message": report,
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )


def receipts(tmp_path: Path) -> list[dict[str, object]]:
    """Load every emitted disposition receipt."""
    return [json.loads(path.read_text(encoding="utf-8")) for path in tmp_path.glob("*/*.json")]


def test_non_completed_response_is_not_gated(tmp_path: Path) -> None:
    """Discussion and clarification turns must not manufacture learning paperwork."""
    result = run_hook(tmp_path, "Here is the explanation you requested.")

    assert result.returncode == 0
    assert result.stdout == ""
    assert receipts(tmp_path) == []


def test_completed_work_without_learning_disposition_is_blocked(tmp_path: Path) -> None:
    """A Done report cannot let a reusable learning silently die in the transcript."""
    result = run_hook(tmp_path, "- **Done** — Implemented the fix.\n- **Policy** — Followed.")

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "Learnings disposition" in payload["reason"]
    assert receipts(tmp_path)[0]["decision"] == "block_missing"


def test_recorded_learning_requires_canonical_register_reference(tmp_path: Path) -> None:
    """Self-reporting 'recorded' without the durable register is not accepted."""
    result = run_hook(
        tmp_path,
        "- **Done** — Implemented.\n- **Learnings** — Recorded in my notes.",
        agent="claude-code",
    )

    assert json.loads(result.stdout)["decision"] == "block"
    assert receipts(tmp_path)[0]["decision"] == "block_unverifiable_record"


def test_recorded_learning_is_accepted_and_receipted(tmp_path: Path) -> None:
    """Both clients can cite the canonical register and stop normally."""
    result = run_hook(
        tmp_path,
        "- **Done** — Implemented.\n"
        "- **Learnings** — Recorded — project-meta/learnings.md at commit abc1234.",
        agent="claude-code",
    )

    assert result.returncode == 0
    assert result.stdout == ""
    receipt = receipts(tmp_path)[0]
    assert receipt["decision"] == "recorded"
    assert receipt["agent"] == "claude-code"
    assert "last_assistant_message" not in receipt


def test_none_requires_a_concrete_reason(tmp_path: Path) -> None:
    """The no-learning path must be an explicit judgment, not an empty bypass."""
    blocked = run_hook(tmp_path, "- **Done** — Explained.\n- **Learnings** — None.")
    assert json.loads(blocked.stdout)["decision"] == "block"

    accepted = run_hook(
        tmp_path,
        "- **Done** — Applied a mechanical spelling correction.\n"
        "- **Learnings** — None — the change was mechanical and exposed no reusable behavior.",
    )
    assert accepted.stdout == ""
    assert {receipt["decision"] for receipt in receipts(tmp_path)} == {"block_empty_none", "none"}


def test_malformed_stop_payload_fails_closed(tmp_path: Path) -> None:
    """A broken hook contract is visible and cannot silently skip the gate."""
    result = subprocess.run(
        ["python3", str(SCRIPT), "--agent", "codex", "--state-dir", str(tmp_path)],
        input=json.dumps({"session_id": "session-123", "hook_event_name": "Stop"}),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "requires non-empty 'last_assistant_message'" in payload["reason"]


def test_non_object_hook_payload_fails_closed(tmp_path: Path) -> None:
    """A syntactically valid but structurally wrong payload cannot bypass the gate."""
    result = subprocess.run(
        ["python3", str(SCRIPT), "--agent", "codex", "--state-dir", str(tmp_path)],
        input="[]",
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "hook input must be a JSON object" in payload["reason"]


def test_install_check_requires_both_exact_client_commands(tmp_path: Path) -> None:
    """Configuration liveness is true only when both Stop adapters use this source."""
    codex = tmp_path / "config.toml"
    claude = tmp_path / "settings.json"
    codex.write_text(
        '[[hooks.Stop]]\n[[hooks.Stop.hooks]]\ncommand = "python3 '
        f'{SCRIPT} --agent codex"\n',
        encoding="utf-8",
    )
    claude.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {"command": f"python3 {SCRIPT} --agent claude-code"},
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    live = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--check-install",
            "--codex-config",
            str(codex),
            "--claude-settings",
            str(claude),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert live.returncode == 0
    assert json.loads(live.stdout)["live"] is True

    claude.write_text("{}", encoding="utf-8")
    missing = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--check-install",
            "--codex-config",
            str(codex),
            "--claude-settings",
            str(claude),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["claude_code_stop_hook"] is False
