"""Tests for exact predecessor Codex process fencing."""

from __future__ import annotations

import json
import os
import shutil
import signal
from pathlib import Path

import pytest

from enforced_planning import session_process_fencing
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
    pid_root.joinpath("cwd").symlink_to(worktree)
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
        trusted_codex_executable=tmp_path / "bin" / "codex",
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
            trusted_codex_executable=tmp_path / "bin" / "codex",
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
            trusted_codex_executable=tmp_path / "bin" / "codex",
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
            trusted_codex_executable=tmp_path / "bin" / "codex",
            signal_process=os.kill,
        )


def test_fence_rejects_pid_in_different_worktree_without_signalling(tmp_path: Path) -> None:
    proc_root, pid_root, session_index, worktree = _fake_process(tmp_path)
    pid_root.joinpath("cwd").unlink()
    other_worktree = tmp_path / "other-worktree"
    other_worktree.mkdir()
    pid_root.joinpath("cwd").symlink_to(other_worktree)
    signals: list[tuple[int, int]] = []

    with pytest.raises(ValueError, match="exact claimed worktree"):
        fence_predecessor_process(
            predecessor_session_id="codex:old-session",
            successor_session_id="codex:new-session",
            worktree_path=str(worktree),
            predecessor_pid=4242,
            proc_root=proc_root,
            session_index=session_index,
            receipt_root=tmp_path / "receipts",
            trusted_codex_executable=tmp_path / "bin" / "codex",
            signal_process=lambda pid, sent_signal: signals.append((pid, sent_signal)),
        )

    assert signals == []


def test_fence_rejects_alternate_codex_executable_without_signalling(tmp_path: Path) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    trusted_codex = tmp_path / "trusted" / "codex"
    trusted_codex.parent.mkdir()
    trusted_codex.write_text("trusted fixture\n", encoding="utf-8")
    signals: list[tuple[int, int]] = []

    with pytest.raises(ValueError, match="successor runtime's exact Codex client"):
        fence_predecessor_process(
            predecessor_session_id="codex:old-session",
            successor_session_id="codex:new-session",
            worktree_path=str(worktree),
            predecessor_pid=4242,
            proc_root=proc_root,
            session_index=session_index,
            receipt_root=tmp_path / "receipts",
            trusted_codex_executable=trusted_codex,
            signal_process=lambda pid, sent_signal: signals.append((pid, sent_signal)),
        )

    assert signals == []


def test_fence_records_term_exit_when_proc_stat_disappears_during_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    original_read = session_process_fencing._read_start_ticks
    reads = 0

    def disappear_on_term_wait(stat_path: Path) -> int:
        nonlocal reads
        reads += 1
        if reads == 3:
            raise FileNotFoundError(stat_path)
        return original_read(stat_path)

    monkeypatch.setattr(session_process_fencing, "_read_start_ticks", disappear_on_term_wait)
    signals: list[tuple[int, int]] = []
    result = fence_predecessor_process(
        predecessor_session_id="codex:old-session",
        successor_session_id="codex:new-session",
        worktree_path=str(worktree),
        predecessor_pid=4242,
        proc_root=proc_root,
        session_index=session_index,
        receipt_root=tmp_path / "receipts",
        trusted_codex_executable=tmp_path / "bin" / "codex",
        signal_process=lambda pid, sent_signal: signals.append((pid, sent_signal)),
    )

    assert signals == [(4242, signal.SIGTERM)]
    assert result["signal"] == "SIGTERM"
    assert Path(str(result["receipt_path"])).is_file()


def test_fence_records_kill_exit_when_proc_stat_disappears_during_kill_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    original_read = session_process_fencing._read_start_ticks
    reads = 0

    def disappear_on_kill_wait(stat_path: Path) -> int:
        nonlocal reads
        reads += 1
        if reads == 5:
            raise FileNotFoundError(stat_path)
        return original_read(stat_path)

    monkeypatch.setattr(session_process_fencing, "_read_start_ticks", disappear_on_kill_wait)
    signals: list[tuple[int, int]] = []
    result = fence_predecessor_process(
        predecessor_session_id="codex:old-session",
        successor_session_id="codex:new-session",
        worktree_path=str(worktree),
        predecessor_pid=4242,
        proc_root=proc_root,
        session_index=session_index,
        receipt_root=tmp_path / "receipts",
        trusted_codex_executable=tmp_path / "bin" / "codex",
        timeout_seconds=0,
        signal_process=lambda pid, sent_signal: signals.append((pid, sent_signal)),
        sleep=lambda _seconds: None,
    )

    assert signals == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]
    assert result["signal"] == "SIGTERM+SIGKILL"
    assert Path(str(result["receipt_path"])).is_file()


def test_trusted_codex_skips_inaccessible_intermediate_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc_root = tmp_path / "proc"
    inaccessible = proc_root / "111" / "exe"
    codex_exe = tmp_path / "codex-runtime" / "codex"
    codex_exe.parent.mkdir()
    codex_exe.write_text("trusted\n", encoding="utf-8")
    (proc_root / "111").mkdir(parents=True)
    (proc_root / "222").mkdir(parents=True)
    (proc_root / "222" / "exe").symlink_to(codex_exe)
    monkeypatch.setattr(
        session_process_fencing, "_current_ancestor_pids", lambda _root: (111, 222)
    )
    original_resolve = Path.resolve

    def resolve_with_inaccessible_intermediate(
        path: Path, strict: bool = False
    ) -> Path:
        if path == inaccessible:
            raise PermissionError(path)
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_with_inaccessible_intermediate)

    assert session_process_fencing._trusted_codex_executable(proc_root) == codex_exe


def test_trusted_codex_selects_nearest_codex_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc_root = tmp_path / "proc"
    near_codex = tmp_path / "near" / "codex"
    far_codex = tmp_path / "far" / "codex"
    near_codex.parent.mkdir()
    far_codex.parent.mkdir()
    near_codex.write_text("near\n", encoding="utf-8")
    far_codex.write_text("far\n", encoding="utf-8")
    for pid, executable in ((111, near_codex), (222, far_codex)):
        (proc_root / str(pid)).mkdir(parents=True)
        (proc_root / str(pid) / "exe").symlink_to(executable)
    monkeypatch.setattr(
        session_process_fencing, "_current_ancestor_pids", lambda _root: (111, 222)
    )

    assert session_process_fencing._trusted_codex_executable(proc_root) == near_codex
