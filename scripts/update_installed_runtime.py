#!/usr/bin/env python3
"""Safely update the installed Codex Enforced Planning runtime.

The installed runtime is a host control surface, not a governed project
worktree. This command is the narrow mutation boundary for updating it from
the canonical remote. It refuses dirty, non-main branches, unapproved divergent
states, and wrong identities, and retains the previous HEAD before mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RECOVERY_NAMESPACE = "refs/codex-runtime-recovery"
ZERO_OID = "0" * 40
CANONICAL_ORIGIN = "https://github.com/BrianMills2718/enforced-planning.git"
CANONICAL_ORIGIN_IDENTITY = "github.com/BrianMills2718/enforced-planning"


class RuntimeUpdateError(RuntimeError):
    """A checked precondition prevented the installed-runtime update."""

    def __init__(self, message: str, *, receipt: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.receipt = receipt


class ReceiptArgumentParser(argparse.ArgumentParser):
    """Return machine-readable denial for malformed operational invocations."""

    def error(self, message: str) -> None:
        raise RuntimeUpdateError(message)


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeUpdateError(f"git {' '.join(args)}: {detail}")
    return result


def _output(repo: Path, *args: str) -> str:
    return _run(repo, *args).stdout.strip()


def _default_runtime_repo() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home / "runtime" / "enforced-planning"


def _canonical_runtime_repo() -> Path:
    """Return the host-owned installed-runtime path, never a caller-selected path."""

    return _default_runtime_repo().resolve()


def _normalize_origin(origin: str) -> str:
    value = origin.strip().removesuffix("/").removesuffix(".git")
    for prefix in ("git@github.com:", "git@github-personal:"):
        if value.startswith(prefix):
            return f"github.com/{value.removeprefix(prefix)}"
    for prefix in (
        "https://github.com/",
        "ssh://git@github.com/",
        "ssh://git@github-personal/",
    ):
        if value.startswith(prefix):
            return f"github.com/{value.removeprefix(prefix)}"
    if value.startswith("file://"):
        return str(Path(value.removeprefix("file://")).resolve())
    if value.startswith("/"):
        return str(Path(value).resolve())
    raise RuntimeUpdateError(f"unsupported origin transport: {origin!r}")


def _canonical_origin_identity() -> str:
    return _normalize_origin(CANONICAL_ORIGIN)


def _observed_at(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _base_receipt(
    *, source_repo: Path, runtime_repo: Path, revision: str, write: bool, now: datetime | None
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "action": "denied",
        "state": "checking",
        "stage": "preflight",
        "host": socket.gethostname(),
        "observed_at": _observed_at(now),
        "source_repo": str(source_repo.resolve()),
        "runtime_repo": str(runtime_repo.resolve()),
        "origin": None,
        "canonical_repository": _canonical_origin_identity(),
        "checkout_mode": None,
        "before_revision": None,
        "target_revision": revision,
        "after_revision": None,
        "recovery_ref": None,
        "remote_main_revision": None,
        "changed": None,
        "update_mode": None,
        "mutation_started": False,
        "write_requested": write,
    }


def _deny(receipt: dict[str, Any], error: RuntimeUpdateError) -> RuntimeUpdateError:
    receipt.update(
        action="partial_failure" if receipt["mutation_started"] else "denied",
        state="failed",
        error={"type": type(error).__name__, "message": str(error)},
    )
    return RuntimeUpdateError(str(error), receipt=receipt.copy())


def _refresh_failure_state(runtime_repo: Path, receipt: dict[str, Any]) -> None:
    if receipt["before_revision"] is None:
        return
    head = _run(runtime_repo, "rev-parse", "HEAD", check=False)
    if head.returncode == 0 and FULL_SHA_RE.fullmatch(head.stdout.strip()):
        receipt["after_revision"] = head.stdout.strip()
    recovery_ref = receipt["recovery_ref"]
    if recovery_ref:
        retained = _run(runtime_repo, "rev-parse", recovery_ref, check=False)
        receipt["recovery_ref_retained"] = (
            retained.returncode == 0 and retained.stdout.strip() == receipt["before_revision"]
        )


def _assert_repo(path: Path, label: str) -> Path:
    if not path.is_dir() or _run(path, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip() != "true":
        raise RuntimeUpdateError(f"{label} is not a Git worktree: {path}")
    top = Path(_output(path, "rev-parse", "--show-toplevel")).resolve()
    if top != path:
        raise RuntimeUpdateError(f"{label} must be the exact Git worktree root: {path}")
    common = Path(_output(path, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = path / common
    return common.resolve()


def _assert_clean_runtime(runtime_repo: Path) -> str:
    dirty = _output(runtime_repo, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise RuntimeUpdateError("installed runtime is dirty; preserve or remove its changes before update")
    branch_result = _run(runtime_repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "detached"
    if branch not in {"main", "detached"}:
        raise RuntimeUpdateError(f"installed runtime must be on main, found {branch!r}")
    return branch


def _validate_revision(source_repo: Path, revision: str) -> None:
    if not FULL_SHA_RE.fullmatch(revision):
        raise RuntimeUpdateError("--revision must be one full lowercase 40-character commit SHA")
    resolved = _output(source_repo, "rev-parse", f"{revision}^{{commit}}")
    if resolved != revision:
        raise RuntimeUpdateError(f"source revision did not resolve exactly: {revision}")


def _remote_main_revision() -> str:
    result = subprocess.run(
        ["git", "ls-remote", CANONICAL_ORIGIN, "refs/heads/main"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git ls-remote failed"
        raise RuntimeUpdateError(f"cannot resolve canonical origin/main read-only: {detail}")
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != "refs/heads/main":
        raise RuntimeUpdateError("canonical origin/main did not resolve to exactly one ref")
    revision = rows[0][0]
    if not FULL_SHA_RE.fullmatch(revision):
        raise RuntimeUpdateError("canonical origin/main returned an invalid commit SHA")
    return revision


def _recovery_ref(before: str, now: datetime) -> str:
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{RECOVERY_NAMESPACE}/{stamp}-{before[:12]}"


def update_runtime(
    *,
    source_repo: Path,
    runtime_repo: Path,
    revision: str,
    write: bool,
    allow_detached_replacement: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and optionally fast-forward one exact installed runtime clone."""

    source_repo = source_repo.resolve()
    runtime_repo = runtime_repo.resolve()
    receipt = _base_receipt(
        source_repo=source_repo,
        runtime_repo=runtime_repo,
        revision=revision,
        write=write,
        now=now,
    )
    try:
        expected_runtime = _canonical_runtime_repo()
        if runtime_repo != expected_runtime:
            raise RuntimeUpdateError(
                f"installed runtime path must be exactly {expected_runtime}, found {runtime_repo}"
            )
        source_common_dir = _assert_repo(source_repo, "source repository")
        runtime_common_dir = _assert_repo(runtime_repo, "installed runtime")
        if runtime_common_dir != (runtime_repo / ".git").resolve():
            raise RuntimeUpdateError("installed runtime must be a standalone clone, not a linked worktree")
        if source_common_dir == runtime_common_dir:
            raise RuntimeUpdateError("source repository and installed runtime must be distinct clones")
        _validate_revision(source_repo, revision)
        checkout_mode = _assert_clean_runtime(runtime_repo)
        receipt["checkout_mode"] = checkout_mode

        source_origin = _output(source_repo, "remote", "get-url", "origin")
        runtime_origin = _output(runtime_repo, "remote", "get-url", "origin")
        expected_origin = _canonical_origin_identity()
        if _normalize_origin(source_origin) != expected_origin:
            raise RuntimeUpdateError("source repository is not the canonical Enforced Planning origin")
        if _normalize_origin(runtime_origin) != expected_origin:
            raise RuntimeUpdateError("installed runtime is not the canonical Enforced Planning origin")
        receipt["origin"] = expected_origin

        before = _output(runtime_repo, "rev-parse", "HEAD")
        receipt.update(before_revision=before, after_revision=before, changed=before != revision)
        receipt["stage"] = "resolve_remote"
        remote_main = _remote_main_revision()
        receipt["remote_main_revision"] = remote_main
        if remote_main != revision:
            raise RuntimeUpdateError(
                f"requested revision {revision} is not canonical origin/main {remote_main}"
            )

        fast_forward = (
            _run(source_repo, "merge-base", "--is-ancestor", before, revision, check=False).returncode == 0
        )
        detached_replacement = checkout_mode == "detached" and allow_detached_replacement
        receipt["update_mode"] = "fast_forward" if fast_forward else "detached_replacement"
        if not fast_forward and not detached_replacement:
            raise RuntimeUpdateError(
                f"installed runtime {before} cannot fast-forward to canonical revision {revision}; "
                "an explicit detached replacement with a recovery ref is required"
            )

        if not write or before == revision:
            receipt.update(
                action="current" if before == revision else "would_update",
                state="succeeded",
                stage="complete",
            )
            return receipt

        if write:
            receipt["stage"] = "fetch_target"
            receipt["mutation_started"] = True
            _run(runtime_repo, "fetch", "--no-tags", "--no-write-fetch-head", CANONICAL_ORIGIN, revision)
            _validate_revision(runtime_repo, revision)

        recovery_ref = _recovery_ref(before, now or datetime.now(UTC))
        receipt["stage"] = "create_recovery_ref"
        _run(runtime_repo, "update-ref", recovery_ref, before, ZERO_OID)
        receipt["recovery_ref"] = recovery_ref
        receipt["mutation_started"] = True
        # The recovery ref deliberately remains and is reported if mutation fails.
        receipt["stage"] = "apply_update"
        if fast_forward:
            _run(runtime_repo, "merge", "--ff-only", revision)
        else:
            _run(runtime_repo, "checkout", "--detach", revision)

        receipt["stage"] = "verify"
        after = _output(runtime_repo, "rev-parse", "HEAD")
        _assert_clean_runtime(runtime_repo)
        retained = _output(runtime_repo, "rev-parse", recovery_ref)
        if after != revision or retained != before:
            raise RuntimeUpdateError("post-update revision or recovery-ref verification failed")
        receipt.update(action="updated", state="succeeded", stage="complete", after_revision=after)
        return receipt
    except RuntimeUpdateError as exc:
        _refresh_failure_state(runtime_repo, receipt)
        raise _deny(receipt, exc) from exc


def _parser() -> argparse.ArgumentParser:
    parser = ReceiptArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="canonical Enforced Planning source checkout (default: this script's repository)",
    )
    parser.add_argument(
        "--runtime-repo",
        type=Path,
        default=_default_runtime_repo(),
        help="installed runtime clone (default: $CODEX_HOME/runtime/enforced-planning)",
    )
    parser.add_argument("--revision", required=True, help="exact full canonical origin/main commit SHA")
    parser.add_argument("--write", action="store_true", help="perform the checked fast-forward")
    parser.add_argument(
        "--allow-detached-replacement",
        action="store_true",
        help="replace a clean divergent detached HEAD after retaining its exact recovery ref",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        payload = update_runtime(
            source_repo=args.source_repo,
            runtime_repo=args.runtime_repo,
            revision=args.revision,
            write=args.write,
            allow_detached_replacement=args.allow_detached_replacement,
        )
    except RuntimeUpdateError as exc:
        payload = exc.receipt or _base_receipt(
            source_repo=Path(__file__).resolve().parents[1],
            runtime_repo=_default_runtime_repo(),
            revision="",
            write=False,
            now=None,
        )
        if exc.receipt is None:
            payload["stage"] = "arguments"
            payload = _deny(payload, exc).receipt
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
