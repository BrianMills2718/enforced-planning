#!/usr/bin/env python3
"""Execute one strict, native-session self-claim bootstrap request."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_package() -> None:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Unable to locate local enforced_planning support")


_bootstrap_package()

from enforced_planning.claim_bootstrap import (
    ClaimBootstrapError,
    execute_request,
    parse_request_json,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--request-json", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        request = parse_request_json(args.request_json)
        payload = execute_request(request)
    except (ClaimBootstrapError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "schema_version": "1.0",
                    "error": {"code": "claim_bootstrap_denied", "message": str(exc)},
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
