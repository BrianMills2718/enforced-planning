#!/usr/bin/env python3
"""Audit one native transcript for user corrections and durable learnings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm_client import call_llm_structured, render_prompt

from enforced_planning.correction_learning import (
    CorrectionClassification,
    LearningCandidate,
    TranscriptExchange,
    audit_exchanges,
    extract_transcript_exchanges,
    load_native_corpus_exchanges,
)

PROMPT = ROOT / "prompts/correction_learning/classify.yaml"


class BatchVerdictMismatch(ValueError):
    """A structured batch omitted or invented one or more frozen event IDs."""

    def __init__(self, batch_index: int, expected: set[str], actual: set[str]) -> None:
        super().__init__(f"native classifier batch {batch_index} verdict IDs do not match")
        self.batch_index = batch_index
        self.missing_event_ids = sorted(expected - actual)
        self.unexpected_event_ids = sorted(actual - expected)


class BatchEvaluationFailure(RuntimeError):
    """A frozen batch failed before a structurally valid verdict set existed."""

    def __init__(self, batch_index: int, error_type: str) -> None:
        super().__init__(f"native classifier batch {batch_index} failed: {error_type}")
        self.batch_index = batch_index
        self.error_type = error_type


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("codex", "claude-code"))
    parser.add_argument("--session-id")
    parser.add_argument("--transcript", type=Path)
    parser.add_argument("--learning-entries-dir", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--source-revision")
    parser.add_argument("--model", default="claude-code/sonnet")
    parser.add_argument("--max-exchanges", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=6)
    args = parser.parse_args()
    native_args = (
        args.agent,
        args.session_id,
        args.transcript,
        args.learning_entries_dir,
        args.receipt,
    )
    if args.corpus:
        if not args.result or not args.source_revision:
            parser.error("--corpus requires --result and --source-revision")
        if any(native_args):
            parser.error("--corpus cannot be combined with single-session audit arguments")
    elif not all(native_args):
        parser.error(
            "single-session audit requires --agent, --session-id, --transcript, "
            "--learning-entries-dir, and --receipt"
        )
    return args


def classify_with_model(
    exchanges: list[TranscriptExchange],
    learning_candidates: list[LearningCandidate],
    *,
    model: str,
    trace_id: str,
) -> CorrectionClassification:
    serialized = [
        {
            "event_id": exchange.event_id,
            "assistant": exchange.assistant_text,
            "user": exchange.user_text,
        }
        for exchange in exchanges
    ]
    learnings = [
        {
            "entry_id": item.entry_id,
            "recorded_at": item.recorded_at.isoformat(),
            "learning": item.learning,
        }
        for item in learning_candidates
    ]
    messages = render_prompt(
        PROMPT,
        exchanges_json=json.dumps(serialized, ensure_ascii=False),
        learnings_json=json.dumps(learnings, ensure_ascii=False),
    )
    result, _meta = call_llm_structured(
        model,
        messages,
        response_model=CorrectionClassification,
        reasoning_effort="low",
        model_policy="enforce_allowlist",
        model_justification=(
            "Use a subscription-backed light agent route for bounded semantic "
            "classification without API credentials or prose regex."
        ),
        task="correction_classification",
        trace_id=trace_id,
        max_budget=0.05,
        max_turns=2,
        tools=[],
        setting_sources=[],
        cwd=str(ROOT),
    )
    return result


def classify_in_batches(
    exchanges: list[TranscriptExchange],
    learning_candidates: list[LearningCandidate],
    *,
    model: str,
    trace_id: str,
    batch_size: int,
) -> CorrectionClassification:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    verdicts = []
    for index in range(0, len(exchanges), batch_size):
        batch = exchanges[index : index + batch_size]
        batch_index = index // batch_size + 1
        try:
            classified = classify_with_model(
                batch,
                learning_candidates,
                model=model,
                trace_id=f"{trace_id}/batch-{batch_index}",
            )
        except Exception as exc:
            raise BatchEvaluationFailure(batch_index, type(exc).__name__) from exc
        expected_ids = {exchange.event_id for exchange in batch}
        actual_ids = {verdict.event_id for verdict in classified.verdicts}
        if actual_ids != expected_ids:
            raise BatchVerdictMismatch(batch_index, expected_ids, actual_ids)
        verdicts.extend(classified.verdicts)
    return CorrectionClassification(verdicts=verdicts)


def atomic_write(path: Path, payload: str) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def verified_frozen_revision(revision: str, *paths: Path) -> str:
    """Resolve a real commit and prove each evaluation input matches its blob."""

    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if resolved.returncode != 0:
        raise ValueError("source revision is not a resolvable Git commit")
    full_revision = resolved.stdout.strip()
    for path in paths:
        relative = path.resolve().relative_to(ROOT)
        frozen = subprocess.run(
            ["git", "show", f"{full_revision}:{relative}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        if frozen.returncode != 0 or frozen.stdout != path.read_bytes():
            raise ValueError(f"evaluation input is not frozen at source revision: {relative}")
    return full_revision


def evaluate_native_corpus(args: argparse.Namespace) -> int:
    """Replay frozen native cases and retain only privacy-reduced verdicts."""

    source_revision = verified_frozen_revision(args.source_revision, args.corpus, PROMPT)
    corpus, exchanges = load_native_corpus_exchanges(args.corpus)
    corpus_bytes = args.corpus.read_bytes()
    trace_id = f"correction-learning/{corpus.corpus_id}/{source_revision[:12]}"
    try:
        classified = classify_in_batches(
            exchanges,
            [],
            model=args.model,
            trace_id=trace_id,
            batch_size=args.batch_size,
        )
    except (BatchVerdictMismatch, BatchEvaluationFailure) as exc:
        if isinstance(exc, BatchVerdictMismatch):
            failure = {
                "code": "batch_verdict_id_mismatch",
                "batch_index": exc.batch_index,
                "missing_event_ids": exc.missing_event_ids,
                "unexpected_event_ids": exc.unexpected_event_ids,
            }
        else:
            failure = {
                "code": "batch_evaluation_error",
                "batch_index": exc.batch_index,
                "error_type": exc.error_type,
            }
        payload = {
            "schema_version": "1.1",
            "record_type": "correction_native_corpus_result",
            "corpus_id": corpus.corpus_id,
            "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_revision": source_revision,
            "corpus": str(args.corpus),
            "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
            "prompt": str(PROMPT.relative_to(ROOT)),
            "prompt_sha256": hashlib.sha256(PROMPT.read_bytes()).hexdigest(),
            "model": args.model,
            "batch_size": args.batch_size,
            "trace_prefix": trace_id,
            "run_status": "invalid",
            "decision_status": "retain_manual_off",
            "failure": failure,
            "non_claims": [
                "No classifier accuracy metric is valid for this partial run.",
                "No assistant text, user text, or model rationale is retained.",
            ],
        }
        serialized = json.dumps(payload, indent=2, sort_keys=True)
        atomic_write(args.result, serialized)
        print(serialized)
        return 2
    verdicts = {verdict.event_id: verdict for verdict in classified.verdicts}
    expected_ids = {case.event_id for case in corpus.cases}
    if set(verdicts) != expected_ids:
        raise ValueError("native classifier verdict IDs must exactly match frozen events")

    predictions = []
    for case in corpus.cases:
        verdict = verdicts[case.event_id]
        acceptable = (
            verdict.classification == case.expected
            if case.expected != "ambiguous"
            else verdict.classification != "correction"
        )
        predictions.append(
            {
                "case_id": case.case_id,
                "role": case.role,
                "agent": case.agent,
                "session_id": case.session_id,
                "event_id": case.event_id,
                "event_hash": case.event_hash,
                "expected": case.expected,
                "actual": verdict.classification,
                "acceptable": acceptable,
                "rationale_hash": hashlib.sha256(verdict.rationale.encode()).hexdigest()[:24],
            }
        )

    scored = [row for row in predictions if row["role"] == "scored"]
    corrections = [row for row in scored if row["expected"] == "correction"]
    negatives = [row for row in scored if row["expected"] == "not_correction"]
    ambiguous = [row for row in scored if row["expected"] == "ambiguous"]
    controls = [row for row in predictions if row["role"] == "native_format_control"]
    valid = all(row["acceptable"] for row in predictions)
    payload = {
        "schema_version": "1.0",
        "record_type": "correction_native_corpus_result",
        "corpus_id": corpus.corpus_id,
        "evaluated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source_revision": source_revision,
        "corpus": str(args.corpus),
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "prompt": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": hashlib.sha256(PROMPT.read_bytes()).hexdigest(),
        "model": args.model,
        "batch_size": args.batch_size,
        "trace_prefix": trace_id,
        "metrics": {
            "exact_event_coverage": f"{len(predictions)}/{len(corpus.cases)}",
            "scored_correction_recall": f"{sum(row['actual'] == 'correction' for row in corrections)}/{len(corrections)}",
            "scored_non_correction_false_positives": sum(
                row["actual"] == "correction" for row in negatives
            ),
            "scored_ambiguous_enforcement_positives": sum(
                row["actual"] == "correction" for row in ambiguous
            ),
            "claude_native_format_false_positives": sum(
                row["actual"] == "correction" for row in controls
            ),
            "session_count": len({(row["agent"], row["session_id"]) for row in predictions}),
        },
        "predictions": predictions,
        "run_status": "valid_pass" if valid else "valid_fail",
        "decision_status": (
            "continue_to_independent_signoff" if valid else "retain_manual_off"
        ),
        "non_claims": [
            "Claude Code native-format controls are not human-conversation evidence.",
            "This result cannot authorize blocking mode without independent signoff and both native observe receipts.",
            "No assistant text, user text, or model rationale is retained in this artifact.",
        ],
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    atomic_write(args.result, serialized)
    print(serialized)
    return 0 if valid else 1


def main() -> int:
    args = parse_args()
    if args.corpus:
        return evaluate_native_corpus(args)
    exchanges = extract_transcript_exchanges(args.transcript, agent=args.agent)
    if args.max_exchanges < 1:
        raise SystemExit("--max-exchanges must be positive")
    exchanges = exchanges[-args.max_exchanges :]
    transcript_digest = hashlib.sha256(args.transcript.expanduser().read_bytes()).hexdigest()[:20]
    trace_id = f"correction-learning/{args.agent}/{args.session_id.split(':', 1)[-1]}/{transcript_digest}"
    receipt = audit_exchanges(
        agent=args.agent,
        session_id=args.session_id,
        exchanges=exchanges,
        classifier=lambda items, learnings: classify_in_batches(
            items,
            learnings,
            model=args.model,
            trace_id=trace_id,
            batch_size=args.batch_size,
        ),
        learning_entries_dir=args.learning_entries_dir,
    )
    atomic_write(args.receipt, receipt.model_dump_json())
    print(receipt.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
