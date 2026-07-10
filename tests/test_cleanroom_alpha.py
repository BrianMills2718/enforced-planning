"""Tests for the loop-engineering clean-room alpha fixture."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from enforced_planning.cleanroom_alpha import CleanroomError
from enforced_planning.cleanroom_alpha import CleanroomSpec
from enforced_planning.cleanroom_alpha import RECEIPT_RELATIVE_PATH
from enforced_planning.cleanroom_alpha import materialize_cleanroom
from enforced_planning.cleanroom_alpha import plan_cleanroom
from enforced_planning.cleanroom_alpha import reset_cleanroom
from enforced_planning.cleanroom_alpha import status_cleanroom
from enforced_planning.cleanroom_alpha import verify_cleanroom


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "cleanroom_alpha.py"


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
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    report = reset_cleanroom(spec.root)

    assert report.verdict == "fail"
    assert any(finding.check_id == "receipt_path_escape" for finding in report.findings)


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

    run_demo = subprocess.run(common + ["run-demo"], text=True, capture_output=True)
    assert run_demo.returncode == 2
    assert json.loads(run_demo.stdout)["code"] == "deferred_slice_2"

    reset = subprocess.run(common + ["reset"], check=True, text=True, capture_output=True)
    assert json.loads(reset.stdout)["verdict"] == "reset"
