"""Focused performance-contract tests for repository closeout collection."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from scripts import coordination_hook


def test_repository_snapshot_collects_statuses_concurrently(monkeypatch, tmp_path: Path) -> None:
    repositories = tuple(tmp_path / f"repo-{index}" for index in range(8))
    active = 0
    max_active = 0
    lock = threading.Lock()

    monkeypatch.setattr(coordination_hook, "_discover_repositories", lambda _root: repositories)

    def fake_status(_repository: Path) -> dict[str, object]:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"fingerprint": "same", "dirty": False, "entry_count": 0}

    monkeypatch.setattr(coordination_hook, "_repository_status", fake_status)

    snapshot = coordination_hook._repository_snapshot(tmp_path)

    assert len(snapshot) == len(repositories)
    assert max_active > 1
