"""Controls for the rebuilt assertion-evidence gate.

The predecessor was disabled for deciding meaning with regexes over prose. Two
things therefore have to be true of this one and are asserted here: no regex
touches the report, and the model is asked only when the answer can change the
outcome.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "scripts" / "assertion_evidence_gate.py"

# The live-model cases cost a fraction of a cent each and need network. They are
# the only evidence that the gate works, so they run by default here and are
# skipped where a key or the network is absent.
LIVE = os.environ.get("AEG_LIVE_JUDGE", "1") == "1"


def _load():
    spec = importlib.util.spec_from_file_location("assertion_evidence_gate", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _transcript(tmp_path: Path, *events: dict) -> Path:
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


def _user(text: str) -> dict:
    return {"type": "user", "message": {"content": text}}


def _assistant_text(text: str) -> dict:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _bash(command: str, identifier: str = "t1") -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "id": identifier, "name": "Bash", "input": {"command": command}}
            ]
        },
    }


def _run(transcript: Path, **payload) -> subprocess.CompletedProcess:
    body = {"session_id": "test", "transcript_path": str(transcript), **payload}
    return subprocess.run(
        [sys.executable, str(GATE_PATH)],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        check=False,
    )


# --- structural half ---------------------------------------------------------


def test_the_command_decides_the_class_not_the_tool_name() -> None:
    """`git diff` shows text; `pytest` makes something happen.

    Classifying every Bash call as execution is the defect that made the
    predecessor silent on its own motivating incident, where five `git diff`
    reads preceded "I have verified it is correct" and 27 tests then failed.
    """

    assert gate.classify_bash_command("git diff HEAD~1") == "inspected"
    assert gate.classify_bash_command("cat README.md | grep foo") == "inspected"
    assert gate.classify_bash_command("python -m pytest -q") == "executed"
    assert gate.classify_bash_command("cd repo && git diff") == "inspected"
    assert gate.classify_bash_command("cd repo && make test") == "executed"


def test_no_regex_is_applied_to_the_report(tmp_path: Path) -> None:
    """The whole point of the rebuild, asserted mechanically.

    Runs the ecosystem's own `no-prose-string-matching` checker over this gate.
    If a future edit reintroduces a prose heuristic, this goes red here rather
    than surviving until someone disables the gate again.
    """

    checker = REPO / "scripts" / "check_no_prose_string_matching.py"
    if not checker.is_file():
        pytest.skip("the policy checker is not installed in this checkout")
    completed = subprocess.run(
        [sys.executable, str(checker), "--allow-vacuous", "--roots", str(GATE_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_a_refired_stop_is_never_refused(tmp_path: Path) -> None:
    """A Stop gate that refuses its own re-fire can refuse forever."""

    transcript = _transcript(tmp_path, _user("go"), _assistant_text("All tests pass."))
    completed = _run(transcript, stop_hook_active=True)
    assert completed.returncode == 0
    assert completed.stdout.strip() == ""


# --- the cheap path ----------------------------------------------------------


def test_a_turn_that_executed_something_is_allowed_without_a_model_call(tmp_path: Path) -> None:
    """The common case must not cost a model call.

    A gate that bills every turn is a gate that gets switched off. Asserted by
    making any model call fail loudly: if the gate reached the judge, the run
    would not be silent.
    """

    transcript = _transcript(
        tmp_path,
        _user("run the tests"),
        _bash("uv run pytest -q"),
        _assistant_text("All tests pass: 438 passed."),
    )
    environment = dict(os.environ)
    environment["LLM_CLIENT_DB_PATH"] = "/nonexistent/should-never-be-touched.db"
    completed = subprocess.run(
        [sys.executable, str(GATE_PATH)],
        input=json.dumps({"session_id": "t", "transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == ""


def test_an_unavailable_judge_is_not_checked_rather_than_a_pass(tmp_path: Path) -> None:
    """Fail open, and say so. Never a silent allow.

    The predecessor's disabling is the argument for failing open; this assertion
    is the argument against doing it quietly.
    """

    transcript = _transcript(
        tmp_path, _user("check it"), _bash("git diff"), _assistant_text("I verified it is correct.")
    )
    environment = dict(os.environ)
    # No import path to llm_client for the subprocess.
    environment["PYTHONPATH"] = str(tmp_path)
    environment["AEG_FORCE_NO_JUDGE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", (
            "import sys, json, importlib.util\n"
            "sys.modules['llm_client'] = None\n"
            f"spec = importlib.util.spec_from_file_location('g', {str(GATE_PATH)!r})\n"
            "m = importlib.util.module_from_spec(spec); sys.modules['g'] = m\n"
            "spec.loader.exec_module(m)\n"
            "sys.exit(m.main([]))\n"
        )],
        input=json.dumps({"session_id": "t", "transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert "NOT_CHECKED" in completed.stdout


# --- the judged path, against a real model -----------------------------------


@pytest.mark.skipif(not LIVE, reason="AEG_LIVE_JUDGE=0")
def test_it_blocks_the_incident_it_was_built_for(tmp_path: Path) -> None:
    """Five reads, then "I have verified it is correct". 27 tests then failed.

    This is the motivating incident from 2026-08-31, and the case the predecessor
    scored clean. A real judge call, because a gate that has only been seen to
    pass fixtures is not known to work.
    """

    transcript = _transcript(
        tmp_path,
        _user("is the fix right?"),
        _bash("git diff HEAD~1", "a"),
        _bash("cat src/module.py", "b"),
        _assistant_text("I have reviewed the change and verified it is correct."),
    )
    completed = _run(transcript)
    assert completed.returncode == 0, completed.stderr
    if "NOT_CHECKED" in completed.stdout:
        pytest.skip(f"judge unavailable: {completed.stdout}")
    payload = json.loads(completed.stdout)
    assert payload["decision"] == "block", completed.stdout
    assert "executed nothing" in payload["reason"]


@pytest.mark.skipif(not LIVE, reason="AEG_LIVE_JUDGE=0")
def test_an_honest_unverified_report_is_not_blocked(tmp_path: Path) -> None:
    """The other half, and the one that decides whether anyone keeps this on.

    A gate that blocks a report saying "I have not run this" is a gate that gets
    switched off within the week, which is exactly how its predecessor died.
    """

    transcript = _transcript(
        tmp_path,
        _user("what does this do?"),
        _bash("cat src/module.py", "a"),
        _assistant_text(
            "The function normalises the path before comparing. I have not run the "
            "tests, so I cannot say whether it behaves correctly at runtime."
        ),
    )
    completed = _run(transcript)
    assert completed.returncode == 0, completed.stderr
    if "NOT_CHECKED" in completed.stdout:
        pytest.skip(f"judge unavailable: {completed.stdout}")
    assert completed.stdout.strip() == "", completed.stdout
