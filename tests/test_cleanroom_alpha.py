"""Tests for the loop-engineering clean-room alpha fixture."""

from __future__ import annotations

import json
import hashlib
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from enforced_planning.cleanroom_alpha import CleanroomError
from enforced_planning.cleanroom_alpha import CleanroomSpec
from enforced_planning.cleanroom_alpha import RECEIPT_RELATIVE_PATH
from enforced_planning.cleanroom_alpha import TRACE_DIRECTORY_RELATIVE_PATH
from enforced_planning.cleanroom_alpha import materialize_cleanroom
from enforced_planning.cleanroom_alpha import plan_cleanroom
from enforced_planning.cleanroom_alpha import reset_cleanroom
from enforced_planning.cleanroom_alpha import run_demo_loop
from enforced_planning.cleanroom_alpha import status_cleanroom
from enforced_planning.cleanroom_alpha import verify_cleanroom
from enforced_planning.cleanroom_alpha import verify_loop_trace


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "cleanroom_alpha.py"


def _resign_receipt(payload: dict[str, object]) -> dict[str, object]:
    """Recompute the public receipt digest so path guards are tested independently."""

    unsigned = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {**unsigned, "receipt_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def _spec(tmp_path: Path) -> CleanroomSpec:
    """Return a valid clean-room spec rooted outside the synthetic projects root."""

    projects_root = tmp_path / "workspace" / "projects"
    projects_root.mkdir(parents=True)
    return CleanroomSpec.build(
        root=tmp_path / "external" / "cleanroom",
        component_revision="test-revision",
        projects_root=projects_root,
    )


def test_plan_rejects_workspace_root(tmp_path: Path) -> None:
    """The planned clean-room root cannot live under the projects workspace."""

    projects_root = tmp_path / "projects"
    with pytest.raises(CleanroomError) as exc_info:
        CleanroomSpec.build(
            root=projects_root / "loop-engineering-cleanroom",
            component_revision="test-revision",
            projects_root=projects_root,
        )

    assert exc_info.value.code == "root_under_workspace"


def test_materialize_verify_status_and_reset(tmp_path: Path) -> None:
    """The happy path plans, applies, verifies, reports status, and resets."""

    spec = _spec(tmp_path)
    plan = plan_cleanroom(spec)

    assert plan.verdict == "planned"
    assert "README.md" in {entry.relative_path for entry in plan.writes}
    assert not spec.root.exists()

    receipt = materialize_cleanroom(spec)
    assert receipt.verdict == "materialized"
    assert receipt.root == "."
    assert (spec.root / RECEIPT_RELATIVE_PATH).exists()

    report = verify_cleanroom(spec.root, projects_root=spec.projects_root)
    assert report.verdict == "pass"
    assert report.findings == []

    status = status_cleanroom(spec.root)
    assert status.verdict == "materialized"

    reset = reset_cleanroom(spec.root)
    assert reset.verdict == "reset"
    assert "README.md" in reset.removed_paths
    assert status_cleanroom(spec.root).verdict == "absent"


def test_apply_refuses_foreign_overwrite(tmp_path: Path) -> None:
    """Apply fails loudly instead of overwriting a pre-existing foreign file."""

    spec = _spec(tmp_path)
    spec.root.mkdir(parents=True)
    (spec.root / "README.md").write_text("foreign content\n", encoding="utf-8")

    with pytest.raises(CleanroomError) as exc_info:
        materialize_cleanroom(spec)

    assert exc_info.value.code == "foreign_overwrite"
    assert exc_info.value.path == "README.md"


def test_verify_rejects_secret_sentinel(tmp_path: Path) -> None:
    """Verification fails when a generated tree contains a secret sentinel."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    (spec.root / "policy-pack" / "registry.yaml").write_text("SECRET_SENTINEL\n", encoding="utf-8")

    report = verify_cleanroom(spec.root, projects_root=spec.projects_root)

    assert report.verdict == "fail"
    assert any(finding.check_id == "no_secret_sentinel" for finding in report.findings)


def test_verify_rejects_symlink_into_workspace(tmp_path: Path) -> None:
    """Verification fails when a symlink points into the projects workspace."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    target = spec.projects_root / "private-project"
    target.mkdir(parents=True)
    (spec.root / "projects" / "hello-app" / "private-link").symlink_to(target)

    report = verify_cleanroom(spec.root, projects_root=spec.projects_root)

    assert report.verdict == "fail"
    assert any(finding.check_id == "no_workspace_symlinks" for finding in report.findings)


def test_verify_rejects_undeclared_project(tmp_path: Path) -> None:
    """Only the two synthetic projects are discoverable."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    (spec.root / "projects" / "extra-project").mkdir()

    report = verify_cleanroom(spec.root, projects_root=spec.projects_root)

    assert report.verdict == "fail"
    assert any(finding.check_id == "synthetic_inventory" for finding in report.findings)


def test_reset_rejects_tampered_receipt_escape(tmp_path: Path) -> None:
    """Reset refuses receipt-owned paths that escape the clean-room root."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    receipt_path = spec.root / RECEIPT_RELATIVE_PATH
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["owned_files"].append("../outside.txt")
    receipt_path.write_text(json.dumps(_resign_receipt(payload)), encoding="utf-8")

    report = reset_cleanroom(spec.root)

    assert report.verdict == "fail"
    assert any(finding.check_id == "receipt_path_escape" for finding in report.findings)


def test_reset_rejects_tampered_same_root_foreign_file(tmp_path: Path) -> None:
    """Reset refuses a same-root foreign file injected into the ownership receipt."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    foreign_path = spec.root / "foreign.txt"
    foreign_path.write_text("must survive\n", encoding="utf-8")
    receipt_path = spec.root / RECEIPT_RELATIVE_PATH
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["owned_files"].append("foreign.txt")
    receipt_path.write_text(json.dumps(_resign_receipt(payload)), encoding="utf-8")

    report = reset_cleanroom(spec.root)

    assert report.verdict == "fail"
    assert any(finding.check_id == "receipt_foreign_path" for finding in report.findings)
    assert foreign_path.read_text(encoding="utf-8") == "must survive\n"


def test_run_demo_repairs_known_failure_and_stops_on_verifier(tmp_path: Path) -> None:
    """The deterministic loop observes failure, repairs it, and stops on verification."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    initial = subprocess.run(["make", "verify"], cwd=spec.root, text=True, capture_output=True)
    assert initial.returncode != 0

    receipt = run_demo_loop(spec.root)

    assert receipt.verdict == "pass"
    assert receipt.status == "completed"
    assert receipt.stop_reason == "verifier_satisfied"
    assert receipt.iterations_used == 1
    assert [transition.verifier_verdict for transition in receipt.transitions] == ["fail", "pass"]
    assert receipt.transitions[0].action_status == "applied"
    assert receipt.transitions[0].state_before_sha256 != receipt.transitions[0].state_after_sha256
    assert receipt.cost_used_usd == 0
    assert subprocess.run(["make", "verify"], cwd=spec.root, check=False).returncode == 0

    trace_path = spec.root / TRACE_DIRECTORY_RELATIVE_PATH / f"{receipt.run_id}.json"
    trace_report = verify_loop_trace(trace_path)
    assert trace_report.verdict == "pass"


def test_run_demo_rejects_self_certification(tmp_path: Path) -> None:
    """Worker success claims never substitute for an independent verifier pass."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)

    receipt = run_demo_loop(spec.root, worker_mode="self-certify", max_iterations=1)

    assert receipt.verdict == "fail"
    assert receipt.stop_reason == "iteration_budget_exhausted"
    assert receipt.transitions[0].action_status == "self_certification_rejected"
    assert all(transition.verifier_verdict == "fail" for transition in receipt.transitions)


def test_run_demo_exhausts_iteration_budget_on_noop_worker(tmp_path: Path) -> None:
    """Repeated failure stops exactly at the configured iteration budget."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)

    receipt = run_demo_loop(spec.root, worker_mode="no-op", max_iterations=2)

    assert receipt.verdict == "fail"
    assert receipt.stop_reason == "iteration_budget_exhausted"
    assert receipt.iterations_used == 2
    assert [item.action_status for item in receipt.transitions[:-1]] == ["no_op", "no_op"]


def test_run_demo_rejects_tampered_verifier(tmp_path: Path) -> None:
    """The runner checks verifier source integrity before trusting its verdict."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    makefile = spec.root / "Makefile"
    makefile.write_text(makefile.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    with pytest.raises(CleanroomError) as exc_info:
        run_demo_loop(spec.root)

    assert exc_info.value.code == "verifier_integrity_failed"
    assert exc_info.value.path == "Makefile"


def test_run_demo_records_exact_worker_action_failure(tmp_path: Path) -> None:
    """A failed declarative precondition remains diagnosable in the receipt."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    expected = spec.root / "projects" / "hello-app" / "src" / "expected_message.txt"
    expected.write_text("a different wrong value\n", encoding="utf-8")

    receipt = run_demo_loop(spec.root)

    assert receipt.verdict == "fail"
    assert receipt.stop_reason == "worker_action_failed"
    assert receipt.transitions[-1].action_error_code == "worker_precondition_failed"
    assert receipt.transitions[-1].action_error_path == "projects/hello-app/src/expected_message.txt"


def test_verify_loop_trace_rejects_tamper(tmp_path: Path) -> None:
    """Mutating a completed canonical receipt breaks its digest validation."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)
    receipt = run_demo_loop(spec.root)
    trace_path = spec.root / TRACE_DIRECTORY_RELATIVE_PATH / f"{receipt.run_id}.json"
    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    payload["stop_reason"] = "tampered"
    trace_path.write_text(json.dumps(payload), encoding="utf-8")

    report = verify_loop_trace(trace_path)

    assert report.verdict == "fail"
    assert any(finding.check_id == "trace_digest" for finding in report.findings)


def test_interruption_receipt_is_valid_and_not_successful(tmp_path: Path) -> None:
    """An interruption after mutation persists truth without inferring success."""

    spec = _spec(tmp_path)
    materialize_cleanroom(spec)

    receipt = run_demo_loop(spec.root, worker_mode="interrupt-after-action")

    assert receipt.verdict == "fail"
    assert receipt.status == "interrupted"
    assert receipt.stop_reason == "interrupted_after_action"
    assert receipt.transitions[-1].action_status == "applied"
    assert verify_loop_trace(
        spec.root / TRACE_DIRECTORY_RELATIVE_PATH / f"{receipt.run_id}.json"
    ).verdict == "pass"
    assert subprocess.run(["make", "verify"], cwd=spec.root, check=False).returncode == 0


def test_generic_runner_has_no_fixture_specific_behavior() -> None:
    """The generic runner consumes declarative actions instead of fixture names."""

    source = inspect.getsource(run_demo_loop)

    assert "hello-app" not in source
    assert "shared-lib" not in source
    assert "expected_message" not in source


def test_cli_json_smoke(tmp_path: Path) -> None:
    """The CLI exposes agent-drivable JSON for every Slice 1 command."""

    root = tmp_path / "external" / "cleanroom"
    projects_root = tmp_path / "workspace" / "projects"
    projects_root.mkdir(parents=True)
    common = [
        sys.executable,
        str(SCRIPT),
        "--root",
        str(root),
        "--projects-root",
        str(projects_root),
        "--component-revision",
        "test-revision",
        "--json",
    ]

    plan = subprocess.run(common + ["plan"], check=True, text=True, capture_output=True)
    assert json.loads(plan.stdout)["verdict"] == "planned"

    apply = subprocess.run(common + ["apply"], check=True, text=True, capture_output=True)
    assert json.loads(apply.stdout)["verdict"] == "materialized"

    verify = subprocess.run(common + ["verify"], check=True, text=True, capture_output=True)
    assert json.loads(verify.stdout)["verdict"] == "pass"

    status = subprocess.run(common + ["status"], check=True, text=True, capture_output=True)
    assert json.loads(status.stdout)["verdict"] == "materialized"

    run_demo = subprocess.run(common + ["run-demo"], check=True, text=True, capture_output=True)
    run_payload = json.loads(run_demo.stdout)
    assert run_payload["verdict"] == "pass"

    trace_path = root / TRACE_DIRECTORY_RELATIVE_PATH / f"{run_payload['run_id']}.json"
    trace_check = subprocess.run(
        common + ["verify-trace", "--trace-path", str(trace_path)],
        check=True,
        text=True,
        capture_output=True,
    )
    assert json.loads(trace_check.stdout)["verdict"] == "pass"

    reset = subprocess.run(common + ["reset"], check=True, text=True, capture_output=True)
    assert json.loads(reset.stdout)["verdict"] == "reset"
