#!/usr/bin/env python3
"""Report hook-invocation health and recurrent outcomes with exact evidence IDs.

The sweep is resilient by design: a single malformed receipt is counted and
named in the output instead of aborting the run. Nothing is silently dropped --
every skipped record is reported with its path and defect reason.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hook_receipts import (  # noqa: E402
    DEFAULT_PREWRITE_EVENT_PATH,
    DEFAULT_RECEIPT_ROOT,
    DEFAULT_SETTINGS_PATHS,
    DEFAULT_TIMEOUT_BUDGET_FRACTION,
    HookReceiptError,
    group_hook_recurrences,
    group_prewrite_recurrences,
    load_declared_hook_commands,
    match_declared_timeouts,
    scan_hook_receipts,
    scan_prewrite_events,
    summarize_hook_health,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-root", type=Path, default=DEFAULT_RECEIPT_ROOT)
    parser.add_argument("--prewrite-events", type=Path, default=DEFAULT_PREWRITE_EVENT_PATH)
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument(
        "--settings",
        type=Path,
        action="append",
        default=None,
        help="Settings file declaring hook timeouts (repeatable).",
    )
    parser.add_argument(
        "--budget-fraction",
        type=float,
        default=DEFAULT_TIMEOUT_BUDGET_FRACTION,
        help="Flag a hook whose measured p95 exceeds this fraction of its declared timeout.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Human-readable table (default) or the full machine-readable record.",
    )
    parser.add_argument(
        "--max-malformed-examples",
        type=int,
        default=5,
        help="How many malformed-receipt example paths to print per defect reason.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any receipt was skipped as malformed.",
    )
    return parser


def _ms(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.0f}ms"


def _render_text(report: dict[str, Any], *, max_examples: int) -> str:
    health = report["health"]
    lines: list[str] = []
    lines.append("Hook invocation telemetry")
    lines.append(f"  receipt root: {health['receipt_root']}")
    lines.append(
        "  scanned {dirs:,} legacy receipt directories and {journals:,} daily journals: "
        "{started:,} started, {completed:,} completed, "
        "{orphan:,} orphaned starts, {bad:,} malformed".format(
            dirs=health["receipt_dir_count"],
            journals=health["journal_file_count"],
            started=health["started_receipt_count"],
            completed=health["completed_receipt_count"],
            orphan=health["orphaned_start_count"],
            bad=health["malformed_receipt_count"],
        )
    )
    lines.append("")

    bad = health["malformed_receipt_count"]
    if bad:
        lines.append(f"MALFORMED: {bad:,} receipts skipped as malformed (not counted in latency)")
        for entry in health["malformed_by_reason"]:
            lines.append(f"  {entry['count']:>6,}  {entry['reason']}")
            lines.append(f"          example: {entry['example_path']}")
        by_hook = health["malformed_by_hook"]
        if by_hook:
            lines.append("  attributed hooks: " + ", ".join(f"{name} x{count}" for name, count in by_hook.items()))
        uncounted = health.get("malformed_uncounted_outcomes") or []
        if uncounted:
            lines.append("  outcomes these bad records carried, EXCLUDED from every number below:")
            for entry in uncounted:
                lines.append(f"    {entry['count']:>6,}  {entry['outcome']}")
        lines.append("")
    else:
        lines.append("MALFORMED: 0 receipts skipped as malformed")
        lines.append("")

    header = (
        f"{'hook':<28}{'started':>9}{'done':>9}{'bad':>6}{'orphan':>8}"
        f"{'p50':>10}{'p95':>10}{'max':>10}{'timeout':>10}{'p95/budget':>12}  flag"
    )
    lines.append("Per-hook latency, failures, and declared timeout budget")
    lines.append("  " + header)
    lines.append("  " + "-" * len(header))
    for hook in health["hooks"]:
        ratio = hook["p95_fraction_of_declared_timeout"]
        if ratio is None:
            ratio_text = "unknown"
        else:
            ratio_text = f"{ratio * 100:.1f}%"
        if hook["p95_over_budget"] is True:
            flag = f"OVER {health['budget_fraction'] * 100:.0f}% OF BUDGET"
        elif hook["p95_over_budget"] is False:
            flag = "ok"
        else:
            flag = f"no declared timeout matched ({hook['declared_timeout_note']})"
        lines.append(
            "  "
            + f"{hook['hook_name']:<28}"
            + f"{hook['started_count']:>9,}"
            + f"{hook['completed_count']:>9,}"
            + f"{hook['malformed_receipt_count']:>6,}"
            + f"{hook['orphaned_start_count']:>8,}"
            + f"{_ms(hook['p50_elapsed_ms']):>10}"
            + f"{_ms(hook['p95_elapsed_ms']):>10}"
            + f"{_ms(hook['max_elapsed_ms']):>10}"
            + f"{_ms(hook['declared_timeout_ms']):>10}"
            + f"{ratio_text:>12}  "
            + flag
        )
    lines.append("")

    lines.append("Nonzero exits")
    any_exit = False
    for hook in health["hooks"]:
        if hook["nonzero_exit_count"]:
            any_exit = True
            codes = ", ".join(f"exit={code} x{count}" for code, count in hook["nonzero_exit_by_code"].items())
            lines.append(
                f"  {hook['hook_name']}: {hook['nonzero_exit_count']:,} nonzero "
                f"({hook['nonzero_exit_count'] / max(hook['completed_count'], 1) * 100:.2f}% of completions) -- {codes}"
            )
    if not any_exit:
        lines.append("  none")
    lines.append("")

    lines.append("Orphaned starts (started receipt with no sibling completion = interrupted hook)")
    any_orphan = False
    for hook in health["hooks"]:
        if hook["orphaned_start_count"]:
            any_orphan = True
            lines.append(
                f"  {hook['hook_name']}: {hook['orphaned_start_count']:,} "
                f"({hook['orphaned_start_count'] / max(hook['started_count'], 1) * 100:.2f}% of starts)"
            )
    if not any_orphan:
        lines.append("  none")
    lines.append("")

    recurrence = report["recurrence"]
    recurrent = [group for group in recurrence["groups"] if group["recurrent"]]
    lines.append(
        f"Recurrent outcome groups (threshold {recurrence['threshold']}): "
        f"{len(recurrent)} of {len(recurrence['groups'])} groups"
    )
    for group in sorted(recurrent, key=lambda item: -item["count"])[:20]:
        lines.append(
            f"  {group['count']:>6,}  {group['hook_name']} v{group['hook_version']} "
            f"[{group['event_name']}] {group['decision']} / {group['reason_code']}"
        )
    if len(recurrent) > 20:
        lines.append(f"  ... {len(recurrent) - 20} more recurrent groups (use --format json)")
    lines.append("")

    prewrite = report["prewrite_recurrence"]
    recurrent_prewrite = [group for group in prewrite["groups"] if group["recurrent"]]
    lines.append(
        f"Prewrite decision groups (threshold {prewrite['threshold']}): "
        f"{len(recurrent_prewrite)} of {len(prewrite['groups'])} groups recurrent"
    )
    lines.append(f"  event path: {prewrite['event_path']}")
    lines.append(
        f"  scanned {prewrite['event_count']:,} valid events; "
        f"{prewrite['malformed_count']:,} malformed lines"
    )
    for group in sorted(recurrent_prewrite, key=lambda item: -item["count"])[:20]:
        lines.append(
            f"  {group['count']:>6,}  {group['client']} [{group['mode']}] "
            f"{group['decision']} / {group['reason_code']}"
        )
    if len(recurrent_prewrite) > 20:
        lines.append(f"  ... {len(recurrent_prewrite) - 20} more recurrent groups (use --format json)")
    if prewrite["missing"]:
        lines.append("  note: prewrite event store does not exist")
    for malformed in prewrite["malformed"][:max_examples]:
        lines.append(f"  malformed line {malformed['line']}: {malformed['reason']}")
    lines.append("")

    if report["notes"]:
        lines.append("Notes")
        for note in report["notes"]:
            lines.append(f"  - {note}")
        lines.append("")

    lines.append("Disposition: make ecosystem-feedback ARGS='record ...' using the exact receipt IDs.")
    _ = max_examples
    return "\n".join(lines)


def build_report(
    *,
    receipt_root: Path,
    prewrite_event_path: Path = DEFAULT_PREWRITE_EVENT_PATH,
    threshold: int,
    settings_paths: tuple[Path, ...],
    budget_fraction: float,
) -> dict[str, Any]:
    scan = scan_hook_receipts(receipt_root)
    declared_commands, notes = load_declared_hook_commands(settings_paths)
    declared = match_declared_timeouts(scan.completed, declared_commands)
    health = summarize_hook_health(scan, declared=declared, budget_fraction=budget_fraction)
    recurrence = group_hook_recurrences(scan.completed, threshold=threshold)
    prewrite_recurrence = group_prewrite_recurrences(
        scan_prewrite_events(prewrite_event_path),
        threshold=threshold,
    )
    all_notes = list(notes)
    for name, entry in sorted(declared.items()):
        if not entry.get("matched"):
            all_notes.append(
                f"{name}: no declared timeout matched -- {entry['match_basis']} "
                f"({entry['distinct_script_digests']} distinct recorded script digests)"
            )
    return {
        "schema_version": 1,
        "record_type": "hook_feedback_report",
        "settings_paths": [str(path) for path in settings_paths],
        "health": health,
        "recurrence": recurrence,
        "prewrite_recurrence": prewrite_recurrence,
        "notes": all_notes,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings_paths = tuple(args.settings) if args.settings else DEFAULT_SETTINGS_PATHS
    try:
        report = build_report(
            receipt_root=args.receipt_root,
            prewrite_event_path=args.prewrite_events,
            threshold=args.threshold,
            settings_paths=settings_paths,
            budget_fraction=args.budget_fraction,
        )
    except (HookReceiptError, ValueError) as exc:
        print(f"hook feedback report failed: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_render_text(report, max_examples=args.max_malformed_examples))

    malformed = (
        report["health"]["malformed_receipt_count"]
        + report["prewrite_recurrence"]["malformed_count"]
    )
    if malformed and args.strict:
        print(
            f"strict mode: {malformed} malformed telemetry record(s) skipped; see the report",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
