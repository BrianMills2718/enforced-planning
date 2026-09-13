"""Focused tests for the portable cross-client completed-work learning gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "learning_capture_hook.py"


def codex_learning_config(config_path: Path, script_path: Path = SCRIPT) -> str:
    """Build an independently fingerprinted trusted Codex fixture."""
    command = f"python3 {script_path} --agent codex"

    def trusted_hash(event_name: str) -> str:
        identity = {
            "event_name": event_name,
            "hooks": [
                {
                    "async": False,
                    "command": command,
                    "timeout": 600,
                    "type": "command",
                }
            ],
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    source = str(config_path.resolve())
    return (
        "[[hooks.UserPromptSubmit]]\n"
        "[[hooks.UserPromptSubmit.hooks]]\n"
        f'command = "{command}"\n'
        "[[hooks.Stop]]\n"
        "[[hooks.Stop.hooks]]\n"
        f'command = "{command}"\n'
        f'[hooks.state."{source}:user_prompt_submit:0:0"]\n'
        f'trusted_hash = "{trusted_hash("user_prompt_submit")}"\n'
        f'[hooks.state."{source}:stop:0:0"]\n'
        f'trusted_hash = "{trusted_hash("stop")}"\n'
    )


def run_hook(
    tmp_path: Path,
    report: str,
    *,
    agent: str = "codex",
    correction_mode: str = "off",
) -> subprocess.CompletedProcess[str]:
    """Run one native-shaped Stop event through the hook."""
    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--agent",
            agent,
            "--state-dir",
            str(tmp_path),
            "--hook-receipt-dir",
            str(tmp_path / "hook-receipts"),
            "--correction-mode",
            correction_mode,
            "--correction-receipt-dir",
            str(tmp_path / "correction-receipts"),
        ],
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


def run_prompt_hook(
    tmp_path: Path,
    prompt: str,
    *,
    agent: str = "codex",
    turn_id: str = "turn-123",
) -> subprocess.CompletedProcess[str]:
    """Run one native-shaped prompt event through the attention path."""

    return subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--agent",
            agent,
            "--state-dir",
            str(tmp_path),
            "--hook-receipt-dir",
            str(tmp_path / "hook-receipts"),
        ],
        input=json.dumps(
            {
                "session_id": "session-123",
                "turn_id": turn_id,
                "hook_event_name": "UserPromptSubmit",
                "prompt": prompt,
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )


def write_correction_receipt(tmp_path: Path, *, status: str) -> None:
    digest = hashlib.sha256(b"codex\0session-123").hexdigest()[:32]
    root = tmp_path / "correction-receipts"
    root.mkdir()
    (root / f"{digest}.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "record_type": "correction_learning_audit",
                "agent": "codex",
                "session_id": "session-123",
                "analyzed_at": "2026-09-11T20:00:00Z",
                "status": status,
                "correction_event_hashes": ["corr_example"],
                "rationale_hashes": ["reason_example"],
                "learning_ids": [],
                "error_code": None,
            }
        ),
        encoding="utf-8",
    )


def test_block_mode_requires_resolved_correction_receipt(tmp_path: Path) -> None:
    write_correction_receipt(tmp_path, status="correction_unresolved")
    result = run_hook(
        tmp_path,
        "- **Done** — Implemented.\n- **Learnings** — None because no reusable finding emerged.",
        correction_mode="block",
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "same-session immutable learning" in payload["reason"]


def test_observe_mode_never_blocks_unresolved_correction(tmp_path: Path) -> None:
    write_correction_receipt(tmp_path, status="correction_unresolved")
    result = run_hook(
        tmp_path,
        "- **Done** — Implemented.\n- **Learnings** — None because no reusable finding emerged.",
        correction_mode="observe",
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_invalid_correction_receipt_never_blocks_completion(tmp_path: Path) -> None:
    write_correction_receipt(tmp_path, status="correction_unresolved")
    receipt = next((tmp_path / "correction-receipts").glob("*.json"))
    receipt.write_text("{}", encoding="utf-8")
    result = run_hook(
        tmp_path,
        "- **Done** — Implemented.\n- **Learnings** — None because no reusable finding emerged.",
        correction_mode="block",
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_incoherent_correction_receipt_never_blocks_completion(tmp_path: Path) -> None:
    write_correction_receipt(tmp_path, status="correction_unresolved")
    receipt = next((tmp_path / "correction-receipts").glob("*.json"))
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["rationale_hashes"] = []
    receipt.write_text(json.dumps(payload), encoding="utf-8")
    result = run_hook(
        tmp_path,
        "- **Done** — Implemented.\n- **Learnings** — None because no reusable finding emerged.",
        correction_mode="block",
    )

    assert result.returncode == 0
    assert result.stdout == ""


def receipts(tmp_path: Path) -> list[dict[str, object]]:
    """Load every emitted disposition receipt."""
    return [json.loads(path.read_text(encoding="utf-8")) for path in tmp_path.glob("*/*.json")]


def test_prompt_hook_injects_immediate_learning_checkpoint_without_storing_prose(
    tmp_path: Path,
) -> None:
    prompt = "No, Taulant is a specialized Claude Code agent definition."
    result = run_prompt_hook(tmp_path, prompt)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "record the reusable lesson" in context
    attention = list(tmp_path.glob("*/attention/*.json"))
    assert len(attention) == 1
    assert prompt not in attention[0].read_text(encoding="utf-8")


def test_prompt_hook_is_idempotent_for_one_native_turn(tmp_path: Path) -> None:
    first = run_prompt_hook(tmp_path, "First delivery")
    second = run_prompt_hook(tmp_path, "Duplicate delivery")

    assert first.returncode == second.returncode == 0
    assert len(list(tmp_path.glob("*/attention/*.json"))) == 1


def test_prompt_hook_state_failure_warns_but_does_not_block_user_turn(
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "not-a-directory"
    state_file.write_text("occupied", encoding="utf-8")
    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--agent",
            "codex",
            "--state-dir",
            str(state_file),
            "--hook-receipt-dir",
            str(tmp_path / "hook-receipts"),
        ],
        input=json.dumps(
            {
                "session_id": "session-123",
                "turn_id": "turn-123",
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Correction",
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "receipt was unavailable" in context
    assert "decision" not in payload


def test_stop_receipt_counts_prompt_time_attention_events(tmp_path: Path) -> None:
    run_prompt_hook(tmp_path, "Please continue", turn_id="turn-one")
    run_prompt_hook(tmp_path, "That assumption was wrong", turn_id="turn-two")

    result = run_hook(
        tmp_path,
        "- **Done** — Implemented.\n"
        "- **Learnings** — None — this fixture exercises receipt accounting only.",
    )

    assert result.returncode == 0
    disposition = next(
        receipt
        for receipt in receipts(tmp_path)
        if receipt.get("decision") == "none"
    )
    assert disposition["attention_events"] == 2


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
    assert "Receipt:" in payload["reason"]
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


def test_simple_recorded_field_accepts_an_entry_id(tmp_path: Path) -> None:
    """The compact semantic form needs no Markdown decoration or register path."""
    result = run_hook(
        tmp_path,
        "Done: Implemented the hook repair.\n"
        "Learnings: recorded lrn-20260913T120000000000Z-a1b2c3d4e5",
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert receipts(tmp_path)[0]["decision"] == "recorded"


def test_simple_none_field_accepts_a_concrete_reason(tmp_path: Path) -> None:
    """The compact semantic form supports the no-learning disposition too."""
    result = run_hook(
        tmp_path,
        "Done: Re-ran an existing deterministic check.\n"
        "Learnings: none — the run only reconfirmed an already tested behavior.",
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert receipts(tmp_path)[0]["decision"] == "none"


def test_markdown_and_simple_fields_can_be_mixed(tmp_path: Path) -> None:
    """Adoption is backward compatible while agents move one field at a time."""
    result = run_hook(
        tmp_path,
        "- **Done** — Implemented the repair.\n"
        "Learnings: recorded lrn-20260913T120000000000Z-a1b2c3d4e5\n"
        "- **Policy** — Followed.",
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert receipts(tmp_path)[0]["decision"] == "recorded"


def test_already_recorded_reuses_an_exact_session_receipt(tmp_path: Path) -> None:
    first = run_hook(
        tmp_path,
        "- **Done** — Implemented.\n"
        "- **Learnings** — Recorded — project-meta/learnings.md at commit abc1234.",
    )
    assert first.stdout == ""

    repeated = run_hook(
        tmp_path,
        "- **Done** — Explanation complete.\n- **Learnings** — Already recorded.",
    )

    assert repeated.returncode == 0
    assert repeated.stdout == ""
    assert "recorded_prior_receipt" in {receipt["decision"] for receipt in receipts(tmp_path)}


def test_already_recorded_without_prior_receipt_still_blocks(tmp_path: Path) -> None:
    result = run_hook(
        tmp_path,
        "- **Done** — Explanation complete.\n- **Learnings** — Already recorded.",
    )

    assert json.loads(result.stdout)["decision"] == "block"


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


def test_blocking_error_has_stable_code_copyable_next_step_and_verifier(tmp_path: Path) -> None:
    result = run_hook(
        tmp_path,
        "Done: Implemented the repair.\nLearnings: worth capturing later.",
    )

    reason = json.loads(result.stdout)["reason"]
    assert "[learning_capture.block_invalid]" in reason
    assert "Why:" in reason
    assert "Next:" in reason
    assert "Learnings: recorded <lrn-entry-id>" in reason
    assert "Learnings: none — <concrete reason of at least 20 characters>" in reason
    assert "Verify:" in reason
    assert "Receipt:" in reason


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
    codex.write_text(codex_learning_config(codex), encoding="utf-8")
    claude.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {"command": f"python3 {SCRIPT} --agent claude-code"},
                            ]
                        }
                    ],
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

    codex.write_text(
        codex_learning_config(codex).replace("sha256:", "sha256:stale", 1),
        encoding="utf-8",
    )
    modified = subprocess.run(
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
    modified_payload = json.loads(modified.stdout)
    assert modified.returncode == 1
    assert modified_payload["codex_prompt_operational"] is False

    codex.write_text(
        codex_learning_config(codex).replace(
            f'[hooks.state."{codex.resolve()}:stop:0:0"]\n',
            f'[hooks.state."{codex.resolve()}:stop:0:0"]\nenabled = false\n',
        ),
        encoding="utf-8",
    )
    disabled = subprocess.run(
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
    disabled_payload = json.loads(disabled.stdout)
    assert disabled.returncode == 1
    assert disabled_payload["codex_stop_hook"] is True
    assert disabled_payload["codex_stop_operational"] is False

    codex.write_text(codex_learning_config(codex), encoding="utf-8")

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
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {"hooks": [{"command": f"python3 {SCRIPT} --agent claude-code"}]}
                    ],
                    "Stop": [
                        {"hooks": [{"command": f"python3 {SCRIPT} --agent claude-code"}]}
                    ],
                }
            },
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


def test_install_check_accepts_symlink_equivalent_hook_path(tmp_path: Path) -> None:
    """A configured checkout alias is live when it resolves to this hook."""
    codex = tmp_path / "config.toml"
    claude = tmp_path / "settings.json"
    openclaw = tmp_path / "run_task.py"
    checkout_alias = tmp_path / "active-enforced-planning"
    checkout_alias.symlink_to(SCRIPT.parent.parent, target_is_directory=True)
    aliased_script = checkout_alias / "scripts" / SCRIPT.name
    codex.write_text(codex_learning_config(codex, aliased_script), encoding="utf-8")
    claude.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {"command": f"python3 {aliased_script} --agent claude-code"},
                            ]
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {"command": f"python3 {aliased_script} --agent claude-code"},
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

    result = subprocess.run(
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

    assert result.returncode == 0
    assert json.loads(result.stdout)["live"] is True


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
    assert "complete response" in reason, (
        "the refusal must say that fixing the line is a complete response; "
        "without that an agent treats a format check as a task"
    )
    assert "do not start work to clear this gate" in reason, (
        "and it must name the one case where stopping is right, so that "
        "'satisfy the gate' never means 'go mutate shared state'"
    )


def test_the_refusal_does_not_read_as_never_record(tmp_path: Path) -> None:
    """The escape route must not swallow the register it protects.

    The first version of this guidance said: if recording would need "a
    worktree, a claim, a push, a skill invocation", write `None -- deferred` and
    stop. But a worktree, a claim and a push are the *only* way to record
    anything here, so read literally it said never record -- and within two
    turns the agent that wrote it had declined twice on those grounds, including
    for a finding the user then asked why it had not written down.

    The narrow case it was for is real: an agent at Stop, nominally waiting on
    the user, mutating shared state to clear a check on formatting. The
    condition is being blocked on someone else, not the ordinary cost of
    recording.
    """
    result = run_hook(tmp_path, _report("Worth recording: something I have not written up."))
    reason = json.loads(result.stdout)["reason"].lower()

    assert "waiting on the user" in reason or "blocked" in reason, (
        "the deferral must be conditioned on being blocked, not on recording's normal cost"
    )
    assert "worktree, a claim, a push" not in reason, (
        "naming the ordinary recording procedure as a reason to defer tells the "
        "agent to never record; that is the register's whole purpose"
    )


def test_backtick_wrapped_recorded_is_accepted(tmp_path: Path) -> None:
    """Regression for commit 9efdfee: a `Recorded` disposition wrapped in

    backticks -- correct content, ordinary formatting -- must not fail a
    strict startswith-style match the way it did before that fix, costing
    two round-trips in the same session.
    """
    result = run_hook(
        tmp_path,
        _report("`Recorded` — project-meta/learnings.md at commit abc1234."),
        agent="claude-code",
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert receipts(tmp_path)[0]["decision"] == "recorded"


def test_structured_marker_trusts_prior_record_without_prose_guessing(tmp_path: Path) -> None:
    """A well-formed learnings-status trailer settles the decision directly.

    The prose reference ("this morning's standup notes") matches none of the
    REFERENCE_PATTERNS shapes, so the old prose-only heuristic would block
    this exact reason as an unreferenced decline (see
    test_decline_claiming_prior_capture_must_name_it, and
    test_no_marker_prose_still_governs_unchanged below, which reproduces that
    exact block with the marker removed entirely). The structured marker
    states the disposition and its reference unambiguously and must be
    trusted directly -- no regex-guessing needed to reach 'none'.
    """
    result = run_hook(
        tmp_path,
        _report(
            "None -- already recorded, see this morning's standup notes.\n"
            "<!-- learnings-status: prior-record ref=lrn-20260903T144848367412Z-731e6c1389 -->"
        ),
    )

    assert result.returncode == 0
    assert result.stdout == ""
    receipt = receipts(tmp_path)[0]
    assert receipt["decision"] == "none"
    assert "lrn-20260903T144848367412Z-731e6c1389" in receipt["detail"]


def test_malformed_structured_marker_blocks_loudly_instead_of_guessing(tmp_path: Path) -> None:
    """A marker missing its required 'ref' field must block with an explicit

    syntax error, never silently fall back to the prose heuristic as if the
    marker had never been attempted. Silently guessing past a broken
    structured attempt would reproduce, one level down, the exact
    silent-degradation failure (a value the source clearly stated getting
    quietly misread) this marker exists to remove.
    """
    result = run_hook(
        tmp_path,
        _report(
            "None -- already recorded, see this morning's standup notes.\n"
            "<!-- learnings-status: prior-record -->"
        ),
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "invalid" in payload["reason"].lower()
    assert "learnings-status" in payload["reason"]
    assert receipts(tmp_path)[0]["decision"] == "block_malformed_learnings_marker"


def test_unknown_marker_status_blocks_loudly_instead_of_guessing(tmp_path: Path) -> None:
    """An unrecognized status value is also malformed and must block loudly,

    not crash and not silently degrade into the prose heuristic.
    """
    result = run_hook(
        tmp_path,
        _report(
            "None -- already recorded, see this morning's standup notes.\n"
            "<!-- learnings-status: bogus-status ref=whatever -->"
        ),
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "invalid" in payload["reason"].lower()
    assert receipts(tmp_path)[0]["decision"] == "block_malformed_learnings_marker"


def test_no_marker_prose_still_governs_unchanged(tmp_path: Path) -> None:
    """No marker at all: behavior is byte-for-byte the old prose heuristic.

    Same reason as the two marker tests above, with the trailer removed --
    proves the fallback path (no marker present) still blocks exactly as it
    did before this change.
    """
    result = run_hook(
        tmp_path, _report("None -- already recorded, see this morning's standup notes.")
    )

    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "name it" in payload["reason"]
    assert receipts(tmp_path)[0]["decision"] == "block_unreferenced_decline"


def test_stop_hook_active_ends_the_turn(monkeypatch, tmp_path: Path) -> None:
    """A re-fired Stop must not refuse the same report again.

    The agent has already been told what its report is missing; refusing it a
    second time cannot change the report and only deadlocks the session.
    """
    import io
    import json
    import sys

    from scripts import learning_capture_hook

    payload = {
        "hook_event_name": "Stop",
        "session_id": "s",
        "stop_hook_active": True,
        "last_assistant_message": "a report with no Learnings line at all",
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))

    def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("repeat Stop reached fallible receipt state")

    monkeypatch.setattr(learning_capture_hook, "start_hook_invocation", unexpected)
    assert learning_capture_hook.main(
        ["--agent", "claude-code", "--hook-receipt-dir", str(tmp_path)]
    ) == 0
