"""Build and verify a portable clean-room loop-engineering alpha fixture.

This module owns the deterministic Slice 1 surface: plan, materialize, verify,
status, and reset for a synthetic external ecosystem. It intentionally does not
run an agent loop; `run-demo` is a deferred Slice 2 command exposed by the CLI
so automation can discover the boundary without receiving false success.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


PROJECT_IDS = ("hello-app", "shared-lib")
SECRET_SENTINEL = "SECRET_SENTINEL"
PERSONAL_SENTINELS = ("/home/brian", "BrianMills2718")
DEFAULT_INSTANCE_ID = "cleanroom-alpha"
RECEIPT_RELATIVE_PATH = ".loop-engineering/state/install_receipt.json"


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

    @classmethod
    def build(
        cls,
        *,
        root: str | Path,
        component_revision: str,
        instance_id: str = DEFAULT_INSTANCE_ID,
        projects_root: str | Path | None = None,
    ) -> "CleanroomSpec":
        """Validate user inputs and return a normalized clean-room spec."""

        revision = component_revision.strip()
        if not revision:
            raise CleanroomError("missing_component_revision", "component_revision is required")
        normalized_root = _resolve_path(root)
        normalized_projects_root = _resolve_path(projects_root or Path.home() / "projects")
        _require_outside_projects_root(normalized_root, normalized_projects_root)
        instance = instance_id.strip()
        if not instance:
            raise CleanroomError("missing_instance_id", "instance_id is required")
        return cls(
            root=normalized_root,
            component_revision=revision,
            instance_id=instance,
            projects_root=normalized_projects_root,
        )


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

    def to_dict(self) -> dict[str, Any]:
        """Return the install receipt as JSON-safe data."""

        return {
            "operation": self.operation,
            "root": self.root,
            "instance_id": self.instance_id,
            "component_revision": self.component_revision,
            "owned_files": self.owned_files,
            "owned_directories": self.owned_directories,
            "verdict": self.verdict,
        }

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
        "synthetic_inventory",
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
    if actual_projects != sorted(PROJECT_IDS):
        findings.append(
            Finding(
                check_id="synthetic_inventory",
                severity="error",
                message=f"expected only {sorted(PROJECT_IDS)}, found {actual_projects}",
                path="projects",
            )
        )

    findings.extend(_scan_tree(normalized_root, normalized_projects_root))
    return VerificationReport(operation="verify", root=str(normalized_root), checks=checks, findings=findings)


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


def run_demo_deferred(root: str | Path) -> dict[str, Any]:
    """Return an explicit Slice 2 deferral payload for the future demo loop."""

    normalized_root = _resolve_path(root)
    return {
        "operation": "run-demo",
        "root": str(normalized_root),
        "verdict": "deferred",
        "code": "deferred_slice_2",
        "message": "deterministic loop execution is intentionally deferred to Slice 2",
    }


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
        ".loop-engineering/state",
        ".loop-engineering/traces",
        ".loop-engineering/receipts",
        "generated",
        "inventory",
        "policy-pack",
        "procedures",
        "projects",
        "projects/hello-app",
        "projects/hello-app/src",
        "projects/shared-lib",
        "projects/shared-lib/src",
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
    spec = CleanroomSpec(root=root, component_revision=revision)
    return _render_files(spec)


def _render_files(spec: CleanroomSpec) -> dict[str, str]:
    """Render all deterministic files for the clean-room fixture."""

    return {
        "README.md": _root_readme(),
        "Makefile": _root_makefile(),
        "cleanroom.yaml": _cleanroom_yaml(spec),
        "component-lock.yaml": _component_lock_yaml(spec),
        "inventory/projects.yaml": _projects_inventory_yaml(),
        "policy-pack/README.md": _policy_readme(),
        "policy-pack/registry.yaml": _policy_registry_yaml(),
        "procedures/README.md": _procedures_readme(),
        "projects/shared-lib/Makefile": _shared_lib_makefile(),
        "projects/shared-lib/src/cleanroom_shared.py": _shared_lib_module(),
        "projects/hello-app/Makefile": _hello_app_makefile(),
        "projects/hello-app/src/hello_app.py": _hello_app_module(),
        "generated/instructions.md": _generated_instructions(),
    }


def _root_readme() -> str:
    """Return the root README content for generated users."""

    return """# Loop-Engineering Clean Room

This generated directory is a synthetic alpha fixture for testing portable
ecosystem governance. Replace the example inventory and policy pack with your
own project list and rules after the fixture verifies locally.

Important locations:

- `inventory/projects.yaml` lists the synthetic projects.
- `policy-pack/registry.yaml` contains example policy rules.
- `.loop-engineering/state/` stores receipts and local state.
- `generated/` contains derived outputs and is never authority.
"""


def _root_makefile() -> str:
    """Return a root Makefile with a deterministic verification command."""

    return """.PHONY: verify

verify:
\t$(MAKE) -C projects/shared-lib verify
\t$(MAKE) -C projects/hello-app verify
"""


def _cleanroom_yaml(spec: CleanroomSpec) -> str:
    """Return the user-editable clean-room configuration."""

    return f"""schema_version: 1
instance_id: {spec.instance_id}
components:
  - component_id: governance
    source_uri: local-enforced-planning
    revision: {spec.component_revision}
projects:
  - project_id: shared-lib
    relative_path: projects/shared-lib
    role: library
  - project_id: hello-app
    relative_path: projects/hello-app
    role: application
demo_loop:
  loop_id: repair-known-failure
  verifier_command: make verify
  max_iterations: 3
  max_cost_usd: 0
"""


def _component_lock_yaml(spec: CleanroomSpec) -> str:
    """Return the component lock file content."""

    return f"""schema_version: 1
components:
  - component_id: governance
    source_uri: local-enforced-planning
    revision: {spec.component_revision}
"""


def _projects_inventory_yaml() -> str:
    """Return the synthetic project inventory."""

    return """schema_version: 1
projects:
  - project_id: shared-lib
    relative_path: projects/shared-lib
    role: library
  - project_id: hello-app
    relative_path: projects/hello-app
    role: application
"""


def _policy_readme() -> str:
    """Return the policy-pack README content."""

    return """# Example Policy Pack

These rules are synthetic. They demonstrate where a user would place their own
ecosystem policy without importing private workspace policy.
"""


def _policy_registry_yaml() -> str:
    """Return a minimal synthetic policy registry."""

    return """schema_version: 1
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

Slice 1 installs only this placeholder. Versioned cross-client procedures are a
later distribution concern.
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
\tPYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:../shared-lib/src python -c "from hello_app import message; assert message() == 'hello-app uses shared-lib'"
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
