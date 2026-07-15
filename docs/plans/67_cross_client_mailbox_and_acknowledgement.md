# Plan #67: Cross-Client Mailbox and Acknowledgement

**Status:** Planned
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9 — fleet adoption and framework maintenance"
**goal_ref:** "autonomous-agent-control-plane"
**adrs_referenced:** []
**research_citations:** []
**Blocked By:** None
**Blocks:** trustworthy Claude Code ↔ Codex coordination without human copy/paste

## Authorization and execution profile

Brian authorized this planning work on 2026-07-15. This document does not
authorize implementation. The future implementation owner must review the plan,
claim the exact paths, and explicitly activate it before changing runtime code.

- Request mode: `plan_only`
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

- Do not promise real-time interruption of a running agent.
- Do not build a background daemon, chat product, task queue, or assignment
  scheduler.
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
for published lanes, not the mailbox authority.

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
- Memory recall: `agent-memory recall 'cross-agent messaging inbox Codex Claude
  coordination' --project enforced-planning` returned no relevant architectural
  finding.

No external research is required. The design is constrained by observed local
client and coordination contracts.

## Modality assessment

| Part | Mode | Why | Treatment |
|---|---|---|---|
| Message identity, lifecycle, persistence, and acknowledgement | Deductive | State and failure modes are predictable. | Freeze typed contracts and both-sign tests first. |
| Client lifecycle polling | Hybrid | Supported lifecycle boundaries are known, but actual visibility in live clients must be observed. | Deterministic adapter tests plus one Claude↔Codex pilot. |
| Real-time interruption | Exploratory/out of scope | The host may not expose an injection callback. | Make no such claim; revisit only when a concrete host API exists. |

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
| M67-8 | The framework reports its actual capability as lifecycle-polled, not real-time. | docs/support matrix | Terminology check rejects unsupported delivery claims. |

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

## Domain model and lifecycle

```text
Session/Claim registry
        │ resolve
        ▼
CoordinationMessage (immutable)
        │ 0..n append-only receipts
        ▼
MessageReceipt: observed | acknowledged
        │ derive at read time
        ▼
MessageStatusView: persisted | observed | acknowledged | expired
```

`CoordinationMessage` owns content and routing intent. It never contains a
mutable `status`. `MessageReceipt` records a recipient observation or explicit
acknowledgement. Expiry is derived from `expires_at` and the requested `as_of`
time, not written back into the message.

Allowed transitions are:

```text
persisted -> observed -> acknowledged
persisted -> acknowledged        # acknowledgement implies observation
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
- `event`: `observed | acknowledged`
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
| Delivery semantics | `persisted`, `observed`, `acknowledged` | One `delivered` boolean overclaims what a file write proves. |
| Polling | Lifecycle-bound polling in both clients | Filesystem watcher/daemon adds operations without solving host injection. Revisit if a supported orchestrator callback exists. |
| Published lanes | PR comment as fallback/projection | GitHub notification is not a mailbox acknowledgement. |
| Migration | One-way import or tombstone for legacy unread messages; no dual-write after cutover | Permanent dual-write preserves two authorities. |

If this contract becomes a cross-repository public API, the implementation
slice must promote these decisions into an ADR before rollout. Until then this
plan is the bounded decision authority.

## Risk-ordered slices

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
| C67-1 | One canonical message/receipt model distinguishes persistence, observation, acknowledgement, and expiry. | source + both-sign tests | F — planned only |
| C67-2 | Recipient resolution reuses canonical session/claim identity and fails on ambiguity. | source + tests | F — planned only |
| C67-3 | Claude and Codex use the same core send/poll/acknowledge operations. | source + adapter tests | F — planned only |
| C67-4 | Governed-repo install/upgrade exposes the shared commands without copied logic. | clean fixture test | F — planned only |
| C67-5 | One live bidirectional pilot retains message and acknowledgement evidence. | observed run + retained receipts | F — planned only |
| C67-6 | Legacy inbox and PR comments cannot masquerade as acknowledged delivery. | negative tests + docs check | F — planned only |
| C67-7 | Support claims remain lifecycle-polled and do not promise real-time interruption. | source/docs test | F — planned only |

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

## Next action

The future owner should perform an isolated review of this plan, reconcile it
with any newer coordination-runtime changes, then activate Slice 1 in a claimed
worktree. No implementation should begin from this planning commit.
