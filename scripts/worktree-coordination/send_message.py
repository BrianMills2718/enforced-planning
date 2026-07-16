#!/usr/bin/env python3
"""Tombstone for the retired Markdown inbox sender."""

from __future__ import annotations

import sys


def main() -> int:
    """Fail loud so callers cannot create a second message authority."""

    print(
        "Legacy Markdown messaging is retired. Use "
        "scripts/meta/coordination_messages.py send with a strict JSON request.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
