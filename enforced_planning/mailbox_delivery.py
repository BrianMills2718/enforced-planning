"""Read-only host mailbox-installation audit and dry-run configuration planning.

This module deliberately does not install hooks.  It makes host configuration
inspectable and produces deterministic candidate descriptions for the later,
separately approved rollout unit.  Configuration, trust, and runtime receipt
evidence remain distinct throughout this boundary.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


def _path(path_text: str) -> Path:
    """Resolve only for local I/O; contracts retain the caller's portable string."""

    return Path(path_text).expanduser()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _adapter_sha256(adapter: HostAdapterSpecV1) -> tuple[str | None, tuple[str, ...]]:
    """Hash an adapter only when it exists; absent adapters are explicit drift."""

    adapter_path = _path(adapter.adapter_path)
    if not adapter_path.is_file():
        return None, ("adapter_missing",)
    return _sha256_bytes(adapter_path.read_bytes()), ()


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
                config_path=config_path,
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
            config_path=config_path,
            configured_events=configured,
            adapter_command=adapter.command if configured else None,
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
    codex, _ = _audit_surface(
        client="codex",
        scope="repository",
        config_path=codex_path.as_posix(),
        config=_read_json(codex_path, label="repository Codex hook"),
        adapter=request.codex_adapter,
        observed_clients=observed_clients,
    )
    claude, _ = _audit_surface(
        client="claude-code",
        scope="repository",
        config_path=claude_path.as_posix(),
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


def _render_toml(config: dict[str, Any]) -> str:
    lines: list[str] = []

    def write_table(prefix: tuple[str, ...], table: dict[str, Any], *, header: str | None = None) -> None:
        if header is not None:
            lines.append(header)
        for key in sorted(table):
            value = table[key]
            if not isinstance(value, (dict, list)) or (isinstance(value, list) and all(not isinstance(item, dict) for item in value)):
                lines.append(f"{key} = {_toml_value(value)}")
        if lines and lines[-1] != "":
            lines.append("")
        for key in sorted(table):
            value = table[key]
            child = prefix + (key,)
            dotted = ".".join(child)
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
    return "\n".join(lines) + "\n"


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
        candidate = json.loads(json.dumps(config))
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
        config_path=config_path,
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
