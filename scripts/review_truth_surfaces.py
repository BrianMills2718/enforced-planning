#!/usr/bin/env python3
"""Deprecated compatibility wrapper for semantic truth-surface review.

The canonical semantic-review entrypoint is now
``scripts/review_truth_surface_semantic.py --config ...``. This wrapper exists
only to preserve a bounded migration path for callers that still invoke the
older repo-wide command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.review_truth_surface_semantic import (  # noqa: E402
    DEFAULT_HISTORY_JSON,
    DEFAULT_OUTPUT_JSON,
    append_semantic_review_history,
    _resolve_output_path,
    review_truth_surface_semantic,
)


def resolve_config_path(repo_root: Path, explicit_config: str | None) -> Path:
    """Resolve the canonical truth-surface config path for the wrapper."""
    if explicit_config:
        return Path(explicit_config).expanduser().resolve()
    return (repo_root / "scripts" / "truth_surface_drift.yaml").resolve()


def main() -> int:
    """Run the compatibility wrapper and print a deprecation notice."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repo root (default: .)")
    parser.add_argument("--config", help="Explicit truth-surface config path")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Latest semantic-review payload path",
    )
    parser.add_argument(
        "--history-json",
        type=Path,
        default=DEFAULT_HISTORY_JSON,
        help="Append-only semantic-review history path",
    )
    parser.add_argument("--model", default="gemini/gemini-2.5-flash")
    parser.add_argument("--max-budget", type=float, default=0.50)
    parser.add_argument(
        "--trace-id",
        default=None,
        help="Trace ID for observability; defaults to a run-unique ID",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the resolved canonical config path")
    args = parser.parse_args()

    repo_root = args.repo.expanduser().resolve()
    if not repo_root.is_dir():
        print(f"Error: {repo_root} is not a directory", file=sys.stderr)
        return 1

    config_path = resolve_config_path(repo_root, args.config)
    print(
        "DEPRECATED: use `python scripts/review_truth_surface_semantic.py --config ...` instead.",
        file=sys.stderr,
    )

    if args.dry_run:
        print(json.dumps({"repo_root": str(repo_root), "config_path": str(config_path)}, indent=2))
        return 0

    if not config_path.exists():
        print(
            f"Error: no truth-surface config found at {config_path}. "
            "Use --config or install/configure truth_surface_drift.yaml first.",
            file=sys.stderr,
        )
        return 1

    review, payload = review_truth_surface_semantic(
        config_path,
        model=args.model,
        max_budget=args.max_budget,
        trace_id=args.trace_id,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    output_path = _resolve_output_path(str(args.output), config_path=config_path)
    if output_path is None:
        print("Error: failed to resolve output path", file=sys.stderr)
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered + "\n")
    if args.history_json:
        history_path = _resolve_output_path(str(args.history_json), config_path=config_path)
        if history_path is None:
            print("Error: failed to resolve history path", file=sys.stderr)
            return 1
        append_semantic_review_history(history_path, payload)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
