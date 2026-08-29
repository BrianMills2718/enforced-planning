"""Resolve an immutable hook launch directory to one exact claimed worktree.

Native hook payloads expose the directory in which the client was launched.
That value is navigation context, not repository authority: per-command shell
workdirs are intentionally absent from the payload.  This module therefore
permits rebinding only through the digest-bound claim projection and only when
one healthy claim belongs to the effective native agent identity.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from enforced_planning.prewrite_claim_fast import (
    LIVE_STATUSES,
    _dynamic_claim_issues,
    _load_projection,
    projection_path_for,
)


class SessionTargetError(ValueError):
    """The hook could not prove one healthy exact-session target."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class SessionTarget:
    """One exact target selected by a healthy projected claim."""

    session_id: str
    repo_root: Path
    worktree_path: Path
    branch: str
    source_file: Path


def effective_session_id(payload: dict[str, Any], client: str) -> str:
    """Return the child agent identity when present, otherwise the session.

    Codex subagent hook events retain the parent's ``session_id`` and carry the
    child's native thread identity in ``agent_id``.  Preferring ``agent_id`` is
    what prevents a child from borrowing the parent's claim or hook state.
    """

    if client not in {"codex", "claude-code"}:
        raise SessionTargetError("unsupported_client", f"unsupported hook client {client!r}")
    raw = payload.get("agent_id")
    if not isinstance(raw, str) or not raw.strip():
        raw = payload.get("session_id")
    if not isinstance(raw, str) or not raw.strip():
        raise SessionTargetError(
            "session_identity_unavailable",
            "hook payload has neither a native agent_id nor session_id",
        )
    value = raw.strip()
    for prefix in ("codex", "claude-code"):
        marker = f"{prefix}:"
        if value.startswith(marker):
            if prefix != client:
                raise SessionTargetError(
                    "client_identity_mismatch",
                    f"hook client {client!r} cannot use identity {value!r}",
                )
            return value
    return f"{client}:{value}"


def resolve_exact_session_target(
    payload: dict[str, Any],
    *,
    client: str,
    claims_dir: Path,
    projection_path: Path | None = None,
) -> SessionTarget:
    """Select exactly one healthy projected claim for the effective identity."""

    session_id = effective_session_id(payload, client)
    resolved_claims = claims_dir.expanduser().resolve()
    resolved_projection = (
        projection_path or projection_path_for(resolved_claims)
    ).expanduser().resolve()
    projection, error = _load_projection(resolved_projection, claims_dir=resolved_claims)
    if projection is None:
        raise SessionTargetError(
            "projection_unavailable_or_stale",
            error or "claim authority projection is unavailable",
        )

    identity_matches = [
        claim
        for claim in projection["claims"]
        if claim["agent"] == client and claim["session_id"] == session_id
    ]
    healthy = [
        claim
        for claim in identity_matches
        if claim["status"] in LIVE_STATUSES
        and not claim["static_issues"]
        and not _dynamic_claim_issues(claim)
    ]
    if not healthy:
        if identity_matches:
            details = sorted(
                {
                    issue
                    for claim in identity_matches
                    for issue in [
                        *(claim["static_issues"] or []),
                        *_dynamic_claim_issues(claim),
                        *([] if claim["status"] in LIVE_STATUSES else ["non_live_status"]),
                    ]
                }
            )
            suffix = f" ({', '.join(details)})" if details else ""
            raise SessionTargetError(
                "claim_not_healthy",
                f"no healthy claim belongs to {session_id}{suffix}",
            )
        raise SessionTargetError(
            "no_exact_session_target",
            f"no healthy claim belongs to {session_id}",
        )
    if len(healthy) != 1:
        lanes = sorted(f"{claim['projects'][0]}:{claim['scope']}" for claim in healthy)
        raise SessionTargetError(
            "ambiguous_exact_session_target",
            f"multiple healthy claims belong to {session_id}: {', '.join(lanes)}",
        )

    claim = healthy[0]
    worktree = Path(claim["worktree_path"]).expanduser().resolve()
    repo_root = Path(claim["repo_root"]).expanduser().resolve()
    if not (worktree / ".git").exists():
        raise SessionTargetError(
            "claim_not_healthy",
            f"claimed worktree is not a Git checkout: {worktree}",
        )
    identity = subprocess.run(
        [
            "git",
            "-C",
            str(worktree),
            "rev-parse",
            "--show-toplevel",
            "--git-common-dir",
            "--abbrev-ref",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = identity.stdout.splitlines() if identity.returncode == 0 else []
    repo_identity = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if len(lines) != 3 or repo_identity.returncode != 0:
        raise SessionTargetError("claim_not_healthy", "claimed Git identity cannot be resolved")
    actual_worktree = Path(lines[0]).expanduser().resolve()
    actual_common = Path(lines[1])
    if not actual_common.is_absolute():
        actual_common = worktree / actual_common
    expected_common = Path(repo_identity.stdout.strip())
    if not expected_common.is_absolute():
        expected_common = repo_root / expected_common
    if (
        actual_worktree != worktree
        or actual_common.resolve() != expected_common.resolve()
        or lines[2] != claim["branch"]
    ):
        raise SessionTargetError(
            "claim_git_identity_mismatch",
            "claimed worktree, common repository, or branch does not match live Git identity",
        )
    return SessionTarget(
        session_id=session_id,
        repo_root=repo_root,
        worktree_path=worktree,
        branch=claim["branch"],
        source_file=Path(claim["source_file"]).expanduser().resolve(),
    )


__all__ = [
    "SessionTarget",
    "SessionTargetError",
    "effective_session_id",
    "resolve_exact_session_target",
]
