# Plan #115: Owner-Real Claimed-Write Outcome Observation

**Status:** Planned
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "observe-outcome-admission-on-real-owner-work"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** linked
**Execution profile:** pilot
**Overlays:** runtime state, exploratory, repository governance
**Blocked By:** #114
**Blocks:** any outcome-continuation enforcement promotion, additional chokepoint wiring, and fleet rollout

---

## Gap

**Current:** Plan #114 proves the pure outcome contract, receipt, lease transition,
and admission decision through two revision-bound CLI scenarios. No current
session, claim, or native write adapter consumes that decision. An ordinary
claimed write therefore produces no evidence about whether outcome continuation
would have been allowed or denied.

**Target:** Extend the existing claim registry and pre-write claim adapter with an
observe-only outcome binding. Against one current Enforced Planning worktree
owned by Brian and his Codex session, bind an exact `OutcomeContractV1` and
`OutcomeLeaseV1` to the live claim, evaluate real claimed-write payloads through
the existing adapter, and append correlated outcome observations. The existing
claim decision remains the only blocking effect. The same claimed write must be
recorded as `would_allow` under an active lease and `would_deny` under a
recovery-required lease without changing the adapter's exit result.

**Why:** This is the smallest owner-first observation that can expose false
blocks, missing bindings, adapter bypasses, and identity mismatches before any
outcome-continuation enforcement is enabled.

## User Outcome

Brian and his agents can use the continuation control during real Brian-owned
work and see whether supported writes would continue or stop for outcome
reasons, while genuine work remains unblocked during calibration.

## Canonical Behavioral Example

**Starting state:** A current Codex session owns one exact Plan #115 claim and
worktree. The claim is atomically bound to a checked-in Plan #115 outcome
contract and an active lease. `meta-process.yaml` selects outcome-continuation
`observe` mode while the existing pre-write claim mode remains independently
configured.

**Positive action:** Evaluate the native Codex `apply_patch` payload for one
Plan #115-owned path through `scripts/prewrite_claim_gate.py`, then perform that
real plan write.

**Positive result:** The ordinary claim decision is `allow`; a correlated
outcome observation is appended with `evidence_class=owner_real_project`, the
exact session/claim/worktree/branch/path identities, `effect=would_allow`, and
`enforcement_applied=false`.

**Negative action:** Rebind the same claim and contract to a valid
`recovery_required` lease derived from two non-outcome receipts, then replay the
same adapter payload.

**Negative result:** The ordinary claim decision is still `allow`; the outcome
observation records `effect=would_deny`, `reason_code=recovery_required`, and
`enforcement_applied=false`. Observe mode returns success and cannot block the
write.

**Delivery classification:** Each observation says whether it came from a
native lifecycle invocation or an exact manual adapter replay. A manual replay
can prove the adapter and current owner-work binding, but it cannot prove that
the Codex host automatically delivered the hook.

**Failure signal:** Outcome observation changes the claim-gate result; a
missing or malformed binding is silent; the observation cannot be correlated
to one exact claim receipt; the same binding produces different admission from
Plan #114; or evidence calls an adapter replay a native hook delivery.

## References Reviewed

- `CLAUDE.md` — repository workflow, claim, verification, and closeout authority.
- `GETTING_STARTED.md` — installed-consumer support tiers and the bounded
  worktree/session entrypoint.
- `docs/reference/CONFIG_REFERENCE.md` — live `claims.prewrite_mode` behavior,
  observe-before-enforce ratchet, supported adapter boundary, and installer
  contract.
- Project Meta `outcome-continuation-lease-hard-gate` at approved revision
  `f6091b6b2f2a5357d0fdbbe88b157435a2ce07fb` — observe before enforcement,
  reuse claim/session state, do not gate cost.
- Project Meta `owner-first-agentic-system-dogfooding` at `origin/main` — real
  Brian-owned work precedes colleague or external-user validation.
- Plan #114 and `enforced_planning/outcome_continuation.py` — canonical pure
  decision seam and both-sign evidence.
- Plan #108, `enforced_planning/prewrite_claim_fast.py`, and
  `scripts/prewrite_claim_gate.py` — existing supported-write adapter, claim
  identity, and append-only receipt path.
- `enforced_planning/coordination_claims.py` — sole mutable claim registry and
  atomic mutation/projection-refresh owner.

## Research

No web research is required for this slice. The decision-relevant evidence is
repository-local and revision-bound: the approved Project Meta continuation
policy, the Plan #114 evaluator and evidence, the Plan #108 native adapter, the
live configuration reference, and current claim/runtime receipts. External
framework comparisons would not answer the decisive question: whether this
repository's existing claimed-write boundary can observe the Plan #114
decision without changing write admission.

The exploratory portion is therefore an authentic local owner-work run. It
must retain the exact claim receipt, outcome observation, contract and lease
digests, current revisions, delivery classification, and any bypass or missing
native-delivery limitation.

## Landscape And Prior Art

| Candidate | Evidence and implication | Disposition |
|---|---|---|
| Add a new outcome hook and mutable lease registry | Plan #108 already owns supported pre-write delivery and exact claim identity; a parallel hook or registry would split authority and correlation. | Rejected. |
| Extend the existing pre-write adapter after its ordinary claim decision | `scripts/prewrite_claim_gate.py`, `enforced_planning/prewrite_claim_fast.py`, and the append-only receipt path already expose the exact session, claim, worktree, branch, and target identity needed by Plan #114. | Adopted for this slice. |
| Wire outcome admission directly into session start, heartbeat, commit, and closeout | Those chokepoints have different failure behavior and have not yet been calibrated against owner-real false blocks or bypasses. | Deferred until this observation readout. |
| Install or enforce across the governed repository fleet | The approved outcome policy and owner-first dogfood policy require a representative owner-real observation before promotion. | Deferred; Plan #115 licenses only Enforced Planning observe mode. |

The linked landscape therefore has one canonical lineage: Plan #114 owns the
pure continuation decision; the claim registry owns mutable identity and lease
binding; the Plan #108 adapter owns supported write delivery; the new append-only
record owns calibration evidence only.

## Design Profile And Epistemic Split

This is a `pilot` because it changes a shared runtime contract and requires a
representative owner-work observation, replay, and usable agent path. Contract
binding, digest checks, and observe-mode non-blocking behavior are deductive.
Automatic Codex hook delivery, false-block rate, and bypass frequency are
exploratory and may be claimed only from retained runtime receipts.

## Boundaries And Domain Rules

| Boundary | Owns | Must not own |
|---|---|---|
| outcome evaluator | typed contract/lease validation and deterministic admission | claim identity, hook delivery, or operational persistence |
| claim outcome binder | exact live-claim binding, atomic YAML mutation, projection refresh, mutation receipt | lease classification or a second claim registry |
| pre-write adapter | correlation of one claim receipt to zero or one outcome observation | outcome enforcement during this plan |
| observation store | append-only calibration evidence with file locking | live lease authority or mutable current state |
| repository config | `off` or `observe` selection for this capability | fleet promotion or implicit `enforce` |

Rules:

1. The live claim YAML remains the only mutable authority record. Its optional
   outcome section contains the repo-relative contract path, exact contract
   digest, full validated lease, exact lease digest, binding class, timestamp,
   and binding session.
2. Binding fails before mutation unless the claim is exact and live; the
   contract is inside its repository; contract, lease, and digests agree; and
   the binding session owns the claim.
3. The binder performs one locked atomic claim replacement, refreshes the
   digest-bound pre-write projection, and emits an `outcome_bind` claim-mutation
   receipt. Failure leaves the original claim and projection unchanged.
4. Outcome evaluation runs only after the ordinary adapter resolves one exact
   healthy claim. Claim denial, ambiguity, or missing identity is recorded as
   `not_evaluated_claim_denied`, never as an outcome denial.
5. Each normalized target path receives the Plan #114 `product_write`
   decision. Any denied target makes the observation `would_deny`; all allowed
   targets make it `would_allow`.
6. Missing, malformed, stale, or digest-mismatched outcome binding is visible
   as `observe_violation`. In this plan it never changes the pre-write claim
   decision or process exit code.
7. Outcome observation accepts approval, cost, and elapsed telemetry only as
   ignored context inherited from Plan #114. No spend, subscription, or time
   field affects binding or admission.
8. Shell/process writes remain unsupported bypasses. Evidence must not call
   them blocked merely because the `apply_patch` adapter is observed.

## Contracts

### `ClaimOutcomeBindingV1`

- `schema_version`
- `contract_path` (portable repository-relative JSON path)
- `contract_sha256`
- `lease` (`OutcomeLeaseV1`)
- `lease_sha256`
- `evidence_class`: `generated_fixture | owner_real_project | external_user`
- `bound_at`
- `bound_by_session_id`

### `OutcomePreWriteObservationV1`

- stable observation ID and timestamp
- correlated ordinary pre-write receipt ID
- project, scope, session, repository, worktree, branch, and target paths
- contract and lease digests when valid
- per-target `ContinuationDecisionV1` results
- `effect`: `would_allow | would_deny | observe_violation | not_evaluated_claim_denied`
- `delivery_source`: `native_hook | manual_adapter_replay`
- `enforcement_applied=false`
- exact limitation and permissible next actions

Unknown fields fail loud. Observation append is file-locked and durable; it is
evidence, not a second mutable authority surface.

## Capability Adoption

**Disposition: extend.** Reuse the Plan #114 evaluator, the canonical YAML claim
registry, the Plan #108 pre-write adapter, and its exact session/claim/worktree
identity. Do not add another hook stack or lease registry. Adoption requires a
current owner-real-project claim receipt plus its correlated outcome
observation; isolated model tests and generated fixtures prove only substrate.

## Scope And Non-Goals

In scope:

- typed claim binding and atomic binder;
- observe-only pre-write adapter integration;
- append-only correlated outcome observations;
- source-repo config and portable installer support for the new runtime module;
- one active-lease positive observation and one recovery-required negative
  observation against the same current Brian-owned claim/write payload;
- truthful delivery and bypass classification.

Not in scope:

- outcome-based blocking or an `enforce` configuration value;
- automatic progress-receipt generation or semantic judgment by the writer;
- session-start, resume, heartbeat, claim creation, commit, or closeout wiring;
- break glass, restart review, WIP ceilings, fleet installation, Project Meta
  registry promotion, colleague packaging, or external-user validation;
- claims that arbitrary Bash/shell writes are blocked;
- cost, subscription, elapsed-time, deployment, or release controls.

## Files Affected

- `enforced_planning/outcome_continuation_runtime.py` (create)
- `enforced_planning/claim_mutation_receipts.py` (update)
- `scripts/outcome_continuation.py` (update)
- `scripts/prewrite_claim_gate.py` (update)
- `enforced_planning/hook_wiring.py` (update)
- `scripts/install_governed_repo.py` (update)
- `meta-process.yaml` (update)
- `tests/test_outcome_continuation_runtime.py` (create)
- `tests/test_prewrite_claim_gate.py` (create/update)
- `tests/test_install_governed_repo.py` (update)
- `examples/owner-real-outcome-observe/plan115-contract.json` (create)
- `examples/owner-real-outcome-observe/plan115-active-lease.json` (create)
- `examples/owner-real-outcome-observe/plan115-recovery-lease.json` (create)
- `docs/evidence/plan115_owner_real_outcome_observations.json` (create)
- `docs/plans/115_owner_real_outcome_observe.md` (create/update)
- `docs/plans/115_owner_real_outcome_observe_work_graph.json` (create/update)
- `docs/plans/CLAUDE.md` (update)
- `ROADMAP.md` (update)

## Plan

### Valuable Thin Slice

1. Add both-sign tests for strict binding, atomic mutation, projection refresh,
   observation correlation, multi-path aggregation, missing/mismatched binding,
   and non-blocking observe behavior.
2. Implement the binder and observation types by consuming the Plan #114
   evaluator directly.
3. Extend the existing pre-write adapter and installer support without adding a
   second hook command.
4. Configure only Enforced Planning for outcome `observe`, bind the active Plan
   #115 claim, and retain the same-payload positive and negative observations.
5. Record whether delivery was native or a manual exact adapter replay, inspect
   false-block/bypass signals, and close without promotion.

Later chokepoints remain conditional on this readout. A later plan may wire
session/claim/commit/closeout only after the observation schema and identity
binding survive owner use.

### Critical Path Classification

| Work | Classification | Why |
|---|---|---|
| typed claim binding, observer, and existing-adapter integration | vertical | It connects the already-proved continuation decision to one supported real write boundary. |
| same-payload owner-real active/recovery observation | vertical | It is the first authentic evidence that genuine work and circular continuation receive opposite advisory decisions. |
| repair of an exact native activation or correlation defect found by that run | direct blocker | It is critical only when the authentic observation demonstrates that the supported path cannot be exercised truthfully. |
| additional lifecycle hooks, arbitrary shell coverage, installer fleet rollout, or colleague packaging | deferred | None is required to answer Plan #115's owner-real observe-mode question. |

## Required Tests

| Test | What it invalidates |
|---|---|
| strict binding and digest matrix | a claim can bind mismatched or unreviewable authority |
| atomic mutation/projection receipt | outcome binding silently desynchronizes canonical and fast-path state |
| active lease claimed write | genuine owner work would be falsely denied |
| recovery-required same write | circular continuation would be silently allowed |
| missing/malformed binding | observe mode hides adoption gaps |
| multi-target aggregation | one denied path is lost inside an allowed patch |
| claim-denied precedence | outcome evidence misstates an identity/ownership failure |
| observe non-blocking metamorphic check | outcome mode changes the existing claim result or exit code |
| installer support check | downstream pre-write adapter imports a module the installer omits |
| owner-real adapter run | fixtures pass while the current session/claim/write boundary is unusable |

## Acceptance Criteria

- [ ] A strict binding command atomically binds one exact live claim to a
  validated Plan #115 contract/lease and refreshes the pre-write projection.
- [ ] The ordinary claim adapter result is byte-for-byte decision-equivalent
  with outcome mode off versus observe, apart from outcome notice/evidence.
- [ ] The same exact current session/claim/worktree/path payload records
  `would_allow` under the active lease and `would_deny` under the
  recovery-required lease.
- [ ] Both observations use `evidence_class=owner_real_project`, correlate to
  ordinary pre-write receipts, and retain exact revision and binding digests.
- [ ] Missing, corrupt, replayed, or mismatched binding fails visibly without
  blocking in observe mode or silently switching authority.
- [ ] Delivery is classified truthfully as native hook or manual adapter replay;
  no unsupported shell write or fleet repository is claimed blocked.
- [ ] Focused runtime, adapter, installer, lint, type, and plan checks pass on
  the integrated candidate.
- [ ] Evidence licenses only Enforced Planning claimed-write observation. It
  does not promote enforcement or colleague/fleet rollout.

## Exploratory Readout And Promotion Rule

The instrument reports concrete observation effects and lets reviewers step
down to the exact claim receipt and target decision. Plan #115 ends after the
both-sign owner-real readout. Enforcement remains prohibited. A later promotion
decision requires representative false-block and bypass review plus evidence
for genuine progress, direct-blocker removal, decision-changing learning,
passive inspection, and clean closeout at the chokepoints being promoted.

## Failure And Reset Rules

| Failure | Response |
|---|---|
| binding cannot update claim and projection atomically | preserve original claim bytes; fix only the mutation boundary and replay |
| observer changes claim-gate result | remove outcome effect from the adapter and add an off/observe metamorphic regression |
| same binding disagrees with Plan #114 evaluator | reuse the pure evaluator directly; do not duplicate admission logic |
| current Codex host does not deliver the hook | retain a manual adapter replay, label native delivery unverified, and defer host activation rather than fabricating it |
| shell target cannot be resolved | record unsupported bypass; do not infer or block a path |
| owner-real positive and negative cannot be distinguished | retain both inputs, repair the smallest binding/evaluation seam, and replay the same pair |

## Pre-Made Decisions

- This plan is observe-only; it cannot promote itself to enforcement.
- Enforced Planning is the first real Brian-owned dogfood consumer. Colleague
  and external-user validation remain downstream.
- The canonical claim YAML owns mutable lease binding; observation JSONL is
  append-only evidence and never grants authority.
- Extend the existing pre-write hook command and Plan #114 evaluator. No
  parallel framework, registry, or admission implementation is permitted.
- Adapter replay and native lifecycle delivery are different evidence classes.
- Progress, not money or elapsed time, remains the continuation discriminator.
