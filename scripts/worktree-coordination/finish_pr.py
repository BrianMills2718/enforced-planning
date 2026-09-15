#!/usr/bin/env python3
"""Review and merge one exact PR head, then close its claimed lane."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


def _framework_root() -> Path:
    """Resolve both source and installed ``scripts/meta`` layouts."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "contracts" / "pr-review-signoff.schema.json").is_file():
            return candidate
    raise RuntimeError("cannot locate the installed PR review contract")


REPO_ROOT = _framework_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_INTEGRATION_AUTHORITY_IMPORT_ERROR: ModuleNotFoundError | None = None
try:
    from enforced_planning.integration_authority import (
        IntegrationAuthorityAssertionV1,
        IntegrationTargetV1,
        assert_integration_authority,
        integration_authority_guard,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {
        "enforced_planning",
        "enforced_planning.integration_authority",
    }:
        raise
    _INTEGRATION_AUTHORITY_IMPORT_ERROR = exc

try:
    from enforced_planning.pr_review_signoff import (
        PRReviewSpec,
        PRSignoffReceipt,
        PullRequestRevision,
        load_review_spec,
        run_review,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"enforced_planning", "enforced_planning.pr_review_signoff"}:
        raise
    runtime_path = REPO_ROOT / "scripts" / "meta" / "pr_review_signoff_runtime.py"
    runtime_spec = importlib.util.spec_from_file_location(
        "installed_pr_review_signoff_runtime", runtime_path
    )
    if runtime_spec is None or runtime_spec.loader is None:
        raise RuntimeError(f"PR review runtime is unavailable: {runtime_path}")
    runtime = importlib.util.module_from_spec(runtime_spec)
    sys.modules[runtime_spec.name] = runtime
    runtime_spec.loader.exec_module(runtime)
    PRReviewSpec = runtime.PRReviewSpec
    PRSignoffReceipt = runtime.PRSignoffReceipt
    PullRequestRevision = runtime.PullRequestRevision
    load_review_spec = runtime.load_review_spec
    run_review = runtime.run_review


def require_integration_authority() -> None:
    """Fail execution, but not CLI discovery, when the pinned package is stale."""

    if _INTEGRATION_AUTHORITY_IMPORT_ERROR is not None:
        raise RuntimeError(
            "integration authority runtime is unavailable; update the declared "
            "enforced-planning dependency before running make finish"
        ) from _INTEGRATION_AUTHORITY_IMPORT_ERROR

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class PrSnapshot:
    base_sha: str
    head_sha: str
    head_branch: str
    base_branch: str
    state: str
    mergeable: str
    checks: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class TrustedReviewSpec:
    spec: PRReviewSpec
    sha256: str


def run_cmd(
    cmd: list[str], check: bool = True, capture: bool = True, *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, check=check, capture_output=capture, text=True,
        env=dict(env) if env is not None else None,
    )


def is_in_worktree() -> bool:
    return Path(".git").is_file()


def get_main_repo_root() -> Path:
    result = run_cmd(["git", "rev-parse", "--git-common-dir"], check=False)
    return Path(result.stdout.strip()).parent if result.returncode == 0 else Path.cwd()


def _load_pr_auto() -> ModuleType:
    """Load the existing isolated account-routing seam beside this helper."""
    candidates = (REPO_ROOT / "scripts" / "pr_auto.py", REPO_ROOT / "scripts" / "meta" / "pr_auto.py")
    candidate = next((path for path in candidates if path.is_file()), None)
    if candidate is None:
        raise RuntimeError(f"GitHub account-routing seam is unavailable: {candidates}")
    spec = importlib.util.spec_from_file_location("finish_pr_pr_auto", candidate)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load GitHub account-routing seam: {candidate}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def github_repository_context() -> Iterator[tuple[str, dict[str, str]]]:
    """Select the origin owner in a private gh config; never mutate shared auth."""
    routing = _load_pr_auto()
    remote = run_cmd(["git", "config", "--get", "remote.origin.url"], check=False)
    if remote.returncode != 0:
        raise RuntimeError(f"Cannot resolve origin URL: {remote.stderr.strip()}")
    repo_slug = routing.parse_github_repo_slug(remote.stdout)
    if repo_slug is None:
        raise RuntimeError(f"Cannot parse GitHub origin URL: {remote.stdout.strip()}")
    account = repo_slug.split("/", 1)[0]
    gh_env = routing.sanitize_github_env(os.environ)
    with routing.isolated_github_auth(
        cwd=Path.cwd(), gh_env=gh_env, account=account
    ) as isolated_env:
        yield repo_slug, isolated_env


def _pr_view_command(pr_number: int, repo_slug: str) -> list[str]:
    return [
        "gh", "pr", "view", str(pr_number), "--repo", repo_slug, "--json",
        "baseRefOid,headRefOid,headRefName,baseRefName,statusCheckRollup,mergeable,state,mergeCommit",
    ]


def _parse_pr_snapshot(raw: str) -> tuple[PrSnapshot, str | None]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GitHub returned invalid PR JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError("GitHub PR response must be one JSON object")
    base_sha = data.get("baseRefOid")
    head_sha = data.get("headRefOid")
    head_branch = data.get("headRefName")
    base_branch = data.get("baseRefName")
    if not isinstance(base_sha, str) or not FULL_SHA_RE.fullmatch(base_sha):
        raise ValueError("PR baseRefOid is missing or is not one full commit SHA")
    if not isinstance(head_sha, str) or not FULL_SHA_RE.fullmatch(head_sha):
        raise ValueError("PR headRefOid is missing or is not one full commit SHA")
    if not isinstance(head_branch, str) or not head_branch:
        raise ValueError("PR head branch is missing")
    if not isinstance(base_branch, str) or not base_branch:
        raise ValueError("PR base branch is missing")
    checks = data.get("statusCheckRollup") or []
    if not isinstance(checks, list) or not all(isinstance(item, dict) for item in checks):
        raise ValueError("PR statusCheckRollup is malformed")
    merge_commit = None
    raw_merge = data.get("mergeCommit")
    if isinstance(raw_merge, dict):
        candidate = raw_merge.get("oid")
        if isinstance(candidate, str) and FULL_SHA_RE.fullmatch(candidate):
            merge_commit = candidate
    return PrSnapshot(
        base_sha, head_sha, head_branch, base_branch,
        str(data.get("state", "UNKNOWN")), str(data.get("mergeable", "UNKNOWN")),
        tuple(checks),
    ), merge_commit


def fetch_pr_snapshot(
    pr_number: int, repo_slug: str, gh_env: Mapping[str, str]
) -> tuple[PrSnapshot, str | None]:
    result = run_cmd(_pr_view_command(pr_number, repo_slug), check=False, env=gh_env)
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to fetch PR head/check rollup: "
            + (result.stderr or result.stdout).strip()
        )
    return _parse_pr_snapshot(result.stdout)


def registered_worktree_roots(canonical_root: Path) -> tuple[Path, ...]:
    result = run_cmd(
        ["git", "-C", str(canonical_root), "worktree", "list", "--porcelain"],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "cannot enumerate repository worktrees: "
            + (result.stderr or result.stdout).strip()
        )
    roots = tuple(
        Path(line.removeprefix("worktree ")).resolve()
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    )
    if not roots:
        raise RuntimeError("repository reported no registered worktrees")
    return roots


def load_trusted_review_spec(
    path: Path,
    *,
    canonical_root: Path,
    worktree_roots: tuple[Path, ...] | None = None,
) -> PRReviewSpec:
    """Load coordinator input only when it is outside PR-controlled repository bytes."""
    if not path.is_absolute():
        raise ValueError("review spec must be an absolute path outside the repository")
    lexical = path.absolute()
    resolved = path.resolve(strict=True)
    roots = worktree_roots or registered_worktree_roots(canonical_root)
    if any(
        lexical.is_relative_to(root.resolve()) or resolved.is_relative_to(root.resolve())
        for root in roots
    ):
        raise ValueError("review spec must be outside the repository and its worktrees")
    return load_review_spec(resolved)


def load_trusted_review_bundle(
    path: Path,
    *,
    canonical_root: Path,
    worktree_roots: tuple[Path, ...] | None = None,
) -> TrustedReviewSpec:
    """Read and validate the trusted review spec exactly once."""

    if not path.is_absolute():
        raise ValueError("review spec must be an absolute path outside the repository")
    lexical = path.absolute()
    resolved = path.resolve(strict=True)
    roots = worktree_roots or registered_worktree_roots(canonical_root)
    if any(
        lexical.is_relative_to(root.resolve()) or resolved.is_relative_to(root.resolve())
        for root in roots
    ):
        raise ValueError("review spec must be outside the repository and its worktrees")
    content = resolved.read_bytes()
    return TrustedReviewSpec(
        spec=PRReviewSpec.model_validate_json(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def resolve_branch_worktree(branch: str) -> Path:
    """Resolve exactly one linked worktree checked out on the requested branch."""
    result = run_cmd(["git", "worktree", "list", "--porcelain"], check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    matches: list[Path] = []
    current_path: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line.removeprefix("worktree "))
        elif line == f"branch refs/heads/{branch}" and current_path is not None:
            matches.append(current_path)
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one linked worktree for {branch!r}; found {len(matches)}"
        )
    return matches[0]


def run_local_review_gate(
    *,
    spec: PRReviewSpec,
    snapshot: PrSnapshot,
    review_worktree: Path,
    repo_slug: str,
    pr_number: int,
    gh_env: Mapping[str, str],
    output_root: Path,
) -> tuple[PRSignoffReceipt, Path]:
    """Run the potentially slow evidence-bound review outside hook execution."""
    if spec.repository != repo_slug or spec.pull_request != pr_number:
        raise RuntimeError("review spec repository or pull request does not match the merge target")
    if spec.base_sha != snapshot.base_sha or spec.head_sha != snapshot.head_sha:
        raise RuntimeError("review spec revision does not match the live pull request")

    def resolve_live(repository: str, pull_request: int) -> PullRequestRevision:
        live, _ = fetch_pr_snapshot(pull_request, repository, gh_env)
        return PullRequestRevision(base_sha=live.base_sha, head_sha=live.head_sha)

    output_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="finish-pr-review-") as directory:
        temporary = Path(directory)
        receipt_path = temporary / "receipt.json"
        payload_path = temporary / "candidate-check.json"
        receipt = run_review(
            spec,
            repo_root=review_worktree,
            output_schema=REPO_ROOT / "contracts" / "pr-review-signoff.schema.json",
            receipt_path=receipt_path,
            check_payload_path=payload_path,
            pr_revision_resolver=resolve_live,
        )
        digest = receipt.receipt_sha256()
        durable_receipt = output_root / f"receipt-{digest}.json"
        durable_payload = output_root / f"candidate-check-{digest}.json"
        for source, target in ((receipt_path, durable_receipt), (payload_path, durable_payload)):
            content = source.read_bytes()
            if target.exists() and target.read_bytes() != content:
                raise RuntimeError(f"content-addressed review artifact collision: {target}")
            if not target.exists():
                target.write_bytes(content)
    if receipt.verdict != "signed_off":
        raise RuntimeError("evidence-bound review rejected the exact pull-request head")
    return receipt, durable_receipt


def fetch_exact_pr_head(pr_number: int, expected_sha: str) -> tuple[bool, str]:
    fetched = run_cmd(
        ["git", "fetch", "--no-tags", "origin", f"refs/pull/{pr_number}/head"],
        check=False,
    )
    if fetched.returncode != 0:
        return False, (fetched.stderr or fetched.stdout).strip()
    resolved = run_cmd(["git", "rev-parse", "FETCH_HEAD"], check=False)
    actual = resolved.stdout.strip() if resolved.returncode == 0 else ""
    if actual != expected_sha:
        return False, f"fetched PR head {actual or 'unknown'} != API head {expected_sha}"
    return True, "OK"


def require_all_required_checks(
    pr_number: int, repo_slug: str, gh_env: Mapping[str, str]
) -> tuple[bool, str]:
    result = run_cmd(
        ["gh", "pr", "checks", str(pr_number), "--repo", repo_slug, "--required"],
        check=False, env=gh_env,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        # `gh pr checks --required` exits 1 with "no checks reported" both when the
        # base branch requires nothing and when required checks never started.
        # Only the first is a pass, so ask GitHub what the base branch requires.
        if result.returncode == 1 and "no checks reported" in output.lower():
            configured, reason = base_branch_required_checks(pr_number, repo_slug, gh_env)
            if configured is None:
                return False, f"required checks are unavailable: {output}; {reason}"
            if not configured:
                return True, "OK: base branch requires no status checks"
            return False, f"required checks have not reported: {', '.join(configured)}"
        state = "pending" if result.returncode == 8 else "failing or unavailable"
        return False, f"required checks are {state}: {output}"
    return True, "OK"


def base_branch_required_checks(
    pr_number: int, repo_slug: str, gh_env: Mapping[str, str]
) -> tuple[list[str] | None, str]:
    """Return required check names on the PR base branch, or None when unknowable."""
    base = run_cmd(
        ["gh", "pr", "view", str(pr_number), "--repo", repo_slug,
         "--json", "baseRefName", "--jq", ".baseRefName"],
        check=False, env=gh_env,
    )
    branch = base.stdout.strip()
    if base.returncode != 0 or not branch:
        return None, f"cannot resolve PR base branch: {(base.stderr or base.stdout).strip()}"
    required: list[str] = []
    classic = run_cmd(
        ["gh", "api", f"repos/{repo_slug}/branches/{branch}/protection/required_status_checks"],
        check=False, env=gh_env,
    )
    if classic.returncode == 0:
        data = json.loads(classic.stdout)
        required.extend(data.get("contexts") or [])
        required.extend(c["context"] for c in data.get("checks") or [] if c.get("context"))
    elif not any(
        marker in (classic.stdout + classic.stderr)
        for marker in ("Required status checks not enabled", "Branch not protected")
    ):
        return None, f"cannot read branch protection: {(classic.stderr or classic.stdout).strip()}"
    rules = run_cmd(
        ["gh", "api", f"repos/{repo_slug}/rules/branches/{branch}"],
        check=False, env=gh_env,
    )
    if rules.returncode != 0:
        return None, f"cannot read branch rules: {(rules.stderr or rules.stdout).strip()}"
    for rule in json.loads(rules.stdout):
        if rule.get("type") == "required_status_checks":
            required.extend(
                c["context"]
                for c in (rule.get("parameters") or {}).get("required_status_checks") or []
                if c.get("context")
            )
        elif rule.get("type") == "workflows":
            required.append("required workflows ruleset")
    return sorted(set(required)), "OK"


def prepare_merge_gate(
    pr_number: int,
    branch: str,
    repo_slug: str,
    gh_env: Mapping[str, str],
    *,
    review_spec_path: Path,
    review_output_root: Path,
) -> tuple[PrSnapshot, Path, TrustedReviewSpec]:
    first, _ = fetch_pr_snapshot(pr_number, repo_slug, gh_env)
    if first.state != "OPEN":
        raise RuntimeError(f"PR state is {first.state}, not OPEN")
    if first.head_branch != branch:
        raise RuntimeError(f"PR head branch {first.head_branch!r} != requested {branch!r}")
    if first.mergeable == "CONFLICTING":
        raise RuntimeError("PR has merge conflicts")
    fetched, reason = fetch_exact_pr_head(pr_number, first.head_sha)
    if not fetched:
        raise RuntimeError(f"Cannot bind exact PR head: {reason}")
    checks_ok, reason = require_all_required_checks(pr_number, repo_slug, gh_env)
    if not checks_ok:
        raise RuntimeError(reason)
    second, _ = fetch_pr_snapshot(pr_number, repo_slug, gh_env)
    if second.head_sha != first.head_sha:
        raise RuntimeError(
            f"PR head changed while checks ran: {first.head_sha} -> {second.head_sha}; review is stale"
        )
    if second.state != "OPEN":
        raise RuntimeError(f"PR state changed to {second.state} before merge")
    trusted_review = load_trusted_review_bundle(
        review_spec_path, canonical_root=get_main_repo_root()
    )
    _receipt, receipt_path = run_local_review_gate(
        spec=trusted_review.spec,
        snapshot=second,
        review_worktree=resolve_branch_worktree(branch),
        repo_slug=repo_slug,
        pr_number=pr_number,
        gh_env=gh_env,
        output_root=review_output_root / repo_slug.replace("/", "__") / f"pr-{pr_number}",
    )
    final, _ = fetch_pr_snapshot(pr_number, repo_slug, gh_env)
    if (
        final.base_sha != first.base_sha
        or final.head_sha != first.head_sha
        or final.state != "OPEN"
    ):
        raise RuntimeError("PR changed after review; signoff is stale")
    checks_ok, reason = require_all_required_checks(pr_number, repo_slug, gh_env)
    if not checks_ok:
        raise RuntimeError(reason)
    after_checks, _ = fetch_pr_snapshot(pr_number, repo_slug, gh_env)
    if after_checks != final:
        raise RuntimeError("PR changed while final required checks ran; signoff is stale")
    return after_checks, receipt_path, trusted_review


def integration_target(
    *,
    snapshot: PrSnapshot,
    repository: str,
    project: str,
    pr_number: int,
    branch: str,
    trusted_review: TrustedReviewSpec,
) -> IntegrationTargetV1:
    """Bind the reviewed revision and trusted spec to canonical claim custody."""

    require_integration_authority()
    return IntegrationTargetV1(
        repository=repository,
        project=project,
        pr_number=pr_number,
        branch=branch,
        base_sha=snapshot.base_sha,
        head_sha=snapshot.head_sha,
        review_spec_sha256=trusted_review.sha256,
        review_work_graph_sha256=trusted_review.spec.work_graph_sha256,
        review_work_unit_id=trusted_review.spec.work_unit_id,
    )


def merge_exact_head(
    pr_number: int, snapshot: PrSnapshot, repo_slug: str,
    gh_env: Mapping[str, str],
    *,
    authority: IntegrationAuthorityAssertionV1,
    target: IntegrationTargetV1,
    agent: str,
    repo_root: Path,
    review_spec_path: Path,
) -> tuple[bool, str]:
    require_integration_authority()
    with integration_authority_guard(
        authority,
        expected_target=target,
        agent=agent,
        repo_root=repo_root,
        review_spec_path=review_spec_path,
    ):
        result = run_cmd([
            "gh", "pr", "merge", str(pr_number), "--repo", repo_slug, "--squash",
            "--match-head-commit", snapshot.head_sha,
        ], check=False, env=gh_env)
    return (
        (True, "Merged") if result.returncode == 0
        else (False, (result.stderr or result.stdout).strip())
    )


def verify_merged_pr(
    pr_number: int, expected_head: str, repo_slug: str,
    gh_env: Mapping[str, str],
) -> tuple[bool, str | None, str]:
    snapshot, merge_commit = fetch_pr_snapshot(pr_number, repo_slug, gh_env)
    if snapshot.head_sha != expected_head:
        return False, None, "merged PR head differs from the approved head"
    if snapshot.state != "MERGED":
        return False, None, f"GitHub reports PR state {snapshot.state}, not MERGED"
    if merge_commit is None:
        return False, None, "GitHub did not report one full merge commit SHA"
    return True, merge_commit, "OK"


def prepare_post_merge_recovery(
    *,
    snapshot: PrSnapshot,
    merge_commit: str | None,
    branch: str,
    pr_number: int,
    repo_slug: str,
    gh_env: Mapping[str, str],
    agent: str,
    project: str,
    repo_root: Path,
    review_spec_path: Path,
    review_output_root: Path,
) -> tuple[str, Path, IntegrationAuthorityAssertionV1]:
    """Re-prove exact review and claim custody after merge-before-close failure."""

    require_integration_authority()
    if snapshot.state != "MERGED" or merge_commit is None:
        raise RuntimeError("post-merge recovery requires a verified merged PR")
    if snapshot.head_branch != branch:
        raise RuntimeError(
            f"merged PR head branch {snapshot.head_branch!r} != requested {branch!r}"
        )
    checks_ok, reason = require_all_required_checks(pr_number, repo_slug, gh_env)
    if not checks_ok:
        raise RuntimeError(reason)
    trusted_review = load_trusted_review_bundle(
        review_spec_path, canonical_root=repo_root
    )
    _receipt, receipt_path = run_local_review_gate(
        spec=trusted_review.spec,
        snapshot=snapshot,
        review_worktree=resolve_branch_worktree(branch),
        repo_slug=repo_slug,
        pr_number=pr_number,
        gh_env=gh_env,
        output_root=review_output_root / repo_slug.replace("/", "__") / f"pr-{pr_number}",
    )
    target = integration_target(
        snapshot=snapshot,
        repository=repo_slug,
        project=project,
        pr_number=pr_number,
        branch=branch,
        trusted_review=trusted_review,
    )
    authority = assert_integration_authority(
        target=target,
        agent=agent,
        repo_root=repo_root,
        review_spec_path=review_spec_path,
    )
    return merge_commit, receipt_path, authority


def close_merged_lane(branch: str, merge_commit: str, base_branch: str) -> tuple[bool, str]:
    refresh = run_cmd(["git", "fetch", "--no-tags", "origin", base_branch], check=False)
    if refresh.returncode != 0:
        return False, (refresh.stderr or refresh.stdout).strip()
    retained = run_cmd(
        ["git", "merge-base", "--is-ancestor", merge_commit, f"origin/{base_branch}"],
        check=False,
    )
    if retained.returncode != 0:
        return False, (
            f"verified merge commit {merge_commit} is not retained by origin/{base_branch}"
        )
    close = run_cmd([
        "make", "worktree-remove", f"BRANCH={branch}",
        f"WORKTREE_MERGE_COMMIT={merge_commit}",
    ], check=False)
    if close.returncode != 0:
        return False, (close.stderr or close.stdout).strip()
    update = run_cmd(["git", "pull", "--ff-only", "origin", base_branch], check=False)
    if update.returncode != 0:
        return False, (update.stderr or update.stdout).strip()
    return True, "Closed"


def finish_pr(
    branch: str,
    pr_number: int,
    *,
    agent: str,
    project: str,
    review_spec_path: Path,
    review_output_root: Path,
) -> bool:
    if is_in_worktree():
        print("ERROR: finish_pr must run from the canonical repository checkout.")
        print(f"Run: cd {get_main_repo_root()} && make finish BRANCH={branch} PR={pr_number}")
        return False
    try:
        with github_repository_context() as (repo_slug, gh_env):
            repo_root = get_main_repo_root().resolve()
            live_snapshot, live_merge_commit = fetch_pr_snapshot(
                pr_number, repo_slug, gh_env
            )
            if live_snapshot.state == "MERGED":
                merge_commit, receipt_path, authority = prepare_post_merge_recovery(
                    snapshot=live_snapshot,
                    merge_commit=live_merge_commit,
                    branch=branch,
                    pr_number=pr_number,
                    repo_slug=repo_slug,
                    gh_env=gh_env,
                    agent=agent,
                    project=project,
                    repo_root=repo_root,
                    review_spec_path=review_spec_path,
                    review_output_root=review_output_root,
                )
                snapshot = live_snapshot
                print(
                    f"Recovered merged exact head {snapshot.head_sha}; "
                    f"re-reviewed receipt: {receipt_path}; integration authority: "
                    f"{authority.assertion_sha256}"
                )
            else:
                snapshot, receipt_path, trusted_review = prepare_merge_gate(
                    pr_number,
                    branch,
                    repo_slug,
                    gh_env,
                    review_spec_path=review_spec_path,
                    review_output_root=review_output_root,
                )
                target = integration_target(
                    snapshot=snapshot,
                    repository=repo_slug,
                    project=project,
                    pr_number=pr_number,
                    branch=branch,
                    trusted_review=trusted_review,
                )
                authority = assert_integration_authority(
                    target=target,
                    agent=agent,
                    repo_root=repo_root,
                    review_spec_path=review_spec_path,
                )
                print(
                    f"Reviewed exact head {snapshot.head_sha}; all required checks passed. "
                    f"Receipt: {receipt_path}; integration authority: "
                    f"{authority.assertion_sha256}"
                )
                merged, reason = merge_exact_head(
                    pr_number,
                    snapshot,
                    repo_slug,
                    gh_env,
                    authority=authority,
                    target=target,
                    agent=agent,
                    repo_root=repo_root,
                    review_spec_path=review_spec_path,
                )
                if not merged:
                    print(f"ERROR: merge failed: {reason}")
                    return False
                verified, merge_commit, reason = verify_merged_pr(
                    pr_number, snapshot.head_sha, repo_slug, gh_env
                )
                if not verified or merge_commit is None:
                    print(f"HIGH: merge command returned but verification failed: {reason}")
                    return False
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: merge gate denied: {exc}")
        return False
    closed, reason = close_merged_lane(branch, merge_commit, snapshot.base_branch)
    if not closed:
        print(f"HIGH: PR merged, but sanctioned lane closeout failed: {reason}")
        return False
    print(f"Done: PR #{pr_number} merged at {snapshot.head_sha} and lane closed.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge one exact approved PR head and close its claimed lane."
    )
    parser.add_argument("--branch", "-b", required=True)
    parser.add_argument("--pr", "-p", type=int, required=True)
    parser.add_argument("--agent", choices=("codex", "claude-code", "openclaw"), required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--review-spec", type=Path, required=True)
    parser.add_argument(
        "--review-output-root",
        type=Path,
        default=Path.home() / ".local" / "state" / "enforced-planning" / "pr-reviews",
    )
    args = parser.parse_args()
    return 0 if finish_pr(
        args.branch,
        args.pr,
        agent=args.agent,
        project=args.project,
        review_spec_path=args.review_spec,
        review_output_root=args.review_output_root,
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
