# Plan #118: Causal Restart Lineage And Restart-Safe Session Handoff Observe

**Status:** In Progress
**Type:** implementation (observe-only restart custody)
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "retain-outcome-and-failure-state-across-restarts"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** pilot
**Overlays:** deductive, repository governance
**Blocked By:** #117
**Blocks:** [future] independent restart review, Project Graph owner-class custody, and outcome-based blocking

---

## Gap

**Current:** Plan #117 makes outcome selection create-once inside one exact
claim-linked session tracker. Direct replacement is rejected, but the sanctioned
`session-resume` path changes the claim's `session_id` without changing the
tracker claim identity or selected binding. The resume command reports success,
then selected pre-write resolution rejects the retained outcome as foreign to
the new runtime. There is also no typed path for a stalled outcome to adopt a
materially different mechanism: the only available command is the deliberately
rejected fresh selection. An operator or agent can therefore either lose the
selected outcome during an ordinary runtime restart or start a fresh lane and
omit the predecessor failure state.

**Target:** Preserve an unchanged selected outcome, lease state, and failure
history automatically when a sanctioned handoff/session-end/stale-lane resume
attaches a new exact runtime to the same branch and worktree. Separately, add a
strict `RestartDeltaV1` and explicit restart command that can replace a stalled
or parked selected scenario only when the successor retains the same owner,
outcome, consumer, canonical journey, target, and predecessor lineage while
binding one changed causal hypothesis, changed mechanism, bounded action, next
canonical observation, and stopping condition. Append immutable transfer and
restart records in the existing tracker; do not create another live registry.

**Why:** A new session, branch, plan, or repository must not reset the evidence
scoreboard. Routine runtime turnover should be boring and lossless. A causal
restart is different: it may reset the active lease counters only after the old
failure state is retained and the proposed mechanism is explicitly different.
This closes the next concrete restart-laundering seam without claiming that
owner-class lookup, independent review identity, cross-repository successors,
or hard blocking already exist.

## User Outcome

Brian can resume an interrupted coding-agent lane without losing its selected
outcome or failure state, and a stalled project can switch mechanisms only
through one inspectable causal restart record rather than a fresh plan or
session that silently forgets why the predecessor failed.

## Canonical Behavioral Example

**Starting state:** A live claimed session has selected a checked-in scenario
whose lease is `stalled`, with three failures at the same named boundary. The
tracker, claim, scenario, contract, lease, and selected-binding digests all
match. A successor scenario in the same worktree names a new lineage, lists the
old lineage as predecessor, keeps the same owner/outcome/consumer/canonical
journey/target, and starts an active lease for a genuinely different mechanism.

**Action:** First attempt ordinary `select` with the successor and observe the
existing `selection_conflict`. Then invoke the explicit restart command with
the successor scenario and a `RestartDeltaV1` bound to the exact predecessor
binding/contract/lease and successor contract. Resolve the selected outcome
through the ordinary pre-write receipt. In a separate fixture-equivalent lane,
handoff and resume the selected stalled scenario under a new exact session ID.

**Expected observable result:** The restart command atomically appends one
transition record and replaces the current selected binding. The transition
retains predecessor lease state, non-outcome count, failure boundary, failure
count, and failed-evidence refs; the current binding points to the successor
lineage and selected pre-write returns its evaluated decision. The resumed lane
keeps the original scenario, contract, lease, and failure digests while only
the exact claim/session binding changes; the new session resolves it and the old
session cannot.

**Behavioral evidence:** Observed at candidate revision `6912ce8`: the real
exact Plan #118 claim rejected direct replacement, accepted one strict causal
restart, retained the predecessor binding/contract/lease and failure facts,
and resolved the successor from ordinary `allow/exact_live_claim` to
`would_allow/active_in_scope`. Fixture-equivalent lifecycle controls proved
lossless cross-session transfer, old-runtime denial, exact rollback, and typed
incomplete failure. See
`docs/evidence/plan118_causal_restart_lineage.json`.

**Substrate/process evidence:** Strict Pydantic contracts, atomic tracker
mutation, claim rollback checks, focused lifecycle/selection tests, and
revision-bound retained evidence support but do not replace the selected
pre-write observations.

**Failure signal:** Resume reports success but selected resolution fails; a
fresh session can drop the selection; direct `select` can replace it; an active
or recovery-required predecessor can restart; the successor changes outcome or
canonical journey; failure counters disappear; a mismatched/tampered delta is
accepted; a partial claim/tracker transition is reported as success; or the
result is described as independently reviewed, cross-project, enforced, or
fleet-wide.

## Authorities And Evidence Reviewed

- `CLAUDE.md` — repository, claim, evidence, and terminal closeout authority.
- `docs/plans/114_outcome_continuation_lease_enforcement.md` — outcome,
  progress, recovery, and lease-state contracts.
- `docs/plans/117_durable_outcome_selection_binding_observe.md` — exact-session
  create-once selection, replacement denial, and explicit promotion limits.
- `enforced_planning/outcome_continuation.py` — current
  `OutcomeContractV1`, `OutcomeLeaseV1`, and `RecoveryLeaseV1` owners.
- `enforced_planning/outcome_selection.py` — current exact claim/tracker
  binding, immutable scenario validation, and selected pre-write resolver.
- `enforced_planning/session_lifecycle.py:1553` and
  `enforced_planning/session_contracts.py:463` — reproduced resume seam: claim
  session identity changes while tracker claim/binding identity does not.
- `project-meta@f6091b6b:policy/proposals/2026-08-20-outcome-continuation-lease-hard-gate.yaml`
  — approved rule requiring `RestartDeltaV1`, predecessor failure retention,
  existing session state, and no second live registry.
- `project-meta@a2349842:investigations/cross-project/2026-08-20-recurring-project-failure-modes.md`
  — calibrated restart laundering, local-completion inflation, and status-truth
  gaps across 12 repository histories.
- `project-meta@c853c574:learnings/entries/lrn-20260821T051119239282Z-c16372dc0f.json`
  and PR #505 — owner-real evidence that goal authority must remain attached to
  the actual write claim rather than an unplanned child.
- `docs/evidence/plan117_durable_outcome_selection_binding.json` — exact
  positive/circular selection evidence and the explicit requirement for a
  restart transition before blocking promotion.

## Research

No additional web research is needed. The behavior is determined by the
approved local policy, executable tracker/claim contracts, the reproduced
resume mismatch, and revision-bound cross-project history. A comparative
framework evaluation would not change the owning seams.

## Landscape And Prior Art

| Alternative | Boundary consequence | Disposition |
|---|---|---|
| Exclude `session_id` from selected identity | Makes a stale or foreign session indistinguishable from a sanctioned transfer. | Rejected. Preserve exact identity and record an explicit transfer. |
| Let `session-resume` drop selected state | Converts ordinary runtime turnover into an evidence reset and recreates restart laundering. | Rejected. Resume must preserve selection or fail before claiming success. |
| Accept a new scenario whenever prose says “restart” | The same agent can rewrite outcome/history and call motion a changed mechanism. | Rejected. Require exact predecessor/successor/delta bindings and immutable transition history. |
| Add a global outcome registry now | Conflicts with the approved existing coordination/session-state seam and lacks Project Graph owner-class calibration. | Deferred. |
| Require cryptographic or independent review in this unit | No control-plane identity or accepted reviewer receipt contract exists yet. A string field would be review theater. | Deferred explicitly; Plan #118 validates the causal delta but remains observe-only. |
| Allow cross-project successor scenarios | Project Graph owner/predecessor lookup is not integrated and the current exact claim requires scenario project equality. | Deferred. Same-project first. |
| Preserve only the outcome ID | Loses the canonical journey, lease state, failure counters, and evidence that distinguish continuation from a reset. | Rejected. Preserve the exact predecessor binding and lease facts. |

**Alternatives:** Extend the existing tracker/session owners; weaken identity,
drop state, add a new registry, accept prose-only restart, require an
unavailable reviewer boundary, or defer. The table records why only the first
option satisfies the approved state and lineage constraints in this slice.

**Project implications:** Extend the existing outcome, selection, tracker, and
session-lifecycle owners. Do not add an alternative claim or lease registry.
Treat routine runtime attachment and causal restart as different transitions:
the first changes identity only; the second may change lineage/mechanism but
must retain the outcome and predecessor failure facts.

**Refresh trigger:** Revisit when Project Graph exposes a revision-bound
owner-class/predecessor resolver, an independent reviewer identity contract is
accepted, or a second repository needs cross-project restart custody.

**Decision method:** Contract invariants and reproduced failure boundaries are
deductive. The useful false-block rate and whether agents supply meaningful
causal deltas are empirical promotion questions, not reasons to compare
alternative frameworks.

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| Session transfer and exact binding | Deductive / plan-first | Claim, tracker, session, and scenario identities are deterministic. | Specify preflight, atomic mutations, rollback, and positive/negative tests. |
| Causal restart contract | Deductive / plan-first | Allowed predecessor states and retained fields follow approved policy. | Use strict models and reject every mismatch before tracker mutation. |
| Meaningfulness of changed mechanism | Exploratory / observe | Strings can be structurally specific without proving the mechanism is genuinely different. | Retain the delta and both-sign result; do not promote to hard enforcement in this plan. |
| Owner-class and cross-project detection | Hybrid / deferred | Contract exists, but authoritative Project Graph resolution is not wired. | Keep out of the implementation and name it as the next enforcement dependency. |

**Exploratory readout:** The real Plan #118 transition must show that direct
replacement is rejected, an exact causal restart succeeds, and the successor
selected pre-write result is usable while the full predecessor state remains
inspectable.

**Step-down path:** Any failed aggregate assertion must identify the exact
claim, tracker, binding, scenario, contract, lease, delta, or transition digest
that differed; no generic “restart invalid” result is sufficient.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| restart-safe session attachment | ended/handoff/stale claim + linked selected tracker + new native session | same selected scenario and lease rebound to the new exact claim identity plus transfer record | session lifecycle extended by Plan #118 | `session-resume`, selected pre-write resolver |
| causal restart validation | predecessor binding/scenario + successor scenario + `RestartDeltaV1` | strict accepted/rejected causal transition | outcome continuation and selection owners | explicit restart CLI |
| atomic outcome transition | exact current binding digest + validated successor binding + delta | replacement current binding plus append-only transition history | tracker mutation owner | selected pre-write observer and operator evidence |
| restart CLI | live claim identity + successor scenario + delta | machine-readable restarted/idempotent/error result | outcome-continuation CLI | Brian and coding-agent sessions |

These remain internal Enforced Planning capabilities. No LLM or model call is
needed; the unit validates evidence structure and identity, not semantic truth.

## Boundaries And Contracts

1. `OutcomeSessionTransferV1` binds prior and successor exact claim identities,
   session IDs, binding digests, the unchanged scenario/contract/lease/outcome
   digests, transfer reason (`session_resume`), and timestamp.
2. Cross-session `session-resume` with selected state performs a full preflight
   before mutation. It may change only claim/tracker/binding session identity;
   project, scope, repo, worktree, branch, tracker, authority, scenario,
   contract, lineage, target, lease, decision, and failure state stay exact.
3. Resume updates claim and tracker through one fail-loud transition. If the
   second atomic file replacement fails, the first is restored from exact
   preflight bytes; a failed rollback records/returns a typed incomplete
   transition and never reports `resumed`.
4. Same-session resume remains idempotent. A selected tracker with invalid,
   stale, or tampered identity fails before claim ownership changes. A lane
   without selected state preserves current compatibility.
5. `RestartDeltaV1` binds exact predecessor binding, contract, lease, lineage,
   lease state, non-outcome count, failure boundary/count, failed-evidence refs,
   successor contract/lineage, changed causal hypothesis, changed mechanism,
   bounded action, next canonical observation, and final stopping condition.
6. A causal restart accepts only a `stalled` or deliberately `parked`
   predecessor. `active`, `recovery_required`, and `complete` are rejected;
   recovery-required work must use its bounded `RecoveryLeaseV1`, and completed
   work needs a separately designed successor-outcome path.
7. The successor keeps the exact owner class, project, outcome ID and text,
   intended consumer, canonical journey, progress dimensions, target, and
   execution authority. Its lineage differs and directly lists the predecessor
   lineage; allowed scope and baseline revision may change for the new mechanism.
8. The successor starts an `active` lease with zero current counters. Resetting
   those current counters is licensed only because the transition permanently
   retains the exact predecessor counters and failure evidence.
9. Direct `select_outcome_for_session` replacement remains rejected. Only the
   explicit restart function may replace `tracker.outcome_selection`, and it
   appends `tracker.outcome_selection_transitions` rather than overwriting
   history.
10. Delta, predecessor, successor, binding, and transition files/models use
    strict schemas and canonical hashes. Replaying the exact accepted restart
    is idempotent; a different delta or successor against the same predecessor
    is a conflict.
11. Selected pre-write resolution continues to consume only the current binding
    and ordinary admission remains authoritative. Plan #118 changes no native
    pre-write exit behavior and makes no hard-gate claim.
12. The pilot does not prove independent review, Project Graph owner-class
    custody, cross-project successors, new-session detection outside sanctioned
    resume, break glass, installation, shell coverage, colleague use, or fleet
    adoption.

## Capability Adoption

**Disposition: extend existing owners.** Add restart contracts to
`outcome_continuation.py`, transition/transfer behavior to
`outcome_selection.py`, and sanctioned resume coupling to
`session_lifecycle.py`. Reuse `mutate_session_tracker`, the claim registry lock,
canonical hashes, the existing outcome CLI, and selected pre-write resolver.
Do not add a second live registry or a new wrapper.

Adoption evidence must execute both the real Plan #118 selected transition and
a fixture-equivalent cross-session resume, not only isolated model tests.

## Scope And Non-Goals

In scope:

- strict `OutcomeSessionTransferV1`, `RestartDeltaV1`, and
  `OutcomeRestartTransitionV1` contracts;
- automatic exact-state transfer on sanctioned cross-session resume;
- fail-loud preflight plus exact rollback behavior for claim/tracker mutation;
- explicit same-project causal restart command and idempotent replay;
- retained predecessor binding, lease/failure facts, and transition history;
- same-outcome/journey/consumer/target/authority successor validation;
- focused lifecycle, contract, selection, CLI, tamper, and regression tests;
- one real Plan #118 causal transition plus one cross-session resume control;
- evidence, operator guide, plan, graph, index, and roadmap truth.

Not in scope:

- independent reviewer-attestation enforcement or break glass;
- semantic judgment that a hypothesis/mechanism is genuinely different;
- Project Graph owner-class/predecessor resolution or WIP ceilings;
- a global lease/outcome registry;
- cross-project, cross-worktree, or cross-branch successor activation;
- completed-outcome successor selection;
- automatic selection for unrelated new sessions or repositories;
- outcome-based blocking, default hook activation, installer/fleet rollout,
  shell interception, deployment, release, or cost control.

## Files Affected

- `enforced_planning/outcome_continuation.py` (modify)
- `enforced_planning/outcome_selection.py` (modify)
- `enforced_planning/session_lifecycle.py` (modify)
- `scripts/outcome_continuation.py` (modify)
- `tests/test_outcome_continuation.py` (modify)
- `tests/test_outcome_selection.py` (modify)
- `examples/owner-real-outcome-observe/plan118-stalled-predecessor.json` (create)
- `examples/owner-real-outcome-observe/plan118-active-successor.json` (create)
- `examples/owner-real-outcome-observe/plan118-restart-delta.json` (create)
- `docs/evidence/plan118_causal_restart_lineage.json` (create)
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` (modify)
- `docs/plans/118_causal_restart_lineage_and_session_handoff_observe.md` (create/modify)
- `docs/plans/118_causal_restart_lineage_and_session_handoff_observe_work_graph.json` (create/modify)
- `docs/plans/CLAUDE.md` (modify after the current owner releases it)
- `ROADMAP.md` (modify after the current owner releases it)

## Plan

### Critical Path Classification

| Increment | Class | Behavior or named blocker changed |
|---|---|---|
| Preserve selected state through sanctioned session resume | `direct_blocker` | A successful runtime handoff no longer leaves the selected outcome unusable or resettable. |
| Execute one exact causal restart | `vertical` | A stalled lineage can switch mechanisms without dropping its outcome or predecessor failure state. |
| Resolve the successor through selected pre-write | `vertical` | The transition reaches the existing behavioral observation seam rather than ending at a schema. |
| Owner-class lookup, independent review, and hard denial | deferred | These are separate promotion dependencies and cannot be claimed from this slice. |

### Steps

1. Add failing focused tests that reproduce the current successful-resume/
   unusable-selection mismatch and direct-selection restart rejection.
2. Add strict transfer/delta/transition models and validators with exact
   predecessor/successor hashes, retained failure facts, and allowed states.
3. Add preflighted session-transfer behavior with atomic tracker mutation,
   exact claim update, rollback tests, and unchanged no-selection compatibility.
4. Add the explicit causal restart transition and CLI; preserve transition
   history and make exact replay idempotent.
5. Prove same outcome/journey/consumer/target/authority retention and reject
   active/recovery/complete predecessors, changed outcome, missing lineage,
   digest mismatch, tamper, and competing restart.
6. Run the current binding through selected pre-write after both session
   transfer and causal restart while preserving ordinary decisions and exits.
7. Execute and retain the Plan #118 owner-real causal transition plus isolated
   cross-session resume control; reconcile guide, evidence, graph, index, and
   roadmap without promotion.

## Required Tests

### New Tests (TDD)

| Test File | Test | What it invalidates |
|---|---|---|
| `tests/test_outcome_continuation.py` | strict restart delta validation | malformed or self-contradictory restart evidence reaches mutation |
| `tests/test_outcome_selection.py` | exact stalled-to-active causal restart | a legitimate changed mechanism has no explicit path |
| `tests/test_outcome_selection.py` | direct replacement, wrong state, changed outcome/journey, missing predecessor, digest tamper, competing delta | restart laundering or ambiguous history is accepted |
| `tests/test_outcome_selection.py` | idempotent exact restart and append-only transition retention | retries duplicate/reset history |
| `tests/test_outcome_selection.py` | selected cross-session resume preserves all non-identity digests | routine agent restart loses or refreshes outcome evidence |
| `tests/test_outcome_selection.py` | invalid selected resume fails before ownership change and exact rollback works | partial transitions are reported as success |
| `tests/test_session_cli.py` | unselected and same-session resume compatibility | Plan #118 breaks existing lifecycle behavior |
| `tests/test_outcome_selection.py` | post-transfer and post-restart selected resolution | contracts stop at local storage and never reach the observation seam |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_outcome_selection.py` | Plan #117 create-once, exact identity, tamper, and both-sign guarantees remain intact |
| `tests/test_outcome_continuation.py` | lease/recovery/admission semantics remain intact |
| `tests/test_session_contracts.py tests/test_session_cli.py` | tracker and lifecycle behavior remains compatible |
| `tests/test_outcome_prewrite_observation.py tests/test_prewrite_claim_projection.py` | selected observation remains advisory and ordinary admission remains authoritative |
| Plan #108/#114/#116/#117 focused regression set | prior enforcement and observation owners do not regress |
| work-graph and strict doc-coupling checks | implementation authority and public operator behavior stay synchronized |

## Acceptance Criteria

- [x] A selected handoff/session-ended/stale lane resumed by a different exact
  runtime retains the same scenario, contract, lineage, target, lease, decision,
  and failure state, appends one transfer record, resolves under the new session,
  and rejects the old session.
- [x] Invalid/stale/tampered selected state fails before resume ownership
  changes; an injected second-file failure restores the exact first-file bytes
  or returns a typed incomplete-transition result without claiming success.
- [x] A strict restart delta can replace only a stalled/parked predecessor with
  a same-owner/project/outcome/consumer/journey/target/authority successor whose
  new lineage directly names the predecessor.
- [x] The accepted restart retains predecessor binding/contract/lease digests,
  state, counters, failure boundary/count, and failed-evidence refs in immutable
  transition history while the successor receives a new active lease.
- [x] Direct reselection, active/recovery/complete predecessor, changed outcome
  or journey, missing predecessor, wrong digest/counter, file tamper, and a
  competing restart all fail without changing the current binding.
- [x] Exact restart replay is byte-idempotent and does not duplicate history.
- [x] The successor current binding resolves through selected pre-write and
  ordinary claim admission/exit behavior remains unchanged.
- [x] Retained evidence binds exact revisions, claims, trackers, sessions,
  scenarios, contracts, leases, delta, transitions, ordinary receipts, and
  selected decisions for the real and negative controls.
- [x] Evidence says observe-only causal custody—not independent review,
  owner-class enforcement, cross-project restart, blocking, installation, or
  fleet adoption.

## Implementation Readout

ORST01 is accepted at candidate revision `6912ce898ff6e9d4715a2370efe528c9fd4e1547`.
The Plan #108/#114/#116/#117/#118 focused boundary passed 137 tests, exact
restart replay preserved tracker bytes, doc-code coupling passed, and the
canonical push gate reported zero issues. The checked-in stalled predecessor
is explicitly a synthetic mechanical control executed through the real claim;
it is not represented as a reconstructed historical product lease. ORST02
remains the path-disjoint plan-index/roadmap closeout and is blocked only while
those two shared documentation paths have a live owner.

## Failure And Reset Rules

| Failure | Response |
|---|---|
| resume would change more than exact runtime identity | reject before mutation; require a separately designed migration/restart path |
| tracker or selected binding is invalid | leave claim ownership unchanged and surface the exact validation code |
| claim/tracker mutation becomes partial | restore exact preflight bytes; if restoration fails, record typed incomplete state and stop mutation |
| predecessor is active or recovery-required | reject restart; continue normally or use the existing bounded recovery lease |
| successor changes outcome/journey/consumer/target/authority | reject as a new outcome, not a restart |
| predecessor lineage or failure facts are omitted | reject as restart laundering |
| exact delta replay differs only by timestamp | return the retained transition idempotently; do not append another event |
| meaningful-mechanism quality cannot be judged structurally | retain observe result and defer hard enforcement; do not add a fake reviewer string |
| normal-project transition cannot be executed | retain the failed command/result and do not claim operational adoption |

## Pre-Made Decisions

- Keep active state in the existing claim-linked tracker; no new live registry.
- Preserve exact session identity and make transfer explicit; do not weaken the
  identity digest to make resume pass.
- Treat routine session attachment and causal mechanism restart as different
  transition types.
- Permit causal restart only from stalled or parked state; recovery-required
  work stays inside `RecoveryLeaseV1`.
- Retain the exact outcome, owner, consumer, canonical journey, target,
  authority, and predecessor failure facts.
- Allow a new lineage, baseline revision, allowed scope, and active lease only
  behind the exact causal delta.
- Keep direct selection create-once and route replacement only through restart.
- Keep ordinary admission authoritative and all Plan #118 behavior observe-only.
- Do not call an agent-authored delta independently reviewed. Bind independent
  reviewer identity in a later unit rather than adding an unverifiable field.
- Use the Project Meta PR #505 owner-real claim result as downstream seam
  evidence, not as proof of selected restart adoption.
