#!/usr/bin/env python3
"""Start or refresh one sanctioned session contract."""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from typing import Any


def _bootstrap_package() -> None:
    """Load local package support or the target repo's upstream bootstrap."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    for parent in current.parents:
        helper = parent / "scripts" / "_upstream_enforced_planning.py"
        if helper.is_file():
            if str(helper.parent) not in sys.path:
                sys.path.insert(0, str(helper.parent))
            from _upstream_enforced_planning import bootstrap_upstream_package  # type: ignore[import-not-found]

            bootstrap_upstream_package(current)
            return
    import importlib.util

    if importlib.util.find_spec("enforced_planning") is not None:
        return
    raise RuntimeError("Unable to locate local or upstream enforced_planning support")


_bootstrap_package()

from enforced_planning import session_lifecycle  # noqa: E402


def _supported_start_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    """Retain compatibility with a target's older local lifecycle contract."""

    kwargs: dict[str, Any] = {
        "agent": args.agent,
        "project": args.project,
        "scope": args.scope,
        "intent": args.intent,
        "repo_root": args.repo_root,
        "worktree_path": args.worktree_path,
        "branch": args.branch,
        "broader_goal": args.broader_goal,
        "current_phase": args.current_phase,
        "plan_ref": args.plan,
        "allow_unplanned": args.allow_unplanned,
        "allow_parallel": args.allow_parallel,
        "session_id": args.session_id,
        "session_name": args.session_name,
        "claim_type": args.claim_type,
        "parent_scope": args.parent_scope,
        "broad_scope_mode": args.broad_scope_mode,
        "broad_scope_reason": args.broad_scope_reason,
        "target_worktree_path": args.target_worktree_path,
        "write_paths": args.write_path or None,
        "read_paths": args.read_path or None,
        "work_graph_path": args.work_graph,
        "work_unit_id": args.work_unit_id,
        "start_revision": args.start_revision,
        "plan_repo_root": args.plan_repo_root,
        "plan_start_point": args.plan_start_point,
        "intended_next_phases": args.next_phase,
        "depends_on_repos": args.depends_on,
        "requires_shared_infra_changes": args.requires_shared_infra_changes,
        "stop_conditions": args.stop_condition,
        "notes": args.notes,
        "outcome_selected": args.outcome_selected,
        "outcome_bootstrap_plan": args.outcome_bootstrap_plan,
    }
    if args.outcome_admission_receipt_path is not None:
        kwargs["outcome_admission_receipt_path"] = args.outcome_admission_receipt_path
    supported = inspect.signature(session_lifecycle.start_session).parameters
    if args.start_revision is not None and "start_revision" not in supported:
        raise RuntimeError(
            "Installed session lifecycle does not support revision custody; "
            "synchronize enforced-planning support before starting this lane."
        )
    if (args.plan_repo_root is not None or args.plan_start_point is not None) and not {
        "plan_repo_root",
        "plan_start_point",
    }.issubset(supported):
        raise RuntimeError(
            "Installed session lifecycle does not support external plan-authority custody; "
            "synchronize enforced-planning support before starting this lane."
        )
    if any((args.broad_scope_mode, args.broad_scope_reason, args.target_worktree_path)) and not {
        "broad_scope_mode",
        "broad_scope_reason",
        "target_worktree_path",
    }.issubset(supported):
        raise RuntimeError(
            "Installed session lifecycle does not support explicit broad-scope custody; "
            "synchronize enforced-planning support before starting this lane."
        )
    return {name: value for name, value in kwargs.items() if name in supported}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the complete session-start contract without hidden defaults."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--intent", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--broader-goal", required=True)
    parser.add_argument("--current-phase", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--allow-unplanned", action="store_true")
    parser.add_argument("--allow-parallel", action="store_true")
    parser.add_argument("--session-id")
    parser.add_argument("--session-name")
    parser.add_argument("--claim-type", choices=["program", "write", "review", "research"])
    parser.add_argument("--parent-scope")
    parser.add_argument("--broad-scope-mode", choices=["bounded", "bootstrap"])
    parser.add_argument("--broad-scope-reason")
    parser.add_argument("--target-worktree-path")
    parser.add_argument("--write-path", action="append", default=[])
    parser.add_argument("--read-path", action="append", default=[])
    parser.add_argument("--work-graph")
    parser.add_argument("--work-unit-id")
    parser.add_argument(
        "--start-revision",
        help="Full immutable Git object ID retained by the plan-bound claim and tracker.",
    )
    parser.add_argument(
        "--plan-repo-root",
        help="Absolute canonical repository root for a qualified external plan authority.",
    )
    parser.add_argument(
        "--plan-start-point",
        help="Full immutable plan-authority revision retained by the claim and tracker.",
    )
    parser.add_argument("--next-phase", action="append")
    parser.add_argument("--depends-on", action="append")
    parser.add_argument("--stop-condition", action="append")
    parser.add_argument("--requires-shared-infra-changes", action="store_true", default=None)
    parser.add_argument("--notes")
    outcome = parser.add_mutually_exclusive_group()
    outcome.add_argument(
        "--outcome-selected",
        action="store_true",
        help="Require exact selected outcome admission before session mutation.",
    )
    outcome.add_argument(
        "--outcome-bootstrap-plan",
        type=int,
        help="Require the fixed source-consumer allocation bootstrap for this plan.",
    )
    parser.add_argument(
        "--outcome-admission-receipt-path",
        type=Path,
        help="Override the append-only outcome-admission receipt stream.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


UNPLANNED_RECOVERY_HINT = (
    "Declare the plan binding explicitly: pass a numbered plan with PLAN=<n> through Make "
    '(or --plan "<project>#<n>" when calling this script directly), or declare the lane '
    "unplanned with ALLOW_UNPLANNED=1 through Make (or --allow-unplanned when calling this "
    "script directly). Unplanned work is never allowed by default."
)


def _undeclared_plan_binding_message(args: argparse.Namespace) -> str | None:
    """Return the operator-facing denial when no plan binding was declared."""

    if (args.plan or "").strip() or args.allow_unplanned:
        return None
    if args.outcome_selected or args.outcome_bootstrap_plan is not None:
        # Outcome admission declares its own binding route and is evaluated first.
        return None
    return (
        "session start requires an explicit plan binding for a live session: "
        f"no plan was given for {args.project}:{args.scope} and unplanned work was not allowed.\n"
        + UNPLANNED_RECOVERY_HINT
    )


def _fail(message: str, *, code: str, as_json: bool) -> int:
    """Emit one loud, actionable failure without a bare traceback."""

    if as_json:
        print(json.dumps({"ok": False, "error": {"code": code, "message": message}}, indent=2, sort_keys=True))
    else:
        print(message, file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    """Start the session and expose its initial mailbox state."""
    args = parse_args(argv)
    undeclared = _undeclared_plan_binding_message(args)
    if undeclared is not None:
        return _fail(undeclared, code="plan_binding_undeclared", as_json=args.json)
    try:
        payload = session_lifecycle.start_session(**_supported_start_kwargs(args))
    except session_lifecycle.OutcomeAdmissionDeniedError as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "outcome_admission_denied",
                            "message": str(exc),
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        message = str(exc)
        if "plan_ref is required" in message:
            return _fail(
                f"{message}\n{UNPLANNED_RECOVERY_HINT}",
                code="plan_binding_undeclared",
                as_json=args.json,
            )
        raise
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['action']}: {payload['session_name']} ({payload['broader_goal']}) -> {payload['tracker_path']}"
        )
        print(payload["coordination_mailbox"]["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
