# Plan #67: Cross-Client Mailbox and Acknowledgement

**Status:** Complete
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9 — fleet adoption and framework maintenance"
**goal_ref:** "autonomous-agent-control-plane"
**adrs_referenced:** []
**research_citations:** []
**Blocked By:** None
**Blocks:** trustworthy Claude Code ↔ Codex coordination without human copy/paste

## Authorization and execution profile

Brian authorized the original planning work on 2026-07-15 and authorized the
bounded Codex app-server steering spike on 2026-07-15 after reviewing external
prior art. That initial authorization covered only Slice 0's disposable
instrument and retained readout.

Brian authorized this agent to take over implementation on 2026-07-15. Slice 1
landed first as the canonical message/receipt walking skeleton. Brian then
approved continuing the documented plan and explicitly authorized this agent
to take over implementation, activating Slice 2 lifecycle wiring, installer
rollout, concern-router cutover, and the bounded bidirectional pilot.

- Request mode: `plan_and_implement` for Slices 1 and 2
- Design depth: Standard
- Execution profile: `production-internal` — coordination state can redirect
  work in shared repositories, but all current operators are trusted.
- Overlays: runtime-state and repository-governance

## Objective

Give Claude Code and Codex sessions one client-neutral, durable way to send,
observe, and acknowledge coordination messages using the existing canonical
session/claim identity model. A sender must be able to distinguish `persisted`
from `observed` and `acknowledged`; no filesystem write may be represented as
delivery by itself.

## Non-goals

- Do not claim arbitrary existing standalone CLI sessions are steerable.
- Do not build a production background daemon, chat product, task queue, or
  assignment scheduler before Slice 0 resolves the app-server ownership seam.
- Do not redefine session, claim, lane, or plan authority.
- Do not automatically resolve write conflicts or authorize another lane.
- Do not require GitHub or network access for the local mailbox path.
- Do not preserve the legacy Claude-only inbox as a second authority.

## Gap

**Current:** `scripts/worktree-coordination/send_message.py` writes Markdown to
a repository-local `.claude/messages/inbox/` directory and explicitly targets
another Claude Code instance. Claude hooks may inspect that inbox when enabled.
Codex has no equivalent consumer or acknowledgement path. Published lanes can
receive a durable PR comment through concern routing, but neither path proves
that the target session observed the message.

**Target:** One package-backed message contract and CLI resolves recipients
through the existing session/claim registry, stores immutable messages and
append-only observation/acknowledgement receipts, and supports lifecycle polling
from both client adapters. PR comments remain a declared fallback projection
for published lanes, not the mailbox authority. Managed Codex sessions may also
receive an event-driven delivery acceleration through their owning app-server;
lifecycle polling remains recovery for offline or unmanaged clients.

**Why:** Missing delivery semantics forces Brian to copy messages between
agents, while broad claims can unnecessarily stall unrelated work because no
reliable request/acknowledgement channel exists.

## References reviewed

- `EXECUTION_BRIEF.md` — Phase 9 maintenance scope and canonical descent
- `PLANNING_OPERATING_MODEL.md` — canonical bounded planning and evidence model
- `docs/overview/CURRENT_STATE.md` — current claim that coordination/session
  infrastructure exists and the repo is in maintenance mode
- `docs/overview/GAP_SUMMARY.md` — current self-hosting gap and active Plan 55
  scope; Plan 67 remains a separate observed coordination correction
- `adr/0009-doc-authority-governance-and-enforcement.md` — concern-specific
  authority and deterministic enforcement
- `adr/0010-agent-memory-as-planning-input.md` — required memory recall and
  separation of session claims from operational findings
- `docs/designs/RECURSIVE_DOCUMENTATION_SPINE_AND_REQUIRED_READ_CLOSURE.md` —
  authority ancestry and bounded required-read closure
- `docs/plans/41_doc-authority-governance-and-enforcement.md` — authority config
  ownership and rollout
- `docs/plans/54_recursive-documentation-spine-and-required-read-closure.md` —
  frozen recursive-spine design
- `docs/plans/55_enforced-planning_recursive_doc_spine_dogfood.md` — current
  bounded self-hosting slice; Plan 67 must not absorb or bypass it
- `scripts/worktree-coordination/send_message.py` — legacy Claude-only sender
- `scripts/worktree-coordination/check_messages.py` — legacy reader/mutating
  acknowledgement surface
- `hooks/claude/worktree-coordination/check-inbox.sh` — Claude write-boundary
  consumer
- `hooks/claude/worktree-coordination/notify-inbox-startup.sh` — Claude startup
  notification
- `enforced_planning/concern_routing.py` — PR-comment/local-inbox fallback
- `enforced_planning/coordination_claims.py` — canonical session and claim model
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — current capability
  boundary, including no real-time presence or mid-session discovery
- `docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md` — shared runtime
  state architecture
- `docs/plans/29_session_heartbeats_and_agent_liveness.md` — liveness contract
- `docs/plans/32_cross_tool_session_adapters_and_adoption_rollout.md` — common
  Codex/Claude session adapter contract
- `docs/plans/35_queue-based-assignment-and-session-routing-architecture.md` —
  assignment/queue separation
- `project-meta` merge `db2d3b8e` — ISSUE-054 evidence that the legacy file
  inbox has no reliable Codex delivery path
- `investigations/cross-project/2026-07-15-cross-agent-communication-channel.md`
  — exact Plan 121 collision and delivery-path investigation
- `investigations/cross-project/2026-07-15-tailscale-ask-ui-and-codex-session-ids.md`
  — observed mapping between live Codex processes and native thread IDs
- `investigations/cross-project/2026-07-15-event-driven-agent-messaging-landscape.md`
  — current Codex, OpenHands, AutoGen, Hermes, Letta, and terminal-injection
  prior art; establishes runtime ownership as the live-delivery seam
- OpenAI Codex app-server documentation for `thread/start`, `turn/start`,
  `turn/steer`, version-generated protocol schemas, and streamed notifications
- OpenAI Codex issue #15299 and discussion #21558 — normal TUI inbound MCP
  notifications and multi-client app-server co-presence remain unsupported
- Memory recall: `agent-memory recall 'cross-agent messaging inbox Codex Claude
  coordination' --project enforced-planning` returned no relevant architectural
  finding.

The external research changed one earlier assumption: Codex has a concrete
native steering API when the controller owns the app-server session. The open
question is no longer whether injection exists; it is whether a broker-owned
session can support the desired operator workflow without a fork or unsupported
second-client attachment.

## Modality assessment

| Part | Mode | Why | Treatment |
|---|---|---|---|
| Message identity, lifecycle, persistence, and acknowledgement | Deductive | State and failure modes are predictable. | Freeze typed contracts and both-sign tests first. |
| Client lifecycle polling | Hybrid | Supported lifecycle boundaries are known, but actual visibility in live clients must be observed. | Deterministic adapter tests plus one Claude↔Codex pilot. |
| Managed Codex event delivery | Exploratory | App-server exposes `turn/steer` and `turn/start`, but multi-client/TUI ownership is unsettled. | Run one isolated version-pinned spike before designing a broker. |
| Unmanaged-client delivery | Hybrid | Lifecycle boundaries are known, but latency depends on client activity. | Retain durable polling and label it eventual. |

## Requirements

| ID | Requirement | Owner | Acceptance / disproof |
|---|---|---|---|
| M67-1 | Sending persists one immutable message with a globally unique ID and resolved sender/recipient session identities. | mailbox store | Same-ID retry is idempotent; unknown or ambiguous recipient fails. |
| M67-2 | Persistence, observation, and acknowledgement are distinct, inspectable states. | receipt projection | A persisted-only message never reports delivered or acknowledged. |
| M67-3 | Recipient resolution consumes the canonical claim/session registry; it does not create another identity system. | recipient resolver | Claim-scope resolution records one exact target session or rejects ambiguity. |
| M67-4 | Both Claude Code and Codex can poll and acknowledge through the same core library and CLI. | client adapters | Cross-adapter tests exercise identical stored records. |
| M67-5 | Offline recipients retain unexpired messages; expired messages remain auditable and cannot masquerade as active. | mailbox store/projection | Offline/expiry both-sign tests. |
| M67-6 | Published-lane PR comments are a durable fallback or projection, not evidence of mailbox observation. | concern router | Route result names its evidence ceiling. |
| M67-7 | Installed governed repos receive the same wrappers and documentation without copied business logic. | installer | Clean install/upgrade fixture invokes the package-backed commands. |
| M67-8 | The framework reports capability per runtime: managed app-server delivery may be event-driven when observed; unmanaged clients remain lifecycle-polled. | docs/support matrix | Terminology check rejects unsupported delivery claims and requires the applicable ownership boundary. |
| M67-9 | A managed Codex app-server session can accept one correlated message during an active turn and one while idle without patching Codex. | Slice 0 instrument | Version-pinned event transcript contains accepted `turn/steer`, later `turn/completed`, and a second `turn/start` on the same thread. |
| M67-10 | Runtime acceptance remains distinct from agent observation and acknowledgement. | delivery projection | The spike records protocol acceptance and model-visible evidence separately and never synthesizes acknowledgement. |

Passing these checks would prove a bounded local cross-client mailbox. It would
not prove low-latency delivery, remote multi-host synchronization, reliable
GitHub notification, or asynchronous interruption of a running agent.

## Boundaries

| Boundary | Owns | Inputs / outputs | Fails loud when | Forbidden responsibility |
|---|---|---|---|---|
| Recipient resolver | Mapping a session ID or claim selector to one recipient session | `RecipientSelector -> ResolvedRecipient` | recipient is missing, stale beyond policy, or ambiguous | Creating claims, choosing work, or authorizing overlap |
| Mailbox store | Immutable messages and append-only receipts | `CoordinationMessage`, `MessageReceipt` | duplicate ID differs, record is corrupt, or writer is not the resolved session | Current-status prose or client-specific hooks |
| Message projector | Derived lifecycle state | records -> `MessageStatusView` | receipt chain is inconsistent | Mutating source records |
| Core service/CLI | Send, poll, acknowledge operations | typed requests/results | validation or persistence fails | Tool-specific identity discovery |
| Client adapters | Session identity discovery and lifecycle invocation | environment/session context -> core requests | current session cannot be resolved | Owning message semantics or storage |
| Concern router | Optional PR-comment projection/fallback | message reference + branch | remote publication fails | Claiming PR comment equals observation |
| Managed Codex delivery adapter | Accelerating one persisted message into a broker-owned Codex thread | message + registered thread/turn -> runtime receipt | endpoint/version is unavailable, turn is not steerable, or expected turn changed | Owning mailbox truth, scraping transcripts, or attaching to arbitrary standalone TUIs |

## Domain model and lifecycle

```text
Session/Claim registry
        │ resolve
        ▼
CoordinationMessage (immutable)
        │ 0..n append-only receipts
        ▼
MessageReceipt: runtime_accepted | observed | acknowledged
        │ derive at read time
        ▼
MessageStatusView: persisted | runtime_accepted | observed | acknowledged | expired
```

`CoordinationMessage` owns content and routing intent. It never contains a
mutable `status`. `MessageReceipt` records a recipient observation or explicit
acknowledgement. A `runtime_accepted` receipt says only that the addressed host
accepted `turn/steer` or `turn/start`; it does not prove the model processed the
message. Expiry is derived from `expires_at` and the requested `as_of` time, not
written back into the message.

Allowed transitions are:

```text
persisted -> observed -> acknowledged
persisted -> acknowledged        # acknowledgement implies observation
persisted -> runtime_accepted -> observed -> acknowledged
persisted/observed -> expired     # derived when unacknowledged at as_of
```

An acknowledgement after expiry remains historical evidence but does not make
the expired message active again. Retrying `send` with the same ID and identical
canonical content is idempotent; different content under the same ID rejects.

## Contracts and schema disposition

The implementation should use strict Pydantic models with field descriptions
and package-owned serialization. Exact field names may change during the
implementation review only if the requirements and lifecycle remain intact.

### `CoordinationMessage`

- `schema_version`
- `message_id` (system-assigned)
- `sender_session_id`
- `recipient_selector` and resolved `recipient_session_id`
- `project`
- `kind`: `info | question | review_request | handoff | coordination_request`
- `subject`
- exactly one of `body` or `content_ref`
- `created_at`, `expires_at`
- optional `plan_ref`, `claim_ref`, `reply_to_message_id`

### `MessageReceipt`

- `schema_version`
- `receipt_id` (system-assigned)
- `message_id`
- `recipient_session_id`
- `event`: `runtime_accepted | observed | acknowledged`
- `recorded_at`
- for acknowledgements, `disposition`:
  `accepted | declined | deferred | information_only`
- optional `response_ref` and bounded note

### Operations

| Operation | Input | Output | Failure variants |
|---|---|---|---|
| `send_message` | sender context + recipient selector + content + TTL + optional idempotency key | persisted message summary | unknown/ambiguous recipient, identity mismatch, collision, storage error |
| `poll_messages` | current session + `as_of` + filters | ordered message views; optional observation receipts | unresolved session, corrupt record |
| `acknowledge_message` | current session + message ID + disposition | acknowledgement receipt + status view | wrong recipient, missing/expired policy violation, conflicting receipt |
| `message_status` | message ID + `as_of` | derived status and receipt chain | missing/corrupt record |

The managed Codex adapter is not added to the production contract until Slice
0 resolves the ownership seam. The spike uses the installed Codex-generated
JSON Schema rather than a hand-maintained protocol model and retains the exact
CLI version with its event transcript.

The existing coordination root remains the storage authority. Code must resolve
it through the established configuration/path helper; no hardcoded home path is
permitted. JSON records are canonical. Markdown and PR comments are derived
human-readable views.

## Capabilities

These are internal framework capabilities exposed through package-backed CLIs;
they are not a remote service or MCP surface.

| Capability | Input schema | Output schema | Producer | Consumers | Cost tier |
|---|---|---|---|---|---|
| `send_message` | `SendMessageRequest` | `PersistedMessageResult` | enforced-planning | Claude/Codex adapters, concern router | free |
| `poll_messages` | `PollMessagesRequest` | `MessagePollResult` | enforced-planning | Claude/Codex lifecycle adapters | free |
| `acknowledge_message` | `AcknowledgeMessageRequest` | `AcknowledgementResult` | enforced-planning | Claude/Codex lifecycle adapters | free |
| `message_status` | `MessageStatusRequest` | `MessageStatusView` | enforced-planning | agents and operators | free |

Implementation validation must provide strict described Pydantic inputs and
outputs, package-backed CLI registration, schema round trips, and the same core
call path for both client adapters.

## Backward runtime pass

Final operator claim: “recipient session X acknowledged message Y with
disposition Z.” That claim requires:

1. a valid acknowledgement receipt bound to Y and X;
2. an immutable Y whose resolver recorded X as the recipient;
3. a canonical session/claim record that resolved X at send time;
4. a caller whose current client adapter resolves to X; and
5. a status projection computed from the exact message and receipt set.

Therefore the CLI must return message/receipt IDs and evidence paths, and the
status view must expose the receipt-set digest or equivalent watermark. A
successful file write or PR comment cannot synthesize an acknowledgement.

### Worked step

1. A Codex session sends `coordination_request` to the session currently owning
   a DIGIMON claim, requesting that its broad `docs` claim be narrowed.
2. Recipient resolution records that claim's exact `session_id` in the immutable
   message.
3. The Claude or Codex owner polls at resume or a governed boundary, creating an
   `observed` receipt.
4. The owner acknowledges `accepted` and narrows the claim through the existing
   claim command.
5. The sender polls status and sees the acknowledgement receipt. The mailbox
   records the communication; the claim subsystem remains the sole owner of the
   actual scope change.

## Decisions and alternatives

| Decision | Chosen | Alternatives rejected / revisit trigger |
|---|---|---|
| State authority | Immutable JSON message plus append-only receipts | Mutating Markdown status loses event history. Revisit only if the coordination store adopts a transactional event backend. |
| Identity | Reuse session/claim IDs | Inbox-directory names create a second identity system. |
| Delivery semantics | `persisted`, `runtime_accepted`, `observed`, `acknowledged` | One `delivered` boolean overclaims what a file write proves. |
| Delivery | Durable mailbox plus capability-specific acceleration | Lifecycle-only polling is too latent for managed sessions; push-only delivery loses offline messages. |
| Managed Codex seam | App-server `turn/steer`/`turn/start`, conditional on Slice 0 | Hermes changes runtimes; tmux keystrokes are untyped; inbound MCP notifications do not enter normal Codex TUI sessions today. |
| Polling | Lifecycle-bound polling as recovery in both clients | A filesystem watcher alone cannot inject into unmanaged hosts. |
| Published lanes | PR comment as fallback/projection | GitHub notification is not a mailbox acknowledgement. |
| Migration | One-way import or tombstone for legacy unread messages; no dual-write after cutover | Permanent dual-write preserves two authorities. |

If this contract becomes a cross-repository public API, the implementation
slice must promote these decisions into an ADR before rollout. Until then this
plan is the bounded decision authority.

## Risk-ordered slices

### Slice 0 — Codex-native steering dependency spike

- Launch one disposable local Codex app-server owned by the instrument.
- Generate or consume protocol definitions from the installed Codex version.
- Start one thread and turn, then submit a uniquely identified `turn/steer`
  against the exact active turn.
- After completion, submit a second uniquely identified `turn/start` on the
  same idle thread.
- Retain a redacted JSONL protocol transcript, Codex version, command identity,
  thread/turn/message IDs, and a concise readout.
- Do not connect a second TUI client, patch Codex, implement mailbox storage, or
  generalize the instrument into a daemon.

**Success readout:** both protocol calls are accepted on the intended native
thread/turn, the active-turn injected marker becomes model-visible before that
turn completes, and the idle-turn marker is processed in the next turn.

**Disproof/inconclusive:** stop and retain evidence if `turn/steer` is rejected,
the marker is not model-visible, a second client or Codex patch is required, or
the installed protocol cannot be used without guessed fields. Passing proves a
single broker-owned Codex session is steerable; it does not prove TUI
co-presence, Claude parity, fleet migration, or durable delivery.

**Observed 2026-07-15:** the bounded dependency question passed on installed
Codex `0.144.1`, with an important lifecycle limitation. After waiting for the
native `turn/started` event, the app server accepted `turn/steer` for the exact
active turn and the injected marker appeared in agent output. The same thread
then accepted a new `turn/start` while idle and produced the second marker. No
Codex patch or second client was required. However, terminal-event delivery was
not reliable: one run omitted `turn/completed` after an agent answer, and the
clean no-tool run emitted `turn/completed` for the steered turn but not for the
following idle turn before the 120-second timeout. Therefore managed steering
is a viable acceleration seam, but a production adapter must recover through
status reconciliation and must not depend on every terminal notification.
Evidence and the bounded claim are summarized in
`docs/evidence/plan67_codex_app_server_spike/README.md`.

### Slice 1 — Canonical message and acknowledgement walking skeleton

- Add strict message, receipt, resolver, store, projection, and core operation
  contracts.
- Add package CLI wrappers for send, poll, status, and acknowledge.
- Test same-process Codex-identity sender to Claude-identity recipient and the
  inverse, including persistence-only, ambiguity, wrong-recipient, idempotency,
  corruption, offline, and expiry controls.
- No hooks, installer changes, PR comments, or legacy migration yet.

**Done when:** M67-1 through M67-5 pass with source+tests; a persisted-only
negative control remains unobserved; no legacy inbox file is consulted.

**Observed 2026-07-15:** Slice 1 is implemented in
`enforced_planning/coordination_messages.py` with thin source and installed-form
JSON CLI wrappers. The implementation derives its mailbox root from the
configured canonical claims directory, resolves only live claim/session
identities, writes integrity-wrapped immutable JSON messages and receipts,
quarantines corrupt records, and derives status plus a receipt-set digest.
Codex→Claude and Claude→Codex fixtures exercise the identical core path. The
67-test coordination/session regression set, focused Ruff, strict mypy, and
framework self-test pass. The repository-wide suite reports 641 passed, 1
skipped, and 12 failures in unchanged worktree/import-root tests; none exercise
the mailbox surface. Those baseline failures are retained as infrastructure
debt rather than being folded into this plan. Hooks, installer propagation,
concern-router cutover, and live cross-process acknowledgement remain Slice 2
work.

### Slice 2 — Client lifecycle and governed-repo adoption

- Wire Claude startup/governed boundaries and Codex session-start/resume plus
  governed CLI boundaries to the same package poll operation.
- Update concern routing to label PR comments as a fallback projection and
  return the mailbox evidence ceiling.
- Install wrappers/docs into a clean governed-repo fixture.
- Run one bounded live Claude→Codex and Codex→Claude send/observe/ack pilot.
- Tombstone or one-way import legacy unread messages, then remove dual authority.

**Done when:** M67-4 and M67-6 through M67-8 pass; the live pilot retains exact
message and receipt IDs; unsupported real-time claims are absent.

**Observed 2026-07-15/16:** shared session start, resume, and heartbeat results
now poll the same package mailbox for both clients, while the generated Claude
hook additionally injects notices after governed read boundaries. The governed
installer ships the package module and thin inbox wrapper, and its runtime
probe requires the package dependencies before hook rollout. Concern routing
now persists unpublished-lane concerns in the canonical mailbox and labels PR
comments `fallback_published`. The legacy Claude inbox hooks are compatibility
redirects that never read or mutate Markdown inbox state.

The retained pilot under `docs/evidence/plan67_mailbox_pilot/` exercised the
source command surfaces in separate processes for `codex:pilot-67` and
`claude-code:pilot-67`. Both directions produced an immutable message, an
observation receipt, and an explicit acknowledgement receipt. This is bounded
cross-process adapter evidence, not evidence that two independently reasoning
model sessions were asynchronously interrupted.

The terminal Slice 2 verification passed 71 focused coordination, lifecycle,
hook, installer, and router tests; focused Ruff and strict mypy; framework
self-test; and an isolated wheel build. The full suite reported 647 passed, 1
skipped, and the same 12 unrelated worktree/import-root baseline failures
already recorded by Slice 1.

### Future, only after evidence

Remote multi-host transport or asynchronous injection requires a new plan and a
concrete supported host/orchestrator API. It is not an extension hidden inside
Slice 2.

## Required tests

| Test surface | Required controls |
|---|---|
| message contracts/store | valid round trip; duplicate-same idempotency; duplicate-different rejection; corrupt record rejection |
| recipient resolver | exact session; unique active claim; unknown, stale, and ambiguous recipient rejection |
| lifecycle projection | persisted-only; observed; direct acknowledgement; expiry; acknowledgement-after-expiry history |
| authorization | sender identity mismatch and wrong-recipient acknowledgement reject |
| client adapters | Claude and Codex identities consume the identical core operations |
| installer | clean install and idempotent upgrade expose working package-backed wrappers |
| concern router | PR comment result is labeled fallback/projection, never acknowledged |
| live pilot | both directions produce observable message and acknowledgement receipts |

Proportional checks run per slice. The repository's full relevant gate runs only
at the terminal claim because this plan changes shared coordination contracts.

## Acceptance Criteria

| ID | Criterion | Required evidence | Current grade |
|---|---|---|---|
| C67-1 | One canonical message/receipt model distinguishes persistence, runtime acceptance, observation, acknowledgement, and expiry. | source + both-sign tests | A — strict source + both-sign filesystem tests |
| C67-2 | Recipient resolution reuses canonical session/claim identity and fails on ambiguity. | source + tests | A — live-claim resolver + unique/unknown/ambiguous tests |
| C67-3 | Claude and Codex use the same core send/poll/acknowledge operations. | source + adapter tests | A — bidirectional session-identity tests + shared CLI core |
| C67-4 | Governed-repo install/upgrade exposes the shared commands without copied logic. | clean fixture test | A — clean full/worktree installer fixtures and hook-generation tests |
| C67-5 | One live bidirectional pilot retains message and acknowledgement evidence. | observed run + retained receipts | B — observed cross-process pilot with exact integrity-wrapped records; not two live reasoning agents |
| C67-6 | Legacy inbox and PR comments cannot masquerade as acknowledged delivery. | negative tests + docs check | A — legacy non-consumption and PR fallback-evidence tests plus redirect docs |
| C67-7 | Support claims distinguish managed event-driven delivery from lifecycle-polled recovery and do not promise arbitrary-session interruption. | source/docs test | A — lifecycle/hook source, support matrix, operator guide, and adapter tests |
| C67-8 | One installed-version Codex app-server session accepts and processes correlated active-turn and idle-turn messages without a fork. | observed protocol transcript + bounded instrument test | B — observed on Codex 0.144.1; terminal-event reliability defect retained |

## Files Affected

Expected during implementation; the exact implementation owner must reconcile
this list against the reviewed codebase before activation.

- `enforced_planning/coordination_messages.py`
- `enforced_planning/coordination_claims.py` only if a public resolver is needed
- package-backed source CLIs under `scripts/meta/`
- installed wrappers under `scripts/`
- Claude hooks only for lifecycle invocation, not message semantics
- `enforced_planning/concern_routing.py`
- installer templates/config reference/operator guide/support matrix
- focused tests and one retained live-pilot evidence record
- temporary Slice 0 instrument and retained readout under a clearly exploratory
  path; remove or promote it after the decision
- ADR only if the seam is promoted to a public cross-repository contract

## Failure and recovery

| Failure | Response |
|---|---|
| recipient missing or ambiguous | Reject; require exact session or narrowed selector. |
| storage or record corruption | Reject and quarantine the record; do not silently skip it. |
| client cannot poll mid-session | Poll at the next supported lifecycle boundary and retain the honest capability label. |
| PR comment succeeds but mailbox does not | Report fallback publication only; never synthesize observation. |
| legacy migration cannot preserve identity | Leave a tombstone/read-only legacy view and require manual disposition; no guessed acknowledgement. |
| live bidirectional pilot fails | Keep support experimental and do not retire the human relay. |

## Completion record

Slices 0 through 2 are complete for the bounded claim. The canonical mailbox,
lifecycle-polled client path, Claude read-boundary acceleration, installer
propagation, concern-router evidence ceiling, compatibility redirects, and
bidirectional pilot evidence are present. Future remote transport or automatic
injection into arbitrary unmanaged sessions requires a separate plan and must
not weaken the persistence/observation/acknowledgement distinction established
here.
