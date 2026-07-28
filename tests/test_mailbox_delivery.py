"""Deterministic MF-01 tests for host mailbox installation audit and dry-run planning."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from enforced_planning.mailbox_delivery import (
    HostAdapterSpecV1,
    HostInstallationAuditRequestV1,
    HostInstallationPlanRequestV1,
    MailboxInstallationError,
    ObservationEvidenceV1,
    StoredHostInstallationCandidateV1,
    _candidate_content,
    audit_host_installation,
    generate_host_installation_candidate,
    plan_host_installation,
)
from enforced_planning.coordination_messages import MessageReceipt, StoredReceiptRecord, _model_digest


CODEX_COMMAND = "python3 /opt/mailbox/codex_adapter.py"
CLAUDE_COMMAND = "python3 /opt/mailbox/claude_adapter.py"


def _request(tmp_path: Path) -> HostInstallationAuditRequestV1:
    """Build an audit request using only fixture-local paths."""

    codex_adapter = tmp_path / "codex_adapter.py"
    claude_adapter = tmp_path / "claude_adapter.py"
    codex_adapter.write_text("# codex adapter\n", encoding="utf-8")
    claude_adapter.write_text("# claude adapter\n", encoding="utf-8")
    return HostInstallationAuditRequestV1(
        codex_config_path=str(tmp_path / "codex.toml"),
        claude_config_path=str(tmp_path / "claude.json"),
        codex_adapter=HostAdapterSpecV1(
            command=CODEX_COMMAND,
            adapter_path=str(codex_adapter),
            expected_sha256=hashlib.sha256(codex_adapter.read_bytes()).hexdigest(),
        ),
        claude_adapter=HostAdapterSpecV1(
            command=CLAUDE_COMMAND,
            adapter_path=str(claude_adapter),
            expected_sha256=hashlib.sha256(claude_adapter.read_bytes()).hexdigest(),
        ),
    )


def _configured_codex(command: str = CODEX_COMMAND) -> str:
    """Render the canonical Codex fixture with one unrelated hook."""

    return f'''model = "gpt-5"

[[hooks.SessionStart]]
matcher = "startup|resume|clear|compact"
[[hooks.SessionStart.hooks]]
type = "command"
command = "{command}"
timeout = 3
statusMessage = "Checking coordination requests"

[[hooks.UserPromptSubmit]]
matcher = ""
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "{command}"
timeout = 3
statusMessage = "Checking coordination requests"

[[hooks.PostToolUse]]
matcher = "*"
[[hooks.PostToolUse.hooks]]
type = "command"
command = "{command}"
timeout = 3
statusMessage = "Checking coordination requests"

[[hooks.PreToolUse]]
matcher = "^Bash$"
[[hooks.PreToolUse.hooks]]
type = "command"
command = "python3 /opt/other/guard.py"
timeout = 15
'''


def _configured_claude(command: str = CLAUDE_COMMAND) -> dict[str, object]:
    """Return the canonical Claude fixture with one unrelated hook."""

    def entry(matcher: str) -> dict[str, object]:
        return {
            "matcher": matcher,
            "hooks": [
                {
                    "type": "command",
                    "command": command,
                    "timeout": 3,
                }
            ],
        }

    return {
        "permissions": {"allow": ["Read"]},
        "hooks": {
            "SessionStart": [entry("startup|resume|clear|compact")],
            "UserPromptSubmit": [entry("")],
            "PostToolUse": [entry("*")],
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [{"type": "command", "command": "python3 /opt/other/guard.py", "timeout": 15}],
                }
            ],
        },
    }


def test_missing_configs_are_absent_and_dry_run_never_writes(tmp_path: Path) -> None:
    """An absent host config is distinguishable from configuration or runtime proof."""

    request = _request(tmp_path)
    receipt = audit_host_installation(request)
    assert [surface.configuration_state for surface in receipt.host_surfaces] == ["absent", "absent"]
    assert [surface.trust_state for surface in receipt.host_surfaces] == ["unknown", "unknown"]

    plan = plan_host_installation(HostInstallationPlanRequestV1(**request.model_dump()))
    assert plan.will_write is False
    assert plan.backup_required_on_apply is True
    assert plan.atomic_replace_required_on_apply is True
    assert {change.configuration_state_before for change in plan.changes} == {"absent"}
    assert all(not Path(path).exists() for path in (request.codex_config_path, request.claude_config_path))


def test_configured_both_signs_preserve_unrelated_semantic_content(tmp_path: Path) -> None:
    """Both native formats report configured without promoting trust or observation."""

    request = _request(tmp_path)
    Path(request.codex_config_path).write_text(_configured_codex(), encoding="utf-8")
    Path(request.claude_config_path).write_text(json.dumps(_configured_claude()), encoding="utf-8")
    before_codex = Path(request.codex_config_path).read_text(encoding="utf-8")
    before_claude = Path(request.claude_config_path).read_text(encoding="utf-8")

    receipt = audit_host_installation(request)
    assert [surface.configuration_state for surface in receipt.host_surfaces] == ["configured", "configured"]
    assert all(surface.trust_state == "unknown" for surface in receipt.host_surfaces)
    assert receipt.duplicate_delivery_risk is False

    plan = plan_host_installation(HostInstallationPlanRequestV1(**request.model_dump()))
    assert plan.changes == ()
    assert Path(request.codex_config_path).read_text(encoding="utf-8") == before_codex
    assert Path(request.claude_config_path).read_text(encoding="utf-8") == before_claude


def test_drifted_command_and_missing_adapter_are_repairable_not_configured(tmp_path: Path) -> None:
    """Exact command and adapter presence are required for the configured state."""

    request = _request(tmp_path)
    Path(request.codex_config_path).write_text(_configured_codex("python3 /opt/wrong.py"), encoding="utf-8")
    Path(request.claude_config_path).write_text(json.dumps(_configured_claude()), encoding="utf-8")
    Path(request.claude_adapter.adapter_path).unlink()

    receipt = audit_host_installation(request)
    by_client = {surface.client: surface for surface in receipt.host_surfaces}
    assert by_client["codex"].configuration_state == "drifted"
    assert "missing_required_hook" in by_client["codex"].issues
    assert by_client["claude-code"].configuration_state == "drifted"
    assert "adapter_missing" in by_client["claude-code"].issues
    assert receipt.repair_actions


def test_adapter_digest_drift_is_not_reported_as_configured(tmp_path: Path) -> None:
    """An existing adapter must match the accepted digest, not merely exist."""

    request = _request(tmp_path)
    Path(request.codex_config_path).write_text(_configured_codex(), encoding="utf-8")
    Path(request.claude_config_path).write_text(json.dumps(_configured_claude()), encoding="utf-8")
    Path(request.codex_adapter.adapter_path).write_text("# drifted codex adapter\n", encoding="utf-8")

    receipt = audit_host_installation(request)
    codex = next(surface for surface in receipt.host_surfaces if surface.client == "codex")
    assert codex.configuration_state == "drifted"
    assert "adapter_digest_mismatch" in codex.issues


def test_dry_run_candidate_preserves_unrelated_hooks_in_both_native_formats(tmp_path: Path) -> None:
    """A repair candidate adds only missing mailbox hooks and keeps unrelated semantics."""

    request = _request(tmp_path)
    codex = tomllib.loads(_configured_codex())
    codex["projects"] = {"/workspace/project": {"trust_level": "trusted"}}
    codex["hooks"].pop("UserPromptSubmit")
    codex_candidate = _candidate_content(client="codex", config=codex, adapter=request.codex_adapter)
    assert codex_candidate is not None
    parsed_codex = tomllib.loads(codex_candidate[0])
    assert parsed_codex["model"] == "gpt-5"
    assert parsed_codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "python3 /opt/other/guard.py"
    assert "UserPromptSubmit" in parsed_codex["hooks"]
    assert parsed_codex["projects"]["/workspace/project"]["trust_level"] == "trusted"

    claude = _configured_claude()
    claude["hooks"].pop("UserPromptSubmit")
    claude_candidate = _candidate_content(client="claude-code", config=claude, adapter=request.claude_adapter)
    assert claude_candidate is not None
    parsed_claude = json.loads(claude_candidate[0])
    assert parsed_claude["permissions"] == {"allow": ["Read"]}
    assert parsed_claude["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "python3 /opt/other/guard.py"
    assert "UserPromptSubmit" in parsed_claude["hooks"]


def test_host_candidate_binds_exact_bytes_without_retaining_unrelated_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """MF-03A emits portable hashes and never persists unrelated configuration text."""

    monkeypatch.setenv("HOME", str(tmp_path))
    request = _request(tmp_path).model_copy(
        update={
            "codex_config_path": str(tmp_path / ".codex" / "config.toml"),
            "claude_config_path": str(tmp_path / ".claude" / "settings.json"),
            "framework_revision": "candidate-fixture",
        }
    )
    codex_path = Path(request.codex_config_path)
    claude_path = Path(request.claude_config_path)
    codex_path.parent.mkdir()
    claude_path.parent.mkdir()
    codex_path.write_text('model = "gpt-5"\nprivate_value = "do-not-retain"\n', encoding="utf-8")
    claude_path.write_text(
        json.dumps({"unrelated_secret": "do-not-retain", "hooks": {"SessionStart": []}}), encoding="utf-8"
    )
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (codex_path, claude_path)}

    candidate = generate_host_installation_candidate(HostInstallationPlanRequestV1(**request.model_dump()))
    rendered = candidate.model_dump_json()

    assert candidate.record_type == "mailbox_host_candidate"
    assert candidate.payload.framework_revision == "candidate-fixture"
    assert candidate.payload.will_write is False
    assert candidate.payload_sha256
    assert StoredHostInstallationCandidateV1.model_validate_json(rendered) == candidate
    assert [item.state for item in candidate.payload.configs] == ["present", "present"]
    assert [item.before_sha256 for item in candidate.payload.configs] == [before[codex_path], before[claude_path]]
    assert all(item.config_path.startswith("~/") for item in candidate.payload.configs)
    assert str(tmp_path) not in rendered
    assert "do-not-retain" not in rendered
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before} == before


def test_host_candidate_handles_absent_config_without_creating_it(tmp_path: Path) -> None:
    """An absent input is fingerprinted as absent while its proposed bytes are still reviewable."""

    request = _request(tmp_path).model_copy(update={"framework_revision": "candidate-fixture"})

    candidate = generate_host_installation_candidate(HostInstallationPlanRequestV1(**request.model_dump()))

    assert [item.state for item in candidate.payload.configs] == ["absent", "absent"]
    assert all(item.before_sha256 is None for item in candidate.payload.configs)
    assert all(item.proposed_sha256 for item in candidate.payload.configs)
    assert not Path(request.codex_config_path).exists()
    assert not Path(request.claude_config_path).exists()


def test_host_candidate_fails_loudly_on_adapter_digest_drift_or_invalid_envelope(tmp_path: Path) -> None:
    """A candidate cannot bless altered adapters or mismatched payload bytes."""

    request = _request(tmp_path).model_copy(update={"framework_revision": "candidate-fixture"})
    Path(request.codex_adapter.adapter_path).write_text("# altered\n", encoding="utf-8")
    with pytest.raises(MailboxInstallationError, match="adapter_digest_mismatch"):
        generate_host_installation_candidate(HostInstallationPlanRequestV1(**request.model_dump()))

    valid = generate_host_installation_candidate(
        HostInstallationPlanRequestV1(
            **_request(tmp_path).model_copy(update={"framework_revision": "candidate-fixture"}).model_dump()
        )
    )
    with pytest.raises(ValueError, match="payload_sha256 mismatch"):
        StoredHostInstallationCandidateV1(payload=valid.payload, payload_sha256="0" * 64)


def test_host_candidate_requires_exact_framework_revision(tmp_path: Path) -> None:
    """A rollout candidate cannot bind itself to the legacy unknown revision default."""

    request = _request(tmp_path)

    with pytest.raises(MailboxInstallationError, match="exact framework_revision"):
        generate_host_installation_candidate(HostInstallationPlanRequestV1(**request.model_dump()))


def test_observation_evidence_changes_trust_only_not_configuration(tmp_path: Path) -> None:
    """Only an exact receipt supplied by a verifier promotes operational observation."""

    request = _request(tmp_path)
    Path(request.codex_config_path).write_text(_configured_codex(), encoding="utf-8")
    Path(request.claude_config_path).write_text(json.dumps(_configured_claude()), encoding="utf-8")
    receipt = MessageReceipt(
        schema_version="1.0",
        receipt_id="rcpt_0123456789abcdef0123456789abcdef",
        message_id="msg_0123456789abcdef0123456789abcdef",
        recipient_session_id="codex:verified-session",
        event="observed",
        recorded_at=datetime(2026, 7, 27, 20, 0, tzinfo=UTC),
    )
    receipt_path = tmp_path / "observed-receipt.json"
    receipt_path.write_text(
        StoredReceiptRecord(
            record_type="message_receipt", payload=receipt, payload_sha256=_model_digest(receipt)
        ).model_dump_json(),
        encoding="utf-8",
    )
    observed = request.model_copy(
        update={
            "observation_evidence": (
                ObservationEvidenceV1(
                    client="codex",
                    receipt_id="rcpt_0123456789abcdef0123456789abcdef",
                    session_id="codex:verified-session",
                    receipt_path=str(receipt_path),
                ),
            )
        }
    )
    receipt = audit_host_installation(observed)
    by_client = {surface.client: surface for surface in receipt.host_surfaces}
    assert by_client["codex"].configuration_state == "configured"
    assert by_client["codex"].trust_state == "operationally_observed"
    assert by_client["claude-code"].trust_state == "unknown"


def test_observation_evidence_rejects_client_session_mismatch(tmp_path: Path) -> None:
    """A receipt cannot be relabeled from one native client to another."""

    request = _request(tmp_path)
    evidence = ObservationEvidenceV1(
        client="codex",
        receipt_id="rcpt_0123456789abcdef0123456789abcdef",
        session_id="claude-code:wrong-client",
        receipt_path=str(tmp_path / "unused.json"),
    )
    with pytest.raises(MailboxInstallationError, match="client/session mismatch"):
        audit_host_installation(request.model_copy(update={"observation_evidence": (evidence,)}))


def test_repository_receipt_paths_keep_portable_tilde(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Durable repository surface paths do not expose a resolved personal home directory."""

    request = _request(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    receipt = audit_host_installation(request.model_copy(update={"repository_root": "~/consumer"}))
    assert [surface.config_path for surface in receipt.repository_surfaces] == [
        "~/consumer/.codex/hooks.json",
        "~/consumer/.claude/settings.json",
    ]


def test_host_receipt_normalizes_explicit_home_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit host paths and configured commands remain portable in durable output."""

    monkeypatch.setenv("HOME", str(tmp_path))
    codex_config = tmp_path / ".codex" / "config.toml"
    claude_config = tmp_path / ".claude" / "settings.json"
    codex_config.parent.mkdir()
    claude_config.parent.mkdir()
    codex_command = f"python3 {tmp_path}/mailbox/codex_adapter.py"
    codex_config.write_text(_configured_codex(codex_command), encoding="utf-8")
    claude_config.write_text(json.dumps(_configured_claude()), encoding="utf-8")
    request = _request(tmp_path).model_copy(
        update={
            "codex_config_path": str(codex_config),
            "claude_config_path": str(claude_config),
            "codex_adapter": _request(tmp_path).codex_adapter.model_copy(update={"command": codex_command}),
        }
    )

    receipt = audit_host_installation(request)
    codex = next(surface for surface in receipt.host_surfaces if surface.client == "codex")
    assert codex.config_path == "~/.codex/config.toml"
    assert codex.adapter_command == "python3 ~/mailbox/codex_adapter.py"


def test_repository_collision_is_risk_not_runtime_proof(tmp_path: Path) -> None:
    """Host/repository coexistence is visible but does not claim suppression exists."""

    request = _request(tmp_path)
    Path(request.codex_config_path).write_text(_configured_codex(), encoding="utf-8")
    Path(request.claude_config_path).write_text(json.dumps(_configured_claude()), encoding="utf-8")
    repository = tmp_path / "consumer"
    (repository / ".codex").mkdir(parents=True)
    (repository / ".claude").mkdir()
    (repository / ".codex" / "hooks.json").write_text(json.dumps(_configured_claude(CODEX_COMMAND)), encoding="utf-8")
    (repository / ".claude" / "settings.json").write_text(json.dumps(_configured_claude()), encoding="utf-8")

    receipt = audit_host_installation(request.model_copy(update={"repository_root": str(repository)}))
    assert receipt.duplicate_delivery_risk is True
    assert "defer_duplicate_delivery_until_mf02" in receipt.repair_actions
    assert all(surface.trust_state == "unknown" for surface in receipt.repository_surfaces)


def test_audit_and_planner_clis_emit_json_without_writing(tmp_path: Path) -> None:
    """The two public MF-01 commands are stable JSON and have no write flag."""

    request = _request(tmp_path)
    common = [
        "--codex-config",
        request.codex_config_path,
        "--claude-config",
        request.claude_config_path,
        "--codex-command",
        CODEX_COMMAND,
        "--claude-command",
        CLAUDE_COMMAND,
        "--codex-adapter",
        request.codex_adapter.adapter_path,
        "--claude-adapter",
        request.claude_adapter.adapter_path,
        "--codex-adapter-sha256",
        request.codex_adapter.expected_sha256,
        "--claude-adapter-sha256",
        request.claude_adapter.expected_sha256,
    ]
    root = Path(__file__).resolve().parents[1]
    for script in ("audit_mailbox_delivery.py", "install_mailbox_host_adapters.py"):
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / script), *common],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["schema_version"].startswith("mailbox_installation_")
    candidate = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "install_mailbox_host_adapters.py"),
            *common,
            "--candidate",
            "--framework-revision",
            "candidate-fixture",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert candidate.returncode == 0, candidate.stderr
    candidate_payload = json.loads(candidate.stdout)
    assert candidate_payload["record_type"] == "mailbox_host_candidate"
    assert candidate_payload["payload"]["will_write"] is False
    assert not Path(request.codex_config_path).exists()
    assert not Path(request.claude_config_path).exists()


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("codex.toml", "[hooks\n"),
        ("claude.json", "{not valid json"),
    ],
)
def test_malformed_host_config_fails_loud_before_a_plan(tmp_path: Path, filename: str, content: str) -> None:
    """Malformed JSON or TOML is never silently repaired or overwritten."""

    request = _request(tmp_path)
    (tmp_path / filename).write_text(content, encoding="utf-8")
    with pytest.raises(MailboxInstallationError, match="invalid"):
        audit_host_installation(request)
    with pytest.raises(MailboxInstallationError, match="invalid"):
        plan_host_installation(HostInstallationPlanRequestV1(**request.model_dump()))
