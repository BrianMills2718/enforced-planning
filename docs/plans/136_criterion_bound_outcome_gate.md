# Plan #136: Criterion-Bound Outcome Gate

**Status:** Complete — local criterion gate and exact Plan 52 browser consumer evidenced; integration and fleet activation remain excluded
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "criterion-bound-outcome-enforcement"
**Landscape disposition:** linked
**Blocked By:** None
**Blocks:** None within this local implementation slice

## Authority and correction

Brian approved the criterion-binding design in native Codex session
`01a09179-ef3e-7241-9827-690d8f05aacf` on 2026-09-12. The accepted design text
has SHA-256 `73c751501fc419a57b1c665fb9bedfbe2d82766d1046e7584cf8242978481334`.

The repeated failure was not missing plan prose. Plan 52 had success criteria,
but the producing agent could count inventory and planning as progress, present
a previously rejected artifact, and self-verify a page that still violated the
requested topology. This plan makes those substitutions ineligible for a
review-ready transition.

## Gap

**Current:** Outcome contracts bind a canonical journey, progress dimensions,
and an evidence chain, but a behavioral-advance receipt does not name the
specific accepted criterion it closes or the exact artifact on which it was
observed. The producer may classify its own work as progress.

**Target:** Criterion-level independent evidence on one exact artifact controls
the review-ready decision, and rejected artifact digests remain ineligible.

## User outcome

When Brian defines or corrects a user-visible outcome, execution can continue
through useful supporting work, but the system cannot offer a result for review
until an independent verifier has attached passing evidence for every frozen
criterion to that exact artifact revision. A rejected artifact revision cannot
be revived within the same outcome lineage.

## Canonical behavioral example

**Starting state:** The Plan 52 dashboard contract requires two separate maps,
including one company-work DAG that flows top-to-bottom. The previously shown
artifact is left-to-right and has been rejected.

**Action:** Attach evidence for only the page split, attempt review, then attach
evidence for all criteria on a new artifact. Also attempt to attach new passing
evidence to the rejected digest.

**Expected result:** The partial artifact is denied with the missing criterion
IDs. The complete new artifact becomes review-ready. The rejected digest remains
denied and cannot accept later passing evidence.

**Failure signal:** Supporting work satisfies a criterion implicitly; evidence
from one artifact carries to another; the producer can self-verify; an omitted
rejection allows an old digest to return; or legacy contracts acquire implicit
review authority.

## Capability ownership and boundaries

This extends Enforced Planning's existing `OutcomeContractV1`, progress-receipt,
lease, and selected-outcome lineage. It does not create another state store or
semantic classifier. AES may produce independent verifier evidence, but the
planning runtime owns the deterministic state transition.

Version `1.2.0` activates the stronger contract. Older contracts remain valid
but receive no implicit `review-ready` authority.

The first slice is local and reversible. It does not install the change into
other repositories, push, merge, publish, deploy, or invoke a model.

## References Reviewed

- `enforced_planning/outcome_continuation.py` — existing outcome contract,
  evidence, lease transition, and admission owner.
- `enforced_planning/outcome_selection.py` — exact-session selection and
  append-only receipt lineage.
- `docs/plans/114_outcome_continuation_lease_enforcement.md` and
  `docs/plans/119_durable_selected_outcome_progress.md` — accepted continuation
  and durable progress boundaries.
- AES `docs/plans/13_portable_orchestrator_spine.md` — independent supervisor
  verifier producer; not the lifecycle owner for the current dashboard session.
- Project Meta `vision/ARCHITECTURAL_IDEAS.md` — precedent for versioned gates
  whose malformed or failed verdicts cannot be interpreted as acceptance.

## Landscape And Prior Art

**Disposition: linked.** Extend the existing Enforced Planning outcome lineage
and use AES's existing verifier role. Do not create a new runtime, state store,
or semantic classifier. The incumbent contract is documented in
[Plan 114](114_outcome_continuation_lease_enforcement.md).

## Capability Adoption

**Disposition: extend.** The authentic consumer is the already-authorized Plan
52 dashboard browser journey. Source-only tests establish the contract substrate
but not adoption.

## Capabilities

| Capability | Change | Owner | Consumer and proof |
|---|---|---|---|
| Criterion-bound outcome lifecycle | Extend `OutcomeContractV1`, progress receipts, and leases with exact criterion and artifact identity | Enforced Planning | The Plan 52 dashboard session consumes a selected contract and receives a deterministic denied/ready decision |
| Independent artifact verification | Reuse the existing verifier role; do not make the producer authoritative | AES Supervisor or another distinct verifier identity | A receipt names the verifier and the exact browser artifact digest |
| Company-work dashboard | Consume the gate without owning or reinterpreting it | Initiative Roadmap Dashboard | The known rejected artifact fails and a corrected browser rendering passes every frozen criterion |

## Contract

- A `1.2.0` outcome contract must contain unique, frozen success criteria.
- Behavioral progress must name at least one criterion, bind it to one artifact
  SHA-256, carry discriminating evidence, and identify both the producer and an
  independent verifier whose identities differ.
- Changing the candidate artifact clears accumulated passing criteria rather
  than inheriting them.
- A rejection receipt adds the exact artifact digest to the lineage's durable
  ineligible set and clears its current criterion evidence.
- `evaluate_review_readiness` returns true only when every frozen criterion has
  passing evidence for the exact non-rejected candidate digest.
- The selected outcome lease remains `working` until that condition is true;
  only the same transition that records the last missing receipt can move it to
  `review_ready`.

## Critical Path Classification

**Critical-path classification: vertical.** The source contract and Plan 52
consumer are one acceptance path. Contract tests are direct blockers; unrelated
planning, inventory, fleet rollout, and classifier work do not advance it.

## Plan

**Critical-path classification: vertical.** Implement and discriminate the
typed source contract, then use the Plan 52 browser journey as its first
authentic consumer before any rollout.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| Typed criterion contract | fully_specifiable_now | Version 1.2.0 activates unique criteria and exact artifact binding | Both-sign focused tests pass | Plan 52 consumer scenario |
| Rejected artifact lineage | fully_specifiable_now | Rejection is an append-only non-outcome receipt | Revival attempt fails | Plan 52 rejected digest |
| Browser criterion evidence | fully_specifiable_now | Independent evidence must inspect the rendered entrypoint | Known wrong artifact denied; corrected artifact admitted | Resume dashboard implementation |

## Acceptance criteria

- [x] A criterion-bound contract cannot exist without at least one unique criterion.
- [x] Missing criterion evidence denies review and names the missing criterion IDs.
- [x] Producer-authored evidence cannot count as independent verification.
- [x] Evidence does not carry between artifact revisions.
- [x] A rejected artifact remains review-ineligible and cannot receive new passing evidence.
- [x] Legacy contracts remain loadable and cannot claim criterion-bound review readiness.
- [x] The Plan 52 dashboard uses the contract through its real browser entrypoint and the known rejected artifact fails.
- [x] A corrected Plan 52 artifact receives independent criterion evidence and becomes review-ready.

## Verification

- Enforced Planning focused suite: 63 tests pass across criterion transitions,
  portfolio admission, selection, and retained consumer replay.
- Dashboard `make ui-check`: 67 tests pass, including Chromium probes for
  downward dependency geometry and separate Company Work / Purpose Map panels.
- Rejected dashboard revision `8d663c75b15136bd389a06171c7fea167b2ab749`
  remains ineligible at artifact digest
  `24bfc04474af5fe9a29e318c1fe4cf557d0cf9828004aca699bb6ad823035a6c`.
- Corrected local dashboard revision
  `bf30ef9a32459af12e5cbe3c885a99c13859ef82` becomes `review_ready`
  only after all four criteria pass on HTML digest
  `9218935126818d90d219c5345308ea9a3813a862a95534049d69631aadf7ab8f`.
- Exact receipts, the partial denial, final decision, and rejected-revival
  negative control are retained in
  `docs/evidence/plan136_criterion_bound_outcome_verification.json`.
- The bounded maintenance allocation is closed as `complete` by
  `docs/evidence/plan136_criterion_bound_outcome_disposition.json` after the
  source and browser evidence were retained.

This is local implementation and consumer evidence. It does not claim that the
branch is merged, installed, or active across ordinary Codex sessions.

## Reassessment Contract

**Triggers:** The real consumer cannot express a criterion without semantic
prose inference on the transition path, or an artifact can inherit or revive
evidence it should not possess.

**Autonomous action:** Stop before activation and repair the typed evidence
contract while preserving independence and artifact binding.

**Plan revision required:** Changing the criterion identity, verifier
independence rule, rejection lineage, or runtime owner requires a revision.

**Human decision required:** Weakening a frozen success criterion or accepting
producer self-verification requires Brian's explicit decision.

**Stopping rule:** Source tests and the authentic Plan 52 negative/positive
journey both discriminate.

## Files Affected

- `enforced_planning/outcome_continuation.py`
- `enforced_planning/outcome_portfolio.py`
- `tests/test_criterion_bound_outcomes.py`
- `tests/test_outcome_portfolio.py`
- `docs/evidence/plan136_criterion_bound_outcome_verification.json`
- `docs/evidence/plan136_criterion_bound_outcome_disposition.json`
- `docs/plans/136_criterion_bound_outcome_gate.md`
- `docs/plans/136_criterion_bound_outcome_gate_work_graph.json`
- `docs/plans/CLAUDE.md`
