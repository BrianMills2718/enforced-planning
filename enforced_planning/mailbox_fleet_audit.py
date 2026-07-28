"""Read-only mailbox compatibility audit for the explicit governed-repo fleet.

The fleet registry is an inventory, not authority to alter its entries or the
repositories it names.  This module therefore reads each registered checkout,
keeps host delivery evidence out of repository classifications, and emits a
separately claimable repair packet only when the local repository boundary is
safe to hand to a later operator.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from enforced_planning.hook_wiring import CODEX_MAILBOX_HOOK, MAILBOX_HOOK, MAILBOX_HOOK_FILES, MAILBOX_SUPPORT_FILES
from enforced_planning.mailbox_delivery import (
    HostAdapterSpecV1,
    HostInstallationAuditRequestV1,
    MailboxInstallationError,
    MailboxInstallationReceiptV1,
    audit_host_installation,
)


FleetClassification = Literal["current", "drifted", "unavailable", "excluded"]


class MailboxFleetAuditError(RuntimeError):
    """Raised when the explicit registry cannot be read as a fleet inventory."""


class StrictContract(BaseModel):
    """Immutable strict base for durable fleet-audit output."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FleetRepositoryEntryV1(StrictContract):
    """One explicit governed-repository inventory entry."""

    repo_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    tier: str = Field(min_length=1)
    mailbox_audit: Literal["included", "excluded"] = "included"


class FleetRepairPacketV1(StrictContract):
    """A proposed, separately claimable repair; the auditor never runs it."""

    repo_id: str = Field(min_length=1)
    claim_scope: str = Field(min_length=1)
    command: str = Field(min_length=1)
    paths: tuple[str, ...]
    requires_clean_worktree: Literal[True] = True
    requires_consumer_repository_authority: Literal[True] = True
    will_execute: Literal[False] = False


class FleetRepositoryReportV1(StrictContract):
    """Read-only classification for one explicitly registered repository."""

    repo_id: str = Field(min_length=1)
    registry_path: str = Field(min_length=1)
    resolved_path: str = Field(min_length=1)
    tier: str = Field(min_length=1)
    classification: FleetClassification
    reasons: tuple[str, ...]
    repair_eligible: bool
    installation_receipt: MailboxInstallationReceiptV1 | None = None
    repair_packet: FleetRepairPacketV1 | None = None


class FleetRegistryOmissionV1(StrictContract):
    """A governed-looking checkout found outside the explicit inventory."""

    resolved_path: str = Field(min_length=1)
    reason: Literal["governed_marker_not_registered"] = "governed_marker_not_registered"
    suggested_repo_id: str = Field(min_length=1)


class MailboxFleetAuditRequestV1(StrictContract):
    """Inputs for a fleet audit whose only possible action is reading files."""

    registry_path: str = Field(min_length=1)
    framework_root: str = Field(min_length=1)
    workspace_root: str | None = Field(default=None, min_length=1)
    framework_revision: str = Field(default="unknown", min_length=1)
    write_requested: Literal[False] = False


class MailboxFleetAuditReportV1(StrictContract):
    """Complete audit result for every explicit registry entry and omissions."""

    schema_version: Literal["mailbox_fleet_audit.v1"] = "mailbox_fleet_audit.v1"
    audited_at: datetime
    registry_path: str = Field(min_length=1)
    explicit_entry_count: int = Field(ge=0)
    reports: tuple[FleetRepositoryReportV1, ...]
    omissions: tuple[FleetRegistryOmissionV1, ...]
    write_performed: Literal[False] = False


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expand(path_text: str) -> Path:
    return Path(path_text).expanduser().resolve()


def _portable_path(path: Path) -> str:
    """Render paths below the current home without retaining its absolute prefix."""

    resolved = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    return "~" if not relative.parts else f"~/{relative.as_posix()}"


def _shell_quote(value: str) -> str:
    """Return a shell-safe single argument without invoking a shell."""

    return "'" + value.replace("'", "'\"'\"'") + "'"


def load_fleet_registry(registry_path: Path) -> tuple[FleetRepositoryEntryV1, ...]:
    """Load every explicit registry entry; malformed inventory fails loudly."""

    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MailboxFleetAuditError(f"invalid fleet registry at {registry_path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("repos"), list):
        raise MailboxFleetAuditError(f"invalid fleet registry at {registry_path}: expected a repos list")

    entries: list[FleetRepositoryEntryV1] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw["repos"]):
        if not isinstance(item, dict):
            raise MailboxFleetAuditError(f"invalid fleet registry entry {index}: expected object")
        raw_id = item.get("repo_id", item.get("id"))
        raw_path = item.get("path")
        raw_tier = item.get("tier", "governed")
        if not isinstance(raw_id, str) or not isinstance(raw_path, str) or not isinstance(raw_tier, str):
            raise MailboxFleetAuditError(f"invalid fleet registry entry {index}: id, path, and tier must be strings")
        if raw_id in seen_ids:
            raise MailboxFleetAuditError(f"invalid fleet registry: duplicate repo id {raw_id!r}")
        seen_ids.add(raw_id)
        mailbox_audit = item.get("mailbox_audit", "included")
        try:
            entries.append(
                FleetRepositoryEntryV1(
                    repo_id=raw_id,
                    path=raw_path,
                    tier=raw_tier,
                    mailbox_audit=mailbox_audit,
                )
            )
        except ValueError as exc:
            raise MailboxFleetAuditError(f"invalid fleet registry entry {raw_id!r}: {exc}") from exc
    return tuple(entries)


def _is_excluded(entry: FleetRepositoryEntryV1) -> bool:
    return entry.mailbox_audit == "excluded" or entry.tier in {"archived", "employer", "external", "excluded"}


def _git_is_dirty(repo_root: Path) -> bool | None:
    """Inspect Git content without ``status`` index refreshes or lock writes."""

    if not (repo_root / ".git").exists():
        return None
    try:
        commands = (
            ["git", "diff", "--no-ext-diff", "--quiet"],
            ["git", "diff", "--cached", "--no-ext-diff", "--quiet"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        )
        results = tuple(
            subprocess.run(command, cwd=repo_root, capture_output=True, text=True, check=False, timeout=15)
            for command in commands
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    unstaged, staged, untracked = results
    if unstaged.returncode not in {0, 1} or staged.returncode not in {0, 1} or untracked.returncode != 0:
        return None
    return unstaged.returncode == 1 or staged.returncode == 1 or bool(untracked.stdout.strip())


def _authority_known(repo_root: Path) -> bool:
    return (repo_root / "CLAUDE.md").is_file() and (repo_root / "meta-process.yaml").is_file()


def _repair_paths(repo_root: Path) -> tuple[str, ...]:
    paths = [".codex/hooks.json", ".claude/settings.json"]
    paths.extend(MAILBOX_HOOK_FILES)
    paths.extend(MAILBOX_SUPPORT_FILES)
    return tuple(_portable_path(repo_root / relative) for relative in sorted(set(paths)))


def _repair_packet(entry: FleetRepositoryEntryV1, repo_root: Path, framework_root: Path) -> FleetRepairPacketV1:
    installer = _portable_path(framework_root / "scripts" / "install_governed_repo.py")
    portable_repo_root = _portable_path(repo_root)
    return FleetRepairPacketV1(
        repo_id=entry.repo_id,
        claim_scope=f"mailbox-repair:{entry.repo_id}",
        command=(
            f"python {_shell_quote(installer)} --repo-root {_shell_quote(portable_repo_root)} "
            "--coordination-messages-only --write"
        ),
        paths=_repair_paths(repo_root),
    )


def _repository_request(repo_root: Path, framework_root: Path, framework_revision: str) -> HostInstallationAuditRequestV1:
    codex_adapter = framework_root / "hooks" / "codex" / "notify-coordination-messages.sh"
    claude_adapter = framework_root / "hooks" / "claude" / "notify-coordination-messages.sh"
    if not codex_adapter.is_file() or not claude_adapter.is_file():
        raise MailboxFleetAuditError("canonical mailbox adapter files are missing from framework root")
    virtual_host = repo_root / ".mailbox-fleet-audit-virtual-host"
    return HostInstallationAuditRequestV1(
        codex_config_path=str(virtual_host / "codex.toml"),
        claude_config_path=str(virtual_host / "claude.json"),
        codex_adapter=HostAdapterSpecV1(
            command=str(CODEX_MAILBOX_HOOK["command"]),
            adapter_path=str(repo_root / ".codex" / "hooks" / "notify-coordination-messages.sh"),
            expected_sha256=_sha256(codex_adapter),
        ),
        claude_adapter=HostAdapterSpecV1(
            command=str(MAILBOX_HOOK["command"]),
            adapter_path=str(repo_root / ".claude" / "hooks" / "notify-coordination-messages.sh"),
            expected_sha256=_sha256(claude_adapter),
        ),
        repository_root=str(repo_root),
        framework_revision=framework_revision,
    )


def _audit_entry(
    entry: FleetRepositoryEntryV1, *, framework_root: Path, framework_revision: str
) -> FleetRepositoryReportV1:
    repo_root = _expand(entry.path)
    if _is_excluded(entry):
        return FleetRepositoryReportV1(
            repo_id=entry.repo_id,
            registry_path=entry.path,
            resolved_path=_portable_path(repo_root),
            tier=entry.tier,
            classification="excluded",
            reasons=("explicitly_excluded_from_mailbox_audit",),
            repair_eligible=False,
        )
    if not repo_root.is_dir():
        return FleetRepositoryReportV1(
            repo_id=entry.repo_id,
            registry_path=entry.path,
            resolved_path=_portable_path(repo_root),
            tier=entry.tier,
            classification="unavailable",
            reasons=("repository_path_unavailable",),
            repair_eligible=False,
        )

    reasons: list[str] = []
    authority_known = _authority_known(repo_root)
    if not authority_known:
        reasons.append("authority_unknown")
    dirty = _git_is_dirty(repo_root)
    if dirty is True:
        reasons.append("working_tree_dirty")
    elif dirty is None:
        reasons.append("git_state_unknown")
    try:
        receipt = audit_host_installation(_repository_request(repo_root, framework_root, framework_revision))
    except MailboxInstallationError as exc:
        return FleetRepositoryReportV1(
            repo_id=entry.repo_id,
            registry_path=entry.path,
            resolved_path=_portable_path(repo_root),
            tier=entry.tier,
            classification="drifted",
            reasons=tuple((*reasons, f"mailbox_audit_failed:{exc}")),
            repair_eligible=False,
        )
    repository_surfaces = receipt.repository_surfaces
    states = {surface.configuration_state for surface in repository_surfaces}
    configured = len(repository_surfaces) == 2 and states == {"configured"}
    if not configured:
        reasons.append("repository_mailbox_hook_drift")
        for surface in repository_surfaces:
            if surface.configuration_state != "configured":
                reasons.append(f"{surface.client}:{surface.configuration_state}:{','.join(surface.issues)}")
    classification: FleetClassification = "current" if configured and authority_known else "drifted"
    repair_eligible = classification == "drifted" and authority_known and dirty is False
    packet = _repair_packet(entry, repo_root, framework_root) if repair_eligible else None
    return FleetRepositoryReportV1(
        repo_id=entry.repo_id,
        registry_path=entry.path,
        resolved_path=_portable_path(repo_root),
        tier=entry.tier,
        classification=classification,
        reasons=tuple(reasons),
        repair_eligible=repair_eligible,
        installation_receipt=receipt,
        repair_packet=packet,
    )


def _default_workspace_root(entries: tuple[FleetRepositoryEntryV1, ...]) -> Path | None:
    if not entries:
        return None
    try:
        return Path(os.path.commonpath([str(_expand(entry.path)) for entry in entries]))
    except ValueError:
        return None


def _find_omissions(workspace_root: Path | None, registered: set[Path]) -> tuple[FleetRegistryOmissionV1, ...]:
    if workspace_root is None or not workspace_root.is_dir():
        return ()
    omissions: list[FleetRegistryOmissionV1] = []
    for candidate in sorted(workspace_root.iterdir(), key=lambda path: path.name.lower()):
        if (
            not candidate.is_dir()
            or candidate.is_symlink()
            or candidate.name.startswith(".")
            or candidate.resolve() in registered
        ):
            continue
        if (candidate / ".git").exists() and (candidate / "meta-process.yaml").is_file():
            omissions.append(
                FleetRegistryOmissionV1(
                    resolved_path=_portable_path(candidate),
                    suggested_repo_id=candidate.name,
                )
            )
    return tuple(omissions)


def audit_mailbox_fleet(request: MailboxFleetAuditRequestV1) -> MailboxFleetAuditReportV1:
    """Read every explicit entry and report unregistered governed-looking peers."""

    registry_path = _expand(request.registry_path)
    framework_root = _expand(request.framework_root)
    entries = load_fleet_registry(registry_path)
    reports = tuple(
        _audit_entry(entry, framework_root=framework_root, framework_revision=request.framework_revision) for entry in entries
    )
    workspace_root = _expand(request.workspace_root) if request.workspace_root else _default_workspace_root(entries)
    omissions = _find_omissions(workspace_root, {_expand(entry.path) for entry in entries})
    return MailboxFleetAuditReportV1(
        audited_at=datetime.now(UTC),
        registry_path=_portable_path(registry_path),
        explicit_entry_count=len(entries),
        reports=reports,
        omissions=omissions,
    )
