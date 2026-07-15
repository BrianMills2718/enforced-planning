#!/usr/bin/env python3
"""Probe Codex app-server steering without promoting a production broker.

The spike owns one disposable app-server process, records a redacted protocol
transcript, and separates protocol acceptance from model-visible evidence.  It
exists to answer Plan 67's runtime-ownership question, not to become a daemon.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import queue
import select
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


REDACTED_KEYS = ("authorization", "api_key", "apikey", "password", "secret", "token")


class SpikeFailure(RuntimeError):
    """Raised when the installed app-server disproves or cannot run the spike."""


@dataclass(frozen=True)
class SpikeReadout:
    """Decision-ready evidence extracted from one app-server observation."""

    codex_version: str
    schema_sha256: str
    thread_id: str
    active_turn_id: str
    active_message_id: str
    active_runtime_accepted: bool
    active_marker_observed: bool
    idle_turn_id: str
    idle_message_id: str
    idle_runtime_accepted: bool
    idle_marker_observed: bool
    passed: bool
    limitations: tuple[str, ...]


def _utc_stamp() -> str:
    """Return a filesystem-safe UTC timestamp for immutable evidence paths."""

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def redact(value: Any) -> Any:
    """Remove credential-shaped fields before protocol evidence is persisted."""

    if isinstance(value, dict):
        return {
            key: "<redacted>" if any(part in key.lower() for part in REDACTED_KEYS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def contains_marker(message: dict[str, Any], marker: str) -> bool:
    """Check only incoming agent-message events for model-visible marker text."""

    method = str(message.get("method", ""))
    if method not in {
        "item/agentMessage/delta",
        "item/completed",
        "codex/event/agent_message_delta",
        "codex/event/agent_message",
    }:
        return False
    return marker in json.dumps(message.get("params", {}), sort_keys=True)


def schema_digest(schema_root: Path) -> str:
    """Hash every generated schema path and byte sequence deterministically."""

    digest = hashlib.sha256()
    files = sorted(path for path in schema_root.rglob("*") if path.is_file())
    if not files:
        raise SpikeFailure(f"Codex generated no protocol schemas under {schema_root}")
    for path in files:
        digest.update(path.relative_to(schema_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class ProtocolClient:
    """Minimal single-owner JSONL client for one disposable app-server process."""

    def __init__(self, codex: str, cwd: Path, transcript: TextIO, timeout_seconds: float) -> None:
        self._transcript = transcript
        self._timeout_seconds = timeout_seconds
        self._stderr: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._process = subprocess.Popen(
            [codex, "app-server", "--stdio"],
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self._process.stdin is None or self._process.stdout is None or self._process.stderr is None:
            raise SpikeFailure("Codex app-server did not expose all stdio pipes")
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        """Prevent app-server diagnostic output from filling its pipe."""

        assert self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr.put(line.rstrip())

    def _record(self, direction: str, payload: dict[str, Any]) -> None:
        """Persist one redacted wire event with an observation timestamp."""

        record = {
            "observed_at": datetime.now(UTC).isoformat(),
            "direction": direction,
            "payload": redact(payload),
        }
        self._transcript.write(json.dumps(record, sort_keys=True) + "\n")
        self._transcript.flush()

    def send(self, payload: dict[str, Any]) -> None:
        """Send one JSON-RPC request or notification to the owned app-server."""

        assert self._process.stdin is not None
        self._record("out", payload)
        self._process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._process.stdin.flush()

    def receive(self, deadline: float) -> dict[str, Any]:
        """Receive one JSON message before the monotonic deadline."""

        assert self._process.stdout is not None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SpikeFailure("Timed out waiting for Codex app-server output")
        readable, _, _ = select.select([self._process.stdout], [], [], remaining)
        if not readable:
            raise SpikeFailure("Timed out waiting for Codex app-server output")
        line = self._process.stdout.readline()
        if not line:
            details = "\n".join(self.stderr_lines()[-20:])
            raise SpikeFailure(
                f"Codex app-server exited before the expected response (code={self._process.poll()}):\n{details}"
            )
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SpikeFailure(f"Codex app-server emitted non-JSON stdout: {line!r}") from exc
        if not isinstance(message, dict):
            raise SpikeFailure(f"Codex app-server emitted a non-object message: {message!r}")
        self._record("in", message)
        return message

    def wait_for_response(self, request_id: int, observed: list[dict[str, Any]]) -> dict[str, Any]:
        """Collect interleaved notifications until one request response arrives."""

        deadline = time.monotonic() + self._timeout_seconds
        while True:
            message = self.receive(deadline)
            observed.append(message)
            if message.get("id") == request_id:
                if "error" in message:
                    raise SpikeFailure(f"Request {request_id} failed: {message['error']}")
                return message

    def wait_for_turn(self, turn_id: str, observed: list[dict[str, Any]]) -> None:
        """Collect events until the exact turn reaches a terminal notification."""

        deadline = time.monotonic() + self._timeout_seconds
        while True:
            message = self.receive(deadline)
            observed.append(message)
            if message.get("method") != "turn/completed":
                continue
            turn = message.get("params", {}).get("turn", {})
            if turn.get("id") != turn_id:
                continue
            status = turn.get("status")
            if status != "completed":
                raise SpikeFailure(f"Turn {turn_id} completed with non-success status {status!r}")
            return

    def wait_for_turn_started(self, turn_id: str, observed: list[dict[str, Any]]) -> None:
        """Wait until the server announces that the turn is actually steerable."""

        deadline = time.monotonic() + self._timeout_seconds
        while True:
            message = self.receive(deadline)
            observed.append(message)
            if message.get("method") != "turn/started":
                continue
            turn = message.get("params", {}).get("turn", {})
            if turn.get("id") == turn_id:
                return

    def stderr_lines(self) -> list[str]:
        """Return currently buffered diagnostics without blocking."""

        lines: list[str] = []
        while True:
            try:
                lines.append(self._stderr.get_nowait())
            except queue.Empty:
                return lines

    def close(self) -> None:
        """Terminate the disposable app-server without touching persisted user sessions."""

        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)


def _result_value(response: dict[str, Any], *path: str) -> str:
    """Read one required string from a JSON-RPC result path or fail loudly."""

    value: Any = response.get("result", {})
    for part in path:
        if not isinstance(value, dict) or part not in value:
            raise SpikeFailure(f"Response lacks required result path {'.'.join(path)}: {response}")
        value = value[part]
    if not isinstance(value, str) or not value:
        raise SpikeFailure(f"Response path {'.'.join(path)} is not a non-empty string: {value!r}")
    return value


def render_readout(readout: SpikeReadout, transcript_path: Path) -> str:
    """Render the bounded claim and explicit non-claims for human review."""

    verdict = "PASS" if readout.passed else "FAIL"
    limitations = "\n".join(f"- {item}" for item in readout.limitations)
    return f"""# Plan 67 Codex App-Server Steering Spike

**Verdict:** {verdict}
**Observed at:** {datetime.now(UTC).isoformat()}
**Codex version:** `{readout.codex_version}`
**Generated schema digest:** `{readout.schema_sha256}`
**Transcript:** `{transcript_path.name}`

## Readout

- Native thread: `{readout.thread_id}`
- Active turn: `{readout.active_turn_id}`
- Active message: `{readout.active_message_id}`
- Active `turn/steer` accepted: `{str(readout.active_runtime_accepted).lower()}`
- Active marker observed in agent output: `{str(readout.active_marker_observed).lower()}`
- Idle-start turn: `{readout.idle_turn_id}`
- Idle message: `{readout.idle_message_id}`
- Idle `turn/start` accepted: `{str(readout.idle_runtime_accepted).lower()}`
- Idle marker observed in agent output: `{str(readout.idle_marker_observed).lower()}`

## Claim boundary

Passing proves only that one controller-owned session on this installed Codex
version accepted and processed active-turn and idle-turn messages. It does not
prove arbitrary TUI attachment, multi-client co-presence, Claude parity,
durable mailbox delivery, fleet migration, or recipient acknowledgement.

## Limitations

{limitations}
"""


def run_spike(codex: str, cwd: Path, output_dir: Path, timeout_seconds: float) -> tuple[SpikeReadout, Path, Path]:
    """Execute the two-message app-server spike and retain its decision evidence."""

    resolved_codex = shutil.which(codex)
    if resolved_codex is None:
        raise SpikeFailure(f"Codex executable is unavailable: {codex}")
    version = subprocess.run(
        [resolved_codex, "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()

    run_id = f"{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    transcript_path = run_dir / "protocol.jsonl"
    readout_path = run_dir / "readout.md"

    with tempfile.TemporaryDirectory(prefix="plan67-codex-schema-") as schema_tmp:
        schema_root = Path(schema_tmp)
        subprocess.run(
            [resolved_codex, "app-server", "generate-json-schema", "--experimental", "--out", str(schema_root)],
            check=True,
        )
        generated_schema_sha256 = schema_digest(schema_root)

    active_marker = f"ACTIVE_STEER_{uuid.uuid4().hex}"
    idle_marker = f"IDLE_START_{uuid.uuid4().hex}"
    active_message_id = f"plan67-active-{uuid.uuid4()}"
    idle_message_id = f"plan67-idle-{uuid.uuid4()}"
    observed: list[dict[str, Any]] = []

    with transcript_path.open("x", encoding="utf-8") as transcript:
        client = ProtocolClient(resolved_codex, cwd, transcript, timeout_seconds)
        try:
            client.send(
                {
                    "method": "initialize",
                    "id": 0,
                    "params": {
                        "clientInfo": {"name": "plan67-spike", "title": "Plan 67 Steering Spike", "version": "0.1.0"},
                        "capabilities": {"experimentalApi": True},
                    },
                }
            )
            client.wait_for_response(0, observed)
            client.send({"method": "initialized", "params": {}})

            client.send(
                {
                    "method": "thread/start",
                    "id": 1,
                    "params": {
                        "cwd": str(cwd.resolve()),
                        "approvalPolicy": "never",
                        "sandbox": "workspace-write",
                        "ephemeral": True,
                    },
                }
            )
            thread_id = _result_value(client.wait_for_response(1, observed), "thread", "id")

            client.send(
                {
                    "method": "turn/start",
                    "id": 2,
                    "params": {
                        "threadId": thread_id,
                        "clientUserMessageId": f"plan67-base-{uuid.uuid4()}",
                        "input": [
                            {
                                "type": "text",
                                "text": (
                                    "This is a bounded transport test. Determine whether 99991 is prime, then answer "
                                    "with ACTIVE_BASE. A follow-up may arrive while you work; incorporate it. "
                                    "Do not use tools."
                                ),
                            }
                        ],
                    },
                }
            )
            active_turn_id = _result_value(client.wait_for_response(2, observed), "turn", "id")
            # The request response can report inProgress before the runtime has
            # installed the turn as steerable. The native turn/started event is
            # the observable readiness boundary.
            client.wait_for_turn_started(active_turn_id, observed)

            client.send(
                {
                    "method": "turn/steer",
                    "id": 3,
                    "params": {
                        "threadId": thread_id,
                        "expectedTurnId": active_turn_id,
                        "clientUserMessageId": active_message_id,
                        "input": [
                            {
                                "type": "text",
                                "text": f"Include the exact token {active_marker} in your final answer.",
                            }
                        ],
                    },
                }
            )
            steer_response = client.wait_for_response(3, observed)
            accepted_turn_id = _result_value(steer_response, "turnId")
            if accepted_turn_id != active_turn_id:
                raise SpikeFailure(
                    f"turn/steer accepted unexpected turn {accepted_turn_id}; expected {active_turn_id}"
                )
            client.wait_for_turn(active_turn_id, observed)
            active_marker_observed = any(contains_marker(message, active_marker) for message in observed)

            idle_observed_start = len(observed)
            client.send(
                {
                    "method": "turn/start",
                    "id": 4,
                    "params": {
                        "threadId": thread_id,
                        "clientUserMessageId": idle_message_id,
                        "input": [
                            {"type": "text", "text": f"Return exactly {idle_marker} and nothing else."}
                        ],
                    },
                }
            )
            idle_turn_id = _result_value(client.wait_for_response(4, observed), "turn", "id")
            client.wait_for_turn(idle_turn_id, observed)
            idle_events = observed[idle_observed_start:]
            idle_marker_observed = any(contains_marker(message, idle_marker) for message in idle_events)
        finally:
            client.close()

    readout = SpikeReadout(
        codex_version=version,
        schema_sha256=generated_schema_sha256,
        thread_id=thread_id,
        active_turn_id=active_turn_id,
        active_message_id=active_message_id,
        active_runtime_accepted=True,
        active_marker_observed=active_marker_observed,
        idle_turn_id=idle_turn_id,
        idle_message_id=idle_message_id,
        idle_runtime_accepted=True,
        idle_marker_observed=idle_marker_observed,
        passed=active_marker_observed and idle_marker_observed,
        limitations=(
            "Single local stdio app-server process controlled by one client.",
            "No normal Codex TUI or second app-server client was attached.",
            "No mailbox persistence, offline recovery, Claude adapter, or acknowledgement was exercised.",
        ),
    )
    readout_path.write_text(render_readout(readout, transcript_path), encoding="utf-8")
    (run_dir / "readout.json").write_text(json.dumps(asdict(readout), indent=2) + "\n", encoding="utf-8")
    return readout, transcript_path, readout_path


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit CLI for the disposable experiment."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex", help="Codex executable to probe")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Disposable thread working directory")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/evidence/plan67_codex_app_server_spike"),
        help="Parent directory for immutable run evidence",
    )
    parser.add_argument(
        "--timeout-seconds", type=float, default=180.0, help="Maximum wait for each response or turn completion"
    )
    return parser


def main() -> int:
    """Run the spike and return nonzero when either marker is not observed."""

    args = build_parser().parse_args()
    try:
        readout, transcript_path, readout_path = run_spike(
            args.codex, args.cwd, args.output_dir, args.timeout_seconds
        )
    except (OSError, subprocess.CalledProcessError, SpikeFailure) as exc:
        print(f"Plan 67 Codex steering spike failed: {exc}")
        return 1
    print(json.dumps(asdict(readout), indent=2))
    print(f"Transcript: {transcript_path}")
    print(f"Readout: {readout_path}")
    return 0 if readout.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
