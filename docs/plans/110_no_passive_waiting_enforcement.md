# Plan #110: No-Passive-Waiting Enforcement

**Status:** 🚧 In Progress — NPW-01 through NPW-03 accepted; NPW-04 blocked on its Project Meta bootstrap seam
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Coordination runtime maintenance"
**goal_ref:** "prevent-passive-waiting-without-erasing-real-blockers"
**Landscape disposition:** linked
**Blocked By:** None
**Blocks:** truthful autonomous continuation and recoverable dependency waits

## User Outcome

An agent may pause a unit, but it cannot represent an entire authorized goal as
blocked merely because one path or dependency is unavailable. The coordination
runtime must distinguish:

1. a blocked unit with other ready work;
2. a path-local integration wait;
3. a live session that has stopped producing durable progress; and
4. a genuine whole-goal blocker with no safe authorized next action.

When a genuine blocker exists, the system preserves the work and records the
exact resume event. It does not leave broad write ownership active indefinitely,
delete work, rebase a dirty branch, or force a takeover. Brian sees either the
next useful unit or a concrete blocker and resume event, rather than an agent
silently waiting on another agent.

## Canonical Behavioral Example

A plan graph contains three units:

- `A` is blocked on another agent's contract;
- `B` is independent and ready;
- `C` depends on `A`.

An attempt to mark the goal blocked must return `continue_ready_work` with `B`.
It must not create a whole-goal blocker or retain an idle broad claim. If `B`
does not exist and `A` requires a named human decision, the runtime records the
blocker, evidence, owner and resume event, retires or narrows idle write
ownership through the existing safe lifecycle, and returns control.

## Gap

- `CONTINUOUS_EXECUTION_CONTRACT.md` already says a blocked task is not a stop
  condition, a path conflict is only an `integration_wait`, and the complete
  authorized ready queue must be evaluated before reporting a goal blocked.
- `ClaimCheckResult.continuation()` already returns path-local continuation
  advice, but the claim/session lifecycle does not enforce a structured blocker
  decision.
- Heartbeats prove probable liveness. They do not prove advancement.
- Historical branch `origin/plan-70-progress-leases` at `2d56f6c` implemented a
  report-only progress lease, but it is 228 main-side commits behind the design
  baseline observed for this plan and never landed on `main`. Its design and
  tests are salvage inputs, not current execution evidence.
- Plan 70 also allowed a `blocker` event to renew progress. Plan 110 rejects
  that rule: recording a blocker is lifecycle evidence, not advancement.

Plan 110 supersedes Plan 70's unmerged integration proposal while preserving
its core separation of heartbeat, progress and ownership.

## Landscape And Prior Art

The landscape disposition is `linked`: the
[continuous execution contract](../guides/CONTINUOUS_EXECUTION_CONTRACT.md),
[coordination operator guide](../guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md),
and the unmerged Plan 70 implementation at `2d56f6c` establish the relevant
local prior art. This plan extends rather than replaces the canonical
claim/session model. The Kubernetes-style distinction adopted by Plan 70
remains useful: a live controller can fail to progress, and reporting that
condition must not itself destroy or take over the workload.

## References Reviewed

- `CLAUDE.md`
- `PLANNING_OPERATING_MODEL.md`
- `ROADMAP.md`
- `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `enforced_planning/coordination_claims.py`
- `enforced_planning/session_lifecycle.py`
- `enforced_planning/plan_readiness.py`
- `origin/plan-70-progress-leases` at `2d56f6c`

## Scope

### Included

- explicit durable progress distinct from heartbeat and lifecycle events;
- deterministic stalled-lane reporting without automatic takeover;
- a typed blocker request and system-produced blocker disposition;
- graph-backed ready-queue evaluation for work-graph-bound lanes;
- safe behavior when complete ready-queue coverage is unavailable;
- mailbox delivery evidence when waiting depends on another agent seeing a
  message;
- installed-repository wrappers, operator status, and focused fleet adoption.

### Excluded

- automatic deletion, force-rebase, merge, reassignment, or branch takeover;
- semantic judgment about whether an agent's work is valuable;
- a general autonomous scheduler;
- changing company-planning's dependency semantics;
- implementing the separate ecosystem-feedback system;
- requiring a work graph for reversible single-writer work.

## Requirements

| ID | Requirement | Acceptance | Provenance |
| --- | --- | --- | --- |
| NPW-1 | Heartbeat, progress, blocker and ownership state remain distinct. | Heartbeat and blocker negative tests cannot change `progress_at`. | explicit_user + reproduced_failure |
| NPW-2 | A path conflict cannot become a whole-goal blocker. | The canonical fixture returns `integration_wait` and identifies compatible work. | governing_authority |
| NPW-3 | A graph-backed goal cannot be blocked while an eligible unit is ready. | A blocked request with unit `B` ready is rejected with `continue_ready_work`. | explicit_user |
| NPW-4 | A genuine blocker is concrete and resumable. | The receipt names scope, class, evidence, dependency owner when known, and an observable resume event. | explicit_user |
| NPW-5 | Idle write authority is not retained solely to wait. | A true terminal wait narrows, hands off, or session-ends claims through an existing safe lifecycle; dirty/unique work remains recoverable. | governing_authority |
| NPW-6 | A persisted mailbox message alone cannot justify waiting for another agent. | Dependency receipt requiring agent delivery rejects `persisted` and accepts the configured `observed` or stronger state. | derived_current_boundary |
| NPW-7 | Incomplete queue knowledge is represented honestly. | Missing/stale/unbound graph returns `queue_coverage_unavailable`, never `goal_blocked_verified`. | derived_current_boundary |
| NPW-8 | Existing claims remain readable during rollout. | Legacy fixtures retain their prior health and ownership semantics. | derived_current_boundary |

Passing these criteria does not prove that every agent follows prose
instructions or that progress evidence is semantically honest. It proves the
canonical lifecycle cannot positively certify passive waiting as a verified
whole-goal blocker.

## Boundaries

| Boundary | Owns | Must do | Must not do |
| --- | --- | --- | --- |
| Claim/session lifecycle | ownership, liveness and safe lane retirement | persist explicit progress and blocker references; preserve existing closeout protections; retire only the selected goal root and descendants | infer business value, delete stalled work, or end unrelated roots owned by the same runtime |
| Ready-queue evaluator | one revision-bound queue readout | inspect the bound work graph, dependencies and active claims; return coverage and eligible alternatives | mutate claims or reinterpret unit objectives |
| Blocker policy evaluator | disposition decision | combine blocker request, queue readout, claim conflicts and required mailbox state | trust an agent's unsupported “nothing else is ready” assertion |
| Status surfaces | derived operator/agent views | expose last progress, blocker, alternatives, recovery and evidence | become a second authority |
| Installed consumer | wrapper and compact instruction | invoke the same canonical package behavior | fork lifecycle semantics downstream |

## Typed contracts

### `ProgressEventV1`

```text
recorded_at: server UTC timestamp
kind: claim_started | verified_commit | accepted_artifact |
      new_diagnostic | integration_result
evidence_ref: non-empty durable reference
next_action: non-empty concrete action
expected_quiet_until: optional bounded UTC timestamp
quiet_reason: required with expected_quiet_until
```

Heartbeat, `blocker_recorded`, `handoff`, and file modification are not progress
kinds. Quiet time suppresses a warning until its deadline but does not renew
progress.

### `ReadyQueueEvaluationV1`

```text
evaluation_id
session_id
goal_or_graph_scope
work_graph_ref: path + sha256 + design/spec revision, when bound
claim_snapshot_sha256
coverage: complete | partial | unavailable
eligible_unit_ids[]
blocked_unit_ids[] with typed blocker/gate references
terminal_unit_ids[]
active_or_indeterminate_unit_ids[]
active_conflict_unit_ids[]
evaluated_at
```

Only `coverage=complete` can support `goal_blocked_verified`. A path-local claim
collision remains an `integration_wait` even when it prevents the current unit.
The graph identity is repository-relative, and the evaluation identity binds
that path, exact graph bytes, and the canonical claim-snapshot digest. Its
numbered filename must match the project-qualified plan identity. A live claim
for a known unit with missing or mismatched graph binding makes coverage
unavailable instead of silently exposing owned work as eligible. Terminal units
do not mask a genuine remaining blocker; an all-terminal graph, active or
indeterminate work, invalid readiness, or a hard-dependency cycle cannot prove
goal blockage. Observation timestamps remain in receipts but are excluded from
stable evaluation and disposition identities when the source state is unchanged.

### `BlockerRequestV1`

```text
session_id
claim_scope
blocked_scope: path | unit | goal
blocked_item_refs[]
blocker_class: hard_dependency | human_decision | external_authority |
               external_system | required_data | irreversible_shared_action |
               path_conflict | unknown
evidence_refs[]
dependency_owner: optional
resume_event: concrete observable condition
mailbox_dependency: optional message_id + required_delivery_state
requested_claim_action: retain_narrow | handoff | session_end
```

The request is evidence supplied by the agent. It is not itself the blocker
decision. Path-scoped references must be canonical portable repository-relative
paths; dot, traversal, absolute, duplicate, empty, and backslash forms fail
contract validation.

### `BlockerDispositionV1`

```text
request_ref
ready_queue_evaluation_ref
decision: continue_ready_work | integration_wait | goal_blocked_verified |
          blocker_unverified_return_control | human_decision_required
alternative_unit_ids[]
claim_action: retain_narrow | handoff_scope | retire_goal_scope | none
reason_codes[]
evidence_refs[]
resume_event
recorded_at
application_authorized: false in the provider-free diagnostic slice
```

The deterministic evaluator owns `decision`. The agent cannot directly write a
verified blocked state. The read-only CLI returns a replayable envelope carrying
both the exact `ReadyQueueEvaluationV1` and its `BlockerDispositionV1`; the
disposition reference therefore never points to an omitted derived queue.
NPW-02 dispositions are diagnostic and cannot authorize claim mutation. NPW-03
must atomically reload the canonical claim registry, resolve the graph bytes
from that claim's repository root plus repository-relative graph reference,
recompute the queue and disposition, and refuse application unless both stable
IDs match the supplied envelope. Only that lifecycle boundary may emit a
separate application receipt.

The public CLI additionally binds `session_id` to the exact native invoking
runtime before loading canonical claims. A fabricated identity cannot suppress
a self-conflict or manufacture an other-session conflict.

## Capability Adoption

**Disposition: extend.** Extend the existing Enforced Planning claim/session
lifecycle and canonical installer manifests. Do not introduce a second queue,
claim registry, scheduler, or consumer-owned wrapper implementation.

## Capabilities

| Capability | Input schema | Output schema | Producer | Consumer(s) | Cost tier |
| --- | --- | --- | --- | --- | --- |
| `record_progress_event` | owning claim selector + `ProgressEventV1` | updated claim identity + timestamp | claim/session lifecycle | status surfaces and owning agents | free |
| `evaluate_ready_queue` | revision-bound work graph + claim snapshot | `ReadyQueueEvaluationV1` | readiness evaluator | blocker policy evaluator | free |
| `decide_blocker_disposition` | `BlockerRequestV1` + revision-bound graph, claim snapshot, and mailbox evidence | queue + `BlockerDispositionV1` envelope | blocker policy evaluator | sanctioned lifecycle command and status views | free |
| `apply_blocker_disposition` | accepted disposition + selected goal-root identity | scoped lifecycle receipt | session lifecycle | agents, operators and installed governed repos | free |

## Decision rules

1. A path conflict produces `integration_wait` only when an exact-bound live
   other-session claim overlaps the requested path; an agent assertion alone
   remains unverified and never proves the goal blocked.
2. Complete queue coverage plus at least one eligible unit produces
   `continue_ready_work`.
3. A required mailbox dependency below its required delivery state produces a
   delivery/escalation action, not evidence that the recipient is working.
4. Complete queue coverage, zero eligible units, and a supported stop-condition
   blocker may produce `goal_blocked_verified`.
5. Partial or unavailable coverage cannot produce verified goal blockage. The
   system records `blocker_unverified_return_control`, preserves evidence, and
   releases or narrows idle ownership rather than pretending certainty.
6. Stalled progress is report-only. It prompts record-progress, move, handoff,
   or session-end; it never seizes ownership automatically.
7. All claim mutations reuse existing atomic claim/session lifecycle writers.
   If no existing writer can retire exactly one selected goal root and its
   descendants, add that scoped operation rather than calling the global
   `session-end` operation, which may own unrelated authorized roots.

## State transitions

```text
active + unit blocked + ready alternative
  -> active on another unit; blocker receipt retained

active + path collision
  -> integration_wait for affected path; compatible work remains available

active + complete queue + no ready work + supported blocker
  -> verified blocker receipt -> narrow/handoff_scope/retire_goal_scope

active + incomplete queue knowledge + no claimed next action
  -> unverified blocker receipt -> return control -> narrow/handoff_scope/retire_goal_scope

fresh heartbeat + expired progress
  -> stalled report; ownership unchanged until explicit safe lifecycle action
```

## Failure behavior and negative controls

| Failure | Required behavior | Negative control |
| --- | --- | --- |
| Agent repeatedly heartbeats while doing no durable work | status becomes `stalled` after configured lease | heartbeat leaves progress fields unchanged |
| Agent records a blocker to renew progress | reject progress kind; store blocker separately | blocker timestamp cannot alter `progress_at` |
| Agent says “waiting” while another unit is ready | return the exact alternative and deny verified goal block | canonical A/B/C fixture |
| Work graph is stale or missing | return unavailable coverage and no verified blocker | stale-digest and absent-graph fixtures |
| Mailbox message is merely persisted | do not treat recipient as engaged | persisted versus observed receipt fixture |
| True blocker has dirty or unique work | preserve work and use handoff/session-end; no deletion | dirty-worktree lifecycle fixture |
| Progress deadline is noisy for a legitimate long operation | bounded quiet interval suppresses only until declared time | before/after quiet-deadline fixture |
| Agent fabricates a plausible evidence reference | report-only visibility exposes reference; semantic validation remains a promotion concern | no automatic destructive response |

## Plan

The implementation order is risk-based. Slices 1-3 are `vertical`; Slice 4 is
an integration `direct_blocker` for fleet use; Slice 5 is exploratory
`hardening` and cannot redefine the implemented capability.

### Slice 1 — Current-main progress visibility

**Epistemic state:** `fully_specifiable_now`.

Port the useful Plan 70 behavior onto current `main`, correct the blocker-as-
progress defect, and prove claim write → classifier → registry/session output.
No ownership action is triggered by a stall.

**Accepted 2026-08-21.** Candidate `419ffc7` adds exact-owner durable progress
events, one frozen-clock weak/stale/stalled classifier, report-only stalled
ownership, registry/session recovery context, and additive legacy-claim
compatibility. The authentic live claim recorded an `integration_result` at
`2026-08-21T08:13:33.950867Z`; both session status and a freshly generated
registry reported the exact `commit:419ffc7` evidence and next action while
the claim remained healthy and owned. The stable focused suite passed 250
tests, generated instruction sync and diff checks passed, no new synthetic
test receipts entered the live ledger, and all three independent reviews
accepted the candidate.

### Slice 2 — Provider-free blocker decision

**Epistemic state:** `fully_specifiable_now`.

Given the A/B/C work-graph fixture and a `BlockerRequestV1`, return a validated
`BlockerDispositionV1`. Add a second fixture in which the same runtime owns an
unrelated authorized root. This slice is read-only and proves the policy before
it can change ownership.

**Accepted 2026-08-21.** Candidate `57863d6cbd596348f42427d21c80d8fb124cec27`
implements the source-bound evaluator and public CLI. The replayable receipt at
`docs/evidence/plan110_npw02_owner_calibration.json` preserves 11 exact graph,
request, claim/mailbox and full-result envelopes plus the historical native
claim snapshot. Its checked-in replay test passes all positive and negative
signs; 85 focused tests, Ruff, diff-check and canonical graph validation pass.
Independent code and evidence audits both accepted NPW02-A1 at Grade A. Every
disposition remains diagnostic with `application_authorized=false`.

### Slice 3 — Safe lifecycle application

**Epistemic state:** `fully_specifiable_now`.

Add the sanctioned session command that records the disposition and invokes
only the safe narrow, scoped-handoff, or scoped-retirement operations. Prove
idempotence and dirty-work preservation. Before any mutation, atomically rebind
the diagnostic envelope to canonical claim-registry and repository bytes and
require the recomputed queue and disposition IDs to match. If scoped retirement is missing,
implement it here; the unrelated-root fixture must remain active.

**Accepted 2026-09-13.** Candidate
`36636e923b1d967c3a0747f0e9afa02144c75837`, reconciled with upstream at
`6397093e51a46dd297ee276e885945972443b2e4`, adds the installed
`apply_blocker_disposition.py` command, canonical locked re-evaluation, a
root-plus-descendants lifecycle transaction, immutable application receipts,
and exact-native-owner replay checks. The evidence packet at
`docs/evidence/plan110_npw03_safe_lifecycle.json` binds both fixture receipts:
ready work leaves the registry unchanged, while a verified whole-goal blocker
session-ends only `goal-root` and `goal-child`. The unrelated root remains
active, dirty bytes remain unchanged, stale-owner application is rejected, and
replay emits no second executor. The blocker-policy suite passed 87 tests and
the installer suite passed 57 tests. This accepts only local lifecycle behavior;
it is not fleet deployment or authentic external shared-action evidence.

### Slice 4 — Installed-consumer integration

**Epistemic state:** `conditional`.

Propagate wrappers and a compact workspace instruction after the other agent's
universal-feedback bootstrap edit is integrated. The common invariant is that
one workspace bootstrap mentions both feedback routing and no-passive-waiting
without duplicating either system's detailed policy.

### Slice 5 — Fleet observation and enforcement calibration

**Epistemic state:** `exploration_required`.

Observe whether the progress lease produces useful or noisy stalled results.
The readout is stalled cases classified as genuine stall, legitimate quiet
work, missing progress instrumentation, or bad threshold. This may tune the
reporting deadline; it cannot authorize automatic takeover or deletion.

## Acceptance Criteria

- focused claim/session/registry tests for every rule and negative control;
- portable contract fixtures validated by producer and consumer;
- one installed-repository dry run showing a ready alternative prevents a
  verified whole-goal block;
- one true-blocker dry run showing evidence and resume event survive safe
  ownership retirement;
- full relevant repository suite at the terminal integration revision;
- no edits to the other agent's feedback implementation lane.

## Files Affected

- `adr/0012-progress-leases-separate-liveness-from-advancement.md`
- `adr/README.md`
- `enforced_planning/coordination_claims.py`
- `enforced_planning/session_contracts.py`
- `enforced_planning/session_lifecycle.py`
- `enforced_planning/active_work_registry.py`
- `enforced_planning/plan_readiness.py` or one new bounded queue-evaluator module
- `scripts/check_coordination_claims.py`
- `scripts/session_status.py`
- one new sanctioned blocker-session entrypoint
- installed wrapper sources owned by `scripts/install_governed_repo.py`
- focused claim, session, registry, readiness and installer tests
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md`
- `docs/reference/CONFIG_REFERENCE.md`
- `GETTING_STARTED.md`
- `docs/plans/125_planning_integrity_loop.md`
- `docs/plans/132_overbroad_claim_narrowing.md`

## Concerns and promotion triggers

- **Progress-reference honesty:** retain as a visible concern. Add semantic or
  artifact validation only after observed misuse makes it a direct blocker.
- **Unplanned work lacks complete queue coverage:** remain honest and return
  control without the `verified` claim; do not require a work graph universally.
- **Native final-answer wording is not interceptable by this runtime:** the
  compact workspace instruction guides agent speech; deterministic enforcement
  governs only canonical coordination state.
- **Automatic takeover:** deliberately deferred. Reconsider only after fleet
  evidence demonstrates a safe ownership/recovery policy.

## Reset boundary

Reset sequencing after two implementation increments or two elapsed hours
without one of these visible deltas: stalled progress shown correctly, the A/B/C
fixture returns `continue_ready_work`, or a true blocker safely retires idle
ownership. Do not add more coordination artifacts in place of one of those
behaviors.

## Next action

Keep `npw-04-workspace-bootstrap-integration` blocked until the Project Meta
bootstrap seam is integrated or released. Continue the broader outcome through
its other owner-local Enforced Planning and AES units; preserve NPW-03's exact
owner, scoped-retirement, unrelated-root, and dirty-work negative controls.
