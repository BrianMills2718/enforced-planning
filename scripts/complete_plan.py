#!/usr/bin/env python3
"""Enforce plan completion requirements.

Mandatory script for marking plans as complete. Runs verification tests
and records evidence before updating plan status.

Usage:
    # Complete a plan (runs tests, records evidence, updates status)
    python scripts/complete_plan.py --plan 35

    # Dry run - check without updating
    python scripts/complete_plan.py --plan 35 --dry-run

    # Skip all E2E tests (for documentation-only plans)
    python scripts/complete_plan.py --plan 35 --skip-e2e

    # Skip only real E2E tests (actual LLM calls) but run smoke tests
    python scripts/complete_plan.py --plan 35 --skip-real-e2e

    # Re-verify an already-complete plan
    python scripts/complete_plan.py --plan 35 --force

    # Complete a plan that requires human review
    # (after manual verification of checklist items)
    python scripts/complete_plan.py --plan 40 --human-verified

    # Require a fully green repository for a release/promotion claim
    python scripts/complete_plan.py --plan 40 --require-repository-green

Plans with a "## Human Review Required" section cannot be completed
without the --human-verified flag. This ensures humans verify things
that automated tests cannot check (visual correctness, UX, etc.).

See meta/patterns/17_verification-enforcement.md for the full pattern.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path


def _ensure_local_package_importable() -> None:
    """Add the nearest governed-repo root for direct installed-script execution."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "enforced_planning").is_dir():
            parent_text = str(parent)
            if parent_text not in sys.path:
                sys.path.insert(0, parent_text)
            return


_ensure_local_package_importable()

from enforced_planning import active_work_registry, coordination_claims  # noqa: E402
from enforced_planning.worktree_paths import resolve_canonical_repo_root  # noqa: E402

# Plan #136: Timeout for test subprocess calls to prevent hanging forever
TEST_TIMEOUT_SECONDS = 300  # 5 minutes


@dataclass(frozen=True)
class TestFailure:
    """One stable failing-test identity from a machine-readable pytest run."""

    identity: str
    file: str | None
    outcome: str
    detail_hash: str
    detail_excerpt: str


@dataclass(frozen=True)
class TestRunResult:
    """Structured evidence from one repository-wide non-E2E pytest run."""

    available: bool
    commit: str
    command: tuple[str, ...]
    returncode: int | None
    summary: str
    test_count: int
    passed_count: int
    skipped_count: int
    failures: tuple[TestFailure, ...]
    error: str | None

    @property
    def failure_count(self) -> int:
        """Return the number of failing or erroring test identities."""
        return len(self.failures)


@dataclass(frozen=True)
class RepositoryHealthComparison:
    """Current-versus-merge-base repository health and completion policy."""

    status: str
    allowed: bool
    reason: str
    baseline_ref: str
    baseline_commit: str | None
    current: TestRunResult
    baseline: TestRunResult | None
    changed_paths: tuple[str, ...]
    new_failures: tuple[str, ...]
    changed_baseline_failures: tuple[str, ...]


def _pytest_command() -> list[str]:
    """Return the interpreter-qualified pytest command for this environment."""
    return [sys.executable, "-m", "pytest"]


def find_plan_file(plan_number: int, plans_dir: Path) -> Path | None:
    """Find a plan file by number."""
    patterns = [
        f"{plan_number:02d}_*.md",
        f"{plan_number}_*.md",
    ]
    for pattern in patterns:
        matches = list(plans_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def get_plan_status(plan_file: Path) -> str:
    """Extract current status from plan file."""
    content = plan_file.read_text()
    match = re.search(r"\*\*Status:\*\*\s*(.+)", content)
    return match.group(1).strip() if match else "Unknown"


def get_human_review_section(plan_file: Path) -> str | None:
    """Extract the Human Review Required section from plan file.

    Returns the section content if present, None otherwise.
    """
    content = plan_file.read_text()

    # Look for ## Human Review Required section
    match = re.search(
        r"##\s*Human Review Required\s*\n(.*?)(?=\n##|\Z)",
        content,
        re.DOTALL | re.IGNORECASE
    )

    if match:
        return match.group(1).strip()
    return None


def print_human_review_instructions(
    plan_number: int,
    section_content: str,
    plan_file: Path,
) -> None:
    """Print human review instructions and checklist."""
    print(f"\n{'='*60}")
    print("HUMAN REVIEW REQUIRED")
    print(f"{'='*60}")
    print(f"\nPlan #{plan_number} requires manual verification before completion.")
    print(f"\nFrom {plan_file.name}:")
    print(f"\n{'-'*40}")
    print(section_content)
    print(f"{'-'*40}")
    print("\nAfter verifying all items above, run:")
    print(f"\n  python scripts/complete_plan.py --plan {plan_number} --human-verified")
    print("\nThis confirms a human has checked things automated tests cannot verify.")


def run_required_plan_tests(
    project_root: Path,
    plan_number: int,
    verbose: bool = True,
) -> tuple[bool, str]:
    """Run the plan-declared required-test manifest as the blocking change gate."""
    if verbose:
        print("\n[1/5] Running plan-required tests...")

    companion = Path(__file__).resolve().with_name("check_plan_tests.py")
    if not companion.exists():
        message = f"required-test runner unavailable: {companion}"
        if verbose:
            print(f"    FAILED: {message}")
        return False, message

    try:
        result = subprocess.run(
            [sys.executable, str(companion), "--plan", str(plan_number)],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        message = f"timeout after {TEST_TIMEOUT_SECONDS}s"
        if verbose:
            print(f"    FAILED: {message}")
        return False, message

    output = (result.stdout + result.stderr).strip()
    summary = _last_nonempty_line(output) or "unknown result"
    passed = result.returncode == 0
    if verbose:
        print(f"    {'PASSED' if passed else 'FAILED'}: {summary}")
        if not passed and output:
            print(output[-2000:])
    return passed, summary


def _last_nonempty_line(output: str) -> str | None:
    """Return the last non-empty output line for a compact evidence summary."""
    for line in reversed(output.splitlines()):
        if line.strip():
            return line.strip()
    return None


def _normalize_test_file(raw_file: str | None, project_root: Path) -> str | None:
    """Normalize a JUnit file attribute to a repository-relative POSIX path."""
    if not raw_file:
        return None
    candidate = Path(raw_file)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(project_root.resolve())
        except ValueError:
            parts = candidate.parts
            if "tests" in parts:
                candidate = Path(*parts[parts.index("tests"):])
            else:
                return candidate.name
    normalized = candidate.as_posix()
    return normalized[2:] if normalized.startswith("./") else normalized


def _file_from_classname(classname: str) -> str | None:
    """Best-effort repository test path when JUnit omits its file attribute."""
    if not classname:
        return None
    module = classname.split("::", 1)[0]
    parts = module.split(".")
    if not parts or parts[0] != "tests":
        return None
    while parts and parts[-1].startswith("Test"):
        parts.pop()
    if not parts:
        return None
    return "/".join(parts) + ".py"


def _parse_count(value: str | None) -> int:
    """Parse one non-negative JUnit count without allowing malformed evidence."""
    if value is None:
        return 0
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"negative JUnit count: {value}")
    return parsed


def _normalized_failure_detail(
    outcome_node: ET.Element,
    *,
    project_root: Path,
) -> tuple[str, str]:
    """Return a path-neutral failure hash plus a bounded diagnostic excerpt."""
    failure_type = outcome_node.get("type", "")
    message = outcome_node.get("message", "")
    traceback = outcome_node.text or ""
    detail = "\n".join((failure_type, message, traceback))
    root_variants = {
        str(project_root),
        str(project_root.resolve()),
    }
    for root_variant in sorted(root_variants, key=len, reverse=True):
        detail = detail.replace(root_variant, "<worktree>")
    detail = detail.replace("\\", "/")
    detail_hash = hashlib.sha256(detail.encode("utf-8", errors="replace")).hexdigest()
    excerpt = " ".join(detail.split())[:500]
    return detail_hash, excerpt


def parse_pytest_junit(
    report_path: Path,
    *,
    project_root: Path,
    commit: str,
    command: tuple[str, ...],
    returncode: int,
    output: str,
) -> TestRunResult:
    """Parse pytest JUnit XML into stable identities or explicit unavailability."""
    if returncode not in {0, 1}:
        return TestRunResult(
            available=False,
            commit=commit,
            command=command,
            returncode=returncode,
            summary=_last_nonempty_line(output) or "pytest did not complete",
            test_count=0,
            passed_count=0,
            skipped_count=0,
            failures=(),
            error=f"pytest exited {returncode}; comparable test evidence unavailable",
        )
    if not report_path.exists():
        return TestRunResult(
            available=False,
            commit=commit,
            command=command,
            returncode=returncode,
            summary=_last_nonempty_line(output) or "missing JUnit report",
            test_count=0,
            passed_count=0,
            skipped_count=0,
            failures=(),
            error="pytest did not produce the required JUnit report",
        )

    try:
        root = ET.parse(report_path).getroot()
        suites = list(root.iter("testsuite"))
        if not suites:
            raise ValueError("JUnit report contains no testsuite")
        test_count = max(_parse_count(suite.get("tests")) for suite in suites)
        skipped_count = max(_parse_count(suite.get("skipped")) for suite in suites)
        failures: list[TestFailure] = []
        for testcase in root.iter("testcase"):
            outcome_node = testcase.find("failure")
            outcome = "failure"
            if outcome_node is None:
                outcome_node = testcase.find("error")
                outcome = "error"
            if outcome_node is None:
                continue
            classname = testcase.get("classname", "")
            name = testcase.get("name", "<unnamed>")
            file_path = _normalize_test_file(
                testcase.get("file") or _file_from_classname(classname),
                project_root,
            )
            identity_parts = [file_path or classname or "<unknown-test>"]
            if classname and classname not in identity_parts:
                identity_parts.append(classname)
            identity_parts.extend([name, outcome])
            detail_hash, detail_excerpt = _normalized_failure_detail(
                outcome_node,
                project_root=project_root,
            )
            failures.append(
                TestFailure(
                    identity="::".join(identity_parts),
                    file=file_path,
                    outcome=outcome,
                    detail_hash=detail_hash,
                    detail_excerpt=detail_excerpt,
                )
            )
        failures.sort(key=lambda failure: failure.identity)
        if returncode == 1 and not failures:
            raise ValueError("pytest failed but JUnit contains no failure identity")
        passed_count = max(test_count - skipped_count - len(failures), 0)
    except (ET.ParseError, OSError, ValueError) as exc:
        return TestRunResult(
            available=False,
            commit=commit,
            command=command,
            returncode=returncode,
            summary=_last_nonempty_line(output) or "invalid JUnit report",
            test_count=0,
            passed_count=0,
            skipped_count=0,
            failures=(),
            error=f"invalid JUnit evidence: {exc}",
        )

    summary = f"{passed_count} passed, {skipped_count} skipped, {len(failures)} failed"
    return TestRunResult(
        available=True,
        commit=commit,
        command=command,
        returncode=returncode,
        summary=summary,
        test_count=test_count,
        passed_count=passed_count,
        skipped_count=skipped_count,
        failures=tuple(failures),
        error=None,
    )


def _mapped_execution_environment(source_root: Path, execution_root: Path) -> dict[str, str]:
    """Map PYTHONPATH entries inside the current checkout to the baseline checkout."""
    environment = os.environ.copy()
    raw_pythonpath = environment.get("PYTHONPATH")
    if not raw_pythonpath:
        return environment

    source_resolved = source_root.resolve()
    mapped: list[str] = []
    for entry in raw_pythonpath.split(os.pathsep):
        if not entry:
            continue
        entry_path = Path(entry).expanduser()
        try:
            relative = entry_path.resolve().relative_to(source_resolved)
        except (OSError, ValueError):
            mapped.append(entry)
        else:
            mapped.append(str(execution_root / relative))
    environment["PYTHONPATH"] = os.pathsep.join(mapped)
    return environment


def _commit_at(project_root: Path) -> str:
    """Return the exact checked-out commit or an explicit unknown marker."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def run_repository_test_suite(
    project_root: Path,
    *,
    commit: str | None = None,
    environment_source_root: Path | None = None,
    verbose: bool = True,
) -> TestRunResult:
    """Run the non-E2E repository suite and return comparable JUnit evidence."""
    if verbose:
        print(f"    Running repository suite in {project_root}")
    commit = commit or _commit_at(project_root)
    with tempfile.TemporaryDirectory(prefix="complete-plan-junit-") as temp_dir:
        report_path = Path(temp_dir) / "pytest.xml"
        command = (
            *_pytest_command(),
            "tests/",
            "--ignore=tests/e2e/",
            "-v",
            "--tb=short",
            f"--junitxml={report_path}",
        )
        recorded_command = tuple(
            "--junitxml=<temporary-report>" if part.startswith("--junitxml=") else part
            for part in command
        )
        environment = (
            _mapped_execution_environment(environment_source_root, project_root)
            if environment_source_root is not None
            else os.environ.copy()
        )
        try:
            result = subprocess.run(
                command,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT_SECONDS,
                env=environment,
            )
        except subprocess.TimeoutExpired:
            return TestRunResult(
                available=False,
                commit=commit,
                command=recorded_command,
                returncode=None,
                summary=f"timeout after {TEST_TIMEOUT_SECONDS}s",
                test_count=0,
                passed_count=0,
                skipped_count=0,
                failures=(),
                error=f"repository suite timed out after {TEST_TIMEOUT_SECONDS}s",
            )
        output = result.stdout + result.stderr
        parsed = parse_pytest_junit(
            report_path,
            project_root=project_root,
            commit=commit,
            command=recorded_command,
            returncode=result.returncode,
            output=output,
        )
        if verbose:
            print(f"    Repository suite: {parsed.summary}")
            if not parsed.available and parsed.error:
                print(f"    UNAVAILABLE: {parsed.error}")
        return parsed


def _resolve_baseline_commit(project_root: Path, baseline_ref: str) -> tuple[str | None, str | None]:
    """Resolve the merge base used as the same-environment comparison control."""
    result = subprocess.run(
        ["git", "merge-base", "HEAD", baseline_ref],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        detail = (result.stderr or result.stdout).strip()
        return None, f"unable to resolve merge base with {baseline_ref}: {detail}"
    return result.stdout.strip(), None


def _select_baseline_ref(
    project_root: Path,
    requested_ref: str | None,
) -> tuple[str | None, str | None]:
    """Select a portable default-branch ref without guessing past known candidates."""
    if requested_ref:
        return requested_ref, None

    symbolic = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    candidates: list[str] = []
    if symbolic.returncode == 0 and symbolic.stdout.strip():
        candidates.append(symbolic.stdout.strip())
    candidates.extend(["origin/main", "origin/master", "main", "master"])

    for candidate in dict.fromkeys(candidates):
        exists = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if exists.returncode == 0:
            return candidate, None
    return None, (
        "unable to auto-detect a baseline ref; pass --baseline-ref with the "
        "repository's default branch"
    )


def _changed_paths(project_root: Path, baseline_commit: str) -> tuple[tuple[str, ...], str | None]:
    """Return tracked and untracked paths changed from the comparison commit."""
    diff = subprocess.run(
        ["git", "diff", "--name-only", "-z", baseline_commit, "--"],
        cwd=project_root,
        capture_output=True,
        check=False,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=project_root,
        capture_output=True,
        check=False,
    )
    if diff.returncode != 0 or untracked.returncode != 0:
        detail = (diff.stderr or untracked.stderr).decode(errors="replace").strip()
        return (), f"unable to enumerate changed paths: {detail}"
    paths = {
        raw.decode(errors="surrogateescape")
        for raw in (diff.stdout + untracked.stdout).split(b"\0")
        if raw
    }
    return tuple(sorted(paths)), None


def _baseline_worktree_path(project_root: Path) -> Path:
    """Return a unique sibling worktree path under the canonical repository root."""
    canonical_root = resolve_canonical_repo_root(project_root)
    return canonical_root / "worktrees" / f".completion-baseline-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _run_baseline_suite(
    project_root: Path,
    baseline_commit: str,
    *,
    verbose: bool,
) -> TestRunResult:
    """Run the repository suite at the merge base in a disposable sibling worktree."""
    canonical_root = resolve_canonical_repo_root(project_root)
    baseline_path = _baseline_worktree_path(project_root)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    add = subprocess.run(
        ["git", "worktree", "add", "--detach", str(baseline_path), baseline_commit],
        cwd=canonical_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if add.returncode != 0:
        return TestRunResult(
            available=False,
            commit=baseline_commit,
            command=tuple(_pytest_command()),
            returncode=None,
            summary="baseline worktree unavailable",
            test_count=0,
            passed_count=0,
            skipped_count=0,
            failures=(),
            error=f"unable to create baseline worktree: {(add.stderr or add.stdout).strip()}",
        )

    baseline_result: TestRunResult
    try:
        baseline_result = run_repository_test_suite(
            baseline_path,
            commit=baseline_commit,
            environment_source_root=project_root,
            verbose=verbose,
        )
    finally:
        remove = subprocess.run(
            ["git", "worktree", "remove", "--force", str(baseline_path)],
            cwd=canonical_root,
            capture_output=True,
            text=True,
            check=False,
        )
    if remove.returncode != 0:
        return replace(
            baseline_result,
            available=False,
            error=(
                "baseline worktree cleanup failed; recover manually at "
                f"{baseline_path}: {(remove.stderr or remove.stdout).strip()}"
            ),
        )
    return baseline_result


def compare_repository_health(
    project_root: Path,
    *,
    baseline_ref: str | None = None,
    verbose: bool = True,
) -> RepositoryHealthComparison:
    """Compare current non-E2E failures with a same-layout merge-base run."""
    if verbose:
        print("\n[2/5] Recording repository health...")
    current = run_repository_test_suite(project_root, verbose=verbose)
    if not current.available:
        return RepositoryHealthComparison(
            status="unavailable",
            allowed=False,
            reason=current.error or "current repository evidence unavailable",
            baseline_ref=baseline_ref or "<auto>",
            baseline_commit=None,
            current=current,
            baseline=None,
            changed_paths=(),
            new_failures=(),
            changed_baseline_failures=(),
        )
    if current.returncode == 0:
        return RepositoryHealthComparison(
            status="green",
            allowed=True,
            reason="repository-wide non-E2E suite passed",
            baseline_ref=baseline_ref or "<auto>",
            baseline_commit=None,
            current=current,
            baseline=None,
            changed_paths=(),
            new_failures=(),
            changed_baseline_failures=(),
        )

    resolved_baseline_ref, ref_error = _select_baseline_ref(project_root, baseline_ref)
    if resolved_baseline_ref is None:
        return RepositoryHealthComparison(
            status="unavailable",
            allowed=False,
            reason=ref_error or "unable to select a baseline ref",
            baseline_ref=baseline_ref or "<auto>",
            baseline_commit=None,
            current=current,
            baseline=None,
            changed_paths=(),
            new_failures=(),
            changed_baseline_failures=(),
        )

    baseline_commit, baseline_error = _resolve_baseline_commit(
        project_root,
        resolved_baseline_ref,
    )
    if baseline_commit is None:
        return RepositoryHealthComparison(
            status="unavailable",
            allowed=False,
            reason=baseline_error or "unable to resolve merge base",
            baseline_ref=resolved_baseline_ref,
            baseline_commit=None,
            current=current,
            baseline=None,
            changed_paths=(),
            new_failures=(),
            changed_baseline_failures=(),
        )
    changed_paths, changed_error = _changed_paths(project_root, baseline_commit)
    if changed_error:
        return RepositoryHealthComparison(
            status="unavailable",
            allowed=False,
            reason=changed_error,
            baseline_ref=resolved_baseline_ref,
            baseline_commit=baseline_commit,
            current=current,
            baseline=None,
            changed_paths=(),
            new_failures=(),
            changed_baseline_failures=(),
        )

    baseline = _run_baseline_suite(
        project_root,
        baseline_commit,
        verbose=verbose,
    )
    if not baseline.available:
        return RepositoryHealthComparison(
            status="unavailable",
            allowed=False,
            reason=baseline.error or "baseline repository evidence unavailable",
            baseline_ref=resolved_baseline_ref,
            baseline_commit=baseline_commit,
            current=current,
            baseline=baseline,
            changed_paths=changed_paths,
            new_failures=(),
            changed_baseline_failures=(),
        )

    baseline_by_identity = {failure.identity: failure for failure in baseline.failures}
    current_by_identity = {failure.identity: failure for failure in current.failures}
    new_failures = tuple(sorted(set(current_by_identity) - set(baseline_by_identity)))
    changed_path_set = set(changed_paths)
    changed_baseline: list[str] = []
    for identity in sorted(set(current_by_identity) & set(baseline_by_identity)):
        current_failure = current_by_identity[identity]
        baseline_failure = baseline_by_identity[identity]
        current_file = current_failure.file
        baseline_file = baseline_failure.file
        if (
            current_failure.detail_hash != baseline_failure.detail_hash
            or
            (current_file is not None and current_file in changed_path_set)
            or (baseline_file is not None and baseline_file in changed_path_set)
            or (current_file is None and baseline_file is None and changed_paths)
        ):
            changed_baseline.append(identity)

    changed_baseline_failures = tuple(changed_baseline)
    if new_failures or changed_baseline_failures:
        reason_parts: list[str] = []
        if new_failures:
            reason_parts.append(f"{len(new_failures)} new failure(s)")
        if changed_baseline_failures:
            reason_parts.append(
                f"{len(changed_baseline_failures)} baseline failure(s) changed evidence "
                "or overlap changed test files"
            )
        return RepositoryHealthComparison(
            status="regressed",
            allowed=False,
            reason="; ".join(reason_parts),
            baseline_ref=resolved_baseline_ref,
            baseline_commit=baseline_commit,
            current=current,
            baseline=baseline,
            changed_paths=changed_paths,
            new_failures=new_failures,
            changed_baseline_failures=changed_baseline_failures,
        )

    return RepositoryHealthComparison(
        status="baseline_degraded",
        allowed=True,
        reason=(
            f"{current.failure_count} current failure(s) reproduce at the same-layout merge base; "
            "no new or changed-test failure"
        ),
        baseline_ref=resolved_baseline_ref,
        baseline_commit=baseline_commit,
        current=current,
        baseline=baseline,
        changed_paths=changed_paths,
        new_failures=(),
        changed_baseline_failures=(),
    )


def write_repository_health_evidence(
    project_root: Path,
    plan_number: int,
    comparison: RepositoryHealthComparison,
    *,
    dry_run: bool,
) -> Path:
    """Persist the complete comparison separately from the compact plan summary."""
    relative_path = Path("docs") / "evidence" / f"plan{plan_number}_repository_health.json"
    if dry_run:
        return relative_path
    target = project_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(comparison)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return relative_path


def run_unit_tests(project_root: Path, verbose: bool = True) -> tuple[bool, str]:
    """Run unit/component tests (excluding E2E).

    Returns (success, summary).
    """
    if verbose:
        print("\n[1/4] Running unit tests...")

    try:
        result = subprocess.run(
            [
                *_pytest_command(),
                "tests/",
                "--ignore=tests/e2e/",
                "-v",
                "--tb=short",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"    TIMEOUT: Tests did not complete within {TEST_TIMEOUT_SECONDS}s")
        return False, f"timeout after {TEST_TIMEOUT_SECONDS}s"

    # Extract summary from output
    output = result.stdout + result.stderr
    summary_match = re.search(r"=+ (.+ passed.*) =+", output)
    summary = summary_match.group(1) if summary_match else "unknown result"

    if verbose:
        if result.returncode == 0:
            print(f"    PASSED: {summary}")
        else:
            print(f"    FAILED: {summary}")
            print(output[-2000:])  # Last 2000 chars of output

    return result.returncode == 0, summary


def run_e2e_tests(project_root: Path, verbose: bool = True) -> tuple[bool, str]:
    """Run E2E smoke tests.

    Returns (success, summary).
    """
    e2e_dir = project_root / "tests" / "e2e"
    smoke_test = e2e_dir / "test_smoke.py"

    if not e2e_dir.exists():
        if verbose:
            print("\n[3/5] E2E smoke tests... SKIPPED (tests/e2e/ not found)")
        return True, "skipped (no e2e directory)"

    if not smoke_test.exists():
        if verbose:
            print("\n[3/5] E2E smoke tests... SKIPPED (test_smoke.py not found)")
        return True, "skipped (no smoke test)"

    if verbose:
        print("\n[3/5] Running E2E smoke tests...")

    try:
        result = subprocess.run(
            [*_pytest_command(), "tests/e2e/test_smoke.py", "-v", "--tb=short"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"    TIMEOUT: Tests did not complete within {TEST_TIMEOUT_SECONDS}s")
        return False, f"timeout after {TEST_TIMEOUT_SECONDS}s"

    output = result.stdout + result.stderr

    # Extract timing
    time_match = re.search(r"in (\d+\.\d+)s", output)
    timing = time_match.group(1) if time_match else "?"

    if result.returncode == 0:
        summary = f"PASSED ({timing}s)"
    else:
        summary = f"FAILED ({timing}s)"

    if verbose:
        if result.returncode == 0:
            print(f"    PASSED ({timing}s)")
        else:
            print("    FAILED")
            print(output[-2000:])

    return result.returncode == 0, summary


def run_real_e2e_tests(project_root: Path, verbose: bool = True) -> tuple[bool, str]:
    """Run real E2E tests (actual LLM calls).

    Returns (success, summary).
    """
    e2e_dir = project_root / "tests" / "e2e"
    real_e2e = e2e_dir / "test_real_e2e.py"

    if not e2e_dir.exists():
        if verbose:
            print("\n[4/5] Real E2E tests... SKIPPED (tests/e2e/ not found)")
        return True, "skipped (no e2e directory)"

    if not real_e2e.exists():
        if verbose:
            print("\n[4/5] Real E2E tests... SKIPPED (test_real_e2e.py not found)")
        return True, "skipped (no real e2e test)"

    if verbose:
        print("\n[4/5] Running real E2E tests (actual LLM calls)...")

    try:
        result = subprocess.run(
            [
                *_pytest_command(),
                "tests/e2e/test_real_e2e.py",
                "-v",
                "--tb=short",
                "--run-external",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print(f"    TIMEOUT: Tests did not complete within {TEST_TIMEOUT_SECONDS}s")
        return False, f"timeout after {TEST_TIMEOUT_SECONDS}s"

    output = result.stdout + result.stderr

    # Extract timing
    time_match = re.search(r"in (\d+\.\d+)s", output)
    timing = time_match.group(1) if time_match else "?"

    if result.returncode == 0:
        summary = f"PASSED ({timing}s)"
    else:
        summary = f"FAILED ({timing}s)"

    if verbose:
        if result.returncode == 0:
            print(f"    PASSED ({timing}s)")
        else:
            print("    FAILED")
            print(output[-2000:])

    return result.returncode == 0, summary


def check_doc_coupling(project_root: Path, verbose: bool = True) -> tuple[bool, str]:
    """Check doc-code coupling.

    Returns (success, summary).
    """
    if verbose:
        print("\n[5/5] Checking doc-code coupling...")

    try:
        result = subprocess.run(
            [sys.executable, "scripts/check_doc_coupling.py", "--strict"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,  # Doc coupling check should be quick
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print("    TIMEOUT: Doc coupling check did not complete within 60s")
        return False, "timeout after 60s"

    violations_reported = "VIOLATIONS" in result.stdout or "VIOLATIONS" in result.stderr
    if result.returncode != 0 or violations_reported:
        if verbose:
            print(f"    FAILED: Doc-coupling check exited {result.returncode}")
            print((result.stdout + result.stderr)[-1000:])
        reason = "violations found" if violations_reported else f"exit {result.returncode}"
        return False, f"failed ({reason})"

    if verbose:
        print("    PASSED")

    return True, "passed"


def _check_trace_evaluable_advisory(plan_file: Path, verbose: bool = True) -> str | None:
    """Advisory check: warn if plan declares trace_evaluable:true without evidence.

    Returns a warning string if the plan should have trace_eval evidence but
    doesn't yet.  Returns None when the plan is compliant or exempt.

    This check is ADVISORY — it never prevents plan completion.
    Promotion to a hard block is tracked in the evidence ledger (Plan #132).
    """
    import re

    content = plan_file.read_text()

    if verbose:
        print("\n[5/4+] Trace evaluable advisory check...")

    # Find the declaration
    value: str | None = None
    for line in content.split("\n"):
        m = re.match(r"`?trace_evaluable:\s*(true|false)\s*(?:#.*)?`?", line.strip())
        if m:
            value = m.group(1)
            break

    if value is None:
        # Not declared — advisory skip
        return None

    if value == "false":
        # Explicitly opted out — no warning
        return None

    # Declared true — check for evidence link
    if "evidence_link:" not in content:
        warning = "plan declares trace_evaluable:true but has no evidence_link field"
        if verbose:
            print(f"  ⚠ ADVISORY: {warning}")
            print("    Add evidence_link: <path_to_trace_result.json> before closing")
            print("    (This is advisory — see docs/ops/trace_evaluable_evidence_ledger.md)")
        return warning

    # Has the field — check if it's still blank
    m = re.search(r"evidence_link:\s*(.+)", content)
    if m and m.group(1).strip() in {"", '""', "''"}:
        warning = "plan declares trace_evaluable:true but evidence_link is still empty"
        if verbose:
            print(f"  ⚠ ADVISORY: {warning}")
            print("    Populate evidence_link: with the path to trace_result.json")
        return warning

    if verbose:
        print("  ✓ trace_evaluable evidence link present")
    return None


def get_git_info(project_root: Path) -> tuple[str, str]:
    """Get current git commit and branch.

    Returns (commit_hash, branch_name).
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
        ).stdout.strip()

        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
        ).stdout.strip()

        return commit, branch
    except Exception:
        return "unknown", "unknown"


def update_plan_file(
    plan_file: Path,
    unit_summary: str,
    e2e_smoke_summary: str,
    e2e_real_summary: str,
    doc_summary: str,
    commit: str,
    dry_run: bool = False,
    *,
    required_summary: str = "not recorded (legacy completion)",
    repository_health_status: str = "green",
    repository_health_evidence: str | None = None,
    status_label: str = "✅ Complete",
) -> bool:
    """Update plan file with verification evidence and complete status.

    Returns True if updated successfully.
    """
    content = plan_file.read_text()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build verification evidence block
    evidence = f"""
**Verified:** {timestamp}
**Verification Evidence:**
```yaml
completed_by: scripts/complete_plan.py
timestamp: {timestamp}
completion_scope: {'scoped' if repository_health_status == 'baseline_degraded' else 'repository_green'}
tests:
  required: {required_summary}
  repository_non_e2e: {unit_summary}
  e2e_smoke: {e2e_smoke_summary}
  e2e_real: {e2e_real_summary}
  doc_coupling: {doc_summary}
repository_health:
  status: {repository_health_status}
  evidence: {repository_health_evidence or 'null'}
commit: {commit}
```
"""

    # Update status line
    new_content = re.sub(
        r"\*\*Status:\*\*\s*.+",
        f"**Status:** {status_label}",
        content
    )

    # Check if already has verification section
    if "**Verified:**" in new_content:
        # Update existing verification
        new_content = re.sub(
            r"\*\*Verified:\*\*.*?```\n",
            evidence.strip() + "\n",
            new_content,
            flags=re.DOTALL
        )
    else:
        # Add verification after status line
        new_content = re.sub(
            r"(\*\*Status:\*\*\s*.+\n)",
            f"\\1{evidence}",
            new_content
        )

    if dry_run:
        print(f"\n[DRY RUN] Would update {plan_file.name}:")
        print(f"  Status: {status_label}")
        print(f"  Verified: {timestamp}")
        print(f"  Commit: {commit}")
        return True

    plan_file.write_text(new_content)
    return True


def update_plan_index(
    plan_number: int,
    plans_dir: Path,
    dry_run: bool = False,
    *,
    status_label: str = "✅ Complete",
) -> bool:
    """Update plan status in CLAUDE.md index.

    Returns True if updated successfully.
    """
    index_file = plans_dir / "CLAUDE.md"
    if not index_file.exists():
        return False

    content = index_file.read_text()
    lines = content.splitlines(keepends=True)
    updated = False

    for index, line in enumerate(lines):
        updated_line = _update_plan_index_row(line, plan_number, status_label=status_label)
        if updated_line is None:
            continue
        lines[index] = updated_line
        updated = True
        break

    if not updated:
        print(f"  WARNING: Could not find plan #{plan_number} in index")
        return False

    new_content = "".join(lines)

    if dry_run:
        print("[DRY RUN] Would update plans/CLAUDE.md index")
        return True

    index_file.write_text(new_content)
    return True


def _update_plan_index_row(
    line: str,
    plan_number: int,
    *,
    status_label: str = "✅ Complete",
) -> str | None:
    """Update only the status cell for the targeted markdown-table plan row.

    Returns the rewritten line when this is the matching plan row, otherwise
    ``None``. Non-status cells are preserved byte-for-byte.
    """
    if not line.lstrip().startswith("|"):
        return None

    parts = line.split("|")
    if len(parts) < 6:
        return None

    cells = parts[1:-1]
    if len(cells) < 5:
        return None

    if cells[0].strip() != str(plan_number):
        return None

    status_index = 4  # parts[0] is the leading empty prefix before the first pipe
    parts[status_index] = _rewrite_status_cell(parts[status_index], status_label)
    return "|".join(parts)


def _rewrite_status_cell(cell: str, new_status: str) -> str:
    """Rewrite a markdown-table status cell while preserving surrounding whitespace."""
    prefix_match = re.match(r"^\s*", cell)
    suffix_match = re.search(r"\s*$", cell)
    prefix = prefix_match.group(0) if prefix_match else " "
    suffix = suffix_match.group(0) if suffix_match else " "
    if not prefix:
        prefix = " "
    if not suffix:
        suffix = " "
    return f"{prefix}{new_status}{suffix}"


def sync_coordination_closeout(
    *,
    plan_number: int,
    project_root: Path,
    dry_run: bool = False,
    verbose: bool = True,
) -> tuple[int, list[str], dict[str, object] | None]:
    """Close matching live claims and refresh derived active-work outputs."""

    canonical_repo_root = resolve_canonical_repo_root(project_root)
    project_name = canonical_repo_root.name
    plan_ref = f"Plan #{plan_number}"
    note = f"closed automatically by scripts/complete_plan.py for {plan_ref}"

    if dry_run:
        live_claims = coordination_claims.check_claims(project_name)
        matching = [
            claim.scope
            for claim in live_claims
            if claim.plan_ref == plan_ref
        ]
        if verbose:
            print(
                f"\n[closeout] Coordination closeout... DRY RUN "
                f"({len(matching)} matching live claims, registry refresh skipped)"
            )
        return len(matching), sorted(matching), None

    completed_count, completed_scopes = coordination_claims.complete_claims_for_plan(
        project=project_name,
        plan_ref=plan_ref,
        note=note,
    )
    payload = active_work_registry.refresh_registry(
        json_output=canonical_repo_root / "generated" / "runtime" / "active_work_registry.json",
        markdown_output=canonical_repo_root / "generated" / "runtime" / "active_work_registry.md",
    )
    if verbose:
        print(
            f"\n[closeout] Coordination closeout... "
            f"{completed_count} claims closed, {payload['claim_count']} live claims remain"
        )
    return completed_count, completed_scopes, payload


def complete_plan(
    plan_number: int,
    project_root: Path,
    dry_run: bool = False,
    skip_e2e: bool = False,
    skip_real_e2e: bool = False,
    force: bool = False,
    human_verified: bool = False,
    baseline_ref: str | None = None,
    require_repository_green: bool = False,
    verbose: bool = True,
) -> bool:
    """Complete a plan with full verification.

    Returns True if plan was completed successfully.
    """
    plans_dir = project_root / "docs" / "plans"
    plan_file = find_plan_file(plan_number, plans_dir)

    if not plan_file:
        print(f"Error: Plan #{plan_number} not found in {plans_dir}")
        return False

    current_status = get_plan_status(plan_file)

    if verbose:
        print(f"\n{'='*60}")
        print(f"Completing Plan #{plan_number}")
        print(f"{'='*60}")
        print(f"File: {plan_file.name}")
        print(f"Current Status: {current_status}")

    if ("\u2705" in current_status or "Complete" in current_status) and not force:
        print(f"\nPlan #{plan_number} is already marked complete.")
        print("Use --force to re-verify and update evidence.")
        return True

    if force and verbose:
        print("  (--force: re-verifying already-complete plan)")

    # Check for human review requirements
    human_review_section = get_human_review_section(plan_file)
    if human_review_section and not human_verified:
        # Human review required but not confirmed
        print_human_review_instructions(plan_number, human_review_section, plan_file)
        print("\n❌ Cannot complete: human review required but --human-verified not provided")
        return False

    if human_review_section and human_verified and verbose:
        print("  (--human-verified: human review confirmed)")

    # 1. The plan-declared change gate is always blocking and runs first.
    required_passed, required_summary = run_required_plan_tests(
        project_root,
        plan_number,
        verbose,
    )
    if not required_passed:
        print(f"\nFAILED: Plan #{plan_number} cannot be marked complete.")
        print("Fix the missing or failing plan-required tests and try again.")
        return False

    # 2. Repository health is always visible. Pre-existing failures are allowed
    # only when the identical suite reproduces them at the same-layout merge base.
    repository_health = compare_repository_health(
        project_root,
        baseline_ref=baseline_ref,
        verbose=verbose,
    )
    repository_passed = repository_health.allowed
    if require_repository_green and repository_health.status != "green":
        repository_passed = False

    all_passed = repository_passed
    unit_summary = repository_health.current.summary

    # 2. E2E smoke tests
    if skip_e2e:
        e2e_smoke_passed, e2e_smoke_summary = True, "skipped (--skip-e2e)"
        if verbose:
            print("\n[3/5] E2E smoke tests... SKIPPED (--skip-e2e flag)")
    else:
        e2e_smoke_passed, e2e_smoke_summary = run_e2e_tests(project_root, verbose)
        if not e2e_smoke_passed:
            all_passed = False

    # 3. Real E2E tests (actual LLM calls)
    if skip_e2e or skip_real_e2e:
        e2e_real_passed, e2e_real_summary = True, "skipped (--skip-real-e2e)"
        if verbose:
            print("\n[4/5] Real E2E tests... SKIPPED (--skip-real-e2e flag)")
    else:
        e2e_real_passed, e2e_real_summary = run_real_e2e_tests(project_root, verbose)
        if not e2e_real_passed:
            all_passed = False

    # 4. Doc coupling
    doc_passed, doc_summary = check_doc_coupling(project_root, verbose)
    if not doc_passed:
        all_passed = False

    # 5. Trace-evaluable advisory check (advisory — never blocks; Plan #132 policy)
    trace_warning = _check_trace_evaluable_advisory(plan_file, verbose)

    # Summary
    if verbose:
        print(f"\n{'='*60}")
        print("VERIFICATION SUMMARY")
        print(f"{'='*60}")
        print(f"  Required tests:  {'PASS' if required_passed else 'FAIL'}")
        print(
            f"  Repository:      {'PASS' if repository_passed else 'FAIL'} "
            f"({repository_health.status})"
        )
        print(f"  E2E smoke:       {'PASS' if e2e_smoke_passed else 'FAIL'}")
        print(f"  E2E real (LLM):  {'PASS' if e2e_real_passed else 'FAIL'}")
        print(f"  Doc coupling:    {'PASS' if doc_passed else 'FAIL'}")
        if trace_warning:
            print(f"  Trace eval:      WARN  ← {trace_warning}")
        else:
            print("  Trace eval:      ok")

    if not all_passed:
        print(f"\nFAILED: Plan #{plan_number} cannot be marked complete.")
        print(f"Repository health: {repository_health.reason}")
        if repository_health.new_failures:
            print("New failures:")
            for failure in repository_health.new_failures:
                print(f"  - {failure}")
        if repository_health.changed_baseline_failures:
            print("Changed baseline failures:")
            for failure in repository_health.changed_baseline_failures:
                print(f"  - {failure}")
        if require_repository_green and repository_health.status == "baseline_degraded":
            print("This invocation requires a fully green repository suite.")
        print("Fix the issues above and try again.")
        return False

    # All passed - persist evidence, then synchronize coordination state before
    # marking the plan complete.
    commit, _branch = get_git_info(project_root)
    evidence_path = write_repository_health_evidence(
        project_root,
        plan_number,
        repository_health,
        dry_run=dry_run,
    )
    status_label = (
        "✅ Complete (scoped; repository baseline degraded)"
        if repository_health.status == "baseline_degraded"
        else "✅ Complete"
    )

    closed_count, closed_scopes, payload = sync_coordination_closeout(
        plan_number=plan_number,
        project_root=project_root,
        dry_run=dry_run,
        verbose=verbose,
    )

    if verbose:
        print("\nAll checks passed!")

    update_plan_file(
        plan_file=plan_file,
        unit_summary=unit_summary,
        e2e_smoke_summary=e2e_smoke_summary,
        e2e_real_summary=e2e_real_summary,
        doc_summary=doc_summary,
        commit=commit,
        dry_run=dry_run,
        required_summary=required_summary,
        repository_health_status=repository_health.status,
        repository_health_evidence=evidence_path.as_posix(),
        status_label=status_label,
    )

    update_plan_index(
        plan_number,
        plans_dir,
        dry_run,
        status_label=status_label,
    )

    if not dry_run:
        print(f"\n{status_label}: Plan #{plan_number}")
        print(f"   Verification evidence recorded in {plan_file.name}")
        if closed_count:
            print(f"   Closed claims: {', '.join(closed_scopes)}")
        if payload is not None:
            print(f"   Active-work registry refreshed: {payload['claim_count']} live claims remain")
        print("\nNext steps:")
        print(f"   1. Commit changes: git add {plan_file}")

    return True


def main() -> int:
    """Parse CLI arguments and execute the plan-completion workflow."""
    parser = argparse.ArgumentParser(
        description="Enforce plan completion requirements",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--plan", "-p",
        type=int,
        required=True,
        help="Plan number to complete (e.g., 35)"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Check without updating files"
    )
    parser.add_argument(
        "--skip-e2e",
        action="store_true",
        help="Skip all E2E tests (for documentation-only plans)"
    )
    parser.add_argument(
        "--skip-real-e2e",
        action="store_true",
        help="Skip real E2E tests (actual LLM calls) but run smoke tests"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Re-verify and update evidence for already-complete plans"
    )
    parser.add_argument(
        "--human-verified",
        action="store_true",
        help="Confirm human review has been done (for plans with '## Human Review Required')"
    )
    parser.add_argument(
        "--baseline-ref",
        default=None,
        help="Git ref whose merge base is the repository-health control (default: auto-detect)",
    )
    parser.add_argument(
        "--require-repository-green",
        action="store_true",
        help="Require the repository-wide suite to pass, for releases/promotions",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output"
    )

    args = parser.parse_args()

    project_root = Path.cwd()

    success = complete_plan(
        plan_number=args.plan,
        project_root=project_root,
        dry_run=args.dry_run,
        skip_e2e=args.skip_e2e,
        skip_real_e2e=args.skip_real_e2e,
        force=args.force,
        human_verified=args.human_verified,
        baseline_ref=args.baseline_ref,
        require_repository_green=args.require_repository_green,
        verbose=not args.quiet,
    )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
