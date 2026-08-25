#!/usr/bin/env python3
"""Fail when a judged-acceptance project's apparatus outgrows its accepted output.

The operating model's Acceptance-Mode-Aware Planning section requires a judged
plan to declare an apparatus ceiling and treats a breach as a stop condition.
This makes that computable, because a ceiling nothing measures is the failure
the same section names: a gate the documentation claims and nothing executes.

In checked work apparatus is value. In judged work it is cost, and it grows
without anyone deciding to grow it -- every plan, method note, audit and
handoff is defensible on its own. Only the ratio shows the pattern.

Declare it in the target repo as `apparatus-ratio.json`:

    {
      "unit": "words of prose you have approved",
      "accepted": ["manuscript/locked/**/*.md"],
      "apparatus": ["*.md", "plan/**/*.md", "docs/**/*.md"],
      "ceiling": 8
    }

`accepted` names ACCEPTED output, not produced output. A draft nobody has
approved is not the denominator; if it were, the measure would reward writing.

    check_apparatus_ratio.py <repo>            # fails on breach, or on zero

Exit 0 within ceiling, 1 on breach or empty denominator, 2 on bad input.
Stdlib plus pydantic, matching this repository's contract convention.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONFIG_NAME = "apparatus-ratio.json"


class RatioConfig(BaseModel):
    """The declaration a judged-acceptance project owes."""

    model_config = ConfigDict(extra="forbid")

    unit: str = Field(min_length=1)
    accepted: list[str] = Field(min_length=1)
    apparatus: list[str] = Field(min_length=1)
    ceiling: float = Field(gt=0)


def count_words(root: Path, patterns: list[str]) -> tuple[int, int]:
    """Words and file count over every match, each file counted once."""
    seen: set[Path] = set()
    for pat in patterns:
        for p in root.glob(pat):
            if p.is_file():
                seen.add(p.resolve())
    total = 0
    for p in seen:
        try:
            total += len(p.read_text(encoding="utf-8", errors="ignore").split())
        except OSError:
            continue
    return total, len(seen)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args(argv)

    root = args.repo.resolve()
    cfg_path = args.config or (root / CONFIG_NAME)
    if not cfg_path.is_file():
        print(f"RESULT: FAIL - no {cfg_path}. A judged-acceptance project must "
              f"declare its unit of accepted output and its apparatus ceiling.",
              file=sys.stderr)
        return 2
    try:
        cfg = RatioConfig.model_validate_json(cfg_path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError) as exc:
        print(f"RESULT: FAIL - {cfg_path} is not a valid declaration: {exc}",
              file=sys.stderr)
        return 2

    accepted, n_acc = count_words(root, cfg.accepted)
    apparatus, n_app = count_words(root, cfg.apparatus)

    print(f"unit: {cfg.unit}")
    print(f"  accepted   {accepted:>9,} words  ({n_acc} file(s))")
    print(f"  apparatus  {apparatus:>9,} words  ({n_app} file(s))")

    if accepted == 0:
        print(f"\nRESULT: FAIL - zero accepted output. The ratio has no "
              f"denominator, so the ceiling of {cfg.ceiling:g}:1 cannot bind and "
              f"apparatus is unbounded. This is the state the ceiling exists to "
              f"make visible, not an error in the check.", file=sys.stderr)
        return 1

    ratio = apparatus / accepted
    print(f"  ratio      {ratio:>9.1f} : 1   ceiling {cfg.ceiling:g} : 1")
    if ratio > cfg.ceiling:
        print(f"\nRESULT: FAIL - apparatus is {ratio:.1f}x accepted output, over "
              f"the declared ceiling of {cfg.ceiling:g}x. Stop adding supporting "
              f"material and produce accepted output, or raise the ceiling "
              f"deliberately and record why.", file=sys.stderr)
        return 1
    print("\nRESULT: within ceiling")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
