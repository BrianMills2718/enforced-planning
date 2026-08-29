#!/usr/bin/env python3
"""Refuse a completed-work report that states a failure count without showing one.

A count of failures looks identical whether the failures are real or cosmetic,
so it never prompts the question that would settle it. That is the cheapest
recurring failure in this ecosystem and the most expensive: it wastes long
provider runs, and worse, it drives confident wrong diagnoses that make the
system worse in the attempt to fix them.

ac16, 2026-08-25, is the instance this was written from. A validator compared
generated output to expected output with exact dictionary equality, including a
free-text `detail` message paired with a machine-readable error code. It failed
correct code over wording. Three days of reports each carried a count -- "16
mismatches", "20 mismatches", "37.9% of cases wrong" -- and each count drove a
diagnosis. Two of the three were withdrawn. The expected and actual values had
been stored in every run record from the very first run; nobody printed one.
Printing four pairs took two minutes and overturned everything.

The gate does not judge whether a diagnosis is right. It enforces the observable
boundary around it: if you are going to report that N things failed, show what at
least one of them looked like, or name where the reader can see them.

Sibling of learning_capture_hook.py and deliberately the same shape: read the
final assistant report from a Stop payload, classify, block with a message the
agent will read. A gate teaches by blocking; prose in a skill nobody loads does
not.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

SUPPORTED_AGENTS = ("claude-code", "codex", "openclaw")

# Below this, agents reliably name the failures individually and the gate is noise.
MIN_FAILURES = 3

# Claims of the shape "N failed" / "N of M failed" / "N% passing".
_FAIL_WORDS = r"(?:fail(?:ed|ing|ure)s?|mismatch(?:es)?|error(?:s)?|reject(?:ed|ions?)|wrong|incorrect|broken)"
COUNT_PATTERNS = (
    # Up to two words may sit between the number and the verdict: "37 cases wrong",
    # "12 acceptance cases failed". Over-firing costs a sample, which is the thing
    # we want anyway; under-firing costs a wrong diagnosis.
    rf"\b(\d+)\s+(?:\w+\s+){{0,2}}{_FAIL_WORDS}\b",
    rf"\b(\d+)\s*(?:of|/)\s*\d+\s+\w*\s*{_FAIL_WORDS}\b",
    rf"{_FAIL_WORDS}\s*[:=]\s*(\d+)\b",
)

# Evidence that the author actually looked at one, rather than counted them.
_EXPECTED_ACTUAL = re.compile(
    r"expected\b.{0,400}?\bactual\b|\bactual\b.{0,400}?\bexpected\b",
    re.IGNORECASE | re.DOTALL,
)
_ARROW_SAMPLE = re.compile(r"[`\"'\w\]\}].{0,80}?(?:->|→|≠|!=|vs\.?)\s*.{0,80}", re.DOTALL)
_ARTIFACT_PATH = re.compile(r"\b[\w./-]+\.(?:json|jsonl|log|txt|md|csv|diff)\b")
_FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=SUPPORTED_AGENTS)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run the built-in cases and exit non-zero if the gate is not a real detector.",
    )
    return parser.parse_args(argv)


def report_field(report: str, name: str) -> str | None:
    """Return one CommonMark closing-report bullet by bold field name."""
    pattern = rf"[-*]\s*\*\*{re.escape(name)}\*\*\s*[-—:]?\s*(.+?)(?=\n[-*]\s*\*\*|\Z)"
    match = re.search(pattern, report, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def failure_counts(report: str) -> list[int]:
    """Every failure count claimed in the report, largest first."""
    found: list[int] = []
    for pattern in COUNT_PATTERNS:
        for match in re.finditer(pattern, report, re.IGNORECASE):
            try:
                found.append(int(match.group(1)))
            except (ValueError, IndexError):
                continue
    return sorted(found, reverse=True)


def shows_a_sample(report: str) -> bool:
    """Whether the report shows what a failure looked like, or says where to see them.

    Deliberately generous. The gate exists to catch a bare count, not to grade
    the presentation. Any of these clears it:

      - an expected value set beside an actual one;
      - a fenced block (a pasted diff, table, or run output);
      - an `x -> y` / `x != y` style sample;
      - a path to a committed artifact holding the failures.
    """
    if _FENCED_BLOCK.search(report):
        return True
    if _EXPECTED_ACTUAL.search(report):
        return True
    if _ARTIFACT_PATH.search(report):
        return True
    return bool(_ARROW_SAMPLE.search(report))


def classify_report(report: str) -> tuple[str, str]:
    """Return ``(decision, detail)`` for one final assistant report."""
    if report_field(report, "Done") is None:
        return "not_completed_work", "No completed-work report was present."

    counts = failure_counts(report)
    if not counts or counts[0] < MIN_FAILURES:
        return "no_count_claimed", "No failure count of consequence was claimed."

    if shows_a_sample(report):
        return "sample_shown", f"Largest claimed failure count {counts[0]} is accompanied by evidence."

    return (
        "block_count_without_sample",
        (
            f"This report states that {counts[0]} things failed and does not show what any "
            "of them looked like.\n\n"
            "A count of failures reads as understanding, and it is not. It looks identical "
            "whether the failures are real or cosmetic, so it never prompts the question "
            "that would settle it. On 2026-08-25 three consecutive diagnoses were built on "
            "counts like this one; two were withdrawn, and the evidence that overturned them "
            "had been sitting in the run records the whole time.\n\n"
            "Before reporting: print the full expected value beside the full actual value for "
            "at least three of them and read them yourself. Then either include one in the "
            "report, or name the committed artifact where they can be read.\n\n"
            "Also worth ten seconds while you are there: run a known-good reference through "
            "the same checker (`trace_eval.reference_selfcheck`). If your checker rejects "
            "known-correct input, the checker is what is broken."
        ),
    )


SELF_TEST_CASES: tuple[tuple[str, str, str], ...] = (
    (
        "bare count blocks",
        "- **Done** — ran it.\n- **Next** — 16 mismatches remain, investigating.",
        "block_count_without_sample",
    ),
    (
        "count with expected/actual passes",
        "- **Done** — ran it. 16 mismatches; case c1 expected {'a': 1}, actual {'a': 2}.",
        "sample_shown",
    ),
    (
        "count with a fenced sample passes",
        "- **Done** — 12 failures.\n```\nc1: bad_timestamp X | bad_timestamp Y\n```",
        "sample_shown",
    ),
    (
        "count naming a committed artifact passes",
        "- **Done** — 20 failures, all recorded in docs/results/run.json.",
        "sample_shown",
    ),
    (
        "small count is not gated",
        "- **Done** — 1 failure, the pinned llm_client test.",
        "no_count_claimed",
    ),
    (
        "not a completed-work report is not gated",
        "Still working on it, 40 failures so far.",
        "not_completed_work",
    ),
    (
        "percentage-only claim without a sample blocks",
        "- **Done** — measured it.\n- **Next** — 37 cases wrong out of 219, diagnosing.",
        "block_count_without_sample",
    ),
)


def self_test() -> int:
    """A gate not observed failing on known-bad input, and passing on known-good, is not evidence."""
    failures = []
    for name, report, expected in SELF_TEST_CASES:
        decision, _ = classify_report(report)
        if decision != expected:
            failures.append(f"  {name}: expected {expected!r}, got {decision!r}")
    if failures:
        print("SELF-TEST FAILED:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"self-test passed: {len(SELF_TEST_CASES)} cases, both directions")
    return 0


def read_event() -> dict[str, Any]:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise TypeError("hook input must be a JSON object")
    if payload.get("hook_event_name") != "Stop":
        raise ValueError("evidence sample hook requires hook_event_name=Stop")
    if not isinstance(payload.get("last_assistant_message"), str):
        raise ValueError("Stop payload requires last_assistant_message")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        payload = read_event()
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        # Fail open on a malformed payload: this gate must never strand a session.
        print(f"evidence-sample gate skipped: {exc}", file=sys.stderr)
        return 0
    if payload.get("stop_hook_active"):
        # Claude re-fires Stop after a hook blocks. Repeating the same refusal
        # cannot produce the missing sample and strands the session in a loop;
        # teach once, then let the re-fired Stop end the turn.
        return 0
    decision, detail = classify_report(payload["last_assistant_message"])
    if decision == "block_count_without_sample":
        print(detail, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
