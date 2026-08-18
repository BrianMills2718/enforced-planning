"""Revision-bound runtime leases for governed human-facing surfaces."""

from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import os
import re
import shlex
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


LEASE_SCHEMA = "canonical-surface-lease/v1"
IDENTITY_SCHEMA = "canonical-surface-identity/v1"
DEFAULT_STATE_ROOT = Path.home() / ".local" / "state" / "governed-surfaces"


class SurfaceRuntimeError(RuntimeError):
    """A surface declaration or runtime failed a deterministic precondition."""


@dataclasses.dataclass(frozen=True)
class RuntimeTarget:
    command: tuple[str, ...]
    frontend_port: int
    backend_port: int | None
    frontend_url: str
    identity_url: str
    readiness_timeout_seconds: float
    environment: dict[str, str]


@dataclasses.dataclass(frozen=True)
class SurfaceDefinition:
    project_id: str
    surface_id: str
    lifecycle: str
    source_path: str
    integration_ref: str
    canonical: RuntimeTarget
    preview: Mapping[str, Any]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "surface"


def _state_root(path: Path | None = None) -> Path:
    if path is not None:
        return path.expanduser().resolve()
    configured = os.environ.get("SURFACE_STATE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state).expanduser().resolve() / "governed-surfaces"
    return DEFAULT_STATE_ROOT


def _git(repo_root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise SurfaceRuntimeError(f"git {' '.join(args)} failed in {repo_root}: {detail}")
    return result.stdout.strip()


def _command(value: Any, *, field: str) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = tuple(shlex.split(value))
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        parts = tuple(value)
    else:
        raise SurfaceRuntimeError(f"{field} must be a command string or string list")
    if not parts:
        raise SurfaceRuntimeError(f"{field} must not be empty")
    return parts


def _port(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 < value < 65536:
        raise SurfaceRuntimeError(f"{field} must be an integer TCP port")
    return value


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SurfaceRuntimeError(f"{field} must be a mapping")
    return value


def _target(value: Any, *, field: str) -> RuntimeTarget:
    payload = _mapping(value, field=field)
    backend_value = payload.get("backend_port")
    environment = payload.get("environment", {})
    if not isinstance(environment, Mapping) or not all(
        isinstance(key, str) and isinstance(item, (str, int, float, bool))
        for key, item in environment.items()
    ):
        raise SurfaceRuntimeError(f"{field}.environment must contain scalar string keys and values")
    frontend_port = _port(payload.get("frontend_port"), field=f"{field}.frontend_port")
    return RuntimeTarget(
        command=_command(payload.get("command"), field=f"{field}.command"),
        frontend_port=frontend_port,
        backend_port=(
            _port(backend_value, field=f"{field}.backend_port") if backend_value is not None else None
        ),
        frontend_url=str(payload.get("frontend_url") or f"http://127.0.0.1:{frontend_port}"),
        identity_url=str(payload.get("identity_url") or ""),
        readiness_timeout_seconds=float(payload.get("readiness_timeout_seconds", 20)),
        environment={str(key): str(item) for key, item in environment.items()},
    )


def load_surface(repo_root: Path, surface_id: str) -> SurfaceDefinition:
    """Load one surface from the repository-owned UI registry."""
    repo_root = repo_root.expanduser().resolve()
    registry_path = repo_root / "ui" / "registry.yaml"
    try:
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SurfaceRuntimeError(f"Unable to load {registry_path}: {exc}") from exc
    registry = _mapping(payload, field="ui registry")
    project_id = registry.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise SurfaceRuntimeError("ui registry requires project_id")
    surfaces = registry.get("surfaces")
    if not isinstance(surfaces, list):
        raise SurfaceRuntimeError("ui registry surfaces must be a list")
    matches = [item for item in surfaces if isinstance(item, Mapping) and item.get("id") == surface_id]
    if len(matches) != 1:
        raise SurfaceRuntimeError(
            f"Expected exactly one surface {surface_id!r} in {registry_path}; found {len(matches)}"
        )
    item = matches[0]
    runtime = _mapping(item.get("runtime"), field=f"surface {surface_id}.runtime")
    integration_ref = runtime.get("integration_ref")
    if not isinstance(integration_ref, str) or not integration_ref.strip():
        raise SurfaceRuntimeError(f"surface {surface_id}.runtime.integration_ref is required")
    preview = _mapping(runtime.get("preview", {}), field=f"surface {surface_id}.runtime.preview")
    return SurfaceDefinition(
        project_id=project_id,
        surface_id=surface_id,
        lifecycle=str(item.get("lifecycle") or ""),
        source_path=str(item.get("source_path") or ""),
        integration_ref=integration_ref,
        canonical=_target(runtime.get("canonical"), field=f"surface {surface_id}.runtime.canonical"),
        preview=preview,
    )


def _process_start_token(pid: int) -> str | None:
    stat_path = Path("/proc") / str(pid) / "stat"
    try:
        stat = stat_path.read_text(encoding="utf-8")
        closing_parenthesis = stat.rfind(")")
        fields_after_command = stat[closing_parenthesis + 2 :].split()
        if (
            closing_parenthesis > 0
            and len(fields_after_command) >= 20
            and fields_after_command[0] != "Z"
        ):
            return f"proc:{fields_after_command[19]}"
    except OSError:
        pass
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        check=False,
        capture_output=True,
        text=True,
    )
    token = " ".join(result.stdout.split())
    return f"ps:{token}" if token else None


def _process_cwd(pid: int) -> str | None:
    proc_cwd = Path("/proc") / str(pid) / "cwd"
    try:
        return str(proc_cwd.resolve(strict=True))
    except OSError:
        return None


def _lease_live(lease: Mapping[str, Any]) -> bool:
    pid = lease.get("pid")
    token = lease.get("process_start")
    return isinstance(pid, int) and isinstance(token, str) and _process_start_token(pid) == token


def _project_state_dir(state_root: Path, project_id: str) -> Path:
    return state_root / _safe_segment(project_id)


def _lease_path(state_root: Path, project_id: str, lease_id: str) -> Path:
    return _project_state_dir(state_root, project_id) / "leases" / f"{_safe_segment(lease_id)}.json"


def _log_path(state_root: Path, project_id: str, lease_id: str) -> Path:
    return _project_state_dir(state_root, project_id) / "logs" / f"{_safe_segment(lease_id)}.log"


@contextlib.contextmanager
def _project_lock(state_root: Path, project_id: str) -> Iterator[None]:
    lock_path = _project_state_dir(state_root, project_id) / ".lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_lease(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SurfaceRuntimeError(f"Unable to read lease {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != LEASE_SCHEMA:
        raise SurfaceRuntimeError(f"Unsupported lease at {path}")
    return payload


def _all_lease_paths(state_root: Path, project_id: str | None = None) -> list[Path]:
    roots = (
        [_project_state_dir(state_root, project_id)]
        if project_id is not None
        else [path for path in state_root.iterdir() if path.is_dir()] if state_root.exists() else []
    )
    return sorted(path for root in roots for path in (root / "leases").glob("*.json"))


def _port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


def _free_port(start: int, end: int, forbidden: set[int]) -> int:
    for port in range(start, end + 1):
        if port not in forbidden and _port_available(port):
            return port
    raise SurfaceRuntimeError(f"No free port in preview range {start}-{end}")


def _preview_range(preview: Mapping[str, Any], name: str, default: tuple[int, int]) -> tuple[int, int]:
    value = preview.get(name, list(default))
    if not isinstance(value, list) or len(value) != 2:
        raise SurfaceRuntimeError(f"runtime.preview.{name} must be [start, end]")
    start = _port(value[0], field=f"runtime.preview.{name}[0]")
    end = _port(value[1], field=f"runtime.preview.{name}[1]")
    if start > end:
        raise SurfaceRuntimeError(f"runtime.preview.{name} start must not exceed end")
    return start, end


def _format_url(value: str, *, frontend_port: int, backend_port: int | None) -> str:
    return value.format(frontend_port=frontend_port, backend_port=backend_port or "")


def _assert_canonical_lineage(repo_root: Path, surface: SurfaceDefinition) -> str:
    if surface.lifecycle != "canonical":
        raise SurfaceRuntimeError(f"surface {surface.surface_id} is not lifecycle=canonical")
    branch = _git(repo_root, "branch", "--show-current")
    expected_branch = surface.integration_ref.removeprefix("refs/heads/")
    if branch != expected_branch:
        raise SurfaceRuntimeError(
            f"canonical surface requires branch {expected_branch!r}; current branch is {branch!r}"
        )
    revision = _git(repo_root, "rev-parse", "HEAD")
    expected_revision = _git(repo_root, "rev-parse", surface.integration_ref)
    if revision != expected_revision:
        raise SurfaceRuntimeError(
            f"canonical checkout {revision} does not match {surface.integration_ref} at {expected_revision}"
        )
    dirty = _git(repo_root, "status", "--short")
    if dirty:
        raise SurfaceRuntimeError("canonical surface requires a clean checkout")
    return revision


def _identity(url: str, timeout: float = 1.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise SurfaceRuntimeError(f"identity endpoint unavailable at {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SurfaceRuntimeError(f"identity endpoint {url} did not return a JSON object")
    return payload


def _assert_identity(identity: Mapping[str, Any], lease: Mapping[str, Any]) -> None:
    expected = {
        "schema_version": IDENTITY_SCHEMA,
        "surface_id": lease["surface_id"],
        "mode": lease["mode"],
        "source_revision": lease["source_revision"],
    }
    mismatches = {
        key: {"expected": value, "observed": identity.get(key)}
        for key, value in expected.items()
        if identity.get(key) != value
    }
    if mismatches:
        raise SurfaceRuntimeError(f"runtime identity mismatch: {json.dumps(mismatches, sort_keys=True)}")


def _terminate_exact(lease: Mapping[str, Any], timeout_seconds: float = 5.0) -> None:
    if not _lease_live(lease):
        raise SurfaceRuntimeError(
            f"Refusing to signal PID {lease.get('pid')}: process start identity no longer matches the lease"
        )
    pid = int(lease["pid"])
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _lease_live(lease):
            return
        time.sleep(0.05)
    if _lease_live(lease):
        os.killpg(pid, signal.SIGKILL)


def _terminate_started_process(
    process: subprocess.Popen[bytes], timeout_seconds: float = 5.0
) -> None:
    """Clean the private process group created by this invocation."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=timeout_seconds)


def _runtime_target(
    surface: SurfaceDefinition,
    *,
    mode: str,
) -> tuple[RuntimeTarget, int, int | None]:
    if mode == "canonical":
        target = surface.canonical
        return target, target.frontend_port, target.backend_port
    if mode != "preview":
        raise SurfaceRuntimeError("mode must be canonical or preview")
    preview = surface.preview
    command = preview.get("command", list(surface.canonical.command))
    frontend_range = _preview_range(preview, "frontend_port_range", (18000, 18999))
    backend_range = _preview_range(preview, "backend_port_range", (19000, 19999))
    forbidden = {surface.canonical.frontend_port}
    if surface.canonical.backend_port is not None:
        forbidden.add(surface.canonical.backend_port)
    frontend_port = _free_port(*frontend_range, forbidden)
    forbidden.add(frontend_port)
    backend_port = (
        _free_port(*backend_range, forbidden) if surface.canonical.backend_port is not None else None
    )
    target = dataclasses.replace(surface.canonical, command=_command(command, field="runtime.preview.command"))
    return target, frontend_port, backend_port


def start_surface(
    repo_root: Path,
    surface_id: str,
    *,
    mode: str = "canonical",
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Start one exact surface and return its readiness-verified lease."""
    repo_root = repo_root.expanduser().resolve()
    state_root = _state_root(state_root)
    surface = load_surface(repo_root, surface_id)
    revision = (
        _assert_canonical_lineage(repo_root, surface)
        if mode == "canonical"
        else _git(repo_root, "rev-parse", "HEAD")
    )
    if mode == "preview" and _git(repo_root, "status", "--short"):
        raise SurfaceRuntimeError(
            "preview surface requires a clean checkout so its source revision identifies served content"
        )
    target, frontend_port, backend_port = _runtime_target(surface, mode=mode)
    lease_id = surface.surface_id if mode == "canonical" else f"{surface.surface_id}-preview-{uuid.uuid4().hex[:10]}"
    lease_path = _lease_path(state_root, surface.project_id, lease_id)
    with _project_lock(state_root, surface.project_id):
        if lease_path.exists():
            existing = _read_lease(lease_path)
            if _lease_live(existing):
                identity = _identity(str(existing["identity_url"]))
                _assert_identity(identity, existing)
                return {**existing, "status": "ready", "reused": True}
            lease_path.unlink()
        occupied = [port for port in (frontend_port, backend_port) if port and not _port_available(port)]
        if occupied:
            raise SurfaceRuntimeError(
                f"Refusing to start {mode} surface; unleased ports are occupied: {occupied}"
            )
        frontend_url = _format_url(
            target.frontend_url, frontend_port=frontend_port, backend_port=backend_port
        )
        identity_url = _format_url(
            target.identity_url, frontend_port=frontend_port, backend_port=backend_port
        )
        if not identity_url:
            raise SurfaceRuntimeError("runtime.canonical.identity_url is required")
        log_path = _log_path(state_root, surface.project_id, lease_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(target.environment)
        env.update(
            {
                "SURFACE_ID": surface.surface_id,
                "SURFACE_MODE": mode,
                "SURFACE_SOURCE_REVISION": revision,
                "UI_PORT": str(frontend_port),
                "VITE_SURFACE_ID": surface.surface_id,
                "VITE_SURFACE_MODE": mode,
                "VITE_SURFACE_REVISION": revision,
            }
        )
        if backend_port is not None:
            env["API_PORT"] = str(backend_port)
        with log_path.open("ab", buffering=0) as log_handle:
            process = subprocess.Popen(
                list(target.command),
                cwd=repo_root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        start_token = _process_start_token(process.pid)
        if start_token is None:
            _terminate_started_process(process)
            raise SurfaceRuntimeError("started process disappeared before its lease could be recorded")
        lease: dict[str, Any] = {
            "schema_version": LEASE_SCHEMA,
            "lease_id": lease_id,
            "project_id": surface.project_id,
            "surface_id": surface.surface_id,
            "mode": mode,
            "repo_root": str(Path(_git(repo_root, "rev-parse", "--show-toplevel")).resolve()),
            "git_common_dir": str(Path(_git(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()),
            "worktree_path": str(repo_root),
            "source_revision": revision,
            "branch": _git(repo_root, "branch", "--show-current"),
            "pid": process.pid,
            "process_start": start_token,
            "process_cwd": _process_cwd(process.pid) or str(repo_root),
            "command": list(target.command),
            "frontend_port": frontend_port,
            "backend_port": backend_port,
            "frontend_url": frontend_url,
            "identity_url": identity_url,
            "log_path": str(log_path),
            "started_at": _utc_now(),
        }
        _write_json(lease_path, lease)
    deadline = time.monotonic() + target.readiness_timeout_seconds
    last_error = "identity endpoint was not observed"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            last_error = "surface process exited before readiness"
            break
        try:
            identity = _identity(identity_url)
            _assert_identity(identity, lease)
            return {**lease, "status": "ready", "reused": False, "identity": identity}
        except SurfaceRuntimeError as exc:
            last_error = str(exc)
            time.sleep(0.1)
    with _project_lock(state_root, surface.project_id):
        _terminate_started_process(process)
        lease_path.unlink(missing_ok=True)
    raise SurfaceRuntimeError(
        f"surface failed readiness: {last_error}; inspect {log_path}"
    )


def list_leases(
    *, state_root: Path | None = None, project_id: str | None = None
) -> list[dict[str, Any]]:
    """Return every lease with freshly evaluated process state."""
    root = _state_root(state_root)
    rows: list[dict[str, Any]] = []
    for path in _all_lease_paths(root, project_id):
        lease = _read_lease(path)
        rows.append({**lease, "lease_path": str(path), "status": "live" if _lease_live(lease) else "stale"})
    return rows


def stop_surface(
    repo_root: Path,
    surface_id: str,
    *,
    lease_id: str | None = None,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Stop only the exact process represented by a selected lease."""
    surface = load_surface(repo_root.expanduser().resolve(), surface_id)
    root = _state_root(state_root)
    selected = lease_id or surface_id
    path = _lease_path(root, surface.project_id, selected)
    with _project_lock(root, surface.project_id):
        if not path.exists():
            raise SurfaceRuntimeError(f"No lease {selected!r} exists for project {surface.project_id}")
        lease = _read_lease(path)
        if lease.get("surface_id") != surface_id:
            raise SurfaceRuntimeError(f"Lease {selected!r} does not belong to surface {surface_id}")
        if _lease_live(lease):
            _terminate_exact(lease)
            action = "stopped"
        else:
            action = "pruned_stale"
        path.unlink()
    return {"lease_id": selected, "surface_id": surface_id, "action": action}


def audit_surface(
    repo_root: Path,
    surface_id: str,
    *,
    state_root: Path | None = None,
    require_running: bool = False,
) -> dict[str, Any]:
    """Compare repository authority, lease state, and served identity."""
    repo_root = repo_root.expanduser().resolve()
    surface = load_surface(repo_root, surface_id)
    leases = [row for row in list_leases(state_root=state_root, project_id=surface.project_id) if row["surface_id"] == surface_id]
    canonical = [row for row in leases if row["mode"] == "canonical" and row["status"] == "live"]
    findings: list[dict[str, Any]] = []
    if len(canonical) > 1:
        findings.append({"code": "competing_canonical_leases", "count": len(canonical)})
    if require_running and not canonical:
        findings.append({"code": "canonical_runtime_missing"})
    for lease in leases:
        if lease["status"] == "stale":
            findings.append({"code": "stale_lease", "lease_id": lease["lease_id"]})
            continue
        try:
            identity = _identity(lease["identity_url"])
            _assert_identity(identity, lease)
        except SurfaceRuntimeError as exc:
            findings.append(
                {"code": "runtime_identity_mismatch", "lease_id": lease["lease_id"], "detail": str(exc)}
            )
    return {
        "project_id": surface.project_id,
        "surface_id": surface.surface_id,
        "integration_ref": surface.integration_ref,
        "leases": leases,
        "findings": findings,
        "ok": not findings,
    }


def live_leases_for_worktree(
    worktree_path: Path, *, state_root: Path | None = None
) -> list[dict[str, Any]]:
    """Return live leases whose recorded cwd belongs to one worktree."""
    root = _state_root(state_root)
    target = worktree_path.expanduser().resolve()
    matches = []
    for lease in list_leases(state_root=root):
        if lease["status"] != "live":
            continue
        recorded = Path(str(lease.get("worktree_path") or lease.get("process_cwd") or "")).expanduser()
        try:
            resolved = recorded.resolve()
        except OSError:
            continue
        if resolved == target or target in resolved.parents:
            matches.append(lease)
    return matches


def assert_no_live_leases_for_worktree(
    worktree_path: Path, *, state_root: Path | None = None
) -> None:
    """Fail before worktree removal when a governed surface is still running."""
    matches = live_leases_for_worktree(worktree_path, state_root=state_root)
    if matches:
        detail = ", ".join(f"{item['surface_id']}:{item['lease_id']} pid={item['pid']}" for item in matches)
        raise SurfaceRuntimeError(
            f"Cannot remove worktree with live surface leases: {detail}. Stop them with surface-down first."
        )
