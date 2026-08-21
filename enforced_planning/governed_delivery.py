"""Prepare, control, and independently verify one governed coding task.

This is the Plan 113 authentic vertical.  It deliberately composes the
existing clean-room and governed-repo installer instead of implementing an
agent runtime.  A worker may change the disposable consumer, but only this
module's executed checks can produce a passing receipt.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TASK_RELATIVE_PATH = "projects/hello-app"
TASK_CONTRACT_FILE = "governed-task.json"
STATE_DIRECTORY = ".governed-delivery"
ATTEMPTS_FILE = "attempts.jsonl"
CHECKPOINTS_FILE = "checkpoints.jsonl"
VERIFICATION_RECEIPT_FILE = "verification-receipt.json"
BASELINE_TAG = "governed-task-baseline"
PERSONAL_SENTINELS = ("/home/brian", "BrianMills2718")


class GovernedDeliveryError(RuntimeError):
    """Fail-loud governed-delivery error with a stable code."""

    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.path = path

    def to_dict(self) -> dict[str, str]:
        """Return a portable JSON error payload."""

        result = {"code": self.code, "message": str(self)}
        if self.path is not None:
            result["path"] = self.path
        return result


class StrictModel(BaseModel):
    """Strict base for durable task and evidence contracts."""

    model_config = ConfigDict(extra="forbid")


class GovernedTaskV1(StrictModel):
    """Frozen contract for the one real clean-room feature request."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: Literal["hello-app-add-name"] = "hello-app-add-name"
    title: str = "Add an optional --name argument"
    authority_path: Literal["CLAUDE.md"] = "CLAUDE.md"
    plan_glob: Literal["docs/plans/[0-9][0-9]_*.md"] = "docs/plans/[0-9][0-9]_*.md"
    allowed_paths: list[str] = Field(
        default_factory=lambda: [
            "README.md",
            "src/hello_app.py",
            "docs/plans/CLAUDE.md",
            "docs/plans/[0-9][0-9]_*.md",
        ]
    )
    expected_default_output: Literal["hello-app uses shared-lib"] = "hello-app uses shared-lib"
    expected_named_output: Literal["Ada uses shared-lib"] = "Ada uses shared-lib"
    requested_command: list[str] = Field(
        default_factory=lambda: ["python", "src/hello_app.py", "--name", "Ada"]
    )


class CheckResultV1(StrictModel):
    """One independently observed pass/fail fact."""

    check_id: str
    verdict: Literal["pass", "fail"]
    detail: str
    observed: str | None = None


class PreparationReceiptV1(StrictModel):
    """Receipt for the prepared, failing governed baseline."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    operation: Literal["prepare"] = "prepare"
    task_id: str
    task_root: Literal["projects/hello-app"] = TASK_RELATIVE_PATH
    framework_revision: str
    baseline_revision: str
    installer_verdict: Literal["governed"]
    initial_probe_verdict: Literal["fail"]
    verdict: Literal["prepared"] = "prepared"


class ProbeReceiptV1(StrictModel):
    """One progress observation recorded independently of the worker."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    operation: Literal["probe"] = "probe"
    task_id: str
    attempt_number: int = Field(ge=1)
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verdict: Literal["pass", "fail"]
    decision: Literal["continue", "course_correction_required", "complete_candidate"]
    checks: list[CheckResultV1]
    recorded_at: str


class CourseCheckpointV1(StrictModel):
    """Explicit changed-assumption/tactic record after repeated non-progress."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["course_checkpoint"] = "course_checkpoint"
    checkpoint_id: str
    task_id: str
    after_attempt: int = Field(ge=2)
    prior_assumption: str = Field(min_length=8)
    changed_assumption: str = Field(min_length=8)
    next_tactic: str = Field(min_length=8)
    recorded_at: str

    @model_validator(mode="after")
    def _assumption_must_change(self) -> CourseCheckpointV1:
        if self.prior_assumption.strip().casefold() == self.changed_assumption.strip().casefold():
            raise ValueError("changed_assumption must differ from prior_assumption")
        return self


class VerificationReceiptV1(StrictModel):
    """Integrity-bound independent completion receipt."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    operation: Literal["verify"] = "verify"
    task_id: str
    task_root: Literal["."] = "."
    baseline_revision: str
    result_revision: str
    agent_session_id: str
    checks: list[CheckResultV1]
    verdict: Literal["pass", "fail"]
    verified_at: str
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _utc_now() -> str:
    """Return a full timezone-aware UTC timestamp."""

    return datetime.now(UTC).isoformat()


def _canonical_sha256(payload: dict[str, Any]) -> str:
    """Hash a JSON-compatible payload with stable serialization."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _resolve(path: str | Path) -> Path:
    """Resolve an explicit caller-supplied path."""

    return Path(path).expanduser().resolve()


def _run(
    argv: list[str],
    *,
    cwd: Path,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run an argv command without a shell and retain exact output."""

    completed = subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise GovernedDeliveryError(
            "command_failed",
            f"Command {argv!r} failed with exit {completed.returncode}: {detail}",
        )
    return completed


def _git(task_root: Path, *args: str, check: bool = True) -> str:
    """Run Git against the disposable task repository."""

    return _run(["git", *args], cwd=task_root, check=check).stdout.strip()


def _write(path: Path, content: str) -> None:
    """Write one prepared-fixture file with a final newline."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")


def _baseline_source() -> str:
    """Return the working default CLI whose requested option is still absent."""

    return '''"""Synthetic application consuming the clean-room shared library."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared-lib" / "src"))
from cleanroom_shared import label


def message() -> str:
    """Return a message proving the app can consume the synthetic library."""

    return f"hello-app uses {label()}"


def main() -> int:
    """Print the current default dependency message."""

    print(message())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _acceptance_tests() -> str:
    """Return consumer-owned black-box tests, including the initial failure."""

    return '''"""Acceptance tests supplied with the governed feature request."""

from __future__ import annotations

import subprocess
import sys
import unittest


class HelloAppCliTest(unittest.TestCase):
    def run_app(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "src/hello_app.py", *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_default_message_is_preserved(self) -> None:
        completed = self.run_app()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "hello-app uses shared-lib")

    def test_name_personalizes_message(self) -> None:
        completed = self.run_app("--name", "Ada")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "Ada uses shared-lib")


if __name__ == "__main__":
    unittest.main()
'''


def _consumer_authority() -> str:
    """Return the canonical minimal authority for the disposable consumer."""

    return """# hello-app

This repository is the disposable consumer for one governed-delivery task.

## Authority

1. The current user request and `governed-task.json` define the feature outcome.
2. This `CLAUDE.md` defines repository working rules.
3. The active bounded plan under `docs/plans/` defines execution and checks.

`AGENTS.md`, generated instructions, audits, and receipts are derived or
evidence surfaces; they do not replace this authority.

## Working Rules

- Create one bounded plan before changing source.
- Change only paths declared by `governed-task.json`; update the plan truthfully
  if the needed scope changes.
- Keep the README concise and current with public behavior.
- Run the supplied acceptance tests. Completion requires the independent
  governed-delivery verifier; a worker report is not evidence of success.
- After two unchanged failing probes, record a course checkpoint that names the
  questioned assumption and changed tactic before probing again.

## Commands

```bash
make verify
python src/hello_app.py
python src/hello_app.py --name Ada
```

## Principles

- Keep one current plan, one concise README, and one independent completion
  receipt.
- Prefer executed behavior and exact failure evidence over worker self-report.

## Workflow

1. Read `governed-task.json` and create one bounded plan.
2. Probe the initial behavior, implement only declared paths, and update the
   README.
3. Run `make verify`, commit the result, and invoke the independent verifier.

## References

- `governed-task.json` — bounded feature and allowed-write contract.
- `docs/plans/CLAUDE.md` — current plan index.
- `README.md` — public usage documentation.
"""


def _baseline_readme() -> str:
    """Return concise documentation for the already-working default behavior."""

    return """# hello-app

Print the shared-library dependency using the default application name:

```bash
python src/hello_app.py
# hello-app uses shared-lib
```
"""


def _baseline_makefile() -> str:
    """Return the task's stable public verification entrypoint."""

    return ".PHONY: verify\n\nverify:\n\tpython -m unittest discover -s tests\n"


def _ensure_task_root(task_root: Path) -> GovernedTaskV1:
    """Validate and load the prepared task root."""

    contract_path = task_root / TASK_CONTRACT_FILE
    if not contract_path.is_file() or not (task_root / ".git").exists():
        raise GovernedDeliveryError(
            "task_not_prepared",
            "Task root must be prepared before probing or verification.",
            path=str(task_root),
        )
    try:
        return GovernedTaskV1.model_validate_json(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GovernedDeliveryError(
            "invalid_task_contract",
            f"Unable to load governed task contract: {exc}",
            path=TASK_CONTRACT_FILE,
        ) from exc


def _check_result(
    check_id: str,
    passed: bool,
    detail: str,
    *,
    observed: str | None = None,
) -> CheckResultV1:
    """Build one typed check result."""

    return CheckResultV1(
        check_id=check_id,
        verdict="pass" if passed else "fail",
        detail=detail,
        observed=observed,
    )


def _command_check(
    task_root: Path,
    *,
    check_id: str,
    argv: list[str],
    expected_stdout: str | None = None,
) -> CheckResultV1:
    """Execute one behavioral command and compare its exact result."""

    executing_argv = [sys.executable, *argv[1:]] if argv and argv[0] == "python" else argv
    completed = _run(executing_argv, cwd=task_root)
    observed = completed.stdout.strip()
    passed = completed.returncode == 0 and (
        expected_stdout is None or observed == expected_stdout
    )
    detail = f"exit={completed.returncode}"
    if expected_stdout is not None:
        detail += f" expected={expected_stdout!r} observed={observed!r}"
    if completed.stderr.strip():
        detail += f" stderr={completed.stderr.strip()!r}"
    return _check_result(check_id, passed, detail, observed=observed)


def _changed_paths(task_root: Path) -> list[str]:
    """Return all committed, staged, unstaged, and untracked paths vs baseline."""

    baseline = _git(task_root, "rev-parse", BASELINE_TAG)
    paths = {
        item
        for item in _git(task_root, "diff", "--name-only", baseline).splitlines()
        if item
    }
    status = _git(task_root, "status", "--porcelain", "--untracked-files=all")
    for line in status.splitlines():
        candidate = line[3:].strip()
        if " -> " in candidate:
            candidate = candidate.split(" -> ", 1)[1]
        if candidate and not candidate.startswith(f"{STATE_DIRECTORY}/"):
            paths.add(candidate)
    return sorted(paths)


def _path_allowed(path: str, contract: GovernedTaskV1) -> bool:
    """Return whether one changed path is declared by the task contract."""

    return any(fnmatch.fnmatchcase(path, pattern) for pattern in contract.allowed_paths)


def _extract_section(content: str, heading: str) -> str:
    """Extract one level-two Markdown section."""

    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(content)
    return match.group("body").strip() if match else ""


def _tracked_text_has_personal_sentinel(task_root: Path) -> tuple[bool, str]:
    """Scan tracked text without embedding the executing machine path in output."""

    tracked = [item for item in _git(task_root, "ls-files").splitlines() if item]
    findings: list[str] = []
    for relative in tracked:
        path = task_root / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if any(sentinel in text for sentinel in PERSONAL_SENTINELS):
            findings.append(relative)
    return not findings, ", ".join(findings)


def _collect_checks(task_root: Path, contract: GovernedTaskV1) -> list[CheckResultV1]:
    """Execute the complete independent check set against current task state."""

    checks: list[CheckResultV1] = []
    checks.append(
        _command_check(
            task_root,
            check_id="default_behavior",
            argv=[sys.executable, "src/hello_app.py"],
            expected_stdout=contract.expected_default_output,
        )
    )
    checks.append(
        _command_check(
            task_root,
            check_id="named_behavior",
            argv=contract.requested_command,
            expected_stdout=contract.expected_named_output,
        )
    )
    checks.append(
        _command_check(
            task_root,
            check_id="acceptance_tests",
            argv=[sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        )
    )

    changed = _changed_paths(task_root)
    undeclared = [path for path in changed if not _path_allowed(path, contract)]
    checks.append(
        _check_result(
            "declared_write_scope",
            not undeclared,
            "all changed paths are declared" if not undeclared else "undeclared: " + ", ".join(undeclared),
            observed=", ".join(changed),
        )
    )

    plan_paths = [
        path
        for path in changed
        if fnmatch.fnmatchcase(path, contract.plan_glob) and path != "docs/plans/CLAUDE.md"
    ]
    plan_path = task_root / plan_paths[0] if len(plan_paths) == 1 else None
    plan_content = plan_path.read_text(encoding="utf-8") if plan_path and plan_path.is_file() else ""
    checks.append(
        _check_result(
            "bounded_plan_present",
            len(plan_paths) == 1 and bool(plan_content),
            f"expected one changed plan, found {plan_paths!r}",
            observed=plan_paths[0] if len(plan_paths) == 1 else None,
        )
    )
    plan_complete = bool(re.search(r"^\*\*Status:\*\*\s*Complete\s*$", plan_content, flags=re.MULTILINE))
    required_sections = all(
        _extract_section(plan_content, heading)
        for heading in ("User Outcome", "Canonical Behavioral Example", "Authority Used", "Required Tests", "Acceptance Criteria")
    )
    checks.append(
        _check_result(
            "plan_truthful_complete",
            plan_complete and required_sections,
            "plan is complete with required sections" if plan_complete and required_sections else "plan is incomplete or missing required sections",
        )
    )
    authority = _extract_section(plan_content, "Authority Used")
    authority_ok = "`CLAUDE.md`" in authority and "generated/instructions.md" not in authority
    checks.append(
        _check_result(
            "plan_authority",
            authority_ok,
            "CLAUDE.md is the declared authority" if authority_ok else f"invalid authority section: {authority!r}",
            observed=authority or None,
        )
    )

    index_path = task_root / "docs" / "plans" / "CLAUDE.md"
    index_content = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    indexed = bool(plan_paths) and Path(plan_paths[0]).name in index_content
    checks.append(
        _check_result(
            "plan_index_current",
            indexed,
            "plan index names the active plan" if indexed else "plan index does not name the changed plan",
        )
    )

    readme_path = task_root / "README.md"
    readme = readme_path.read_text(encoding="utf-8") if readme_path.is_file() else ""
    readme_ok = (
        "python src/hello_app.py --name Ada" in readme
        and contract.expected_named_output in readme
        and len(readme.splitlines()) <= 80
    )
    checks.append(
        _check_result(
            "documentation_current_minimal",
            readme_ok,
            "README has one concise runnable named example" if readme_ok else "README example is missing, stale, or over 80 lines",
        )
    )

    governed_files = ["CLAUDE.md", "AGENTS.md", "meta-process.yaml", "scripts/meta/validate_plan.py"]
    missing_governance = [path for path in governed_files if not (task_root / path).exists()]
    checks.append(
        _check_result(
            "governed_install",
            not missing_governance,
            "canonical governed-repo surfaces are installed" if not missing_governance else "missing: " + ", ".join(missing_governance),
        )
    )
    portable, personal_paths = _tracked_text_has_personal_sentinel(task_root)
    checks.append(
        _check_result(
            "portable_content",
            portable,
            "tracked content contains no maintainer sentinel" if portable else "personal sentinel in: " + personal_paths,
        )
    )
    clean = not _git(task_root, "status", "--porcelain", "--untracked-files=all")
    checks.append(
        _check_result(
            "clean_committed_result",
            clean,
            "result is clean and committed" if clean else "result has uncommitted or untracked paths",
        )
    )
    baseline = _git(task_root, "rev-parse", BASELINE_TAG)
    result = _git(task_root, "rev-parse", "HEAD")
    checks.append(
        _check_result(
            "result_revision_advanced",
            result != baseline,
            f"baseline={baseline} result={result}",
        )
    )
    return checks


def _state_sha256(task_root: Path) -> str:
    """Hash exact Git/source state while excluding ignored progress records."""

    payload = {
        "head": _git(task_root, "rev-parse", "HEAD"),
        "status": _git(task_root, "status", "--porcelain", "--untracked-files=all"),
        "diff": _git(task_root, "diff", "HEAD"),
        "cached_diff": _git(task_root, "diff", "--cached"),
    }
    return _canonical_sha256(payload)


def _load_jsonl(path: Path, model: type[StrictModel]) -> list[StrictModel]:
    """Load an append-only JSONL record set or fail loudly."""

    if not path.exists():
        return []
    records: list[StrictModel] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip():
                records.append(model.model_validate_json(line))
    except (OSError, ValueError) as exc:
        raise GovernedDeliveryError(
            "invalid_progress_record",
            f"Invalid progress record at {path.name}:{line_number}: {exc}",
            path=str(path),
        ) from exc
    return records


def _append_jsonl(path: Path, record: StrictModel) -> None:
    """Append one validated compact JSON record."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json() + "\n")


def prepare_governed_task(
    *,
    cleanroom_root: str | Path,
    framework_root: str | Path,
) -> PreparationReceiptV1:
    """Overlay, govern, and commit the one failing hello-app task baseline."""

    root = _resolve(cleanroom_root)
    framework = _resolve(framework_root)
    task_root = root / TASK_RELATIVE_PATH
    source_path = task_root / "src" / "hello_app.py"
    receipt_path = root / ".loop-engineering" / "state" / "install_receipt.json"
    installer = framework / "scripts" / "install_governed_repo.py"
    if not receipt_path.is_file() or not source_path.is_file():
        raise GovernedDeliveryError(
            "cleanroom_not_materialized",
            "Prepare requires a materialized default clean-room fixture.",
            path=str(root),
        )
    if (task_root / ".git").exists() or (task_root / TASK_CONTRACT_FILE).exists():
        raise GovernedDeliveryError(
            "task_already_prepared",
            "Refusing to overwrite an existing governed task.",
            path=str(task_root),
        )
    if not installer.is_file():
        raise GovernedDeliveryError(
            "installer_unavailable",
            "Canonical governed-repo installer is unavailable.",
            path=str(installer),
        )
    framework_revision = _git(framework, "rev-parse", "HEAD")
    try:
        cleanroom_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernedDeliveryError(
            "invalid_cleanroom_receipt",
            f"Unable to read the clean-room install receipt: {exc}",
            path=str(receipt_path),
        ) from exc
    component_revision = cleanroom_receipt.get("component_revision")
    if component_revision != framework_revision:
        raise GovernedDeliveryError(
            "component_revision_mismatch",
            "Clean-room component revision does not match the executing framework revision: "
            f"receipt={component_revision!r} framework={framework_revision!r}",
            path=str(receipt_path),
        )
    original = source_path.read_text(encoding="utf-8")
    if "from cleanroom_shared import label" not in original or "def message()" not in original:
        raise GovernedDeliveryError(
            "unexpected_cleanroom_source",
            "hello-app source does not match the clean-room capability seam.",
            path="src/hello_app.py",
        )

    contract = GovernedTaskV1()
    _write(source_path, _baseline_source())
    _write(task_root / "tests" / "test_cli.py", _acceptance_tests())
    _write(task_root / "README.md", _baseline_readme())
    _write(task_root / "CLAUDE.md", _consumer_authority())
    _write(task_root / "Makefile", _baseline_makefile())
    _write(task_root / TASK_CONTRACT_FILE, contract.model_dump_json(indent=2))
    _write(task_root / ".gitignore", f"{STATE_DIRECTORY}/\n__pycache__/\n*.pyc\n")

    _run(["git", "init", "-b", "main"], cwd=task_root, check=True)
    _git(task_root, "config", "user.name", "Governed Delivery Fixture")
    _git(task_root, "config", "user.email", "governed-delivery@example.invalid")
    installed = _run(
        [
            sys.executable,
            str(installer),
            "--repo-root",
            str(task_root),
            "--write",
            "--strict-governed",
            "--json",
        ],
        cwd=framework,
    )
    if installed.returncode != 0:
        detail = (installed.stderr or installed.stdout).strip()
        raise GovernedDeliveryError(
            "governed_install_failed",
            f"Canonical installer failed: {detail}",
        )
    try:
        install_payload = json.loads(installed.stdout)
    except json.JSONDecodeError as exc:
        raise GovernedDeliveryError(
            "invalid_installer_receipt",
            f"Installer did not return JSON: {exc}",
        ) from exc
    post_audit = install_payload.get("post_audit")
    classification = post_audit.get("classification") if isinstance(post_audit, dict) else None
    if classification != "governed":
        raise GovernedDeliveryError(
            "governed_install_incomplete",
            f"Installer result was not governed: {classification!r}",
        )

    _git(task_root, "add", "-A")
    _git(task_root, "commit", "-m", "[Unplanned] Prepare governed task baseline")
    _git(task_root, "tag", BASELINE_TAG)
    baseline_revision = _git(task_root, "rev-parse", BASELINE_TAG)
    initial_checks = _collect_checks(task_root, contract)
    if all(check.verdict == "pass" for check in initial_checks):
        raise GovernedDeliveryError(
            "initial_failure_not_observed",
            "Prepared task unexpectedly satisfies every acceptance check.",
        )
    named_check = next(check for check in initial_checks if check.check_id == "named_behavior")
    if named_check.verdict != "fail":
        raise GovernedDeliveryError(
            "named_failure_not_observed",
            "Prepared task must fail the requested --name behavior.",
        )
    portable_check = next(check for check in initial_checks if check.check_id == "portable_content")
    if portable_check.verdict != "pass":
        raise GovernedDeliveryError(
            "prepared_content_not_portable",
            portable_check.detail,
        )
    return PreparationReceiptV1(
        task_id=contract.task_id,
        framework_revision=framework_revision,
        baseline_revision=baseline_revision,
        installer_verdict="governed",
        initial_probe_verdict="fail",
    )


def probe_governed_task(task_root: str | Path) -> ProbeReceiptV1:
    """Execute checks and enforce a checkpoint after repeated unchanged failure."""

    root = _resolve(task_root)
    contract = _ensure_task_root(root)
    state = root / STATE_DIRECTORY
    attempts_path = state / ATTEMPTS_FILE
    checkpoints_path = state / CHECKPOINTS_FILE
    attempts = [item for item in _load_jsonl(attempts_path, ProbeReceiptV1)]
    checkpoints = [item for item in _load_jsonl(checkpoints_path, CourseCheckpointV1)]
    latest_required_checkpointed = False
    if attempts and attempts[-1].decision == "course_correction_required":
        latest_required_checkpointed = any(
            item.after_attempt == attempts[-1].attempt_number for item in checkpoints
        )
        if not latest_required_checkpointed:
            raise GovernedDeliveryError(
                "course_checkpoint_required",
                "A course checkpoint with a changed assumption and tactic is required before another probe.",
            )

    checks = _collect_checks(root, contract)
    verdict: Literal["pass", "fail"] = (
        "pass" if all(check.verdict == "pass" for check in checks) else "fail"
    )
    digest = _state_sha256(root)
    decision: Literal["continue", "course_correction_required", "complete_candidate"]
    if verdict == "pass":
        decision = "complete_candidate"
    elif (
        attempts
        and attempts[-1].verdict == "fail"
        and attempts[-1].state_sha256 == digest
        and not latest_required_checkpointed
    ):
        decision = "course_correction_required"
    else:
        decision = "continue"
    receipt = ProbeReceiptV1(
        task_id=contract.task_id,
        attempt_number=len(attempts) + 1,
        state_sha256=digest,
        verdict=verdict,
        decision=decision,
        checks=checks,
        recorded_at=_utc_now(),
    )
    _append_jsonl(attempts_path, receipt)
    return receipt


def record_course_checkpoint(
    task_root: str | Path,
    *,
    prior_assumption: str,
    changed_assumption: str,
    next_tactic: str,
) -> CourseCheckpointV1:
    """Record the changed reasoning required by a non-progress decision."""

    root = _resolve(task_root)
    contract = _ensure_task_root(root)
    state = root / STATE_DIRECTORY
    attempts = [item for item in _load_jsonl(state / ATTEMPTS_FILE, ProbeReceiptV1)]
    checkpoints = [item for item in _load_jsonl(state / CHECKPOINTS_FILE, CourseCheckpointV1)]
    if not attempts or attempts[-1].decision != "course_correction_required":
        raise GovernedDeliveryError(
            "checkpoint_not_required",
            "A course checkpoint is accepted only after repeated unchanged failure.",
        )
    if any(item.after_attempt == attempts[-1].attempt_number for item in checkpoints):
        raise GovernedDeliveryError(
            "checkpoint_already_recorded",
            "A course checkpoint already exists for the latest attempt.",
        )
    try:
        checkpoint = CourseCheckpointV1(
            checkpoint_id="ccp_" + uuid.uuid4().hex,
            task_id=contract.task_id,
            after_attempt=attempts[-1].attempt_number,
            prior_assumption=prior_assumption.strip(),
            changed_assumption=changed_assumption.strip(),
            next_tactic=next_tactic.strip(),
            recorded_at=_utc_now(),
        )
    except ValueError as exc:
        raise GovernedDeliveryError(
            "invalid_course_checkpoint",
            f"Course checkpoint is invalid: {exc}",
        ) from exc
    _append_jsonl(state / CHECKPOINTS_FILE, checkpoint)
    return checkpoint


def verify_governed_task(
    task_root: str | Path,
    *,
    agent_session_id: str | None = None,
) -> VerificationReceiptV1:
    """Execute terminal checks and write an integrity-bound independent receipt."""

    root = _resolve(task_root)
    contract = _ensure_task_root(root)
    session_id = (agent_session_id or os.environ.get("CODEX_THREAD_ID") or "").strip()
    if not session_id:
        raise GovernedDeliveryError(
            "missing_agent_session",
            "Verification requires the authentic worker session id.",
        )
    if not session_id.startswith("codex:"):
        session_id = f"codex:{session_id}"

    checks = _collect_checks(root, contract)
    attempts = [
        item
        for item in _load_jsonl(root / STATE_DIRECTORY / ATTEMPTS_FILE, ProbeReceiptV1)
    ]
    initial_failure = bool(attempts) and attempts[0].verdict == "fail"
    checks.append(
        _check_result(
            "initial_failure_observed",
            initial_failure,
            "first persisted probe failed before implementation" if initial_failure else "no persisted initial failing probe",
        )
    )
    verdict: Literal["pass", "fail"] = (
        "pass" if all(check.verdict == "pass" for check in checks) else "fail"
    )
    unsigned = {
        "schema_version": "1.0.0",
        "operation": "verify",
        "task_id": contract.task_id,
        "task_root": ".",
        "baseline_revision": _git(root, "rev-parse", BASELINE_TAG),
        "result_revision": _git(root, "rev-parse", "HEAD"),
        "agent_session_id": session_id,
        "checks": [item.model_dump(mode="json") for item in checks],
        "verdict": verdict,
        "verified_at": _utc_now(),
    }
    receipt = VerificationReceiptV1(
        **unsigned,
        receipt_sha256=_canonical_sha256(unsigned),
    )
    state_path = root / STATE_DIRECTORY / VERIFICATION_RECEIPT_FILE
    _write(state_path, receipt.model_dump_json(indent=2))
    return receipt
