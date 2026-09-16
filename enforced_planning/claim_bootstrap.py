"""Narrow self-service lane controls for a natively identified agent session.

This module is intentionally not a general lifecycle command proxy. It accepts
only typed claim-registry operations, derives the caller's session identity from
the native runtime, and exposes transactional maintenance, new-local-repository
bootstrap, and local integration operations. It never executes caller-supplied
shell fragments.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from enforced_planning import (
    coordination_claims,
    repository_authority,
    session_contracts,
    session_lifecycle,
)
from enforced_planning.repository_authority import (
    MaintenanceWorktreeAuthority,
    RepositoryAuthority,
    RepositoryAuthorityError,
    resolve_maintenance_worktree_authority,
    resolve_repository_authority,
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
    new_files: list[str] = Field(default_factory=list, max_length=16)

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
        if self.new_files:
            if self.operation != "maintenance_worktree":
                raise ValueError("new_files is restricted to direct maintenance worktrees")
            if self.write_paths == ["."]:
                raise ValueError("new_files requires final narrow write_paths")
            if len(self.new_files) != len(set(self.new_files)):
                raise ValueError("new_files must contain unique literal paths")
            for value in self.new_files:
                path = Path(value)
                if (
                    not value
                    or value != value.strip()
                    or path.is_absolute()
                    or len(path.parts) != 1
                    or path.as_posix() != value
                    or value not in self.write_paths
                    or any(char in value for char in "\\:*?[]")
                ):
                    raise ValueError(
                        "new_files must be unique declared top-level write_paths with safe literal names"
                    )
        return self


class GoalWorktreeRequest(MaintenanceWorktreeRequest):
    """Atomic claim/worktree/session bootstrap under explicit goal authority."""

    operation: Literal["goal_worktree"]
    plan_ref: str = Field(pattern=r"^goal:[A-Za-z0-9][A-Za-z0-9._:-]*$")
    broader_goal: str = Field(min_length=1)
    current_phase: str = Field(min_length=1)
    next_action: str | None = Field(default=None, min_length=1)

    @field_validator("broader_goal", "current_phase", "next_action")
    @classmethod
    def _validate_goal_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("goal lifecycle text must not contain surrounding whitespace")
        return value


class DelegatedMaintenanceWorktreeRequest(MaintenanceWorktreeRequest):
    """Parent-authorized creation of one narrow child-owned maintenance lane."""

    operation: Literal["delegate_maintenance_worktree"]
    claim_type: Literal["write"]
    parent_scope: str = Field(min_length=1)
    child_agent_id: str = Field(min_length=1, max_length=200)

    @field_validator("parent_scope", "child_agent_id")
    @classmethod
    def _validate_delegation_identity(cls, value: str) -> str:
        if value != value.strip() or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", value) is None:
            raise ValueError("delegation identities must be canonical non-whitespace literals")
        return value

    @model_validator(mode="after")
    def _validate_delegated_target(self) -> DelegatedMaintenanceWorktreeRequest:
        if self.write_paths == ["."] or "." in self.write_paths:
            raise ValueError("delegated maintenance requires narrow write_paths; whole-repository scope is forbidden")
        if self.parent_scope == self.scope:
            raise ValueError("delegated maintenance cannot name itself as parent")
        return self


class RevokeDelegatedMaintenanceWorktreeRequest(_StrictRequest):
    """Parent cleanup for one pristine delegated lane that never produced work."""

    operation: Literal["revoke_delegated_maintenance_worktree"]
    agent: AgentName
    repo_root: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    parent_scope: str = Field(min_length=1)
    child_agent_id: str = Field(min_length=1, max_length=200)

    @field_validator("parent_scope", "child_agent_id")
    @classmethod
    def _validate_delegation_identity(cls, value: str) -> str:
        if value != value.strip() or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", value) is None:
            raise ValueError("delegation identities must be canonical non-whitespace literals")
        return value

    @model_validator(mode="after")
    def _validate_target(self) -> RevokeDelegatedMaintenanceWorktreeRequest:
        repo = Path(self.repo_root).expanduser()
        if not repo.is_absolute() or ".." in repo.parts or str(repo.resolve()) != self.repo_root:
            raise ValueError("repo_root must be one canonical absolute path without traversal")
        if self.scope != self.branch:
            raise ValueError("scope must exactly match branch")
        if self.parent_scope == self.scope:
            raise ValueError("delegated maintenance cannot name itself as parent")
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


class LocalRepositoryIntegrateRequest(_StrictRequest):
    operation: Literal["local_repository_integrate"]
    agent: AgentName
    repo_root: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    default_branch: Literal["main"] = "main"

    @model_validator(mode="after")
    def _validate_target(self) -> LocalRepositoryIntegrateRequest:
        repo = Path(self.repo_root).expanduser()
        if not repo.is_absolute() or ".." in repo.parts or str(repo.resolve()) != self.repo_root:
            raise ValueError("repo_root must be one canonical absolute path without traversal")
        if self.project != repo.name:
            raise ValueError("project must exactly match the local repository directory name")
        if self.scope != self.branch:
            raise ValueError("scope must exactly match branch")
        if self.branch in {"main", "master"}:
            raise ValueError("integration source must be a non-default task branch")
        if (
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", self.branch) is None
            or self.branch.startswith(("-", "/"))
            or self.branch.endswith(("/", "."))
            or ".." in self.branch
            or "//" in self.branch
        ):
            raise ValueError("branch is not a safe literal Git branch")
        return self


class WorkspaceFileArchiveRequest(_StrictRequest):
    """Move one exact loose workspace file into its recoverable archive tree."""

    operation: Literal["workspace_file_archive"]
    agent: AgentName
    project: Literal["workspace-root"]
    scope: Literal["loose-file-archive"]
    workspace_root: str = Field(min_length=1)
    source: str = Field(min_length=1)
    destination: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_move(self) -> WorkspaceFileArchiveRequest:
        root = Path(self.workspace_root).expanduser()
        if not root.is_absolute() or ".." in root.parts or str(root.resolve()) != self.workspace_root:
            raise ValueError("workspace_root must be one canonical absolute path")
        source = Path(self.source)
        destination = Path(self.destination)
        if (
            source.is_absolute()
            or len(source.parts) != 1
            or source.name in {"", ".", ".."}
            or source.as_posix() != self.source
        ):
            raise ValueError("source must be one direct-child workspace filename")
        if (
            destination.is_absolute()
            or len(destination.parts) < 2
            or destination.parts[0] != "archive"
            or ".." in destination.parts
            or destination.as_posix() != self.destination
        ):
            raise ValueError("destination must be a canonical path beneath archive/")
        return self


class WorkspaceImageCanaryRequest(_StrictRequest):
    """Stage one preserved PNG as the exact image.png watcher canary."""

    operation: Literal["workspace_image_canary"]
    agent: AgentName
    project: Literal["workspace-root"]
    scope: Literal["image-ingest-canary"]
    workspace_root: str = Field(min_length=1)
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_stage(self) -> WorkspaceImageCanaryRequest:
        root = Path(self.workspace_root).expanduser()
        if not root.is_absolute() or ".." in root.parts or str(root.resolve()) != self.workspace_root:
            raise ValueError("workspace_root must be one canonical absolute path")
        source = Path(self.source)
        if (
            source.is_absolute()
            or len(source.parts) < 2
            or source.parts[0] != "archive"
            or ".." in source.parts
            or source.as_posix() != self.source
            or source.suffix.casefold() != ".png"
        ):
            raise ValueError("source must be one canonical archived PNG path")
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
    | RevokeDelegatedMaintenanceWorktreeRequest
    | DelegatedMaintenanceWorktreeRequest
    | GoalWorktreeRequest
    | MaintenanceWorktreeRequest
    | LocalRepositoryWorktreeRequest
    | LocalRepositoryIntegrateRequest
    | WorkspaceFileArchiveRequest
    | WorkspaceImageCanaryRequest,
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


def _canonical_lock_module() -> Any:
    """Load the shipped canonical-lock owner without creating a second implementation."""

    package_root = Path(__file__).resolve().parents[1]
    candidates = (
        package_root / "scripts" / "worktree-coordination" / "canonical_lock.py",
        package_root / "scripts" / "meta" / "canonical_lock.py",
    )
    module_path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if module_path is None:
        rendered = ", ".join(str(candidate) for candidate in candidates)
        raise ClaimBootstrapError(f"canonical lock control is unavailable; checked: {rendered}")
    module_name = f"_claim_bootstrap_canonical_lock_{abs(hash(str(module_path)))}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ClaimBootstrapError(f"canonical lock control cannot be loaded: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _reconcile_canonical_after_claim(
    repo: Path,
    *,
    session_id: str,
) -> dict[str, Any]:
    """Make the canonical checkout match the exact live-claim registry."""

    canonical_lock = _canonical_lock_module()
    report = canonical_lock.reconcile(
        repos=[repo],
        claims_dir=coordination_claims.CLAIMS_DIR,
        session_id=session_id,
    )
    integrity = canonical_lock.verify_lock_integrity(repo)
    if integrity.get("verdict") != canonical_lock.VERDICT_LOCKED:
        raise ClaimBootstrapError(
            "canonical checkout did not become read-only after maintenance lane creation"
        )
    return report


def _finish_canonical_relock(
    canonical_lock: Any,
    repo: Path,
    *,
    justifying_claims: list[str],
    session_id: str,
) -> dict[str, Any]:
    """Finish a relock after integration, including a partial first attempt."""

    first_error: Exception | None = None
    try:
        result = canonical_lock.lock_repo(
            repo,
            justifying_claims=justifying_claims,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 - a partial lock must be repaired before return
        first_error = exc
        result = None

    try:
        if canonical_lock.read_receipt(repo) is not None:
            repair = canonical_lock.relock_repo(repo)
            if result is None:
                result = repair
        elif first_error is not None:
            result = canonical_lock.lock_repo(
                repo,
                justifying_claims=justifying_claims,
                session_id=session_id,
            )
    except Exception as exc:
        detail = f"{first_error}; recovery failed: {exc}" if first_error else str(exc)
        raise ClaimBootstrapError(f"canonical checkout relock failed: {detail}") from exc

    integrity = canonical_lock.verify_lock_integrity(repo)
    if integrity.get("verdict") != canonical_lock.VERDICT_LOCKED:
        detail = f" after initial error: {first_error}" if first_error else ""
        raise ClaimBootstrapError(f"canonical checkout relock remained degraded{detail}")
    if result is None:
        raise ClaimBootstrapError("canonical checkout relock produced no result")
    return result


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


def _validate_existing_session_worktree(request: SessionStartOrUpdateRequest) -> None:
    """Prove an ordinary session upsert names one existing Git checkout."""

    repo = Path(request.repo_root).resolve()
    worktree = Path(request.worktree_path).resolve()
    if not worktree.is_dir():
        raise ClaimBootstrapError("worktree_path is not an existing Git checkout")

    repo_identity = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    worktree_identity = _git(
        worktree,
        "rev-parse",
        "--show-toplevel",
        "--path-format=absolute",
        "--git-common-dir",
        "--abbrev-ref",
        "HEAD",
    )
    if repo_identity.returncode != 0 or worktree_identity.returncode != 0:
        raise ClaimBootstrapError("worktree_path is not an existing Git checkout")
    identity_lines = [line.strip() for line in worktree_identity.stdout.splitlines() if line.strip()]
    if len(identity_lines) != 3:
        raise ClaimBootstrapError("worktree_path Git identity is incomplete")
    observed_worktree, observed_common_dir, observed_branch = identity_lines
    if Path(observed_worktree).resolve() != worktree:
        raise ClaimBootstrapError("worktree_path does not match its Git top-level checkout")
    if Path(observed_common_dir).resolve() != Path(repo_identity.stdout.strip()).resolve():
        raise ClaimBootstrapError("worktree_path belongs to a different Git repository")
    if observed_branch != request.branch:
        raise ClaimBootstrapError("worktree_path is checked out on a different branch")


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


def _delegated_session_id(
    *,
    agent: AgentName,
    child_agent_id: str,
    parent_session_id: str,
) -> str:
    """Normalize one child identity without letting the request change client."""

    value = child_agent_id.strip()
    for prefix in ("codex", "claude-code", "openclaw"):
        marker = f"{prefix}:"
        if value.startswith(marker):
            if prefix != agent:
                raise ClaimBootstrapError(
                    f"delegated child identity {value!r} does not belong to native {agent} client"
                )
            value = value[len(marker):]
            break
    if not value or ":" in value:
        raise ClaimBootstrapError("delegated child identity must contain exactly one native client prefix")
    delegated = f"{agent}:{value}"
    if delegated == parent_session_id:
        raise ClaimBootstrapError("delegated child identity must differ from the parent session")
    return delegated


def _delegating_parent_claim(
    *,
    agent: AgentName,
    project: str,
    parent_scope: str,
    parent_session_id: str,
    repo: Path,
) -> coordination_claims.ClaimRecord:
    """Resolve one healthy unparented program claim owned by the caller."""

    active_claims = coordination_claims.check_claims()
    matches = [
        claim
        for claim in active_claims
        if claim.is_live()
        and claim.agent == agent
        and claim.primary_project() == project
        and claim.scope == parent_scope
        and claim.session_id == parent_session_id
    ]
    if len(matches) != 1:
        raise ClaimBootstrapError(
            "delegated maintenance requires one exact live parent claim owned by the native caller"
        )
    parent = matches[0]
    if parent.claim_type != "program" or parent.parent_scope is not None:
        raise ClaimBootstrapError("delegated maintenance parent must be one unparented program claim")
    if not parent.repo_root or Path(parent.repo_root).expanduser().resolve() != repo:
        raise ClaimBootstrapError("delegated maintenance parent must own the exact target repository")
    status = coordination_claims.claim_runtime_status(parent, active_claims=active_claims)
    if status != "healthy":
        raise ClaimBootstrapError(f"delegated maintenance parent claim is not healthy: {status}")
    return parent


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _configured_workspace_root() -> Path:
    """Resolve the canonical workspace from the hash-pinned authority provider.

    The request may name the root it expects, but it cannot select the authority
    used to verify that claim. The provider config fixes a digest-verified
    Project Meta adapter, whose three configured ``code-*`` homes must agree on
    one parent workspace.
    """

    try:
        provider = repository_authority._load_provider(  # noqa: SLF001
            repository_authority.DEFAULT_PROVIDER_CONFIG
        )
        module_name = f"_claim_bootstrap_workspace_authority_{abs(hash(str(provider)))}"
        module = sys.modules.get(module_name)
        if module is None:
            spec = importlib.util.spec_from_file_location(module_name, provider)
            if spec is None or spec.loader is None:
                raise ClaimBootstrapError("workspace authority provider cannot be loaded")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        raw_paths = getattr(module, "WORKSPACE_HOME_PATHS", None)
    except (OSError, RepositoryAuthorityError) as exc:
        raise ClaimBootstrapError(f"workspace authority is unavailable: {exc}") from exc

    keys = ("code-active", "code-inactive", "code-template")
    if not isinstance(raw_paths, dict) or any(key not in raw_paths for key in keys):
        raise ClaimBootstrapError("workspace authority provider has no complete code workspace homes")
    configured: list[Path] = []
    for key in keys:
        value = raw_paths[key]
        if not isinstance(value, Path):
            raise ClaimBootstrapError(f"workspace authority path {key!r} is not a Path")
        resolved = value.expanduser().resolve()
        if not value.is_absolute() or ".." in value.parts or resolved != value:
            raise ClaimBootstrapError(f"workspace authority path {key!r} is not canonical")
        configured.append(resolved)
    parents = {path.parent for path in configured}
    if len(parents) != 1:
        raise ClaimBootstrapError("configured code workspace homes do not share one root")
    root = parents.pop()
    if not root.is_dir():
        raise ClaimBootstrapError(f"configured workspace root is unavailable: {root}")
    return root


def _workspace_root_for_request(*, requested: str, operation: str) -> Path:
    root = _configured_workspace_root()
    if Path(requested) != root:
        raise ClaimBootstrapError(
            f"{operation} workspace_root does not match the configured workspace root"
        )
    if Path.cwd().resolve() != root:
        raise ClaimBootstrapError(f"{operation} must run from the configured workspace root")
    return root


def _execute_workspace_file_archive(request: WorkspaceFileArchiveRequest) -> dict[str, Any]:
    root = _workspace_root_for_request(
        requested=request.workspace_root,
        operation="workspace_file_archive",
    )

    source = root / request.source
    destination = root / request.destination
    try:
        source_info = source.lstat()
    except OSError as exc:
        raise ClaimBootstrapError(f"source is unavailable: {request.source}: {exc}") from exc
    if source.is_symlink() or not stat.S_ISREG(source_info.st_mode):
        raise ClaimBootstrapError("source must be a non-symlink regular file")
    if os.path.lexists(destination):
        raise ClaimBootstrapError("destination already exists; archive never overwrites")

    archive_root = root / "archive"
    current = root
    for part in destination.parent.relative_to(root).parts:
        current /= part
        if os.path.lexists(current) and (current.is_symlink() or not current.is_dir()):
            raise ClaimBootstrapError(f"archive ancestor is not a real directory: {current}")
    resolved_archive = archive_root.resolve(strict=False)
    if not destination.resolve(strict=False).is_relative_to(resolved_archive):
        raise ClaimBootstrapError("destination escapes the workspace archive root")

    digest = _file_sha256(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError as exc:
        raise ClaimBootstrapError(f"archive link creation failed without moving source: {exc}") from exc
    if _file_sha256(destination) != digest:
        destination.unlink(missing_ok=True)
        raise ClaimBootstrapError("archive digest verification failed; source was retained")
    try:
        source.unlink()
    except OSError as exc:
        raise ClaimBootstrapError(
            f"archive copy is verified but source remains; remove only after inspection: {exc}"
        ) from exc
    return {
        "action": "workspace_file_archived",
        "source": str(source),
        "destination": str(destination),
        "sha256": digest,
        "size_bytes": source_info.st_size,
        "recoverable": True,
    }


def _execute_workspace_image_canary(request: WorkspaceImageCanaryRequest) -> dict[str, Any]:
    root = _workspace_root_for_request(
        requested=request.workspace_root,
        operation="workspace_image_canary",
    )
    source = root / request.source
    destination = root / "image.png"
    current = root
    for part in Path(request.source).parts:
        current /= part
        if current != source and os.path.lexists(current) and current.is_symlink():
            raise ClaimBootstrapError(f"canary source ancestor is a symlink: {current}")
    try:
        source_info = source.lstat()
    except OSError as exc:
        raise ClaimBootstrapError(f"canary source is unavailable: {request.source}: {exc}") from exc
    if source.is_symlink() or not stat.S_ISREG(source_info.st_mode):
        raise ClaimBootstrapError("canary source must be a non-symlink regular PNG")
    if os.path.lexists(destination):
        raise ClaimBootstrapError("image.png already exists; canary never overwrites")

    digest = _file_sha256(source)
    try:
        with source.open("rb") as source_handle, destination.open("xb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ClaimBootstrapError(f"image.png canary staging failed; source was retained: {exc}") from exc
    return {
        "action": "workspace_image_canary_staged",
        "source": str(source),
        "destination": str(destination),
        "sha256": digest,
        "size_bytes": source_info.st_size,
        "source_preserved": True,
    }


def execute_request(request: ClaimBootstrapRequest) -> dict[str, Any]:
    """Execute one self-owned claim mutation and return a JSON-safe receipt."""

    agent, session_id = _native_agent(request.agent)

    if isinstance(request, WorkspaceImageCanaryRequest):
        payload = _execute_workspace_image_canary(request)
    elif isinstance(request, WorkspaceFileArchiveRequest):
        payload = _execute_workspace_file_archive(request)
    elif isinstance(request, LocalRepositoryIntegrateRequest):
        payload = _execute_local_repository_integrate(request, agent=agent, session_id=session_id)
    elif isinstance(request, LocalRepositoryWorktreeRequest):
        payload = _execute_local_repository_worktree(request, agent=agent, session_id=session_id)
    elif isinstance(request, RevokeDelegatedMaintenanceWorktreeRequest):
        payload = _execute_revoke_delegated_worktree(request, agent=agent, session_id=session_id)
    elif isinstance(request, (DelegatedMaintenanceWorktreeRequest, MaintenanceWorktreeRequest)):
        payload = _execute_maintenance_worktree(request, agent=agent, session_id=session_id)
    elif isinstance(request, SessionStartOrUpdateRequest):
        _require_self_owned_slot(
            agent=agent,
            session_id=session_id,
            project=request.project,
            scope=request.scope,
            allow_absent=True,
        )
        _validate_existing_session_worktree(request)
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


def _execute_local_repository_integrate(
    request: LocalRepositoryIntegrateRequest,
    *,
    agent: AgentName,
    session_id: str,
) -> dict[str, Any]:
    """Fast-forward one locked local-only canonical checkout from its sole live lane."""

    repo = Path(request.repo_root).resolve()
    _require_self_owned_slot(
        agent=agent,
        session_id=session_id,
        project=request.project,
        scope=request.scope,
        allow_absent=False,
    )
    matches = [
        claim
        for claim in coordination_claims.check_claims(request.project)
        if claim.is_live()
        and claim.agent == agent
        and claim.session_id == session_id
        and claim.scope == request.scope
    ]
    if len(matches) != 1:
        raise ClaimBootstrapError("local integration requires one exact live self-owned claim")
    claim = matches[0]
    if Path(claim.repo_root or "").expanduser().resolve() != repo:
        raise ClaimBootstrapError("local integration repository does not match the exact live claim")
    if claim.branch != request.branch:
        raise ClaimBootstrapError("local integration branch does not match the exact live claim")
    worktree = Path(claim.worktree_path or "").expanduser().resolve()
    if not worktree.is_dir():
        raise ClaimBootstrapError("local integration worktree is missing")

    repo_claims = [
        candidate
        for candidate in coordination_claims.check_claims()
        if candidate.is_live()
        and candidate.repo_root
        and Path(candidate.repo_root).expanduser().resolve() == repo
    ]
    if len(repo_claims) != 1 or repo_claims[0].session_id != session_id or repo_claims[0].scope != request.scope:
        labels = ", ".join(
            sorted(f"{candidate.agent}:{candidate.scope}" for candidate in repo_claims)
        ) or "none"
        raise ClaimBootstrapError(
            "local integration requires this lane to be the repository's sole live claim; "
            f"found: {labels}"
        )

    remotes = _git(repo, "remote")
    if remotes.returncode != 0:
        raise ClaimBootstrapError(remotes.stderr.strip() or "local repository remote check failed")
    if remotes.stdout.strip():
        raise ClaimBootstrapError("local integration is restricted to repositories with no remotes")
    current_branch = _git(repo, "branch", "--show-current")
    if current_branch.returncode != 0 or current_branch.stdout.strip() != request.default_branch:
        raise ClaimBootstrapError(
            f"canonical checkout must be on {request.default_branch!r} before local integration"
        )
    status = _git(repo, "status", "--porcelain")
    if status.returncode != 0 or status.stdout.strip():
        raise ClaimBootstrapError("canonical checkout must be clean before local integration")
    lane_branch = _git(worktree, "branch", "--show-current")
    if lane_branch.returncode != 0 or lane_branch.stdout.strip() != request.branch:
        raise ClaimBootstrapError("claimed worktree is not on the exact integration branch")
    lane_status = _git(worktree, "status", "--porcelain")
    if lane_status.returncode != 0 or lane_status.stdout.strip():
        raise ClaimBootstrapError("claimed worktree must be clean before local integration")

    canonical_lock = _canonical_lock_module()
    receipt = canonical_lock.read_receipt(repo)
    if receipt is None:
        raise ClaimBootstrapError("canonical checkout has no live lock receipt")
    if request.scope not in receipt.justifying_claims:
        raise ClaimBootstrapError("canonical lock is not justified by the exact live claim")

    before = _git(repo, "rev-parse", request.default_branch)
    lane_head = _git(repo, "rev-parse", request.branch)
    if before.returncode != 0 or lane_head.returncode != 0:
        raise ClaimBootstrapError("local integration revisions could not be resolved")
    before_sha = before.stdout.strip()
    lane_sha = lane_head.stdout.strip()
    if before_sha == lane_sha:
        if canonical_lock.verify_lock_integrity(repo).get("verdict") != canonical_lock.VERDICT_LOCKED:
            canonical_lock.relock_repo(repo)
        if canonical_lock.verify_lock_integrity(repo).get("verdict") != canonical_lock.VERDICT_LOCKED:
            raise ClaimBootstrapError("already-integrated canonical checkout lock is degraded")
        return {
            "action": "already_integrated",
            "repo_root": str(repo),
            "default_branch": request.default_branch,
            "branch": request.branch,
            "before_revision": before_sha,
            "integrated_revision": lane_sha,
            "lock_action": "unchanged",
        }
    ancestor = _git(repo, "merge-base", "--is-ancestor", request.default_branch, request.branch)
    if ancestor.returncode != 0:
        raise ClaimBootstrapError("local integration must be an exact fast-forward")

    integrity = canonical_lock.verify_lock_integrity(repo)
    if integrity.get("verdict") != canonical_lock.VERDICT_LOCKED:
        raise ClaimBootstrapError("canonical checkout lock is degraded before integration")

    canonical_lock.unlock_repo(repo)
    merge: subprocess.CompletedProcess[str] | None = None
    relock: dict[str, Any] | None = None
    try:
        merge = _git(repo, "merge", "--ff-only", request.branch)
    finally:
        relock = _finish_canonical_relock(
            canonical_lock,
            repo,
            justifying_claims=list(receipt.justifying_claims),
            session_id=session_id,
        )
    if merge is None or merge.returncode != 0:
        detail = "" if merge is None else (merge.stderr.strip() or merge.stdout.strip())
        raise ClaimBootstrapError(f"local fast-forward integration failed: {detail or 'unknown Git error'}")
    after = _git(repo, "rev-parse", request.default_branch)
    if after.returncode != 0 or after.stdout.strip() != lane_sha:
        raise ClaimBootstrapError("local integration did not advance canonical main to the lane revision")
    if canonical_lock.verify_lock_integrity(repo).get("verdict") != canonical_lock.VERDICT_LOCKED:
        raise ClaimBootstrapError("canonical checkout was not relocked after local integration")
    return {
        "action": "integrated",
        "repo_root": str(repo),
        "default_branch": request.default_branch,
        "branch": request.branch,
        "before_revision": before_sha,
        "integrated_revision": lane_sha,
        "lock_action": relock.get("action") if relock else None,
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
        pristine_checkout = status.returncode == 0 and not status_entries
        if (
            not branch_created
            or not branch_unchanged
            or not target_branch_matches
            or worktree_head.returncode != 0
            or worktree_head.stdout.strip() != expected_head
            or not (pristine_no_checkout or pristine_checkout)
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
    expected_target = str(worktree)
    if (claim.target_worktree_path or claim.worktree_path) != expected_target:
        return True
    expected = {
        "agent": agent,
        "session_id": session_id,
        "branch": branch,
        "worktree_path": claim.worktree_path,
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
            broad_scope_mode="bounded",
            broad_scope_reason="initialize the intentionally new local repository within this lane lease",
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


def _execute_revoke_delegated_worktree(
    request: RevokeDelegatedMaintenanceWorktreeRequest,
    *,
    agent: AgentName,
    session_id: str,
) -> dict[str, Any]:
    """Remove only a pristine child lane through its exact parent authority."""

    repo = Path(request.repo_root).resolve()
    authority = _repository_authority(repo, branch=request.branch)
    if request.project != authority.project_id:
        raise ClaimBootstrapError(
            f"project must match provider id {authority.project_id!r} for origin {authority.repository_identity}"
        )
    _delegating_parent_claim(
        agent=agent,
        project=request.project,
        parent_scope=request.parent_scope,
        parent_session_id=session_id,
        repo=repo,
    )
    child_session_id = _delegated_session_id(
        agent=agent,
        child_agent_id=request.child_agent_id,
        parent_session_id=session_id,
    )
    matches = [
        claim
        for claim in coordination_claims.check_claims(request.project)
        if claim.scope == request.scope and claim.is_live()
    ]
    if len(matches) != 1:
        raise ClaimBootstrapError("delegated revocation requires one exact live child claim")
    child = matches[0]
    worktree = repo / "worktrees" / request.branch
    expected = {
        "agent": agent,
        "session_id": child_session_id,
        "branch": request.branch,
        "parent_scope": request.parent_scope,
        "claim_type": "write",
        "repo_root": str(repo),
        "worktree_path": str(worktree),
        "plan_ref": session_contracts.UNPLANNED_PLAN_REF,
    }
    if any(getattr(child, field) != value for field, value in expected.items()):
        raise ClaimBootstrapError("delegated child claim identity changed; refusing parent revocation")
    if child.write_paths == ["."] or not child.write_paths or child.broad_scope_mode is not None:
        raise ClaimBootstrapError("delegated child claim is not narrow; refusing parent revocation")
    if not child.start_revision or re.fullmatch(r"[0-9a-f]{40,64}", child.start_revision) is None:
        raise ClaimBootstrapError("delegated child claim lacks an exact retained start revision")
    if not worktree.is_dir() or worktree.is_symlink():
        raise ClaimBootstrapError("delegated child worktree is unavailable or not a real directory")
    status = _git(worktree, "status", "--porcelain", "--untracked-files=normal")
    if status.returncode != 0 or status.stdout.strip():
        raise ClaimBootstrapError("delegated child worktree is not pristine; parent revocation refused")
    tip = _git(worktree, "rev-parse", "HEAD")
    if tip.returncode != 0 or tip.stdout.strip() != child.start_revision:
        raise ClaimBootstrapError("delegated child produced commits; use normal child closeout or handoff")
    if not child.tracker_path:
        raise ClaimBootstrapError("delegated child tracker is unavailable")
    tracker_path = Path(child.tracker_path).expanduser().resolve()
    tracker = session_contracts.read_session_tracker(tracker_path)
    tracker_claim = tracker.get("claim")
    tracker_expected = {
        "agent": agent,
        "project": request.project,
        "scope": request.scope,
        "session_id": child_session_id,
        "branch": request.branch,
        "worktree_path": str(worktree),
    }
    if not isinstance(tracker_claim, dict) or any(
        tracker_claim.get(field) != value for field, value in tracker_expected.items()
    ):
        raise ClaimBootstrapError("delegated child tracker identity changed; refusing parent revocation")

    revoke_delegated = getattr(session_lifecycle, "revoke_delegated_session", None)
    if revoke_delegated is None:
        raise ClaimBootstrapError(
            "delegated lifecycle revocation support is unavailable at this source revision"
        )
    result = revoke_delegated(
        agent=agent,
        project=request.project,
        scope=request.scope,
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch=request.branch,
        parent_scope=request.parent_scope,
        parent_session_id=session_id,
        child_session_id=child_session_id,
        expected_start_revision=child.start_revision,
        tracker_path=str(tracker_path),
        note=f"Pristine delegated lane revoked by parent {request.parent_scope}",
    )
    try:
        lock_reconciliation = _reconcile_canonical_after_claim(
            repo,
            session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 - revocation already completed irreversibly
        return {
            **result,
            "action": "pristine_delegated_lane_revoked_canonical_reconciliation_required",
            "status": "revoked_canonical_reconciliation_required",
            "delegated_session_id": child_session_id,
            "delegated_by_session_id": session_id,
            "parent_scope": request.parent_scope,
            "canonical_lock": None,
            "canonical_lock_reconciliation_required": True,
            "canonical_lock_error": {
                "type": type(exc).__name__,
                "message": str(exc)[:500],
            },
        }
    return {
        **result,
        "action": "pristine_delegated_lane_revoked",
        "status": "revoked",
        "delegated_session_id": child_session_id,
        "delegated_by_session_id": session_id,
        "parent_scope": request.parent_scope,
        "canonical_lock": lock_reconciliation,
        "canonical_lock_reconciliation_required": False,
    }


def _execute_maintenance_worktree(
    request: MaintenanceWorktreeRequest | DelegatedMaintenanceWorktreeRequest | GoalWorktreeRequest,
    *,
    agent: AgentName,
    session_id: str,
) -> dict[str, Any]:
    """Create one maintenance or goal-bound worktree as a typed transaction."""

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
    delegated = isinstance(request, DelegatedMaintenanceWorktreeRequest)
    goal_bound = isinstance(request, GoalWorktreeRequest)
    owner_session_id = session_id
    parent_scope: str | None = None
    claim_type: ClaimType = "program"
    if delegated:
        owner_session_id = _delegated_session_id(
            agent=agent,
            child_agent_id=request.child_agent_id,
            parent_session_id=session_id,
        )
        parent = _delegating_parent_claim(
            agent=agent,
            project=request.project,
            parent_scope=request.parent_scope,
            parent_session_id=session_id,
            repo=repo,
        )
        parent_scope = parent.scope
        claim_type = "write"
        child_claims = [
            claim
            for claim in coordination_claims.check_claims()
            if claim.is_live() and claim.session_id == owner_session_id
        ]
        if child_claims:
            labels = ", ".join(sorted(f"{claim.primary_project()}:{claim.scope}" for claim in child_claims))
            raise ClaimBootstrapError(
                "delegated maintenance requires the child identity to own zero live claims; "
                f"close or transfer first: {labels}"
            )
    else:
        existing_roots = [
            claim
            for claim in coordination_claims.check_claims()
            if claim.is_live() and claim.session_id == session_id and not claim.parent_scope
        ]
        if existing_roots:
            labels = ", ".join(sorted(f"{claim.primary_project()}:{claim.scope}" for claim in existing_roots))
            raise ClaimBootstrapError(
                "worktree bootstrap requires the native session to own zero existing claim roots; "
                f"close or transfer first: {labels}"
            )

    if goal_bound:
        goal = request.broader_goal
    else:
        goal_prefix = "Delegated maintenance" if delegated else "Unplanned maintenance"
        goal = f"{goal_prefix}: {request.branch.replace('-', ' ').replace('/', ' ')}"
    session_name = session_contracts.derive_session_name(goal)
    contract = session_contracts.SessionContract.build(
        agent=agent,
        project=request.project,
        scope=request.scope,
        intent=goal,
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch=request.branch,
        session_id=owner_session_id,
        broader_goal=goal,
        session_name=session_name,
        plan_ref=request.plan_ref if goal_bound else None,
        allow_unplanned=not goal_bound,
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

    new_files = list(request.new_files) if isinstance(request, MaintenanceWorktreeRequest) else []
    bootstrap_broad = request.write_paths == ["."] or bool(new_files)
    bootstrap_kind = "goal-bound" if goal_bound else "maintenance"
    branch_created = False

    def create_git_artifacts() -> None:
        nonlocal branch_created
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
            raise ClaimBootstrapError(created_branch.stderr.strip() or "atomic maintenance branch creation failed")
        branch_created = True
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
            raise ClaimBootstrapError(created.stderr.strip() or "git worktree creation failed")
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
                populated.stderr.strip() or "maintenance worktree population failed after branch creation"
            )

    def start_primary_session(
        *,
        start_revision: str | None,
        write_paths: list[str] | None = None,
        declared_new_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create or refresh the primary claim around the Git artifact boundary."""
        selected_write_paths = request.write_paths if write_paths is None else write_paths
        selected_bootstrap = selected_write_paths == ["."]
        return session_lifecycle.start_session(
            agent=agent,
            project=request.project,
            scope=request.scope,
            intent=goal,
            repo_root=str(repo),
            worktree_path=str(worktree),
            branch=request.branch,
            broader_goal=goal,
            current_phase=request.current_phase if goal_bound else "maintenance-bootstrap",
            plan_ref=request.plan_ref if goal_bound else None,
            session_id=owner_session_id,
            session_name=session_name,
            claim_type=claim_type,
            write_paths=selected_write_paths,
            read_paths=[],
            parent_scope=parent_scope,
            tracker_dir=SESSION_TRACKERS_DIR,
            start_revision=start_revision,
            intended_next_phases=(
                [request.next_action]
                if goal_bound and request.next_action
                else None
            ),
            allow_unplanned=not goal_bound,
            broad_scope_mode="bootstrap" if selected_bootstrap else None,
            broad_scope_reason=(
                f"construct this {bootstrap_kind} lane, then narrow before its first repository write"
                if selected_bootstrap
                else None
            ),
            target_worktree_path=str(worktree) if selected_bootstrap else None,
            new_files=declared_new_files,
            verified_goal_default_revision=starting_head if goal_bound else None,
            verified_maintenance_default_revision=(starting_head if not goal_bound else None),
        )

    try:
        if delegated:
            start_delegated = getattr(session_lifecycle, "start_delegated_session", None)
            if start_delegated is None:
                raise ClaimBootstrapError(
                    "delegated lifecycle support is unavailable at this source revision"
                )
            create_git_artifacts()
            payload = start_delegated(
                agent=agent,
                project=request.project,
                scope=request.scope,
                intent=goal,
                repo_root=str(repo),
                worktree_path=str(worktree),
                branch=request.branch,
                broader_goal=goal,
                current_phase="maintenance-bootstrap",
                parent_scope=request.parent_scope,
                parent_session_id=session_id,
                child_session_id=owner_session_id,
                start_revision=starting_head,
                write_paths=request.write_paths,
                session_name=session_name,
                tracker_dir=SESSION_TRACKERS_DIR,
            )
        else:
            if goal_bound:
                create_git_artifacts()
            payload = start_primary_session(
                start_revision=starting_head,
                declared_new_files=new_files or None,
            )
    except Exception as exc:
        if delegated:
            candidates = [
                claim
                for claim in coordination_claims.check_claims(request.project)
                if claim.scope == request.scope
            ]
            if candidates or tracker_path.exists():
                residue = []
                if candidates:
                    residue.append("delegated claim remains")
                if tracker_path.exists():
                    residue.append("delegated tracker remains")
                detail = "; ".join(residue)
                raise ClaimBootstrapError(
                    "delegated maintenance bootstrap failed with lifecycle residue; "
                    f"intact lane preserved for retry: {exc}; {detail}"
                ) from exc
            cleanup_errors = _rollback_created_worktree(
                repo=repo,
                worktree=worktree,
                branch=request.branch,
                expected_head=starting_head,
                branch_created=branch_created,
                created_dirs=created_dirs,
            )
            detail = f"; {'; '.join(cleanup_errors)}" if cleanup_errors else ""
            disposition = "; lane preserved for inspection" if cleanup_errors else "; transaction rolled back"
            raise ClaimBootstrapError(
                f"delegated maintenance bootstrap failed before claim creation: {exc}{disposition}{detail}"
            ) from exc

        cleanup_errors: list[str] = []
        claim_verified = False
        candidates = [
            claim
            for claim in coordination_claims.check_claims(request.project)
            if claim.scope == request.scope
        ]
        if candidates:
            if len(candidates) != 1:
                cleanup_errors.append("claim cleanup found ambiguous exact scope")
            else:
                claim = candidates[0]
                effective_target = claim.target_worktree_path or claim.worktree_path
                if (
                    claim.agent != agent
                    or claim.session_id != owner_session_id
                    or claim.branch != request.branch
                    or effective_target != str(worktree)
                ):
                    cleanup_errors.append("claim identity changed; refusing unsafe cleanup")
                else:
                    claim_verified = True
        tracker_verified = False
        if not cleanup_errors and tracker_path.is_file():
            try:
                with session_contracts.session_tracker_lock(tracker_path):
                    tracker = session_contracts.read_session_tracker(tracker_path)
                    tracker_claim = tracker.get("claim")
                    expected_identity = {
                        "agent": agent,
                        "project": request.project,
                        "scope": request.scope,
                        "session_id": owner_session_id,
                        "branch": request.branch,
                        "worktree_path": str(worktree),
                    }
                    if not isinstance(tracker_claim, dict) or any(
                        tracker_claim.get(key) != value for key, value in expected_identity.items()
                    ):
                        raise ValueError("tracker identity changed; refusing unsafe cleanup")
                    tracker_verified = True
            except Exception as cleanup_exc:  # noqa: BLE001
                cleanup_errors.append(f"tracker verification failed: {cleanup_exc}")
        if not cleanup_errors:
            try:
                if claim_verified:
                    released, message = coordination_claims.release_claim(
                        agent,
                        request.project,
                        request.scope,
                        expected_session_id=owner_session_id,
                        allow_managed_lane_rollback=True,
                    )
                    if not released:
                        raise ValueError(message)
                if tracker_verified:
                    with session_contracts.session_tracker_lock(tracker_path):
                        tracker_path.unlink(missing_ok=True)
            except Exception as cleanup_exc:  # noqa: BLE001
                cleanup_errors.append(f"claim/tracker cleanup failed: {cleanup_exc}")
        if branch_created and not cleanup_errors:
            cleanup_errors.extend(
                _rollback_created_worktree(
                    repo=repo,
                    worktree=worktree,
                    branch=request.branch,
                    expected_head=starting_head,
                    branch_created=branch_created,
                    created_dirs=created_dirs,
                )
            )
        elif not branch_created:
            for candidate in reversed(created_dirs):
                try:
                    candidate.rmdir()
                except OSError:
                    pass
        detail = f"; {'; '.join(cleanup_errors)}" if cleanup_errors else ""
        disposition = "; intact lane preserved for inspection" if cleanup_errors else "; transaction rolled back"
        raise ClaimBootstrapError(
            f"worktree claim bootstrap failed: {exc}{disposition}{detail}"
        ) from exc

    try:
        if not delegated and not goal_bound:
            create_git_artifacts()
            for relative in new_files:
                target = worktree / relative
                if target.exists() or target.is_symlink():
                    raise ClaimBootstrapError(f"declared new file already exists: {relative}")
                target.touch(mode=0o644, exist_ok=False)
            # The initial claim authorizes Git artifact creation. Once those
            # exact artifacts exist, attach the already-resolved remote-default
            # revision so closeout can measure concurrent arrivals precisely.
            payload = start_primary_session(
                start_revision=starting_head,
                declared_new_files=new_files or None,
            )
        lock_reconciliation = _reconcile_canonical_after_claim(
            repo,
            session_id=session_id,
        )
        payload = {**payload, "canonical_lock": lock_reconciliation}
        return {
            **payload,
            "project_graph_id": authority.project_id,
            "github_repo": authority.repository_identity,
            "default_branch": authority.default_branch,
            "start_revision": starting_head,
            "bootstrap_requires_narrowing": request.write_paths == ["."],
            "authority_scope": {
                "operation": request.operation,
                "repo_root": str(repo),
                "branch": request.branch,
            },
            "delegated_by_session_id": session_id if delegated else None,
            "delegated_session_id": owner_session_id if delegated else None,
            "parent_scope": parent_scope,
            "new_files_created": new_files,
        }
    except Exception as exc:
        if delegated:
            try:
                session_lifecycle.revoke_delegated_session(
                    agent=agent,
                    project=request.project,
                    scope=request.scope,
                    repo_root=str(repo),
                    worktree_path=str(worktree),
                    branch=request.branch,
                    parent_scope=request.parent_scope,
                    parent_session_id=session_id,
                    child_session_id=owner_session_id,
                    expected_start_revision=starting_head,
                    tracker_path=str(tracker_path),
                    note="Delegated maintenance bootstrap rolled back after post-claim failure",
                )
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve the intact delegated lane for retry
                raise ClaimBootstrapError(
                    "delegated maintenance session creation failed after claim creation: "
                    f"{exc}; delegated revoke failed: {cleanup_exc}; intact lane preserved for retry"
                ) from exc
            raise ClaimBootstrapError(
                f"delegated maintenance session creation failed after claim creation: {exc}; transaction revoked"
            ) from exc

        if goal_bound:
            raise ClaimBootstrapError(
                "goal worktree post-claim reconciliation failed; "
                f"the complete claimed lane remains intact for recovery: {exc}"
            ) from exc

        for relative in new_files:
            target = worktree / relative
            try:
                if target.is_file() and not target.is_symlink() and target.stat().st_size == 0:
                    target.unlink()
            except OSError as cleanup_exc:
                cleanup_errors = [f"new file rollback failed for {relative}: {cleanup_exc}"]
                break
        else:
            cleanup_errors = []
        cleanup_errors.extend(_rollback_created_worktree(
            repo=repo,
            worktree=worktree,
            branch=request.branch,
            expected_head=starting_head,
            branch_created=branch_created,
            created_dirs=created_dirs,
        ))
        tracker_verified = False
        try:
            with session_contracts.session_tracker_lock(tracker_path):
                if tracker_path.is_file():
                    tracker = session_contracts.read_session_tracker(tracker_path)
                    tracker_claim = tracker.get("claim")
                    expected_identity = {
                        "agent": agent,
                        "project": request.project,
                        "scope": request.scope,
                        "session_id": owner_session_id,
                        "branch": request.branch,
                        "worktree_path": str(worktree),
                    }
                    if not isinstance(tracker_claim, dict) or any(
                        tracker_claim.get(key) != value for key, value in expected_identity.items()
                    ):
                        raise ValueError("tracker identity changed; refusing unsafe cleanup")
                    tracker_verified = True
        except Exception as cleanup_exc:  # noqa: BLE001 - retain recoverable residue details
            cleanup_errors.append(f"tracker verification failed: {cleanup_exc}")
        if not cleanup_errors:
            try:
                released, message = coordination_claims.release_claim(
                    agent,
                    request.project,
                    request.scope,
                    expected_session_id=owner_session_id,
                    allow_managed_lane_rollback=True,
                )
                if not released:
                    raise ValueError(message)
                if tracker_verified:
                    with session_contracts.session_tracker_lock(tracker_path):
                        tracker_path.unlink(missing_ok=True)
                canonical_lock = _canonical_lock_module()
                canonical_lock.reconcile(
                    repos=[repo],
                    claims_dir=coordination_claims.CLAIMS_DIR,
                    session_id=session_id,
                )
            except Exception as cleanup_exc:  # noqa: BLE001 - retain recoverable residue details
                cleanup_errors.append(f"claim/tracker cleanup failed: {cleanup_exc}")
        if cleanup_errors:
            try:
                _preserve_partial_session_claim_as_blocked(
                    agent=agent,
                    project=request.project,
                    scope=request.scope,
                    session_id=owner_session_id,
                    branch=request.branch,
                    worktree=worktree,
                    failure=exc,
                )
            except Exception as cleanup_exc:  # noqa: BLE001 - preserve ambiguous residue
                cleanup_errors.append(f"claim preservation failed: {cleanup_exc}")
        detail = f"; {'; '.join(cleanup_errors)}" if cleanup_errors else ""
        disposition = "; lane preserved for inspection" if cleanup_errors else "; transaction rolled back"
        raise ClaimBootstrapError(f"maintenance session creation failed: {exc}{disposition}{detail}") from exc


__all__ = [
    "ClaimBootstrapError",
    "ClaimBootstrapRequest",
    "DelegatedMaintenanceWorktreeRequest",
    "GoalWorktreeRequest",
    "HeartbeatRequest",
    "LocalRepositoryWorktreeRequest",
    "MaintenanceWorktreeRequest",
    "ProgressRequest",
    "RepositoryAuthority",
    "RevokeDelegatedMaintenanceWorktreeRequest",
    "SessionStartOrUpdateRequest",
    "canonical_script_path",
    "execute_request",
    "parse_projection_recovery_command",
    "parse_raw_bash_command",
    "parse_request_json",
    "projection_recovery_command",
]
