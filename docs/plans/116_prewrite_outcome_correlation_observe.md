# Plan #116: Pre-Write Outcome Correlation Observe Pilot

**Status:** Planned
**Type:** implementation (observe-only runtime integration)
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "correlate-continuation-authority-with-one-ordinary-claimed-write"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** linked
**Execution profile:** pilot
**Overlays:** exploratory, repository governance
**Blocked By:** #115
**Blocks:** any outcome-based pre-write enforcement or installer/fleet promotion

---

## Gap

**Current:** Plan #115 proved that real Brian-owned progress keeps the outcome
lease active and admits one exact next action, while the retained circular
control requires recovery. That decision is still a separate manual CLI run.
The ordinary pre-write claim gate evaluates and receipts the real native
session, worktree, branch, claim, and target payload, but no artifact correlates
the two decisions.

**Target:** Add one explicit observe-only option to the existing pre-write CLI.
After the ordinary claim decision is durably recorded, evaluate one immutable
outcome scenario against the same normalized target and append a typed
correlation receipt that says `would_allow` or `would_deny`. The ordinary claim
decision, native output contract, and process exit code remain authoritative
and unchanged.

**Why:** This is the smallest runtime bridge supported by the owner-real
evidence. It tests whether progress authority can be attached to a real claimed
write before inventing mutable lease state, claim bindings, installation, or
blocking.

## User Outcome

Brian can inspect one real claimed-write receipt and see the linked continuation
decision for that exact action. Genuine progress produces `would_allow`; the
same action with two circular non-outcome receipts produces `would_deny`; both
remain observation only.

## Canonical Behavioral Example

**Starting state:** A live Plan #116 worktree claim owns
`docs/evidence/plan116_prewrite_outcome_correlation.json`. Two immutable Plan
#116 scenarios share one outcome contract, request, operator context, and target:
one binds the completed Plan #115 owner observation as a behavioral advance;
the other supplies two synthetic non-outcome receipts.

**Action:** Send the same supported Codex `PreToolUse/apply_patch` payload for
that evidence path through `scripts/prewrite_claim_gate.py --mode observe`, once
with each explicit scenario and an isolated correlation-receipt path.

**Expected result:** In both runs, the existing claim gate records
`decision=allow` and `reason_code=exact_live_claim`. The positive correlation
references that ordinary receipt and records `would_allow/active_in_scope`. The
negative correlation references its ordinary receipt and records
`would_deny/recovery_required`. Both commands retain the ordinary successful
exit code, and no write is blocked or performed by the observation.

**Failure signal:** The scenario target differs from the normalized pre-write
target; the claim project differs from the outcome project; correlation loses
the ordinary receipt/session/worktree/branch identity; observation changes the
ordinary decision, native behavior, or exit code; an error is silent; or the
result is described as installed or enforced.

## References Reviewed

- `CLAUDE.md` — repository, claim, evidence, and closeout authority.
- `docs/plans/108_prewrite_claim_enforcement.md` — ordinary native pre-write
  boundary, receipt, and observe-before-enforce rules.
- `scripts/prewrite_claim_gate.py` — supported Codex/Claude adapter and native
  exit behavior.
- `enforced_planning/prewrite_claim_fast.py` — dependency-light ordinary
  decision, exact-claim identity, and durable receipt shape.
- `tests/test_prewrite_claim_fast.py` — current both-sign and CLI compatibility
  coverage.
- `docs/plans/114_outcome_continuation_lease_enforcement.md` and
  `enforced_planning/outcome_continuation.py` — strict outcome, receipt, lease,
  and admission contracts.
- `docs/evidence/plan115_owner_real_outcome_observation.json` — owner-real
  positive observation, manual-friction readout, selected seam, and falsifier.
- `examples/owner-real-outcome-observe/plan115-owner-progress.json` — immutable
  owner-progress source for the next lineage.

## Research

No web research is required. The decision is constrained by the current typed
contracts, native adapter behavior, retained owner evidence, and an executable
same-payload observation. General agent-framework comparisons would not test
this repository seam.

## Landscape And Prior Art

| Candidate | Evidence and implication | Disposition |
|---|---|---|
| Extend the existing pre-write wrapper after its ordinary decision | It already has the exact native payload and complete claim receipt identity. A lazy optional outcome path avoids changing the dependency-light claim evaluator. | Adopted for this pilot. |
| Put outcome logic in `prewrite_claim_fast.py` | That module intentionally uses only the standard library and is installed as a low-latency ordinary claim boundary. Adding Pydantic outcome state would couple unrelated contracts. | Rejected. |
| Add outcome fields to claims or the pre-write projection | Plan #115 identified this as a possible prerequisite only if explicit correlation is ambiguous or stale. | Deferred unless the pilot falsifier fires. |
| Install the option across governed repositories or block writes | No representative calibration or false-block evidence exists. | Deferred. |

One lineage remains authoritative: Plan #108 owns ordinary claim admission;
Plans #114/#115 own outcome continuation; Plan #116 owns only their explicit
observe-mode correlation.

## Design Profile And Epistemic Split

This is a `pilot`. Exact target/project/session correlation, immutable scenario
evaluation, append-only receipt shape, and exit compatibility are deductive.
Whether this seam is useful enough to justify durable lease binding or later
enforcement remains exploratory and must be decided from the retained run.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| ordinary pre-write claim decision | native payload + live claim projection | authoritative claim decision + receipt | `prewrite_claim_fast` | native adapter |
| outcome pre-write observation | ordinary receipt + immutable continuation scenario | typed correlated `would_allow` or `would_deny` receipt | Plan #116 correlation owner | Brian/operator evidence run |
| explicit wrapper option | native payload + scenario/receipt paths | unchanged ordinary native result plus visible observation status | `scripts/prewrite_claim_gate.py` | Brian and his coding agents |

These capabilities remain native to Enforced Planning. Shared data contracts
are deferred until a second repository consumes the boundary; `llm_client` is
not involved because this is a deterministic local decision.

## Boundaries And Contracts

1. With no outcome-scenario option, `scripts/prewrite_claim_gate.py` remains
   behaviorally identical.
2. The ordinary claim decision runs and records first. It remains the only
   decision that controls native output and exit status.
3. Outcome imports are lazy and activated only by an explicit scenario path;
   `enforced_planning/prewrite_claim_fast.py` stays dependency-light and
   unchanged unless a reproduced blocker proves otherwise.
4. Correlation requires exactly one normalized pre-write target equal to the
   scenario request target and a claim project equal to the outcome project.
5. The typed observation binds the ordinary receipt ID and full non-content
   identity: client, session, repository, worktree, branch, claim scope/source,
   target, scenario file hash, scenario digest, outcome contract, receipt/lease
   digests, and outcome reason.
6. Positive and negative scenarios use the same contract, request, approval,
   cost, elapsed context, and target. Only progress receipts differ.
7. Observation failures are visible in JSON/native output and retained when
   possible, but never change the ordinary claim decision or exit code.
8. The pilot neither executes the write nor claims shell coverage, native host
   activation, installation, blocking, colleague use, or fleet adoption.

## Capability Adoption

**Disposition: extend the existing seam.** Reuse the ordinary pre-write adapter
and Plan #114 evaluator. Add one typed correlation owner rather than another
claim evaluator, hook, or lease implementation. Adoption evidence is a real
Plan #116 claimed payload observed through the public CLI in both signs.

## Scope And Non-Goals

In scope:

- one typed correlation/append owner;
- one explicit optional CLI scenario and receipt-path surface;
- same-payload positive and synthetic negative scenarios;
- focused contract, CLI-compatibility, failure-visibility, and both-sign tests;
- one retained owner-first evidence artifact and truthful plan/roadmap status.

Not in scope:

- claim schema or pre-write projection changes;
- durable mutable outcome leases or automatic semantic progress classification;
- installer, hook wiring, downstream repository, colleague, or fleet changes;
- outcome-based blocking, shell interception, deployment, or release;
- shared `llm_client` or data-contracts integration.

## Files Affected

- `enforced_planning/outcome_prewrite_observation.py` (create)
- `scripts/prewrite_claim_gate.py` (update)
- `tests/test_outcome_prewrite_observation.py` (create)
- `examples/owner-real-outcome-observe/plan116-owner-progress.json` (create)
- `examples/owner-real-outcome-observe/plan116-circular.json` (create)
- `docs/evidence/plan116_prewrite_outcome_correlation.json` (create)
- `docs/plans/116_prewrite_outcome_correlation_observe.md` (create/update)
- `docs/plans/116_prewrite_outcome_correlation_observe_work_graph.json` (create/update)
- `docs/plans/CLAUDE.md` (update)
- `ROADMAP.md` (update)

## Plan

### Critical Path Classification

| Increment | Class | Behavior or blocker changed |
|---|---|---|
| Add typed exact-payload correlation after the ordinary decision | `vertical` | A real pre-write receipt can carry a linked continuation observation without affecting admission. |
| Prove same-payload `would_allow` and `would_deny` | `vertical` | Progress evidence, not repeated approval or effort, distinguishes both signs at the real adapter. |
| Retain owner evidence and select the next prerequisite/promotion decision | `vertical` | Further integration is based on observed ambiguity, utility, and false-block risk. |
| Claim mutation, installation, or blocking | deferred | These are not licensed by an observe-only pilot. |

### Steps

1. Freeze two strict same-contract scenarios and a typed correlation receipt.
2. Extend the public wrapper with lazy explicit observation, preserving ordinary
   no-option behavior, decision ordering, native output, and exit status.
3. Start with failing focused tests for target/project mismatch, both signs,
   ordinary allow/deny preservation, and visible observation failure.
4. Execute the same real Plan #116 claimed payload with both scenarios and
   retain ordinary receipt IDs plus correlated results.
5. Reconcile evidence, plan, work graph, index, and roadmap; do not promote
   installation or enforcement.

## Required Tests

| Check | What it invalidates |
|---|---|
| no-option CLI regression | the existing pre-write boundary changed for ordinary users |
| exact target/project binding | unrelated outcome authority can be attached to a write |
| positive same-payload observation | real progress cannot reach the ordinary adapter |
| negative same-payload observation | circular work is not distinguished at the same adapter |
| ordinary allow/deny and exit preservation | observation accidentally became enforcement |
| append/parse replay | receipts are not durable, typed, or correlated |
| Plan #108 and #114 focused regressions | the bridge relies on a regression in either owner |
| plan/work-graph validation | execution or promotion boundaries are missing |

## Acceptance Criteria

- [ ] Without explicit outcome options, existing pre-write JSON/native behavior
  and exit codes are unchanged.
- [ ] One ordinary decision is durably recorded before one typed outcome
  observation references its receipt ID.
- [ ] Exact target and claim-project correlation fail visibly on mismatch while
  preserving ordinary admission.
- [ ] The same real claimed payload produces ordinary `allow/exact_live_claim`
  in both runs, plus outcome `would_allow/active_in_scope` for genuine progress
  and `would_deny/recovery_required` for the synthetic circular control.
- [ ] Approval text, cost, and elapsed context are identical and ignored in both
  signs.
- [ ] Retained evidence is revision- and digest-bound and truthfully classified
  as an explicit manual observe pilot.
- [ ] Focused pre-write/outcome regressions and plan validation pass.
- [ ] No claim mutation, automatic lease, installer, host activation, shell,
  enforcement, colleague, or fleet claim is made.

## Failure And Reset Rules

| Failure | Response |
|---|---|
| ordinary decision or exit changes | revert the wrapper coupling; keep the outcome evaluator separate |
| target/project cannot bind exactly | retain the mismatch and require explicit durable claim/session outcome binding before another adapter attempt |
| observation error is silent | fail the focused check and add a visible non-authoritative diagnostic |
| positive and circular scenarios do not differ | inspect receipt lineage and contract binding; do not tune claim admission |
| useful correlation requires projection or installer changes | stop this unit and adopt a separately bounded prerequisite rather than expanding scope |

## Pre-Made Decisions

- Extend only the existing wrapper; do not create a second pre-write gate.
- Keep the ordinary claim evaluator dependency-light and authoritative.
- Use explicit immutable scenarios and a separate append-only observation log.
- Preserve ordinary native output and exit behavior in every observation state.
- Test Brian and his agents on Enforced Planning first; colleagues and fleet
  rollout remain downstream.
