# Plan #115: Owner-Real Outcome Continuation Observation

**Status:** Planned
**Type:** implementation (observe-only adoption)
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "observe-existing-continuation-contract-on-real-owner-progress"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** linked
**Execution profile:** pilot
**Overlays:** exploratory, repository governance
**Blocked By:** #114
**Blocks:** selection of the first runtime continuation integration seam and any enforcement promotion

---

## Gap

**Current:** Plan #114 proves the typed outcome contract, progress receipt,
lease transition, and admission decision with a retained authentic consumer and
a synthetic circular control. No observation yet binds those contracts to
genuine progress made by Brian and his agents while improving Enforced Planning
itself. Selecting a session, claim, pre-write, commit, or closeout integration
now would be architectural speculation.

**Target:** Bind the canonical merged Plan #55 compact-context owner-dogfood
result to the existing Plan #114 JSON CLI as one strict
`behavioral_advance` receipt. Ask whether the next exact Plan #115 evidence
write is admitted, retain the result and its evidence lineage, and record which
manual steps reveal the smallest useful runtime integration seam. This plan
does not add a hook, claim binding, mutable lease registry, or hard gate.

**Why:** This is the first owner-real continuation observation and the cheapest
way to learn what actually needs integration before changing a shared runtime
boundary.

## User Outcome

Brian can see that real progress on his own engineering system—not approval,
spend, elapsed time, or generated motion—licenses a concrete next project
action, while the evidence shows exactly what remains manual before enforcement
could be trustworthy.

## Canonical Behavioral Example

**Starting state:** Canonical Enforced Planning merge
`5fbcd6e7679abe323dda7473998f5cd9e086bbb8` contains the completed Plan #55
owner dogfood. For `enforced_planning/doc_authority.py`, the public
`file_context` route returns exactly four required documents. The command's
JSON stdout digest is
`7f920c7d4d4a6354f8aa39eb18aa5ad983cf18e2435ae33d8e238c7fa09ae668`,
and the governing `scripts/doc_authority.yaml` digest is
`81e5c7635e0131e30ecb5e7028f7b88e31020315a44bc43a6178563ddfdee7ef`.

**Action:** Encode that result as one lineage-bound
`behavioral_advance` receipt in a checked-in Plan #115 scenario. Request an
in-scope `product_write` to
`docs/evidence/plan115_owner_real_outcome_observation.json` with the same
decision-inert context used in Plan #114: ordinary approval, approval text
`I approve, continue`, high cost telemetry, and high elapsed telemetry. Run
`python scripts/outcome_continuation.py evaluate --scenario <scenario>`.

**Expected result:** The existing evaluator returns an active lease and allows
the evidence write as `active_in_scope`. The retained readout classifies this
as a manual CLI observation, not native lifecycle delivery, and lists the
manual contract, receipt, lease, and operation-binding steps that remain.

**Negative control:** Plan #114's retained two-increment circular scenario
remains the deterministic denied control. Plan #115 does not fabricate a
historical owner failure and does not relabel that synthetic control as real.

**Failure signal:** The real receipt cannot be validated from exact revisions
and digests; the admitted path is outside the declared contract scope; approval
or telemetry affects the decision; the result is described as automatically
enforced; or an integration seam is selected without evidence from the manual
run.

## References Reviewed

- `CLAUDE.md` — repository workflow, evidence, claim, and closeout authority.
- `GETTING_STARTED.md` — current installed-consumer and native-tool support
  boundaries.
- `docs/reference/CONFIG_REFERENCE.md` — current observe-before-enforce ratchet
  and supported adapter limitations.
- `docs/plans/114_outcome_continuation_lease_enforcement.md` — canonical typed
  continuation contract, staged proof, and promotion limits.
- `enforced_planning/outcome_continuation.py` and
  `scripts/outcome_continuation.py` — existing decision seam and public CLI.
- `docs/evidence/plan114_outcome_continuation_decisions.json` — retained
  positive and synthetic negative controls.
- `docs/plans/55_enforced-planning_recursive_doc_spine_dogfood.md` at canonical
  merge `5fbcd6e7679abe323dda7473998f5cd9e086bbb8` — real owner-progress source.
- `scripts/doc_authority.yaml` and `scripts/file_context.py` — exact
  configuration and observation route for that progress.
- Project Meta `outcome-continuation-lease-hard-gate` at approved revision
  `f6091b6b2f2a5357d0fdbbe88b157435a2ce07fb` — progress-only authority and
  observe-before-enforce rollout.
- Project Meta `owner-first-agentic-system-dogfooding` — Brian and his agents
  use the mechanism on real Brian-owned work before colleague or fleet rollout.

## Research

No web research is required. The decision-relevant sources are current local
policy, typed runtime contracts, canonical Git revisions, exact configuration
and output digests, and an executable owner-work scenario. General framework
comparisons would not identify which manual step in this repository's
continuation flow should become the first integration seam.

The exploratory evidence is the CLI run plus a step-level readout of what had
to be supplied manually. Claims are limited to that retained observation.

## Landscape And Prior Art

| Candidate | Evidence and implication | Disposition |
|---|---|---|
| Reuse `scripts/outcome_continuation.py` against real Plan #55 progress | The strict scenario already accepts exact outcome, receipt, lease, operation, approval, cost, and elapsed context. | Adopted for this owner-real observation. |
| Add a pre-write claim adapter now | `scripts/prewrite_claim_gate.py` exposes a plausible supported-write boundary, but no owner-real continuation run yet proves that write admission is the first missing seam. | Deferred pending this readout. |
| Add session, heartbeat, commit, or closeout integration now | Each has different authority and recovery behavior; selecting one before observing manual friction would encode an assumption. | Deferred. |
| Install or enforce across repositories | Approved policy requires representative owner observation and false-block/bypass review first. | Deferred; no fleet or colleague claim. |

This preserves one lineage: Plan #114 owns the decision implementation; Plan
#55 supplies real owner-progress evidence; Plan #115 records adoption and the
next seam recommendation without creating a parallel runtime.

## Design Profile And Epistemic Split

This is a `pilot`: strict scenario validation and digest binding are deductive;
whether the manual workflow identifies a useful integration seam is
exploratory. The scenario result can prove only that one real progress receipt
admits one named action through the existing CLI. It cannot prove native
delivery, historical failure detection, or enforcement.

## Boundaries And Rules

1. The Plan #114 Pydantic models and CLI are reused unchanged unless the exact
   owner scenario reproduces a blocking defect.
2. The receipt binds the canonical Plan #55 merge, configuration digest,
   command, output digest, artifact references, and timezone-aware observation.
3. The requested action is one root-relative path explicitly listed in the
   outcome contract's allowed scope.
4. Approval text, cost, and elapsed telemetry stay present and decision-inert.
5. The evidence artifact records `delivery_classification=manual_cli_observation`
   and must not imply hook, session, claim, or fleet activation.
6. The synthetic Plan #114 circular control stays synthetic. No historical
   owner failure is invented to make the pilot look broader.
7. The readout separates four candidate manual concerns: outcome selection,
   progress observation/classification, lease persistence/lineage, and
   operation admission. It recommends the smallest next seam supported by the
   observed friction; Plan #115 does not implement it.
8. Spend, subscription, and elapsed time never grant, renew, narrow, or revoke
   continuation authority.

## Capability Adoption

**Disposition: reuse.** Consume the existing Plan #114 contract, transition,
admission, and CLI without adding another hook, registry, or evaluator.
Adoption evidence is the checked-in owner-real scenario and retained CLI
result, not model construction or generated fixtures alone.

## Scope And Non-Goals

In scope:

- one checked-in scenario bound to the merged Plan #55 owner result;
- exact re-observation of its configuration and file-context output digests;
- one retained allow decision for a concrete next Plan #115 action;
- a truthful manual-friction and next-integration-seam readout;
- focused regression and plan validation.

Not in scope:

- new runtime code unless the exact scenario exposes a direct blocker;
- a pre-write, session, claim, heartbeat, commit, or closeout adapter;
- mutable lease persistence, automatic progress classification, or semantic
  judgment by an agent;
- outcome enforcement, break glass, fleet installation, colleague packaging,
  or external-user validation;
- a spend, subscription, elapsed-time, or arbitrary-shell-write gate.

## Files Affected

- `examples/owner-real-outcome-observe/plan115-owner-progress.json` (create)
- `docs/evidence/plan115_owner_real_outcome_observation.json` (create)
- `docs/plans/115_owner_real_outcome_observe.md` (create/update)
- `docs/plans/115_owner_real_outcome_observe_work_graph.json` (create/update)
- `docs/plans/CLAUDE.md` (update)
- `ROADMAP.md` (update)

## Plan

### Critical Path Classification

| Increment | Class | Behavior or blocker changed |
|---|---|---|
| Bind and execute the merged Plan #55 progress scenario | `vertical` | The continuation contract is used on real Brian-owned progress for the first time. |
| Retain the decision and manual-friction readout | `vertical` | The next integration choice is grounded in executable owner evidence. |
| Repair an exact scenario/CLI incompatibility | `direct_blocker` only | Removes only a reproduced defect preventing the same owner scenario. |
| Add lifecycle adapters or fleet rollout | deferred | These do not belong on the critical path until the observation identifies their seam. |

### Steps

1. Create a strict scenario whose contract and receipt bind the exact Plan #55
   merge, configuration, route, output, and allowed next action.
2. Re-run the Plan #55 file-context command and verify both supplied digests.
3. Execute the scenario through the unchanged Plan #114 CLI from a clean
   candidate revision and retain its typed result, exit code, command, digests,
   delivery classification, limitations, and manual steps.
4. Compare those manual steps by expected progress protection and false-block
   risk; name the smallest evidence-supported next integration seam.
5. Run the focused Plan #114 regression, plan validation, and documentation
   checks; integrate and close the lane without promoting enforcement.

## Required Tests

| Check | What it invalidates |
|---|---|
| `scripts/doc_authority.yaml` digest | progress receipt points at different configuration |
| `file_context --json` stdout digest | claimed owner progress cannot be reproduced |
| strict scenario load | malformed or unbound evidence masquerades as progress |
| public CLI execution | models exist but owner workflow is unusable |
| approval/cost/time flags in result | operator context accidentally controls admission |
| `tests/test_outcome_continuation.py` | owner scenario relies on a regression in the Plan #114 seam |
| plan validator | adoption evidence or rollout limits are missing |

## Acceptance Criteria

- [ ] One checked-in strict scenario binds the canonical Plan #55 owner result
  to its exact merge, configuration digest, command, output digest, and
  artifacts.
- [ ] The source command is re-observed with the expected four-document output
  and both expected digests.
- [ ] The unchanged Plan #114 CLI exits `0`, leaves the lease `active`, and
  admits the exact Plan #115 evidence path as `active_in_scope`.
- [ ] Approval text, cost telemetry, and elapsed telemetry are present and
  explicitly ignored by the decision.
- [ ] Retained evidence includes exact revisions, scenario/contract/receipt/
  lease digests, command, exit code, delivery classification, and limitations.
- [ ] The readout identifies the manual step that is the strongest candidate
  for the next integration seam and states what evidence would falsify it.
- [ ] Focused continuation tests and plan validation pass on the integrated
  candidate.
- [ ] No hook, claim binding, automatic delivery, historical failure, hard
  enforcement, shell coverage, colleague, or fleet claim is made.

## Failure And Reset Rules

| Failure | Response |
|---|---|
| source output or config digest differs | inspect the exact canonical revision and preserve the mismatch; do not rewrite expected evidence silently |
| scenario validation fails | repair only the owner evidence binding or expose an exact Plan #114 contract incompatibility |
| real progress is denied | retain the full result and treat the smallest reproduced contract/admission defect as the only direct blocker |
| result is allowed but manual steps do not distinguish an integration seam | record that uncertainty and run one additional bounded manual owner action; do not guess a hook |
| evidence language implies native enforcement | correct it to manual observation and keep promotion prohibited |

## Pre-Made Decisions

- The first owner-real observation reuses the existing CLI; it does not add a
  pre-write or lifecycle adapter.
- Real Plan #55 progress is the positive owner observation. Plan #114's
  circular scenario remains the synthetic negative control.
- Progress, not approval, money, or elapsed time, controls continuation.
- The result selects a candidate next seam but does not implement or promote it.
- Enforced Planning remains the only dogfood project in this slice; colleague,
  external-user, and fleet work stay downstream.
