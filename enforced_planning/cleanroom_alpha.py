"""Build and exercise a portable clean-room loop-engineering alpha fixture.

The module owns the deterministic generator lifecycle plus a zero-LLM verified
loop. Fixture-specific repair knowledge is rendered into ``loop-spec.json``;
the runner itself only interprets guarded commands and declarative actions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


PROJECT_IDS = ("hello-app", "shared-lib")
SECRET_SENTINEL = "SECRET_SENTINEL"
PERSONAL_SENTINELS = ("/home/brian", "BrianMills2718")
DEFAULT_INSTANCE_ID = "cleanroom-alpha"
CONSUMER_CONFIG_RELATIVE_PATH = "consumer-config.json"
RECEIPT_RELATIVE_PATH = ".loop-engineering/state/install_receipt.json"
LOOP_SPEC_RELATIVE_PATH = "loop-spec.json"
TRACE_DIRECTORY_RELATIVE_PATH = ".loop-engineering/traces"
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
SAFE_SCALAR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")


class CleanroomError(RuntimeError):
    """Raised when a clean-room operation cannot be safely completed."""

    def __init__(self, code: str, message: str, *, path: str | None = None) -> None:
        """Create a fail-loud error with a stable machine-readable code."""

        super().__init__(message)
        self.code = code
        self.path = path

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-safe representation of the error."""

        payload = {"code": self.code, "message": str(self)}
        if self.path is not None:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class CleanroomSpec:
    """User-provided clean-room inputs after path normalization."""

    root: Path
    component_revision: str
    instance_id: str = DEFAULT_INSTANCE_ID
    projects_root: Path = field(default_factory=lambda: Path(os.environ.get("PROJECTS_ROOT", str(Path.home() / "projects"))))
    component_source: str = "local-enforced-planning"
    policy_pack_name: str = "example-policy-pack"
    consumer_projects: tuple[tuple[str, str], ...] = (("shared-lib", "projects/shared-lib"), ("hello-app", "projects/hello-app"))

    @classmethod
    def build(
        cls,
        *,
        root: str | Path,
        component_revision: str,
        instance_id: str = DEFAULT_INSTANCE_ID,
        projects_root: str | Path | None = None,
        component_source: str = "local-enforced-planning",
        policy_pack_name: str = "example-policy-pack",
        consumer_projects: list[dict[str, str]] | None = None,
    ) -> "CleanroomSpec":
        """Validate user inputs and return a normalized clean-room spec."""

        revision = component_revision.strip()
        if not SAFE_SCALAR_RE.fullmatch(revision):
            raise CleanroomError("invalid_component_revision", "component_revision must be a single safe scalar")
        normalized_root = _resolve_path(root)
        normalized_projects_root = _resolve_path(projects_root or Path.home() / "projects")
        _require_outside_projects_root(normalized_root, normalized_projects_root)
        instance = instance_id.strip()
        if not IDENTIFIER_RE.fullmatch(instance):
            raise CleanroomError("invalid_instance_id", "instance_id must be a lowercase portable identifier")
        source = component_source.strip()
        policy = policy_pack_name.strip()
        if not SAFE_SCALAR_RE.fullmatch(source):
            raise CleanroomError("invalid_component_source", "component_source must be a single safe scalar")
        if not IDENTIFIER_RE.fullmatch(policy):
            raise CleanroomError("invalid_policy_pack_name", "policy_pack_name must be a lowercase portable identifier")
        projects = _validate_consumer_projects(consumer_projects)
        return cls(
            root=normalized_root,
            component_revision=revision,
            instance_id=instance,
            projects_root=normalized_projects_root,
            component_source=source,
            policy_pack_name=policy,
            consumer_projects=projects,
        )


def load_consumer_config(path: str | Path) -> dict[str, Any]:
    """Load and validate user-neutral metadata without importing workspace state."""

    config_path = _resolve_path(path)
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanroomError("invalid_consumer_config", f"consumer config is not valid JSON: {exc}", path=str(config_path)) from exc
    if not isinstance(payload, dict):
        raise CleanroomError("invalid_consumer_config", "consumer config must be a JSON object", path=str(config_path))
    values: dict[str, Any] = {key: str(payload.get(key, "")).strip() for key in ("instance_id", "component_source", "policy_pack_name")}
    if any(not value for value in values.values()):
        raise CleanroomError("invalid_consumer_config", "instance_id, component_source, and policy_pack_name are required", path=str(config_path))
    if any(sentinel.lower() in json.dumps(payload).lower() for sentinel in PERSONAL_SENTINELS):
        raise CleanroomError("personal_config_leak", "consumer config contains a personal sentinel", path=str(config_path))
    values["consumer_projects"] = payload.get("projects")
    _validate_consumer_projects(values["consumer_projects"])
    return values


def _validate_consumer_projects(projects: list[dict[str, str]] | None) -> tuple[tuple[str, str], ...]:
    """Validate consumer project identity and root-relative paths."""

    if projects is None:
        return (("shared-lib", "projects/shared-lib"), ("hello-app", "projects/hello-app"))
    if not isinstance(projects, list) or not projects:
        raise CleanroomError("invalid_project_inventory", "projects must be a non-empty list")
    result: list[tuple[str, str]] = []
    for item in projects:
        if not isinstance(item, dict):
            raise CleanroomError("invalid_project_inventory", "each project must be an object")
        project_id, relative_path = str(item.get("project_id", "")).strip(), str(item.get("relative_path", "")).strip()
        path = Path(relative_path)
        if not IDENTIFIER_RE.fullmatch(project_id) or relative_path != f"projects/{project_id}" or path.is_absolute() or ".." in path.parts:
            raise CleanroomError("invalid_project_inventory", "project ids and root-relative paths are required")
        result.append((project_id, relative_path))
    if len({item[0] for item in result}) != len(result) or len({item[1] for item in result}) != len(result):
        raise CleanroomError("duplicate_project_inventory", "project ids and paths must be unique")
    return tuple(result)


@dataclass(frozen=True)
class PlannedWrite:
    """One file the materializer intends to write."""

    relative_path: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        """Return the planned write as a JSON object."""

        return {"relative_path": self.relative_path, "sha256": self.sha256}


@dataclass(frozen=True)
class MaterializationPlan:
    """Dry-run result describing all files that apply would create."""

    operation: Literal["plan"]
    root: str
    instance_id: str
    component_revision: str
    writes: list[PlannedWrite]
    directories: list[str]
    verdict: Literal["planned"] = "planned"

    def to_dict(self) -> dict[str, Any]:
        """Return the materialization plan as JSON-safe data."""

        return {
            "operation": self.operation,
            "root": self.root,
            "instance_id": self.instance_id,
            "component_revision": self.component_revision,
            "writes": [entry.to_dict() for entry in self.writes],
            "directories": self.directories,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class InstallReceipt:
    """Receipt recording the exact paths owned by one materialization."""

    operation: Literal["apply"]
    root: str
    instance_id: str
    component_revision: str
    owned_files: list[str]
    owned_directories: list[str]
    verdict: Literal["materialized"] = "materialized"

    def unsigned_dict(self) -> dict[str, Any]:
        """Return install ownership content covered by its integrity digest."""

        return {
            "operation": self.operation,
            "root": self.root,
            "instance_id": self.instance_id,
            "component_revision": self.component_revision,
            "owned_files": self.owned_files,
            "owned_directories": self.owned_directories,
            "verdict": self.verdict,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the integrity-bound install receipt as JSON-safe data."""

        unsigned = self.unsigned_dict()
        return {**unsigned, "receipt_sha256": _canonical_json_sha256(unsigned)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InstallReceipt":
        """Parse an install receipt from JSON data."""

        return cls(
            operation="apply",
            root=str(payload["root"]),
            instance_id=str(payload["instance_id"]),
            component_revision=str(payload["component_revision"]),
            owned_files=[str(item) for item in payload.get("owned_files", [])],
            owned_directories=[str(item) for item in payload.get("owned_directories", [])],
        )


@dataclass(frozen=True)
class Finding:
    """One verification or reset finding with a stable check id."""

    check_id: str
    severity: Literal["error", "warning"]
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Return the finding as JSON-safe data."""

        payload = {
            "check_id": self.check_id,
            "severity": self.severity,
            "message": self.message,
        }
        if self.path is not None:
            payload["path"] = self.path
        return payload


@dataclass(frozen=True)
class VerificationReport:
    """Verification result for a materialized clean room."""

    operation: Literal["verify"]
    root: str
    checks: list[str]
    findings: list[Finding]

    @property
    def verdict(self) -> Literal["pass", "fail"]:
        """Return pass only when no error findings exist."""

        return "fail" if any(finding.severity == "error" for finding in self.findings) else "pass"

    def to_dict(self) -> dict[str, Any]:
        """Return the verification report as JSON-safe data."""

        return {
            "operation": self.operation,
            "root": self.root,
            "checks": self.checks,
            "findings": [finding.to_dict() for finding in self.findings],
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class StatusReport:
    """Current clean-room state summary."""

    operation: Literal["status"]
    root: str
    materialized: bool
    receipt_path: str
    verdict: Literal["materialized", "absent"]

    def to_dict(self) -> dict[str, Any]:
        """Return the status report as JSON-safe data."""

        return {
            "operation": self.operation,
            "root": self.root,
            "materialized": self.materialized,
            "receipt_path": self.receipt_path,
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class ResetReport:
    """Result of removing receipt-owned clean-room artifacts."""

    operation: Literal["reset"]
    root: str
    removed_paths: list[str]
    findings: list[Finding]

    @property
    def verdict(self) -> Literal["reset", "fail"]:
        """Return reset only when no error findings exist."""

        return "fail" if any(finding.severity == "error" for finding in self.findings) else "reset"

    def to_dict(self) -> dict[str, Any]:
        """Return the reset report as JSON-safe data."""

        return {
            "operation": self.operation,
            "root": self.root,
            "removed_paths": self.removed_paths,
            "findings": [finding.to_dict() for finding in self.findings],
            "verdict": self.verdict,
        }


@dataclass(frozen=True)
class GuardedFile:
    """One verifier source whose content must match the materialized contract."""

    relative_path: str
    sha256: str


@dataclass(frozen=True)
class DeclarativeTextReplacement:
    """A bounded text replacement supplied by fixture config, not runner code."""

    action_id: str
    relative_path: str
    old_text: str
    new_text: str


@dataclass(frozen=True)
class LoopSpec:
    """Validated deterministic loop inputs loaded from the generated fixture."""

    loop_id: str
    verifier_command: list[str]
    guarded_files: list[GuardedFile]
    max_iterations: int
    max_cost_usd: float
    require_initial_failure: bool
    actions: list[DeclarativeTextReplacement]


@dataclass(frozen=True)
class LoopTransition:
    """One independently verified state observation and optional worker action."""

    sequence: int
    iteration: int
    timestamp_utc: str
    state_before_sha256: str
    verifier_command: list[str]
    verifier_exit_code: int
    verifier_verdict: Literal["pass", "fail"]
    verifier_stdout_sha256: str
    verifier_stderr_sha256: str
    worker_mode: str
    action_id: str | None
    action_status: Literal[
        "none",
        "applied",
        "no_op",
        "self_certification_rejected",
        "failed",
    ]
    action_error_code: str | None
    action_error_message: str | None
    action_error_path: str | None
    state_after_sha256: str

    def to_dict(self) -> dict[str, Any]:
        """Return the transition as canonical JSON-safe data."""

        return {
            "sequence": self.sequence,
            "iteration": self.iteration,
            "timestamp_utc": self.timestamp_utc,
            "state_before_sha256": self.state_before_sha256,
            "verifier_command": self.verifier_command,
            "verifier_exit_code": self.verifier_exit_code,
            "verifier_verdict": self.verifier_verdict,
            "verifier_stdout_sha256": self.verifier_stdout_sha256,
            "verifier_stderr_sha256": self.verifier_stderr_sha256,
            "worker_mode": self.worker_mode,
            "action_id": self.action_id,
            "action_status": self.action_status,
            "action_error_code": self.action_error_code,
            "action_error_message": self.action_error_message,
            "action_error_path": self.action_error_path,
            "state_after_sha256": self.state_after_sha256,
        }


@dataclass
class LoopRunReceipt:
    """Canonical loop trace shared by the runner, tests, and future adapters."""

    operation: Literal["run-demo"]
    schema_version: int
    run_id: str
    loop_id: str
    root: str
    component_revision: str
    started_at_utc: str
    completed_at_utc: str | None
    status: Literal["running", "completed", "interrupted", "failed"]
    stop_reason: str | None
    iterations_used: int
    max_iterations: int
    cost_used_usd: float
    max_cost_usd: float
    transitions: list[LoopTransition]
    trace_sha256: str = ""

    @property
    def verdict(self) -> Literal["pass", "fail"]:
        """Return pass only for a completed run stopped by verifier success."""

        if self.status == "completed" and self.stop_reason == "verifier_satisfied":
            return "pass"
        return "fail"

    def unsigned_dict(self) -> dict[str, Any]:
        """Return receipt content covered by the trace digest."""

        return {
            "operation": self.operation,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "loop_id": self.loop_id,
            "root": self.root,
            "component_revision": self.component_revision,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "iterations_used": self.iterations_used,
            "max_iterations": self.max_iterations,
            "cost_used_usd": self.cost_used_usd,
            "max_cost_usd": self.max_cost_usd,
            "transitions": [transition.to_dict() for transition in self.transitions],
            "verdict": self.verdict,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the signed receipt as JSON-safe data."""

        return {**self.unsigned_dict(), "trace_sha256": self.trace_sha256}


@dataclass(frozen=True)
class LoopTraceVerification:
    """Integrity and semantic validation result for a stored loop receipt."""

    operation: Literal["verify-trace"]
    trace_path: str
    findings: list[Finding]

    @property
    def verdict(self) -> Literal["pass", "fail"]:
        """Return pass only when the trace has no error findings."""

        return "fail" if any(item.severity == "error" for item in self.findings) else "pass"

    def to_dict(self) -> dict[str, Any]:
        """Return the trace verification as JSON-safe data."""

        return {
            "operation": self.operation,
            "trace_path": self.trace_path,
            "findings": [finding.to_dict() for finding in self.findings],
            "verdict": self.verdict,
        }


def current_git_revision(repo_root: Path) -> str:
    """Return the current git commit for component locking."""

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def plan_cleanroom(spec: CleanroomSpec) -> MaterializationPlan:
    """Return a dry-run plan for the clean-room fixture without writing files."""

    files = _render_files(spec)
    writes = [
        PlannedWrite(relative_path=relative_path, sha256=_sha256(content))
        for relative_path, content in sorted(files.items())
    ]
    return MaterializationPlan(
        operation="plan",
        root=str(spec.root),
        instance_id=spec.instance_id,
        component_revision=spec.component_revision,
        writes=writes,
        directories=sorted(_planned_directories(files)),
    )


def materialize_cleanroom(spec: CleanroomSpec) -> InstallReceipt:
    """Create the clean-room fixture and write an install receipt."""

    plan = plan_cleanroom(spec)
    files = _render_files(spec)
    for directory in plan.directories:
        target_dir = _safe_join(spec.root, directory)
        if target_dir.exists() and not target_dir.is_dir():
            raise CleanroomError("directory_conflict", "planned directory path is not a directory", path=directory)
        target_dir.mkdir(parents=True, exist_ok=True)

    for relative_path, content in files.items():
        target = _safe_join(spec.root, relative_path)
        if target.exists() and not target.is_file():
            raise CleanroomError("non_file_conflict", "planned file path is not a regular file", path=relative_path)
        if target.exists() and target.read_text(encoding="utf-8") != content:
            raise CleanroomError("foreign_overwrite", "refusing to overwrite existing non-matching file", path=relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    receipt = InstallReceipt(
        operation="apply",
        root=".",
        instance_id=spec.instance_id,
        component_revision=spec.component_revision,
        owned_files=sorted(files),
        owned_directories=plan.directories,
    )
    receipt_path = _receipt_path(spec.root)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def verify_cleanroom(root: str | Path, *, projects_root: str | Path | None = None) -> VerificationReport:
    """Verify a materialized clean-room root and return exact findings."""

    normalized_root = _resolve_path(root)
    normalized_projects_root = _resolve_path(projects_root or Path.home() / "projects")
    checks = [
        "root_external",
        "receipt_present",
        "receipt_paths_owned",
        "inventory_materialization",
        "required_files_present",
        "no_secret_sentinel",
        "no_personal_sentinels",
        "no_workspace_symlinks",
    ]
    findings: list[Finding] = []

    if _is_relative_to(normalized_root, normalized_projects_root):
        findings.append(
            Finding(
                check_id="root_external",
                severity="error",
                message="clean-room root must not be inside the projects workspace",
                path=str(normalized_root),
            )
        )
    if not normalized_root.exists():
        findings.append(
            Finding(
                check_id="root_exists",
                severity="error",
                message="clean-room root does not exist",
                path=str(normalized_root),
            )
        )
        return VerificationReport(operation="verify", root=str(normalized_root), checks=checks, findings=findings)

    receipt = _load_receipt(normalized_root, findings)
    if receipt is not None:
        findings.extend(_validate_receipt_paths(normalized_root, receipt))

    expected_files = set(_render_files_for_existing(normalized_root, receipt).keys())
    for relative_path in sorted(expected_files | {RECEIPT_RELATIVE_PATH}):
        if not _safe_join(normalized_root, relative_path).exists():
            findings.append(
                Finding(
                    check_id="required_files_present",
                    severity="error",
                    message="required clean-room file is missing",
                    path=relative_path,
                )
            )

    project_dir = normalized_root / "projects"
    actual_projects = sorted(path.name for path in project_dir.iterdir() if path.is_dir()) if project_dir.exists() else []
    declared_projects = _declared_project_ids(normalized_root / "inventory" / "projects.yaml")
    if actual_projects != declared_projects:
        findings.append(
            Finding(
                check_id="inventory_materialization_mismatch",
                severity="error",
                message=f"declared projects {declared_projects} do not match materialized directories {actual_projects}",
                path="projects",
            )
        )

    findings.extend(_scan_tree(normalized_root, normalized_projects_root))
    return VerificationReport(operation="verify", root=str(normalized_root), checks=checks, findings=findings)


def _declared_project_ids(path: Path) -> list[str]:
    """Read project ids from the generated simple YAML inventory."""

    if not path.exists():
        return []
    return sorted(line.split(":", 1)[1].strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("- project_id:"))


def status_cleanroom(root: str | Path) -> StatusReport:
    """Return whether a clean-room root currently has an install receipt."""

    normalized_root = _resolve_path(root)
    receipt_path = _receipt_path(normalized_root)
    materialized = receipt_path.exists()
    return StatusReport(
        operation="status",
        root=str(normalized_root),
        materialized=materialized,
        receipt_path=str(receipt_path),
        verdict="materialized" if materialized else "absent",
    )


def reset_cleanroom(root: str | Path) -> ResetReport:
    """Delete only receipt-owned files and directories from a clean-room root."""

    normalized_root = _resolve_path(root)
    findings: list[Finding] = []
    receipt = _load_receipt(normalized_root, findings)
    if receipt is None:
        return ResetReport(operation="reset", root=str(normalized_root), removed_paths=[], findings=findings)

    path_findings = _validate_receipt_paths(normalized_root, receipt)
    if path_findings:
        return ResetReport(operation="reset", root=str(normalized_root), removed_paths=[], findings=path_findings)

    removed: list[str] = []
    for relative_path in sorted(set(receipt.owned_files + [RECEIPT_RELATIVE_PATH]), key=lambda item: len(item), reverse=True):
        target = _safe_join(normalized_root, relative_path)
        if target.exists():
            target.unlink()
            removed.append(relative_path)

    for relative_path in sorted(set(receipt.owned_directories), key=lambda item: len(item), reverse=True):
        target = _safe_join(normalized_root, relative_path)
        if not target.exists():
            continue
        try:
            target.rmdir()
            removed.append(relative_path)
        except OSError:
            findings.append(
                Finding(
                    check_id="reset_directory_not_empty",
                    severity="warning",
                    message="directory still contains unowned content and was left in place",
                    path=relative_path,
                )
            )

    return ResetReport(operation="reset", root=str(normalized_root), removed_paths=removed, findings=findings)


def load_loop_spec(root: str | Path) -> LoopSpec:
    """Load and validate the generated declarative loop contract."""

    normalized_root = _resolve_path(root)
    spec_path = _safe_join(normalized_root, LOOP_SPEC_RELATIVE_PATH)
    try:
        payload = json.loads(spec_path.read_text(encoding="utf-8"))
        verifier = payload["verifier"]
        budget = payload["budget"]
        command = verifier["command"]
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            raise ValueError("verifier.command must be a non-empty argv string list")
        max_iterations = int(budget["max_iterations"])
        max_cost_usd = float(budget["max_cost_usd"])
        if max_iterations < 0:
            raise ValueError("budget.max_iterations must be non-negative")
        if max_cost_usd < 0:
            raise ValueError("budget.max_cost_usd must be non-negative")
        guarded_files = [
            GuardedFile(relative_path=str(item["relative_path"]), sha256=str(item["sha256"]))
            for item in verifier["guarded_files"]
        ]
        actions = [
            DeclarativeTextReplacement(
                action_id=str(item["action_id"]),
                relative_path=str(item["relative_path"]),
                old_text=str(item["old_text"]),
                new_text=str(item["new_text"]),
            )
            for item in payload["actions"]
        ]
        return LoopSpec(
            loop_id=str(payload["loop_id"]),
            verifier_command=command,
            guarded_files=guarded_files,
            max_iterations=max_iterations,
            max_cost_usd=max_cost_usd,
            require_initial_failure=bool(payload["require_initial_failure"]),
            actions=actions,
        )
    except FileNotFoundError as exc:
        raise CleanroomError("loop_spec_missing", "loop spec is missing", path=LOOP_SPEC_RELATIVE_PATH) from exc
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise CleanroomError("loop_spec_invalid", f"loop spec is invalid: {exc}", path=LOOP_SPEC_RELATIVE_PATH) from exc


def run_demo_loop(
    root: str | Path,
    *,
    worker_mode: Literal["repair", "no-op", "self-certify", "interrupt-after-action"] = "repair",
    max_iterations: int | None = None,
) -> LoopRunReceipt:
    """Run a bounded deterministic worker whose success only the verifier certifies."""

    normalized_root = _resolve_path(root)
    findings: list[Finding] = []
    install_receipt = _load_receipt(normalized_root, findings)
    if install_receipt is None or findings:
        first = findings[0]
        raise CleanroomError(first.check_id, first.message, path=first.path)
    loop_spec = load_loop_spec(normalized_root)
    iteration_limit = loop_spec.max_iterations if max_iterations is None else max_iterations
    if iteration_limit < 0:
        raise CleanroomError("invalid_iteration_budget", "max_iterations must be non-negative")
    _verify_guarded_files(normalized_root, loop_spec.guarded_files)

    receipt = LoopRunReceipt(
        operation="run-demo",
        schema_version=1,
        run_id=uuid.uuid4().hex,
        loop_id=loop_spec.loop_id,
        root=".",
        component_revision=install_receipt.component_revision,
        started_at_utc=_utc_now(),
        completed_at_utc=None,
        status="running",
        stop_reason=None,
        iterations_used=0,
        max_iterations=iteration_limit,
        cost_used_usd=0,
        max_cost_usd=loop_spec.max_cost_usd,
        transitions=[],
    )
    trace_relative_path = f"{TRACE_DIRECTORY_RELATIVE_PATH}/{receipt.run_id}.json"
    _register_owned_file(normalized_root, install_receipt, trace_relative_path)
    _write_loop_trace(normalized_root, trace_relative_path, receipt)

    while True:
        _verify_guarded_files(normalized_root, loop_spec.guarded_files)
        state_before = _state_digest(normalized_root)
        verifier = _run_verifier(normalized_root, loop_spec.verifier_command)
        is_initial_observation = not receipt.transitions

        if verifier["verdict"] == "pass":
            receipt.transitions.append(
                _transition(
                    receipt=receipt,
                    state_before=state_before,
                    verifier=verifier,
                    worker_mode=worker_mode,
                    action_id=None,
                    action_status="none",
                    state_after=state_before,
                )
            )
            receipt.status = "failed" if is_initial_observation and loop_spec.require_initial_failure else "completed"
            receipt.stop_reason = "initial_failure_not_observed" if receipt.status == "failed" else "verifier_satisfied"
            receipt.completed_at_utc = _utc_now()
            _write_loop_trace(normalized_root, trace_relative_path, receipt)
            return receipt

        if receipt.iterations_used >= iteration_limit:
            receipt.transitions.append(
                _transition(
                    receipt=receipt,
                    state_before=state_before,
                    verifier=verifier,
                    worker_mode=worker_mode,
                    action_id=None,
                    action_status="none",
                    state_after=state_before,
                )
            )
            receipt.status = "failed"
            receipt.stop_reason = "iteration_budget_exhausted"
            receipt.completed_at_utc = _utc_now()
            _write_loop_trace(normalized_root, trace_relative_path, receipt)
            return receipt

        action_id: str | None = None
        action_status: Literal["applied", "no_op", "self_certification_rejected", "failed"]
        try:
            if worker_mode in {"repair", "interrupt-after-action"}:
                action = loop_spec.actions[receipt.iterations_used]
                action_id = action.action_id
                _apply_text_replacement(normalized_root, action)
                action_status = "applied"
            elif worker_mode == "no-op":
                action_status = "no_op"
            elif worker_mode == "self-certify":
                action_status = "self_certification_rejected"
            else:
                raise CleanroomError("unknown_worker_mode", f"unsupported worker mode: {worker_mode}")
        except (CleanroomError, IndexError) as exc:
            action_status = "failed"
            if isinstance(exc, CleanroomError):
                action_error_code = exc.code
                action_error_message = str(exc)
                action_error_path = exc.path
            else:
                action_error_code = "worker_action_missing"
                action_error_message = "no declarative worker action remains for this iteration"
                action_error_path = None
            receipt.iterations_used += 1
            receipt.transitions.append(
                _transition(
                    receipt=receipt,
                    state_before=state_before,
                    verifier=verifier,
                    worker_mode=worker_mode,
                    action_id=action_id,
                    action_status=action_status,
                    state_after=_state_digest(normalized_root),
                    action_error_code=action_error_code,
                    action_error_message=action_error_message,
                    action_error_path=action_error_path,
                )
            )
            receipt.status = "failed"
            receipt.stop_reason = "worker_action_failed"
            receipt.completed_at_utc = _utc_now()
            _write_loop_trace(normalized_root, trace_relative_path, receipt)
            if isinstance(exc, CleanroomError):
                return receipt
            return receipt

        receipt.iterations_used += 1
        receipt.transitions.append(
            _transition(
                receipt=receipt,
                state_before=state_before,
                verifier=verifier,
                worker_mode=worker_mode,
                action_id=action_id,
                action_status=action_status,
                state_after=_state_digest(normalized_root),
            )
        )
        if worker_mode == "interrupt-after-action":
            receipt.status = "interrupted"
            receipt.stop_reason = "interrupted_after_action"
            receipt.completed_at_utc = _utc_now()
            _write_loop_trace(normalized_root, trace_relative_path, receipt)
            return receipt
        _write_loop_trace(normalized_root, trace_relative_path, receipt)


def verify_loop_trace(trace_path: str | Path) -> LoopTraceVerification:
    """Verify the digest and success invariants of a canonical loop receipt."""

    normalized_path = _resolve_path(trace_path)
    findings: list[Finding] = []
    try:
        payload = json.loads(normalized_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        findings.append(Finding("trace_readable", "error", f"trace cannot be read: {exc}", str(normalized_path)))
        return LoopTraceVerification("verify-trace", str(normalized_path), findings)

    recorded_digest = payload.get("trace_sha256")
    unsigned = {key: value for key, value in payload.items() if key != "trace_sha256"}
    if not isinstance(recorded_digest, str) or recorded_digest != _canonical_json_sha256(unsigned):
        findings.append(Finding("trace_digest", "error", "trace digest does not match canonical content", str(normalized_path)))

    transitions = payload.get("transitions")
    if not isinstance(transitions, list):
        findings.append(Finding("trace_transitions", "error", "transitions must be a list", str(normalized_path)))
        transitions = []
    sequences = [item.get("sequence") for item in transitions if isinstance(item, dict)]
    if sequences != list(range(len(transitions))):
        findings.append(Finding("trace_sequence", "error", "transition sequence is not contiguous", str(normalized_path)))

    if payload.get("verdict") == "pass":
        last_verdict = transitions[-1].get("verifier_verdict") if transitions and isinstance(transitions[-1], dict) else None
        if payload.get("status") != "completed" or payload.get("stop_reason") != "verifier_satisfied" or last_verdict != "pass":
            findings.append(Finding("trace_success_invariant", "error", "passing trace lacks independent final verifier success", str(normalized_path)))
    return LoopTraceVerification("verify-trace", str(normalized_path), findings)


def _verify_guarded_files(root: Path, guarded_files: list[GuardedFile]) -> None:
    """Fail before verification when a declared verifier source has changed."""

    for guarded in guarded_files:
        target = _safe_join(root, guarded.relative_path)
        if not target.is_file() or _sha256(target.read_text(encoding="utf-8")) != guarded.sha256:
            raise CleanroomError(
                "verifier_integrity_failed",
                "guarded verifier content does not match the loop spec",
                path=guarded.relative_path,
            )


def _run_verifier(root: Path, command: list[str]) -> dict[str, Any]:
    """Run the independent verifier without a shell and retain evidence hashes."""

    try:
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    except OSError as exc:
        raise CleanroomError("verifier_unavailable", f"verifier could not run: {exc}") from exc
    return {
        "command": list(command),
        "exit_code": result.returncode,
        "verdict": "pass" if result.returncode == 0 else "fail",
        "stdout_sha256": _sha256(result.stdout),
        "stderr_sha256": _sha256(result.stderr),
    }


def _transition(
    *,
    receipt: LoopRunReceipt,
    state_before: str,
    verifier: dict[str, Any],
    worker_mode: str,
    action_id: str | None,
    action_status: Literal["none", "applied", "no_op", "self_certification_rejected", "failed"],
    state_after: str,
    action_error_code: str | None = None,
    action_error_message: str | None = None,
    action_error_path: str | None = None,
) -> LoopTransition:
    """Build one ordered transition from verifier and worker observations."""

    return LoopTransition(
        sequence=len(receipt.transitions),
        iteration=receipt.iterations_used,
        timestamp_utc=_utc_now(),
        state_before_sha256=state_before,
        verifier_command=list(verifier["command"]),
        verifier_exit_code=int(verifier["exit_code"]),
        verifier_verdict=verifier["verdict"],
        verifier_stdout_sha256=str(verifier["stdout_sha256"]),
        verifier_stderr_sha256=str(verifier["stderr_sha256"]),
        worker_mode=worker_mode,
        action_id=action_id,
        action_status=action_status,
        action_error_code=action_error_code,
        action_error_message=action_error_message,
        action_error_path=action_error_path,
        state_after_sha256=state_after,
    )


def _apply_text_replacement(root: Path, action: DeclarativeTextReplacement) -> None:
    """Apply one exact declarative replacement with a single-match precondition."""

    target = _safe_join(root, action.relative_path)
    if not target.is_file():
        raise CleanroomError("worker_target_missing", "worker action target is missing", path=action.relative_path)
    content = target.read_text(encoding="utf-8")
    if content.count(action.old_text) != 1:
        raise CleanroomError(
            "worker_precondition_failed",
            "worker replacement requires exactly one old-text match",
            path=action.relative_path,
        )
    target.write_text(content.replace(action.old_text, action.new_text, 1), encoding="utf-8")


def _state_digest(root: Path) -> str:
    """Hash authoritative instance files while excluding changing local loop state."""

    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".loop-engineering/"):
            continue
        entries.append(f"{relative}\0{hashlib.sha256(path.read_bytes()).hexdigest()}")
    return _sha256("\n".join(entries))


def _write_loop_trace(root: Path, relative_path: str, receipt: LoopRunReceipt) -> None:
    """Atomically persist the latest truthful receipt after every transition."""

    trace_path = _safe_join(root, relative_path)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    receipt.trace_sha256 = _canonical_json_sha256(receipt.unsigned_dict())
    temp_path = trace_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_path, trace_path)


def _register_owned_file(root: Path, receipt: InstallReceipt, relative_path: str) -> None:
    """Add a runtime-produced receipt to the install ownership manifest."""

    _safe_join(root, relative_path)
    if relative_path in receipt.owned_files:
        return
    updated = InstallReceipt(
        operation="apply",
        root=receipt.root,
        instance_id=receipt.instance_id,
        component_revision=receipt.component_revision,
        owned_files=sorted([*receipt.owned_files, relative_path]),
        owned_directories=receipt.owned_directories,
    )
    _receipt_path(root).write_text(json.dumps(updated.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    """Hash a JSON object using a stable compact representation."""

    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _utc_now() -> str:
    """Return a timezone-aware timestamp for observable loop transitions."""

    return datetime.now(UTC).isoformat()


def _resolve_path(path: str | Path) -> Path:
    """Resolve a user-supplied path without requiring it to exist."""

    return Path(path).expanduser().resolve(strict=False)


def _is_relative_to(path: Path, possible_parent: Path) -> bool:
    """Return whether path is inside possible_parent."""

    try:
        path.relative_to(possible_parent)
        return True
    except ValueError:
        return False


def _require_outside_projects_root(root: Path, projects_root: Path) -> None:
    """Fail when the clean-room root would live inside the projects workspace."""

    if _is_relative_to(root, projects_root):
        raise CleanroomError(
            "root_under_workspace",
            "clean-room root must not be inside the projects workspace",
            path=str(root),
        )


def _safe_join(root: Path, relative_path: str) -> Path:
    """Resolve a fixture-relative path and fail if it escapes the root."""

    candidate = (root / relative_path).resolve(strict=False)
    if not _is_relative_to(candidate, root):
        raise CleanroomError("path_escape", "relative path escapes clean-room root", path=relative_path)
    return candidate


def _sha256(content: str) -> str:
    """Return the SHA-256 digest for generated text content."""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _planned_directories(files: dict[str, str]) -> set[str]:
    """Return every directory the generated fixture owns."""

    directories = {
        ".loop-engineering",
        ".loop-engineering/state",
        ".loop-engineering/traces",
        ".loop-engineering/receipts",
        "generated",
        "inventory",
        "policy-pack",
        "procedures",
        "projects",
    }
    for relative_path in files:
        parent = Path(relative_path).parent
        while str(parent) not in ("", "."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _render_files_for_existing(root: Path, receipt: InstallReceipt | None) -> dict[str, str]:
    """Render expected files using an existing receipt revision when available."""

    revision = receipt.component_revision if receipt is not None else "unknown"
    config_path = root / CONSUMER_CONFIG_RELATIVE_PATH
    metadata = load_consumer_config(config_path) if config_path.exists() else {}
    spec = CleanroomSpec.build(root=root, component_revision=revision, projects_root=Path.home() / "projects", **metadata)
    return _render_files(spec)


def _render_files(spec: CleanroomSpec) -> dict[str, str]:
    """Render all deterministic files for the clean-room fixture."""

    files = {
        "README.md": _root_readme(spec),
        "Makefile": _root_makefile(spec),
        "cleanroom.yaml": _cleanroom_yaml(spec),
        CONSUMER_CONFIG_RELATIVE_PATH: _consumer_config_json(spec),
        "component-lock.yaml": _component_lock_yaml(spec),
        "inventory/projects.yaml": _projects_inventory_yaml(spec),
        "policy-pack/README.md": _policy_readme(spec),
        "policy-pack/registry.yaml": _policy_registry_yaml(spec),
        "procedures/README.md": _procedures_readme(),
        "generated/instructions.md": _generated_instructions(),
    }
    if _is_demo_fixture(spec):
        files.update({LOOP_SPEC_RELATIVE_PATH: _loop_spec_json(), "projects/shared-lib/Makefile": _shared_lib_makefile(), "projects/shared-lib/src/cleanroom_shared.py": _shared_lib_module(), "projects/hello-app/Makefile": _hello_app_makefile(), "projects/hello-app/src/hello_app.py": _hello_app_module(), "projects/hello-app/src/expected_message.txt": "hello-app uses wrong-lib\n"})
    else:
        for project_id, relative_path in spec.consumer_projects:
            files[f"{relative_path}/Makefile"] = _generic_project_makefile()
            files[f"{relative_path}/project.json"] = _generic_project_json(project_id)
    return files


def _root_readme(spec: CleanroomSpec) -> str:
    """Return the root README content for generated users."""

    if not _is_demo_fixture(spec):
        return """# Loop-Engineering Clean Room

This generated alpha contains consumer-declared placeholder projects. Each
placeholder exposes `make verify`; replace it through a consumer-owned source
and build adapter before using the ecosystem for real work.

- `inventory/projects.yaml` is the project inventory authority.
- `policy-pack/registry.yaml` is example policy content.
- `.loop-engineering/state/` stores lifecycle receipts.
- No deterministic repair demo is installed for custom inventories.
"""
    return """# Loop-Engineering Clean Room

This generated directory is a synthetic alpha fixture for testing portable
ecosystem governance. Replace the example inventory and policy pack with your
own project list and rules after the fixture verifies locally.

Important locations:

- `inventory/projects.yaml` lists the synthetic projects.
- `policy-pack/registry.yaml` contains example policy rules.
- `.loop-engineering/state/` stores receipts and local state.
- `loop-spec.json` declares the deterministic verifier, budgets, and demo repair.
- `generated/` contains derived outputs and is never authority.

The generated demo intentionally starts with one failing expectation. The
`run-demo` command observes, repairs, independently verifies, and traces it.
"""


def _root_makefile(spec: CleanroomSpec | None = None) -> str:
    """Return a root Makefile with a deterministic verification command."""

    projects = spec.consumer_projects if spec is not None else (("shared-lib", "projects/shared-lib"), ("hello-app", "projects/hello-app"))
    commands = "\n".join(f"\t$(MAKE) -C {relative_path} verify" for _, relative_path in projects)
    return f""".PHONY: verify

verify:
{commands}
"""


def _cleanroom_yaml(spec: CleanroomSpec) -> str:
    """Return the user-editable clean-room configuration."""

    project_lines = []
    for project_id, relative_path in spec.consumer_projects:
        role = "library" if project_id == "shared-lib" else "application"
        project_lines.extend([f"  - project_id: {project_id}", f"    relative_path: {relative_path}", f"    role: {role}"])
    demo = """demo_loop:
  loop_id: repair-known-failure
  verifier_command: make verify
  max_iterations: 3
  max_cost_usd: 0
""" if _is_demo_fixture(spec) else ""
    return f"""schema_version: 1
instance_id: {spec.instance_id}
components:
  - component_id: governance
    source_uri: {spec.component_source}
    revision: {spec.component_revision}
projects:
{chr(10).join(project_lines)}
{demo}
"""


def _consumer_config_json(spec: CleanroomSpec) -> str:
    """Return the normalized consumer-owned metadata captured in the fixture."""

    return json.dumps(
        {
            "schema_version": 1,
            "instance_id": spec.instance_id,
            "component_source": spec.component_source,
            "policy_pack_name": spec.policy_pack_name,
            "projects": [{"project_id": project_id, "relative_path": relative_path} for project_id, relative_path in spec.consumer_projects],
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def _is_demo_fixture(spec: CleanroomSpec) -> bool:
    """Return whether the requested inventory is the deterministic repair demo."""

    return spec.consumer_projects == (("shared-lib", "projects/shared-lib"), ("hello-app", "projects/hello-app"))


def _generic_project_makefile() -> str:
    """Return the minimal verifier interface for a consumer project placeholder."""

    return ".PHONY: verify\n\nverify:\n\tpython3 -m json.tool project.json >/dev/null\n"


def _generic_project_json(project_id: str) -> str:
    """Return a deterministic placeholder manifest owned by the consumer adapter."""

    return json.dumps({"project_id": project_id, "status": "adapter-placeholder"}, indent=2, sort_keys=True) + "\n"


def _loop_spec_json() -> str:
    """Return the declarative deterministic loop and verifier-integrity contract."""

    payload = {
        "schema_version": 1,
        "loop_id": "repair-known-failure",
        "require_initial_failure": True,
        "verifier": {
            "command": ["make", "verify"],
            "guarded_files": [
                {"relative_path": "Makefile", "sha256": _sha256(_root_makefile())},
                {
                    "relative_path": "projects/hello-app/Makefile",
                    "sha256": _sha256(_hello_app_makefile()),
                },
                {
                    "relative_path": "projects/shared-lib/Makefile",
                    "sha256": _sha256(_shared_lib_makefile()),
                },
            ],
        },
        "budget": {"max_iterations": 3, "max_cost_usd": 0},
        "actions": [
            {
                "action_id": "repair-expected-message",
                "kind": "replace_text",
                "relative_path": "projects/hello-app/src/expected_message.txt",
                "old_text": "hello-app uses wrong-lib\n",
                "new_text": "hello-app uses shared-lib\n",
            }
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _component_lock_yaml(spec: CleanroomSpec) -> str:
    """Return the component lock file content."""

    return f"""schema_version: 1
components:
  - component_id: governance
    source_uri: {spec.component_source}
    revision: {spec.component_revision}
"""


def _projects_inventory_yaml(spec: CleanroomSpec) -> str:
    """Return the synthetic project inventory."""

    lines = ["schema_version: 1", "projects:"]
    for project_id, relative_path in spec.consumer_projects:
        role = "library" if project_id == "shared-lib" else "application"
        lines.extend([f"  - project_id: {project_id}", f"    relative_path: {relative_path}", f"    role: {role}"])
    return "\n".join(lines) + "\n"


def _policy_readme(spec: CleanroomSpec) -> str:
    """Return the policy-pack README content."""

    return f"""# Policy Pack: {spec.policy_pack_name}

These rules are synthetic. They demonstrate where a user would place their own
ecosystem policy without importing private workspace policy.
"""


def _policy_registry_yaml(spec: CleanroomSpec) -> str:
    """Return a minimal synthetic policy registry."""

    return f"""schema_version: 1
policy_pack_name: {spec.policy_pack_name}
policies:
  - policy_id: require-make-verify
    level: suggestion
    description: Each fixture project exposes `make verify`.
  - policy_id: generated-state-is-not-authority
    level: suggestion
    description: Derived files under generated/ are never source authority.
"""


def _procedures_readme() -> str:
    """Return the procedures placeholder content."""

    return """# Procedures

The alpha installs only this placeholder. Versioned cross-client procedures
remain a later distribution concern.
"""


def _shared_lib_makefile() -> str:
    """Return the shared-lib verification Makefile."""

    return """.PHONY: verify

verify:
\tPYTHONDONTWRITEBYTECODE=1 python -c "from src.cleanroom_shared import label; assert label() == 'shared-lib'"
"""


def _shared_lib_module() -> str:
    """Return the shared library Python module."""

    return '''"""Synthetic shared library for the clean-room fixture."""


def label() -> str:
    """Return the fixture library label used by hello-app."""

    return "shared-lib"
'''


def _hello_app_makefile() -> str:
    """Return the hello-app verification Makefile."""

    return """.PHONY: verify

verify:
\tPYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:../shared-lib/src python -c "from pathlib import Path; from hello_app import message; expected = Path('src/expected_message.txt').read_text().strip(); assert message() == expected, (message(), expected)"
"""


def _hello_app_module() -> str:
    """Return the hello application Python module."""

    return '''"""Synthetic application for the clean-room fixture."""

from cleanroom_shared import label


def message() -> str:
    """Return a message proving the app can consume the synthetic library."""

    return f"hello-app uses {label()}"
'''


def _generated_instructions() -> str:
    """Return generated instructions that are deliberately non-authoritative."""

    return """# Generated Instructions

This file is derived from the clean-room fixture. Edit `cleanroom.yaml`,
`inventory/projects.yaml`, or `policy-pack/registry.yaml` instead.
"""


def _receipt_path(root: Path) -> Path:
    """Return the install receipt path for a clean-room root."""

    return _safe_join(root, RECEIPT_RELATIVE_PATH)


def _load_receipt(root: Path, findings: list[Finding]) -> InstallReceipt | None:
    """Load a receipt or append exact findings when it is missing or invalid."""

    receipt_path = _receipt_path(root)
    if not receipt_path.exists():
        findings.append(
            Finding(
                check_id="receipt_present",
                severity="error",
                message="install receipt is missing",
                path=RECEIPT_RELATIVE_PATH,
            )
        )
        return None
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        recorded_digest = payload.pop("receipt_sha256")
        if not isinstance(recorded_digest, str) or recorded_digest != _canonical_json_sha256(payload):
            findings.append(
                Finding(
                    check_id="receipt_integrity",
                    severity="error",
                    message="install receipt digest does not match its ownership content",
                    path=RECEIPT_RELATIVE_PATH,
                )
            )
            return None
        return InstallReceipt.from_dict(payload)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        findings.append(
            Finding(
                check_id="receipt_valid",
                severity="error",
                message=f"install receipt is invalid: {exc}",
                path=RECEIPT_RELATIVE_PATH,
            )
        )
        return None


def _validate_receipt_paths(root: Path, receipt: InstallReceipt) -> list[Finding]:
    """Return findings for receipt paths that are unsafe or missing."""

    findings: list[Finding] = []
    generated_files = set(_render_files_for_existing(root, receipt))
    generated_directories = _planned_directories(_render_files_for_existing(root, receipt))
    for relative_path in receipt.owned_files + receipt.owned_directories:
        try:
            target = _safe_join(root, relative_path)
        except CleanroomError as exc:
            findings.append(
                Finding(
                    check_id="receipt_path_escape",
                    severity="error",
                    message=str(exc),
                    path=relative_path,
                )
            )
            continue
        if relative_path in receipt.owned_files and relative_path not in generated_files:
            is_trace = relative_path.startswith(f"{TRACE_DIRECTORY_RELATIVE_PATH}/") and relative_path.endswith(".json")
            if not is_trace or verify_loop_trace(target).verdict != "pass":
                findings.append(
                    Finding(
                        check_id="receipt_foreign_path",
                        severity="error",
                        message="receipt claims a file not produced by the generator or a valid loop run",
                        path=relative_path,
                    )
                )
                continue
        if relative_path in receipt.owned_directories and relative_path not in generated_directories:
            findings.append(
                Finding(
                    check_id="receipt_foreign_path",
                    severity="error",
                    message="receipt claims a directory not produced by the generator",
                    path=relative_path,
                )
            )
            continue
        if not target.exists():
            findings.append(
                Finding(
                    check_id="receipt_path_missing",
                    severity="error",
                    message="receipt-owned path is missing",
                    path=relative_path,
                )
            )
    return findings


def _scan_tree(root: Path, projects_root: Path) -> list[Finding]:
    """Scan generated files and symlinks for isolation violations."""

    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = path.resolve(strict=False)
            if _is_relative_to(target, projects_root):
                findings.append(
                    Finding(
                        check_id="no_workspace_symlinks",
                        severity="error",
                        message="symlink points into the projects workspace",
                        path=relative_path,
                    )
                )
            continue
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if SECRET_SENTINEL in text:
            findings.append(
                Finding(
                    check_id="no_secret_sentinel",
                    severity="error",
                    message="secret sentinel found in generated content",
                    path=relative_path,
                )
            )
        for sentinel in PERSONAL_SENTINELS + (str(projects_root),):
            if sentinel and sentinel in text:
                findings.append(
                    Finding(
                        check_id="no_personal_sentinels",
                        severity="error",
                        message="personal workspace sentinel found in generated content",
                        path=relative_path,
                    )
                )
    return findings


def remove_root_if_empty(root: Path) -> None:
    """Remove a root directory when reset left it empty."""

    if root.exists() and root.is_dir() and not any(root.iterdir()):
        root.rmdir()


def remove_tree_for_test(root: Path) -> None:
    """Remove a generated test tree; this is only for test cleanup."""

    if root.exists():
        shutil.rmtree(root)
