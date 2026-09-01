"""Exact predecessor-process fencing for cross-session Codex custody transfer."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CODEX_SESSION_INDEX = Path("~/.codex/session_index.jsonl")
DEFAULT_FENCE_RECEIPT_ROOT = Path("~/.claude/coordination/session-process-fences-v1")


class ProcessFenceReceiptV1(BaseModel):
    """Immutable proof that one exact predecessor Codex process exited."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["session_predecessor_process_fence"] = (
        "session_predecessor_process_fence"
    )
    predecessor_session_id: str = Field(min_length=1)
    successor_session_id: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    pid: int = Field(gt=1)
    process_start_ticks: int = Field(ge=1)
    command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signal: Literal["SIGTERM", "SIGTERM+SIGKILL"] = "SIGTERM"
    fenced_at: datetime


def _read_start_ticks(stat_path: Path) -> int:
    raw = stat_path.read_text(encoding="utf-8")
    closing = raw.rfind(")")
    if closing < 0:
        raise ValueError("predecessor /proc stat record is malformed")
    fields_after_command = raw[closing + 1 :].split()
    if len(fields_after_command) <= 19:
        raise ValueError("predecessor /proc stat record lacks process start identity")
    return int(fields_after_command[19])


def _current_ancestor_pids(proc_root: Path) -> set[int]:
    ancestors: set[int] = set()
    current = os.getpid()
    while current > 1 and current not in ancestors:
        ancestors.add(current)
        status_path = proc_root / str(current) / "status"
        try:
            parent_line = next(
                line for line in status_path.read_text(encoding="utf-8").splitlines()
                if line.startswith("PPid:")
            )
        except (FileNotFoundError, StopIteration):
            break
        current = int(parent_line.partition(":")[2].strip())
    return ancestors


def _current_display_names(session_index: Path) -> dict[str, str]:
    latest: dict[str, tuple[str, str]] = {}
    for line in session_index.expanduser().read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError("Codex session index contains malformed JSON") from exc
        if not isinstance(record, dict):
            raise TypeError("Codex session index contains a non-object record")
        session_id = record.get("id")
        display_name = record.get("thread_name")
        updated_at = record.get("updated_at")
        if not all(isinstance(value, str) and value.strip() for value in (session_id, display_name, updated_at)):
            continue
        candidate = (updated_at, display_name.strip())
        if session_id not in latest or candidate[0] > latest[session_id][0]:
            latest[session_id] = candidate
    return {session_id: candidate[1] for session_id, candidate in latest.items()}


def _validate_codex_process_command(
    *,
    pid_root: Path,
    predecessor_session_id: str,
    session_index: Path,
) -> str:
    executable = pid_root.joinpath("exe").resolve(strict=True)
    if executable.name != "codex":
        raise ValueError("predecessor PID executable is not the exact Codex client")
    command_bytes = pid_root.joinpath("cmdline").read_bytes()
    tokens = [token.decode("utf-8") for token in command_bytes.split(b"\0") if token]
    if not tokens or Path(tokens[0]).name != "codex" or tokens.count("resume") != 1:
        raise ValueError("predecessor PID command is not one direct Codex resume process")
    resume_index = tokens.index("resume")
    if resume_index + 1 >= len(tokens) or tokens[resume_index + 1].startswith("-"):
        raise ValueError("predecessor Codex process does not name one exact resumed session")

    raw_session_id = predecessor_session_id.removeprefix("codex:")
    names = _current_display_names(session_index)
    display_name = names.get(raw_session_id)
    allowed_targets = {raw_session_id}
    if display_name is not None:
        if sum(1 for value in names.values() if value == display_name) != 1:
            raise ValueError("predecessor Codex display name is not unique in the session index")
        allowed_targets.add(display_name)
    if tokens[resume_index + 1] not in allowed_targets:
        raise ValueError("predecessor PID command targets a different Codex session")
    return hashlib.sha256(command_bytes).hexdigest()


def fence_predecessor_process(
    *,
    predecessor_session_id: str,
    successor_session_id: str,
    worktree_path: str,
    predecessor_pid: int,
    proc_root: Path = Path("/proc"),
    session_index: Path = DEFAULT_CODEX_SESSION_INDEX,
    receipt_root: Path = DEFAULT_FENCE_RECEIPT_ROOT,
    timeout_seconds: float = 5.0,
    signal_process: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Terminate one exact Codex predecessor and persist fail-closed evidence."""

    if predecessor_session_id == successor_session_id:
        raise ValueError("process fencing requires distinct predecessor and successor sessions")
    if not predecessor_session_id.startswith("codex:") or not successor_session_id.startswith("codex:"):
        raise ValueError("exact process fencing currently supports Codex-to-Codex transfer only")
    if predecessor_pid <= 1 or predecessor_pid in _current_ancestor_pids(proc_root):
        raise ValueError("refusing to fence the current successor process or one of its ancestors")
    canonical_worktree = Path(worktree_path).expanduser().resolve(strict=True)
    pid_root = proc_root / str(predecessor_pid)
    start_ticks = _read_start_ticks(pid_root / "stat")
    command_sha256 = _validate_codex_process_command(
        pid_root=pid_root,
        predecessor_session_id=predecessor_session_id,
        session_index=session_index,
    )

    def wait_for_exit(deadline: float) -> bool:
        while pid_root.exists():
            if _read_start_ticks(pid_root / "stat") != start_ticks:
                raise RuntimeError("predecessor PID was reused before termination could be proven")
            if time.monotonic() >= deadline:
                return False
            sleep(0.05)
        return True

    signal_process(predecessor_pid, signal.SIGTERM)
    final_signal: Literal["SIGTERM", "SIGTERM+SIGKILL"] = "SIGTERM"
    if not wait_for_exit(time.monotonic() + timeout_seconds):
        if _read_start_ticks(pid_root / "stat") != start_ticks:
            raise RuntimeError("predecessor PID was reused before termination could be proven")
        signal_process(predecessor_pid, signal.SIGKILL)
        final_signal = "SIGTERM+SIGKILL"
        if not wait_for_exit(time.monotonic() + timeout_seconds):
            raise RuntimeError("exact predecessor process did not exit after SIGKILL")

    receipt = ProcessFenceReceiptV1(
        predecessor_session_id=predecessor_session_id,
        successor_session_id=successor_session_id,
        worktree_path=str(canonical_worktree),
        pid=predecessor_pid,
        process_start_ticks=start_ticks,
        command_sha256=command_sha256,
        signal=final_signal,
        fenced_at=datetime.now(UTC),
    )
    serialized = receipt.model_dump_json(indent=2).encode("utf-8") + b"\n"
    receipt_root = receipt_root.expanduser().resolve()
    receipt_root.mkdir(parents=True, exist_ok=True)
    receipt_id = hashlib.sha256(serialized).hexdigest()
    receipt_path = receipt_root / f"{receipt_id}.json"
    descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        **receipt.model_dump(mode="json"),
        "receipt_path": str(receipt_path),
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    }


__all__ = ["ProcessFenceReceiptV1", "fence_predecessor_process"]
