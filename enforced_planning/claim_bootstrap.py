"""Narrow self-service claim mutations for a natively identified agent session.

This module is intentionally not a general lifecycle command proxy. It accepts
only typed claim-registry operations, derives the caller's session identity from
the native runtime, and exposes transactional maintenance and new-local-repository
worktree bootstraps. It never executes caller-supplied shell fragments.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from enforced_planning import coordination_claims, session_contracts, session_lifecycle
from enforced_planning.repository_authority import (
    MaintenanceWorktreeAuthority,
    RepositoryAuthority,
    RepositoryAuthorityError,
    resolve_repository_authority,
    resolve_maintenance_worktree_authority,
)

AgentName = Literal["codex", "claude-code", "openclaw"]
ClaimType = Literal["program", "write", "review", "research"]
ProgressKind = Literal[
    "claim_started",
    "verified_commit",
    "accepted_artifact",
    "new_diagnostic",
    "integration_result",
]


class ClaimBootstrapError(ValueError):
    """A bootstrap request was malformed or exceeded self-service authority."""


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.0"] = "1.0"
    operation: str
    agent: AgentName | None = None
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)

    @field_validator("project", "scope")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must contain non-whitespace text")
        return stripped


class SessionStartOrUpdateRequest(_StrictRequest):
    operation: Literal["session_start_or_update"]
    intent: str = Field(min_length=1)
    claim_type: ClaimType
    repo_root: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    session_name: str = Field(min_length=1)
    broader_goal: str = Field(min_length=1)
    plan_ref: str = Field(min_length=1)
    write_paths: list[str] = Field(default_factory=list)
    read_paths: list[str] = Field(default_factory=list)
    current_phase: str = Field(min_length=1)
    next_action: str | None = None
    parent_scope: str | None = None
    work_graph_path: str | None = None
    work_unit_id: str | None = None
    start_revision: str | None = None

    @field_validator(
        "intent",
        "branch",
        "session_name",
        "broader_goal",
        "plan_ref",
        "current_phase",
    )
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must contain non-whitespace text")
        return stripped

    @field_validator("repo_root", "worktree_path")
    @classmethod
    def _require_absolute_path(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("must be an absolute path")
        return str(path.resolve())

    @field_validator("write_paths", "read_paths")
    @classmethod
    def _validate_repo_paths(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            path = value.strip()
            if not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError("claim paths must be non-empty repo-relative paths without '..'")
            if path not in cleaned:
                cleaned.append(path)
        return cleaned

    @model_validator(mode="after")
    def _validate_claim_shape(self) -> SessionStartOrUpdateRequest:
        if self.claim_type == "write" and not self.write_paths:
            raise ValueError("write claims require at least one write_paths entry")
        if self.plan_ref == "UNPLANNED" and (self.work_graph_path or self.work_unit_id or self.start_revision):
            raise ValueError("UNPLANNED bootstrap cannot carry plan work-unit or start-revision fields")
        return self


class HeartbeatRequest(_StrictRequest):
    operation: Literal["heartbeat"]
    branch: str | None = None
    current_phase: str | None = None


class MaintenanceWorktreeRequest(_StrictRequest):
    operation: Literal["maintenance_worktree"]
    agent: AgentName
    repo_root: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    claim_type: Literal["program"]
    write_paths: list[str] = Field(default_factory=lambda: ["."])

    @field_validator("write_paths")
    @classmethod
    def _validate_write_paths(cls, values: list[str]) -> list[str]:
        if not values or len(values) != len(set(values)):
            raise ValueError("write_paths must contain unique literal repository paths")
        for value in values:
            path = Path(value)
            if (
                not value or value != value.strip() or path.is_absolute()
                or ".." in path.parts or path.as_posix() != value
                or any(char in value for char in "\\:*?[]")
            ):
                raise ValueError("write_paths must be canonical repository-relative literals")
        if "." in values and values != ["."]:
            raise ValueError("whole-repository scope cannot be mixed with narrow paths")
        return values

    @model_validator(mode="after")
    def _validate_target(self) -> MaintenanceWorktreeRequest:
        repo = Path(self.repo_root).expanduser()
        if not repo.is_absolute() or ".." in repo.parts or str(repo.resolve()) != self.repo_root:
            raise ValueError("repo_root must be one canonical absolute path without traversal")
        if self.scope != self.branch:
            raise ValueError("scope must exactly match branch")
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", self.branch) is None
            or self.branch.startswith(("-", "/"))
            or self.branch.endswith(("/", "."))
            or ".." in self.branch
            or "//" in self.branch
        ):
            raise ValueError("branch is not a safe literal Git branch")
        return self


class LocalRepositoryWorktreeRequest(_StrictRequest):
    operation: Literal["local_repository_worktree"]
    agent: AgentName
    repo_root: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    claim_type: Literal["program"]
    write_paths: list[str] = Field(default_factory=lambda: ["."])

    @field_validator("write_paths")
    @classmethod
    def _require_whole_repository_scope(cls, values: list[str]) -> list[str]:
        if values != ["."]:
            raise ValueError("local repository bootstrap requires exact whole-repository scope ['.']")
        return values

    @model_validator(mode="after")
    def _validate_target(self) -> LocalRepositoryWorktreeRequest:
        repo = Path(self.repo_root).expanduser()
        if not repo.is_absolute() or ".." in repo.parts or str(repo.resolve()) != self.repo_root:
            raise ValueError("repo_root must be one canonical absolute path without traversal")
        if self.project != repo.name:
            raise ValueError("project must exactly match the new repository directory name")
        if self.scope != self.branch:
            raise ValueError("scope must exactly match branch")
        if self.branch in {"main", "master"}:
            raise ValueError("local repository work must start on a non-default task branch")
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", self.branch) is None
            or self.branch.startswith(("-", "/"))
            or self.branch.endswith(("/", "."))
            or ".." in self.branch
            or "//" in self.branch
        ):
            raise ValueError("branch is not a safe literal Git branch")
        return self


class ProgressRequest(_StrictRequest):
    operation: Literal["progress"]
    progress_kind: ProgressKind
    evidence_ref: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    expected_quiet_until: str | None = None
    quiet_reason: str | None = None


ClaimBootstrapRequest = Annotated[
    SessionStartOrUpdateRequest
    | HeartbeatRequest
    | ProgressRequest
    | MaintenanceWorktreeRequest
    | LocalRepositoryWorktreeRequest,
    Field(discriminator="operation"),
]
_REQUEST_ADAPTER = TypeAdapter(ClaimBootstrapRequest)
SESSION_TRACKERS_DIR = session_contracts.DEFAULT_SESSION_TRACKERS_DIR
def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _github_repo_from_remote(remote_url: str) -> str:
    """Return owner/repository from an HTTPS, SSH, or SSH-host-alias URL."""

    raw = remote_url.strip().rstrip("/")
    value = ""
    if raw.startswith("https://"):
        parsed = urlparse(raw)
        if (
            parsed.hostname != "github.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            raise ClaimBootstrapError("HTTPS origin must use github.com without embedded credentials")
        value = parsed.path
    elif raw.startswith("ssh://"):
        parsed = urlparse(raw)
        if parsed.username != "git" or not parsed.hostname:
            raise ClaimBootstrapError("SSH origin must use the git user and a GitHub host")
        host = _resolved_ssh_hostname(parsed.hostname)
        if host != "github.com":
            raise ClaimBootstrapError("SSH origin host must resolve to github.com")
        value = parsed.path
    else:
        match = re.fullmatch(r"git@([^:/]+):(.+)", raw)
        if match is None:
            raise ClaimBootstrapError("origin must be an HTTPS or SSH GitHub URL")
        host, value = match.groups()
        if _resolved_ssh_hostname(host) != "github.com":
            raise ClaimBootstrapError("SSH origin host must resolve to github.com")
    value = value.removesuffix(".git").strip("/")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) is None:
        raise ClaimBootstrapError("origin URL does not identify one GitHub owner/repository pair")
    return value


def _resolved_ssh_hostname(host: str) -> str:
    if host == "github.com":
        return host
    configured = subprocess.run(
        ["ssh", "-G", host],
        capture_output=True,
        text=True,
        check=False,
    )
    if configured.returncode != 0:
        raise ClaimBootstrapError(f"unable to resolve SSH origin host alias {host!r}")
    hostnames = [
        line.split(None, 1)[1].strip().casefold()
        for line in configured.stdout.splitlines()
        if line.casefold().startswith("hostname ") and len(line.split(None, 1)) == 2
    ]
    if len(hostnames) != 1:
        raise ClaimBootstrapError(f"SSH origin host alias {host!r} has no unique hostname")
    return hostnames[0]


def _repository_authority(
    repo: Path, *, branch: str | None = None,
) -> RepositoryAuthority | MaintenanceWorktreeAuthority:
    """Inspect repository identity, then delegate policy to the installed adapter."""

    identity = _git(repo, "rev-parse", "--show-toplevel")
    if identity.returncode != 0 or Path(identity.stdout.strip()).resolve() != repo:
        raise ClaimBootstrapError("repo_root is not the canonical Git worktree root")
    remote = _git(repo, "remote", "get-url", "origin")
    if remote.returncode != 0:
        raise ClaimBootstrapError("repository has no readable origin remote")
    remote_url = remote.stdout.strip()
    github_repo = _github_repo_from_remote(remote_url)
    try:
        if branch is not None:
            return resolve_maintenance_worktree_authority(
                repo_root=repo, repository_identity=github_repo,
                remote_url=remote_url, branch=branch,
            )
        return resolve_repository_authority(
            repo_root=repo,
            repository_identity=github_repo,
            remote_url=remote_url,
        )
    except RepositoryAuthorityError as exc:
        raise ClaimBootstrapError(str(exc)) from exc


def _fresh_remote_default_revision(
    repo: Path,
    authority: RepositoryAuthority | MaintenanceWorktreeAuthority,
) -> str:
    """Fetch and resolve the graph-declared remote default before lane creation."""

    advertised = _git(repo, "ls-remote", "--symref", authority.remote_url, "HEAD")
    if advertised.returncode != 0:
        raise ClaimBootstrapError(
            advertised.stderr.strip() or "remote default branch lookup failed before maintenance bootstrap"
        )
    default_lines = [
        line for line in advertised.stdout.splitlines()
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD")
    ]
    if len(default_lines) != 1:
        raise ClaimBootstrapError("origin must advertise exactly one symbolic default branch")
    remote_default = default_lines[0].split("\t", 1)[0].removeprefix("ref: refs/heads/")
    if remote_default != authority.default_branch:
        raise ClaimBootstrapError(
            "Project Graph default branch does not match the fresh origin default: "
            f"{authority.default_branch!r} != {remote_default!r}"
        )
    fetched_ref = f"refs/enforced-planning/bootstrap/{os.getpid()}-{secrets.token_hex(12)}"
    fetched = _git(
        repo,
        "fetch",
        "--no-tags",
        "--no-write-fetch-head",
        "--atomic",
        authority.remote_url,
        f"+refs/heads/{remote_default}:{fetched_ref}",
    )
    if fetched.returncode != 0:
        raise ClaimBootstrapError(
            fetched.stderr.strip() or "fresh remote default fetch failed before maintenance bootstrap"
        )
    resolved = _git(repo, "rev-parse", "--verify", f"{fetched_ref}^{{commit}}")
    revision = resolved.stdout.strip()
    if resolved.returncode != 0 or re.fullmatch(r"[0-9a-f]{40,64}", revision) is None:
        _git(repo, "update-ref", "-d", fetched_ref)
        raise ClaimBootstrapError("fresh remote default did not resolve to one full commit id")
    removed = _git(repo, "update-ref", "-d", fetched_ref, revision)
    if removed.returncode != 0 or _git(repo, "show-ref", "--verify", fetched_ref).returncode == 0:
        raise ClaimBootstrapError("private fetched revision changed concurrently; bootstrap refused")
    return revision


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting ambiguity at every nesting level."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ClaimBootstrapError(f"request-json contains duplicate object key {key!r}")
        result[key] = value
    return result


def parse_request_json(raw_json: str) -> ClaimBootstrapRequest:
    """Parse one strict v1 request; unknown fields, including session_id, fail."""

    try:
        payload = json.loads(raw_json, object_pairs_hook=_reject_duplicate_object_keys)
    except ClaimBootstrapError:
        raise
    except json.JSONDecodeError as exc:
        raise ClaimBootstrapError(f"request-json is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ClaimBootstrapError("request-json must be one JSON object")
    try:
        return _REQUEST_ADAPTER.validate_python(payload)
    except ValueError as exc:
        raise ClaimBootstrapError(str(exc)) from exc


def canonical_script_path(repo_root: Path | None = None) -> Path:
    """Return the one canonical script path accepted by the raw Bash grammar."""

    root = repo_root or Path(__file__).resolve().parents[1]
    return (root / "scripts" / "claim_bootstrap.py").resolve()


def parse_raw_bash_command(
    raw_command: str,
    *,
    script_path: Path | None = None,
) -> ClaimBootstrapRequest:
    """Accept only one uncomposed absolute Python bootstrap command.

    The JSON is enclosed by one shell single-quoted token.  A JSON string that
    needs an apostrophe must encode it as ``\\u0027``; a literal apostrophe
    cannot occur in the accepted raw command.
    """

    if "\n" in raw_command or "\r" in raw_command:
        raise ClaimBootstrapError("claim bootstrap command must be exactly one line")
    canonical = str((script_path or canonical_script_path()).resolve())
    prefix = f"/usr/bin/python3 {canonical} --request-json '"
    if not raw_command.startswith(prefix) or not raw_command.endswith("'"):
        raise ClaimBootstrapError(
            "command must be exactly /usr/bin/python3 <canonical>/scripts/claim_bootstrap.py --request-json '<JSON>'"
        )
    raw_json = raw_command[len(prefix) : -1]
    if "'" in raw_json:
        raise ClaimBootstrapError("JSON apostrophes must be encoded as \\u0027")
    return parse_request_json(raw_json)


def projection_recovery_command(
    *,
    script_path: Path,
    claims_dir: Path,
    projection_path: Path,
) -> str:
    """Render the exact projection refresh command advertised by the gate."""

    return (
        f"/usr/bin/python3 {script_path.expanduser().resolve()} "
        f"--claims-dir {claims_dir.expanduser().resolve()} "
        f"--projection-path {projection_path.expanduser().resolve()}"
    )


def parse_projection_recovery_command(
    raw_command: str,
    *,
    script_path: Path,
    claims_dir: Path,
    projection_path: Path,
) -> None:
    """Accept only the exact installed refresh operation and destinations."""

    expected = projection_recovery_command(
        script_path=script_path,
        claims_dir=claims_dir,
        projection_path=projection_path,
    )
    if raw_command != expected:
        raise ClaimBootstrapError("projection recovery command does not match the exact installed authority paths")


def _native_agent(requested: AgentName | None) -> tuple[AgentName, str]:
    """Resolve one current native runtime and reject borrowed agent identity."""

    strong_markers: dict[AgentName, str] = {
        "codex": os.environ.get("CODEX_THREAD_ID", "").strip(),
        "claude-code": os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip(),
        "openclaw": os.environ.get("OPENCLAW_SESSION_ID", "").strip(),
    }
    detected = [agent for agent, marker in strong_markers.items() if marker]
    if requested is None:
        if len(detected) != 1:
            raise ClaimBootstrapError("agent is required unless exactly one native runtime marker is present")
        agent = detected[0]
    else:
        agent = requested
    session_id = coordination_claims.resolve_session_id(agent)
    if not session_id:
        raise ClaimBootstrapError(f"unable to derive identity from the native {agent} runtime")
    try:
        coordination_claims.validate_native_session_binding(
            agent,
            session_id,
            require_native_marker=True,
        )
    except ValueError as exc:
        raise ClaimBootstrapError(str(exc)) from exc
    return agent, session_id


def _require_self_owned_slot(
    *,
    agent: AgentName,
    session_id: str,
    project: str,
    scope: str,
    allow_absent: bool,
) -> None:
    """Refuse ambiguous, ownerless, or foreign claim-slot mutation."""

    matches = [
        claim for claim in coordination_claims.check_claims(project) if claim.agent == agent and claim.scope == scope
    ]
    if not matches:
        if allow_absent:
            return
        raise ClaimBootstrapError(f"no exact live self-owned claim for {agent} -> {project}:{scope}")
    if len(matches) != 1:
        raise ClaimBootstrapError(f"multiple live claims occupy {project}:{scope}; repair registry identity first")
    owner = matches[0].session_id
    if owner != session_id:
        raise ClaimBootstrapError(
            f"claim slot {project}:{scope} belongs to session {owner or '<missing>'}, "
            f"not current session {session_id}; bootstrap cannot take over another slot"
        )


def execute_request(request: ClaimBootstrapRequest) -> dict[str, Any]:
    """Execute one self-owned claim mutation and return a JSON-safe receipt."""

    agent, session_id = _native_agent(request.agent)

    if isinstance(request, LocalRepositoryWorktreeRequest):
        payload = _execute_local_repository_worktree(request, agent=agent, session_id=session_id)
    elif isinstance(request, MaintenanceWorktreeRequest):
        payload = _execute_maintenance_worktree(request, agent=agent, session_id=session_id)
    elif isinstance(request, SessionStartOrUpdateRequest):
        _require_self_owned_slot(
            agent=agent,
            session_id=session_id,
            project=request.project,
            scope=request.scope,
            allow_absent=True,
        )
        payload = session_lifecycle.start_session(
            agent=agent,
            project=request.project,
            scope=request.scope,
            intent=request.intent,
            repo_root=request.repo_root,
            worktree_path=request.worktree_path,
            branch=request.branch,
            broader_goal=request.broader_goal,
            current_phase=request.current_phase,
            plan_ref=None if request.plan_ref == "UNPLANNED" else request.plan_ref,
            session_id=session_id,
            session_name=request.session_name,
            intended_next_phases=[request.next_action] if request.next_action else None,
            claim_type=request.claim_type,
            write_paths=list(request.write_paths),
            read_paths=list(request.read_paths),
            parent_scope=request.parent_scope,
            work_graph_path=request.work_graph_path,
            work_unit_id=request.work_unit_id,
            start_revision=request.start_revision,
            tracker_dir=SESSION_TRACKERS_DIR,
            allow_unplanned=request.plan_ref == "UNPLANNED",
        )
    elif isinstance(request, HeartbeatRequest):
        _require_self_owned_slot(
            agent=agent,
            session_id=session_id,
            project=request.project,
            scope=request.scope,
            allow_absent=False,
        )
        payload = session_lifecycle.heartbeat_session(
            agent=agent,
            project=request.project,
            scope=request.scope,
            branch=request.branch,
            session_id=session_id,
            current_phase=request.current_phase,
            tracker_dir=SESSION_TRACKERS_DIR,
        )
    elif isinstance(request, ProgressRequest):
        _require_self_owned_slot(
            agent=agent,
            session_id=session_id,
            project=request.project,
            scope=request.scope,
            allow_absent=False,
        )
        claim, event = coordination_claims.record_progress_claims(
            agent=agent,
            project=request.project,
            scope=request.scope,
            progress_kind=request.progress_kind,
            evidence_ref=request.evidence_ref,
            next_action=request.next_action,
            session_id=session_id,
            expected_quiet_until=request.expected_quiet_until,
            quiet_reason=request.quiet_reason,
            require_native_session_binding=True,
        )
        payload = {
            "action": "progress_recorded",
            "project": claim.primary_project(),
            "scope": claim.scope,
            "progress_event": event.model_dump(mode="json"),
        }
    else:  # pragma: no cover - the discriminated request union is exhaustive
        raise ClaimBootstrapError("unsupported claim bootstrap operation")

    return {
        "ok": True,
        "schema_version": "1.0",
        "operation": request.operation,
        "agent": agent,
        "session_id": session_id,
        "project": request.project,
        "scope": request.scope,
        "result": payload,
    }


def _rollback_created_worktree(
    *,
    repo: Path,
    worktree: Path,
    branch: str,
    expected_head: str,
    branch_created: bool,
    created_dirs: list[Path],
) -> list[str]:
    """Remove only the exact, untouched no-checkout lane created by bootstrap."""

    errors: list[str] = []
    listing = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    target_blocks = [
        block.splitlines()
        for block in listing.stdout.split("\n\n")
        if listing.returncode == 0
        and f"worktree {worktree}" in block.splitlines()
    ]
    registered = len(target_blocks) == 1
    target_branch_matches = registered and f"branch refs/heads/{branch}" in target_blocks[0]
    branch_worktrees: list[Path] = []
    for block in listing.stdout.split("\n\n") if listing.returncode == 0 else []:
        lines = block.splitlines()
        path_line = next((line for line in lines if line.startswith("worktree ")), None)
        if path_line and f"branch refs/heads/{branch}" in lines:
            branch_worktrees.append(Path(path_line.removeprefix("worktree ")).resolve())
    foreign_checkouts = [path for path in branch_worktrees if path != worktree]
    branch_head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    branch_unchanged = branch_head.returncode == 0 and branch_head.stdout.strip() == expected_head
    safe_to_delete_branch = listing.returncode == 0 and not registered and not os.path.lexists(worktree)
    if listing.returncode != 0:
        errors.append(listing.stderr.strip() or "worktree registry inspection failed")
    if foreign_checkouts:
        errors.append(
            "branch is checked out by another worktree; preserving it: "
            + ", ".join(str(path) for path in foreign_checkouts)
        )
        safe_to_delete_branch = False
    if registered:
        worktree_head = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        status = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True,
            check=False,
        )
        head_paths = subprocess.run(
            ["git", "-C", str(worktree), "ls-tree", "-r", "--name-only", "-z", expected_head],
            capture_output=True,
            check=False,
        )
        status_entries = [entry for entry in status.stdout.split(b"\0") if entry]
        tracked_paths = [path for path in head_paths.stdout.split(b"\0") if path]
        pristine_no_checkout = (
            status.returncode == 0
            and head_paths.returncode == 0
            and sorted(status_entries) == sorted(b"D  " + path for path in tracked_paths)
        )
        if (
            not branch_created
            or not branch_unchanged
            or not target_branch_matches
            or worktree_head.returncode != 0
            or worktree_head.stdout.strip() != expected_head
            or not pristine_no_checkout
        ):
            errors.append("worktree identity changed; refusing unsafe cleanup")
            safe_to_delete_branch = False
        else:
            removed = subprocess.run(
                [
                    "git", "-c", "core.hooksPath=/dev/null", "-C", str(repo),
                    "worktree", "remove", "--force", str(worktree),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if removed.returncode != 0:
                errors.append(removed.stderr.strip() or "worktree cleanup failed")
                safe_to_delete_branch = False
            else:
                safe_to_delete_branch = not foreign_checkouts
    elif os.path.lexists(worktree):
        errors.append(f"unregistered worktree residue requires inspection: {worktree}")
        safe_to_delete_branch = False

    if branch_created and safe_to_delete_branch:
        deleted = subprocess.run(
            [
                "git", "-c", "core.hooksPath=/dev/null", "-C", str(repo),
                "update-ref", "-d", f"refs/heads/{branch}", expected_head,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if deleted.returncode != 0:
            errors.append(deleted.stderr.strip() or "branch compare-and-delete cleanup failed")
        elif subprocess.run(
            ["git", "-C", str(repo), "show-ref", "--verify", f"refs/heads/{branch}"],
            capture_output=True,
            check=False,
        ).returncode == 0:
            errors.append("branch changed during cleanup; compare-and-delete preserved it")

    for candidate in reversed(created_dirs):
        try:
            candidate.rmdir()
        except OSError:
            continue
    return errors


def _preserve_partial_session_claim_as_blocked(
    *,
    agent: AgentName,
    project: str,
    scope: str,
    session_id: str,
    branch: str,
    worktree: Path,
    failure: Exception,
) -> bool:
    """Preserve and block an exact claim that survived a bootstrap failure."""

    candidates = [
        claim
        for claim in coordination_claims.check_claims(project)
        if claim.scope == scope
    ]
    if not candidates:
        return False
    if len(candidates) != 1:
        return True
    claim = candidates[0]
    expected = {
        "agent": agent,
        "session_id": session_id,
        "branch": branch,
        "worktree_path": str(worktree),
    }
    if any(getattr(claim, key) != value for key, value in expected.items()):
        return True
    claim_file = Path(claim.source_file) if claim.source_file else session_lifecycle._claim_path(agent, project, scope)
    session_lifecycle._apply_claim_payload_updates(
        claim=claim,
        claim_file=claim_file,
        updates={
            "status": "blocked",
            "current_phase": "maintenance-bootstrap-blocked",
            "progress_summary": f"Bootstrap failed after claim persistence: {failure}",
        },
        expected_fields=expected,
    )
    return True


def _remove_pristine_bootstrap_repository(repo: Path, *, expected_head: str | None = None) -> list[str]:
    """Remove only an exact repository created by this failed transaction."""

    if not os.path.lexists(repo):
        return []
    errors: list[str] = []
    if repo.is_symlink() or not repo.is_dir():
        return [f"bootstrap target changed identity; preserving it: {repo}"]
    if expected_head is not None:
        head = _git(repo, "rev-parse", "HEAD")
        status = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        if head.returncode != 0 or head.stdout.strip() != expected_head or status.returncode != 0 or status.stdout:
            return [f"bootstrap repository changed; preserving it: {repo}"]
    for candidate in sorted((repo / "worktrees").glob("**/*"), reverse=True) if (repo / "worktrees").is_dir() else []:
        if candidate.is_dir() and not candidate.is_symlink():
            try:
                candidate.rmdir()
            except OSError:
                break
    try:
        (repo / "worktrees").rmdir()
    except OSError:
        pass
    visible = {path.name for path in repo.iterdir() if path.name != ".git"}
    if visible not in (set(), {".gitignore"}):
        return [f"bootstrap repository contains unexpected paths; preserving it: {repo}"]
    try:
        shutil.rmtree(repo)
    except OSError as exc:
        errors.append(f"bootstrap repository cleanup failed: {exc}")
    return errors


def _execute_local_repository_worktree(
    request: LocalRepositoryWorktreeRequest,
    *,
    agent: AgentName,
    session_id: str,
) -> dict[str, Any]:
    """Initialize one local-only repository and its first claimed task worktree."""

    repo = Path(request.repo_root)
    workspace = Path.cwd().resolve()
    if repo.parent != workspace:
        raise ClaimBootstrapError(
            "new local repository must be one direct child of the command working directory"
        )
    enclosing = _git(workspace, "rev-parse", "--show-toplevel")
    if enclosing.returncode == 0:
        raise ClaimBootstrapError("refusing to create an independent repository inside another Git worktree")
    if os.path.lexists(repo):
        raise ClaimBootstrapError(f"new local repository target already exists: {repo}")
    checked = subprocess.run(
        ["git", "check-ref-format", "--branch", request.branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if checked.returncode != 0:
        raise ClaimBootstrapError("branch is not accepted by git check-ref-format")
    existing_roots = [
        claim
        for claim in coordination_claims.check_claims()
        if claim.is_live() and claim.session_id == session_id and not claim.parent_scope
    ]
    if existing_roots:
        labels = ", ".join(sorted(f"{claim.primary_project()}:{claim.scope}" for claim in existing_roots))
        raise ClaimBootstrapError(
            "local repository bootstrap requires the native session to own zero existing claim roots; "
            f"close or transfer first: {labels}"
        )
    occupied = [
        claim
        for claim in coordination_claims.check_claims(request.project)
        if claim.scope == request.scope and claim.is_live()
    ]
    if occupied:
        raise ClaimBootstrapError(
            f"claim slot already exists for new repository identity {request.project}:{request.scope}"
        )

    initialized = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "init", "-b", "main", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )
    if initialized.returncode != 0:
        cleanup = _remove_pristine_bootstrap_repository(repo)
        detail = f"; {'; '.join(cleanup)}" if cleanup else ""
        raise ClaimBootstrapError((initialized.stderr.strip() or "local repository initialization failed") + detail)
    try:
        (repo / ".gitignore").write_text("/worktrees/\n", encoding="utf-8")
        added = _git(repo, "add", ".gitignore")
        if added.returncode != 0:
            raise ClaimBootstrapError(added.stderr.strip() or "bootstrap .gitignore staging failed")
        committed = subprocess.run(
            [
                "git", "-c", "core.hooksPath=/dev/null",
                "-c", "user.name=Repository Bootstrap",
                "-c", "user.email=repository-bootstrap@localhost",
                "-C", str(repo), "commit", "-m", "Initialize local repository",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if committed.returncode != 0:
            raise ClaimBootstrapError(committed.stderr.strip() or "bootstrap commit failed")
        starting_head_result = _git(repo, "rev-parse", "HEAD")
        if starting_head_result.returncode != 0:
            raise ClaimBootstrapError("bootstrap commit did not resolve to a revision")
        starting_head = starting_head_result.stdout.strip()

        base = repo / "worktrees"
        worktree = base / request.branch
        created_dirs: list[Path] = []
        for candidate in [base, *(base.joinpath(*Path(request.branch).parts[:index])
                                   for index in range(1, len(Path(request.branch).parts)))]:
            if os.path.lexists(candidate):
                if candidate.is_symlink() or not candidate.is_dir():
                    raise ClaimBootstrapError(f"worktree parent changed identity: {candidate}")
                continue
            candidate.mkdir()
            created_dirs.append(candidate)
        created = subprocess.run(
            [
                "git", "-c", "core.hooksPath=/dev/null", "-C", str(repo),
                "worktree", "add", "--no-checkout", "-b", request.branch,
                str(worktree), starting_head,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            raise ClaimBootstrapError(created.stderr.strip() or "local task worktree creation failed")

        goal = f"Initialize local repository: {request.project}"
        session_name = session_contracts.derive_session_name(goal)
        payload = session_lifecycle.start_session(
            agent=agent,
            project=request.project,
            scope=request.scope,
            intent=goal,
            repo_root=str(repo),
            worktree_path=str(worktree),
            branch=request.branch,
            broader_goal=goal,
            current_phase="local-repository-bootstrap",
            plan_ref=None,
            session_id=session_id,
            session_name=session_name,
            claim_type="program",
            write_paths=["."],
            read_paths=[],
            tracker_dir=SESSION_TRACKERS_DIR,
            allow_unplanned=True,
        )
        populated = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-C", str(worktree),
             "checkout", "--force", request.branch],
            capture_output=True,
            text=True,
            check=False,
        )
        if populated.returncode != 0:
            raise ClaimBootstrapError(populated.stderr.strip() or "local task worktree population failed")
        return {
            **payload,
            "local_only": True,
            "default_branch": "main",
            "start_revision": starting_head,
            "authority_scope": {
                "operation": "local_repository_worktree",
                "workspace_root": str(workspace),
                "repo_root": str(repo),
                "branch": request.branch,
            },
        }
    except Exception as exc:
        worktree = repo / "worktrees" / request.branch
        starting_head = locals().get("starting_head")
        cleanup_errors: list[str] = []
        try:
            preserved_claim = _preserve_partial_session_claim_as_blocked(
                agent=agent,
                project=request.project,
                scope=request.scope,
                session_id=session_id,
                branch=request.branch,
                worktree=worktree,
                failure=exc,
            )
        except Exception as cleanup_exc:  # noqa: BLE001 - preserve ambiguous residue
            preserved_claim = True
            cleanup_errors.append(f"claim preservation failed: {cleanup_exc}")
        if not preserved_claim and isinstance(starting_head, str):
            cleanup_errors.extend(_rollback_created_worktree(
                repo=repo,
                worktree=worktree,
                branch=request.branch,
                expected_head=starting_head,
                branch_created=True,
                created_dirs=locals().get("created_dirs", []),
            ))
            if not cleanup_errors:
                cleanup_errors.extend(_remove_pristine_bootstrap_repository(repo, expected_head=starting_head))
        elif not preserved_claim and starting_head is None:
            cleanup_errors.extend(_remove_pristine_bootstrap_repository(repo))
        detail = f"; {'; '.join(cleanup_errors)}" if cleanup_errors else ""
        if preserved_claim:
            raise ClaimBootstrapError(
                f"local repository bootstrap failed after claim persistence; lane preserved for inspection: {exc}{detail}"
            ) from exc
        raise ClaimBootstrapError(f"local repository bootstrap failed: {exc}{detail}") from exc


def _execute_maintenance_worktree(
    request: MaintenanceWorktreeRequest,
    *,
    agent: AgentName,
    session_id: str,
) -> dict[str, Any]:
    """Create one unplanned worktree and exact claim as a typed transaction."""

    repo = Path(request.repo_root).resolve()
    authority = _repository_authority(repo, branch=request.branch)
    if request.branch == authority.default_branch:
        raise ClaimBootstrapError("maintenance target must be a non-default branch")
    if request.project != authority.project_id:
        raise ClaimBootstrapError(
            f"project must match provider id {authority.project_id!r} for origin {authority.repository_identity}"
        )
    checked = subprocess.run(
        ["git", "check-ref-format", "--branch", request.branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if checked.returncode != 0:
        raise ClaimBootstrapError("branch is not accepted by git check-ref-format")
    base = repo / "worktrees"
    worktree = base / request.branch
    if os.path.lexists(worktree):
        raise ClaimBootstrapError(f"maintenance worktree already exists: {worktree}")
    branch_exists = subprocess.run(
        ["git", "-C", str(repo), "show-ref", "--verify", f"refs/heads/{request.branch}"],
        capture_output=True,
        check=False,
    ).returncode == 0
    if branch_exists:
        raise ClaimBootstrapError(f"maintenance branch already exists: {request.branch}")
    existing_claims = [
        claim
        for claim in coordination_claims.check_claims(request.project)
        if claim.scope == request.scope and claim.is_live()
    ]
    if existing_claims:
        owners = ", ".join(sorted(f"{claim.agent}:{claim.session_id or '<missing>'}" for claim in existing_claims))
        raise ClaimBootstrapError(
            f"maintenance claim slot already exists for {request.project}:{request.scope}: {owners}"
        )
    existing_roots = [
        claim
        for claim in coordination_claims.check_claims()
        if claim.is_live() and claim.session_id == session_id and not claim.parent_scope
    ]
    if existing_roots:
        labels = ", ".join(sorted(f"{claim.primary_project()}:{claim.scope}" for claim in existing_roots))
        raise ClaimBootstrapError(
            "maintenance bootstrap requires the native session to own zero existing claim roots; "
            f"close or transfer first: {labels}"
        )

    goal = f"Unplanned maintenance: {request.branch.replace('-', ' ').replace('/', ' ')}"
    session_name = session_contracts.derive_session_name(goal)
    contract = session_contracts.SessionContract.build(
        agent=agent,
        project=request.project,
        scope=request.scope,
        intent=goal,
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch=request.branch,
        session_id=session_id,
        broader_goal=goal,
        session_name=session_name,
        allow_unplanned=True,
    )
    tracker_path = session_contracts.session_tracker_path(contract, tracker_dir=SESSION_TRACKERS_DIR)
    if tracker_path.exists():
        raise ClaimBootstrapError(f"maintenance session tracker already exists: {tracker_path}")

    # The network and remote-default freshness boundary precedes every lane
    # artifact. A stale primary checkout must never determine the new branch.
    starting_head = _fresh_remote_default_revision(repo, authority)

    created_dirs: list[Path] = []
    directory = base
    prefix_directories = [base]
    for part in Path(request.branch).parts[:-1]:
        directory = directory / part
        prefix_directories.append(directory)
    for candidate in prefix_directories:
        if os.path.lexists(candidate):
            if candidate.is_symlink() or not candidate.is_dir():
                raise ClaimBootstrapError(
                    f"maintenance worktree parent must be a real directory, not a link or file: {candidate}"
                )
            continue
        candidate.mkdir()
        created_dirs.append(candidate)
    if not worktree.resolve().is_relative_to(base.resolve()):
        raise ClaimBootstrapError("maintenance worktree path escapes the governed repository")

    created_branch = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repo),
            "update-ref",
            f"refs/heads/{request.branch}",
            starting_head,
            "0" * len(starting_head),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if created_branch.returncode != 0:
        for candidate in reversed(created_dirs):
            try:
                candidate.rmdir()
            except OSError:
                pass
        raise ClaimBootstrapError(created_branch.stderr.strip() or "atomic maintenance branch creation failed")
    created = subprocess.run(
        [
            "git", "-c", "core.hooksPath=/dev/null", "-C", str(repo),
            "worktree", "add", "--no-checkout", str(worktree), request.branch,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode != 0:
        cleanup_errors = _rollback_created_worktree(
            repo=repo,
            worktree=worktree,
            branch=request.branch,
            expected_head=starting_head,
            branch_created=True,
            created_dirs=created_dirs,
        )
        detail = f"; {'; '.join(cleanup_errors)}" if cleanup_errors else ""
        raise ClaimBootstrapError((created.stderr.strip() or "git worktree creation failed") + detail)
    try:
        payload = session_lifecycle.start_session(
            agent=agent,
            project=request.project,
            scope=request.scope,
            intent=goal,
            repo_root=str(repo),
            worktree_path=str(worktree),
            branch=request.branch,
            broader_goal=goal,
            current_phase="maintenance",
            plan_ref=None,
            session_id=session_id,
            session_name=session_name,
            claim_type="program",
            write_paths=request.write_paths,
            read_paths=[],
            tracker_dir=SESSION_TRACKERS_DIR,
            allow_unplanned=True,
        )
        populated = subprocess.run(
            [
                "git", "-c", "core.hooksPath=/dev/null", "-C", str(worktree),
                "checkout", "--force", request.branch,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if populated.returncode != 0:
            raise ClaimBootstrapError(
                populated.stderr.strip() or "maintenance worktree population failed after claim creation"
            )
        return {
            **payload,
            "project_graph_id": authority.project_id,
            "github_repo": authority.repository_identity,
            "default_branch": authority.default_branch,
            "start_revision": starting_head,
            "authority_scope": {
                "operation": "maintenance_worktree",
                "repo_root": str(repo),
                "branch": request.branch,
            },
        }
    except Exception as exc:
        cleanup_errors: list[str] = []
        try:
            preserved_claim = _preserve_partial_session_claim_as_blocked(
                agent=agent,
                project=request.project,
                scope=request.scope,
                session_id=session_id,
                branch=request.branch,
                worktree=worktree,
                failure=exc,
            )
        except Exception as cleanup_exc:  # noqa: BLE001 - preserve ambiguous residue
            preserved_claim = True
            cleanup_errors.append(f"claim preservation failed: {cleanup_exc}")
        if preserved_claim:
            detail = f"; {'; '.join(cleanup_errors)}" if cleanup_errors else ""
            raise ClaimBootstrapError(
                "maintenance session creation failed after claim persistence; "
                f"lane preserved for inspection: {exc}{detail}"
            ) from exc
        try:
            coordination_claims.release_claim(
                agent,
                request.project,
                request.scope,
                expected_session_id=session_id,
            )
        except Exception as cleanup_exc:  # noqa: BLE001 - retain recoverable residue details
            cleanup_errors.append(f"claim cleanup failed: {cleanup_exc}")
        try:
            with session_contracts.session_tracker_lock(tracker_path):
                if tracker_path.is_file():
                    tracker = session_contracts.read_session_tracker(tracker_path)
                    tracker_claim = tracker.get("claim")
                    expected_identity = {
                        "agent": agent,
                        "project": request.project,
                        "scope": request.scope,
                        "session_id": session_id,
                        "branch": request.branch,
                        "worktree_path": str(worktree),
                    }
                    if not isinstance(tracker_claim, dict) or any(
                        tracker_claim.get(key) != value for key, value in expected_identity.items()
                    ):
                        raise ValueError("tracker identity changed; refusing unsafe cleanup")
                    tracker_path.unlink()
        except Exception as cleanup_exc:  # noqa: BLE001 - retain recoverable residue details
            cleanup_errors.append(f"tracker cleanup failed: {cleanup_exc}")
        cleanup_errors.extend(
            _rollback_created_worktree(
                repo=repo,
                worktree=worktree,
                branch=request.branch,
                expected_head=starting_head,
                branch_created=True,
                created_dirs=created_dirs,
            )
        )
        detail = f"; {'; '.join(cleanup_errors)}" if cleanup_errors else ""
        raise ClaimBootstrapError(f"maintenance session creation failed: {exc}{detail}") from exc


__all__ = [
    "ClaimBootstrapError",
    "ClaimBootstrapRequest",
    "HeartbeatRequest",
    "LocalRepositoryWorktreeRequest",
    "MaintenanceWorktreeRequest",
    "ProgressRequest",
    "RepositoryAuthority",
    "SessionStartOrUpdateRequest",
    "canonical_script_path",
    "execute_request",
    "parse_projection_recovery_command",
    "parse_raw_bash_command",
    "parse_request_json",
    "projection_recovery_command",
]
