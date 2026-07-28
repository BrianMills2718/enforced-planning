# Plan #106: Cross-Client Mailbox Fleet Delivery Certification

**Status:** In Progress — MF-01/MF-02/MF-03A/MF-04 accepted; MF-03B applied and awaits hook review/resume evidence
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

- Request mode: adopted planning and dependency-governed implementation
- Design revision: `mailbox-fleet-delivery-v2`
- Design depth: Standard
- Execution profile: `production_internal`
- Overlays: runtime state, operational service, repository governance, migration
- Landscape disposition: linked to Plans #67, #68, and #100 plus the current
  Codex lifecycle-hook contract
- Non-claim: design adoption does not authorize configuration writes,
  repository rollout, hook trust, deployment, or message-driven work outside
  the readiness and approval gates of the exact work unit.

### Adoption Record

Brian adopted design revision `mailbox-fleet-delivery-v1` on 2026-07-27. Brian
then approved the delegation-safety revision `mailbox-fleet-delivery-v2` on
2026-07-27: host candidate generation and host mutation are separate units.
MF-01, MF-02, and MF-04 remain valid `reuse_unchanged` outputs from v1. MF-03A
is accepted. Brian approved the exact MF-03A candidate digest on 2026-07-27;
MF-03B applied it on 2026-07-27 and remains open only for native hook review
and fresh client restart/resume evidence. MF-05 remains dependency- and
approval-gated in the work graph.

### MF-01 Implementation Record

Implementation commit `fafcdb0` added the typed receipt/audit/planning boundary,
the read-only JSON CLIs, and deterministic fixtures. Completion review then
closed four contract blockers: adapter digest comparison, client/session receipt
binding, portable durable paths, and valid complex-key TOML rendering. The
post-review gate passed 69 compatibility tests, 8 MF-01 selector tests, Ruff,
strict mypy, and diff checks. MF-01 is accepted. Its outputs were consumed by
the now-accepted MF-02 and MF-04 units.

### MF-02 And MF-04 Acceptance Record

MF-02 implementation commit `502cfeb` (merged as `bf35b48`) added one durable
delivery-event marker shared by Codex and Claude lifecycle adapters. Exact
host/repository duplicate, later-event repeat, missing-identity, wrong-session,
expired, and acknowledged controls pass. The acceptance selector passed 12
tests; Ruff, strict mypy, and diff checks passed. MF-02 is accepted.

MF-04 implementation commit `11f30e5` added the read-only fleet report and
bounded repair packets. Completion review found that resolved workstation paths
were retained in durable JSON; review-fix commit `3d33c97` replaced home-prefixed
paths with portable `~/...` values. The combined mailbox compatibility suite
then passed 77 tests; Ruff, strict mypy, and diff checks passed. MF-04 is
accepted. The real read-only report covered all 16 explicit registry entries
and separately reported 27 governed-looking omissions; those observations are
inventory evidence, not authority to mutate any repository.

### MF-03A Acceptance Record

MF-03A adds the strict `StoredHostInstallationCandidateV1` envelope and binds
the proposed Codex and Claude host-hook changes to exact before-config,
proposed-config, adapter, and framework hashes. Candidate generation rejects an
unknown framework revision, adapter drift, malformed host configuration, and a
digest-mismatched envelope. The full mailbox compatibility suite passed 77
tests; Ruff, strict mypy, and diff checks passed.

The real read-only candidate is retained locally at portable coordination path
`~/.claude/coordination/candidates/plan106-mf03a-host-candidate-20260727.json`.
Its `payload_sha256` is
`5e3936b23a642ba97418b83fcf03b151b65d80785ec81d9330464a4380ffa834`,
bound to framework revision `fffbec5217e3f66dd6c35d1ad723c83a0e197d78`.
Before/after hashes proved that neither host configuration changed. MF-03A is
accepted; this record is not readiness approval to apply the candidate.

### MF-03B Apply Record

Brian explicitly approved candidate payload SHA-256
`5e3936b23a642ba97418b83fcf03b151b65d80785ec81d9330464a4380ffa834`.
The applier rechecked the exact candidate envelope, framework revision, adapter
digest, and both before-config digests before mutation. It then created exact
readable backups under
`~/.claude/coordination/backups/mailbox-host/20260728T012000.360188Z-5e3936b23a64/`,
atomically installed both native hook configurations, parsed and hashed the
results, and produced a zero-action second dry run.

Codex changed from `a96437a8a82932da34aadb9e740c016dc462188d9aed9f3b414016aa846d19aa`
to `4587012899bb7f9f10bc3b1fbd1ebdd3db2474687b4dacd4f76ed85939e6977c`.
Claude changed from `29629433b3319947a290dfd212b8373711a66f631eea9e966b067569600a78ed`
to `a5ca8d31ec89ca04f0e92b073a2f6872a254892b39ab698de8892dbb3261607d`.
Backup digests equal the two before digests. The after audit classifies both
host surfaces as `configured`, with `trust_state=unknown`, no repair actions,
and no claim of live delivery. Deterministic tests include exact approval,
backup/readback, zero-action idempotence, wrong-digest preflight rejection, and
an injected second-write failure that restores both exact inputs. MF-03B is not
accepted until Codex `/hooks` review and fresh Codex and Claude restart/resume
state are recorded.

After apply, Codex `doctor` loaded the rewritten config successfully and
reported the hooks feature enabled. A direct exact-session adapter smoke then
observed message `msg_bf41b253ee384cbb7f6d761c41c00cd7` as receipt
`rcpt_3c24dd03cfe10b614b106c536dfa366c` and acknowledged it as receipt
`rcpt_b86ecbebaa8e179780ce5c9854b1c552`. This proves the configured adapter's
message/receipt boundary, but it does not substitute for native-client hook
trust or prove a newly started client invoked the hook.

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

## Capabilities

| Capability | Input schema | Output schema | Producer | Consumer(s) | Cost tier |
|---|---|---|---|---|---|
| `audit_mailbox_host_installation` | `HostInstallationAuditRequestV1` | `MailboxInstallationReceiptV1` | enforced-planning | Codex/Claude operators, fleet auditor | free |
| `plan_mailbox_host_installation` | `HostInstallationPlanRequestV1` | `HostInstallationPlanV1` | enforced-planning | controlled rollout unit | free |
| `query_mailbox_delivery` | `MailboxDeliveryQueryV1` | `MailboxDeliveryStatusV1` | enforced-planning | four-direction certifier, operators | free |

All contracts are Pydantic-backed and revision-bound. Repository-local adapters
may preserve compatibility during migration, but they cannot assert a host
installation, delivery observation, or acknowledgement without the producer's
durable receipt.

### Capability Validation

- [ ] Strict schema round trips cover both Codex and Claude configuration forms.
- [ ] Audit and dry-run planning have package-backed CLIs with stable JSON.
- [ ] A configured hook never substitutes for a runtime delivery observation.
- [ ] MF-05 records one complete receipt chain for each client direction.

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

class HostConfigFingerprintV1(StrictContract):
    client: Literal["codex", "claude-code"]
    config_path: str
    state: Literal["absent", "present"]
    before_sha256: str | None
    proposed_sha256: str
    adapter_sha256: str

class HostInstallationCandidatePayloadV1(StrictContract):
    schema_version: Literal["mailbox_host_candidate.v1"]
    framework_revision: str
    generated_at: datetime
    configs: tuple[HostConfigFingerprintV1, HostConfigFingerprintV1]
    plan: HostInstallationPlanV1
    will_write: Literal[False]

class StoredHostInstallationCandidateV1(StrictContract):
    record_type: Literal["mailbox_host_candidate"]
    payload: HostInstallationCandidatePayloadV1
    payload_sha256: str

class HostInstallationApplyReceiptV1(StrictContract):
    schema_version: Literal["mailbox_host_apply_receipt.v1"]
    candidate_payload_sha256: str
    applied_at: datetime
    backup_paths: tuple[str | None, str | None]
    before_sha256: tuple[str | None, str | None]
    after_sha256: tuple[str, str]
    second_dry_run_action_count: Literal[0]

class HostInstallationApplyFailureV1(StrictContract):
    schema_version: Literal["mailbox_host_apply_failure.v1"]
    candidate_payload_sha256: str
    failed_at: datetime
    failure_stage: Literal["preflight", "backup", "codex_write", "claude_write", "readback", "rollback"]
    backup_paths: tuple[str | None, str | None]
    rollback_completed: bool
    restored_sha256: tuple[str | None, str | None]
    error_code: str

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

MF-03A produces only hashes, portable paths, required hook changes, and counts;
it does not retain unrelated configuration values. `payload_sha256` is the
SHA-256 of canonical JSON for `payload`; the digest is stored in the outer
envelope and is never self-referential. `HostConfigFingerprintV1` validates that
`present` requires `before_sha256` and `absent` requires `None`. MF-03B may apply
only a candidate whose envelope `payload_sha256` has exact readiness approval
and whose current config and adapter hashes still match the candidate inputs.
Any mismatch invalidates the candidate and returns to MF-03A.

MF-03B backs up every config that exists; an absent config has a `None` backup
path and remains identified by its `absent` fingerprint. If any write or
readback fails after mutation begins, the applier restores every changed file
to its exact before state, verifies the restored hashes, and emits
`HostInstallationApplyFailureV1`. A failed or rolled-back attempt never emits a
success receipt or upgrades installation/runtime state.

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
| MF-03A | `enabler` | Produces an exact reviewable candidate without host writes. |
| MF-03B | `enabler` | Applies only the approved unchanged candidate; it does not prove delivery. |
| MF-04 | `enabler` | Makes fleet drift visible without mutating consumers. |
| MF-05 | `vertical` | Demonstrates the user outcome in all four client directions. |

### Thin-Slice Skeleton

1. **MF-01 — host installation audit and safe config merger.** Implement typed
   read-only receipts and fixture-tested, dry-run-by-default host configuration
   planning. No real home config write.
2. **MF-02 — duplicate-safe shared lifecycle adapters.** Generalize the current
   Codex/Claude adapters around exact client/session/event identity and prove
   host plus repository hooks produce one notice per event.
3. **MF-03A — exact host candidate.** Read the current Codex and Claude user
   configuration, bind the proposed change to config and adapter hashes, and
   emit a portable dry-run candidate. No host write or backup occurs.
4. **MF-03B — approved host apply.** After exact candidate-digest readiness
   approval, recheck all hashes, back up each present config, atomically replace
   each file with only the canonical mailbox hook additions, roll back the group
   on partial failure, parse/read back, and prove a zero-action second dry run.
5. **MF-04 — fleet read-only audit and bounded repository repair packets.** Scan
   `governed_repos.yaml`; report drift and one exact per-repository repair
   command without writing consumer repositories.
6. **MF-05 — four-direction live certification.** Retain exact send, observe,
   acknowledge evidence for all client pairs.

The machine-readable execution graph is
`docs/plans/106_cross_client_mailbox_fleet_delivery_work_graph.json`.

---

## Files Affected

Framework implementation units may touch only:

- `enforced_planning/mailbox_delivery.py` (new)
- `enforced_planning/mailbox_fleet_audit.py` (new)
- `enforced_planning/coordination_messages.py`
- `scripts/audit_mailbox_delivery.py` (new)
- `scripts/audit_mailbox_fleet.py` (new)
- `scripts/install_mailbox_host_adapters.py` (new)
- `scripts/coordination_hook.py`
- `hooks/claude/notify-coordination-messages.sh`
- `hooks/codex/notify-coordination-messages.sh`
- `enforced_planning/hook_wiring.py`
- `scripts/install_governed_repo.py`
- `scripts/upgrade_governed_repos.py`
- `governed_repos.yaml`
- `tests/test_mailbox_delivery.py` (new)
- `tests/test_mailbox_fleet_audit.py` (new)
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

MF-03A requires a portable candidate bound to the exact before-config and
adapter hashes and proof that neither host config changed. MF-03B requires the
exact candidate approval, before/after installation receipts, backup readback,
idempotent second dry run, Codex `/hooks` review, and fresh client resume.
MF-05 requires four real exact-session message chains.

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
- Host configuration cannot be parsed or fingerprinted: stop MF-03A without
  producing an executable candidate.
- MF-03B observes a config, adapter, or candidate digest different from the
  approved MF-03A artifact: stop before backup or write and regenerate MF-03A.
- Host configuration cannot be safely backed up: stop MF-03B before write.
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

Assign only a unit whose work-graph `claimability` is `ready_for_execution`.
The implementer must read this plan and the exact unit record, claim only its
conflict surfaces, write tests before implementation, and stop rather than
choosing a new hook scope, trust policy, delivery guarantee, or
consumer-repository rollout.

### Parallel Delegation Contract

One orchestrator must first own the unparented Plan #106 `program` root. Every
parallel worker is a child lane with `parent_scope` set to that exact root and a
narrow write claim for its unit's declared conflict surfaces. `--allow-parallel`
does not authorize multiple same-plan program roots; the one-root hierarchy is
intentional and mechanically enforced. If the parent root does not exist, the
operator must create it before spawning workers rather than bypassing the claim
gate or pretending one sibling unit owns another.

Current handoff order:

1. `mailbox-mf-03a-host-candidate` is accepted with the exact candidate digest
   recorded above.
2. `mailbox-mf-03b-host-apply` remains blocked until Brian approves that exact
   candidate `payload_sha256`.
3. `mailbox-mf-05-four-direction-live-certification` remains blocked until
   MF-03B is accepted and four exact live sessions are bound.
