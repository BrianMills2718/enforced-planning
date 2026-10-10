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
    assert len(receipts) == 1
    assert receipts[-1]["decision"] == "deny"
    assert receipts[-1]["trace_review"]["valid"] is False


@pytest.mark.parametrize("client", ["codex", "claude-code"])
@pytest.mark.parametrize("mode", ["off", "observe", "enforce"])
@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("form", ["-C", "--chdir", "--chdir="])
def test_unclaimed_explicit_shell_target_cannot_borrow_launch_coverage(tmp_path, monkeypatch, capsys, client, mode, relative, form):
    _, launch, target, claims_dir, claim_path = _fixture(tmp_path)
    claim_path.unlink()
    (launch / "meta-process.yaml").write_text("meta_process:\n  trace_review:\n    mode: off\n")
    (target / "meta-process.yaml").write_text("meta_process:\n  trace_review:\n    mode: enforce\n")
    monkeypatch.setattr(provider.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    calls = []
    real_admit = provider.admit
    def record_admission(root, operation, session_id, registry):
        calls.append(root)
        return real_admit(root, operation, session_id, registry)
    monkeypatch.setattr(provider, "admit", record_admission)
    operand = target.relative_to(launch) if relative else target
    binding = f"{form}{operand}" if form.endswith("=") else f"{form} {operand}"
    payload = _payload(cwd=launch, tool="Bash", tool_input={"command":
        f"/usr/bin/env {binding} touch TRACE_REVIEW_SENTINEL_NOT_EXECUTED"})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir,
                             projection_path=tmp_path / "projection.json", client=client, mode=mode)
    assert code == 2 and decision["decision"] == "deny"
    if mode == "enforce":
        assert decision["reason_code"] == "target_worktree_not_claimed"
        assert calls == []
    else:
        assert calls == [target]
        assert decision["reason_code"] == "trace_review_required"
        assert decision["trace_review"]["mode"] == "enforce"
        assert decision["trace_review"]["disposition"] == "deny"
    assert not (target / "TRACE_REVIEW_SENTINEL_NOT_EXECUTED").exists()


@pytest.mark.parametrize("client", ["codex", "claude-code"])
@pytest.mark.parametrize("mode", ["off", "observe"])
def test_enforced_trace_cannot_authorize_an_unprovable_shell_destination(tmp_path, monkeypatch, capsys, client, mode):
    _, launch, _, claims_dir, claim_path = _fixture(tmp_path)
    claim_path.unlink()
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    monkeypatch.setattr(provider, "admit", lambda *_args, **_kwargs: {
        "mode": "enforce", "disposition": "allow", "valid": True, "errors": []})
    payload = _payload(cwd=launch, tool="Bash", tool_input={"command":
        'printf repaired > "$REPAIR_DESTINATION"'})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir,
                             projection_path=tmp_path / "projection.json", client=client, mode=mode)
    assert code == 2 and decision["decision"] == "deny"
    assert decision["reason_code"] == "trace_review_required"
    assert decision["trace_review"]["disposition"] == "deny"
    assert "trace admission requires a provable shell target worktree" in decision["trace_review"]["errors"]


@pytest.mark.parametrize("client", ["codex", "claude-code"])
@pytest.mark.parametrize("form", ["-C", "--chdir", "--chdir="])
@pytest.mark.parametrize("repeated", [False, True])
def test_claimed_relative_shell_target_preserves_launch_and_admits_the_right_worktree(tmp_path, monkeypatch, capsys, client, form, repeated):
    _, launch, target, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text())
    claim.update(agent=client, session_id=f"{client}:host-gate-test")
    claim_path.write_text(yaml.safe_dump(claim))
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    calls = []
    def admit(root, operation, session_id, registry):
        calls.append((root, session_id))
        return {"mode": "enforce", "disposition": "allow", "valid": True, "errors": []}
    monkeypatch.setattr(provider, "admit", admit)
    operand = target.relative_to(launch)
    binding = f"{form}{operand}" if form.endswith("=") else f"{form} {operand}"
    if repeated:
        binding = f"-C {launch} {binding}"
    payload = _payload(cwd=launch, tool="Bash", tool_input={"command":
        f"/usr/bin/env {binding} touch src/allowed.py"})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir,
                             projection_path=tmp_path / "projection.json", client=client, mode="enforce")
    assert code == 0 and decision["decision"] == "allow"
    assert decision["worktree_path"] == str(target)
    assert decision["trace_review"]["disposition"] == "allow"
    assert calls == [(target, f"{client}:host-gate-test")]
    assert (target / "src/allowed.py").read_text() == "VALUE = 1\n"


@pytest.mark.parametrize("client", ["codex", "claude-code"])
@pytest.mark.parametrize("mode", ["off", "observe", "enforce"])
@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("forms", [("-C", "-C"), ("-C", "--chdir"), ("--chdir=", "-C"), ("-C", "--chdir="), ("-C", "-Cjoined")])
def test_repeated_env_directories_admit_the_actual_final_target(tmp_path, monkeypatch, capsys, client, mode, relative, forms):
    from enforced_planning.prewrite_claim_fast import _bash_explicit_worktree
    _, launch, target, claims_dir, claim_path = _fixture(tmp_path)
    claim_path.unlink()
    (launch / "meta-process.yaml").write_text("meta_process:\n  trace_review:\n    mode: off\n")
    (target / "meta-process.yaml").write_text("meta_process:\n  trace_review:\n    mode: enforce\n")
    monkeypatch.setattr(provider.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    calls = []
    real_admit = provider.admit
    def admit(root, *args):
        calls.append(root)
        return real_admit(root, *args)
    monkeypatch.setattr(provider, "admit", admit)
    def binding(form, operand):
        if form == "-Cjoined":
            return f"-C{operand}"
        return f"{form}{operand}" if form.endswith("=") else f"{form} {operand}"
    final = target.relative_to(launch) if relative else target
    command = f"/usr/bin/env {binding(forms[0], launch)} {binding(forms[1], final)} touch TRACE_REVIEW_SENTINEL_NOT_EXECUTED"
    assert _bash_explicit_worktree(command, cwd=tmp_path) == target
    payload = _payload(cwd=launch, tool="Bash", tool_input={"command": command})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir,
                             projection_path=tmp_path / "projection.json", client=client, mode=mode)
    assert code == 2 and decision["decision"] == "deny"
    if mode != "enforce":
        assert calls == [target]
        assert decision["reason_code"] == "trace_review_required"
    assert not (target / "TRACE_REVIEW_SENTINEL_NOT_EXECUTED").exists()


@pytest.mark.parametrize("client", ["codex", "claude-code"])
@pytest.mark.parametrize("mode", ["off", "observe"])
@pytest.mark.parametrize("form", ["cd", "-C", "--chdir", "--chdir="])
@pytest.mark.parametrize("suffix", ["&& true", "; true", "|| true"])
def test_compound_shell_cannot_borrow_uncovered_launch_for_an_enforced_path(tmp_path, monkeypatch, capsys, client, mode, form, suffix):
    _, launch, target, claims_dir, claim_path = _fixture(tmp_path)
    claim_path.unlink()
    (launch / "meta-process.yaml").write_text("meta_process:\n  trace_review:\n    mode: off\n")
    (target / "meta-process.yaml").write_text("meta_process:\n  trace_review:\n    mode: enforce\n")
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    if form == "cd":
        command = f"cd {target} && touch TRACE_REVIEW_SENTINEL_NOT_EXECUTED {suffix}"
    else:
        binding = f"{form}{target}" if form.endswith("=") else f"{form} {target}"
        command = f"/usr/bin/env {binding} touch TRACE_REVIEW_SENTINEL_NOT_EXECUTED {suffix}"
    payload = _payload(cwd=launch, tool="Bash", tool_input={"command": command})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir,
                             projection_path=tmp_path / "projection.json", client=client, mode=mode)
    assert code == 2 and decision["decision"] == "deny"
    assert decision["reason_code"] == "trace_review_required"
    assert decision["trace_review"]["mode"] == "enforce"
    assert decision["trace_review"]["disposition"] == "deny"
    assert any("another enforced trace target" in error for error in decision["trace_review"]["errors"])
    assert not (target / "TRACE_REVIEW_SENTINEL_NOT_EXECUTED").exists()


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


@pytest.mark.parametrize("client", ["codex", "claude-code"])
def test_outcome_allow_cannot_override_trace_denial(tmp_path, monkeypatch, capsys, client):
    from scripts import prewrite_claim_gate as gate
    workspace, _, worktree, claims_dir, claim_path = _fixture(tmp_path)
    claim = yaml.safe_load(claim_path.read_text())
    claim.update(agent=client, session_id=f"{client}:host-gate-test")
    claim_path.write_text(yaml.safe_dump(claim))
    write_projection(claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    monkeypatch.setattr(gate, "_resolved_outcome_mode", lambda *_args, **_kwargs: "enforce_selected")
    monkeypatch.setattr(gate, "_sanctioned_maintenance_exemption", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gate, "_enforce_selected_outcome", lambda *_args, **_kwargs: {"result": {"decision": {"disposition": "allow"}}})
    monkeypatch.setattr(provider, "admit", lambda *_args, **_kwargs: {"mode": "enforce", "disposition": "deny", "valid": False, "errors": ["missing full trace review"]})
    payload = _payload(cwd=worktree, tool="Edit", tool_input={"file_path": str(worktree / "src/allowed.py")})
    if client == "codex":
        payload = _payload(cwd=worktree, tool="apply_patch", tool_input={"command": f"*** Begin Patch\n*** Update File: {worktree / 'src/allowed.py'}\n@@\n-VALUE = 1\n+VALUE = 2\n*** End Patch\n"})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir, projection_path=tmp_path / "projection.json", client=client)
    assert decision["outcome_admission"]["result"]["decision"]["disposition"] == "allow"
    assert decision["trace_review"]["disposition"] == "deny"
    assert decision["decision"] == "deny" and code == 2


def test_disabled_trace_admission_retains_uncovered_receipt(tmp_path, monkeypatch, capsys):
    _, _, worktree, claims_dir, _ = _fixture(tmp_path)
    monkeypatch.setattr(provider, "admit", lambda *_args, **_kwargs: {"mode": "off", "disposition": "uncovered", "valid": False, "errors": []})
    payload = _payload(cwd=worktree, tool="Edit", tool_input={"file_path": str(worktree / "src/allowed.py")})
    code, decision = _run_cli(monkeypatch, capsys, tmp_path, payload, claims_dir=claims_dir, projection_path=tmp_path / "projection.json")
    assert code == 0 and decision["trace_review"]["disposition"] == "uncovered"
    receipt = json.loads((tmp_path / "receipts.jsonl").read_text().splitlines()[-1])
    assert receipt["trace_review"]["disposition"] == "uncovered"
