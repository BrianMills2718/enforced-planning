"""Focused both-sign tests for the Plan 113 governed-delivery vertical."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from enforced_planning.cleanroom_alpha import CleanroomSpec, materialize_cleanroom
from enforced_planning.governed_delivery import (
    GovernedDeliveryError,
    prepare_governed_task,
    probe_governed_task,
    record_course_checkpoint,
    verify_governed_task,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "governed_delivery.py"
STATUS_PROFILE = REPO_ROOT / "examples" / "cleanroom-ecosystem" / "status-cli-profile.json"


def _git(task_root: Path, *args: str) -> str:
    """Run one successful Git command in the disposable consumer."""

    completed = subprocess.run(
        ["git", *args],
        cwd=task_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _prepared_task(tmp_path: Path) -> tuple[Path, object]:
    """Materialize the neutral clean-room and prepare its real governed task."""

    projects_root = tmp_path / "workspace" / "projects"
    projects_root.mkdir(parents=True)
    spec = CleanroomSpec.build(
        root=tmp_path / "external" / "cleanroom",
        component_revision=_git(REPO_ROOT, "rev-parse", "HEAD"),
        projects_root=projects_root,
    )
    materialize_cleanroom(spec)
    receipt = prepare_governed_task(
        cleanroom_root=spec.root,
        framework_root=REPO_ROOT,
    )
    return spec.root / "projects" / "hello-app", receipt


def _status_cleanroom(tmp_path: Path) -> CleanroomSpec:
    """Materialize the custom one-project inventory used by the second profile."""

    projects_root = tmp_path / "workspace" / "projects"
    projects_root.mkdir(parents=True)
    spec = CleanroomSpec.build(
        root=tmp_path / "external" / "status-cleanroom",
        component_revision=_git(REPO_ROOT, "rev-parse", "HEAD"),
        projects_root=projects_root,
        instance_id="status-consumer",
        consumer_projects=[
            {
                "project_id": "status-cli",
                "relative_path": "projects/status-cli",
            }
        ],
    )
    materialize_cleanroom(spec)
    return spec


def _prepared_status_task(tmp_path: Path) -> tuple[Path, object]:
    """Prepare the copied status profile in its consumer-owned inventory."""

    spec = _status_cleanroom(tmp_path)
    receipt = prepare_governed_task(
        cleanroom_root=spec.root,
        framework_root=REPO_ROOT,
        profile_path=STATUS_PROFILE,
    )
    return spec.root / "projects" / "status-cli", receipt


def _completed_source() -> str:
    """Return the accepted hello-app implementation used by verifier tests."""

    return '''"""Synthetic application consuming the clean-room shared library."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared-lib" / "src"))
from cleanroom_shared import label


def message(name: str = "hello-app") -> str:
    """Return a message proving the app can consume the synthetic library."""

    return f"{name} uses {label()}"


def main() -> int:
    """Print the dependency message for the requested display name."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="hello-app")
    args = parser.parse_args()
    print(message(args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _completed_status_source() -> str:
    """Return the accepted status-cli implementation used by verifier tests."""

    return '''"""Consumer status CLI backed by the clean-room project manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_status() -> dict[str, str]:
    """Load the consumer-owned project manifest."""

    return json.loads(Path(__file__).resolve().parents[1].joinpath("project.json").read_text())


def main() -> int:
    """Print human-readable or compact JSON status."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    status = load_status()
    if args.json:
        print(json.dumps(status, sort_keys=True, separators=(",", ":")))
    else:
        print(f"{status['project_id']}: {status['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _plan(*, authority: str = "CLAUDE.md", status: str = "Complete") -> str:
    """Return the bounded consumer plan fixture."""

    return f"""# Plan #1: Add Optional Name

**Status:** {status}
**Type:** implementation

## User Outcome

A caller can personalize the hello-app dependency message without changing the
existing default.

## Canonical Behavioral Example

`python src/hello_app.py --name Ada` prints `Ada uses shared-lib`.

## Authority Used

- `{authority}`

## Files Affected

- `src/hello_app.py`
- `README.md`
- `docs/plans/01_add_optional_name.md`
- `docs/plans/CLAUDE.md`

## Required Tests

- Default output remains `hello-app uses shared-lib`.
- `--name Ada` prints `Ada uses shared-lib`.

## Acceptance Criteria

- [x] Both exact commands pass.
- [x] README contains one concise usage example.
- [x] Independent governed-delivery verifier passes.
"""


def _complete_task(
    task_root: Path,
    *,
    authority: str = "CLAUDE.md",
    unexpected_path: str | None = None,
) -> None:
    """Create and commit a result candidate inside the disposable consumer."""

    task_root.joinpath("src/hello_app.py").write_text(_completed_source(), encoding="utf-8")
    task_root.joinpath("README.md").write_text(
        """# hello-app

Print the shared-library dependency using the default application name:

```bash
python src/hello_app.py
# hello-app uses shared-lib
```

Optionally provide a display name:

```bash
python src/hello_app.py --name Ada
# Ada uses shared-lib
```
""",
        encoding="utf-8",
    )
    plan_path = task_root / "docs" / "plans" / "01_add_optional_name.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(_plan(authority=authority), encoding="utf-8")
    index_path = task_root / "docs" / "plans" / "CLAUDE.md"
    index_path.write_text(
        "# Implementation Plans\n\n- [Plan #1: Add Optional Name](01_add_optional_name.md) — Complete\n",
        encoding="utf-8",
    )
    if unexpected_path:
        unexpected = task_root / unexpected_path
        unexpected.parent.mkdir(parents=True, exist_ok=True)
        unexpected.write_text("undeclared\n", encoding="utf-8")
    _git(task_root, "add", "-A")
    _git(task_root, "commit", "-m", "[Plan #1] Add optional name")


def _complete_status_task(task_root: Path) -> None:
    """Create and commit the configured status-cli result candidate."""

    task_root.joinpath("src/status_cli.py").write_text(
        _completed_status_source(), encoding="utf-8"
    )
    task_root.joinpath("README.md").write_text(
        """# status-cli

Show the current project status:

```bash
python src/status_cli.py
# status-cli: adapter-placeholder
```

Emit compact JSON for machine consumers:

```bash
python src/status_cli.py --json
# {"project_id":"status-cli","status":"adapter-placeholder"}
```
""",
        encoding="utf-8",
    )
    plan_path = task_root / "docs" / "plans" / "01_add_json_status.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        """# Plan #1: Add JSON Status

**Status:** Complete
**Type:** implementation

## User Outcome

Machine consumers can request compact JSON without changing the default output.

## Canonical Behavioral Example

`python src/status_cli.py --json` prints the compact project manifest.

## Authority Used

- `CLAUDE.md`

## Required Tests

- Default status remains unchanged.
- `--json` prints the exact compact manifest.

## Acceptance Criteria

- [x] Both exact commands pass.
- [x] README contains one concise example for each public mode.
- [x] Independent governed-delivery verifier passes.
""",
        encoding="utf-8",
    )
    task_root.joinpath("docs/plans/CLAUDE.md").write_text(
        "# Implementation Plans\n\n- [Plan #1: Add JSON Status](01_add_json_status.md) — Complete\n",
        encoding="utf-8",
    )
    _git(task_root, "add", "-A")
    _git(task_root, "commit", "-m", "[Plan #1] Add compact JSON status")


def _check(receipt: object, check_id: str) -> object:
    """Return one check from a typed probe or verification receipt."""

    checks = receipt.checks
    return next(item for item in checks if item.check_id == check_id)


def test_prepare_creates_governed_failing_baseline(tmp_path: Path) -> None:
    """Preparation installs authority, commits a baseline, and observes failure."""

    task_root, receipt = _prepared_task(tmp_path)

    assert receipt.verdict == "prepared"
    assert receipt.initial_probe_verdict == "fail"
    assert receipt.baseline_revision == _git(task_root, "rev-parse", "governed-task-baseline")
    assert _git(task_root, "status", "--porcelain") == ""
    assert (task_root / "AGENTS.md").exists()
    assert (task_root / "governed-task.json").exists()
    task_contract = (task_root / "governed-task.json").read_text(encoding="utf-8")
    assert "/home/brian" not in task_contract
    assert json.loads(task_contract)["requested_command"][0] == "python"
    named = subprocess.run(
        [sys.executable, "src/hello_app.py", "--name", "Ada"],
        cwd=task_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert named.stdout.strip() != "Ada uses shared-lib"


def test_prepare_rejects_component_revision_drift(tmp_path: Path) -> None:
    """Preparation cannot bless a hand-written revision that did not execute."""

    projects_root = tmp_path / "workspace" / "projects"
    projects_root.mkdir(parents=True)
    spec = CleanroomSpec.build(
        root=tmp_path / "external" / "cleanroom",
        component_revision="0" * 40,
        projects_root=projects_root,
    )
    materialize_cleanroom(spec)

    with pytest.raises(GovernedDeliveryError) as exc_info:
        prepare_governed_task(cleanroom_root=spec.root, framework_root=REPO_ROOT)

    assert exc_info.value.code == "component_revision_mismatch"


def test_external_status_profile_prepares_different_consumer(tmp_path: Path) -> None:
    """A copied profile selects a custom inventory, adapter, commands, and outputs."""

    task_root, receipt = _prepared_status_task(tmp_path)

    assert receipt.profile_id == "status-cli-json"
    assert receipt.task_id == "status-cli-add-json"
    assert receipt.task_root == "projects/status-cli"
    assert len(receipt.profile_sha256) == 64
    default = subprocess.run(
        [sys.executable, "src/status_cli.py"],
        cwd=task_root,
        capture_output=True,
        text=True,
        check=False,
    )
    requested = subprocess.run(
        [sys.executable, "src/status_cli.py", "--json"],
        cwd=task_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert default.returncode == 0
    assert default.stdout.strip() == "status-cli: adapter-placeholder"
    assert requested.returncode != 0
    assert _git(task_root, "status", "--porcelain") == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_relative_path", "/tmp/status-cli"),
        ("source_path", "../status_cli.py"),
        ("source_adapter", "arbitrary-shell"),
    ],
)
def test_profile_rejects_unsafe_paths_and_unknown_adapters_before_git(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """Invalid consumer configuration fails before task repository mutation."""

    spec = _status_cleanroom(tmp_path)
    profile = json.loads(STATUS_PROFILE.read_text(encoding="utf-8"))
    profile[field] = value
    invalid_profile = tmp_path / "invalid-profile.json"
    invalid_profile.write_text(json.dumps(profile), encoding="utf-8")

    with pytest.raises(GovernedDeliveryError) as exc_info:
        prepare_governed_task(
            cleanroom_root=spec.root,
            framework_root=REPO_ROOT,
            profile_path=invalid_profile,
        )

    assert exc_info.value.code == "invalid_task_profile"
    assert not (spec.root / "projects" / "status-cli" / ".git").exists()


def test_repeated_unchanged_failure_requires_course_checkpoint(tmp_path: Path) -> None:
    """An unchanged failing loop cannot continue without changing its tactic."""

    task_root, _ = _prepared_task(tmp_path)

    first = probe_governed_task(task_root)
    second = probe_governed_task(task_root)

    assert first.decision == "continue"
    assert second.decision == "course_correction_required"
    assert first.state_sha256 == second.state_sha256
    with pytest.raises(GovernedDeliveryError, match="course checkpoint") as exc_info:
        probe_governed_task(task_root)
    assert exc_info.value.code == "course_checkpoint_required"

    checkpoint = record_course_checkpoint(
        task_root,
        prior_assumption="The feature might already be available through the generated instructions.",
        changed_assumption="Executed behavior and CLAUDE.md are authoritative; the option is absent.",
        next_tactic="Implement the option in source and verify both CLI paths.",
    )
    assert checkpoint.after_attempt == 2
    assert probe_governed_task(task_root).decision == "continue"


def test_probe_preserves_first_porcelain_path(tmp_path: Path) -> None:
    """Leading porcelain status whitespace cannot truncate a declared path."""

    task_root, _ = _prepared_task(tmp_path)
    readme = task_root / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nWorking note.\n", encoding="utf-8")

    receipt = probe_governed_task(task_root)
    scope = _check(receipt, "declared_write_scope")

    assert scope.verdict == "pass"
    assert scope.observed == "README.md"


def test_verifier_accepts_plan_docs_code_and_declared_git_diff(tmp_path: Path) -> None:
    """The smallest complete consumer result passes every independent check."""

    task_root, _ = _prepared_task(tmp_path)
    initial = probe_governed_task(task_root)
    assert initial.verdict == "fail"
    _complete_task(task_root)

    receipt = verify_governed_task(task_root, agent_session_id="codex:test-session")

    assert receipt.verdict == "pass"
    assert receipt.baseline_revision == _git(task_root, "rev-parse", "governed-task-baseline")
    assert receipt.result_revision == _git(task_root, "rev-parse", "HEAD")
    assert receipt.framework_revision == _git(REPO_ROOT, "rev-parse", "HEAD")
    assert receipt.agent_session_id == "codex:test-session"
    assert receipt.receipt_sha256
    assert all(item.verdict == "pass" for item in receipt.checks)
    assert _check(receipt, "requested_behavior").observed == "Ada uses shared-lib"


def test_verifier_accepts_configured_status_consumer(tmp_path: Path) -> None:
    """The different task profile crosses the same independent completion gate."""

    task_root, prepared = _prepared_status_task(tmp_path)
    initial = probe_governed_task(task_root)
    assert initial.verdict == "fail"
    _complete_status_task(task_root)

    receipt = verify_governed_task(task_root, agent_session_id="codex:status-session")

    assert receipt.verdict == "pass"
    assert receipt.profile_id == prepared.profile_id
    assert receipt.profile_sha256 == prepared.profile_sha256
    assert receipt.task_id == "status-cli-add-json"
    assert _check(receipt, "default_behavior").observed == "status-cli: adapter-placeholder"
    assert _check(receipt, "requested_behavior").observed == (
        '{"project_id":"status-cli","status":"adapter-placeholder"}'
    )
    assert _check(receipt, "profile_contract_binding").verdict == "pass"


def test_verifier_rejects_profile_drift_from_baseline(tmp_path: Path) -> None:
    """A worker cannot rewrite its profile and certify the changed success contract."""

    task_root, _ = _prepared_status_task(tmp_path)
    probe_governed_task(task_root)
    _complete_status_task(task_root)
    contract_path = task_root / "governed-task.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["title"] = "Worker-rewritten task contract"
    contract_path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    _git(task_root, "add", "governed-task.json")
    _git(task_root, "commit", "-m", "[Plan #1] Rewrite task contract")

    receipt = verify_governed_task(task_root, agent_session_id="codex:status-session")

    assert receipt.verdict == "fail"
    assert _check(receipt, "profile_contract_binding").verdict == "fail"


def test_false_generated_authority_is_rejected(tmp_path: Path) -> None:
    """Generated orientation cannot substitute for the consumer's CLAUDE authority."""

    task_root, _ = _prepared_task(tmp_path)
    probe_governed_task(task_root)
    _complete_task(task_root, authority="generated/instructions.md")

    receipt = verify_governed_task(task_root, agent_session_id="codex:test-session")

    assert receipt.verdict == "fail"
    assert _check(receipt, "plan_authority").verdict == "fail"


def test_undeclared_write_is_rejected(tmp_path: Path) -> None:
    """A passing feature cannot hide a committed write outside the task contract."""

    task_root, _ = _prepared_task(tmp_path)
    probe_governed_task(task_root)
    _complete_task(task_root, unexpected_path="notes/rabbit-hole.md")

    receipt = verify_governed_task(task_root, agent_session_id="codex:test-session")

    assert receipt.verdict == "fail"
    scope = _check(receipt, "declared_write_scope")
    assert scope.verdict == "fail"
    assert "notes/rabbit-hole.md" in scope.detail


def test_worker_self_report_cannot_certify_completion(tmp_path: Path) -> None:
    """A worker-authored success marker remains irrelevant to executed checks."""

    task_root, _ = _prepared_task(tmp_path)
    probe_governed_task(task_root)
    state = task_root / ".governed-delivery"
    state.mkdir(exist_ok=True)
    state.joinpath("worker-report.json").write_text(
        json.dumps({"verdict": "pass", "claim": "complete"}),
        encoding="utf-8",
    )

    receipt = verify_governed_task(task_root, agent_session_id="codex:test-session")

    assert receipt.verdict == "fail"
    assert _check(receipt, "requested_behavior").verdict == "fail"


def test_cli_json_prepare_probe_checkpoint_and_verify(tmp_path: Path) -> None:
    """The complete control surface is agent-drivable without importing Python."""

    projects_root = tmp_path / "workspace" / "projects"
    projects_root.mkdir(parents=True)
    spec = CleanroomSpec.build(
        root=tmp_path / "external" / "cleanroom",
        component_revision=_git(REPO_ROOT, "rev-parse", "HEAD"),
        projects_root=projects_root,
    )
    materialize_cleanroom(spec)
    prepared = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--cleanroom-root",
            str(spec.root),
            "--framework-root",
            str(REPO_ROOT),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(prepared.stdout)["verdict"] == "prepared"
    task_root = spec.root / "projects" / "hello-app"

    first = subprocess.run(
        [sys.executable, str(SCRIPT), "probe", "--task-root", str(task_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        [sys.executable, str(SCRIPT), "probe", "--task-root", str(task_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert json.loads(first.stdout)["decision"] == "continue"
    assert json.loads(second.stdout)["decision"] == "course_correction_required"

    checkpoint = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "checkpoint",
            "--task-root",
            str(task_root),
            "--prior-assumption",
            "Generated orientation might define behavior.",
            "--changed-assumption",
            "The executable source and CLAUDE.md define current behavior.",
            "--next-tactic",
            "Change source, then execute both exact commands.",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(checkpoint.stdout)["after_attempt"] == 2

    _complete_task(task_root)
    verified = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify",
            "--task-root",
            str(task_root),
            "--agent-session-id",
            "codex:test-session",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(verified.stdout)["verdict"] == "pass"


def test_cli_prepare_accepts_copied_status_profile(tmp_path: Path) -> None:
    """The public JSON CLI selects the second consumer without Python imports."""

    spec = _status_cleanroom(tmp_path)
    prepared = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--cleanroom-root",
            str(spec.root),
            "--framework-root",
            str(REPO_ROOT),
            "--profile",
            str(STATUS_PROFILE),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(prepared.stdout)
    assert payload["verdict"] == "prepared"
    assert payload["profile_id"] == "status-cli-json"
    assert payload["task_root"] == "projects/status-cli"
