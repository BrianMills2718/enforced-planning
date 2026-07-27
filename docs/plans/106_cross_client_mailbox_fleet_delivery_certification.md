# Plan #106: Cross-Client Mailbox Fleet Delivery Certification

**Status:** Planned — bounded design complete; implementation units require design adoption
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9 — fleet adoption and framework maintenance"
**goal_ref:** "cross-client-mailbox-delivery"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** linked
**Blocked By:** None
**Blocks:** Trustworthy ecosystem-wide Codex/Claude coordination without human relay

---

## Request Mode And Design Profile

- Request mode: planning and decomposition only
- Design revision: `mailbox-fleet-delivery-v1`
- Design depth: Standard
- Execution profile: `production_internal`
- Overlays: runtime state, operational service, repository governance, migration
- Landscape disposition: linked to Plans #67, #68, and #100 plus the current
  Codex lifecycle-hook contract
- Non-claim: this plan does not authorize implementation, configuration writes,
  repository rollout, hook trust, deployment, or message-driven work

## Gap

**Current:** The canonical JSON mailbox can persist, route, observe, and
acknowledge cross-client messages. The source repository contains Codex and
Claude lifecycle adapters, and the bounded installer can copy them into a
consumer repository. The current DIGIMON checkout nevertheless has no Codex
mailbox hook, no `.codex/hooks.json`, and no installed coordination hook
script. A real Plan #186 review message therefore remained `persisted` rather
than `observed`. User-level Codex and Claude hook configurations also do not
currently invoke the canonical mailbox adapter. Existing tests prove the core
and isolated installation fixtures, but there is no fleet drift gate or
host-level delivery certification.

**Target:** One host-level adapter installation makes the canonical mailbox
available to every claimed Codex and Claude session on the workstation,
regardless of which governed repository supplies its current working
directory. A read-only fleet audit distinguishes configured, drifted,
operationally observed, and acknowledged states. Portable repository hooks
remain supported during migration but cannot double-deliver messages. Four
real directions—Codex→Codex, Claude→Claude, Codex→Claude, and Claude→Codex—are
certified through exact message and receipt IDs.

**Why:** Ecosystem policy currently promises cross-client coordination more
broadly than the deployed hook surface supports. A persisted JSON file is not
evidence that a reasoning agent saw a request.

---

## User Outcome

An operator can send a coordination request from any claimed Codex or Claude
session to any other claimed Codex or Claude session on this workstation and
see whether the recipient actually observed and acknowledged it, without
copying the request manually.

## Canonical Behavioral Example

**Starting input/state:** Two live claimed sessions in different repositories,
one Codex and one Claude, have the canonical host adapters installed. No
repository-local mailbox hook is required.

**Action:** Codex sends a review request to the exact Claude session. Claude
performs its next configured lifecycle event and acknowledges the request.

**Expected observable result:** The sender queries one message ID and sees the
same exact recipient session ID plus ordered `persisted`, `observed`, and
`acknowledged` evidence. The recipient sees the request once per lifecycle
event despite any remaining repository-local compatibility hook.

**Behavioral evidence:** Unobserved for the host-level design. The existing
repository-local native Codex proof in Plan #100 is historical evidence only.

**Substrate/process evidence:** Plans #67/#68/#100; canonical mailbox models;
current installer and hook-wiring tests; current DIGIMON missing-hook
reproduction `msg_85bf2ccc122bc78c35c324ac26714d83`.

**Failure signal:** The message stays `persisted`; a hook reports success
without an observation receipt; the wrong session observes it; one lifecycle
event injects duplicate notices; or configuration presence is reported as
operational delivery.

---

## References Reviewed

- `CLAUDE.md` — framework ownership and consumer-installation boundary
- `docs/plans/67_cross_client_mailbox_and_acknowledgement.md` — canonical
  persisted/observed/acknowledged semantics
- `docs/plans/68_bounded_mailbox_fleet_rollout.md` — bounded consumer-repo
  installer profile
- `docs/plans/100_codex_mailbox_lifecycle_delivery.md` — repository-local
  native Codex lifecycle proof and limitations
- `enforced_planning/coordination_messages.py` — canonical message and receipt
  state machine
- `scripts/coordination_hook.py` — current Codex lifecycle adapter
- `hooks/claude/notify-coordination-messages.sh` — current Claude repository
  adapter
- `hooks/codex/notify-coordination-messages.sh` — current Codex repository
  adapter
- `enforced_planning/hook_wiring.py` — current repository-local hook merger
- `scripts/install_governed_repo.py` — bounded mailbox installer
- `scripts/upgrade_governed_repos.py` and `governed_repos.yaml` — current fleet
  registry and upgrade driver
- Current Codex manual, Hooks section — user and project hook layers, lifecycle
  events, and trust behavior
- Prior-session memory lookup was unavailable on 2026-07-27 because the
  embedding provider returned `insufficient_quota`; no memory result informed
  this design

## Research Basis For This Slice

No additional research beyond the current Codex hook contract and the
repository-local references listed above was needed.

## Landscape And Prior Art

- `docs/plans/67_cross_client_mailbox_and_acknowledgement.md`
- `docs/plans/68_bounded_mailbox_fleet_rollout.md`
- `docs/plans/100_codex_mailbox_lifecycle_delivery.md`

This plan extends the already-adopted canonical mailbox rather than building a
second broker. The Codex hook model supports user-level and project-level
`SessionStart`, `UserPromptSubmit`, and `PostToolUse` hooks; Claude already has
a user-level hook configuration on this workstation. The smallest durable
extension is therefore a host adapter and audit layer over the existing
mailbox, not terminal injection, a daemon, or a new network service.

**Alternatives:**

- Repository hooks only: rejected as the canonical path because missing or
  newly created repositories can silently escape the policy.
- Host hooks only with immediate repository-hook deletion: rejected for the
  first migration because portable consumer installations must remain usable
  on other workstations.
- Background daemon or TUI keystroke injection: rejected; it expands the trust
  and interruption boundary without being required for next-lifecycle-event
  delivery.
- New mailbox/broker: rejected; storage, routing, receipt, expiry, and identity
  contracts already exist.

**Project implication:** host adapters become canonical on Brian's workstation;
repository adapters become a declared compatibility surface. Duplicate
suppression is required before both may coexist.

**Refresh trigger:** Codex or Claude changes its lifecycle hook input/output or
trust model, or a second workstation becomes an active delivery target.

---

## Modality Assessment

| Part | Mode | Why | Planning treatment |
|---|---|---|---|
| Message/receipt semantics | Deductive | The canonical state machine exists. | Reuse unchanged and test exact identity/order. |
| Host hook installation | Deductive | Config locations and events are known. | Strict merge, backup, idempotence, and negative fixtures. |
| Duplicate suppression | Deductive | All matching hooks may run. | One event-delivery identity and both-sign tests. |
| Real cross-client delivery | Hybrid | Hook execution/trust is runtime state. | Deterministic fixtures first, then four real directions. |

**Exploratory readout:** none. Runtime certification records observed facts; it
does not search for thresholds.

**Step-down path:** every fleet summary row contains the repository/client,
configuration file, adapter digest, message ID, receipt IDs, event, and exact
failure reason.

---

## Boundaries And Ownership

| Boundary | Owns | Must not own |
|---|---|---|
| Canonical mailbox core | Message, routing, receipt, expiry, acknowledgement semantics | Hook installation or work authorization |
| Host adapter installer | Safe merge/audit of Brian's user-level Codex and Claude hooks | Repository feature code, automatic hook trust, client restart |
| Lifecycle adapter | Normalize client event/session/project and expose active messages | Recipient selection, acknowledgement inference, task authorization |
| Repository compatibility installer | Portable repo-local fallback and bounded drift repair | Claiming host-wide operation |
| Fleet auditor | Read-only configuration/install/receipt classification | Mutating configs or treating configuration as observation |
| Live certification | Four exact runtime receipt chains | General latency, idle interruption, or completion of requested work |

### Data flow

```text
sender -> canonical message store -> exact claimed recipient
       -> host lifecycle hook -> client adapter -> observation receipt
       -> agent-visible notice -> explicit acknowledgement receipt
       -> sender status query / fleet certification
```

Repository-local and host hooks may invoke the same adapter during migration.
The adapter must derive one `delivery_event_id` from client, session, lifecycle
event, and native event/turn identity when available. If the native event has
no stable ID, use a short-lived lock/receipt keyed by message, session, event,
and hook invocation timestamp bucket only for duplicate suppression; it must
not create acknowledgement or suppress later lifecycle events.

---

## Typed Contracts

Add strict Pydantic v2 models under `enforced_planning/mailbox_delivery.py`:

```python
class HookSurfaceV1(StrictContract):
    client: Literal["codex", "claude-code"]
    scope: Literal["host", "repository"]
    config_path: str
    configured_events: tuple[str, ...]
    adapter_command: str | None
    adapter_sha256: str | None
    configuration_state: Literal["absent", "drifted", "configured"]
    trust_state: Literal["unknown", "operationally_observed"]
    issues: tuple[str, ...]

class MailboxInstallationReceiptV1(StrictContract):
    schema_version: Literal["mailbox_installation_receipt.v1"]
    observed_at: datetime
    framework_revision: str
    host_surfaces: tuple[HookSurfaceV1, ...]
    repository_surfaces: tuple[HookSurfaceV1, ...]
    duplicate_delivery_risk: bool
    repair_actions: tuple[str, ...]

class DeliveryLegV1(StrictContract):
    sender_client: Literal["codex", "claude-code"]
    recipient_client: Literal["codex", "claude-code"]
    sender_session_id: str
    recipient_session_id: str
    message_id: str
    persisted_at: datetime
    lifecycle_event: str
    observed_receipt_id: str
    acknowledged_receipt_id: str

class MailboxDeliveryCertificationV1(StrictContract):
    schema_version: Literal["mailbox_delivery_certification.v1"]
    framework_revision: str
    installation_receipt_sha256: str
    legs: tuple[DeliveryLegV1, DeliveryLegV1, DeliveryLegV1, DeliveryLegV1]
    certified_at: datetime
```

Unknown fields are forbidden. Paths and commands may contain `~` but durable
artifacts must not contain Brian's resolved home path. Secret values and full
hook inputs are never retained.

### State and claim rules

1. `configured` means exact hook structure and adapter command are present; it
   does not mean Codex trusted the hook or a client executed it.
2. Only an exact observation receipt upgrades one client/session path to
   `operationally_observed`.
3. Only an explicit recipient acknowledgement creates `acknowledged` evidence.
4. A host and repository hook collision is `duplicate_delivery_risk` until the
   adapter proves per-event suppression.
5. A missing adapter or unsupported config shape fails loud before mutation.
6. Host-config writes preserve an exact timestamped backup outside Git and
   perform atomic replace only after parsing and re-reading the candidate.
7. Installation never marks a hook trusted and never claims a running client
   has reloaded configuration. The operator performs `/hooks` review and
   restart/resume as a separate runtime step.

---

## Fixtures And Negative Controls

- Valid Codex-only, Claude-only, and dual-client host settings.
- Existing unrelated hooks preserved byte-for-byte in semantic content.
- Missing config file creates only the required hook block.
- Malformed JSON/TOML blocks before backup or mutation.
- Duplicate host/repository hooks produce risk, then one visible message after
  suppression is enabled.
- Absent adapter, drifted adapter digest, wrong session, unknown claim,
  expired message, acknowledged message, and unsupported event all fail or
  remain hidden as required.
- A configured-but-never-run hook remains `trust_state=unknown`.
- Four live legs must use four distinct message IDs and exact receipt IDs.

---

## Compatibility, Failure, Recovery, And Deletion

- Existing message and receipt schemas remain unchanged.
- Existing repository installers remain supported during the migration.
- The host installer is idempotent and preserves unrelated hook entries.
- Any config write has a recoverable backup and prints its exact path.
- If the new hook fails, restore the backup and retain the failed audit receipt;
  do not delete mailbox messages or receipts.
- Repository hook deletion is deferred until the fleet auditor shows host
  operation for that client and a separate portability decision approves
  deletion. Plan #106 does not authorize that deletion.
- An idle unmanaged client is not asynchronously interrupted. The guarantee is
  delivery on the next configured lifecycle event.

---

## Plan

### Critical Path Classification

| Increment | Class | Behavior or named blocker changed |
|---|---|---|
| MF-01 | `enabler` | Makes configuration and runtime evidence mechanically distinguishable. |
| MF-02 | `direct_blocker` | Removes duplicate injection when host and repository hooks coexist. |
| MF-03 | `enabler` | Installs the accepted adapters but does not prove delivery. |
| MF-04 | `enabler` | Makes fleet drift visible without mutating consumers. |
| MF-05 | `vertical` | Demonstrates the user outcome in all four client directions. |

### Thin-Slice Skeleton

1. **MF-01 — host installation audit and safe config merger.** Implement typed
   read-only receipts and fixture-tested, dry-run-by-default host configuration
   planning. No real home config write.
2. **MF-02 — duplicate-safe shared lifecycle adapters.** Generalize the current
   Codex/Claude adapters around exact client/session/event identity and prove
   host plus repository hooks produce one notice per event.
3. **MF-03 — host rollout.** Back up, install, review, and activate Codex and
   Claude user-level hooks on this workstation.
4. **MF-04 — fleet read-only audit and bounded repository repair packets.** Scan
   `governed_repos.yaml`; report drift and one exact per-repository repair
   command without writing consumer repositories.
5. **MF-05 — four-direction live certification.** Retain exact send, observe,
   acknowledge evidence for all client pairs.

The machine-readable execution graph is
`docs/plans/106_cross_client_mailbox_fleet_delivery_work_graph.json`.

---

## Files Affected

Framework implementation units may touch only:

- `enforced_planning/mailbox_delivery.py` (new)
- `enforced_planning/coordination_messages.py`
- `scripts/audit_mailbox_delivery.py` (new)
- `scripts/install_mailbox_host_adapters.py` (new)
- `scripts/coordination_hook.py`
- `hooks/claude/notify-coordination-messages.sh`
- `hooks/codex/notify-coordination-messages.sh`
- `enforced_planning/hook_wiring.py`
- `scripts/install_governed_repo.py`
- `scripts/upgrade_governed_repos.py`
- `governed_repos.yaml`
- `tests/test_mailbox_delivery.py` (new)
- `tests/test_coordination_messages.py`
- `tests/test_generate_hook_wiring.py`
- `tests/test_install_governed_repo.py`
- `docs/reference/CONFIG_REFERENCE.md`
- this plan, work graph, plan index, and roadmap

Host rollout units may write only the reviewed hook portions of
`~/.codex/config.toml` and `~/.claude/settings.json` plus explicit backup files.
Consumer-repository mutation is excluded from this plan; MF-04 produces repair
packets for separately claimed repository units.

---

## Required Verification

```bash
pytest -q tests/test_mailbox_delivery.py tests/test_coordination_messages.py tests/test_generate_hook_wiring.py tests/test_install_governed_repo.py
ruff check enforced_planning/mailbox_delivery.py enforced_planning/coordination_messages.py scripts/audit_mailbox_delivery.py scripts/install_mailbox_host_adapters.py scripts/coordination_hook.py tests/test_mailbox_delivery.py
mypy --strict enforced_planning/mailbox_delivery.py scripts/audit_mailbox_delivery.py scripts/install_mailbox_host_adapters.py scripts/coordination_hook.py
python scripts/self_test.py
python scripts/validate_plan.py --plan-file docs/plans/106_cross_client_mailbox_fleet_delivery_certification.md
python <company-planning-work-unit-validator> docs/plans/106_cross_client_mailbox_fleet_delivery_work_graph.json
```

MF-03 additionally requires a before/after installation receipt, backup
readback, idempotent second dry run, Codex `/hooks` review, and fresh client
resume. MF-05 requires four real exact-session message chains.

## Acceptance Criteria

- [ ] Host Codex and Claude hook configuration is inspectable and idempotently
  repairable without overwriting unrelated hooks.
- [ ] Configuration, trust, observation, and acknowledgement are distinct
  mechanically enforced states.
- [ ] Host and repository compatibility hooks cannot double-inject one message
  for one lifecycle event.
- [ ] Fleet audit reports every registered governed repository as current,
  drifted, unavailable, or excluded with an exact reason.
- [ ] All four real client-direction legs have exact persisted, observed, and
  acknowledged evidence.
- [ ] Missing adapters, invalid configs, wrong identities, expired messages,
  and configuration-only false positives fail loud.
- [ ] No test, installer, or audit claims asynchronous interruption of an idle
  unmanaged client.

## Stop Conditions

- A client lifecycle event lacks enough identity to suppress duplicate
  host/repository delivery: stop MF-02 and return a bounded client-specific
  design revision.
- Host configuration cannot be parsed or safely backed up: stop before write.
- Hook trust cannot be established by the operator: retain `configured` and do
  not attempt MF-05 for that client.
- A consumer repository is dirty, employer-owned, archived, or lacks mutation
  authority: report it; do not repair it under this plan.
- Three materially different attempts at one live leg produce no new evidence:
  record the exact last state and resume event rather than manufacturing a
  receipt.

## Non-Goals

- No daemon, network broker, terminal injection, or arbitrary TUI attachment.
- No guarantee of delivery while the recipient has no lifecycle activity.
- No inference that a recipient performed the requested work.
- No automatic acknowledgement, hook trust, restart, or repository mutation.
- No replacement of the canonical claim/session registry.
- No secrets, transcripts, prompt bodies beyond the existing bounded message
  contract, or resolved personal home paths in committed evidence.

## Implementation Handoff

After Brian adopts design revision `mailbox-fleet-delivery-v1`, assign only a
unit whose work-graph `claimability` is `ready_for_execution`. The implementer
must read this plan and the exact unit record, claim only its conflict surfaces,
write tests before implementation, and stop rather than choosing a new hook
scope, trust policy, delivery guarantee, or consumer-repository rollout.
