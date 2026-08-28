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


def test_openclaw_adapter_can_request_explicit_allow_result(tmp_path: Path) -> None:
    """Non-native lifecycle adapters receive a parseable allow decision."""
    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--agent",
            "openclaw",
            "--emit-result",
            "--state-dir",
            str(tmp_path),
        ],
        input=json.dumps(
            {
                "session_id": "openclaw-task-123",
                "hook_event_name": "Stop",
                "last_assistant_message": (
                    "- **Done** — Completed the coding task.\n"
                    "- **Learnings** — None — this repeated a previously verified mechanical change."
                ),
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "allow"
    assert payload["classification"] == "none"
    assert receipts(tmp_path)[0]["agent"] == "openclaw"


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


def test_install_check_requires_all_coding_agent_completion_paths(tmp_path: Path) -> None:
    """Liveness is true only when all supported agent paths use the shared gate."""
    codex = tmp_path / "config.toml"
    claude = tmp_path / "settings.json"
    openclaw = tmp_path / "run_task.py"
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
    openclaw.write_text(
        "OPENCLAW_LEARNING_CAPTURE_HOOK = True\n"
        "OPENCLAW_LEARNING_CAPTURE_REQUIRED = True\n"
        "def _apply_learning_capture_gate(): ...\n",
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
            "--openclaw-runner",
            str(openclaw),
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
            "--openclaw-runner",
            str(openclaw),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["claude_code_stop_hook"] is False

    claude.write_text(
        json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"command": f"python3 {SCRIPT} --agent claude-code"}]}]}},
        ),
        encoding="utf-8",
    )
    openclaw.write_text("# ungated runner\n", encoding="utf-8")
    missing_openclaw = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--check-install",
            "--codex-config",
            str(codex),
            "--claude-settings",
            str(claude),
            "--openclaw-runner",
            str(openclaw),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing_openclaw.returncode == 1
    assert json.loads(missing_openclaw.stdout)["openclaw_completion_gate"] is False


def _report(learnings: str) -> str:
    return f"- **Done** — shipped a change.\n- **Learnings** — {learnings}\n"


def test_decline_claiming_prior_capture_must_name_it(tmp_path: Path) -> None:
    """An unfalsifiable 'already recorded' is the most common decline in practice.

    Measured across 296 closing reports, 51% of declines given on those grounds
    cited nothing at all. The reason was honest wherever it was checkable --
    every cited reference spot-checked resolved -- but nobody reading the report
    can separate the halves.
    """
    result = run_hook(
        tmp_path, _report("None new: today's reusable findings are already recorded.")
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "name it" in payload["reason"]


def test_decline_naming_a_reference_passes(tmp_path: Path) -> None:
    """Any shape a real reference takes is accepted: entry id, sha, slug, path."""
    for reason in (
        "None: already recorded as lrn-20260822T055157292299Z-8a2a99c14a.",
        "None new; the finding is already recorded at 310022af in the register.",
        "None: already captured in memory as project_kops_quote_provenance today.",
        "None — already covered by project-meta/learnings.md from this morning.",
    ):
        result = run_hook(tmp_path, _report(reason))
        assert result.returncode == 0, reason


def test_ordinary_declines_are_untouched(tmp_path: Path) -> None:
    """The gate fires only on a claim of prior capture, not on every decline."""
    result = run_hook(
        tmp_path,
        _report("None: this turn produced no durable finding, only a status check."),
    )

    assert result.returncode == 0


def test_the_refusal_says_reformatting_is_a_complete_response(tmp_path: Path) -> None:
    """The gate must not read as an instruction to go do the recording work.

    Observed 2026-08-28. A session closed out with a blocking question for the
    user and a Learnings line reading "Worth recording: ... I haven't written it,
    because <reason>" -- the honest answer, in the wrong shape. The gate refused
    on form. The agent read the refusal as a mandate, invoked a skill, tripped
    three read-first gates, created a coordination claim and a worktree, pushed a
    commit to project-meta main, and closed the lane -- roughly ten tool calls of
    shared-state mutation -- all while nominally blocked awaiting the user, who
    had not spoken since before the refusal.

    Every one of those actions cleared the gate. So did rewriting one line. A
    control whose cheapest satisfying action is also its largest is pointed the
    wrong way, and the refusal has to say so, because the agent reading it is at
    the exact moment it is trying to stop.
    """
    result = run_hook(tmp_path, _report("Worth recording: something I have not written up."))
    payload = json.loads(result.stdout)

    assert payload["decision"] == "block"
    reason = payload["reason"].lower()
    assert "none" in reason, "the reformat-and-stop route must be named"
    assert "new work" in reason, (
        "the refusal must say that starting new work to satisfy it is not the "
        "expected response; without that an agent treats a format check as a task"
    )
