#!/usr/bin/env python3
"""Select, inspect, or clear a read-only repository context target."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.read_target import (  # noqa: E402
    ReadTargetError,
    clear_read_target,
    resolve_read_target,
    select_read_target,
    validate_request,
)


def _payload(client: str) -> dict[str, str]:
    key = "CODEX_THREAD_ID" if client == "codex" else "CLAUDE_CODE_SESSION_ID"
    value = os.environ.get(key, "").strip()
    if not value:
        raise ReadTargetError("session_identity_unavailable", f"{key} is required")
    return {"session_id": value}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--request-json")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.show:
            client = "codex" if os.environ.get("CODEX_THREAD_ID") else "claude-code"
            result = resolve_read_target(_payload(client), client=client)
        else:
            if not args.request_json:
                parser.error("--request-json is required unless --show is used")
            request = validate_request(json.loads(args.request_json))
            client = str(request.get("client", ""))
            payload = _payload(client)
            if request.get("operation") == "select":
                result = select_read_target(
                    payload,
                    client=client,
                    project=str(request.get("project", "")),
                    repo_root=str(request.get("repo_root", "")),
                    registry_path=Path(str(request.get("registry_path", ""))),
                )
            elif request.get("operation") == "clear":
                result = clear_read_target(payload, client=client)
            else:
                raise ReadTargetError("read_target_request_invalid", "operation must be select or clear")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": {"code": getattr(exc, "reason_code", "read_target_failed"), "message": str(exc)}}), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "result": result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
