"""Regression coverage for observation and repair during claim-control failures."""

from __future__ import annotations

from pathlib import Path

import pytest

from enforced_planning.prewrite_claim_fast import evaluate_prewrite_fast


def _evaluate(tmp_path: Path, command: str) -> dict[str, object]:
    return evaluate_prewrite_fast(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "session_id": "codex:no-claim",
            "cwd": str(tmp_path),
        },
        client="codex",
        mode="enforce",
        claims_dir=tmp_path / "missing-claims",
        projection_path=tmp_path / "missing-projection.json",
        receipt_path=tmp_path / "prewrite-events.jsonl",
    )


@pytest.mark.parametrize(
    "command",
    [
        "sed -n '1,20p' README.md\nrg -n needle README.md",
        "git status --short\ngit log -5 --oneline --decorate\ngit diff --stat",
        "stat -c '%y %s %n' snapshot.json\nsed -n '1,220p' snapshot.json",
    ],
)
def test_multiline_read_only_inspection_survives_missing_claim_projection(
    tmp_path: Path,
    command: str,
) -> None:
    decision = _evaluate(tmp_path, command)

    assert decision["decision"] == "allow", decision
    assert decision["reason_code"] == "bash_read_only"


@pytest.mark.parametrize(
    "command",
    [
        "git status --short\ntouch marker",
        "sed -n '1,20p' README.md\npython3 repair.py",
        "rg -n needle .\ngit add README.md",
    ],
)
def test_multiline_inspection_with_one_unproved_mutation_still_fails_closed(
    tmp_path: Path,
    command: str,
) -> None:
    decision = _evaluate(tmp_path, command)

    assert decision["decision"] == "deny", decision
    assert decision["reason_code"] == "repository_identity_unavailable"
