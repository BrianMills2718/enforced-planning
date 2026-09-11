#!/usr/bin/env python3
"""Audit one native transcript for user corrections and durable learnings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
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
)

PROMPT = ROOT / "prompts/correction_learning/classify.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=("codex", "claude-code"))
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--transcript", required=True, type=Path)
    parser.add_argument("--learning-entries-dir", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--model", default="claude-code/haiku")
    parser.add_argument("--max-exchanges", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=5)
    return parser.parse_args()


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
        classified = classify_with_model(
            batch,
            learning_candidates,
            model=model,
            trace_id=f"{trace_id}/batch-{index // batch_size + 1}",
        )
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


def main() -> int:
    args = parse_args()
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
