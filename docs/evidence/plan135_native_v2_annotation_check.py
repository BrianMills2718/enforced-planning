#!/usr/bin/env python3
"""Recompute Plan 135 native-v2 agreement, adjudication, and final labels."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence"


def _labels(name: str) -> dict[str, str]:
    payload = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    return {row["event_id"]: row["label"] for row in payload["labels"]}


def main() -> int:
    waves = [
        (
            "plan135_native_v2_labels_a.json",
            "plan135_native_v2_labels_b.json",
            "plan135_native_v2_adjudication.json",
        ),
        (
            "plan135_native_v2_extension1_labels_a.json",
            "plan135_native_v2_extension1_labels_b.json",
            "plan135_native_v2_extension1_adjudication.json",
        ),
    ]
    final: dict[str, str] = {}
    agreements = 0
    disagreements = 0
    for a_name, b_name, adjudication_name in waves:
        a = _labels(a_name)
        b = _labels(b_name)
        adjudicated = _labels(adjudication_name)
        if set(a) != set(b):
            raise SystemExit("annotator event populations differ")
        wave_disagreements = {event_id for event_id in a if a[event_id] != b[event_id]}
        if set(adjudicated) != wave_disagreements:
            raise SystemExit("adjudication population does not equal disagreements")
        agreements += len(a) - len(wave_disagreements)
        disagreements += len(wave_disagreements)
        final.update(
            {
                event_id: a[event_id]
                if a[event_id] == b[event_id]
                else adjudicated[event_id]
                for event_id in a
            }
        )

    corpus = json.loads(
        (ROOT / "prompts/correction_learning/native_corpus_v2.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {row["event_id"]: row["expected"] for row in corpus["cases"]}
    if final != expected:
        raise SystemExit("reconstructed annotations differ from frozen corpus")
    counts = Counter(final.values())
    print(
        "PASS "
        f"cases={len(final)} agreements={agreements} disagreements={disagreements} "
        f"correction={counts['correction']} not_correction={counts['not_correction']} "
        f"ambiguous={counts['ambiguous']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
