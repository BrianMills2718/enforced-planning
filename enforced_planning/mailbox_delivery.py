"""Read-only host mailbox-installation audit and dry-run configuration planning.

This module deliberately does not install hooks.  It makes host configuration
inspectable and produces deterministic candidate descriptions for the later,
separately approved rollout unit.  Configuration, trust, and runtime receipt
evidence remain distinct throughout this boundary.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enforced_planning.coordination_messages import StoredReceiptRecord


ClientName = Literal["codex", "claude-code"]
ConfigurationState = Literal["absent", "drifted", "configured"]
TrustState = Literal["unknown", "operationally_observed"]

CODEX_HOOK_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("SessionStart", "startup|resume|clear|compact"),
    ("UserPromptSubmit", ""),
    ("PostToolUse", "*"),
)
CLAUDE_HOOK_REQUIREMENTS = CODEX_HOOK_REQUIREMENTS


class MailboxInstallationError(RuntimeError):
    """Raised when a host configuration cannot be safely inspected or planned."""


class StrictContract(BaseModel):
    """Strict immutable base for durable mailbox-installation contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class HostAdapterSpecV1(StrictContract):
    """Expected command and local adapter file for one native client."""

    command: str = Field(min_length=1)
    adapter_path: str = Field(min_length=1)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ObservationEvidenceV1(StrictContract):
    """An already-verified observation receipt supplied by the caller."""

    client: ClientName
    receipt_id: str = Field(pattern=r"^rcpt_[0-9a-f]{32}$")
    session_id: str = Field(min_length=1)
    receipt_path: str = Field(min_length=1)


class HostInstallationAuditRequestV1(StrictContract):
    """Read-only inputs needed to classify host and optional repository hooks."""

    codex_config_path: str = Field(default="~/.codex/config.toml", min_length=1)
    claude_config_path: str = Field(default="~/.claude/settings.json", min_length=1)
    codex_adapter: HostAdapterSpecV1
    claude_adapter: HostAdapterSpecV1
    repository_root: str | None = Field(default=None, min_length=1)
    observation_evidence: tuple[ObservationEvidenceV1, ...] = ()
    framework_revision: str = Field(default="unknown", min_length=1)


class HostInstallationPlanRequestV1(HostInstallationAuditRequestV1):
    """Dry-run-only planning request; write authority is intentionally impossible."""

    write_requested: Literal[False] = False


class HookSurfaceV1(StrictContract):
    """One inspected host or repository hook surface, never a runtime assertion."""

    client: ClientName
    scope: Literal["host", "repository"]
    config_path: str = Field(min_length=1)
    configured_events: tuple[str, ...]
    adapter_command: str | None
    adapter_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    configuration_state: ConfigurationState
    trust_state: TrustState
    issues: tuple[str, ...]


class MailboxInstallationReceiptV1(StrictContract):
    """Durable read-only classification of installation state."""

    schema_version: Literal["mailbox_installation_receipt.v1"] = "mailbox_installation_receipt.v1"
    observed_at: datetime
    framework_revision: str = Field(min_length=1)
    host_surfaces: tuple[HookSurfaceV1, ...]
    repository_surfaces: tuple[HookSurfaceV1, ...]
    duplicate_delivery_risk: bool
    repair_actions: tuple[str, ...]


class HostConfigChangeV1(StrictContract):
    """A candidate configuration replacement described without writing it."""

    client: ClientName
    config_path: str = Field(min_length=1)
    configuration_state_before: ConfigurationState
    proposed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposed_bytes: int = Field(ge=0)
    required_events: tuple[str, ...]
    preserved_unrelated_hook_count: int = Field(ge=0)


class HostInstallationPlanV1(StrictContract):
    """A deterministic non-mutating plan for the separately approved rollout."""

    schema_version: Literal["mailbox_installation_plan.v1"] = "mailbox_installation_plan.v1"
    receipt: MailboxInstallationReceiptV1
    changes: tuple[HostConfigChangeV1, ...]
    will_write: Literal[False] = False
    backup_required: Literal[False] = False
    backup_required_on_apply: Literal[True] = True
    atomic_replace_required_on_apply: Literal[True] = True


class HostConfigFingerprintV1(StrictContract):
    """One exact host-config and adapter binding for a read-only candidate."""

    client: ClientName
    config_path: str = Field(min_length=1)
    state: Literal["absent", "present"]
    before_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proposed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_state_digest(self) -> HostConfigFingerprintV1:
        """Make an absent source distinguishable from an omitted fingerprint."""

        if self.state == "absent" and self.before_sha256 is not None:
            raise ValueError("absent config must not retain before_sha256")
        if self.state == "present" and self.before_sha256 is None:
            raise ValueError("present config requires before_sha256")
        return self


class HostInstallationCandidatePayloadV1(StrictContract):
    """Portable, non-mutating candidate bound to exact source bytes."""

    schema_version: Literal["mailbox_host_candidate.v1"] = "mailbox_host_candidate.v1"
    framework_revision: str = Field(min_length=1)
    generated_at: datetime
    configs: tuple[HostConfigFingerprintV1, HostConfigFingerprintV1]
    plan: HostInstallationPlanV1
    will_write: Literal[False] = False

    @model_validator(mode="after")
    def validate_clients(self) -> HostInstallationCandidatePayloadV1:
        """Require exactly one binding for each supported host client."""

        if tuple(item.client for item in self.configs) != ("codex", "claude-code"):
            raise ValueError("candidate configs must be ordered as codex then claude-code")
        return self


class StoredHostInstallationCandidateV1(StrictContract):
    """Digest envelope for the exact candidate a later rollout may approve."""

    record_type: Literal["mailbox_host_candidate"] = "mailbox_host_candidate"
    payload: HostInstallationCandidatePayloadV1
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digest(self) -> StoredHostInstallationCandidateV1:
        """Reject envelopes that do not bind their exact payload bytes."""

        if self.payload_sha256 != _model_digest(self.payload):
            raise ValueError("host candidate payload_sha256 mismatch")
        return self


class HostInstallationAppliedFileV1(StrictContract):
    """One host config after a verified, recoverable candidate application."""

    client: ClientName
    config_path: str = Field(min_length=1)
    before_state: Literal["absent", "present"]
    before_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    after_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backup_path: str | None = None
    backup_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class HostInstallationApplyReceiptV1(StrictContract):
    """Durable evidence that one approved candidate was applied and rechecked."""

    schema_version: Literal["mailbox_host_apply_receipt.v1"] = "mailbox_host_apply_receipt.v1"
    approved_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    framework_revision: str = Field(min_length=1)
    applied_at: datetime
    files: tuple[HostInstallationAppliedFileV1, HostInstallationAppliedFileV1]
    before_receipt: MailboxInstallationReceiptV1
    after_receipt: MailboxInstallationReceiptV1
    second_dry_run_action_count: Literal[0] = 0
    trust_state: Literal["unknown"] = "unknown"
    client_restart_or_resume_required: Literal[True] = True


class HostInstallationRollbackV1(StrictContract):
    """Exact restoration evidence for one config after an apply failure."""

    client: ClientName
    config_path: str = Field(min_length=1)
    restored_state: Literal["absent", "present"]
    restored_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class HostInstallationApplyFailureV1(StrictContract):
    """Fail-loud evidence for a rejected or rolled-back host application."""

    schema_version: Literal["mailbox_host_apply_failure.v1"] = "mailbox_host_apply_failure.v1"
    approved_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    failed_at: datetime
    stage: Literal["preflight", "backup", "write", "readback", "idempotence"]
    reason: str = Field(min_length=1)
    mutation_started: bool
    rollback_verified: bool
    rollback: tuple[HostInstallationRollbackV1, ...] = ()


class HostInstallationApplyError(MailboxInstallationError):
    """Host application failed with a typed, inspectable failure record."""

    def __init__(self, receipt: HostInstallationApplyFailureV1) -> None:
        super().__init__(receipt.reason)
        self.receipt = receipt


def _path(path_text: str) -> Path:
    """Resolve only for local I/O; contracts retain the caller's portable string."""

    return Path(path_text).expanduser()


def _portable_text(value: str) -> str:
    """Replace the current home prefix with ``~`` in durable display values."""

    home = str(Path.home())
    return value.replace(home, "~") if home else value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _model_digest(payload: StrictContract) -> str:
    """Hash canonical JSON for a durable strict-contract envelope."""

    encoded = json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _adapter_sha256(adapter: HostAdapterSpecV1) -> tuple[str | None, tuple[str, ...]]:
    """Hash an adapter only when it exists; absent adapters are explicit drift."""

    adapter_path = _path(adapter.adapter_path)
    if not adapter_path.is_file():
        return None, ("adapter_missing",)
    digest = _sha256_bytes(adapter_path.read_bytes())
    if digest != adapter.expected_sha256:
        return digest, ("adapter_digest_mismatch",)
    return digest, ()


def _read_json(path: Path, *, label: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MailboxInstallationError(f"invalid {label} JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MailboxInstallationError(f"invalid {label} JSON at {path}: expected object")
    return value


def _read_toml(path: Path, *, label: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MailboxInstallationError(f"invalid {label} TOML at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MailboxInstallationError(f"invalid {label} TOML at {path}: expected table")
    return value


def _hook_blocks(config: dict[str, Any], event: str) -> list[dict[str, Any]]:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return []
    blocks = hooks.get(event)
    if not isinstance(blocks, list):
        return []
    return [block for block in blocks if isinstance(block, dict)]


def _commands(block: dict[str, Any]) -> list[str]:
    hooks = block.get("hooks")
    if not isinstance(hooks, list):
        return []
    return [entry["command"] for entry in hooks if isinstance(entry, dict) and isinstance(entry.get("command"), str)]


def _matching_events(
    config: dict[str, Any], requirements: tuple[tuple[str, str], ...], command: str
) -> tuple[tuple[str, ...], tuple[str, ...], int]:
    """Return exact configured events, missing events, and unrelated command count."""

    configured: list[str] = []
    missing: list[str] = []
    expected_pairs = set(requirements)
    unrelated_commands = 0
    for event, matcher in requirements:
        present = any(block.get("matcher", "") == matcher and command in _commands(block) for block in _hook_blocks(config, event))
        (configured if present else missing).append(event)
    for event, blocks in (config.get("hooks") or {}).items() if isinstance(config.get("hooks"), dict) else ():
        if not isinstance(event, str) or not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            is_expected_block = (event, block.get("matcher", "")) in expected_pairs
            for configured_command in _commands(block):
                if not (is_expected_block and configured_command == command):
                    unrelated_commands += 1
    return tuple(configured), tuple(missing), unrelated_commands


def _verified_observed_clients(evidence: tuple[ObservationEvidenceV1, ...]) -> frozenset[ClientName]:
    """Validate exact durable observation receipts before promoting runtime state."""

    verified: set[ClientName] = set()
    for item in evidence:
        expected_prefix = "codex:" if item.client == "codex" else "claude-code:"
        if not item.session_id.startswith(expected_prefix):
            raise MailboxInstallationError(
                f"observation evidence client/session mismatch: {item.client} requires {expected_prefix!r}"
            )
        receipt_path = _path(item.receipt_path)
        try:
            record = StoredReceiptRecord.model_validate_json(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise MailboxInstallationError(f"invalid observation receipt at {receipt_path}: {exc}") from exc
        receipt = record.payload
        if receipt.receipt_id != item.receipt_id or receipt.recipient_session_id != item.session_id:
            raise MailboxInstallationError(f"observation receipt identity mismatch at {receipt_path}")
        if receipt.event != "observed":
            raise MailboxInstallationError(f"observation receipt at {receipt_path} is not an observed event")
        verified.add(item.client)
    return frozenset(verified)


def _trust_state(client: ClientName, observed_clients: frozenset[ClientName]) -> TrustState:
    return "operationally_observed" if client in observed_clients else "unknown"


def _audit_surface(
    *,
    client: ClientName,
    scope: Literal["host", "repository"],
    config_path: str,
    config: dict[str, Any] | None,
    adapter: HostAdapterSpecV1,
    observed_clients: frozenset[ClientName],
) -> tuple[HookSurfaceV1, int]:
    digest, adapter_issues = _adapter_sha256(adapter)
    if config is None:
        return (
            HookSurfaceV1(
                client=client,
                scope=scope,
                config_path=_portable_text(config_path),
                configured_events=(),
                adapter_command=None,
                adapter_sha256=digest,
                configuration_state="absent",
                trust_state=_trust_state(client, observed_clients),
                issues=("config_missing", *adapter_issues),
            ),
            0,
        )
    requirements = CODEX_HOOK_REQUIREMENTS if client == "codex" else CLAUDE_HOOK_REQUIREMENTS
    configured, missing, unrelated = _matching_events(config, requirements, adapter.command)
    issues = [*adapter_issues]
    if missing:
        issues.append("missing_required_hook")
    state: ConfigurationState = "configured" if not issues else "drifted"
    return (
        HookSurfaceV1(
            client=client,
            scope=scope,
            config_path=_portable_text(config_path),
            configured_events=configured,
            adapter_command=_portable_text(adapter.command) if configured else None,
            adapter_sha256=digest,
            configuration_state=state,
            trust_state=_trust_state(client, observed_clients),
            issues=tuple(issues),
        ),
        unrelated,
    )


def _repository_surfaces(
    request: HostInstallationAuditRequestV1, observed_clients: frozenset[ClientName]
) -> tuple[HookSurfaceV1, ...]:
    if request.repository_root is None:
        return ()
    root = _path(request.repository_root)
    codex_path = root / ".codex" / "hooks.json"
    claude_path = root / ".claude" / "settings.json"
    display_root = PurePosixPath(request.repository_root)
    codex, _ = _audit_surface(
        client="codex",
        scope="repository",
        config_path=_portable_text((display_root / ".codex" / "hooks.json").as_posix()),
        config=_read_json(codex_path, label="repository Codex hook"),
        adapter=request.codex_adapter,
        observed_clients=observed_clients,
    )
    claude, _ = _audit_surface(
        client="claude-code",
        scope="repository",
        config_path=_portable_text((display_root / ".claude" / "settings.json").as_posix()),
        config=_read_json(claude_path, label="repository Claude hook"),
        adapter=request.claude_adapter,
        observed_clients=observed_clients,
    )
    return codex, claude


def audit_host_installation(request: HostInstallationAuditRequestV1) -> MailboxInstallationReceiptV1:
    """Inspect host hooks without writing files or treating configuration as runtime proof."""

    codex_path = _path(request.codex_config_path)
    claude_path = _path(request.claude_config_path)
    observed_clients = _verified_observed_clients(request.observation_evidence)
    codex, _ = _audit_surface(
        client="codex",
        scope="host",
        config_path=request.codex_config_path,
        config=_read_toml(codex_path, label="Codex host config"),
        adapter=request.codex_adapter,
        observed_clients=observed_clients,
    )
    claude, _ = _audit_surface(
        client="claude-code",
        scope="host",
        config_path=request.claude_config_path,
        config=_read_json(claude_path, label="Claude host config"),
        adapter=request.claude_adapter,
        observed_clients=observed_clients,
    )
    repository_surfaces = _repository_surfaces(request, observed_clients)
    duplicate_risk = any(
        host.configuration_state == "configured"
        and any(
            repo.client == host.client and repo.configuration_state == "configured" for repo in repository_surfaces
        )
        for host in (codex, claude)
    )
    repairs: list[str] = []
    for surface in (codex, claude, *repository_surfaces):
        if surface.configuration_state == "absent":
            repairs.append(f"configure:{surface.scope}:{surface.client}")
        elif surface.configuration_state == "drifted":
            repairs.append(f"repair:{surface.scope}:{surface.client}:{','.join(surface.issues)}")
    if duplicate_risk:
        repairs.append("defer_duplicate_delivery_until_mf02")
    return MailboxInstallationReceiptV1(
        observed_at=datetime.now(UTC),
        framework_revision=request.framework_revision,
        host_surfaces=(codex, claude),
        repository_surfaces=repository_surfaces,
        duplicate_delivery_risk=duplicate_risk,
        repair_actions=tuple(repairs),
    )


def _ensure_required(config: dict[str, Any], requirements: tuple[tuple[str, str], ...], command: str) -> None:
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise MailboxInstallationError("invalid hook configuration: hooks must be an object")
    for event, matcher in requirements:
        blocks = hooks.setdefault(event, [])
        if not isinstance(blocks, list):
            raise MailboxInstallationError(f"invalid hook configuration: hooks.{event} must be a list")
        matching = next((block for block in blocks if isinstance(block, dict) and block.get("matcher", "") == matcher), None)
        if matching is None:
            matching = {"matcher": matcher, "hooks": []}
            blocks.append(matching)
        hook_list = matching.setdefault("hooks", [])
        if not isinstance(hook_list, list):
            raise MailboxInstallationError(f"invalid hook configuration: hooks.{event} matcher hooks must be a list")
        if not any(isinstance(entry, dict) and entry.get("command") == command for entry in hook_list):
            hook_list.append({"type": "command", "command": command, "timeout": 3})


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list) and all(not isinstance(item, dict) for item in value):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise MailboxInstallationError(f"unsupported TOML value in dry-run planner: {type(value).__name__}")


_TOML_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(value: str) -> str:
    """Quote TOML keys that are not valid bare keys, including filesystem paths."""

    return value if _TOML_BARE_KEY.fullmatch(value) else json.dumps(value)


def _render_toml(config: dict[str, Any]) -> str:
    lines: list[str] = []

    def write_table(prefix: tuple[str, ...], table: dict[str, Any], *, header: str | None = None) -> None:
        if header is not None:
            lines.append(header)
        for key in sorted(table):
            value = table[key]
            if not isinstance(value, (dict, list)) or (isinstance(value, list) and all(not isinstance(item, dict) for item in value)):
                lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
        if lines and lines[-1] != "":
            lines.append("")
        for key in sorted(table):
            value = table[key]
            child = prefix + (key,)
            dotted = ".".join(_toml_key(part) for part in child)
            if isinstance(value, dict):
                write_table(child, value, header=f"[{dotted}]")
            elif isinstance(value, list) and any(isinstance(item, dict) for item in value):
                if not all(isinstance(item, dict) for item in value):
                    raise MailboxInstallationError("unsupported mixed TOML array in dry-run planner")
                for item in value:
                    write_table(child, item, header=f"[[{dotted}]]")

    write_table((), config)
    while lines and lines[-1] == "":
        lines.pop()
    rendered = "\n".join(lines) + "\n"
    try:
        tomllib.loads(rendered)
    except tomllib.TOMLDecodeError as exc:
        raise MailboxInstallationError(f"generated Codex TOML candidate is invalid: {exc}") from exc
    return rendered


def _candidate_content(
    *,
    client: ClientName,
    config: dict[str, Any] | None,
    adapter: HostAdapterSpecV1,
) -> tuple[str, int] | None:
    """Render a non-persisted semantic merge candidate for deterministic planning."""

    if config is None:
        candidate: dict[str, Any] = {}
        unrelated = 0
    else:
        candidate = copy.deepcopy(config)
        requirements = CODEX_HOOK_REQUIREMENTS if client == "codex" else CLAUDE_HOOK_REQUIREMENTS
        _configured, missing, unrelated = _matching_events(config, requirements, adapter.command)
        if not missing:
            return None
    requirements = CODEX_HOOK_REQUIREMENTS if client == "codex" else CLAUDE_HOOK_REQUIREMENTS
    _ensure_required(candidate, requirements, adapter.command)
    rendered = _render_toml(candidate) if client == "codex" else json.dumps(candidate, indent=2, sort_keys=True) + "\n"
    return rendered, unrelated


def _candidate_change(
    *,
    client: ClientName,
    config_path: str,
    config: dict[str, Any] | None,
    adapter: HostAdapterSpecV1,
    state: ConfigurationState,
) -> HostConfigChangeV1 | None:
    candidate = _candidate_content(client=client, config=config, adapter=adapter)
    if candidate is None:
        return None
    rendered, unrelated = candidate
    requirements = CODEX_HOOK_REQUIREMENTS if client == "codex" else CLAUDE_HOOK_REQUIREMENTS
    return HostConfigChangeV1(
        client=client,
        config_path=_portable_text(config_path),
        configuration_state_before=state,
        proposed_sha256=_sha256_bytes(rendered.encode("utf-8")),
        proposed_bytes=len(rendered.encode("utf-8")),
        required_events=tuple(event for event, _matcher in requirements),
        preserved_unrelated_hook_count=unrelated,
    )


def plan_host_installation(request: HostInstallationPlanRequestV1) -> HostInstallationPlanV1:
    """Produce a dry-run-only host configuration plan; this function never writes."""

    receipt = audit_host_installation(request)
    codex_config = _read_toml(_path(request.codex_config_path), label="Codex host config")
    claude_config = _read_json(_path(request.claude_config_path), label="Claude host config")
    changes = tuple(
        change
        for change in (
            _candidate_change(
                client="codex",
                config_path=request.codex_config_path,
                config=codex_config,
                adapter=request.codex_adapter,
                state=receipt.host_surfaces[0].configuration_state,
            ),
            _candidate_change(
                client="claude-code",
                config_path=request.claude_config_path,
                config=claude_config,
                adapter=request.claude_adapter,
                state=receipt.host_surfaces[1].configuration_state,
            ),
        )
        if change is not None
    )
    return HostInstallationPlanV1(receipt=receipt, changes=changes)


def _candidate_fingerprint(
    *,
    client: ClientName,
    config_path: str,
    adapter: HostAdapterSpecV1,
    plan: HostInstallationPlanV1,
) -> HostConfigFingerprintV1:
    """Bind one candidate leg to exact source bytes and validated adapter bytes."""

    adapter_sha256, adapter_issues = _adapter_sha256(adapter)
    if adapter_issues or adapter_sha256 is None:
        detail = ",".join(adapter_issues) if adapter_issues else "adapter_digest_unavailable"
        raise MailboxInstallationError(f"cannot generate host candidate: {client} {detail}")
    source = _path(config_path)
    before = source.read_bytes() if source.exists() else None
    changes = {change.client: change for change in plan.changes}
    proposed_sha256 = changes[client].proposed_sha256 if client in changes else _sha256_bytes(before or b"")
    return HostConfigFingerprintV1(
        client=client,
        config_path=_portable_text(config_path),
        state="present" if before is not None else "absent",
        before_sha256=_sha256_bytes(before) if before is not None else None,
        proposed_sha256=proposed_sha256,
        adapter_sha256=adapter_sha256,
    )


def generate_host_installation_candidate(
    request: HostInstallationPlanRequestV1,
) -> StoredHostInstallationCandidateV1:
    """Create an exact, portable, read-only candidate for later human approval."""

    if request.framework_revision == "unknown":
        raise MailboxInstallationError(
            "cannot generate host candidate: exact framework_revision is required"
        )
    plan = plan_host_installation(request)
    payload = HostInstallationCandidatePayloadV1(
        framework_revision=request.framework_revision,
        generated_at=datetime.now(UTC),
        configs=(
            _candidate_fingerprint(
                client="codex",
                config_path=request.codex_config_path,
                adapter=request.codex_adapter,
                plan=plan,
            ),
            _candidate_fingerprint(
                client="claude-code",
                config_path=request.claude_config_path,
                adapter=request.claude_adapter,
                plan=plan,
            ),
        ),
        plan=plan,
    )
    return StoredHostInstallationCandidateV1(payload=payload, payload_sha256=_model_digest(payload))


def _atomic_replace(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    """Replace one file from the same directory and fsync before returning."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _parse_config_bytes(client: ClientName, content: bytes, *, label: str) -> dict[str, Any]:
    try:
        parsed = tomllib.loads(content.decode("utf-8")) if client == "codex" else json.loads(content)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        raise MailboxInstallationError(f"invalid {label} for {client}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MailboxInstallationError(f"invalid {label} for {client}: expected object")
    return parsed


def _failure(
    *,
    candidate: StoredHostInstallationCandidateV1,
    approved_payload_sha256: str,
    stage: Literal["preflight", "backup", "write", "readback", "idempotence"],
    reason: str,
    mutation_started: bool,
    rollback_verified: bool = False,
    rollback: tuple[HostInstallationRollbackV1, ...] = (),
) -> HostInstallationApplyError:
    return HostInstallationApplyError(
        HostInstallationApplyFailureV1(
            approved_payload_sha256=approved_payload_sha256,
            candidate_payload_sha256=candidate.payload_sha256,
            failed_at=datetime.now(UTC),
            stage=stage,
            reason=reason,
            mutation_started=mutation_started,
            rollback_verified=rollback_verified,
            rollback=rollback,
        )
    )


def _rollback_configs(
    originals: dict[ClientName, bytes | None], paths: dict[ClientName, Path]
) -> tuple[HostInstallationRollbackV1, HostInstallationRollbackV1]:
    records: list[HostInstallationRollbackV1] = []
    for client in ("codex", "claude-code"):
        path = paths[client]
        original = originals[client]
        if original is None:
            path.unlink(missing_ok=True)
            if path.exists():
                raise MailboxInstallationError(f"rollback failed to remove originally absent {client} config")
            restored_sha256 = None
            state: Literal["absent", "present"] = "absent"
        else:
            mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
            _atomic_replace(path, original, mode=mode)
            restored_sha256 = _sha256_bytes(path.read_bytes())
            if restored_sha256 != _sha256_bytes(original):
                raise MailboxInstallationError(f"rollback digest mismatch for {client} config")
            _parse_config_bytes(client, path.read_bytes(), label="restored host config")
            state = "present"
        records.append(
            HostInstallationRollbackV1(
                client=client,
                config_path=_portable_text(str(path)),
                restored_state=state,
                restored_sha256=restored_sha256,
            )
        )
    return records[0], records[1]


def apply_host_installation_candidate(
    *,
    candidate: StoredHostInstallationCandidateV1,
    approved_payload_sha256: str,
    request: HostInstallationPlanRequestV1,
    backup_root: str,
) -> HostInstallationApplyReceiptV1:
    """Apply exactly one approved, unchanged candidate or restore the full group."""

    if approved_payload_sha256 != candidate.payload_sha256:
        raise _failure(
            candidate=candidate,
            approved_payload_sha256=approved_payload_sha256,
            stage="preflight",
            reason="approved payload digest does not match candidate",
            mutation_started=False,
        )
    if request.framework_revision != candidate.payload.framework_revision:
        raise _failure(
            candidate=candidate,
            approved_payload_sha256=approved_payload_sha256,
            stage="preflight",
            reason="framework revision does not match approved candidate",
            mutation_started=False,
        )

    configs = candidate.payload.configs
    paths: dict[ClientName, Path] = {
        "codex": _path(request.codex_config_path),
        "claude-code": _path(request.claude_config_path),
    }
    adapters: dict[ClientName, HostAdapterSpecV1] = {
        "codex": request.codex_adapter,
        "claude-code": request.claude_adapter,
    }
    originals: dict[ClientName, bytes | None] = {}
    proposed: dict[ClientName, bytes] = {}
    before_receipt: MailboxInstallationReceiptV1
    try:
        before_receipt = audit_host_installation(request)
        for fingerprint in configs:
            client = fingerprint.client
            if fingerprint.config_path != _portable_text(str(paths[client])):
                raise MailboxInstallationError(f"config path drift for {client}")
            adapter_digest, adapter_issues = _adapter_sha256(adapters[client])
            if adapter_issues or adapter_digest != fingerprint.adapter_sha256:
                raise MailboxInstallationError(f"adapter digest drift for {client}")
            original = paths[client].read_bytes() if paths[client].exists() else None
            originals[client] = original
            observed_state = "present" if original is not None else "absent"
            observed_digest = _sha256_bytes(original) if original is not None else None
            if observed_state != fingerprint.state or observed_digest != fingerprint.before_sha256:
                raise MailboxInstallationError(f"config input digest drift for {client}")
            parsed = _parse_config_bytes(client, original, label="host config") if original is not None else None
            rendered = _candidate_content(client=client, config=parsed, adapter=adapters[client])
            candidate_bytes = original if rendered is None and original is not None else (rendered[0].encode("utf-8") if rendered else b"")
            if _sha256_bytes(candidate_bytes) != fingerprint.proposed_sha256:
                raise MailboxInstallationError(f"proposed config digest drift for {client}")
            proposed[client] = candidate_bytes
    except MailboxInstallationError as exc:
        raise _failure(
            candidate=candidate,
            approved_payload_sha256=approved_payload_sha256,
            stage="preflight",
            reason=str(exc),
            mutation_started=False,
        ) from exc

    backup_directory = _path(backup_root) / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + f"-{candidate.payload_sha256[:12]}"
    )
    backups: dict[ClientName, Path | None] = {"codex": None, "claude-code": None}
    try:
        backup_directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        for client in ("codex", "claude-code"):
            original = originals[client]
            if original is None:
                continue
            suffix = ".toml" if client == "codex" else ".json"
            backup = backup_directory / f"{client}-config{suffix}"
            descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
            backup_bytes = backup.read_bytes()
            if backup_bytes != original:
                raise MailboxInstallationError(f"backup readback mismatch for {client}")
            _parse_config_bytes(client, backup_bytes, label="backup")
            backups[client] = backup
    except (OSError, MailboxInstallationError) as exc:
        raise _failure(
            candidate=candidate,
            approved_payload_sha256=approved_payload_sha256,
            stage="backup",
            reason=str(exc),
            mutation_started=False,
        ) from exc

    mutation_started = False
    stage: Literal["write", "readback", "idempotence"] = "write"
    try:
        for client in ("codex", "claude-code"):
            if proposed[client] == originals[client]:
                continue
            mutation_started = True
            current = paths[client]
            mode = current.stat().st_mode & 0o777 if current.exists() else 0o600
            _atomic_replace(current, proposed[client], mode=mode)
        stage = "readback"
        for fingerprint in configs:
            content = paths[fingerprint.client].read_bytes()
            _parse_config_bytes(fingerprint.client, content, label="applied host config")
            if _sha256_bytes(content) != fingerprint.proposed_sha256:
                raise MailboxInstallationError(f"applied config digest mismatch for {fingerprint.client}")
        after_receipt = audit_host_installation(request)
        if any(surface.configuration_state != "configured" for surface in after_receipt.host_surfaces):
            raise MailboxInstallationError("applied host audit did not classify both clients as configured")
        stage = "idempotence"
        second_plan = plan_host_installation(request)
        if second_plan.changes:
            raise MailboxInstallationError("second host installation dry run was not zero-action")
    except (OSError, MailboxInstallationError) as exc:
        try:
            rollback = _rollback_configs(originals, paths)
        except (OSError, MailboxInstallationError) as rollback_exc:
            raise _failure(
                candidate=candidate,
                approved_payload_sha256=approved_payload_sha256,
                stage=stage,
                reason=f"{exc}; rollback failed: {rollback_exc}",
                mutation_started=mutation_started,
                rollback_verified=False,
            ) from rollback_exc
        raise _failure(
            candidate=candidate,
            approved_payload_sha256=approved_payload_sha256,
            stage=stage,
            reason=str(exc),
            mutation_started=mutation_started,
            rollback_verified=True,
            rollback=rollback,
        ) from exc

    applied_file_records: list[HostInstallationAppliedFileV1] = []
    for fingerprint in configs:
        receipt_backup = backups[fingerprint.client]
        applied_file_records.append(
            HostInstallationAppliedFileV1(
                client=fingerprint.client,
                config_path=fingerprint.config_path,
                before_state=fingerprint.state,
                before_sha256=fingerprint.before_sha256,
                after_sha256=fingerprint.proposed_sha256,
                backup_path=_portable_text(str(receipt_backup)) if receipt_backup else None,
                backup_sha256=_sha256_bytes(receipt_backup.read_bytes()) if receipt_backup else None,
            )
        )
    return HostInstallationApplyReceiptV1(
        approved_payload_sha256=approved_payload_sha256,
        framework_revision=candidate.payload.framework_revision,
        applied_at=datetime.now(UTC),
        files=(applied_file_records[0], applied_file_records[1]),
        before_receipt=before_receipt,
        after_receipt=after_receipt,
    )
