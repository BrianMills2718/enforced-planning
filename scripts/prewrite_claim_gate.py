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

from enforced_planning.prewrite_claim_fast import (  # noqa: E402
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
    parser.add_argument(
        "--outcome-scenario",
        type=Path,
        help="Explicit immutable continuation scenario to correlate after the ordinary decision.",
    )
    parser.add_argument(
        "--outcome-observation-path",
        type=Path,
        help="Append-only Plan 116 observation ledger; active only with --outcome-scenario.",
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
    *,
    decision: dict[str, Any],
    scenario_path: Path,
    observation_path: Path | None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Lazily evaluate Plan 116 after the ordinary receipt already exists."""

    from enforced_planning.outcome_prewrite_observation import (
        DEFAULT_OUTCOME_PREWRITE_OBSERVATION_PATH,
        OutcomePreWriteObservationError,
        evaluate_and_record_outcome_prewrite,
    )

    try:
        observation = evaluate_and_record_outcome_prewrite(
            prewrite_decision=decision,
            scenario_path=scenario_path,
            observation_path=observation_path or DEFAULT_OUTCOME_PREWRITE_OBSERVATION_PATH,
        )
    except OutcomePreWriteObservationError as exc:
        return None, {"code": exc.code, "message": str(exc)}
    return observation.model_dump(mode="json"), None


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
        except Exception:
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

    outcome_observation: dict[str, Any] | None = None
    outcome_error: dict[str, str] | None = None
    if args.outcome_scenario is not None:
        outcome_observation, outcome_error = _observe_outcome(
            decision=decision,
            scenario_path=args.outcome_scenario,
            observation_path=args.outcome_observation_path,
        )

    if args.json:
        if args.outcome_scenario is None:
            print(json.dumps(decision, indent=2, sort_keys=True))
        else:
            print(
                json.dumps(
                    {
                        "ok": outcome_error is None,
                        "prewrite_decision": decision,
                        "outcome_observation": outcome_observation,
                        "outcome_observation_error": outcome_error,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0

    if args.outcome_scenario is not None:
        if outcome_error is not None:
            outcome_notice = (
                "OBSERVE ONLY: outcome correlation failed "
                f"({outcome_error['code']}): {outcome_error['message']}. "
                "The ordinary pre-write decision remains authoritative."
            )
        else:
            assert outcome_observation is not None
            outcome = outcome_observation["outcome"]
            outcome_notice = (
                "OBSERVE ONLY: outcome continuation "
                f"{outcome['disposition']} ({outcome['reason_code']}). "
                "The ordinary pre-write decision remains authoritative."
            )
    else:
        outcome_notice = None

    if decision["decision"] == "deny":
        detail = ", ".join(decision["details"])
        message = f"Pre-write claim denied ({decision['reason_code']})"
        if detail:
            message += f": {detail}"
        if decision["recovery"]:
            message += f". {decision['recovery']}"
        if outcome_notice:
            message += f". {outcome_notice}"
        print(message, file=sys.stderr)
        return 2
    if decision["decision"] == "observe_violation":
        notice = f"OBSERVE ONLY: pre-write claim violation ({decision['reason_code']})."
        if outcome_notice:
            notice += f" {outcome_notice}"
        print(_native_notice(notice))
    elif outcome_notice:
        print(_native_notice(outcome_notice))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
