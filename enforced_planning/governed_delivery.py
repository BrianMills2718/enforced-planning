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
import shlex
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
PORTABLE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")


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
    """Validated consumer profile copied into one governed task repository."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    profile_id: str = "hello-app-name"
    project_id: str = "hello-app"
    project_relative_path: str = TASK_RELATIVE_PATH
    source_adapter: Literal["hello-shared-lib", "manifest-status-cli"] = (
        "hello-shared-lib"
    )
    source_path: str = "src/hello_app.py"
    task_id: str = "hello-app-add-name"
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
    default_command: list[str] = Field(
        default_factory=lambda: ["python", "src/hello_app.py"]
    )
    expected_default_output: str = "hello-app uses shared-lib"
    requested_command: list[str] = Field(
        default_factory=lambda: ["python", "src/hello_app.py", "--name", "Ada"]
    )
    expected_requested_output: str = "Ada uses shared-lib"

    @model_validator(mode="after")
    def _portable_profile(self) -> GovernedTaskV1:
        """Reject unsafe or internally inconsistent consumer configuration."""

        for field_name, value in (
            ("profile_id", self.profile_id),
            ("project_id", self.project_id),
            ("task_id", self.task_id),
        ):
            if not PORTABLE_ID_RE.fullmatch(value):
                raise ValueError(f"{field_name} must be a portable lowercase identifier")
        if self.project_relative_path != f"projects/{self.project_id}":
            raise ValueError("project_relative_path must equal projects/<project_id>")
        self._validate_relative_path(self.source_path, field_name="source_path")
        if not self.source_path.startswith("src/") or not self.source_path.endswith(".py"):
            raise ValueError("source_path must name a Python file under src/")
        if self.default_command != ["python", self.source_path]:
            raise ValueError("default_command must be ['python', source_path]")
        if (
            len(self.requested_command) <= len(self.default_command)
            or self.requested_command[: len(self.default_command)] != self.default_command
        ):
            raise ValueError("requested_command must extend default_command")
        for command in (self.default_command, self.requested_command):
            if any(not item or "\n" in item or "\r" in item for item in command):
                raise ValueError("commands must contain non-empty single-line arguments")
            if any(sentinel.casefold() in " ".join(command).casefold() for sentinel in PERSONAL_SENTINELS):
                raise ValueError("commands must not contain a personal sentinel")
        if not self.allowed_paths:
            raise ValueError("allowed_paths must not be empty")
        for path in self.allowed_paths:
            self._validate_relative_path(path, field_name="allowed_paths")
        required_paths = {
            "README.md",
            self.source_path,
            "docs/plans/CLAUDE.md",
            self.plan_glob,
        }
        if not required_paths.issubset(self.allowed_paths):
            raise ValueError("allowed_paths must include README, source, plan index, and plan glob")
        for output in (self.expected_default_output, self.expected_requested_output):
            if not output or "\n" in output or "\r" in output:
                raise ValueError("expected outputs must be non-empty single lines")
            if any(sentinel.casefold() in output.casefold() for sentinel in PERSONAL_SENTINELS):
                raise ValueError("expected outputs must not contain a personal sentinel")
        return self

    @staticmethod
    def _validate_relative_path(value: str, *, field_name: str) -> None:
        path = Path(value)
        if (
            not value
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or any(sentinel.casefold() in value.casefold() for sentinel in PERSONAL_SENTINELS)
        ):
            raise ValueError(f"{field_name} must contain portable root-relative paths")


class CheckResultV1(StrictModel):
    """One independently observed pass/fail fact."""

    check_id: str
    verdict: Literal["pass", "fail"]
    detail: str
    observed: str | None = None


class PreparationReceiptV1(StrictModel):
    """Receipt for the prepared, failing governed baseline."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    operation: Literal["prepare"] = "prepare"
    profile_id: str
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str
    task_root: str
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

    schema_version: Literal["1.1.0"] = "1.1.0"
    operation: Literal["verify"] = "verify"
    profile_id: str
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str
    task_root: Literal["."] = "."
    framework_revision: str
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


def load_governed_task_profile(profile_path: str | Path | None = None) -> GovernedTaskV1:
    """Load one consumer-owned profile or return the stable default profile."""

    if profile_path is None:
        return GovernedTaskV1()
    path = _resolve(profile_path)
    try:
        raw = path.read_text(encoding="utf-8")
        if any(sentinel.casefold() in raw.casefold() for sentinel in PERSONAL_SENTINELS):
            raise ValueError("profile contains a personal sentinel")
        return GovernedTaskV1.model_validate_json(raw)
    except (OSError, ValueError) as exc:
        raise GovernedDeliveryError(
            "invalid_task_profile",
            f"Unable to load governed task profile: {exc}",
            path=str(path),
        ) from exc


def _profile_sha256(contract: GovernedTaskV1) -> str:
    """Hash one normalized task profile independently of JSON formatting."""

    return _canonical_sha256(contract.model_dump(mode="json"))


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

    return _run(["git", *args], cwd=task_root, check=check).stdout.rstrip("\n")


def _write(path: Path, content: str) -> None:
    """Write one prepared-fixture file with a final newline."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")


def _baseline_source(contract: GovernedTaskV1) -> str:
    """Return the selected adapter's working default and missing requested feature."""

    if contract.source_adapter == "hello-shared-lib":
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

    return '''"""Consumer status CLI backed by the clean-room project manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_status() -> dict[str, str]:
    """Load the consumer-owned project manifest."""

    return json.loads(Path(__file__).resolve().parents[1].joinpath("project.json").read_text())


def message() -> str:
    """Return the stable human-readable project status."""

    status = load_status()
    return f"{status['project_id']}: {status['status']}"


def main() -> int:
    """Print the current human-readable project status."""

    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(message())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _acceptance_tests(contract: GovernedTaskV1) -> str:
    """Return consumer-owned black-box tests, including the initial failure."""

    return f'''"""Acceptance tests supplied with the governed feature request."""

from __future__ import annotations

import subprocess
import sys
import unittest


DEFAULT_ARGS = {contract.default_command[1:]!r}
REQUESTED_ARGS = {contract.requested_command[1:]!r}


class GovernedTaskCliTest(unittest.TestCase):
    def run_app(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_default_behavior_is_preserved(self) -> None:
        completed = self.run_app(DEFAULT_ARGS)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), {contract.expected_default_output!r})

    def test_requested_behavior(self) -> None:
        completed = self.run_app(REQUESTED_ARGS)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), {contract.expected_requested_output!r})


if __name__ == "__main__":
    unittest.main()
'''


def _consumer_authority(contract: GovernedTaskV1) -> str:
    """Return the canonical minimal authority for the disposable consumer."""

    return f"""# {contract.project_id}

This repository is the disposable consumer for `{contract.title}`.

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
{shlex.join(contract.default_command)}
{shlex.join(contract.requested_command)}
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


def _baseline_readme(contract: GovernedTaskV1) -> str:
    """Return concise documentation for the already-working default behavior."""

    return f"""# {contract.project_id}

Run the current default behavior:

```bash
{shlex.join(contract.default_command)}
# {contract.expected_default_output}
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


def _cleanroom_component_revision(task_root: Path) -> str:
    """Return the integrity-recorded component revision for this task root."""

    receipt_path = task_root.parents[1] / ".loop-engineering" / "state" / "install_receipt.json"
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernedDeliveryError(
            "invalid_cleanroom_receipt",
            f"Unable to read the clean-room install receipt: {exc}",
            path=str(receipt_path),
        ) from exc
    revision = payload.get("component_revision")
    if not isinstance(revision, str) or not revision:
        raise GovernedDeliveryError(
            "invalid_cleanroom_receipt",
            "Clean-room receipt has no component revision.",
            path=str(receipt_path),
        )
    return revision


def _executing_framework_revision() -> str:
    """Return the exact Git revision containing the executing verifier source."""

    return _git(Path(__file__).resolve().parents[1], "rev-parse", "HEAD")


def _baseline_contract(task_root: Path) -> GovernedTaskV1:
    """Load the immutable task profile committed at the governed baseline."""

    try:
        raw = _git(task_root, "show", f"{BASELINE_TAG}:{TASK_CONTRACT_FILE}")
        return GovernedTaskV1.model_validate_json(raw)
    except (GovernedDeliveryError, ValueError) as exc:
        raise GovernedDeliveryError(
            "invalid_baseline_profile",
            f"Unable to load the baseline task profile: {exc}",
            path=TASK_CONTRACT_FILE,
        ) from exc


def _collect_checks(task_root: Path, contract: GovernedTaskV1) -> list[CheckResultV1]:
    """Execute the complete independent check set against current task state."""

    checks: list[CheckResultV1] = []
    checks.append(
        _command_check(
            task_root,
            check_id="default_behavior",
            argv=contract.default_command,
            expected_stdout=contract.expected_default_output,
        )
    )
    checks.append(
        _command_check(
            task_root,
            check_id="requested_behavior",
            argv=contract.requested_command,
            expected_stdout=contract.expected_requested_output,
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
        shlex.join(contract.requested_command) in readme
        and contract.expected_requested_output in readme
        and len(readme.splitlines()) <= 80
    )
    checks.append(
        _check_result(
            "documentation_current_minimal",
            readme_ok,
            "README has one concise runnable requested example" if readme_ok else "README example is missing, stale, or over 80 lines",
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
    recorded_framework_revision = _cleanroom_component_revision(task_root)
    executing_framework_revision = _executing_framework_revision()
    checks.append(
        _check_result(
            "framework_revision_binding",
            recorded_framework_revision == executing_framework_revision,
            (
                "prepared component equals executing verifier revision"
                if recorded_framework_revision == executing_framework_revision
                else "prepared component does not equal executing verifier revision: "
                f"prepared={recorded_framework_revision} executing={executing_framework_revision}"
            ),
            observed=executing_framework_revision,
        )
    )
    baseline_contract = _baseline_contract(task_root)
    baseline_profile_sha256 = _profile_sha256(baseline_contract)
    current_profile_sha256 = _profile_sha256(contract)
    checks.append(
        _check_result(
            "profile_contract_binding",
            baseline_profile_sha256 == current_profile_sha256,
            (
                "current task profile equals the governed baseline profile"
                if baseline_profile_sha256 == current_profile_sha256
                else "current task profile differs from the governed baseline profile"
            ),
            observed=current_profile_sha256,
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


def _validate_cleanroom_project(root: Path, contract: GovernedTaskV1) -> None:
    """Require the selected task project to be declared by the clean-room owner."""

    config_path = root / "consumer-config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        projects = payload["projects"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GovernedDeliveryError(
            "invalid_consumer_inventory",
            f"Unable to read the clean-room consumer inventory: {exc}",
            path="consumer-config.json",
        ) from exc
    selected = {
        "project_id": contract.project_id,
        "relative_path": contract.project_relative_path,
    }
    if selected not in projects:
        raise GovernedDeliveryError(
            "task_project_not_declared",
            "Task profile project is not declared by the clean-room inventory.",
            path=contract.project_relative_path,
        )


def _validate_source_adapter(task_root: Path, contract: GovernedTaskV1) -> None:
    """Validate the exact placeholder seam one known source adapter replaces."""

    source_path = task_root / contract.source_path
    if contract.source_adapter == "hello-shared-lib":
        try:
            original = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GovernedDeliveryError(
                "unexpected_adapter_source",
                f"Unable to read the hello shared-library source: {exc}",
                path=contract.source_path,
            ) from exc
        if "from cleanroom_shared import label" not in original or "def message()" not in original:
            raise GovernedDeliveryError(
                "unexpected_adapter_source",
                "hello-shared-lib adapter requires the clean-room hello-app source.",
                path=contract.source_path,
            )
        return

    manifest_path = task_root / "project.json"
    if source_path.exists():
        raise GovernedDeliveryError(
            "unexpected_adapter_source",
            "manifest-status-cli adapter refuses to overwrite an existing source file.",
            path=contract.source_path,
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernedDeliveryError(
            "unexpected_adapter_source",
            f"manifest-status-cli adapter requires a valid project.json: {exc}",
            path="project.json",
        ) from exc
    expected_manifest = {
        "project_id": contract.project_id,
        "status": "adapter-placeholder",
    }
    expected_json = json.dumps(expected_manifest, sort_keys=True, separators=(",", ":"))
    if (
        manifest != expected_manifest
        or contract.expected_default_output
        != f"{contract.project_id}: adapter-placeholder"
        or contract.expected_requested_output != expected_json
        or contract.requested_command != ["python", contract.source_path, "--json"]
    ):
        raise GovernedDeliveryError(
            "adapter_profile_mismatch",
            "manifest-status-cli profile does not match the declared placeholder and --json contract.",
            path="project.json",
        )


def prepare_governed_task(
    *,
    cleanroom_root: str | Path,
    framework_root: str | Path,
    profile_path: str | Path | None = None,
) -> PreparationReceiptV1:
    """Overlay, govern, and commit one profile-selected failing task baseline."""

    root = _resolve(cleanroom_root)
    framework = _resolve(framework_root)
    contract = load_governed_task_profile(profile_path)
    task_root = root / contract.project_relative_path
    source_path = task_root / contract.source_path
    receipt_path = root / ".loop-engineering" / "state" / "install_receipt.json"
    installer = framework / "scripts" / "install_governed_repo.py"
    if not receipt_path.is_file() or not task_root.is_dir():
        raise GovernedDeliveryError(
            "cleanroom_not_materialized",
            "Prepare requires a materialized clean-room containing the selected project.",
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
    _validate_cleanroom_project(root, contract)
    _validate_source_adapter(task_root, contract)
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
    _write(source_path, _baseline_source(contract))
    _write(task_root / "tests" / "test_cli.py", _acceptance_tests(contract))
    _write(task_root / "README.md", _baseline_readme(contract))
    _write(task_root / "CLAUDE.md", _consumer_authority(contract))
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
    requested_check = next(
        check for check in initial_checks if check.check_id == "requested_behavior"
    )
    if requested_check.verdict != "fail":
        raise GovernedDeliveryError(
            "requested_failure_not_observed",
            "Prepared task must fail the requested profile behavior.",
        )
    portable_check = next(check for check in initial_checks if check.check_id == "portable_content")
    if portable_check.verdict != "pass":
        raise GovernedDeliveryError(
            "prepared_content_not_portable",
            portable_check.detail,
        )
    return PreparationReceiptV1(
        profile_id=contract.profile_id,
        profile_sha256=_profile_sha256(contract),
        task_id=contract.task_id,
        task_root=contract.project_relative_path,
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
    baseline_contract = _baseline_contract(root)
    unsigned = {
        "schema_version": "1.1.0",
        "operation": "verify",
        "profile_id": baseline_contract.profile_id,
        "profile_sha256": _profile_sha256(baseline_contract),
        "task_id": contract.task_id,
        "task_root": ".",
        "framework_revision": _executing_framework_revision(),
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
