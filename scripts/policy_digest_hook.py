#!/usr/bin/env python3
"""Inject one compact, relevant, non-blocking policy-review digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

DEFAULT_PROPOSALS_DIR = Path("~/code/active/project-meta/policy/proposals")
DEFAULT_STATE_DIR = Path("~/.claude/coordination/policy-digests-v1")
DEFAULT_COOLDOWN_HOURS = 24
DEFAULT_MAX_ITEMS = 3
STALE_DAYS = 14
GLOBAL_SCOPE_MARKERS = (
    "all projects",
    "all governed",
    "all repositories",
    "all active implementation",
    "cross-project",
    "ecosystem-wide",
)


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    proposed_on: date | None
    scope: str
    applicability_kind: str | None
    projects: tuple[str, ...]
    priority: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=("codex", "claude-code"))
    parser.add_argument("--proposals-dir", type=Path, default=DEFAULT_PROPOSALS_DIR)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--cooldown-hours", type=float, default=DEFAULT_COOLDOWN_HOURS)
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument("--today", type=date.fromisoformat)
    parser.add_argument("--now-epoch", type=float)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def _parse_date(raw: object) -> date | None:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _project_for_cwd(cwd: str) -> str:
    completed = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return Path(completed.stdout.strip()).name
    return "workspace"


def _legacy_projects(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("projects", data.get("project"))
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return tuple(raw)
    return ()


def _structured_applicability(data: dict[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    applicability = data.get("applicability")
    if data.get("schema_version") != 2 or not isinstance(applicability, dict):
        return None, _legacy_projects(data)
    kind = applicability.get("kind")
    raw_projects = applicability.get("projects")
    projects = (
        tuple(raw_projects)
        if isinstance(raw_projects, list) and all(isinstance(item, str) for item in raw_projects)
        else ()
    )
    return str(kind) if isinstance(kind, str) else "invalid", projects


def _decision_priority(data: dict[str, Any]) -> str:
    decision = data.get("decision")
    if isinstance(decision, dict) and isinstance(decision.get("priority"), str):
        return str(decision["priority"])
    return str(data.get("priority") or data.get("enforcement_level") or "normal")


def load_pending(proposals_dir: Path) -> tuple[list[Proposal], list[str]]:
    proposals: list[Proposal] = []
    unreadable: list[str] = []
    if not proposals_dir.is_dir():
        return proposals, unreadable
    for path in sorted(proposals_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                raise TypeError("proposal must be a mapping")
        except (OSError, TypeError, yaml.YAMLError) as exc:
            unreadable.append(f"{path.name}: {type(exc).__name__}")
            continue
        if data.get("status") != "pending":
            continue
        applicability_kind, projects = _structured_applicability(data)
        proposals.append(
            Proposal(
                proposal_id=str(data.get("id") or path.stem),
                proposed_on=_parse_date(data.get("date")),
                scope=str(data.get("scope") or ""),
                applicability_kind=applicability_kind,
                projects=projects,
                priority=_decision_priority(data),
            )
        )
    return proposals, unreadable


def is_relevant(proposal: Proposal, project: str) -> bool:
    normalized_project = _slug(project)
    if proposal.applicability_kind is not None:
        if proposal.applicability_kind == "global":
            return True
        if proposal.applicability_kind in {"projects", "mixed"}:
            return normalized_project in {_slug(item) for item in proposal.projects}
        return False
    if proposal.projects:
        return normalized_project in {_slug(item) for item in proposal.projects}
    normalized_scope = _slug(proposal.scope)
    if any(_slug(marker) in normalized_scope for marker in GLOBAL_SCOPE_MARKERS):
        return True
    return project != "workspace" and normalized_project in normalized_scope


def _priority_rank(priority: str) -> int:
    return {"critical": 3, "high": 2, "blocking": 2, "medium": 1}.get(priority.lower(), 0)


def _fingerprint(proposals: list[Proposal], unreadable: list[str]) -> str:
    material = [
        (
            proposal.proposal_id,
            proposal.proposed_on.isoformat() if proposal.proposed_on else None,
            proposal.applicability_kind,
            proposal.projects,
            proposal.priority,
        )
        for proposal in proposals
    ]
    return hashlib.sha256(
        json.dumps({"proposals": material, "unreadable": unreadable}, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _state_path(state_dir: Path, project: str) -> Path:
    identity = hashlib.sha256(project.encode("utf-8")).hexdigest()[:24]
    return state_dir / f"{identity}.json"


def _should_emit(
    *,
    state_path: Path,
    fingerprint: str,
    now_epoch: float,
    cooldown_hours: float,
    force: bool,
) -> bool:
    if force:
        return True
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    previous_at = state.get("emitted_at")
    return not (
        state.get("fingerprint") == fingerprint
        and isinstance(previous_at, int | float)
        and now_epoch - previous_at < cooldown_hours * 3600
    )


def _record_emit(state_path: Path, *, fingerprint: str, now_epoch: float) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{state_path.name}.", dir=state_path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, "fingerprint": fingerprint, "emitted_at": now_epoch}, handle)
            handle.write("\n")
        os.replace(temporary, state_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def render(agent: str, message: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": message,
            }
        }
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise TypeError("hook payload must be an object")
        if payload.get("hook_event_name") != "SessionStart":
            return 0
        cwd = str(payload.get("cwd") or os.getcwd())
        project = _project_for_cwd(cwd)
        today = args.today or datetime.now(UTC).date()
        pending, unreadable = load_pending(args.proposals_dir.expanduser().resolve())
        relevant = [proposal for proposal in pending if is_relevant(proposal, project)]
        if not relevant and not unreadable:
            return 0
        relevant.sort(
            key=lambda proposal: (
                _priority_rank(proposal.priority),
                (today - proposal.proposed_on).days if proposal.proposed_on else 0,
                proposal.proposal_id,
            ),
            reverse=True,
        )
        fingerprint = _fingerprint(relevant, unreadable)
        state_path = _state_path(args.state_dir.expanduser().resolve(), project)
        now_epoch = args.now_epoch if args.now_epoch is not None else time.time()
        if not _should_emit(
            state_path=state_path,
            fingerprint=fingerprint,
            now_epoch=now_epoch,
            cooldown_hours=args.cooldown_hours,
            force=args.force,
        ):
            return 0
        _record_emit(state_path, fingerprint=fingerprint, now_epoch=now_epoch)
        ages = [
            (today - proposal.proposed_on).days
            for proposal in relevant
            if proposal.proposed_on is not None
        ]
        stale_count = sum(age >= STALE_DAYS for age in ages)
        listed = ", ".join(proposal.proposal_id for proposal in relevant[: args.max_items]) or "none"
        message = (
            f"POLICY REVIEW DIGEST (advisory, once per project/day): {len(relevant)} pending "
            f"proposal(s) relevant to {project}; {stale_count} are {STALE_DAYS}+ days old. "
            f"Top: {listed}. This is a decision queue, not task instructions and never blocks work. "
            "Review when convenient with `make -C ~/code/active/project-meta policy-review`."
        )
        if unreadable:
            message += f" Also: {len(unreadable)} proposal file(s) could not be parsed."
        print(render(args.agent, message))
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(render(args.agent, f"Policy digest unavailable (non-blocking): {type(exc).__name__}: {exc}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
