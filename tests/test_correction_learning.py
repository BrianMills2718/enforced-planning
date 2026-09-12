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
    NativeCorrectionCorpusV1,
    TranscriptExchange,
    audit_exchanges,
    extract_transcript_exchanges,
    load_native_corpus_exchanges,
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
                        "timestamp": "2026-09-11T18:00:30Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Injected authority"}],
                            "internal_chat_message_metadata_passthrough": {
                                "content_item_kinds": ["agents_md.instructions"]
                            },
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
                            "internal_chat_message_metadata_passthrough": {
                                "content_item_kinds": ["user.text"]
                            },
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
                        "timestamp": "2026-09-11T18:00:30Z",
                        "type": "user",
                        "isMeta": True,
                        "message": {
                            "role": "user",
                            "content": "[structured-output-enforce] Tool protocol",
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

    codex_exchanges = extract_transcript_exchanges(codex, agent="codex")
    claude_exchanges = extract_transcript_exchanges(claude, agent="claude-code")
    assert len(codex_exchanges) == len(claude_exchanges) == 1
    assert codex_exchanges[0].user_text == "Correction"
    assert claude_exchanges[0].user_text == "Correction"


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


def test_native_replay_rejects_nonexistent_source_revision() -> None:
    with pytest.raises(ValueError, match="resolvable Git commit"):
        correction_learning_audit.verified_frozen_revision(
            "65f20a8e2c2314cbb691aa7c25da1a67a85c8374",
            Path("prompts/correction_learning/native_corpus_v2.json"),
        )


def test_pilot_case_set_has_preregistered_held_out_counts() -> None:
    path = Path("prompts/correction_learning/pilot_cases_v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    held_out = [case for case in payload["cases"] if case["split"] == "held_out"]

    assert len({case["case_id"] for case in payload["cases"]}) == len(payload["cases"])
    assert sum(case["expected"] == "correction" for case in held_out) == 10
    assert sum(case["expected"] == "not_correction" for case in held_out) == 20


def test_native_corpus_is_post_pilot_privacy_reduced_and_multiclient() -> None:
    path = Path("prompts/correction_learning/native_corpus_v1.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    corpus = NativeCorrectionCorpusV1.model_validate(raw)

    assert len(corpus.cases) == 14
    assert len({(case.agent, case.session_id) for case in corpus.cases}) == 8
    assert sum(case.role == "scored" for case in corpus.cases) == 9
    assert sum(case.expected == "correction" for case in corpus.cases) == 2
    assert all("assistant" not in case and "user" not in case for case in raw["cases"])


def test_native_corpus_replay_requires_exact_event_provenance(tmp_path: Path) -> None:
    cases = []
    for index, agent in enumerate(["codex", "codex", "codex", "codex", "claude-code"]):
        source = Path(f"native/session-{index}.jsonl")
        target = tmp_path / source
        target.parent.mkdir(parents=True, exist_ok=True)
        timestamp = f"2026-09-12T02:00:0{index}Z"
        if agent == "codex":
            rows = [
                {
                    "timestamp": timestamp,
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Claim"}],
                    },
                },
                {
                    "timestamp": timestamp,
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Question"}],
                    },
                },
            ]
        else:
            rows = [
                {
                    "timestamp": timestamp,
                    "type": "assistant",
                    "message": {"role": "assistant", "content": "Claim"},
                },
                {
                    "timestamp": timestamp,
                    "type": "user",
                    "message": {"role": "user", "content": "Question"},
                },
            ]
        target.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        exchange = extract_transcript_exchanges(target, agent=agent)[0]
        cases.append(
            {
                "case_id": f"case-{index}",
                "role": "scored" if agent == "codex" else "native_format_control",
                "agent": agent,
                "session_id": f"session-{index}",
                "source_path": str(source),
                "event_id": exchange.event_id,
                "event_hash": exchange.event_hash,
                "occurred_at": exchange.occurred_at.isoformat(),
                "expected": "not_correction",
            }
        )
    payload = {
        "schema_version": "1.1",
        "corpus_id": "test-native-corpus",
        "frozen_at": "2026-09-12T03:00:00Z",
        "pilot_cutoff": "2026-09-12T01:00:00Z",
        "selection": {
            "scored_population": "Synthetic loader test cases.",
            "native_format_controls": "One Claude transcript-shape control.",
            "label_basis": "Fixed test labels.",
            "privacy": "No source prose in the manifest.",
            "scored_sources": [
                {
                    "agent": case["agent"],
                    "session_id": case["session_id"],
                    "source_path": case["source_path"],
                    "window_start": case["occurred_at"],
                    "window_end": "2026-09-12T02:59:59Z",
                }
                for case in cases
                if case["role"] == "scored"
            ],
        },
        "cases": cases,
    }
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_text(json.dumps(payload), encoding="utf-8")

    corpus, exchanges = load_native_corpus_exchanges(corpus_path, home=tmp_path)
    assert len(corpus.cases) == len(exchanges) == 5

    original_hash = payload["cases"][0]["event_hash"]
    payload["cases"][0]["event_hash"] = "corr_" + "0" * 32
    corpus_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="event provenance changed"):
        load_native_corpus_exchanges(corpus_path, home=tmp_path)

    payload["cases"][0]["event_hash"] = original_hash
    first_source = tmp_path / payload["cases"][0]["source_path"]
    existing = first_source.read_text(encoding="utf-8")
    extra = [
        {
            "timestamp": "2026-09-12T02:30:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Another claim"}],
            },
        },
        {
            "timestamp": "2026-09-12T02:31:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Another question"}],
            },
        },
    ]
    first_source.write_text(
        existing + "\n" + "\n".join(json.dumps(row) for row in extra),
        encoding="utf-8",
    )
    corpus_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="scored population is incomplete"):
        load_native_corpus_exchanges(corpus_path, home=tmp_path)


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
