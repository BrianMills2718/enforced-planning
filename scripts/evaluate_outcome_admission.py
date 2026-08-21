#!/usr/bin/env python3
"""Run the frozen first-consumer outcome-admission evaluation."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError


def _add_repo_root_to_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "enforced_planning").is_dir():
            sys.path.insert(0, str(parent))
            return parent
    raise RuntimeError("Unable to locate repository root containing enforced_planning/")


ROOT = _add_repo_root_to_path()

from enforced_planning.outcome_admission_evaluation import (
    evaluate_admission_suite,
    load_evaluation_inputs,
    resolve_candidate_source_binding,
    result_sha256,
    run_corruption_control,
)


def _head_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--population", required=True, type=Path)
    parser.add_argument(
        "--candidate-revision",
        help="Exact implementation commit; defaults to current checkout HEAD.",
    )
    parser.add_argument(
        "--corruption-control",
        action="store_true",
        help="Also invert one expectation in memory and require mismatch detection.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        loaded = load_evaluation_inputs(
            cases_path=args.cases.resolve(),
            population_path=args.population.resolve(),
        )
        candidate_revision = args.candidate_revision or _head_revision()
        source_binding = resolve_candidate_source_binding(
            repo_root=ROOT,
            candidate_revision=candidate_revision,
            source_ref="enforced_planning/outcome_admission_evaluation.py",
        )
        result = evaluate_admission_suite(
            loaded,
            candidate_revision=source_binding.candidate_revision,
            candidate_source_sha256=source_binding.source_sha256,
        )
        corruption = run_corruption_control(loaded) if args.corruption_control else None
    except (OSError, ValueError, ValidationError, subprocess.CalledProcessError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "evaluation_invalid",
                        "message": str(exc),
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    corruption_passed = corruption is None or corruption.mismatch_detected
    ok = result.promotion_thresholds_passed and corruption_passed
    payload = {
        "ok": ok,
        "result_sha256": result_sha256(result),
        "result": result.model_dump(mode="json"),
        "corruption_control": (
            corruption.model_dump(mode="json") if corruption is not None else None
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
