"""Tests for exact predecessor Codex process fencing."""

from __future__ import annotations

import json
import signal
from pathlib import Path

import pytest

from enforced_planning import session_process_fencing
from enforced_planning.session_process_fencing import fence_predecessor_process


def _pidfd_controls(
    *, exit_on: int | None
) -> tuple[list[tuple[int, int]], dict[str, object]]:
    signals: list[tuple[int, int]] = []
    state = {"exited": False}

    def send(pidfd: int, sent_signal: int) -> None:
        signals.append((pidfd, sent_signal))
        if sent_signal == exit_on:
            state["exited"] = True

    controls: dict[str, object] = {
        "open_pidfd": lambda _pid: 99,
        "signal_pidfd": send,
        "pidfd_exited": lambda _pidfd, _timeout: state["exited"],
        "close_pidfd": lambda _pidfd: None,
    }
    return signals, controls


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
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    signals, pidfd_controls = _pidfd_controls(exit_on=signal.SIGTERM)

    result = fence_predecessor_process(
        predecessor_session_id="codex:old-session",
        successor_session_id="codex:new-session",
        worktree_path=str(worktree),
        predecessor_pid=4242,
        proc_root=proc_root,
        session_index=session_index,
        receipt_root=tmp_path / "receipts",
        trusted_codex_executable=tmp_path / "bin" / "codex",
        **pidfd_controls,
    )

    assert signals == [(99, signal.SIGTERM)]
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
    signals, pidfd_controls = _pidfd_controls(exit_on=signal.SIGTERM)

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
            **pidfd_controls,
        )

    assert signals == []


def test_fence_fails_closed_when_exact_process_does_not_exit(tmp_path: Path) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    signals, pidfd_controls = _pidfd_controls(exit_on=None)

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
            **pidfd_controls,
        )

    assert signals == [(99, signal.SIGTERM), (99, signal.SIGKILL)]
    assert list((tmp_path / "receipts" / "intents").glob("*.json"))
    assert not list((tmp_path / "receipts").glob("*.json"))


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
        _signals, pidfd_controls = _pidfd_controls(exit_on=signal.SIGTERM)
        fence_predecessor_process(
            predecessor_session_id="codex:old-session",
            successor_session_id="codex:new-session",
            worktree_path=str(worktree),
            predecessor_pid=4242,
            proc_root=proc_root,
            session_index=session_index,
            receipt_root=tmp_path / "receipts",
            trusted_codex_executable=tmp_path / "bin" / "codex",
            **pidfd_controls,
        )


def test_fence_rejects_pid_in_different_worktree_without_signalling(tmp_path: Path) -> None:
    proc_root, pid_root, session_index, worktree = _fake_process(tmp_path)
    pid_root.joinpath("cwd").unlink()
    other_worktree = tmp_path / "other-worktree"
    other_worktree.mkdir()
    pid_root.joinpath("cwd").symlink_to(other_worktree)
    signals, pidfd_controls = _pidfd_controls(exit_on=signal.SIGTERM)

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
            **pidfd_controls,
        )

    assert signals == []


def test_fence_rejects_alternate_codex_executable_without_signalling(tmp_path: Path) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    trusted_codex = tmp_path / "trusted" / "codex"
    trusted_codex.parent.mkdir()
    trusted_codex.write_text("trusted fixture\n", encoding="utf-8")
    signals, pidfd_controls = _pidfd_controls(exit_on=signal.SIGTERM)

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
            **pidfd_controls,
        )

    assert signals == []


def test_pid_reuse_at_signal_boundary_cannot_receive_signal(tmp_path: Path) -> None:
    proc_root, pid_root, session_index, worktree = _fake_process(tmp_path)
    handle_targets = {99: "exact-original-process"}
    handle_signals: list[tuple[str, int]] = []
    replacement_signals: list[int] = []
    state = {"exited": False}

    def signal_exact_handle(pidfd: int, sent_signal: int) -> None:
        stat_fields = ["S", *(["0"] * 18), "999999"]
        pid_root.joinpath("stat").write_text(
            f"4242 (replacement) {' '.join(stat_fields)}\n",
            encoding="utf-8",
        )
        handle_signals.append((handle_targets[pidfd], sent_signal))
        state["exited"] = True

    result = fence_predecessor_process(
        predecessor_session_id="codex:old-session",
        successor_session_id="codex:new-session",
        worktree_path=str(worktree),
        predecessor_pid=4242,
        proc_root=proc_root,
        session_index=session_index,
        receipt_root=tmp_path / "receipts",
        trusted_codex_executable=tmp_path / "bin" / "codex",
        open_pidfd=lambda _pid: 99,
        signal_pidfd=signal_exact_handle,
        pidfd_exited=lambda _pidfd, _timeout: state["exited"],
        close_pidfd=lambda _pidfd: None,
    )

    assert handle_signals == [("exact-original-process", signal.SIGTERM)]
    assert replacement_signals == []
    assert result["signal"] == "SIGTERM"
    assert Path(str(result["receipt_path"])).is_file()


def test_receipt_write_failure_after_exit_retries_from_durable_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    receipt_root = tmp_path / "receipts"
    signals, pidfd_controls = _pidfd_controls(exit_on=signal.SIGTERM)
    original_write = session_process_fencing._write_durable_exclusive
    failed_final_write = False

    def fail_first_final_write(path: Path, payload: bytes) -> None:
        nonlocal failed_final_write
        if path.parent == receipt_root and not failed_final_write:
            failed_final_write = True
            raise OSError("injected final receipt write failure")
        original_write(path, payload)

    monkeypatch.setattr(
        session_process_fencing, "_write_durable_exclusive", fail_first_final_write
    )
    with pytest.raises(OSError, match="injected final receipt write failure"):
        fence_predecessor_process(
            predecessor_session_id="codex:old-session",
            successor_session_id="codex:new-session",
            worktree_path=str(worktree),
            predecessor_pid=4242,
            proc_root=proc_root,
            session_index=session_index,
            receipt_root=receipt_root,
            trusted_codex_executable=tmp_path / "bin" / "codex",
            **pidfd_controls,
        )

    assert signals == [(99, signal.SIGTERM)]
    assert list((receipt_root / "intents").glob("*.json"))
    assert not list(receipt_root.glob("*.json"))

    retry = fence_predecessor_process(
        predecessor_session_id="codex:old-session",
        successor_session_id="codex:new-session",
        worktree_path=str(worktree),
        predecessor_pid=4242,
        proc_root=proc_root,
        session_index=session_index,
        receipt_root=receipt_root,
        trusted_codex_executable=tmp_path / "bin" / "codex",
        open_pidfd=lambda _pid: (_ for _ in ()).throw(ProcessLookupError()),
        signal_pidfd=lambda _pidfd, _signal: pytest.fail("retry must not signal"),
        pidfd_exited=lambda _pidfd, _timeout: True,
        close_pidfd=lambda _pidfd: None,
    )

    assert retry["signal"] == "RECOVERED_ABSENT_AFTER_INTENT"
    assert Path(str(retry["receipt_path"])).is_file()


def test_completed_fence_retry_is_idempotent_without_opening_pidfd(tmp_path: Path) -> None:
    proc_root, _pid_root, session_index, worktree = _fake_process(tmp_path)
    controls_signals, pidfd_controls = _pidfd_controls(exit_on=signal.SIGTERM)
    first = fence_predecessor_process(
        predecessor_session_id="codex:old-session",
        successor_session_id="codex:new-session",
        worktree_path=str(worktree),
        predecessor_pid=4242,
        proc_root=proc_root,
        session_index=session_index,
        receipt_root=tmp_path / "receipts",
        trusted_codex_executable=tmp_path / "bin" / "codex",
        **pidfd_controls,
    )
    second = fence_predecessor_process(
        predecessor_session_id="codex:old-session",
        successor_session_id="codex:new-session",
        worktree_path=str(worktree),
        predecessor_pid=4242,
        proc_root=proc_root,
        session_index=session_index,
        receipt_root=tmp_path / "receipts",
        trusted_codex_executable=tmp_path / "bin" / "codex",
        open_pidfd=lambda _pid: pytest.fail("completed retry must not open pidfd"),
    )

    assert controls_signals == [(99, signal.SIGTERM)]
    assert second["receipt_sha256"] == first["receipt_sha256"]


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
    (proc_root / "111" / "comm").write_text("bash\n", encoding="utf-8")
    (proc_root / "222" / "comm").write_text("codex\n", encoding="utf-8")
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
        (proc_root / str(pid) / "comm").write_text("codex\n", encoding="utf-8")
        (proc_root / str(pid) / "exe").symlink_to(executable)
    monkeypatch.setattr(
        session_process_fencing, "_current_ancestor_pids", lambda _root: (111, 222)
    )

    assert session_process_fencing._trusted_codex_executable(proc_root) == near_codex
