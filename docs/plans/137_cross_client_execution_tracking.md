# Plan #137: Observe-Only Cross-Client Execution Tracking

**Status:** Planned — user-authorized local implementation; no host activation or blocking enforcement
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "cross-client-outcome-alignment"
**Landscape disposition:** linked
**Blocked By:** None
**Blocks:** measured evidence for any later completion-enforcement decision

## Authority and decision

Brian authorized implementation on 2026-09-12 after reviewing the tentative
cross-client execution-tracking design. The reviewed source has SHA-256
`b95c2aa077113091b9510307c5e31011e554189d7ce9905697aa2dd9b3649833`.

This plan incorporates the review correction: it does not create a second
mailbox acknowledgement protocol or a second outcome store. Enforced Planning
owns the neutral lifecycle and completion decision. Company Planning continues
to own project and work-unit meaning. AES and client integrations translate
native events without gaining authority to close the outcome.

## Gap

**Current:** Enforced Planning can retain selected outcomes, criterion-bound
evidence, recovery lineage, and message acknowledgements. AES can supervise a
native Codex thread and retain pushed App Server events. Those capabilities do
not yet expose one stable execution-item projection across Codex and Claude, a
typed native/canonical divergence record, or a terminal proposal that joins
resolved execution items back to every frozen outcome criterion.

**Target:** One small neutral extension supplies those missing concepts. Thin
runtime adapters project it into native client surfaces, while the existing
outcome lineage remains authoritative and one both-sign local fixture measures
where each client can and cannot intercept transitions.

## User outcome

Brian can see whether a long-running Codex or Claude session is still advancing
the same approved outcome, which obligations remain, and whether completion is
actually evidenced. Native task displays stay useful, but a green checklist,
turn ending, transport success, or subagent report cannot silently become goal
completion.

## Canonical behavioral example

**Starting state:** One disposable goal has two frozen criteria and two stable
execution items. The same canonical state can be projected into isolated Codex
and Claude sessions.

**Action:** Complete both displayed items while withholding current evidence
for criterion two. Then add valid evidence, rename and reorder the display
items, hand the work across clients, and replay one event.

**Expected result:** The first completion proposal is denied and the missing
criterion remains visible. The evidenced proposal succeeds once. Rename,
reorder, handoff, and replay retain the stable identities and do not duplicate
state. Existing mailbox receipts distinguish persisted, observed, and
acknowledged messages without implying authority or user authorship.

**Failure signal:** Native green state closes the goal; checklist edits remove
an obligation; a queued message is reported as received; automation is rendered
as Brian-authored input; replay duplicates a transition; unavailable hooks are
reported as enforcement; or adapter failure mutates canonical state.

## Ownership and reuse

| Concern | Existing owner | Plan 137 disposition |
|---|---|---|
| Outcome identity, criteria, evidence, rejection lineage, review readiness | Enforced Planning `OutcomeContractV1` and Plan #136 | Extend only the missing execution projection and terminal proposal |
| Selected outcome, progress, recovery, and custody | Enforced Planning Plans #114–#125 | Link; do not duplicate |
| Cross-client messages and acknowledgement | Enforced Planning Plans #67 and #100 | Reuse unchanged; `persisted`, `runtime_accepted`, `observed`, and `acknowledged` retain their existing meanings |
| Project/work-unit DAG | Company Planning | Reference stable work-unit IDs; do not copy project authority into the session ledger |
| Codex App Server process and pushed events | AES Plan #13 native adapter | Add a thin projection/observation adapter behind the neutral contract |
| Claude Task and hook events | Enforced Planning client adapter surface | Add a thin projection/observation adapter; no host-wide activation |
| Semantic judgment | Approved light LLM or independent verifier | Off the transition hot path; result is evidence input, never the state-transition authority |

The representation gap is narrow. Current outcome state has criterion and
artifact identity but no stable client-neutral execution-item projection or
record of native/canonical divergence. `review_ready` is not the same as a
terminal `complete` proposal. These are the only new neutral concepts.

## References Reviewed

- `enforced_planning/outcome_continuation.py` and
  [Plan #136](136_criterion_bound_outcome_gate.md) — current criterion,
  artifact, verifier, review-readiness, lease, and completion state.
- Plans #114–#125 — selected outcome, retained progress, recovery, installed
  consumer, and completion-ownership boundaries.
- `enforced_planning/coordination_messages.py` and Plans #67/#100 — existing
  persisted/observed/acknowledged message lifecycle and native Codex delivery.
- Plan #32 — existing Codex/Claude session-adapter identity boundary.
- AES `src/aes/orchestration/contracts.py`, `native_codex.py`, and
  `supervisor.py` — current context, task, native event, terminal observation,
  recovery, verification, and App Server ownership.
- AES Plan #13 — accepted portable supervisor boundary and authentic native
  fixture requirement.
- Project Meta `vision/ARCHITECTURAL_IDEAS.md` — typed provider adapters,
  progress-event typing, causal event evidence, and deterministic terminal
  outcomes derived from cross-field validation.

## Landscape And Prior Art

**Disposition: linked.** Compose the existing
[criterion-bound outcome lifecycle](136_criterion_bound_outcome_gate.md),
mailbox, and client-adapter seams with AES's existing App Server adapter. The
reviewed native Codex and Claude surfaces determine adapter capability, but do
not replace the neutral owner. The accepted tentative design contains the
external documentation citations and version assumptions; implementation must
refresh them through isolated live probes before claiming native support.

## Capability Adoption

**Disposition: extend.** Extend Enforced Planning's outcome contract with the
minimum missing projection and terminal proposal. Extend AES's native Codex
adapter and Enforced Planning's Claude adapter surface. Reuse Plan #67
acknowledgement unchanged. The cross-client fixture is the required authentic
consumer; source-only tests cannot establish adoption.

## Capabilities

| Capability | Owner | Change | Consumer evidence |
|---|---|---|---|
| Canonical execution projection and goal proposal | Enforced Planning | Extend Plan #136 outcome lineage | Both-sign cross-client fixture |
| Durable messaging and acknowledgement | Enforced Planning Plan #67 | Reuse unchanged | Handoff receipt keeps its weaker semantics |
| Native Codex projection/observation | AES | Extend Plan #13 App Server adapter | Isolated App Server trace |
| Native Claude projection/observation | Enforced Planning client adapter | Add thin isolated adapter | Isolated Task/hook trace |
| Project/work-unit meaning | Company Planning | Link only | Stable work-unit reference survives projection |
| Semantic criterion review | Approved verifier route | Supply evidence off hot path | Criterion receipt with explicit uncertainty/provenance |

## Contract

1. A neutral execution item has a stable ID, parent outcome contract digest,
   display label, status, criterion references, dependency IDs, owner role, and
   source provenance. Position and prose are never identity.
2. Canonical state is authoritative. A native update is an observation or a
   transition intent; it cannot directly write canonical completion.
3. Accepted transitions compare the expected prior revision and idempotency
   key. Exact replay returns the retained result; stale or conflicting input
   fails visibly.
4. Native projection happens after canonical acceptance. Projection failure
   records typed divergence and leaves canonical state unchanged.
5. One `propose_goal_completion` operation checks the current authorized goal
   revision, every frozen criterion, exact artifact/evidence revisions, and the
   complete execution-item set. It is the only terminal success path.
6. Human review, preservation, cancellation, interruption, transport failure,
   hook unavailability, and blocking remain non-success states. They do not
   create automatic execution eligibility or a successor offer.
7. Message provenance remains explicit. Plan #67 receipts do not imply Brian
   authored a message, adopted its content, or authorized execution.
8. Deterministic checks own identity, revision, dependency, replay, and state
   invariants. Semantic adequacy is never inferred with regex or string
   matching; when needed it is supplied as criterion-bound verifier evidence.

## Enforcement tier

This plan is **measured/observe-only**. The canonical controller can deny its
own `propose_goal_completion` call, but Plan 137 does not claim that every native
Codex or Claude action is synchronously interceptable. App Server notifications
observe changes after they happen. Client hooks may intercept only the paths
authentically proven in the isolated fixture. Unsupported or bypassed paths are
reported as `unavailable` or divergent and cannot certify completion.

No global configuration, installer default, fleet activation, TUI attachment,
daemon, scheduler, dashboard, OpenClaw path, or blocking Stop hook is authorized.

## Critical Path Classification

**Critical-path classification: `vertical`.** The work stops after one authentic
cross-client fixture demonstrates visible progress, denied incomplete closure,
accepted evidenced closure, and stable handoff/replay behavior.

| Unit | Classification | Why it is on the path |
|---|---|---|
| XCET-01 | `direct_blocker` | Both adapters require the same accepted neutral contract. |
| XCET-02 | `direct_blocker` | The integrated journey requires authentic Codex projection evidence. |
| XCET-03 | `direct_blocker` | The integrated journey requires authentic Claude projection evidence. |
| XCET-04 | `vertical` | This is the user-visible both-sign cross-client result. |

## Plan

The contract and adapters are `direct_blocker` units; the integrated fixture is
the single `vertical` unit. No enabler or hardening unit may delay that fixture.

1. **XCET-01 — neutral contract.** Add the execution projection, divergence,
   and canonical completion-proposal types and both-sign tests in Enforced
   Planning. Reuse Plan #136 and Plan #67 directly.
2. **XCET-02 — Codex adapter.** In AES, translate the neutral projection to the
   installed App Server surface and retain pushed native observations. Report
   unsupported capabilities rather than manufacturing parity.
3. **XCET-03 — Claude adapter.** Translate the same neutral projection to an
   isolated Claude Task surface and retain typed tool/hook observations. Keep
   host configuration unchanged.
4. **XCET-04 — integrated fixture and feedback.** Run the canonical example
   across both isolated clients through their public local entrypoints. Retain
   false-pass, false-block, divergence, replay, friction, version, and latency
   observations suitable for a later promotion decision.

XCET-01 owns its own acceptance update across the graph and three human-facing
status surfaces. XCET-02 and XCET-03 become ready after XCET-01 and can execute
in parallel in disjoint repositories. Because the AES lane cannot write the
Enforced Planning graph, XCET-03 owns the joint adapter acceptance transition:
it may mark XCET-02 and XCET-03 accepted only after independently verifying the
exact merged AES evidence and its own Claude evidence. XCET-04 requires both
accepted adapters and owns the final synchronized closeout across the plan,
graph, roadmap, and plan index.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| Neutral identity and completion | fully_specifiable_now | Typed deterministic extension of Plan #136 | Both-sign contract tests discriminate | Unblocks both adapters |
| Codex native projection/interception | exploration_required | Existing AES App Server adapter; observation is weaker than interception | One isolated installed-version probe records supported and bypassed paths | Qualifies Codex capability claim |
| Claude native projection/interception | exploration_required | Existing client hook identity; Task behavior must be observed | One isolated installed-version probe records supported and disabled paths | Qualifies Claude capability claim |
| Semantic adequacy | exploration_required | Criterion-bound independent evidence, never regex prose inference | Fixture verifier finds no false pass in the frozen two-criterion case | Feeds measured promotion evidence |
| Blocking promotion | human_decision_required | Explicitly excluded from this plan | Measured false-pass/false-block evidence is reviewed | Separate owner decision only |

## Acceptance criteria

- [ ] The neutral contract adds no duplicate outcome, claim, session, mailbox,
      project, or work-unit authority.
- [ ] Stable item identity survives display rename/reorder and event replay.
- [ ] All-green native items with one missing or stale criterion receipt cannot
      close the canonical goal.
- [ ] A current fully evidenced result closes exactly once through
      `propose_goal_completion`.
- [ ] Codex and Claude isolated sessions visibly project the same canonical
      fixture and retain native event evidence with client/version/configuration.
- [ ] Disabled, unavailable, bypassed, malformed, reordered, and projection-
      failed paths remain non-success and visible without corrupting canonical
      state.
- [ ] A cross-client handoff preserves outcome, item, criterion, evidence, and
      coordinator-custody identities; message acknowledgement retains Plan #67
      semantics and never implies execution authority or user authorship.
- [ ] The public local fixture records both the intended pass and discriminating
      negative controls, plus feedback data for false passes, false blocks,
      friction, latency, and unsupported capability incidence.

## Verification

- Focused Pydantic contract tests for identity, revision, dependencies,
  idempotency, evidence freshness, completion, and divergence.
- Adapter tests against recorded or disposable native surfaces, followed by one
  isolated authentic Codex run and one isolated authentic Claude run.
- One public local cross-client fixture that intentionally fails incomplete
  completion before passing the evidenced case.
- Existing outcome-continuation, criterion-gate, mailbox, and AES orchestration
  suites stay green where their seams are touched.

Unit tests and hand-authored transcripts do not prove adoption. If either native
client cannot be exercised authentically, the plan remains partial and names
the exact unverified boundary.

## Feedback loop

Each fixture episode records the canonical transition, native observation,
adapter capability result, verifier evidence, divergence/reconciliation result,
latency, and operator friction without prompt or response content. A later
promotion decision compares false-pass and false-block cases and samples these
records for semantic misses. Recurring failures route through the existing
Plan #111 ecosystem-feedback seam; Plan 137 creates no second learning store and
does not automatically rewrite policy from one episode.

## Reassessment contract

**Triggers:** The first adapter needs a second authoritative store; a native
surface lacks stable correlation; the fixture needs global configuration; or
two implementation increments fail to advance the canonical example.

**Autonomous action:** Stop the affected adapter, retain the observed limitation,
and continue only on an independent ready unit. Prefer a thinner projection or
existing host seam over new infrastructure.

**Plan revision required:** Changing the authoritative owner, adding blocking
host enforcement, adding a persistence service, or broadening beyond the
isolated fixture requires a new revision.

**Human decision required:** Fleet activation, global client configuration,
blocking native-session enforcement, or weakening a frozen criterion requires
Brian's explicit decision.

**Stopping rule:** Stop this plan when the public local fixture proves both-sign
cross-client behavior and the status surfaces truthfully record the result.

## Non-goals

- Replacing Company Planning or its work graph.
- Rebuilding Plan #67 acknowledgement or Plan #136 criterion evidence.
- Building an always-on reviewer, project-management system, dashboard,
  scheduler, daemon, OpenClaw integration, or second ledger.
- Treating queue acceptance, an open TUI, a running process, native green state,
  or worker prose as completion.
- Fleet rollout, deployment, publication, or broad policy enforcement.

## Files expected

- Enforced Planning: neutral contracts, focused tests, isolated Claude adapter,
  fixture/evidence, and the four canonical Plan #137 status surfaces.
- AES: existing orchestration contract/adapter extensions and focused tests.
- No other repository is an implementation target.
