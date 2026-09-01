#!/usr/bin/env python3
"""Safely fast-forward the installed Codex Enforced Planning runtime.

The installed runtime is a host control surface, not a governed project
worktree.  This command is the narrow mutation boundary for updating it from
the canonical remote.  It refuses dirty, detached, divergent, or wrong-remote
clones and retains the previous HEAD under a recovery ref before mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RECOVERY_NAMESPACE = "refs/codex-runtime-recovery"


class RuntimeUpdateError(RuntimeError):
    """A checked precondition prevented the installed-runtime update."""


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


def _assert_repo(path: Path, label: str) -> None:
    if not path.is_dir() or _run(path, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip() != "true":
        raise RuntimeUpdateError(f"{label} is not a Git worktree: {path}")


def _assert_clean_runtime(runtime_repo: Path) -> None:
    dirty = _output(runtime_repo, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise RuntimeUpdateError("installed runtime is dirty; preserve or remove its changes before update")
    branch = _output(runtime_repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != "main":
        raise RuntimeUpdateError(f"installed runtime must be on main, found {branch!r}")


def _validate_revision(source_repo: Path, revision: str) -> None:
    if not FULL_SHA_RE.fullmatch(revision):
        raise RuntimeUpdateError("--revision must be one full lowercase 40-character commit SHA")
    resolved = _output(source_repo, "rev-parse", f"{revision}^{{commit}}")
    if resolved != revision:
        raise RuntimeUpdateError(f"source revision did not resolve exactly: {revision}")


def _recovery_ref(before: str, now: datetime) -> str:
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{RECOVERY_NAMESPACE}/{stamp}-{before[:12]}"


def update_runtime(
    *,
    source_repo: Path,
    runtime_repo: Path,
    revision: str,
    write: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and optionally fast-forward one exact installed runtime clone."""

    source_repo = source_repo.resolve()
    runtime_repo = runtime_repo.resolve()
    _assert_repo(source_repo, "source repository")
    _assert_repo(runtime_repo, "installed runtime")
    _validate_revision(source_repo, revision)
    _assert_clean_runtime(runtime_repo)

    source_origin = _output(source_repo, "remote", "get-url", "origin")
    runtime_origin = _output(runtime_repo, "remote", "get-url", "origin")
    if runtime_origin != source_origin:
        raise RuntimeUpdateError(
            "installed runtime origin does not match canonical source origin: "
            f"{runtime_origin!r} != {source_origin!r}"
        )

    before = _output(runtime_repo, "rev-parse", "HEAD")
    _run(runtime_repo, "fetch", "origin", "main")
    remote_main = _output(runtime_repo, "rev-parse", "refs/remotes/origin/main")
    if remote_main != revision:
        raise RuntimeUpdateError(
            f"requested revision {revision} is not the fetched canonical origin/main {remote_main}"
        )
    if _run(runtime_repo, "merge-base", "--is-ancestor", before, revision, check=False).returncode != 0:
        raise RuntimeUpdateError(
            f"installed runtime {before} cannot fast-forward to canonical revision {revision}"
        )

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "action": "check" if not write else "updated",
        "source_repo": str(source_repo),
        "runtime_repo": str(runtime_repo),
        "origin": runtime_origin,
        "before_revision": before,
        "target_revision": revision,
        "after_revision": before,
        "recovery_ref": None,
        "changed": before != revision,
    }
    if not write or before == revision:
        payload["action"] = "current" if before == revision else "would_update"
        return payload

    recovery_ref = _recovery_ref(before, now or datetime.now(UTC))
    _run(runtime_repo, "update-ref", recovery_ref, before)
    # The recovery ref deliberately remains even when the merge itself fails.
    _run(runtime_repo, "merge", "--ff-only", revision)

    after = _output(runtime_repo, "rev-parse", "HEAD")
    _assert_clean_runtime(runtime_repo)
    retained = _output(runtime_repo, "rev-parse", recovery_ref)
    if after != revision or retained != before:
        raise RuntimeUpdateError("post-update revision or recovery-ref verification failed")
    payload.update(after_revision=after, recovery_ref=recovery_ref)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = update_runtime(
            source_repo=args.source_repo,
            runtime_repo=args.runtime_repo,
            revision=args.revision,
            write=args.write,
        )
    except RuntimeUpdateError as exc:
        print(json.dumps({"schema_version": "1.0", "action": "denied", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
