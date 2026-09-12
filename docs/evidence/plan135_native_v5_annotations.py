#!/usr/bin/env python3
"""Run the shared privacy-reduced annotation pipeline for native v5."""

from pathlib import Path

import plan135_native_v4_annotations as pipeline

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence"

pipeline.CANDIDATES = EVIDENCE / "plan135_native_v5_candidates.json"
pipeline.LABEL_A = EVIDENCE / "plan135_native_v5_labels_a.json"
pipeline.LABEL_B = EVIDENCE / "plan135_native_v5_labels_b.json"
pipeline.ADJUDICATION = EVIDENCE / "plan135_native_v5_adjudication.json"
pipeline.CORPUS = ROOT / "prompts/correction_learning/native_corpus_v5.json"
pipeline.SUMMARY = EVIDENCE / "plan135_native_v5_annotation_summary.json"
pipeline.CASE_PREFIX = "native-v5"
pipeline.CORPUS_ID = "correction-learning-native-v5"
pipeline.SCORED_POPULATION = (
    "Deterministic 16-session-per-client sample from the unseen 2026-08-24 "
    "through 2026-08-30 population."
)


if __name__ == "__main__":
    raise SystemExit(pipeline.main())
