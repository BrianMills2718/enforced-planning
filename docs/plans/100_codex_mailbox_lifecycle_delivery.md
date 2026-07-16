# Plan #100: Native Codex Mailbox Lifecycle Delivery

**Status:** Complete
**Goal:** Make persisted cross-agent requests visible to active Codex recipients
without relying on human relay or optional manual lifecycle commands.
**Repairs:** Plan #67 C67-3/C67-5/C67-7 verification gap

## Problem

Two messages sent to live exact-session recipients were persisted but never
observed or acknowledged before those claims disappeared. Plan #67 installed a
Claude hook and explicit shared lifecycle polling, but no native Codex hook.
Its retained pilot proved separate CLI processes, not delivery into independent
Codex reasoning sessions.

## Requirements

1. Native Codex lifecycle events receive the runtime `session_id`, poll the
   canonical mailbox, and inject active requests as agent-visible context.
2. Observation receipts are written only when a notice reaches a hook result.
3. Acknowledged and expired messages do not keep reappearing; observed but
   unacknowledged requests remain visible.
4. The bounded mailbox installer deploys Claude and Codex adapters together
   without refreshing unrelated governance files.
5. Missing prerequisites or mailbox failures produce a visible hook warning,
   not silent success.

## Boundaries

- The JSON mailbox remains the durable authority.
- Hooks accelerate lifecycle delivery; they do not authorize work or infer an
  acknowledgement disposition.
- No terminal keystroke injection or attachment to arbitrary TUI processes.
- A running turn receives the request at its next supported lifecycle event;
  asynchronous interruption remains limited to broker-owned app-server threads.

## Contracts

`Codex hook JSON -> session identity + repository project -> canonical poll ->
observation receipt + agent-visible hook JSON`.

Events: `SessionStart`, `UserPromptSubmit`, and `PostToolUse`. Session start adds
developer context; turn events emit a system message. The hook prefixes raw
Codex UUIDs with `codex:` to match canonical claim identities.

## Acceptance Criteria

| ID | Criterion | Evidence | Grade target |
|---|---|---|---|
| C100-1 | Hook-shaped Codex input causes a persisted request to become observed and agent-visible. | real filesystem message/receipt test | A |
| C100-2 | Acknowledged requests disappear while observed-unacknowledged requests remain visible. | both-sign projection test | A |
| C100-3 | Mailbox-only install writes both client hook surfaces and is idempotent. | clean installer fixture | A |
| C100-4 | Inside Success receives the bounded installer and a fresh live request completes send -> observe -> acknowledge. | installed-repo readback and retained IDs | B |
| C100-5 | Plan #67 and operator guidance stop claiming the old CLI pilot proves live reasoning-agent delivery. | source review | A |

## Failure Controls

- malformed hook JSON returns a visible warning;
- missing or unknown session identity does not create an observation receipt;
- wrong recipient cannot acknowledge;
- acknowledged request is absent from later hook output;
- installer dry-run may touch only the declared mailbox allowlist.

## Verification Gap Found During Rollout

The first Inside Success rollout exposed that the clean installer fixture had
preloaded `coordination_claims.py` and the other lifecycle dependencies. A real
partial local package did not have them, so the installed mailbox CLI failed at
import time. The installer now owns the complete local dependency closure and
the fixture starts from the same partial-package condition. This finding is
retained here because the ecosystem verification-gap log was actively claimed
by another lane when discovered.

## Verification

```bash
pytest -q tests/test_coordination_messages.py tests/test_generate_hook_wiring.py tests/test_install_governed_repo.py
ruff check enforced_planning/coordination_messages.py enforced_planning/hook_wiring.py scripts/coordination_hook.py tests/test_coordination_messages.py tests/test_generate_hook_wiring.py tests/test_install_governed_repo.py
mypy --strict enforced_planning/coordination_messages.py enforced_planning/hook_wiring.py scripts/coordination_hook.py
python scripts/self_test.py
```

## Promotion Claim

Passing proves lifecycle-triggered delivery for installed Claude and Codex
clients and a live bounded receipt chain. It does not prove interruption of an
idle unmanaged client, guaranteed latency without lifecycle activity, or that a
recipient completed the requested work.

## Completion Record

- Framework implementation: `enforced-planning` commits `b6118ec` and
  `15457d8`; 48 focused tests, Ruff, strict mypy, and framework self-test pass.
- Inside Success rollout: commit `8806c8e`; bounded installer rerun is
  idempotent with no blockers.
- Installed contract chain: message `msg_c187690c4d18985188538afa3a1e8580`
  produced observation receipt `rcpt_f4ec2a5bff3ff31bb70aa0873923eeb9`
  and acknowledgement receipt `rcpt_a9b73c2f3b46755ee557e70994f7e7ae`.
- Real native-client control: Codex thread
  `019f6c48-2118-78f3-a60f-bf0806e632db` resumed with the reviewed project
  hook and reported `msg_9358a988aa2e282408ae0fad4f459e55` plus subject
  `Native resumed-session proof` without tools. Independent canonical status
  then showed observation receipt `rcpt_29273069ac90797a258e4b7e2014305d`
  and exact-recipient acknowledgement receipt
  `rcpt_a4ff204dbc8c8f699aa8e170fc972fd8`.
- Acknowledged-message negative control: a later direct lifecycle invocation
  emitted no mailbox context for the acknowledged request.

Users must still trust new or changed project hooks once through Codex `/hooks`.
An idle unmanaged client is not asynchronously interrupted; delivery occurs on
the next configured lifecycle event.
