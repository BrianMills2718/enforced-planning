# Plan #114: Outcome Continuation Lease Enforcement

**Status:** Planned
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "deny-circular-continuation-without-blocking-real-progress"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** poc
**Blocked By:** #62, #113
**Blocks:** [future] observe-mode session/claim integration and any fleet promotion

---

## Gap

**Current:** Plans #113 and #62 prove two configured governed-delivery tasks and
can require a course checkpoint after repeated unchanged probes. They do not
bind later coding-agent continuation to outcome evidence. A conversational
approval can still lead to another plan, worktree, repair, or rewrite after the
project has stopped advancing.

Project Meta proposal `outcome-continuation-lease-hard-gate` is approved at
revision `f6091b6b2f2a5357d0fdbbe88b157435a2ce07fb`. It explicitly separates
authorization from progress evidence and explicitly rejects cost, subscription,
and elapsed-time gates.

**Target:** Add native typed outcome, progress-receipt, lease, recovery, and
admission contracts plus one JSON CLI. Execute two revision-bound scenarios
against the stable Plan #62 consumer identity: authentic behavioral progress
permits the next in-scope operation, while two consecutive non-outcome
increments deny circular continuation even when the request contains ordinary
approval. Prove that changing cost telemetry does not change either decision.

**Why:** This is the smallest mechanism that can falsify the approved policy's
central claim before any hook wiring or fleet rollout.

## User Outcome

Brian can keep paying for and continuing work that produces genuine outcome
progress, while the supported workflow refuses another project-writing cycle
when the only new input is approval, motion, or repeated evidence.

## Canonical Behavioral Example

**Starting input/state:** An outcome contract is bound to the configured
`status-cli-json` governed-delivery consumer from Plan #62 and an initial active
lease. Its canonical result is the independently verified JSON behavior.

**Action A:** Submit a digest-bound `behavioral_advance` receipt for the
canonical journey, then request an in-scope product write.

**Expected result A:** Admission is allowed, the non-outcome counter is reset,
and the lease remains active. The result is unchanged whether cost telemetry is
absent, small, or large.

**Action B:** Starting from the same contract, submit two distinct
`non_outcome` receipts and request another product write with
`ordinary_approval=true`.

**Expected result B:** Admission is denied with `recovery_required`; the next
allowed actions are exact replay/readout, passive inspection, evidence
preservation, closeout, or one separately bound recovery action. Approval text
and cost telemetry do not renew or widen the lease.

**Behavioral evidence:** Unobserved until both CLI scenarios execute from a
clean implementation revision and their decisions are retained.

**Substrate/process evidence:** Focused transition, digest, replay, scope,
recovery, approval-invariance, and cost-invariance tests.

**Failure signal:** Circular input is allowed; genuine progress is denied; a
replayed receipt renews a lease; an out-of-scope operation is allowed; or
approval/cost changes a decision.

## References Reviewed

- `CLAUDE.md` — repository authority, development profile, and claimed-lane
  workflow.
- `PLANNING_OPERATING_MODEL.md` — outcome-first plan and authentic evidence
  requirements.
- `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md` — current continuation
  behavior that later enforcement must reconcile.
- `docs/plans/113_governed_delivery_authentic_vertical.md` — first authentic
  task, course checkpoint, and independent verifier.
- `docs/plans/62_user_neutral_ecosystem_instantiation.md` — configured second
  consumer and stable profile identity.
- `enforced_planning/governed_delivery.py` — existing capability owner and
  receipt/digest conventions.
- Project Meta
  `policy/proposals/2026-08-20-outcome-continuation-lease-hard-gate.yaml` at
  `f6091b6b` — approved policy and rollout limits.

## Research Basis For This Slice

No web research is required. This slice tests a locally approved policy against
existing local contracts and a retained authentic consumer. Executed both-sign
evidence is more decision-relevant than additional general research.

## Landscape And Prior Art

**Alternatives:**

1. Treat the existing `CourseCheckpointV1` as the portfolio lease — rejected
   because it is scoped to one generated task's repeated probes and does not
   govern later claims or writes.
2. Add lease state directly to `governed_delivery.py` — rejected because Plan
   #62 established a clean configurable delivery seam and continuation is a
   distinct lifecycle concern with future session/claim consumers.
3. Create a new repository or shared contract package — deferred until a
   second authentic implementation consumer creates that ownership seam.
4. Add a small native `outcome_continuation` module that consumes stable
   governed-delivery identity and digest conventions — adopted for this slice.

**Project implications:** Add only one module, one CLI, focused tests, two
scenario inputs, and one retained decision artifact. Leave existing delivery,
session, claim, hook, installer, and downstream-repository surfaces unchanged.

**Refresh trigger:** Revisit module ownership only after session/claim
integration demonstrates a cross-package seam, or if the Plan #62 receipt
cannot serve as an authentic consumer identity.

## Modality Assessment

| Part | Mode | Why | Planning treatment |
|---|---|---|---|
| Contract and digest validation | Deductive | Inputs and invariants are deterministic. | Pydantic models and both-sign unit tests. |
| Lease transitions | Deductive | Receipt classes and counters define exact state changes. | Table-driven transition tests. |
| Admission usefulness | Exploratory / ladder | A typed gate may still fail to distinguish useful progress from motion. | Execute one positive and one circular scenario; license only those observations. |
| Fleet hook integration | Exploratory / deferred | False blocks and bypasses require representative live flows. | Excluded until this vertical passes. |

**Exploratory readout:** The same implementation revision allows the genuine
progress scenario and denies the circular scenario for the intended reasons.

**Step-down path:** If the positive and negative cases cannot be distinguished,
retain the exact inputs and decisions, revise only the discriminating contract
or transition, and rerun the same pair before adding integrations.

## Boundaries And Non-Goals

Enforced Planning owns the staged typed contracts, transition logic, CLI, and
focused evidence. Project Meta owns policy approval, owner classes, project
lineage, and later promotion status. Existing coordination state remains the
only claim registry.

This slice does not wire session-start, worktree, pre-write, commit, or fleet
hooks; promote the Project Meta registry row; install downstream repositories;
implement break-glass or restart review; impose spend/subscription/time limits;
or claim that unsupported shell writes are blocked.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| `OutcomeContractV1` | actor, lineage, canonical journey, scope | digest-bound outcome identity | Enforced Planning | lease evaluator |
| `OutcomeProgressReceiptV1` | exact observation + prior receipt | classified progress/non-outcome evidence | observer | lease evaluator |
| `OutcomeLeaseV1` transition | current lease + ordered receipts | replay-safe lease state | lease evaluator | admission check |
| `RecoveryLeaseV1` | exact failure/question + bounded action | one constrained recovery authority | operator/control plane | admission check |
| continuation admission | lease + requested operation | allow/deny reason and exact next actions | Enforced Planning | later session/claim hooks |
| scenario CLI | JSON scenario | deterministic decision and resulting lease | Enforced Planning | operator/evidence run |

## Capability Adoption

**Disposition: extend.** Reuse the configured Plan #62 consumer identity and
the repository's native Pydantic/digest conventions. Add one distinct module;
do not duplicate the governed-task materializer, verifier, coordination
registry, or session lifecycle. Adoption is proved only by executing both signs
through the CLI, not by model construction or unit tests alone.

## Files Affected

- `enforced_planning/outcome_continuation.py` (create)
- `scripts/outcome_continuation.py` (create)
- `tests/test_outcome_continuation.py` (create)
- `examples/cleanroom-ecosystem/outcome-continuation-progress.json` (create)
- `examples/cleanroom-ecosystem/outcome-continuation-circular.json` (create)
- `docs/evidence/plan114_outcome_continuation_decisions.json` (create)
- `docs/plans/114_outcome_continuation_lease_enforcement.md` (create/update)
- `docs/plans/CLAUDE.md` (update)
- `ROADMAP.md` (update)

## Plan

### Critical Path Classification

| Increment | Class | Behavior or blocker changed |
|---|---|---|
| Typed lease transition and admission | `vertical` | Supported continuation becomes evidence-bound. |
| Execute progress and circular scenarios | `vertical` | Both signs are observed through the public CLI. |
| Repair a reproduced digest/profile incompatibility | `direct_blocker` only | Removes the exact failure preventing the same scenarios. |

### Steps

1. Write focused failing tests for model validation, stable digests, receipt
   replay, the three progress classes, two non-outcome increments, the third
   same-boundary failure, recovery scope, operation scope, passive actions, and
   approval/cost invariance.
2. Implement the smallest Pydantic models, pure state transitions, admission
   check, and JSON scenario CLI.
3. Bind two checked-in scenarios to the stable Plan #62 profile and receipt
   identity without importing or modifying its delivery implementation.
4. Commit the implementation, run both scenarios from that clean revision, and
   retain one evidence artifact containing exact inputs, decisions, commands,
   revision, and digests.
5. Run focused tests plus plan validation; update this plan/index/roadmap
   truthfully; push to canonical main; and close the claimed lane.

## Required Tests

| Test | What it invalidates |
|---|---|
| Progress-class transition matrix | Genuine progress cannot activate/reset the lease. |
| Two non-outcome increments | Motion can continue without a replay/readout boundary. |
| Third same-boundary failure | Repeated failed recovery never reaches stalled. |
| Duplicate-receipt replay | Reusing old evidence can renew continuation. |
| Approval invariance | `approve` or `continue` changes a denied decision. |
| Cost/time invariance | Telemetry becomes an accidental authorization or expiry gate. |
| Scope and state admission matrix | Claims/writes escape outcome scope or terminal states. |
| Recovery lease checks | Recovery becomes an unbounded alternate implementation path. |
| CLI positive/negative scenarios | Models pass while the operator boundary is unusable. |

## Acceptance Criteria

- [ ] Typed contracts fail loudly on unsafe paths, mismatched digests, broken
  receipt lineage, missing decision deltas, or unbounded recovery.
- [ ] All three approved progress classes activate/reset a lease, while a
  `non_outcome` receipt does not masquerade as progress.
- [ ] Two consecutive non-outcome increments require recovery/replay and deny
  normal product writes; a third same-boundary failure without discriminating
  evidence moves the lease to stalled.
- [ ] Applying the same receipt twice cannot renew or otherwise change a lease.
- [ ] Active leases allow only in-scope product operations; stalled, parked,
  and complete leases preserve passive inspection, exact replay, evidence
  preservation, and closeout.
- [ ] A recovery lease authorizes only its named action/path/replay and cannot
  create a new front door or general product-write authority.
- [ ] Ordinary approval and cost/elapsed telemetry have no effect on lease
  transition or admission results.
- [ ] The checked-in positive CLI scenario is allowed and the circular
  scenario is denied from the same clean implementation revision.
- [ ] The retained evidence licenses only the staged CLI/admission claim; no
  session-hook or fleet-enforcement claim is made.
- [ ] Focused tests and plan validation pass on the integrated candidate.

## Failure And Replan Rules

| Failure | Required response |
|---|---|
| Plan #62 identity cannot be consumed without coupling | Bind the stable profile/receipt digests as external evidence; do not edit the delivery seam speculatively. |
| Positive and circular scenarios produce the same decision | Preserve both inputs, revise the smallest discriminating transition, and replay the pair. |
| Approval or telemetry changes a decision | Remove the branch from decision logic and add a metamorphic regression test. |
| Recovery permits a general write | Deny it and require exact action, path, failure/question, and stopping condition. |
| CLI requires hook/session integration to run | Keep the pure JSON boundary and defer integration; do not widen the slice. |
| A fleet or hard-enforcement claim appears before evidence | Remove the claim; retain staged/observe language until representative integration evidence exists. |

## Pre-Made Decisions

- Progress, not money or time, controls continuation.
- Ordinary conversational approval is accepted only as telemetry/context and
  cannot create, renew, widen, or revive a lease.
- The first implementation is native to Enforced Planning and separate from
  `governed_delivery.py` while consuming its stable consumer identity.
- State transitions are pure and receipt-replay-safe before any hook wiring.
- One positive and one negative authentic-style scenario are the first
  promotion gate; fleet rollout and Project Meta promotion remain deferred.
