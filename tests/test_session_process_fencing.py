"""Tests for exact predecessor Codex process fencing."""

from __future__ import annotations

import json
import os
import shutil
import signal
from pathlib import Path

import pytest

from enforced_planning.session_process_fencing import fence_predecessor_process


def _fake_process(
    tmp_path: Path,
    *,
    pid: int = 4242,
    target: str = "old-agent",
    start_ticks: int = 123456,
) -> tuple[Path, Path, Path, Path]:
    proc_root = tmp_path / "proc"
    pid_root = proc_root / str(pid)
    pid_root.mkdir(parents=True)
    codex = tmp_path / "bin" / "codex"
    codex.parent.mkdir()
    codex.write_text("fixture\n", encoding="utf-8")
    pid_root.joinpath("exe").symlink_to(codex)
    pid_root.joinpath("cmdline").write_bytes(
        f"{codex}\0resume\0{target}\0--yolo\0".encode()
    )
    stat_fields = ["S", *(["0"] * 18), str(start_ticks)]
    pid_root.joinpath("stat").write_text(
        f"{pid} (codex) {' '.join(stat_fields)}\n",
        encoding="utf-8",
    )
    session_index = tmp_path / "session_index.jsonl"
    session_index.write_text(
        json.dumps(
            {
                "id": "old-session",
                "thread_name": "old-agent",
                "updated_at": "2026-09-01T23:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    return proc_root, pid_root, session_index, worktree


def test_fence_terminates_only_exact_session_pid_and_persists_receipt(tmp_path: Path) -> None:
    proc_root, pid_root, session_index, worktree = _fake_process(tmp_path)
    signals: list[tuple[int, int]] = []

    def terminate(pid: int, sent_signal: int) -> None:
        signals.append((pid, sent_signal))
        shutil.rmtree(pid_root)

    result = fence_predecessor_process(
        predecessor_session_id="codex:old-session",
        successor_session_id="codex:new-session",
        worktree_path=str(worktree),
        predecessor_pid=4242,
        proc_root=proc_root,
        session_index=session_index,
        receipt_root=tmp_path / "receipts",
        signal_process=terminate,
    )

    assert signals == [(4242, signal.SIGTERM)]
    assert result["pid"] == 4242
    assert result["process_start_ticks"] == 123456
    receipt_path = Path(str(result["receipt_path"]))
    assert receipt_path.is_file()
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert result["receipt_sha256"]


def test_fence_rejects_pid_for_different_session_without_signalling(tmp_path: Path) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(
        tmp_path, target="another-agent"
    )
    signals: list[tuple[int, int]] = []

    with pytest.raises(ValueError, match="different Codex session"):
        fence_predecessor_process(
            predecessor_session_id="codex:old-session",
            successor_session_id="codex:new-session",
            worktree_path=str(worktree),
            predecessor_pid=4242,
            proc_root=proc_root,
            session_index=session_index,
            receipt_root=tmp_path / "receipts",
            signal_process=lambda pid, sent_signal: signals.append((pid, sent_signal)),
        )

    assert signals == []


def test_fence_fails_closed_when_exact_process_does_not_exit(tmp_path: Path) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    signals: list[tuple[int, int]] = []

    with pytest.raises(RuntimeError, match="did not exit after SIGKILL"):
        fence_predecessor_process(
            predecessor_session_id="codex:old-session",
            successor_session_id="codex:new-session",
            worktree_path=str(worktree),
            predecessor_pid=4242,
            proc_root=proc_root,
            session_index=session_index,
            receipt_root=tmp_path / "receipts",
            timeout_seconds=0,
            signal_process=lambda pid, sent_signal: signals.append((pid, sent_signal)),
            sleep=lambda _seconds: None,
        )

    assert signals == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]
    assert not (tmp_path / "receipts").exists()


def test_fence_rejects_ambiguous_display_name(tmp_path: Path) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    with session_index.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "id": "other-session",
                    "thread_name": "old-agent",
                    "updated_at": "2026-09-01T23:01:00Z",
                }
            )
            + "\n"
        )

    with pytest.raises(ValueError, match="not unique"):
        fence_predecessor_process(
            predecessor_session_id="codex:old-session",
            successor_session_id="codex:new-session",
            worktree_path=str(worktree),
            predecessor_pid=4242,
            proc_root=proc_root,
            session_index=session_index,
            receipt_root=tmp_path / "receipts",
            signal_process=os.kill,
        )
