from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from enforced_planning.surface_runtime import (
    SurfaceRuntimeError,
    assert_no_live_leases_for_worktree,
    audit_surface,
    list_leases,
    start_surface,
    stop_surface,
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [*args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _repo(tmp_path: Path, *, wrong_identity: bool = False) -> tuple[Path, int, int]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main")
    _run(repo, "git", "config", "user.email", "test@example.com")
    _run(repo, "git", "config", "user.name", "Test")
    frontend_port = _free_port()
    backend_port = _free_port()
    preview_frontend = _free_port()
    preview_backend = _free_port()
    (repo / "ui").mkdir()
    identity_source = "'wrong'" if wrong_identity else "os.environ['SURFACE_SOURCE_REVISION']"
    (repo / "fake_surface.py").write_text(
        """
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = {
            "schema_version": "canonical-surface-identity/v1",
            "surface_id": os.environ["SURFACE_ID"],
            "mode": os.environ["SURFACE_MODE"],
            "source_revision": SOURCE_REVISION,
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass

ThreadingHTTPServer(("127.0.0.1", int(os.environ["API_PORT"])), Handler).serve_forever()
""".replace("SOURCE_REVISION", identity_source),
        encoding="utf-8",
    )
    (repo / "ui" / "registry.yaml").write_text(
        f"""schema_version: ui-registry/v1
project_id: test-project
ui_status: active
surfaces:
  - id: test-ui
    lifecycle: canonical
    source_path: ui-src
    runtime:
      integration_ref: main
      canonical:
        command: [{json.dumps(sys.executable)}, fake_surface.py]
        frontend_port: {frontend_port}
        backend_port: {backend_port}
        frontend_url: http://127.0.0.1:{{frontend_port}}
        identity_url: http://127.0.0.1:{{backend_port}}/api/runtime/identity
        readiness_timeout_seconds: 1
      preview:
        command: [{json.dumps(sys.executable)}, fake_surface.py]
        frontend_port_range: [{preview_frontend}, {preview_frontend}]
        backend_port_range: [{preview_backend}, {preview_backend}]
""",
        encoding="utf-8",
    )
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-m", "fixture")
    return repo, frontend_port, backend_port


def test_canonical_surface_round_trip_uses_exact_lease(tmp_path: Path) -> None:
    repo, frontend_port, backend_port = _repo(tmp_path)
    state = tmp_path / "state"

    lease = start_surface(repo, "test-ui", state_root=state)
    try:
        assert lease["status"] == "ready"
        assert lease["mode"] == "canonical"
        assert lease["frontend_port"] == frontend_port
        assert lease["backend_port"] == backend_port
        assert lease["identity"]["source_revision"] == lease["source_revision"]
        assert list_leases(state_root=state)[0]["status"] == "live"
        assert audit_surface(repo, "test-ui", state_root=state, require_running=True)["ok"]
        with pytest.raises(SurfaceRuntimeError, match="live surface leases"):
            assert_no_live_leases_for_worktree(repo, state_root=state)
    finally:
        stopped = stop_surface(repo, "test-ui", state_root=state)

    assert stopped["action"] == "stopped"
    assert list_leases(state_root=state) == []


def test_canonical_surface_rejects_dirty_or_wrong_lineage(tmp_path: Path) -> None:
    repo, _, _ = _repo(tmp_path)
    state = tmp_path / "state"
    (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(SurfaceRuntimeError, match="clean checkout"):
        start_surface(repo, "test-ui", state_root=state)
    (repo / "dirty.txt").unlink()
    _run(repo, "git", "switch", "-c", "feature")
    with pytest.raises(SurfaceRuntimeError, match="requires branch 'main'"):
        start_surface(repo, "test-ui", state_root=state)


def test_preview_uses_noncanonical_ports_and_independent_lease(tmp_path: Path) -> None:
    repo, frontend_port, backend_port = _repo(tmp_path)
    state = tmp_path / "state"
    _run(repo, "git", "switch", "-c", "feature")
    lease = start_surface(repo, "test-ui", mode="preview", state_root=state)
    try:
        assert lease["mode"] == "preview"
        assert lease["frontend_port"] != frontend_port
        assert lease["backend_port"] != backend_port
        assert lease["lease_id"].startswith("test-ui-preview-")
    finally:
        stop_surface(repo, "test-ui", lease_id=lease["lease_id"], state_root=state)


def test_identity_mismatch_fails_and_cleans_process_and_lease(tmp_path: Path) -> None:
    repo, _, _ = _repo(tmp_path, wrong_identity=True)
    state = tmp_path / "state"
    with pytest.raises(SurfaceRuntimeError, match="runtime identity mismatch"):
        start_surface(repo, "test-ui", state_root=state)
    assert list_leases(state_root=state) == []


def test_occupied_canonical_port_is_never_killed(tmp_path: Path) -> None:
    repo, frontend_port, _ = _repo(tmp_path)
    state = tmp_path / "state"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", frontend_port))
        listener.listen()
        with pytest.raises(SurfaceRuntimeError, match="unleased ports are occupied"):
            start_surface(repo, "test-ui", state_root=state)
