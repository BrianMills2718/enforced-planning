#!/usr/bin/env python3
"""Run a fresh exact-revision Codex review and emit a typed signoff receipt."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.pr_review_signoff import load_review_spec, run_review


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument(
        "--output-schema",
        type=Path,
        default=REPO_ROOT / "contracts" / "pr-review-signoff.schema.json",
    )
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--check-payload", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--model", default="gpt-5.6")
    parser.add_argument("--effort", default="high")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = run_review(
        load_review_spec(args.spec),
        repo_root=args.repo_root,
        output_schema=args.output_schema,
        receipt_path=args.receipt,
        check_payload_path=args.check_payload,
        codex_bin=args.codex_bin,
        model=args.model,
        effort=args.effort,
    )
    print(json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if receipt.verdict == "signed_off" else 1


if __name__ == "__main__":
    raise SystemExit(main())
