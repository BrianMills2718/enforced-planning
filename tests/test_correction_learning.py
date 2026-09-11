from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from enforced_planning.correction_learning import (
    CorrectionClassification,
    CorrectionVerdict,
    TranscriptExchange,
    audit_exchanges,
    extract_transcript_exchanges,
)
from scripts import correction_learning_audit


def _exchange(event_id: str, *, at: str = "2026-09-11T18:00:00Z") -> TranscriptExchange:
    return TranscriptExchange(
        event_id=event_id,
        occurred_at=datetime.fromisoformat(at),
        assistant_text="Taulant is the shared Second Brain implementation.",
        user_text="It is specialized Claude Code agent definitions, not that.",
    )


def _classifier(*verdicts: CorrectionVerdict):
    def classify(_exchanges, _learnings) -> CorrectionClassification:
        return CorrectionClassification(verdicts=list(verdicts))

    return classify


def _learning(
    root: Path,
    *,
    entry_id: str,
    source_ref: str,
    recorded_at: str,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{entry_id}.json").write_text(
        json.dumps(
            {
                "entry_id": entry_id,
                "schema_version": "learning/v3",
                "recorded_at": recorded_at,
                "source_ref": source_ref,
                "learning": "The corrected mistake and reusable practice.",
            }
        ),
        encoding="utf-8",
    )


def test_known_correction_is_unresolved_without_learning(tmp_path: Path) -> None:
    exchange = _exchange("turn-1")
    receipt = audit_exchanges(
        agent="codex",
        session_id="codex:session-1",
        exchanges=[exchange],
        classifier=_classifier(
            CorrectionVerdict(
                event_id="turn-1",
                classification="correction",
                rationale="The user replaces a factual characterization.",
                matching_learning_id=None,
            )
        ),
        learning_entries_dir=tmp_path / "entries",
    )

    assert receipt.status == "correction_unresolved"
    assert receipt.correction_event_hashes == [exchange.event_hash]
    assert receipt.learning_ids == []
    assert "Taulant" not in receipt.model_dump_json()


def test_scope_change_is_not_a_correction(tmp_path: Path) -> None:
    exchange = _exchange("turn-2")
    receipt = audit_exchanges(
        agent="codex",
        session_id="codex:session-1",
        exchanges=[exchange],
        classifier=_classifier(
            CorrectionVerdict(
                event_id="turn-2",
                classification="not_correction",
                rationale="The user chooses a new task without disputing prior work.",
                matching_learning_id=None,
            )
        ),
        learning_entries_dir=tmp_path / "entries",
    )

    assert receipt.status == "no_corrections"
    assert receipt.correction_event_hashes == []


def test_same_session_newer_learning_resolves_correction(tmp_path: Path) -> None:
    entries = tmp_path / "entries"
    _learning(
        entries,
        entry_id="lrn-new",
        source_ref="codex-thread:session-1",
        recorded_at="2026-09-11T18:05:00Z",
    )
    receipt = audit_exchanges(
        agent="codex",
        session_id="codex:session-1",
        exchanges=[_exchange("turn-3")],
        classifier=_classifier(
            CorrectionVerdict(
                event_id="turn-3",
                classification="correction",
                rationale="The user corrects the assistant's prior claim.",
                matching_learning_id="lrn-new",
            )
        ),
        learning_entries_dir=entries,
    )

    assert receipt.status == "correction_resolved"
    assert receipt.learning_ids == ["lrn-new"]


def test_other_session_or_older_learning_does_not_resolve(tmp_path: Path) -> None:
    entries = tmp_path / "entries"
    _learning(
        entries,
        entry_id="lrn-old",
        source_ref="codex-thread:session-1",
        recorded_at="2026-09-11T17:55:00Z",
    )
    _learning(
        entries,
        entry_id="lrn-other",
        source_ref="codex-thread:session-2",
        recorded_at="2026-09-11T18:05:00Z",
    )
    receipt = audit_exchanges(
        agent="codex",
        session_id="codex:session-1",
        exchanges=[_exchange("turn-4")],
        classifier=_classifier(
            CorrectionVerdict(
                event_id="turn-4",
                classification="correction",
                rationale="The user corrects the assistant's prior claim.",
                matching_learning_id="lrn-other",
            )
        ),
        learning_entries_dir=entries,
    )

    assert receipt.status == "correction_unresolved"
    assert receipt.learning_ids == []


def test_unrelated_later_learning_does_not_resolve_correction(tmp_path: Path) -> None:
    entries = tmp_path / "entries"
    _learning(
        entries,
        entry_id="lrn-unrelated",
        source_ref="codex-thread:session-1",
        recorded_at="2026-09-11T18:05:00Z",
    )
    receipt = audit_exchanges(
        agent="codex",
        session_id="codex:session-1",
        exchanges=[_exchange("turn-unrelated")],
        classifier=_classifier(
            CorrectionVerdict(
                event_id="turn-unrelated",
                classification="correction",
                rationale="The correction is unrelated to the available learning.",
                matching_learning_id=None,
            )
        ),
        learning_entries_dir=entries,
    )

    assert receipt.status == "correction_unresolved"
    assert receipt.learning_ids == []


def test_model_failure_is_visible_and_non_blocking(tmp_path: Path) -> None:
    def fail(_exchanges, _learnings) -> CorrectionClassification:
        raise RuntimeError("route unavailable")

    receipt = audit_exchanges(
        agent="codex",
        session_id="codex:session-1",
        exchanges=[_exchange("turn-5")],
        classifier=fail,
        learning_entries_dir=tmp_path / "entries",
    )

    assert receipt.status == "audit_error"
    assert receipt.error_code == "classifier_runtime_error"
    assert "route unavailable" not in receipt.model_dump_json()


def test_current_codex_and_claude_transcript_shapes_extract_adjacent_exchanges(
    tmp_path: Path,
) -> None:
    codex = tmp_path / "codex.jsonl"
    codex.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-09-11T18:00:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "Claim"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-09-11T18:01:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Correction"}],
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    claude = tmp_path / "claude.jsonl"
    claude.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-09-11T18:00:00Z",
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Claim"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-09-11T18:01:00Z",
                        "type": "user",
                        "message": {"role": "user", "content": "Correction"},
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    assert len(extract_transcript_exchanges(codex, agent="codex")) == 1
    assert len(extract_transcript_exchanges(claude, agent="claude-code")) == 1


def test_audit_cli_loads_the_claimed_worktree_package() -> None:
    result = subprocess.run(
        ["python3", "scripts/correction_learning_audit.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Audit one native transcript" in result.stdout


def test_classifier_route_disables_agent_context_and_ordinary_tools(monkeypatch) -> None:
    captured = {}

    def fake_call(model, messages, **kwargs):
        captured.update({"model": model, "messages": messages, **kwargs})
        return (
            CorrectionClassification(
                verdicts=[
                    CorrectionVerdict(
                        event_id="turn-1",
                        classification="not_correction",
                        rationale="No correction.",
                    )
                ]
            ),
            object(),
        )

    monkeypatch.setattr(correction_learning_audit, "call_llm_structured", fake_call)
    result = correction_learning_audit.classify_with_model(
        [_exchange("turn-1")],
        [],
        model="claude-code/sonnet",
        trace_id="test/stripped-agent-context",
    )

    assert result.verdicts[0].classification == "not_correction"
    assert captured["max_turns"] == 2
    assert captured["tools"] == []
    assert captured["setting_sources"] == []
    assert captured["cwd"] == str(correction_learning_audit.ROOT)


def test_pilot_case_set_has_preregistered_held_out_counts() -> None:
    path = Path("prompts/correction_learning/pilot_cases_v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    held_out = [case for case in payload["cases"] if case["split"] == "held_out"]

    assert len({case["case_id"] for case in payload["cases"]}) == len(payload["cases"])
    assert sum(case["expected"] == "correction" for case in held_out) == 10
    assert sum(case["expected"] == "not_correction" for case in held_out) == 20


@pytest.mark.skipif(
    not os.environ.get("CORRECTION_LEARNING_INTEGRATION"),
    reason="set CORRECTION_LEARNING_INTEGRATION=1 for the frozen live pilot",
)
def test_frozen_sonnet_classifier_pilot() -> None:
    payload = json.loads(
        Path("prompts/correction_learning/pilot_cases_v1.json").read_text(encoding="utf-8")
    )
    exchanges = [
        TranscriptExchange(
            event_id=case["case_id"],
            occurred_at=datetime.fromisoformat("2026-09-11T21:00:00Z"),
            assistant_text=case["assistant"],
            user_text=case["user"],
        )
        for case in payload["cases"]
    ]
    result = correction_learning_audit.classify_in_batches(
        exchanges,
        [],
        model="claude-code/sonnet",
        trace_id="correction-learning/pilot-v1/sonnet",
        batch_size=6,
    )
    by_id = {verdict.event_id: verdict for verdict in result.verdicts}
    assert set(by_id) == {case["case_id"] for case in payload["cases"]}

    held_out = [case for case in payload["cases"] if case["split"] == "held_out"]
    negatives = [case for case in held_out if case["expected"] == "not_correction"]
    positives = [case for case in held_out if case["expected"] == "correction"]
    boundaries = [case for case in payload["cases"] if case["split"] == "boundary"]
    false_positives = sum(
        by_id[case["case_id"]].classification == "correction" for case in negatives
    )
    true_positives = sum(
        by_id[case["case_id"]].classification == "correction" for case in positives
    )
    boundary_positives = sum(
        by_id[case["case_id"]].classification == "correction" for case in boundaries
    )
    assert false_positives == 0
    assert true_positives / len(positives) >= 0.9
    assert boundary_positives == 0
