#!/usr/bin/env python3
"""Tombstone for the retired mutable Markdown inbox reader."""

from __future__ import annotations

import sys


def main() -> int:
    """Fail loud so legacy files cannot masquerade as current delivery state."""

    print(
        "Legacy Markdown inbox state is non-authoritative. Use "
        "scripts/meta/coordination_inbox.py to poll or "
        "scripts/meta/coordination_messages.py acknowledge with a strict JSON request.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
