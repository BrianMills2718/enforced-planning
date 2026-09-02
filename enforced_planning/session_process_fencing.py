"""Exact predecessor-process fencing for cross-session Codex custody transfer."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import select
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_CODEX_SESSION_INDEX = Path("~/.codex/session_index.jsonl")
DEFAULT_FENCE_RECEIPT_ROOT = Path("~/.claude/coordination/session-process-fences-v1")


def _open_pidfd(pid: int) -> int:
    return os.pidfd_open(pid, 0)


def _signal_pidfd(pidfd: int, sent_signal: int) -> None:
    signal.pidfd_send_signal(pidfd, sent_signal, None, 0)


def _pidfd_exited(pidfd: int, timeout_seconds: float) -> bool:
    poller = select.poll()
    poller.register(pidfd, select.POLLIN)
    timeout_ms = max(0, round(timeout_seconds * 1000))
    return bool(poller.poll(timeout_ms))


class ProcessFenceReceiptV1(BaseModel):
    """Immutable proof that one exact predecessor Codex process exited."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["session_predecessor_process_fence"] = "session_predecessor_process_fence"
    predecessor_session_id: str = Field(min_length=1)
    successor_session_id: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    pid: int = Field(gt=1)
    transfer_epoch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    process_start_ticks: int = Field(ge=1)
    command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signal: Literal["SIGTERM", "SIGTERM+SIGKILL", "RECOVERED_ABSENT_AFTER_INTENT"] = "SIGTERM"
    fenced_at: datetime


class ProcessFenceIntentV1(BaseModel):
    """Durable pre-signal identity used to recover an interrupted fence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["session_predecessor_process_fence_intent"] = "session_predecessor_process_fence_intent"
    predecessor_session_id: str = Field(min_length=1)
    successor_session_id: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    pid: int = Field(gt=1)
    transfer_epoch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    process_start_ticks: int = Field(ge=1)
    command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class PredecessorProcessIdentityV1(BaseModel):
    """Exact live Codex process generation resolved before successor launch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["codex_predecessor_process_identity"] = (
        "codex_predecessor_process_identity"
    )
    predecessor_session_id: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    pid: int = Field(gt=1)
    process_start_ticks: int = Field(ge=1)
    command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _write_durable_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    for directory in (path.parent, path.parent.parent, path.parent.parent.parent):
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _load_json_model(path: Path, model: type[BaseModel]) -> BaseModel:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def _read_start_ticks(stat_path: Path) -> int:
    raw = stat_path.read_text(encoding="utf-8")
    closing = raw.rfind(")")
    if closing < 0:
        raise ValueError("predecessor /proc stat record is malformed")
    fields_after_command = raw[closing + 1 :].split()
    if len(fields_after_command) <= 19:
        raise ValueError("predecessor /proc stat record lacks process start identity")
    return int(fields_after_command[19])


def _current_ancestor_pids(proc_root: Path) -> tuple[int, ...]:
    ancestors: list[int] = []
    current = os.getpid()
    while current > 1 and current not in ancestors:
        ancestors.append(current)
        status_path = proc_root / str(current) / "status"
        try:
            parent_line = next(
                line for line in status_path.read_text(encoding="utf-8").splitlines() if line.startswith("PPid:")
            )
        except (FileNotFoundError, StopIteration):
            break
        current = int(parent_line.partition(":")[2].strip())
    return tuple(ancestors)


def _trusted_codex_executable(proc_root: Path) -> Path:
    """Resolve the exact Codex executable used by this successor runtime."""

    for pid in _current_ancestor_pids(proc_root):
        pid_root = proc_root / str(pid)
        try:
            process_name = pid_root.joinpath("comm").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if process_name != "codex":
            continue
        try:
            return pid_root.joinpath("exe").resolve(strict=True)
        except OSError as exc:
            raise ValueError("nearest Codex ancestor executable is not inspectable") from exc
    raise ValueError("successor runtime has no exact Codex ancestor executable")


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
    trusted_codex_executable: Path,
) -> str:
    executable = pid_root.joinpath("exe").resolve(strict=True)
    if executable != trusted_codex_executable.resolve(strict=True):
        raise ValueError("predecessor PID executable is not the successor runtime's exact Codex client")
    command_bytes = pid_root.joinpath("cmdline").read_bytes()
    tokens = [token.decode("utf-8") for token in command_bytes.split(b"\0") if token]
    if not tokens or Path(tokens[0]).name != "codex":
        raise ValueError("predecessor PID command is not one direct Codex resume process")

    flag_only_globals = {
        "--dangerously-bypass-approvals-and-sandbox",
        "--full-auto",
        "--no-alt-screen",
        "--oss",
        "--search",
    }
    valued_globals = {
        "--add-dir",
        "--ask-for-approval",
        "--chdir",
        "--config",
        "--disable",
        "--enable",
        "--image",
        "--model",
        "--profile",
        "--sandbox",
        "-C",
        "-a",
        "-c",
        "-i",
        "-m",
        "-p",
        "-s",
    }
    index = 1
    while index < len(tokens) and tokens[index] != "resume":
        token = tokens[index]
        if token in flag_only_globals:
            index += 1
            continue
        option, separator, value = token.partition("=")
        if separator and option in valued_globals and value:
            index += 1
            continue
        if token in valued_globals and index + 1 < len(tokens):
            index += 2
            continue
        raise ValueError("predecessor PID command is not one direct Codex resume process")
    if index >= len(tokens) or tokens[index] != "resume":
        raise ValueError("predecessor PID command is not one direct Codex resume process")
    resume_index = index
    if resume_index + 2 != len(tokens) or tokens[resume_index + 1].startswith("-"):
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


def resolve_predecessor_process(
    *,
    predecessor_session_id: str,
    worktree_path: str,
    trusted_codex_executable: Path,
    proc_root: Path = Path("/proc"),
    session_index: Path = DEFAULT_CODEX_SESSION_INDEX,
) -> PredecessorProcessIdentityV1:
    """Resolve exactly one direct Codex resume process for an offered owner."""

    if not predecessor_session_id.startswith("codex:"):
        raise ValueError("predecessor process resolution requires a Codex session")
    canonical_worktree = Path(worktree_path).expanduser().resolve(strict=True)
    trusted_executable = trusted_codex_executable.expanduser().resolve(strict=True)
    matches: list[PredecessorProcessIdentityV1] = []
    for pid_root in sorted(
        (candidate for candidate in proc_root.iterdir() if candidate.name.isdigit()),
        key=lambda candidate: int(candidate.name),
    ):
        pid = int(pid_root.name)
        if pid <= 1:
            continue
        try:
            if pid_root.joinpath("cwd").resolve(strict=True) != canonical_worktree:
                continue
            command_sha256 = _validate_codex_process_command(
                pid_root=pid_root,
                predecessor_session_id=predecessor_session_id,
                session_index=session_index,
                trusted_codex_executable=trusted_executable,
            )
            start_ticks = _read_start_ticks(pid_root / "stat")
        except (FileNotFoundError, OSError, UnicodeDecodeError, ValueError):
            continue
        matches.append(
            PredecessorProcessIdentityV1(
                predecessor_session_id=predecessor_session_id,
                worktree_path=str(canonical_worktree),
                pid=pid,
                process_start_ticks=start_ticks,
                command_sha256=command_sha256,
            )
        )
    if not matches:
        raise ValueError("no exact live predecessor Codex resume process was found")
    if len(matches) != 1:
        raise ValueError("multiple exact predecessor Codex resume processes were found")
    return matches[0]


def fence_predecessor_process(
    *,
    predecessor_session_id: str,
    successor_session_id: str,
    worktree_path: str,
    predecessor_pid: int,
    transfer_epoch_sha256: str,
    predecessor_process_start_ticks: int,
    proc_root: Path = Path("/proc"),
    session_index: Path = DEFAULT_CODEX_SESSION_INDEX,
    receipt_root: Path = DEFAULT_FENCE_RECEIPT_ROOT,
    trusted_codex_executable: Path | None = None,
    timeout_seconds: float = 5.0,
    open_pidfd: Callable[[int], int] = _open_pidfd,
    signal_pidfd: Callable[[int, int], None] = _signal_pidfd,
    pidfd_exited: Callable[[int, float], bool] = _pidfd_exited,
    close_pidfd: Callable[[int], None] = os.close,
) -> dict[str, object]:
    """Terminate one exact Codex predecessor and persist fail-closed evidence."""

    if predecessor_session_id == successor_session_id:
        raise ValueError("process fencing requires distinct predecessor and successor sessions")
    if not predecessor_session_id.startswith("codex:") or not successor_session_id.startswith("codex:"):
        raise ValueError("exact process fencing currently supports Codex-to-Codex transfer only")
    if predecessor_pid <= 1 or predecessor_pid in _current_ancestor_pids(proc_root):
        raise ValueError("refusing to fence the current successor process or one of its ancestors")
    if len(transfer_epoch_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in transfer_epoch_sha256
    ):
        raise ValueError("process fencing requires one exact lowercase claim-bytes SHA-256 epoch")
    if predecessor_process_start_ticks < 1:
        raise ValueError("process fencing requires positive predecessor process start ticks")
    canonical_worktree = Path(worktree_path).expanduser().resolve(strict=True)
    receipt_root = receipt_root.expanduser().resolve()
    request_bytes = json.dumps(
        {
            "predecessor_session_id": predecessor_session_id,
            "successor_session_id": successor_session_id,
            "worktree_path": str(canonical_worktree),
            "pid": predecessor_pid,
            "transfer_epoch_sha256": transfer_epoch_sha256,
            "process_start_ticks": predecessor_process_start_ticks,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    intent_id = hashlib.sha256(request_bytes).hexdigest()
    intent_path = receipt_root / "intents" / f"{intent_id}.json"
    receipt_path = receipt_root / f"{intent_id}.json"

    def validate_request_binding(record: ProcessFenceIntentV1 | ProcessFenceReceiptV1) -> None:
        if (
            record.predecessor_session_id != predecessor_session_id
            or record.successor_session_id != successor_session_id
            or record.worktree_path != str(canonical_worktree)
            or record.pid != predecessor_pid
            or record.transfer_epoch_sha256 != transfer_epoch_sha256
            or record.process_start_ticks != predecessor_process_start_ticks
        ):
            raise RuntimeError("persisted process-fence state does not match this exact request")

    def completed_result() -> dict[str, object] | None:
        if not receipt_path.exists():
            return None
        if intent is None:
            raise RuntimeError("completed process-fence receipt lacks its durable intent")
        receipt = ProcessFenceReceiptV1.model_validate_json(receipt_path.read_text(encoding="utf-8"))
        validate_request_binding(receipt)
        if receipt.process_start_ticks != intent.process_start_ticks or receipt.command_sha256 != intent.command_sha256:
            raise RuntimeError("completed process-fence receipt does not match its durable intent")
        return {
            **receipt.model_dump(mode="json"),
            "receipt_path": str(receipt_path),
            "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        }

    intent = (
        ProcessFenceIntentV1.model_validate_json(intent_path.read_text(encoding="utf-8"))
        if intent_path.exists()
        else None
    )
    if intent is not None:
        validate_request_binding(intent)

    already_completed = completed_result()

    def finalize(
        active_intent: ProcessFenceIntentV1,
        final_signal: Literal["SIGTERM", "SIGTERM+SIGKILL", "RECOVERED_ABSENT_AFTER_INTENT"],
    ) -> dict[str, object]:
        receipt = ProcessFenceReceiptV1(
            predecessor_session_id=active_intent.predecessor_session_id,
            successor_session_id=active_intent.successor_session_id,
            worktree_path=active_intent.worktree_path,
            pid=active_intent.pid,
            transfer_epoch_sha256=active_intent.transfer_epoch_sha256,
            process_start_ticks=active_intent.process_start_ticks,
            command_sha256=active_intent.command_sha256,
            signal=final_signal,
            fenced_at=datetime.now(UTC),
        )
        serialized = receipt.model_dump_json(indent=2).encode("utf-8") + b"\n"
        try:
            _write_durable_exclusive(receipt_path, serialized)
        except FileExistsError:
            pass
        completed = completed_result()
        if completed is None:
            raise RuntimeError("process-fence receipt was not durably finalized")
        return completed

    pid_root = proc_root / str(predecessor_pid)
    try:
        pidfd = open_pidfd(predecessor_pid)
    except ProcessLookupError:
        if already_completed is not None:
            return already_completed
        if intent is None:
            raise
        return finalize(intent, "RECOVERED_ABSENT_AFTER_INTENT")
    try:
        if pidfd_exited(pidfd, 0):
            if already_completed is not None:
                return already_completed
            if intent is not None:
                return finalize(intent, "RECOVERED_ABSENT_AFTER_INTENT")
            raise RuntimeError("exact predecessor process exited before identity validation")
        start_ticks = _read_start_ticks(pid_root / "stat")
        if start_ticks != predecessor_process_start_ticks:
            raise RuntimeError(
                "live predecessor generation does not match --predecessor-process-start-ticks; "
                "inspect the exact process and retry with a fresh generation"
            )
        if already_completed is not None:
            raise RuntimeError("completed fence evidence cannot be replayed for a live process generation")
        predecessor_worktree = pid_root.joinpath("cwd").resolve(strict=True)
        if predecessor_worktree != canonical_worktree:
            raise ValueError("predecessor PID is not running in the exact claimed worktree")
        trusted_executable = (
            trusted_codex_executable.resolve(strict=True)
            if trusted_codex_executable is not None
            else _trusted_codex_executable(proc_root)
        )
        command_sha256 = _validate_codex_process_command(
            pid_root=pid_root,
            predecessor_session_id=predecessor_session_id,
            session_index=session_index,
            trusted_codex_executable=trusted_executable,
        )
        if _read_start_ticks(pid_root / "stat") != start_ticks:
            raise RuntimeError("predecessor PID was reused before it could be signalled")
        if pidfd_exited(pidfd, 0):
            if already_completed is not None:
                return already_completed
            if intent is not None:
                return finalize(intent, "RECOVERED_ABSENT_AFTER_INTENT")
            raise RuntimeError("exact predecessor process exited during identity validation")

        if intent is None:
            intent = ProcessFenceIntentV1(
                predecessor_session_id=predecessor_session_id,
                successor_session_id=successor_session_id,
                worktree_path=str(canonical_worktree),
                pid=predecessor_pid,
                transfer_epoch_sha256=transfer_epoch_sha256,
                process_start_ticks=predecessor_process_start_ticks,
                command_sha256=command_sha256,
                created_at=datetime.now(UTC),
            )
            try:
                _write_durable_exclusive(
                    intent_path,
                    intent.model_dump_json(indent=2).encode("utf-8") + b"\n",
                )
            except FileExistsError:
                persisted_intent = ProcessFenceIntentV1.model_validate_json(intent_path.read_text(encoding="utf-8"))
                validate_request_binding(persisted_intent)
                if persisted_intent != intent:
                    raise RuntimeError("concurrent process-fence intent has different identity")
                intent = persisted_intent
        elif intent.command_sha256 != command_sha256:
            raise RuntimeError("live predecessor command does not match durable fence intent")

        signal_pidfd(pidfd, signal.SIGTERM)
        final_signal: Literal["SIGTERM", "SIGTERM+SIGKILL"] = "SIGTERM"
        if not pidfd_exited(pidfd, timeout_seconds):
            signal_pidfd(pidfd, signal.SIGKILL)
            final_signal = "SIGTERM+SIGKILL"
            if not pidfd_exited(pidfd, timeout_seconds):
                raise RuntimeError("exact predecessor process did not exit after SIGKILL")
    finally:
        close_pidfd(pidfd)
    return finalize(intent, final_signal)


__all__ = [
    "PredecessorProcessIdentityV1",
    "ProcessFenceIntentV1",
    "ProcessFenceReceiptV1",
    "fence_predecessor_process",
    "resolve_predecessor_process",
]
