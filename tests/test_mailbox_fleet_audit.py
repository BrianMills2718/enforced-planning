"""Deterministic MF-04 coverage for the read-only mailbox fleet audit."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from enforced_planning.hook_wiring import CODEX_MAILBOX_HOOK, MAILBOX_HOOK
from enforced_planning.mailbox_fleet_audit import MailboxFleetAuditRequestV1, audit_mailbox_fleet


ROOT = Path(__file__).resolve().parents[1]


def _hook_block(command: str, matcher: str) -> dict[str, object]:
    return {"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 3}]}


def _configured_hooks(command: str) -> dict[str, object]:
    return {
        "hooks": {
            "SessionStart": [_hook_block(command, "startup|resume|clear|compact")],
            "UserPromptSubmit": [_hook_block(command, "")],
            "PostToolUse": [_hook_block(command, "*")],
        }
    }


def _repo(tmp_path: Path, name: str, *, configured: bool, governed: bool = True) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=repo, check=True)
    (repo / "CLAUDE.md").write_text("# fixture\n", encoding="utf-8")
    if governed:
        (repo / "meta-process.yaml").write_text("version: 1\n", encoding="utf-8")
    for client in ("codex", "claude"):
        source = ROOT / "hooks" / client / "notify-coordination-messages.sh"
        destination = repo / f".{client}" / "hooks" / "notify-coordination-messages.sh"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    if configured:
        (repo / ".codex").mkdir(exist_ok=True)
        (repo / ".claude").mkdir(exist_ok=True)
        (repo / ".codex" / "hooks.json").write_text(
            json.dumps(_configured_hooks(str(CODEX_MAILBOX_HOOK["command"]))), encoding="utf-8"
        )
        (repo / ".claude" / "settings.json").write_text(
            json.dumps(_configured_hooks(str(MAILBOX_HOOK["command"]))), encoding="utf-8"
        )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    return repo


def _registry(tmp_path: Path, entries: list[dict[str, str]]) -> Path:
    path = tmp_path / "governed_repos.yaml"
    lines = ["version: 1", "repos:"]
    for entry in entries:
        first_key, first_value = next(iter(entry.items()))
        lines.append(f"  - {first_key}: {first_value}")
        lines.extend(f"    {key}: {value}" for key, value in list(entry.items())[1:])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _request(registry: Path, workspace: Path) -> MailboxFleetAuditRequestV1:
    return MailboxFleetAuditRequestV1(
        registry_path=str(registry), framework_root=str(ROOT), workspace_root=str(workspace), framework_revision="fixture",
    )


def test_fleet_audits_every_explicit_entry_and_separates_registry_omissions(tmp_path: Path) -> None:
    """Current, drifted, unavailable, excluded, and omitted are distinct read-only facts."""

    current = _repo(tmp_path, "current", configured=True)
    drifted = _repo(tmp_path, "drifted", configured=False)
    omitted = _repo(tmp_path, "Digimon_for_KG_application", configured=True)
    registry = _registry(
        tmp_path,
        [
            {"id": "current", "path": str(current), "tier": "governed"},
            {"id": "drifted", "path": str(drifted), "tier": "governed"},
            {"id": "missing", "path": str(tmp_path / "missing"), "tier": "governed"},
            {"id": "archive", "path": str(tmp_path / "archive"), "tier": "archived"},
        ],
    )
    before = {
        path: path.stat().st_mtime_ns
        for path in (*current.rglob("*"), *drifted.rglob("*"))
        if path.is_file() and ".git" not in path.parts
    }

    report = audit_mailbox_fleet(_request(registry, tmp_path))

    assert report.write_performed is False
    assert report.explicit_entry_count == 4
    reports = {item.repo_id: item for item in report.reports}
    assert reports["current"].classification == "current"
    assert reports["current"].repair_packet is None
    assert reports["drifted"].classification == "drifted"
    assert reports["drifted"].repair_eligible is True
    packet = reports["drifted"].repair_packet
    assert packet is not None
    assert packet.will_execute is False
    assert packet.claim_scope == "mailbox-repair:drifted"
    assert "--coordination-messages-only --write" in packet.command
    assert str(drifted / ".codex" / "hooks.json") in packet.paths
    assert reports["missing"].classification == "unavailable"
    assert reports["archive"].classification == "excluded"
    assert [(item.suggested_repo_id, item.reason) for item in report.omissions] == [
        (omitted.name, "governed_marker_not_registered")
    ]
    assert {path: path.stat().st_mtime_ns for path in before} == before


def test_dirty_and_authority_unknown_repositories_are_reported_but_not_repairable(tmp_path: Path) -> None:
    """The auditor emits no mutation packet for a dirty or authority-unknown checkout."""

    dirty = _repo(tmp_path, "dirty", configured=False)
    (dirty / "uncommitted.txt").write_text("local work\n", encoding="utf-8")
    unknown = _repo(tmp_path, "unknown", configured=False, governed=False)
    registry = _registry(
        tmp_path,
        [
            {"id": "dirty", "path": str(dirty), "tier": "governed"},
            {"id": "unknown", "path": str(unknown), "tier": "governed"},
        ],
    )

    reports = {item.repo_id: item for item in audit_mailbox_fleet(_request(registry, tmp_path)).reports}

    assert reports["dirty"].classification == "drifted"
    assert "working_tree_dirty" in reports["dirty"].reasons
    assert reports["dirty"].repair_packet is None
    assert reports["unknown"].classification == "drifted"
    assert "authority_unknown" in reports["unknown"].reasons
    assert reports["unknown"].repair_packet is None


def test_fleet_audit_cli_emits_json_and_does_not_modify_registered_repositories(tmp_path: Path) -> None:
    """The public one-command audit has no write flag and leaves a drifted repo untouched."""

    drifted = _repo(tmp_path, "drifted", configured=False)
    registry = _registry(tmp_path, [{"id": "drifted", "path": str(drifted), "tier": "governed"}])
    before = sorted(path.relative_to(drifted).as_posix() for path in drifted.rglob("*") if path.is_file())
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_mailbox_fleet.py"),
            "--registry",
            str(registry),
            "--framework-root",
            str(ROOT),
            "--workspace-root",
            str(tmp_path),
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "mailbox_fleet_audit.v1"
    assert payload["write_performed"] is False
    assert payload["reports"][0]["classification"] == "drifted"
    assert sorted(path.relative_to(drifted).as_posix() for path in drifted.rglob("*") if path.is_file()) == before
