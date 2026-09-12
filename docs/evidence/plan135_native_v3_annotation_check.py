#!/usr/bin/env python3
"""Recompute native-v3 agreement, adjudication, and final frozen labels."""

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
    a = _labels("plan135_native_v3_labels_a.json")
    b = _labels("plan135_native_v3_labels_b.json")
    adjudicated = _labels("plan135_native_v3_adjudication.json")
    if set(a) != set(b):
        raise SystemExit("annotator event populations differ")
    disagreements = {event_id for event_id in a if a[event_id] != b[event_id]}
    if set(adjudicated) != disagreements:
        raise SystemExit("adjudication population does not equal disagreements")
    final = {
        event_id: a[event_id]
        if a[event_id] == b[event_id]
        else adjudicated[event_id]
        for event_id in a
    }
    corpus = json.loads(
        (ROOT / "prompts/correction_learning/native_corpus_v3.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {row["event_id"]: row["expected"] for row in corpus["cases"]}
    if final != expected:
        raise SystemExit("reconstructed annotations differ from frozen corpus")
    counts = Counter(final.values())
    print(
        "PASS "
        f"cases={len(final)} agreements={len(final) - len(disagreements)} "
        f"disagreements={len(disagreements)} correction={counts['correction']} "
        f"not_correction={counts['not_correction']} ambiguous={counts['ambiguous']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
