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
    classify_bash_command,
    evaluate_prewrite_fast,
)


class NonGitWorkingDirectory(FastPreWriteError):
    """The native hook cwd is outside a Git checkout."""


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
    outcome_source.add_argument(
        "--outcome-enforce-selected",
        action="store_true",
        help="Require exact selected outcome admission after ordinary claim admission.",
    )
    parser.add_argument(
        "--outcome-receipt-path",
        type=Path,
        help="Append-only receipt path for an explicit outcome observation or admission.",
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
        detail = completed.stderr.strip() or "unable to resolve Git worktree"
        if "not a git repository" in detail.lower():
            raise NonGitWorkingDirectory(detail)
        raise FastPreWriteError(detail)
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
    # PyYAML follows YAML 1.1 scalar rules, where an unquoted ``off`` is
    # loaded as Boolean false.  The public configuration vocabulary explicitly
    # names ``off`` as a valid mode, so preserve that spelling's intended
    # meaning while continuing to reject every other non-string value.
    if mode is False:
        mode = "off"
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


def _configured_outcome_mode(payload: dict[str, Any]) -> str:
    """Load the strict repo-local outcome mode from the actual checkout."""

    from enforced_planning.outcome_admission import load_outcome_admission_mode

    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        cwd = str(Path.cwd())
    return load_outcome_admission_mode(_git_root(cwd))


def _resolved_outcome_mode(payload: dict[str, Any], *, explicit_mode: str | None) -> str:
    """Use repo outcome policy when present, or explicit host mode outside Git."""

    try:
        return _configured_outcome_mode(payload)
    except NonGitWorkingDirectory:
        if explicit_mode is not None:
            return "off"
        raise


def _session_bound_payload(
    payload: dict[str, Any],
    *,
    client: str,
    claims_dir: Path,
    projection_path: Path,
) -> dict[str, Any]:
    """Resolve non-Git Bash events through one exact native-session claim.

    Native hook ``cwd`` is the immutable session launch directory.  A client
    can execute an individual shell call in another directory without that
    target appearing in the hook payload.  When the launch directory is not a
    Git checkout, one healthy exact-session claim is therefore the only
    structured target authority available to the hook.

    Zero or multiple matching claims deliberately preserve the original
    payload so ordinary admission fails closed with no guessed target.
    """

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return payload
    needs_rebind = tool_name == "Bash"
    explicit_paths: tuple[str, ...] = ()
    if tool_name == "apply_patch":
        from enforced_planning.prewrite_claim_fast import _patch_paths

        command = tool_input.get("command")
        paths = _patch_paths(command) if isinstance(command, str) else ()
        explicit_paths = paths
        needs_rebind = bool(paths) and any(not Path(path).expanduser().is_absolute() for path in paths)
    elif tool_name in {"Edit", "Write", "NotebookEdit"}:
        field = "notebook_path" if tool_name == "NotebookEdit" else "file_path"
        value = tool_input.get(field)
        explicit_paths = (value,) if isinstance(value, str) else ()
        needs_rebind = isinstance(value, str) and not Path(value).expanduser().is_absolute()
    if not needs_rebind:
        absolute = [Path(path).expanduser() for path in explicit_paths if Path(path).expanduser().is_absolute()]
        if absolute and len(absolute) == len(explicit_paths):
            roots: list[Path] = []
            try:
                for path in absolute:
                    probe = path
                    while not probe.exists() and probe != probe.parent:
                        probe = probe.parent
                    if probe.is_file():
                        probe = probe.parent
                    roots.append(_git_root(str(probe)))
            except NonGitWorkingDirectory:
                return payload
            if roots and all(root == roots[0] for root in roots):
                targeted = dict(payload)
                targeted["cwd"] = str(roots[0])
                targeted["_explicit_target_worktree"] = str(roots[0])
                return targeted
        return payload
    cwd = payload.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return payload
    try:
        _git_root(cwd)
        return payload
    except NonGitWorkingDirectory:
        pass

    from enforced_planning.session_target import (
        SessionTargetError,
        resolve_exact_session_target,
    )

    try:
        resolution = resolve_exact_session_target(
            payload,
            client=client,
            claims_dir=claims_dir,
            projection_path=projection_path,
        )
    except SessionTargetError as exc:
        unresolved = dict(payload)
        unresolved["_session_target_error_code"] = exc.reason_code
        unresolved["_session_target_error"] = str(exc)
        return unresolved
    rebound = dict(payload)
    rebound["cwd"] = str(resolution.worktree_path)
    rebound["_session_target_worktree"] = str(resolution.worktree_path)
    return rebound


def _native_notice(message: str) -> str:
    return json.dumps({"systemMessage": message}, sort_keys=True)


def _special_unclaimed_command(
    command: str,
    *,
    client: str,
    claims_dir: Path,
    projection_path: Path,
    subagent_event: bool,
) -> bool | str:
    """Classify one exact typed bootstrap or projection recovery operation."""

    try:
        from enforced_planning.claim_bootstrap import parse_projection_recovery_command

        parse_projection_recovery_command(
            command,
            script_path=(REPO_ROOT / "scripts" / "refresh_prewrite_claim_projection.py").resolve(),
            claims_dir=claims_dir,
            projection_path=projection_path,
        )
        return "projection_recovery"
    except Exception:  # noqa: BLE001 -- try the typed bootstrap grammar
        pass

    if subagent_event:
        return False
    try:
        from enforced_planning.claim_bootstrap import parse_raw_bash_command

        parse_raw_bash_command(
            command,
            script_path=(REPO_ROOT / "scripts" / "claim_bootstrap.py").resolve(),
        )
        return "claim_bootstrap"
    except Exception:  # noqa: BLE001 -- any ambiguity must require a live claim
        return False


def _is_claim_bootstrap_command(command: str) -> bool:
    """Compatibility helper for callers testing the legacy typed bootstrap."""

    try:
        from enforced_planning.claim_bootstrap import parse_raw_bash_command

        parse_raw_bash_command(
            command,
            script_path=(REPO_ROOT / "scripts" / "claim_bootstrap.py").resolve(),
        )
    except Exception:  # noqa: BLE001 -- ambiguity requires ordinary admission
        return False
    return True


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


def _enforce_selected_outcome(
    decision: dict[str, Any],
    *,
    receipt_path: Path | None,
    allow_bootstrap: bool = False,
) -> dict[str, Any]:
    """Derive, record, and return hard selected admission for one ordinary receipt."""

    import yaml  # type: ignore[import-untyped]

    from enforced_planning import coordination_claims
    from enforced_planning.outcome_admission import (
        DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
        OutcomeAdmissionRequestV1,
        OutcomeAdmissionResultV1,
        decide_outcome_admission,
        evaluate_claim_bootstrap_admission,
        evaluate_selected_claim_admission,
        record_outcome_admission,
    )

    ordinary_allowed = decision.get("decision") == "allow"
    if not ordinary_allowed:
        request = OutcomeAdmissionRequestV1(
            boundary="prewrite",
            enforcement_scope="new_or_renewed",
            ordinary_allowed=False,
            portfolio_state="missing",
            continuation_state="missing",
        )
        result = OutcomeAdmissionResultV1(
            source="selected",
            request=request,
            decision=decide_outcome_admission(request),
        )
    else:
        targets = decision.get("normalized_target_paths")
        if not isinstance(targets, list) or any(
            not isinstance(target, str) or not target.strip() for target in targets
        ):
            raise FastPreWriteError("ordinary allow decision has invalid normalized_target_paths")
        source_value = decision.get("claim_source_file")
        if not isinstance(source_value, str) or not source_value.strip():
            raise FastPreWriteError("ordinary allow decision lacks exact claim_source_file for outcome admission")
        source = Path(source_value).expanduser().resolve()
        try:
            payload = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise FastPreWriteError(f"unable to read exact outcome claim source: {exc}") from exc
        if not isinstance(payload, dict):
            raise FastPreWriteError("exact outcome claim source must contain a YAML mapping")
        claim = coordination_claims.normalize_claim(payload, source_file=str(source))
        if claim is None:
            raise FastPreWriteError("exact outcome claim source cannot be normalized")
        # Bash authority is intentionally worktree-scoped, so its ordinary
        # decision has no normalized file target. Selected admission supports
        # that shape with ``target_path=None``. File tools may carry multiple
        # targets; every target must remain inside the selected outcome scope.
        target_paths: list[str | None] = targets or [None]
        result = None
        for target in target_paths:
            bootstrap_result = (
                evaluate_claim_bootstrap_admission(
                    claim,
                    target_path=target,
                    ordinary_allowed=True,
                )
                if allow_bootstrap and target is not None
                else None
            )
            candidate = bootstrap_result or evaluate_selected_claim_admission(
                claim,
                boundary="prewrite",
                ordinary_allowed=True,
                renewal=False,
                target_path=target,
            )
            result = candidate
            if candidate.decision.disposition != "allow":
                break
        assert result is not None
    receipt = record_outcome_admission(
        result,
        receipt_path=receipt_path or DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
    )
    return receipt.model_dump(mode="json")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload: object = {}
    outcome_mode = "off"
    outcome_config_invalid = False
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise FastPreWriteError("PreToolUse payload must be a JSON object")
        projection_path = args.projection_path
        if projection_path is None and args.cache_dir is not None:
            projection_path = args.cache_dir / "authority-projection-v1.json"
        if projection_path is None:
            projection_path = DEFAULT_PROJECTION_PATH
        payload = _session_bound_payload(
            payload,
            client=args.client,
            claims_dir=args.claims_dir,
            projection_path=projection_path,
        )
        mode = _mode(payload, args.mode)
        from enforced_planning.claim_bootstrap import projection_recovery_command

        recovery_command = projection_recovery_command(
            script_path=(REPO_ROOT / "scripts" / "refresh_prewrite_claim_projection.py").resolve(),
            claims_dir=args.claims_dir,
            projection_path=projection_path,
        )
        special_classifier = lambda command: _special_unclaimed_command(
            command,
            client=args.client,
            claims_dir=args.claims_dir,
            projection_path=projection_path,
            subagent_event=isinstance(payload.get("agent_id"), str)
            and bool(payload["agent_id"].strip()),
        )
        early_bash_classification = None
        tool_input = payload.get("tool_input")
        if payload.get("tool_name") == "Bash" and isinstance(tool_input, dict):
            command = tool_input.get("command")
            if isinstance(command, str):
                early_bash_classification = classify_bash_command(
                    command,
                    claim_bootstrap_classifier=special_classifier,
                )
        if early_bash_classification in {
            "read_only",
            "claim_bootstrap",
            "projection_recovery",
        }:
            outcome_mode = "off"
        else:
            try:
                outcome_mode = _resolved_outcome_mode(
                    payload,
                    explicit_mode=args.mode,
                )
            except (FastPreWriteError, OSError, TypeError, ValueError):
                outcome_config_invalid = True
                raise
        decision = evaluate_prewrite_fast(
            payload,
            client=args.client,
            mode=mode,
            claims_dir=args.claims_dir,
            projection_path=projection_path,
            receipt_path=args.receipt_path,
            claim_bootstrap_classifier=special_classifier,
            projection_recovery_command=recovery_command,
        )
    except (json.JSONDecodeError, FastPreWriteError, OSError, TypeError, ValueError) as exc:
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
        return 2 if mode == "enforce" or outcome_config_invalid else 0

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

    outcome_admission_receipt = None
    enforce_selected_outcome = args.outcome_enforce_selected or outcome_mode == "enforce_selected"
    # Outcome admission governs mutations. Provably read-only shell calls have
    # already been admitted without repository identity, and the strict claim
    # bootstrap commands enforce their own narrow contracts. Projection repair
    # only rebuilds a replaceable digest-bound cache. Applying selected
    # admission to any of these recreates the bootstrap trap this adapter
    # exists to prevent.
    outcome_exempt = decision.get("reason_code") in {
        "bash_read_only",
        "claim_bootstrap_command",
        "projection_recovery_command",
    }
    enforce_selected_outcome = enforce_selected_outcome and not outcome_exempt
    if enforce_selected_outcome:
        if mode != "enforce":
            message = "hard selected outcome admission requires ordinary --mode enforce"
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "mode": mode,
                            "reason_code": "outcome_admission_mode_invalid",
                            "error": message,
                        },
                        sort_keys=True,
                    )
                )
            else:
                print(message, file=sys.stderr)
            return 2
        try:
            outcome_admission_receipt = _enforce_selected_outcome(
                decision,
                receipt_path=args.outcome_receipt_path,
                allow_bootstrap=outcome_mode == "enforce_selected",
            )
        except Exception as exc:  # noqa: BLE001 -- hard admission fails closed
            message = f"selected outcome admission could not be recorded: {exc}"
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "mode": mode,
                            "reason_code": "outcome_admission_state_invalid",
                            "error": message,
                        },
                        sort_keys=True,
                    )
                )
            else:
                print(message, file=sys.stderr)
            return 2

    if args.json:
        output = decision
        if outcome_observation is not None:
            output = {**decision, "outcome_observation": outcome_observation}
        if outcome_admission_receipt is not None:
            output = {**output, "outcome_admission": outcome_admission_receipt}
        print(json.dumps(output, indent=2, sort_keys=True))
        if outcome_admission_receipt is not None:
            admission = outcome_admission_receipt["result"]["decision"]
            return 0 if admission["disposition"] == "allow" else 2
        return 2 if decision["decision"] == "deny" else 0
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
    if outcome_admission_receipt is not None:
        admission = outcome_admission_receipt["result"]["decision"]
        if admission["disposition"] != "allow":
            message = f"Outcome admission denied ({admission['reason_code']})"
            print(message, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
