# Plan 67 Codex App-Server Steering Evidence

**Observed:** 2026-07-15

**Installed Codex:** `0.144.1`

**Bounded verdict:** Managed active-turn and idle-turn delivery are viable;
terminal notification delivery was not reliable enough to be the sole recovery
mechanism.

## What the evidence demonstrates

- A client that owns a Codex app-server thread can submit `turn/steer` against
  the exact active turn after observing `turn/started`.
- The injected active-turn marker became visible in agent output.
- After that turn completed, the same managed thread accepted another
  `turn/start`, and its idle-turn marker became visible in agent output.
- No Codex patch, terminal keystroke injection, second client, or Hermes runtime
  was needed.

This supports event-driven acceleration for broker-owned Codex sessions. It
does not demonstrate attachment to arbitrary existing TUI sessions, durable
mailbox behavior, recipient acknowledgement, multi-client co-presence, Claude
parity, or fleet operation.

## Attempts

| Evidence directory | Result | Decision value |
|---|---|---|
| `20260715T232835Z-3ed10e60` | `turn/steer` returned `no active turn to steer`. | A successful `turn/start` response is not the readiness boundary; wait for the matching `turn/started` event. |
| `20260715T232928Z-eef46d33` | After the readiness fix, `turn/steer` was accepted and `ACTIVE_STEER_98421692d89646838824c325f6720e29` appeared in final agent output. No `turn/completed` arrived before timeout. | Active steering works, but terminal-event delivery cannot be assumed. |
| `20260715T233550Z-2ab8279c` | No-tool run: active steering marker observed; active `turn/completed` observed; subsequent idle `turn/start` accepted and `IDLE_START_285eb2ef7c6046b890a912b1d9c6a217` observed. The idle turn omitted `turn/completed` before the 120-second timeout. | Both required delivery modes work on one managed thread. A production adapter still needs timeout/status reconciliation. |

Each directory contains the redacted JSONL transcript. Failed attempts do not
have generated pass readouts because the instrument fails loud at the missing
protocol boundary; this summary is the authoritative bounded interpretation of
the retained transcripts.

## Consequence for Plan 67

Proceed, when separately authorized, with a durable mailbox as authority and a
managed app-server adapter as optional acceleration. Record runtime acceptance,
agent observation, and acknowledgement separately. Do not use terminal events
as the only way to reconcile current state, and do not advertise real-time
interruption for unmanaged Codex sessions.
