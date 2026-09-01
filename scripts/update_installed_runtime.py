#!/usr/bin/env python3
"""Safely update the installed Codex Enforced Planning runtime.

The installed runtime is a host control surface, not a governed project
worktree. This command is the narrow mutation boundary for updating it from
the canonical remote. It refuses dirty, non-main branches, unapproved divergent
states, and wrong identities, and retains the previous HEAD before mutation.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
import pwd
import re
import socket
import stat
import subprocess
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RECOVERY_NAMESPACE = "refs/codex-runtime-recovery"
RECOVERY_CONFIG_PREFIX = "codex.runtimerecovery"
RECOVERY_REF_KEY_RE = re.compile(r"^\d{8}T\d{12}Z-[0-9a-f]{12}$")
RECOVERY_CONFIG_RE = re.compile(
    r"^codex\.runtimerecovery\.\d{8}t\d{12}z-[0-9a-f]{12}\."
    r"record$"
)
ZERO_OID = "0" * 40
CANONICAL_ORIGIN = "https://github.com/BrianMills2718/enforced-planning.git"
CANONICAL_ORIGIN_IDENTITY = "github.com/BrianMills2718/enforced-planning"
LEGACY_RUNTIME_ORIGIN = "git@github-personal:BrianMills2718/enforced-planning.git"
GIT_EXECUTABLE = Path("/usr/bin/git")
GH_EXECUTABLE = Path("/usr/bin/gh")
ALLOWED_RUNTIME_CONFIG_KEYS = {
    "branch.main.merge",
    "branch.main.remote",
    "core.bare",
    "core.filemode",
    "core.logallrefupdates",
    "core.repositoryformatversion",
    "remote.origin.fetch",
    "remote.origin.url",
    "user.email",
    "user.name",
}


class RuntimeUpdateError(RuntimeError):
    """A checked precondition prevented the installed-runtime update."""

    def __init__(self, message: str, *, receipt: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.receipt = receipt


class ReceiptArgumentParser(argparse.ArgumentParser):
    """Return machine-readable denial for malformed operational invocations."""

    def error(self, message: str) -> None:
        raise RuntimeUpdateError(message)


def _run(
    repo: Path,
    *args: str,
    check: bool = True,
    mutating: bool = False,
    network_auth: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = _canonical_network_git_env() if network_auth else _sanitized_git_env()
    if not mutating:
        env["GIT_OPTIONAL_LOCKS"] = "0"
    command = [str(GIT_EXECUTABLE)]
    if mutating:
        command.extend(("-c", "core.hooksPath=/dev/null"))
    command.extend(("-C", str(repo), *args))
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeUpdateError(f"git {' '.join(args)}: {detail}")
    return result


def _output(repo: Path, *args: str) -> str:
    return _run(repo, *args).stdout.strip()


def _default_runtime_repo() -> Path:
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return account_home / ".codex" / "runtime" / "enforced-planning"


def _canonical_runtime_repo() -> Path:
    """Return the host-owned installed-runtime path, never a caller-selected path."""

    return _default_runtime_repo()


def _normalize_origin(origin: str) -> str:
    value = origin.strip().removesuffix("/").removesuffix(".git")
    for prefix in ("https://github.com/",):
        if value.startswith(prefix):
            return f"github.com/{value.removeprefix(prefix)}"
    if value.startswith("file://"):
        return str(Path(value.removeprefix("file://")).resolve())
    if value.startswith("/"):
        return str(Path(value).resolve())
    raise RuntimeUpdateError("unsupported origin transport")


def _canonical_origin_identity() -> str:
    return _normalize_origin(CANONICAL_ORIGIN)


def _observed_at(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _safe_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unavailable"


def _base_receipt(
    *, source_repo: Path, runtime_repo: Path, revision: str, write: bool, now: datetime | None
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "action": "denied",
        "state": "checking",
        "stage": "preflight",
        "host": _safe_hostname(),
        "observed_at": _observed_at(now),
        "source_repo": None,
        "runtime_repo": None,
        "origin": None,
        "stored_origin_before": None,
        "stored_origin_after": None,
        "origin_migration_required": None,
        "canonical_repository": _canonical_origin_identity(),
        "checkout_mode": None,
        "checkout_ref": None,
        "before_revision": None,
        "target_revision": revision if FULL_SHA_RE.fullmatch(revision) else None,
        "after_revision": None,
        "recovery_ref": None,
        "remote_main_revision": None,
        "changed": None,
        "update_mode": None,
        "mutation_started": False,
        "receipt_refresh_failed": False,
        "write_requested": write,
    }


def _sanitized_git_env() -> dict[str, str]:
    """Return a Git environment without caller-selected config or TLS overrides."""

    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return {
        "HOME": str(account_home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }


def _canonical_network_git_env() -> dict[str, str]:
    """Add only the pinned Brian-owned GitHub credential for canonical HTTPS."""

    env = _sanitized_git_env()
    if not CANONICAL_ORIGIN.startswith("https://github.com/"):
        return env
    if not GH_EXECUTABLE.is_file() or not os.access(GH_EXECUTABLE, os.X_OK):
        raise RuntimeUpdateError("canonical GitHub credential helper is unavailable")
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    token_result = subprocess.run(
        [str(GH_EXECUTABLE), "auth", "token", "--hostname", "github.com", "--user", "BrianMills2718"],
        check=False,
        capture_output=True,
        text=True,
        env={
            "HOME": str(account_home),
            "GH_CONFIG_DIR": str(account_home / ".config" / "gh"),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        },
    )
    token = token_result.stdout.strip()
    if token_result.returncode != 0 or not token:
        raise RuntimeUpdateError("canonical BrianMills2718 GitHub credential is unavailable")
    authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env.update(
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="http.https://github.com/.extraHeader",
        GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {authorization}",
    )
    return env


def _deny(receipt: dict[str, Any], error: Exception) -> RuntimeUpdateError:
    receipt.update(
        action="partial_failure" if receipt["mutation_started"] else "denied",
        state="failed",
        error={
            "type": "RuntimeUpdateError",
            "code": "runtime_update_failed",
            "message": "Runtime update failed at the recorded stage; raw error details are omitted.",
        },
    )
    return RuntimeUpdateError(str(error), receipt=receipt.copy())


def _refresh_failure_state(runtime_repo: Path, receipt: dict[str, Any]) -> None:
    receipt.update(
        after_revision=None,
        recovery_ref_retained=None,
        receipt_refresh_failed=False,
    )
    if receipt["before_revision"] is None:
        return
    try:
        head = _run(runtime_repo, "rev-parse", "HEAD", check=False)
        if head.returncode == 0 and FULL_SHA_RE.fullmatch(head.stdout.strip()):
            receipt["after_revision"] = head.stdout.strip()
        else:
            receipt["receipt_refresh_failed"] = True
    except (RuntimeUpdateError, OSError, subprocess.SubprocessError):
        receipt["receipt_refresh_failed"] = True
    recovery_ref = receipt["recovery_ref"]
    if recovery_ref:
        try:
            retained = _direct_recovery_ref_commit(runtime_repo, recovery_ref)
            receipt["recovery_ref_retained"] = retained == receipt["before_revision"]
        except (RuntimeUpdateError, OSError, subprocess.SubprocessError):
            receipt["receipt_refresh_failed"] = True


def _assert_repo(path: Path, label: str) -> Path:
    if not path.is_dir() or _run(path, "rev-parse", "--is-inside-work-tree", check=False).stdout.strip() != "true":
        raise RuntimeUpdateError(f"{label} is not a Git worktree: {path}")
    try:
        top = Path(_output(path, "rev-parse", "--show-toplevel")).resolve()
    except RuntimeError as exc:
        raise RuntimeUpdateError(f"{label} path cannot be resolved") from exc
    if top != path:
        raise RuntimeUpdateError(f"{label} must be the exact Git worktree root: {path}")
    common = Path(_output(path, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = path / common
    try:
        return common.resolve()
    except RuntimeError as exc:
        raise RuntimeUpdateError(f"{label} Git directory cannot be resolved") from exc


def _assert_runtime_path_not_symlinked(runtime_repo: Path) -> None:
    default_runtime = _default_runtime_repo()
    if runtime_repo == default_runtime:
        components = [
            default_runtime.parents[1],
            default_runtime.parent,
            default_runtime,
        ]
    else:
        # Test/profile seam: the exact runtime itself remains non-symlinkable.
        components = [runtime_repo]
    if any(path.is_symlink() for path in components):
        raise RuntimeUpdateError("installed runtime path must not contain symlinks")


def _assert_safe_runtime_local_config(repo: Path) -> None:
    """Reject every unneeded local key that could alter Git's network boundary."""

    result = _run(repo, "config", "--includes", "--local", "--name-only", "--list")
    observed = {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}
    unsupported = sorted(
        key
        for key in observed - ALLOWED_RUNTIME_CONFIG_KEYS
        if not RECOVERY_CONFIG_RE.fullmatch(key)
    )
    if unsupported:
        raise RuntimeUpdateError(
            "installed runtime has unsupported local Git configuration: " + ", ".join(unsupported)
        )


def _assert_clean_runtime(runtime_repo: Path) -> str:
    dirty = _output(runtime_repo, "status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise RuntimeUpdateError("installed runtime is dirty; preserve or remove its changes before update")
    branch_result = _run(runtime_repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "detached"
    if branch not in {"main", "detached"}:
        raise RuntimeUpdateError(f"installed runtime must be on main, found {branch!r}")
    return branch


def _checkout_ref(runtime_repo: Path, checkout_mode: str) -> str | None:
    if checkout_mode == "detached":
        return None
    checkout_ref = _output(runtime_repo, "symbolic-ref", "HEAD")
    if checkout_ref != "refs/heads/main":
        raise RuntimeUpdateError("installed runtime main checkout does not resolve to refs/heads/main")
    return checkout_ref


@contextmanager
def _exclusive_runtime_lock(runtime_repo: Path):
    lock_path = runtime_repo.parent / ".enforced-planning-runtime-update.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or metadata.st_mode & 0o077
        ):
            raise RuntimeUpdateError("runtime updater lock is not a safe owner-controlled regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _validate_revision(source_repo: Path, revision: str) -> None:
    if not FULL_SHA_RE.fullmatch(revision):
        raise RuntimeUpdateError("--revision must be one full lowercase 40-character commit SHA")
    resolved = _output(source_repo, "rev-parse", f"{revision}^{{commit}}")
    if resolved != revision:
        raise RuntimeUpdateError(f"source revision did not resolve exactly: {revision}")


def _remote_main_revision() -> str:
    with tempfile.TemporaryDirectory(prefix="codex-runtime-ls-remote-") as directory:
        result = subprocess.run(
            [str(GIT_EXECUTABLE), "ls-remote", CANONICAL_ORIGIN, "refs/heads/main"],
            check=False,
            capture_output=True,
            text=True,
            cwd=directory,
            env={**_canonical_network_git_env(), "GIT_OPTIONAL_LOCKS": "0"},
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


def _fetch_canonical_revision_into_quarantine(revision: str) -> tempfile.TemporaryDirectory[str]:
    """Fetch canonical HTTPS into a fresh bare repo isolated from caller config."""

    temporary = tempfile.TemporaryDirectory(prefix="codex-runtime-fetch-")
    quarantine = Path(temporary.name) / "quarantine.git"
    init = subprocess.run(
        [str(GIT_EXECUTABLE), "init", "--bare", str(quarantine)],
        check=False,
        capture_output=True,
        text=True,
        cwd=temporary.name,
        env=_sanitized_git_env(),
    )
    if init.returncode != 0:
        temporary.cleanup()
        raise RuntimeUpdateError("cannot initialize isolated canonical fetch quarantine")
    try:
        _run(
            quarantine,
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            CANONICAL_ORIGIN,
            revision,
            mutating=True,
            network_auth=True,
        )
        _validate_revision(quarantine, revision)
    except Exception:
        temporary.cleanup()
        raise
    return temporary


def _recovery_ref(before: str, now: datetime) -> str:
    stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{RECOVERY_NAMESPACE}/{stamp}-{before[:12]}"


def _recovery_key(recovery_ref: str) -> str:
    prefix = f"{RECOVERY_NAMESPACE}/"
    if not recovery_ref.startswith(prefix):
        raise RuntimeUpdateError("rollback ref is outside the updater recovery namespace")
    raw_key = recovery_ref.removeprefix(prefix)
    if not RECOVERY_REF_KEY_RE.fullmatch(raw_key):
        raise RuntimeUpdateError("rollback ref does not have a structurally valid recovery identity")
    return raw_key.lower()


def _recovery_config_key(recovery_ref: str, field: str) -> str:
    return f"{RECOVERY_CONFIG_PREFIX}.{_recovery_key(recovery_ref)}.{field}"


def _write_recovery_metadata(runtime_repo: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    record = {**payload, "recordSha256": hashlib.sha256(encoded).hexdigest()}
    _run(
        runtime_repo,
        "config",
        "--local",
        _recovery_config_key(payload["recoveryRef"], "record"),
        json.dumps(record, sort_keys=True, separators=(",", ":")),
        mutating=True,
    )


def _record_recovery_metadata(
    runtime_repo: Path,
    *,
    recovery_ref: str,
    before: str,
    target: str,
    prior_origin: str,
    checkout_mode: str,
    checkout_ref: str | None,
) -> None:
    payload = {
        "schemaVersion": "1.0",
        "recoveryRef": recovery_ref,
        "beforeRevision": before,
        "targetRevision": target,
        "priorOrigin": prior_origin,
        "checkoutMode": checkout_mode,
        "checkoutRef": checkout_ref,
        "state": "active",
    }
    _write_recovery_metadata(runtime_repo, payload)


def _recovery_metadata_records(runtime_repo: Path, recovery_ref: str) -> list[str]:
    records = _run(
        runtime_repo,
        "config",
        "--local",
        "--get-all",
        _recovery_config_key(recovery_ref, "record"),
        check=False,
    )
    if records.returncode == 1:
        return []
    if records.returncode != 0:
        raise RuntimeUpdateError("rollback metadata could not be classified safely")
    return records.stdout.splitlines()


def _load_recovery_metadata(runtime_repo: Path, recovery_ref: str) -> dict[str, Any]:
    values_raw = _recovery_metadata_records(runtime_repo, recovery_ref)
    if len(values_raw) != 1:
        raise RuntimeUpdateError("rollback metadata must contain exactly one recovery record")
    raw = values_raw[0]
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeUpdateError("rollback metadata is not valid JSON") from exc
    expected_fields = {
        "schemaVersion",
        "recoveryRef",
        "beforeRevision",
        "targetRevision",
        "priorOrigin",
        "checkoutMode",
        "checkoutRef",
        "state",
        "recordSha256",
    }
    if not isinstance(values, dict) or set(values) != expected_fields:
        raise RuntimeUpdateError("rollback metadata does not match the exact record contract")
    string_fields = expected_fields - {"checkoutRef"}
    if not all(isinstance(values[field], str) for field in string_fields) or not (
        values["checkoutRef"] is None or isinstance(values["checkoutRef"], str)
    ):
        raise RuntimeUpdateError("rollback metadata contains invalid field types")
    if values["recoveryRef"] != recovery_ref:
        raise RuntimeUpdateError("rollback metadata does not match the requested recovery ref")
    if values["schemaVersion"] != "1.0":
        raise RuntimeUpdateError("rollback metadata has an unsupported schema version")
    if not FULL_SHA_RE.fullmatch(values["beforeRevision"]) or not FULL_SHA_RE.fullmatch(
        values["targetRevision"]
    ):
        raise RuntimeUpdateError("rollback metadata contains an invalid revision identity")
    if values["priorOrigin"] not in {CANONICAL_ORIGIN, LEGACY_RUNTIME_ORIGIN}:
        raise RuntimeUpdateError("rollback metadata contains an unsupported prior origin")
    if values["checkoutMode"] not in {"main", "detached"}:
        raise RuntimeUpdateError("rollback metadata contains an unsupported checkout mode")
    expected_checkout_ref = "refs/heads/main" if values["checkoutMode"] == "main" else None
    if values["checkoutRef"] != expected_checkout_ref:
        raise RuntimeUpdateError("rollback metadata checkout ref does not match its mode")
    if values["state"] not in {"active", "consumed"}:
        raise RuntimeUpdateError("rollback metadata contains an unsupported lifecycle state")
    key = _recovery_key(recovery_ref)
    if not key.endswith(f"-{values['beforeRevision'][:12]}"):
        raise RuntimeUpdateError("rollback ref identity is not bound to its recorded commit")
    payload = {field: values[field] for field in expected_fields - {"recordSha256"}}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if values["recordSha256"] != hashlib.sha256(encoded).hexdigest():
        raise RuntimeUpdateError("rollback metadata digest does not match its record")
    return values


def _mark_recovery_consumed(runtime_repo: Path, metadata: dict[str, Any]) -> None:
    payload = {key: value for key, value in metadata.items() if key != "recordSha256"}
    payload["state"] = "consumed"
    _write_recovery_metadata(runtime_repo, payload)


def _direct_recovery_ref_commit(runtime_repo: Path, recovery_ref: str) -> str | None:
    symbolic = _run(runtime_repo, "symbolic-ref", "--quiet", recovery_ref, check=False)
    if symbolic.returncode == 0:
        raise RuntimeUpdateError("rollback recovery ref must be a direct ref")
    resolved = _run(
        runtime_repo,
        "for-each-ref",
        "--format=%(objectname)",
        recovery_ref,
        check=False,
    )
    if resolved.returncode != 0:
        raise RuntimeUpdateError("rollback recovery ref could not be classified safely")
    rows = [line for line in resolved.stdout.splitlines() if line]
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeUpdateError("rollback recovery ref did not resolve to exactly one object")
    revision = rows[0]
    if not FULL_SHA_RE.fullmatch(revision):
        raise RuntimeUpdateError("rollback recovery ref does not resolve to one exact commit")
    object_type = _output(runtime_repo, "cat-file", "-t", revision)
    if object_type != "commit":
        raise RuntimeUpdateError("rollback recovery ref must point directly to a commit")
    return revision


def _update_runtime_under_lock(
    *,
    source_repo: Path,
    runtime_repo: Path,
    revision: str,
    write: bool,
    allow_detached_replacement: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate and optionally fast-forward one exact installed runtime clone."""

    source_repo = Path(os.path.abspath(source_repo.expanduser()))
    runtime_repo = Path(os.path.abspath(runtime_repo.expanduser()))
    receipt = _base_receipt(
        source_repo=source_repo,
        runtime_repo=runtime_repo,
        revision=revision,
        write=write,
        now=now,
    )
    try:
        try:
            source_repo = source_repo.resolve()
        except RuntimeError as exc:
            raise RuntimeUpdateError("source repository path cannot be resolved") from exc
        expected_runtime = Path(os.path.abspath(_canonical_runtime_repo().expanduser()))
        if runtime_repo != expected_runtime:
            raise RuntimeUpdateError(
                f"installed runtime path must be exactly {expected_runtime}, found {runtime_repo}"
            )
        _assert_runtime_path_not_symlinked(runtime_repo)
        try:
            runtime_repo = runtime_repo.resolve()
        except RuntimeError as exc:
            raise RuntimeUpdateError("installed runtime path cannot be resolved") from exc
        receipt["runtime_repo"] = str(runtime_repo)
        source_common_dir = _assert_repo(source_repo, "source repository")
        receipt["source_repo"] = str(source_repo)
        runtime_common_dir = _assert_repo(runtime_repo, "installed runtime")
        runtime_git_dir = runtime_repo / ".git"
        if (
            not runtime_git_dir.is_dir()
            or runtime_git_dir.is_symlink()
            or runtime_common_dir != runtime_git_dir.resolve()
        ):
            raise RuntimeUpdateError("installed runtime must be a standalone clone, not a linked worktree")
        if source_common_dir == runtime_common_dir:
            raise RuntimeUpdateError("source repository and installed runtime must be distinct clones")
        _validate_revision(source_repo, revision)
        receipt["target_revision"] = revision
        _assert_safe_runtime_local_config(runtime_repo)
        checkout_mode = _assert_clean_runtime(runtime_repo)
        checkout_ref = _checkout_ref(runtime_repo, checkout_mode)
        receipt["checkout_mode"] = checkout_mode
        receipt["checkout_ref"] = checkout_ref
        runtime_origin = _output(runtime_repo, "config", "--local", "--get", "remote.origin.url")
        expected_origin = _canonical_origin_identity()
        if runtime_origin == CANONICAL_ORIGIN:
            stored_origin_state = "canonical_https"
            origin_migration_required = False
        elif runtime_origin == LEGACY_RUNTIME_ORIGIN:
            stored_origin_state = "legacy_github_personal_alias"
            origin_migration_required = True
        else:
            raise RuntimeUpdateError("installed runtime is not the canonical Enforced Planning origin")
        receipt.update(
            origin=expected_origin,
            stored_origin_before=stored_origin_state,
            stored_origin_after=stored_origin_state,
            origin_migration_required=origin_migration_required,
        )

        before = _output(runtime_repo, "rev-parse", "HEAD")
        receipt.update(
            before_revision=before,
            after_revision=before,
            changed=before != revision or origin_migration_required,
        )
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
        if before == revision and origin_migration_required:
            receipt["update_mode"] = "origin_migration"
        else:
            receipt["update_mode"] = "fast_forward" if fast_forward else "detached_replacement"
        if not fast_forward and not detached_replacement:
            raise RuntimeUpdateError(
                f"installed runtime {before} cannot fast-forward to canonical revision {revision}; "
                "an explicit detached replacement with a recovery ref is required"
            )

        if not write or (before == revision and not origin_migration_required):
            receipt.update(
                action="current" if not receipt["changed"] else "would_update",
                state="succeeded",
                stage="complete",
            )
            return receipt

        recovery_ref = _recovery_ref(before, now or datetime.now(UTC))
        receipt["stage"] = "create_recovery_ref"
        receipt["recovery_ref"] = recovery_ref
        retained = _direct_recovery_ref_commit(runtime_repo, recovery_ref)
        existing_records = _recovery_metadata_records(runtime_repo, recovery_ref)
        if len(existing_records) > 1:
            raise RuntimeUpdateError("recovery identity has duplicate metadata records")
        expected_metadata = {
            "schemaVersion": "1.0",
            "recoveryRef": recovery_ref,
            "beforeRevision": before,
            "targetRevision": revision,
            "priorOrigin": runtime_origin,
            "checkoutMode": checkout_mode,
            "checkoutRef": checkout_ref,
            "state": "active",
        }
        if existing_records:
            recorded_metadata = _load_recovery_metadata(runtime_repo, recovery_ref)
            observed_payload = {
                key: value for key, value in recorded_metadata.items() if key != "recordSha256"
            }
            if observed_payload != expected_metadata:
                raise RuntimeUpdateError("recovery identity has stale or mismatched metadata")
            receipt["recovery_metadata_recorded"] = True
            receipt["mutation_started"] = True
        else:
            if retained is not None:
                raise RuntimeUpdateError("recovery ref exists without coherent metadata")
            receipt["stage"] = "record_recovery"
            receipt["mutation_started"] = True
            _record_recovery_metadata(
                runtime_repo,
                recovery_ref=recovery_ref,
                before=before,
                target=revision,
                prior_origin=runtime_origin,
                checkout_mode=checkout_mode,
                checkout_ref=checkout_ref,
            )
            recorded_metadata = _load_recovery_metadata(runtime_repo, recovery_ref)
            observed_payload = {
                key: value for key, value in recorded_metadata.items() if key != "recordSha256"
            }
            if observed_payload != expected_metadata:
                raise RuntimeUpdateError("recovery record did not enter the exact active state")
            receipt["recovery_metadata_recorded"] = True
        if retained not in {None, before}:
            raise RuntimeUpdateError("recovery ref does not match its coherent metadata")
        if before != revision:
            receipt["stage"] = "fetch_target"
            receipt["mutation_started"] = True
            _assert_safe_runtime_local_config(runtime_repo)
            quarantine = _fetch_canonical_revision_into_quarantine(revision)
            try:
                _run(
                    runtime_repo,
                    "fetch",
                    "--no-tags",
                    "--no-write-fetch-head",
                    str(Path(quarantine.name) / "quarantine.git"),
                    revision,
                    mutating=True,
                )
                _validate_revision(runtime_repo, revision)
            finally:
                quarantine.cleanup()
        if retained is None:
            receipt["stage"] = "create_recovery_ref"
            receipt["mutation_started"] = True
            _run(
                runtime_repo,
                "update-ref",
                "--no-deref",
                recovery_ref,
                before,
                ZERO_OID,
                mutating=True,
            )
        if _direct_recovery_ref_commit(runtime_repo, recovery_ref) != before:
            raise RuntimeUpdateError("created recovery ref does not retain the exact prior commit")
        # The recovery ref deliberately remains and is reported if mutation fails.
        receipt["stage"] = "apply_update"
        if before != revision:
            if fast_forward:
                _run(runtime_repo, "merge", "--ff-only", revision, mutating=True)
            else:
                _run(runtime_repo, "checkout", "--detach", revision, mutating=True)
        if origin_migration_required:
            receipt["stage"] = "migrate_origin"
            _run(runtime_repo, "remote", "set-url", "origin", CANONICAL_ORIGIN, mutating=True)
            receipt["stored_origin_after"] = "canonical_https"

        receipt["stage"] = "verify"
        after = _output(runtime_repo, "rev-parse", "HEAD")
        observed_checkout_mode = _assert_clean_runtime(runtime_repo)
        observed_checkout_ref = _checkout_ref(runtime_repo, observed_checkout_mode)
        retained = _direct_recovery_ref_commit(runtime_repo, recovery_ref)
        stored_origin_after = _output(runtime_repo, "config", "--local", "--get", "remote.origin.url")
        if (
            after != revision
            or retained != before
            or stored_origin_after != CANONICAL_ORIGIN
            or observed_checkout_mode != checkout_mode
            or observed_checkout_ref != checkout_ref
        ):
            raise RuntimeUpdateError(
                "post-update revision, origin, checkout, or recovery-ref verification failed"
            )
        receipt.update(action="updated", state="succeeded", stage="complete", after_revision=after)
        return receipt
    except (RuntimeUpdateError, OSError, subprocess.SubprocessError) as exc:
        _refresh_failure_state(runtime_repo, receipt)
        raise _deny(receipt, exc) from exc


def update_runtime(
    *,
    source_repo: Path,
    runtime_repo: Path,
    revision: str,
    write: bool,
    allow_detached_replacement: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Serialize and revalidate one exact installed-runtime update."""

    normalized_runtime = Path(os.path.abspath(runtime_repo.expanduser()))
    expected_runtime = Path(os.path.abspath(_canonical_runtime_repo().expanduser()))
    if normalized_runtime != expected_runtime:
        return _update_runtime_under_lock(
            source_repo=source_repo,
            runtime_repo=runtime_repo,
            revision=revision,
            write=write,
            allow_detached_replacement=allow_detached_replacement,
            now=now,
        )
    try:
        with _exclusive_runtime_lock(normalized_runtime):
            return _update_runtime_under_lock(
                source_repo=source_repo,
                runtime_repo=runtime_repo,
                revision=revision,
                write=write,
                allow_detached_replacement=allow_detached_replacement,
                now=now,
            )
    except (RuntimeUpdateError, OSError) as exc:
        if isinstance(exc, RuntimeUpdateError) and exc.receipt is not None:
            raise
        receipt = _base_receipt(
            source_repo=Path(source_repo),
            runtime_repo=normalized_runtime,
            revision=revision,
            write=write,
            now=now,
        )
        raise _deny(receipt, exc) from exc


def _rollback_receipt(*, write: bool, now: datetime | None) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "rollback",
        "action": "denied",
        "state": "checking",
        "stage": "preflight",
        "host": _safe_hostname(),
        "observed_at": _observed_at(now),
        "runtime_repo": None,
        "recovery_ref": None,
        "before_revision": None,
        "target_revision": None,
        "after_revision": None,
        "stored_origin_before": None,
        "stored_origin_after": None,
        "checkout_mode": None,
        "checkout_ref": None,
        "recovery_ref_consumed": None,
        "recovery_record_state": None,
        "mutation_started": False,
        "receipt_refresh_failed": False,
        "write_requested": write,
    }


def _origin_label(origin: str) -> str | None:
    if origin == CANONICAL_ORIGIN:
        return "canonical_https"
    if origin == LEGACY_RUNTIME_ORIGIN:
        return "legacy_github_personal_alias"
    return None


def _refresh_rollback_failure_state(
    runtime_repo: Path,
    recovery_ref: str,
    receipt: dict[str, Any],
) -> None:
    receipt.update(
        after_revision=None,
        stored_origin_after=None,
        recovery_ref_consumed=None,
        recovery_record_state=None,
        receipt_refresh_failed=False,
    )
    try:
        observed_head = _run(runtime_repo, "rev-parse", "HEAD", check=False)
        if observed_head.returncode == 0 and FULL_SHA_RE.fullmatch(observed_head.stdout.strip()):
            receipt["after_revision"] = observed_head.stdout.strip()
        else:
            receipt["receipt_refresh_failed"] = True
    except (RuntimeUpdateError, OSError, subprocess.SubprocessError):
        receipt["receipt_refresh_failed"] = True
    try:
        observed_origin = _run(
            runtime_repo,
            "config",
            "--local",
            "--get",
            "remote.origin.url",
            check=False,
        )
        if observed_origin.returncode == 0:
            label = _origin_label(observed_origin.stdout.strip())
            receipt["stored_origin_after"] = label
            if label is None:
                receipt["receipt_refresh_failed"] = True
        else:
            receipt["receipt_refresh_failed"] = True
    except (RuntimeUpdateError, OSError, subprocess.SubprocessError):
        receipt["receipt_refresh_failed"] = True
    try:
        receipt["recovery_ref_consumed"] = (
            _direct_recovery_ref_commit(runtime_repo, recovery_ref) is None
        )
    except (RuntimeUpdateError, OSError, subprocess.SubprocessError):
        receipt["receipt_refresh_failed"] = True
    try:
        receipt["recovery_record_state"] = _load_recovery_metadata(
            runtime_repo, recovery_ref
        )["state"]
    except (RuntimeUpdateError, OSError, subprocess.SubprocessError):
        receipt["receipt_refresh_failed"] = True


def _rollback_runtime_under_lock(
    *,
    runtime_repo: Path,
    recovery_ref: str,
    write: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate, resume, and optionally consume one structural recovery point."""

    runtime_repo = Path(os.path.abspath(runtime_repo.expanduser()))
    receipt = _rollback_receipt(write=write, now=now)
    try:
        _recovery_key(recovery_ref)
        receipt["recovery_ref"] = recovery_ref
        expected_runtime = Path(os.path.abspath(_canonical_runtime_repo().expanduser()))
        if runtime_repo != expected_runtime:
            raise RuntimeUpdateError(
                f"installed runtime path must be exactly {expected_runtime}, found {runtime_repo}"
            )
        _assert_runtime_path_not_symlinked(runtime_repo)
        try:
            runtime_repo = runtime_repo.resolve()
        except RuntimeError as exc:
            raise RuntimeUpdateError("installed runtime path cannot be resolved") from exc
        receipt["runtime_repo"] = str(runtime_repo)
        runtime_common_dir = _assert_repo(runtime_repo, "installed runtime")
        runtime_git_dir = runtime_repo / ".git"
        if (
            not runtime_git_dir.is_dir()
            or runtime_git_dir.is_symlink()
            or runtime_common_dir != runtime_git_dir.resolve()
        ):
            raise RuntimeUpdateError("installed runtime must be a standalone clone, not a linked worktree")
        _assert_safe_runtime_local_config(runtime_repo)
        checkout_mode = _assert_clean_runtime(runtime_repo)
        checkout_ref = _checkout_ref(runtime_repo, checkout_mode)
        metadata = _load_recovery_metadata(runtime_repo, recovery_ref)
        current = _output(runtime_repo, "rev-parse", "HEAD")
        retained = _direct_recovery_ref_commit(runtime_repo, recovery_ref)
        current_origin = _output(runtime_repo, "config", "--local", "--get", "remote.origin.url")
        prior_revision = metadata["beforeRevision"]
        target_revision = metadata["targetRevision"]
        prior_origin = metadata["priorOrigin"]
        record_state = metadata["state"]
        if (
            checkout_mode != metadata["checkoutMode"]
            or checkout_ref != metadata["checkoutRef"]
        ):
            raise RuntimeUpdateError("installed runtime checkout identity no longer matches the recovery record")
        fully_restored = current == prior_revision and current_origin == prior_origin
        if record_state == "active":
            if current not in {target_revision, prior_revision}:
                raise RuntimeUpdateError("installed runtime no longer matches the recovery transition")
            if retained != prior_revision and not (retained is None and fully_restored):
                raise RuntimeUpdateError("active recovery ref no longer matches its recorded commit")
            if current_origin not in {CANONICAL_ORIGIN, prior_origin}:
                raise RuntimeUpdateError("installed runtime origin no longer matches the recovery record")
        elif not fully_restored or retained not in {prior_revision, None}:
            raise RuntimeUpdateError("consumed recovery record does not match a restored runtime")
        receipt.update(
            before_revision=current,
            target_revision=prior_revision,
            after_revision=current,
            checkout_mode=checkout_mode,
            checkout_ref=checkout_ref,
            stored_origin_before=_origin_label(current_origin),
            stored_origin_after=_origin_label(current_origin),
            recovery_ref_consumed=retained is None,
            recovery_record_state=record_state,
        )
        if not write:
            if record_state == "consumed" and retained is None:
                action = "already_rolled_back"
            elif record_state == "consumed" or fully_restored:
                action = "would_finalize_rollback"
            else:
                action = "would_rollback"
            receipt.update(
                action=action,
                state="succeeded",
                stage="complete",
            )
            return receipt

        initial_record_state = record_state
        if record_state == "consumed" and retained is None:
            receipt.update(action="already_rolled_back", state="succeeded", stage="complete")
            return receipt

        if record_state == "active" and retained is None and fully_restored:
            receipt["stage"] = "consume_record"
            receipt["mutation_started"] = True
            _mark_recovery_consumed(runtime_repo, metadata)
            consumed_metadata = _load_recovery_metadata(runtime_repo, recovery_ref)
            if consumed_metadata["state"] != "consumed":
                raise RuntimeUpdateError("recovery record did not enter the consumed state")
            receipt.update(
                action="already_rolled_back",
                state="succeeded",
                stage="complete",
                recovery_ref_consumed=True,
                recovery_record_state="consumed",
            )
            return receipt

        if record_state == "active" and current != prior_revision:
            receipt["stage"] = "restore_revision"
            receipt["mutation_started"] = True
            if checkout_mode == "main":
                _run(runtime_repo, "reset", "--hard", prior_revision, mutating=True)
            else:
                _run(runtime_repo, "checkout", "--detach", prior_revision, mutating=True)
            current = _output(runtime_repo, "rev-parse", "HEAD")
            receipt["after_revision"] = current
            if current != prior_revision:
                raise RuntimeUpdateError("rollback did not restore the recorded prior commit")
        if record_state == "active" and prior_origin != current_origin:
            receipt["stage"] = "restore_origin"
            receipt["mutation_started"] = True
            _run(runtime_repo, "remote", "set-url", "origin", prior_origin, mutating=True)
            current_origin = _output(runtime_repo, "config", "--local", "--get", "remote.origin.url")
            receipt["stored_origin_after"] = _origin_label(current_origin)
        receipt["stage"] = "verify"
        after = _output(runtime_repo, "rev-parse", "HEAD")
        observed_checkout_mode = _assert_clean_runtime(runtime_repo)
        observed_checkout_ref = _checkout_ref(runtime_repo, observed_checkout_mode)
        restored_origin = _output(runtime_repo, "config", "--local", "--get", "remote.origin.url")
        receipt["after_revision"] = after
        if (
            after != prior_revision
            or restored_origin != prior_origin
            or observed_checkout_mode != checkout_mode
            or observed_checkout_ref != checkout_ref
        ):
            raise RuntimeUpdateError("post-rollback revision, origin, or checkout verification failed")
        if record_state == "active":
            receipt["stage"] = "consume_record"
            receipt["mutation_started"] = True
            _mark_recovery_consumed(runtime_repo, metadata)
            consumed_metadata = _load_recovery_metadata(runtime_repo, recovery_ref)
            if consumed_metadata["state"] != "consumed":
                raise RuntimeUpdateError("recovery record did not enter the consumed state")
            record_state = "consumed"
            receipt["recovery_record_state"] = record_state

        receipt["stage"] = "consume_recovery_ref"
        retained = _direct_recovery_ref_commit(runtime_repo, recovery_ref)
        if retained is not None:
            if retained != prior_revision:
                raise RuntimeUpdateError("recovery ref changed before consumption")
            receipt["mutation_started"] = True
            _run(
                runtime_repo,
                "update-ref",
                "--no-deref",
                "-d",
                recovery_ref,
                prior_revision,
                mutating=True,
            )
            if _direct_recovery_ref_commit(runtime_repo, recovery_ref) is not None:
                raise RuntimeUpdateError("recovery ref remained after exact consumption")
        receipt["recovery_ref_consumed"] = True
        receipt.update(
            action="rolled_back" if initial_record_state == "active" else "finalized_rollback",
            state="succeeded",
            stage="complete",
            after_revision=after,
            stored_origin_after=_origin_label(restored_origin),
        )
        return receipt
    except (RuntimeUpdateError, OSError, subprocess.SubprocessError) as exc:
        if receipt["runtime_repo"] is not None:
            _refresh_rollback_failure_state(runtime_repo, recovery_ref, receipt)
        raise _deny(receipt, exc) from exc


def rollback_runtime(
    *,
    runtime_repo: Path,
    recovery_ref: str,
    write: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Serialize and revalidate one exact installed-runtime rollback."""

    normalized_runtime = Path(os.path.abspath(runtime_repo.expanduser()))
    expected_runtime = Path(os.path.abspath(_canonical_runtime_repo().expanduser()))
    if normalized_runtime != expected_runtime:
        return _rollback_runtime_under_lock(
            runtime_repo=runtime_repo,
            recovery_ref=recovery_ref,
            write=write,
            now=now,
        )
    try:
        with _exclusive_runtime_lock(normalized_runtime):
            return _rollback_runtime_under_lock(
                runtime_repo=runtime_repo,
                recovery_ref=recovery_ref,
                write=write,
                now=now,
            )
    except (RuntimeUpdateError, OSError) as exc:
        if isinstance(exc, RuntimeUpdateError) and exc.receipt is not None:
            raise
        receipt = _rollback_receipt(write=write, now=now)
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
    parser.add_argument("--revision", help="exact full canonical origin/main commit SHA")
    parser.add_argument(
        "--rollback-ref",
        help="consume one structurally coherent recovery ref and restore its recorded state",
    )
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
        if args.rollback_ref:
            if args.revision or args.allow_detached_replacement:
                raise RuntimeUpdateError(
                    "--rollback-ref cannot be combined with --revision or --allow-detached-replacement"
                )
            payload = rollback_runtime(
                runtime_repo=args.runtime_repo,
                recovery_ref=args.rollback_ref,
                write=args.write,
            )
        else:
            if not args.revision:
                raise RuntimeUpdateError("--revision is required unless --rollback-ref is used")
            payload = update_runtime(
                source_repo=args.source_repo,
                runtime_repo=args.runtime_repo,
                revision=args.revision,
                write=args.write,
                allow_detached_replacement=args.allow_detached_replacement,
            )
    except (RuntimeUpdateError, OSError, subprocess.SubprocessError) as exc:
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
