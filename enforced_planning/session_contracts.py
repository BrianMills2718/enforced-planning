"""Session bootstrap contract and tracker helpers.

This module defines the split between compact claim metadata that belongs on
the canonical coordination claim and richer tracker-only execution context that
should live in a linked per-session artifact.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

DEFAULT_SESSION_TRACKERS_DIR = Path.home() / ".claude" / "coordination" / "sessions"
SESSION_TRACKER_SCHEMA_VERSION = 3
UNPLANNED_PLAN_REF = "UNPLANNED"

CLAIM_FIELD_NAMES = (
    "agent",
    "project",
    "scope",
    "intent",
    "plan_ref",
    "repo_root",
    "worktree_path",
    "branch",
    "session_id",
    "session_name",
    "broader_goal",
    "tracker_path",
    "start_revision",
    "plan_repo_root",
    "plan_revision",
    "plan_sha256",
)

TRACKER_ONLY_FIELD_NAMES = (
    "current_phase",
    "intended_next_phases",
    "depends_on_repos",
    "requires_shared_infra_changes",
    "stop_conditions",
    "notes",
)

OUTCOME_CUSTODY_TRACKER_FIELDS = (
    "outcome_selection",
    "outcome_progress_transitions",
    "outcome_session_transfers",
    "outcome_selection_transitions",
)


def _require_text(value: str, *, field_name: str) -> str:
    """Return one stripped text field or raise a clear contract error."""

    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def normalize_plan_ref(plan_ref: str | None, *, allow_unplanned: bool = False) -> str:
    """Return a normalized plan marker or fail loud if none was declared."""

    if isinstance(plan_ref, str) and plan_ref.strip():
        return plan_ref.strip()
    if allow_unplanned:
        return UNPLANNED_PLAN_REF
    raise ValueError(
        "plan_ref is required for live sessions. Pass a real numbered plan or explicitly allow unplanned work."
    )


def _clean_string_list(items: list[str] | None) -> list[str]:
    """Return a stable deduplicated string list for tracker serialization."""

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items or []:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def derive_session_name(broader_goal: str) -> str:
    """Derive the canonical session name from the broader goal text."""

    tokens = re.findall(r"[a-z0-9]+", broader_goal.lower())
    if not tokens:
        raise ValueError("broader_goal must contain at least one alphanumeric token")
    return "-".join(tokens)


def validate_session_name(*, session_name: str, broader_goal: str) -> str:
    """Require the session name to match the broader-goal-derived canonical slug."""

    expected = derive_session_name(broader_goal)
    normalized = derive_session_name(session_name)
    if normalized != expected:
        raise ValueError(
            f"session_name must match the broader-goal-derived canonical name '{expected}', not local-task wording"
        )
    return expected


@dataclass(frozen=True)
class SessionContract:
    """Compact session contract fields that belong on the canonical claim."""

    agent: str
    project: str
    scope: str
    intent: str
    plan_ref: str | None
    repo_root: str
    worktree_path: str
    branch: str
    session_id: str
    session_name: str
    broader_goal: str
    tracker_path: str | None = None
    start_revision: str | None = None
    plan_repo_root: str | None = None
    plan_revision: str | None = None
    plan_sha256: str | None = None

    @classmethod
    def build(
        cls,
        *,
        agent: str,
        project: str,
        scope: str,
        intent: str,
        repo_root: str,
        worktree_path: str,
        branch: str,
        session_id: str,
        broader_goal: str,
        plan_ref: str | None = None,
        session_name: str | None = None,
        tracker_path: str | None = None,
        start_revision: str | None = None,
        plan_repo_root: str | None = None,
        plan_revision: str | None = None,
        plan_sha256: str | None = None,
        allow_unplanned: bool = False,
    ) -> SessionContract:
        """Build a validated session contract from bootstrap inputs."""

        broader_goal_text = _require_text(broader_goal, field_name="broader_goal")
        derived_session_name = derive_session_name(broader_goal_text)
        if session_name is None:
            session_name_text = derived_session_name
        else:
            session_name_text = validate_session_name(
                session_name=session_name,
                broader_goal=broader_goal_text,
            )

        if start_revision is not None and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", start_revision) is None:
            raise ValueError("start_revision must be one full lowercase Git object ID")
        plan_binding = (plan_repo_root, plan_revision, plan_sha256)
        if any(value is not None for value in plan_binding) and not all(
            isinstance(value, str) and value.strip() for value in plan_binding
        ):
            raise ValueError("external plan custody requires plan_repo_root, plan_revision, and plan_sha256 together")
        if plan_revision is not None and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", plan_revision) is None:
            raise ValueError("plan_revision must be one full lowercase Git object ID")
        if plan_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", plan_sha256) is None:
            raise ValueError("plan_sha256 must be one lowercase SHA-256 digest")

        return cls(
            agent=_require_text(agent, field_name="agent"),
            project=_require_text(project, field_name="project"),
            scope=_require_text(scope, field_name="scope"),
            intent=_require_text(intent, field_name="intent"),
            plan_ref=normalize_plan_ref(plan_ref, allow_unplanned=allow_unplanned),
            repo_root=_require_text(repo_root, field_name="repo_root"),
            worktree_path=_require_text(worktree_path, field_name="worktree_path"),
            branch=_require_text(branch, field_name="branch"),
            session_id=_require_text(session_id, field_name="session_id"),
            session_name=session_name_text,
            broader_goal=broader_goal_text,
            tracker_path=tracker_path.strip() if isinstance(tracker_path, str) and tracker_path.strip() else None,
            start_revision=start_revision,
            plan_repo_root=(str(Path(plan_repo_root).expanduser().resolve()) if plan_repo_root is not None else None),
            plan_revision=plan_revision,
            plan_sha256=plan_sha256,
        )

    def with_tracker_path(self, tracker_path: str) -> SessionContract:
        """Return the same contract with a concrete tracker path attached."""

        return replace(self, tracker_path=_require_text(tracker_path, field_name="tracker_path"))

    def claim_fields(self) -> dict[str, str]:
        """Return only the claim-critical contract fields."""

        fields = {
            "agent": self.agent,
            "project": self.project,
            "scope": self.scope,
            "intent": self.intent,
            "plan_ref": self.plan_ref or "",
            "repo_root": self.repo_root,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "session_id": self.session_id,
            "session_name": self.session_name,
            "broader_goal": self.broader_goal,
            "tracker_path": self.tracker_path or "",
        }
        if self.start_revision is not None:
            fields["start_revision"] = self.start_revision
        if self.plan_repo_root is not None:
            fields["plan_repo_root"] = self.plan_repo_root
            fields["plan_revision"] = self.plan_revision or ""
            fields["plan_sha256"] = self.plan_sha256 or ""
        return fields


@dataclass(frozen=True)
class SessionTrackerRecord:
    """Human-readable tracker artifact linked from one session contract."""

    contract: SessionContract
    current_phase: str
    intended_next_phases: list[str]
    depends_on_repos: list[str]
    requires_shared_infra_changes: bool
    stop_conditions: list[str]
    notes: str | None
    created_at: str
    updated_at: str
    schema_version: int = SESSION_TRACKER_SCHEMA_VERSION

    def tracker_fields(self) -> dict[str, Any]:
        """Return only the tracker-only execution fields."""

        return {
            "current_phase": self.current_phase,
            "intended_next_phases": self.intended_next_phases,
            "depends_on_repos": self.depends_on_repos,
            "requires_shared_infra_changes": self.requires_shared_infra_changes,
            "stop_conditions": self.stop_conditions,
            "notes": self.notes or "",
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the nested contract/tracker representation for YAML output."""

        return {
            "schema_version": self.schema_version,
            "claim": self.contract.claim_fields(),
            "tracker": self.tracker_fields(),
            "timestamps": {
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            },
        }


def session_contract_schema() -> dict[str, list[str]]:
    """Return the formal split between claim and tracker fields."""

    return {
        "claim_fields": list(CLAIM_FIELD_NAMES),
        "tracker_only_fields": list(TRACKER_ONLY_FIELD_NAMES),
    }


def build_session_tracker(
    *,
    contract: SessionContract,
    current_phase: str,
    intended_next_phases: list[str] | None = None,
    depends_on_repos: list[str] | None = None,
    requires_shared_infra_changes: bool = False,
    stop_conditions: list[str] | None = None,
    notes: str | None = None,
    now: datetime | None = None,
) -> SessionTrackerRecord:
    """Build the linked tracker artifact for one active session contract."""

    timestamp = (now or datetime.now(UTC)).isoformat()
    return SessionTrackerRecord(
        contract=contract,
        current_phase=_require_text(current_phase, field_name="current_phase"),
        intended_next_phases=_clean_string_list(intended_next_phases),
        depends_on_repos=_clean_string_list(depends_on_repos),
        requires_shared_infra_changes=requires_shared_infra_changes,
        stop_conditions=_clean_string_list(stop_conditions),
        notes=notes.strip() if isinstance(notes, str) and notes.strip() else None,
        created_at=timestamp,
        updated_at=timestamp,
        schema_version=(
            SESSION_TRACKER_SCHEMA_VERSION
            if contract.plan_repo_root is not None
            else (2 if contract.start_revision is not None else 1)
        ),
    )


# A tracker is rewritten through _atomic_write_session_tracker, which creates a
# sibling named ".{filename}.XXXXXXXX.tmp" -- one leading dot, one separator, the
# eight characters tempfile appends, and ".tmp". That is fourteen bytes the
# generator never budgeted for, so a filename the writer accepted could be one
# byte too long to ever update. Observed 2026-09-09: a 242-byte tracker produced a
# 256-byte temp name against Linux's 255-byte limit and every close of that lane
# died with "OSError: [Errno 36] File name too long", leaving the claim permanent.
# The overrun came from session_name, which is derived from free-text task wording.
_TRACKER_TEMP_DECORATION_BYTES = len(".") + len(".") + 8 + len(".tmp")
MAX_TRACKER_FILENAME_BYTES = 255
MAX_TRACKER_NAME_BYTES = MAX_TRACKER_FILENAME_BYTES - _TRACKER_TEMP_DECORATION_BYTES


def _bounded_tracker_filename(
    *, agent: str, project: str, safe_session_id: str, session_name: str
) -> str:
    """Compose a tracker filename that survives its own atomic rewrite.

    Only session_name is shortened. The identity prefix is what
    find_session_tracker_path globs on, and identity itself is read back out of
    the file's claim payload, never parsed from the name -- so trimming the
    descriptive tail cannot change which claim this is.
    """

    prefix = f"{agent}__{project}__{safe_session_id}__"
    suffix = ".yaml"
    budget = MAX_TRACKER_NAME_BYTES - len(prefix.encode()) - len(suffix.encode())
    if budget <= 0:
        raise ValueError(
            "Session tracker identity prefix alone exceeds the writable filename budget "
            f"({len(prefix.encode()) + len(suffix.encode())} bytes against "
            f"{MAX_TRACKER_NAME_BYTES}): agent={agent!r}, project={project!r}, "
            f"session_id={safe_session_id!r}. Shorten the agent or project identifier."
        )
    encoded = session_name.encode()
    if len(encoded) > budget:
        session_name = encoded[:budget].decode("utf-8", "ignore")
    return f"{prefix}{session_name}{suffix}"


def session_tracker_path(
    contract: SessionContract,
    *,
    tracker_dir: Path = DEFAULT_SESSION_TRACKERS_DIR,
) -> Path:
    """Return the canonical tracker path for one session contract."""

    safe_session_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", contract.session_id)
    directory = tracker_dir / contract.project
    bounded = directory / _bounded_tracker_filename(
        agent=contract.agent,
        project=contract.project,
        safe_session_id=safe_session_id,
        session_name=contract.session_name,
    )
    legacy = (
        directory
        / f"{contract.agent}__{contract.project}__{safe_session_id}__{contract.session_name}.yaml"
    )
    # A record written before the bound existed keeps its own path. Returning the
    # shortened name for it would strand the live tracker and start a second one
    # for the same claim.
    # ``Path.is_file`` stats the candidate and can raise ENAMETOOLONG before
    # returning False when the unbounded historical name exceeds the filesystem
    # component limit. Such a component cannot contain a legacy tracker, so skip
    # the probe and use the bounded path. Keep probing names that could exist:
    # this preserves pre-bound trackers that fit on disk but exceed our safer
    # atomic-rewrite budget.
    legacy_name_fits_filesystem = len(legacy.name.encode()) <= MAX_TRACKER_FILENAME_BYTES
    primary = (
        legacy
        if legacy != bounded and legacy_name_fits_filesystem and legacy.is_file()
        else bounded
    )
    if not primary.is_file():
        return primary
    previous = read_session_tracker(primary)
    tracker = previous.get("tracker")
    if not isinstance(tracker, dict) or tracker.get("current_phase") != "closed":
        return primary

    # A closed lane is history, not an occupied goal. Keep its original path
    # and allocate a deterministic successor path from the existing lane
    # identity. Refreshing/closing the predecessor still selects itself.
    identity_fields = (
        "agent", "project", "session_id", "repo_root", "scope", "branch", "worktree_path"
    )
    identity = {name: getattr(contract, name) for name in identity_fields}
    previous_claim = previous.get("claim")
    if not isinstance(previous_claim, dict) or any(
        not isinstance(previous_claim.get(name), str) or not previous_claim[name]
        for name in identity_fields
    ):
        raise ValueError(f"Closed session tracker at {primary} has incomplete lane identity")
    if any(previous_claim[name] != identity[name] for name in identity_fields[:4]):
        raise ValueError(f"Closed session tracker at {primary} belongs to another session")
    if all(previous_claim[name] == value for name, value in identity.items()):
        return primary
    lane_key = hashlib.sha256(
        "\0".join(identity[name] for name in identity_fields).encode()
    ).hexdigest()[:16]
    successor = directory / _bounded_tracker_filename(
        agent=contract.agent,
        project=contract.project,
        safe_session_id=safe_session_id,
        # Put the distinguishing key before the potentially truncated goal.
        session_name=f"lane-{lane_key}-{contract.session_name}",
    )
    if successor.is_file():
        successor_claim = read_session_tracker(successor).get("claim")
        if not isinstance(successor_claim, dict) or any(
            successor_claim.get(name) != value for name, value in identity.items()
        ):
            raise ValueError(f"Successor session tracker at {successor} has conflicting lane identity")
    return successor


def find_session_tracker_path(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str | None,
    preferred_path: str | None = None,
    tracker_dir: Path | None = None,
) -> Path | None:
    """Find one exact tracker when refreshed claim metadata lost its path.

    The lookup is deliberately identity-bound rather than an age or filename
    heuristic. More than one exact match is unsafe to resolve automatically.
    """

    if preferred_path:
        preferred = Path(preferred_path).expanduser()
        if preferred.is_file():
            return preferred
    if not session_id:
        return None

    safe_session_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", session_id)
    root = tracker_dir or DEFAULT_SESSION_TRACKERS_DIR
    candidates: list[Path] = []
    for path in sorted((root / project).glob(f"{agent}__{project}__{safe_session_id}__*.yaml")):
        payload = read_session_tracker(path)
        contract = payload.get("claim")
        if not isinstance(contract, dict):
            raise TypeError(f"Session tracker at {path} is missing claim metadata")
        if (
            contract.get("agent") == agent
            and contract.get("project") == project
            and contract.get("scope") == scope
            and contract.get("session_id") == session_id
        ):
            candidates.append(path)
    if len(candidates) > 1:
        rendered = ", ".join(str(path) for path in candidates)
        raise ValueError("Ambiguous exact session trackers after claim metadata refresh: " + rendered)
    return candidates[0] if candidates else None


def write_session_tracker(
    record: SessionTrackerRecord,
    *,
    tracker_dir: Path = DEFAULT_SESSION_TRACKERS_DIR,
) -> Path:
    """Persist one tracker without erasing selected outcome custody history."""

    path = session_tracker_path(record.contract, tracker_dir=tracker_dir)
    with session_tracker_lock(path):
        next_payload = record.to_dict()
        if path.is_file():
            current_payload = read_session_tracker(path)
            current_tracker = current_payload.get("tracker")
            if not isinstance(current_tracker, dict):
                raise TypeError(f"Session tracker at {path} is missing tracker metadata")
            custody: dict[str, Any] = {}
            for field in OUTCOME_CUSTODY_TRACKER_FIELDS:
                value = current_tracker.get(field)
                if value is None:
                    continue
                expected_type = dict if field == "outcome_selection" else list
                if not isinstance(value, expected_type):
                    raise TypeError(f"Session tracker at {path} has invalid {field} metadata")
                custody[field] = value
            if custody and "outcome_selection" not in custody:
                raise TypeError(f"Session tracker at {path} has outcome custody history without outcome_selection")
            if custody:
                current_claim = current_payload.get("claim")
                next_claim = next_payload.get("claim")
                if not isinstance(current_claim, dict) or not isinstance(next_claim, dict):
                    raise TypeError(f"Session tracker at {path} is missing claim metadata")
                identity_fields = (
                    "agent",
                    "project",
                    "scope",
                    "plan_ref",
                    "repo_root",
                    "worktree_path",
                    "branch",
                    "session_id",
                    "tracker_path",
                    "start_revision",
                    "plan_repo_root",
                    "plan_revision",
                    "plan_sha256",
                )
                path_identity_fields = {"repo_root", "worktree_path", "tracker_path", "plan_repo_root"}

                def identity_value(claim: dict[str, Any], field: str) -> object:
                    value = claim.get(field)
                    if field not in path_identity_fields or not isinstance(value, str) or not value:
                        return value
                    return str(Path(value).expanduser().resolve())

                mismatches = [
                    field
                    for field in identity_fields
                    if identity_value(current_claim, field) != identity_value(next_claim, field)
                ]
                if mismatches:
                    raise ValueError(
                        "A tracker with a selected outcome cannot change exact claim identity: " + ", ".join(mismatches)
                    )
                next_tracker = next_payload.get("tracker")
                if not isinstance(next_tracker, dict):
                    raise TypeError(f"Session tracker at {path} is missing tracker metadata")
                next_tracker.update(custody)
                current_timestamps = current_payload.get("timestamps")
                next_timestamps = next_payload.get("timestamps")
                if isinstance(current_timestamps, dict) and isinstance(next_timestamps, dict):
                    next_timestamps["created_at"] = current_timestamps.get(
                        "created_at",
                        next_timestamps["created_at"],
                    )
        _atomic_write_session_tracker(path, next_payload)
    return path


def tracker_lock_path(path: Path) -> Path:
    """Where the mutation lock for one tracker lives.

    NOT beside the tracker. A lock is process coordination, not repository
    content, and a sibling lock cannot be created when the tracker sits in a
    canonical checkout that a live lane claim has deliberately made read-only.
    That is not a hypothetical: closing a project-meta lane was impossible on
    2026-09-06 because ``learnings.md`` is in that repository's root, so the
    sibling lock landed inside the read-only tree and every closeout died on
    ``PermissionError: '.learnings.md.lock'``. The same closeout ran cleanly
    five times that session against a repository whose tracker was not in a
    locked root -- the failure was the lock's LOCATION, not the tracker.

    A crashed process also used to leave that sibling behind inside the locked
    tree, where it could not be cleared without unlocking the checkout again.

    The name is the sha256 of the resolved tracker path, so two different
    trackers never share a lock and the same tracker always resolves to the
    same one regardless of which worktree is asking.
    """

    resolved = path.expanduser().resolve()
    digest = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:32]
    root = Path(
        os.environ.get("ENFORCED_PLANNING_LOCK_DIR")
        or (Path(os.environ.get("XDG_RUNTIME_DIR") or Path.home() / ".cache")
            / "enforced-planning" / "tracker-locks")
    )
    # PURE. Computing where a lock lives must not create anything: the status
    # observer calls this only to LOOK for an existing lock, and an earlier
    # version of this function made the directory as a side effect, so merely
    # reading status started writing to disk. `session_tracker_lock` creates
    # the directory when it actually takes the lock.
    return root / f"{digest}.lock"


class TrackerPathNotYAML(TypeError):
    """A claim's tracker path is not a readable YAML mapping.

    A TypeError subclass so existing handlers that catch TypeError still work.
    """


@contextmanager
def session_tracker_lock(path: Path) -> Iterator[None]:
    """Serialize exact-session tracker mutations through one out-of-tree lock."""

    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = tracker_lock_path(resolved)
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("a+", encoding="utf-8") as handle:
        lock_path.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_session_tracker(path: Path, payload: dict[str, Any]) -> None:
    """Replace one tracker without exposing partial YAML to another reader."""

    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            yaml.safe_dump(payload, handle, default_flow_style=False, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, resolved)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def read_session_tracker(path: Path) -> dict[str, Any]:
    """Load one tracker artifact and fail loud if the structure is invalid.

    A parse failure is reported against the tracker path, not as a raw parser
    traceback. A claim recorded with a tracker path that is not a YAML mapping
    -- a Markdown document, say -- used to be accepted silently and then kill
    the CLOSEOUT with a bare ``yaml.scanner.ScannerError``, stranding a lane
    whose work was already merged. `check_coordination_claims.py` now refuses
    such a path when the claim is made; this is the second line of defence for
    claims recorded before that check existed.
    """

    text = path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TrackerPathNotYAML(
            f"Session tracker at {path} is not parseable as YAML, so the lane "
            f"holding it cannot be read or closed. A tracker must be a YAML "
            f"mapping; this looks like another kind of document. Underlying "
            f"parser error: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise TrackerPathNotYAML(
            f"Session tracker at {path} parsed as {type(raw).__name__}, not a "
            "YAML mapping. A Markdown or prose file passed as --tracker-path is "
            "the usual cause."
        )
    return raw


def mutate_session_tracker(
    path: Path,
    mutation: Callable[[dict[str, Any]], None],
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Apply one locked tracker transformation and atomically persist it."""

    resolved = path.expanduser().resolve()
    with session_tracker_lock(resolved):
        payload = read_session_tracker(resolved)
        mutation(payload)
        timestamps = payload.get("timestamps")
        if not isinstance(timestamps, dict):
            raise TypeError(f"Session tracker at {resolved} is missing timestamps section")
        timestamps["updated_at"] = updated_at or datetime.now(UTC).isoformat()
        _atomic_write_session_tracker(resolved, payload)
    return payload


def update_session_tracker(
    path: Path,
    *,
    current_phase: str | None = None,
    intended_next_phases: list[str] | None = None,
    depends_on_repos: list[str] | None = None,
    requires_shared_infra_changes: bool | None = None,
    stop_conditions: list[str] | None = None,
    notes: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    """Update one existing tracker artifact in place and return the payload."""

    def apply_updates(payload: dict[str, Any]) -> None:
        tracker = payload.get("tracker")
        timestamps = payload.get("timestamps")
        if not isinstance(tracker, dict) or not isinstance(timestamps, dict):
            raise TypeError(f"Session tracker at {path} is missing tracker/timestamps sections")
        if current_phase is not None:
            tracker["current_phase"] = _require_text(current_phase, field_name="current_phase")
        if intended_next_phases is not None:
            tracker["intended_next_phases"] = _clean_string_list(intended_next_phases)
        if depends_on_repos is not None:
            tracker["depends_on_repos"] = _clean_string_list(depends_on_repos)
        if requires_shared_infra_changes is not None:
            tracker["requires_shared_infra_changes"] = requires_shared_infra_changes
        if stop_conditions is not None:
            tracker["stop_conditions"] = _clean_string_list(stop_conditions)
        if notes is not None:
            tracker["notes"] = notes.strip()

    return mutate_session_tracker(path, apply_updates, updated_at=updated_at)
