#!/usr/bin/env python3
"""Privacy-reduce, adjudicate, assemble, and check native annotations."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence"
CANDIDATES = EVIDENCE / "plan135_native_v4_candidates.json"
LABEL_A = EVIDENCE / "plan135_native_v4_labels_a.json"
LABEL_B = EVIDENCE / "plan135_native_v4_labels_b.json"
ADJUDICATION = EVIDENCE / "plan135_native_v4_adjudication.json"
CORPUS = ROOT / "prompts/correction_learning/native_corpus_v4.json"
SUMMARY = EVIDENCE / "plan135_native_v4_annotation_summary.json"
ALLOWED = {"correction", "not_correction", "ambiguous"}
CASE_PREFIX = "native-v4"
CORPUS_ID = "correction-learning-native-v4"
SCORED_POPULATION = (
    "Deterministic 16-session-per-client sample from the unseen 2026-08-31 "
    "through 2026-09-06 population."
)


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _candidate_rows() -> list[dict[str, object]]:
    return [
        event | {key: source[key] for key in ("agent", "session_id", "source_path")}
        for source in _read(CANDIDATES)["sources"]
        for event in source["events"]
    ]


def _labels(path: Path) -> list[dict[str, str]]:
    rows = _read(path)["labels"]
    if any(set(row) != {"event_id", "label"} or row["label"] not in ALLOWED for row in rows):
        raise SystemExit(f"invalid privacy-reduced labels: {path.name}")
    return rows


def reduce_private(source: Path, annotator: str, destination: Path) -> None:
    private = _read(source)
    rows = [{"event_id": row["event_id"], "label": row["label"]} for row in private["labels"]]
    expected = [row["event_id"] for row in _candidate_rows()]
    actual = [row["event_id"] for row in rows]
    if actual != expected or len(set(actual)) != len(actual):
        raise SystemExit("private annotation does not exactly cover the candidate manifest")
    if any(row["label"] not in ALLOWED for row in rows):
        raise SystemExit("private annotation contains an invalid label")
    _write(destination, {"annotator": annotator, "labels": rows})


def write_disagreements(destination: Path) -> None:
    a = {row["event_id"]: row["label"] for row in _labels(LABEL_A)}
    b = {row["event_id"]: row["label"] for row in _labels(LABEL_B)}
    expected = [row["event_id"] for row in _candidate_rows()]
    if list(a) != expected or list(b) != expected:
        raise SystemExit("annotator populations do not match candidate order")
    _write(destination, {"event_ids": [event_id for event_id in expected if a[event_id] != b[event_id]]})


def _final_labels() -> tuple[dict[str, str], int]:
    a = {row["event_id"]: row["label"] for row in _labels(LABEL_A)}
    b = {row["event_id"]: row["label"] for row in _labels(LABEL_B)}
    adjudicated = {row["event_id"]: row["label"] for row in _labels(ADJUDICATION)}
    disagreements = {event_id for event_id in a if a[event_id] != b[event_id]}
    if set(adjudicated) != disagreements:
        raise SystemExit("adjudication population does not equal disagreements")
    return (
        {event_id: a[event_id] if a[event_id] == b[event_id] else adjudicated[event_id] for event_id in a},
        len(disagreements),
    )


def build(candidate_commit: str, labels_commit: str, adjudication_commit: str) -> None:
    candidates = _read(CANDIDATES)
    final, disagreement_count = _final_labels()
    frozen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cases = [
        {
            "agent": row["agent"],
            "case_id": f"{CASE_PREFIX}-{index:03d}",
            "event_hash": row["event_hash"],
            "event_id": row["event_id"],
            "expected": final[row["event_id"]],
            "occurred_at": row["occurred_at"],
            "role": "scored",
            "session_id": row["session_id"],
            "source_path": row["source_path"],
        }
        for index, row in enumerate(_candidate_rows(), start=1)
    ]
    sources = [
        {key: source[key] for key in ("agent", "session_id", "source_path", "window_start", "window_end")}
        for source in candidates["sources"]
    ]
    corpus = {
        "cases": cases,
        "corpus_id": CORPUS_ID,
        "frozen_at": frozen_at,
        "pilot_cutoff": candidates["population_start"],
        "schema_version": "1.1",
        "selection": {
            "label_basis": "Privacy-reduced A/B labels committed independently before blind adjudication; all disagreements resolved before corpus freeze and replay.",
            "native_format_controls": "Typed Codex content_item_kinds and Claude Code isMeta admission are deterministic tested controls upstream.",
            "privacy": "No conversation prose or annotation rationale retained; exact home-relative provenance permits local verification.",
            "scored_population": SCORED_POPULATION,
            "scored_sources": sources,
        },
    }
    _write(CORPUS, corpus)
    counts = Counter(final.values())
    artifacts = [CANDIDATES, LABEL_A, LABEL_B, ADJUDICATION]
    summary = {
        "artifact_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts},
        "combined": {
            "adjudicated": disagreement_count,
            "agreements": len(final) - disagreement_count,
            "cases": len(final),
            "disagreements": disagreement_count,
            "labels": dict(sorted(counts.items())),
        },
        "commit_chain": {
            "adjudication": adjudication_commit,
            "candidate": candidate_commit,
            "labels": labels_commit,
        },
        "corpus_id": CORPUS_ID,
        "frozen_at": frozen_at,
        "non_claims": [
            "Conversation prose and annotation rationales are not retained.",
            "Annotation agreement does not establish classifier accuracy.",
        ],
        "record_type": "native_corpus_annotation_summary",
        "schema_version": "1.0",
    }
    _write(SUMMARY, summary)


def check() -> None:
    final, disagreement_count = _final_labels()
    corpus = _read(CORPUS)
    expected = {row["event_id"]: row["expected"] for row in corpus["cases"]}
    if final != expected:
        raise SystemExit("reconstructed annotations differ from frozen corpus")
    counts = Counter(final.values())
    print(
        f"PASS cases={len(final)} agreements={len(final) - disagreement_count} "
        f"disagreements={disagreement_count} correction={counts['correction']} "
        f"not_correction={counts['not_correction']} ambiguous={counts['ambiguous']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    reduce_parser = subparsers.add_parser("reduce")
    reduce_parser.add_argument("source", type=Path)
    reduce_parser.add_argument("annotator")
    reduce_parser.add_argument("destination", type=Path)
    disagreement_parser = subparsers.add_parser("disagreements")
    disagreement_parser.add_argument("destination", type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("candidate_commit")
    build_parser.add_argument("labels_commit")
    build_parser.add_argument("adjudication_commit")
    subparsers.add_parser("check")
    args = parser.parse_args()
    if args.command == "reduce":
        reduce_private(args.source, args.annotator, args.destination)
    elif args.command == "disagreements":
        write_disagreements(args.destination)
    elif args.command == "build":
        build(args.candidate_commit, args.labels_commit, args.adjudication_commit)
    else:
        check()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
