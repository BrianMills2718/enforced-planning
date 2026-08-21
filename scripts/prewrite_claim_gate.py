#!/usr/bin/env python3
"""Dependency-light native hook adapter for canonical pre-write claims."""

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

from enforced_planning.prewrite_claim_fast import (
    DEFAULT_CLAIMS_DIR,
    DEFAULT_PROJECTION_PATH,
    DEFAULT_RECEIPT_PATH,
    FastPreWriteError,
    evaluate_prewrite_fast,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, choices=("codex", "claude-code"))
    parser.add_argument("--mode", choices=("off", "observe", "enforce"))
    parser.add_argument("--claims-dir", type=Path, default=DEFAULT_CLAIMS_DIR)
    parser.add_argument("--projection-path", type=Path)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Compatibility alias: use <dir>/authority-projection-v1.json.",
    )
    parser.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH)
    outcome_source = parser.add_mutually_exclusive_group()
    outcome_source.add_argument(
        "--outcome-scenario",
        type=Path,
        help="Explicit immutable scenario to correlate after the ordinary decision.",
    )
    outcome_source.add_argument(
        "--outcome-selected",
        action="store_true",
        help="Resolve the create-once scenario from the exact claim-linked session tracker.",
    )
    parser.add_argument(
        "--outcome-receipt-path",
        type=Path,
        help="Append-only receipt path for an explicit outcome observation.",
    )
    parser.add_argument("--json", action="store_true", help="Print the decision instead of native hook output.")
    return parser


def _git_root(cwd: str) -> Path:
    completed = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise FastPreWriteError(completed.stderr.strip() or "unable to resolve Git worktree")
    return Path(completed.stdout.strip()).resolve()


def _load_mode(repo_root: Path) -> str:
    import yaml  # type: ignore[import-untyped]

    config_path = repo_root / "meta-process.yaml"
    if not config_path.is_file():
        return "off"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if payload is None:
        return "off"
    if not isinstance(payload, dict):
        raise FastPreWriteError(f"{config_path} must contain a YAML mapping")
    meta_process = payload.get("meta_process", payload)
    if not isinstance(meta_process, dict):
        raise FastPreWriteError("meta-process.yaml meta_process must be a mapping")
    claims = meta_process.get("claims", {})
    if claims is None:
        return "off"
    if not isinstance(claims, dict):
        raise FastPreWriteError("meta-process.yaml claims must be a mapping")
    mode = claims.get("prewrite_mode", "off")
    if mode not in {"off", "observe", "enforce"}:
        raise FastPreWriteError("claims.prewrite_mode must be one of: off, observe, enforce")
    return str(mode)


def _mode(payload: dict[str, Any], explicit: str | None) -> str:
    if explicit is not None:
        return explicit
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        cwd = str(Path.cwd())
    return _load_mode(_git_root(cwd))


def _native_notice(message: str) -> str:
    return json.dumps({"systemMessage": message}, sort_keys=True)


def _observe_outcome(
    decision: dict[str, Any],
    *,
    scenario_path: Path,
    receipt_path: Path | None,
) -> dict[str, Any]:
    """Lazy-load the typed observer after ordinary admission is recorded."""

    try:
        from enforced_planning.outcome_prewrite_observation import (
            DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
            observe_prewrite_outcome,
        )

        record = observe_prewrite_outcome(
            decision,
            scenario_path=scenario_path,
            receipt_path=receipt_path or DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
        )
        return record.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- observation cannot override ordinary admission
        # Observation is deliberately non-authoritative.  Fail visibly without
        # changing the already-recorded ordinary decision or its exit behavior.
        return {
            "schema_version": "1.0.0",
            "record_type": "outcome_prewrite_observation_unrecorded_failure",
            "ordinary_receipt_id": decision.get("receipt_id"),
            "scenario_path": str(scenario_path),
            "disposition": "observation_error",
            "error_code": getattr(exc, "code", type(exc).__name__),
            "error_message": str(exc),
            "ordinary_authority_preserved": True,
            "enforcement_applied": False,
        }


def _observe_selected_outcome(
    decision: dict[str, Any],
    *,
    receipt_path: Path | None,
) -> dict[str, Any]:
    """Lazy-load exact-session selected observation after ordinary admission."""

    try:
        from enforced_planning.outcome_prewrite_observation import (
            DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
            observe_selected_prewrite_outcome,
        )

        record = observe_selected_prewrite_outcome(
            decision,
            receipt_path=receipt_path or DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
        )
        return record.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- observation cannot override ordinary admission
        return {
            "schema_version": "1.0.0",
            "record_type": "outcome_prewrite_observation_unrecorded_failure",
            "ordinary_receipt_id": decision.get("receipt_id"),
            "scenario_path": "<selected-outcome>",
            "disposition": "observation_error",
            "error_code": getattr(exc, "code", type(exc).__name__),
            "error_message": str(exc),
            "ordinary_authority_preserved": True,
            "enforcement_applied": False,
        }


def _outcome_notice(observation: dict[str, Any]) -> str:
    disposition = observation.get("disposition", "observation_error")
    receipt_id = observation.get("ordinary_receipt_id")
    ordinary = observation.get("ordinary")
    if isinstance(ordinary, dict):
        receipt_id = ordinary.get("receipt_id", receipt_id)
    if disposition in {"would_allow", "would_deny"}:
        detail = observation.get("outcome_reason_code", "unknown")
    else:
        detail = observation.get("error_code", "unknown_observation_error")
    return (
        f"OUTCOME OBSERVE ONLY: {disposition} ({detail}) correlated to ordinary "
        f"receipt {receipt_id}; ordinary claim admission remains authoritative."
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload: object = {}
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise FastPreWriteError("PreToolUse payload must be a JSON object")
        mode = _mode(payload, args.mode)
        projection_path = args.projection_path
        if projection_path is None and args.cache_dir is not None:
            projection_path = args.cache_dir / "authority-projection-v1.json"
        if projection_path is None:
            projection_path = DEFAULT_PROJECTION_PATH
        decision = evaluate_prewrite_fast(
            payload,
            client=args.client,
            mode=mode,
            claims_dir=args.claims_dir,
            projection_path=projection_path,
            receipt_path=args.receipt_path,
        )
    except (json.JSONDecodeError, FastPreWriteError, OSError, ValueError) as exc:
        try:
            mode = _mode(payload if isinstance(payload, dict) else {}, args.mode)
        except Exception:  # noqa: BLE001 -- retain the original fail-safe mode resolution
            mode = args.mode or "enforce"
        message = f"Pre-write claim gate could not validate this write: {exc}"
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "mode": mode,
                        "reason_code": "invalid_hook_payload",
                        "error": str(exc),
                    },
                    sort_keys=True,
                )
            )
        elif mode == "observe":
            print(_native_notice(f"OBSERVE ONLY: {message}"))
        elif mode == "enforce":
            print(message, file=sys.stderr)
        return 2 if mode == "enforce" else 0

    outcome_observation = None
    if args.outcome_scenario is not None:
        outcome_observation = _observe_outcome(
            decision,
            scenario_path=args.outcome_scenario,
            receipt_path=args.outcome_receipt_path,
        )
    elif args.outcome_selected:
        outcome_observation = _observe_selected_outcome(
            decision,
            receipt_path=args.outcome_receipt_path,
        )

    if args.json:
        output = decision
        if outcome_observation is not None:
            output = {**decision, "outcome_observation": outcome_observation}
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    outcome_notice = _outcome_notice(outcome_observation) if outcome_observation is not None else None
    if decision["decision"] == "deny":
        if outcome_notice is not None:
            print(_native_notice(outcome_notice))
        detail = ", ".join(decision["details"])
        message = f"Pre-write claim denied ({decision['reason_code']})"
        if detail:
            message += f": {detail}"
        if decision["recovery"]:
            message += f". {decision['recovery']}"
        print(message, file=sys.stderr)
        return 2
    if decision["decision"] == "observe_violation":
        message = f"OBSERVE ONLY: pre-write claim violation ({decision['reason_code']})."
        if outcome_notice is not None:
            message += f" {outcome_notice}"
        print(_native_notice(message))
    elif outcome_notice is not None:
        print(_native_notice(outcome_notice))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
