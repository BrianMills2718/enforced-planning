"""Host wiring checks; real provider semantics are verified by CP probes."""
import json
from pathlib import Path

import pytest
import yaml

from enforced_planning import trace_review_provider as provider
from enforced_planning.prewrite_claim_projection import write_projection
from scripts import complete_plan
from tests.test_host_prewrite_claim_gate import _fixture, _payload, _run_cli


@pytest.mark.parametrize("client", ["codex", "claude-code"])
@pytest.mark.parametrize("mode", ["off", "observe", "enforce"])
def test_ordinary_edit_cannot_escape_repair_admission_from_workspace_cwd(tmp_path, monkeypatch, capsys, client, mode):
    workspace, _, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text())
    claim.update(agent=client, session_id=f"{client}:host-gate-test")
    claim_path.write_text(yaml.safe_dump(claim))
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    calls = []
    def deny(root, operation, session_id, registry):
        calls.append((root, operation, session_id, registry))
        return {"mode": "enforce", "disposition": "deny", "valid": False,
                "errors": ["fixture: preserved failure requires its full review"]}
    monkeypatch.setattr(provider, "admit", deny)
    payload = _payload(cwd=workspace, tool="Edit", tool_input={"file_path": str(worktree / "src/allowed.py")})
    if client == "codex":
        payload = _payload(cwd=workspace, tool="apply_patch", tool_input={"command":
            f"*** Begin Patch\n*** Update File: {worktree / 'src/allowed.py'}\n@@\n-VALUE = 1\n+VALUE = 2\n*** End Patch\n"})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir,
                             projection_path=tmp_path / "projection.json", client=client, mode=mode)
    assert code == 2
    assert decision["decision"] == "deny"
    assert decision["reason_code"] == "trace_review_required"
    assert calls == [(worktree, "repair", f"{client}:host-gate-test", claims_dir)]
    receipts = [json.loads(line) for line in (tmp_path / "receipts.jsonl").read_text().splitlines()]
    assert receipts[-1]["decision"] == "deny"
    assert receipts[-1]["trace_review"]["valid"] is False


def test_read_only_diagnosis_does_not_invoke_repair_guard(tmp_path, monkeypatch, capsys):
    workspace, _, worktree, claims_dir, _ = _fixture(tmp_path)
    def forbidden(*args):
        raise AssertionError("read-only diagnosis reached repair admission")
    monkeypatch.setattr(provider, "admit", forbidden)
    payload = _payload(cwd=worktree, tool="Bash", tool_input={"command": "git status --short"})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir,
                             projection_path=tmp_path / "projection.json")
    assert code == 0
    assert decision["reason_code"] == "bash_read_only"


@pytest.mark.parametrize("mode", ["off", "observe"])
def test_mixed_worktree_patch_cannot_borrow_unenrolled_launch_directory(tmp_path, monkeypatch, capsys, mode):
    workspace, repo, worktree, claims_dir, _ = _fixture(tmp_path)
    (worktree / "meta-process.yaml").write_text("meta_process:\n  trace_review:\n    mode: enforce\n")
    payload = _payload(cwd=workspace, tool="apply_patch", tool_input={"command":
        f"*** Begin Patch\n*** Update File: {worktree / 'src/allowed.py'}\n@@\n-VALUE = 1\n+VALUE = 2\n"
        f"*** Update File: {repo / 'README.md'}\n@@\n-seed\n+changed\n*** End Patch\n"})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir,
                             projection_path=tmp_path / "projection.json", client="codex", mode=mode)
    assert code == 2
    assert decision["trace_review"]["disposition"] == "deny"
    assert decision["reason_code"] == "trace_review_required"


def test_already_completed_plan_cannot_bypass_enabled_trace_guard(tmp_path, monkeypatch):
    plans = tmp_path / "docs/plans"
    plans.mkdir(parents=True)
    plan = plans / "12_fixture.md"
    plan.write_text("# Fixture\nStatus: Complete\n")
    original = plan.read_bytes()
    monkeypatch.setattr(provider, "admit", lambda *args, **kwargs: {
        "mode": "enforce", "disposition": "deny", "valid": False, "errors": ["missing review"]})
    assert complete_plan.complete_plan(12, tmp_path, verbose=False) is False
    assert plan.read_bytes() == original


def test_missing_cursor_and_disabled_gate_are_reported_uncovered(tmp_path):
    result = provider.admit(tmp_path, "repair", "codex:fixture", tmp_path / "claims")
    assert result["disposition"] == "uncovered"
    assert result["valid"] is False


def test_enabled_missing_provider_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(provider.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "meta-process.yaml").write_text("meta_process:\n  trace_review:\n    mode: enforce\n")
    result = provider.admit(tmp_path, "repair", "codex:fixture", tmp_path / "claims")
    assert result["disposition"] == "deny"
    assert any("must pin" in e for e in result["errors"])


def test_enrolled_cursor_reuses_existing_shared_pin_without_claiming_coverage(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(provider.Path, "home", classmethod(lambda cls: home))
    shared = home / ".config/aes/trace-review.json"
    shared.parent.mkdir(parents=True)
    command = ["/usr/bin/python3", "~/explicitly-pinned-provider.py"]
    shared.write_text(json.dumps({"command": command}))
    cursor = tmp_path / ".company-planning/active-execution.json"
    cursor.parent.mkdir()
    cursor.write_text("{}")
    assert provider.configuration(tmp_path) == {"mode": "enforce", "command": command}
    assert provider.admit(tmp_path, "repair", "codex:fixture", tmp_path / "claims")["disposition"] == "deny"


def test_untrusted_provider_is_refused_without_running_it(tmp_path):
    script = tmp_path / "untrusted.py"
    script.write_text("raise AssertionError('must not run')\n")
    (tmp_path / "meta-process.yaml").write_text(yaml.safe_dump({"meta_process": {"trace_review": {
        "mode": "enforce", "command": ["/usr/bin/python3", str(script)]}}}))
    result = provider.admit(tmp_path, "repair", "codex:fixture", tmp_path / "claims")
    assert result["disposition"] == "deny"
    assert result["valid"] is False
