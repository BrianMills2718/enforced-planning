#!/usr/bin/env python3
"""Native hook adapter for the canonical pre-write claim evaluator."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.prewrite_claim_gate import (  # noqa: E402
    DEFAULT_CACHE_DIR,
    DEFAULT_RECEIPT_PATH,
    HookPayloadError,
    PreWriteMode,
    PreWriteEvaluationError,
    adapt_hook_payload,
    evaluate_prewrite,
    load_prewrite_mode,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, choices=("codex", "claude-code"))
    parser.add_argument("--mode", choices=("off", "observe", "enforce"))
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--json", action="store_true", help="Print the typed decision instead of native hook output.")
    return parser


def _git_root(cwd: str) -> Path:
    completed = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PreWriteEvaluationError(completed.stderr.strip() or "unable to resolve Git worktree")
    return Path(completed.stdout.strip()).resolve()


def _mode(payload: dict[str, Any], explicit: PreWriteMode | None) -> PreWriteMode:
    if explicit is not None:
        return explicit
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        cwd = str(Path.cwd())
    return load_prewrite_mode(_git_root(cwd))


def _native_notice(message: str) -> str:
    return json.dumps({"systemMessage": message}, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload: object = {}
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise HookPayloadError("PreToolUse payload must be a JSON object")
        mode = _mode(payload, args.mode)
        request = adapt_hook_payload(payload, client=args.client)
        kwargs: dict[str, Any] = {
            "mode": mode,
            "receipt_path": args.receipt_path,
            "cache_dir": args.cache_dir,
        }
        if args.claims_dir is not None:
            kwargs["claims_dir"] = args.claims_dir
        decision = evaluate_prewrite(request, **kwargs)
    except (json.JSONDecodeError, HookPayloadError, PreWriteEvaluationError, ValueError) as exc:
        try:
            mode = _mode(payload if isinstance(payload, dict) else {}, args.mode)
        except Exception:
            mode = args.mode or "enforce"
        message = f"Pre-write claim gate could not validate this write: {exc}"
        if args.json:
            print(json.dumps({"ok": False, "mode": mode, "reason_code": "invalid_hook_payload", "error": str(exc)}, sort_keys=True))
        elif mode == "observe":
            print(_native_notice(f"OBSERVE ONLY: {message}"))
        elif mode == "enforce":
            print(message, file=sys.stderr)
        return 2 if mode == "enforce" else 0

    if args.json:
        print(decision.model_dump_json(indent=2))
        return 0
    if decision.decision == "deny":
        detail = ", ".join(decision.details)
        message = f"Pre-write claim denied ({decision.reason_code})"
        if detail:
            message += f": {detail}"
        if decision.recovery:
            message += f". {decision.recovery}"
        print(message, file=sys.stderr)
        return 2
    if decision.decision == "observe_violation":
        print(_native_notice(f"OBSERVE ONLY: pre-write claim violation ({decision.reason_code})."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
