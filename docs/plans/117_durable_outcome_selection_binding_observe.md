# Plan #117: Durable Outcome Selection And Exact-Session Binding Observe Pilot

**Status:** 📋 Planned
**Type:** implementation (observe-only session binding)
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "bind-one-claimed-session-to-one-durable-outcome-selection"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** linked
**Execution profile:** pilot
**Overlays:** deductive, repository governance
**Blocked By:** #116
**Blocks:** [future] representative owner calibration and outcome enforcement

---

## Gap

**Current:** Plan #116 can correlate an immutable outcome scenario with an
ordinary claimed write, but every invocation must be handed a scenario path.
Nothing in the live claim or its linked session tracker owns that choice. An
agent can omit the option, choose a different scenario on the next write, or
carry an old scenario into a replacement session without producing a binding
failure. The outcome decision is useful, but continuation identity is still
caller-selected.

**Target:** Let one exact live claimed session select one immutable outcome
scenario into its existing linked session tracker. A new explicit
`--outcome-selected` pre-write option resolves that stored choice through the
ordinary receipt's exact claim source, validates session/worktree/branch and
scenario digests, and appends the existing observe-only outcome decision with
selection-binding evidence. Missing, conflicting, stale, tampered, or
cross-session state fails visibly while ordinary claim admission remains
authoritative.

**Why:** The approved ecosystem policy requires continuation evidence to be
owned by coordination/session state rather than supplied afresh by the same
agent asking to continue. Cross-project Git-history calibration also found
restart laundering, plan-completion inflation, and governance substitution.
Durable exact-session selection closes one concrete bypass without pretending
that automatic outcome choice, mutable leases, or blocking are already solved.

## User Outcome

Brian can inspect one claimed session and see which outcome it is actually
working toward. The same selected outcome is used on every opted-in pre-write
observation; silently switching the outcome, scenario, session, branch, or
worktree produces a typed visible failure instead of a fresh permissive choice.

## Canonical Behavioral Example

**Starting state:** A live Plan #117 Codex claim links to one session tracker
and owns `docs/evidence/plan117_durable_outcome_selection_binding.json`. The
Plan #117 owner-progress scenario is an immutable file inside that worktree.

**Action:** Select the scenario once through the outcome-continuation CLI, then
send the claimed evidence-file `apply_patch` payload through
`scripts/prewrite_claim_gate.py --mode observe --outcome-selected` without
passing a scenario path.

**Expected result:** The tracker contains one strict `outcome_selection`
binding. The ordinary decision remains `allow/exact_live_claim`; the outcome
observation resolves the exact claim and tracker, records the selection digest,
and returns `would_allow/active_in_scope`. In an isolated same-contract control,
a selected circular scenario returns `would_deny/recovery_required`. Replaying
with a different session identity or a modified selected file records a typed
observation error while retaining the ordinary result and exit code.

**Failure signal:** A second different selection overwrites the first; a
heartbeat erases the selection; a replacement session, branch, worktree, claim,
or modified scenario is accepted; selected observation falls back to a caller
scenario; ordinary admission changes; storage is partial or unlocked; or the
result is described as automatic, blocking, installed, or fleet-wide.

## Authorities And Evidence Reviewed

- `CLAUDE.md` — repository, claim, evidence, and closeout authority.
- `docs/plans/108_prewrite_claim_enforcement.md` — authoritative ordinary
  claimed-write decision and compatibility boundary.
- `docs/plans/114_outcome_continuation_lease_enforcement.md` — typed outcome,
  progress, lease, and admission contracts.
- `docs/plans/116_prewrite_outcome_correlation_observe.md` — explicit scenario
  observation, same-payload proof, and promotion limits.
- `enforced_planning/session_contracts.py` and
  `enforced_planning/session_lifecycle.py` — existing claim-linked tracker
  owner and current non-atomic YAML writers.
- `enforced_planning/outcome_prewrite_observation.py` and
  `scripts/prewrite_claim_gate.py` — current correlation owner and public
  optional wrapper seam.
- `project-meta@f6091b6b:policy/proposals/2026-08-20-outcome-continuation-lease-hard-gate.yaml`
  — approved progress-not-approval policy and existing-session-state mandate.
- `project-meta@a2349842:investigations/cross-project/2026-08-20-recurring-project-failure-modes.md`
  and its JSON evidence — calibrated burst thrash, local-completion inflation,
  governance substitution, restart laundering, and status-truth gaps across 12
  retained repository revisions.

## Research

No additional web research is required. This unit is constrained by the
approved policy, revision-bound local history, current coordination contracts,
and an executable owner-real boundary. Generic orchestration patterns would not
decide how this exact claim and tracker must bind.

## Landscape And Prior Art

| Candidate | Evidence and implication | Disposition |
|---|---|---|
| Store selection in the existing claim-linked session tracker | The tracker is already the richer per-session authority and is linked from the exact live claim. This satisfies the approved lineage without another registry. | Adopted. |
| Add scenario or outcome fields to the fast projection | It would change the dependency-light ordinary boundary before selection ownership is proven. The ordinary receipt already exposes the exact claim source needed for a lazy selected lookup. | Rejected for this pilot. |
| Continue accepting `--outcome-scenario` on every write | Plan #116 proved evaluation but leaves the deciding agent free to omit or switch the scenario. | Retained only as backward-compatible explicit observation, not the selected path. |
| Automatically infer an outcome from plans or repository names | The history calibration shows that plans and successor names can launder unchanged outcomes. No representative semantic selector exists. | Deferred. |
| Block writes immediately when selection is missing or denied | Representative false-block evidence and supported-flow calibration do not exist. | Deferred. |

One lineage remains authoritative: Plan #108 owns ordinary write admission;
Plans #114–#116 own outcome evaluation and explicit correlation; Plan #117 owns
only durable exact-session selection and observe-mode resolution.

## Design Profile And Epistemic Split

This is a `pilot`. Exact claim/session identity, create-once selection,
scenario immutability, atomic tracker mutation, both-sign evaluation, and
ordinary-exit preservation are deductive. Whether the selection is usable on
representative normal project work, what should select it automatically, and
when denial may block remain exploratory and require retained observations.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| exact-session outcome selection | live claim identity + immutable scenario | strict create-once binding in the linked tracker | Plan #117 selection owner | selected pre-write observer |
| atomic tracker mutation | existing tracker + bounded transformation | locked, atomically replaced YAML preserving unrelated session fields | session-contract owner | lifecycle and outcome selection |
| selected outcome observation | ordinary receipt + exact claim/tracker state | typed `would_allow`, `would_deny`, or visible binding failure | existing Plan #116 observer extended by Plan #117 | Brian/operator evidence run |
| explicit selection CLI | claim/session identity + scenario | machine-readable selected/idempotent/error result | existing outcome-continuation CLI | Brian and his coding agents |

These capabilities remain native to Enforced Planning. A shared contract is
deferred until a second authentic repository consumes the boundary; no LLM is
needed for this deterministic binding slice.

## Boundaries And Contracts

1. Selection resolves exactly one live canonical claim by agent, project,
   scope, and native session ID; ambiguity, missing identity, unhealthy state,
   or a missing tracker fails loud.
2. The selected scenario must be a strict `OutcomeContinuationScenarioV1`
   file inside the claim worktree and its outcome project must equal the claim
   project.
3. `OutcomeSelectionBindingV1` retains the stable claim-identity digest,
   tracker path, scenario path/file/scenario/contract/lease digests, outcome and
   predecessor lineage, target, initial decision, and selection timestamp.
4. Stable claim identity includes agent, project, scope, session ID, repository,
   worktree, branch, tracker, and claim source. Mutable heartbeat/expiry fields
   do not invalidate an otherwise identical session.
5. Selection is create-once: the same binding is idempotent; a different
   scenario or identity cannot replace it through the selection command.
6. Tracker reads and writes use one sibling lock and same-filesystem atomic
   replacement. Existing heartbeat/resume updates preserve the selection.
7. `--outcome-selected` and `--outcome-scenario` are mutually exclusive. The
   selected path derives its scenario only from the exact tracker binding.
8. No-option behavior and the existing explicit scenario behavior remain
   compatible. The ordinary decision runs and records first and remains the
   only authority controlling output and exit status.
9. Selected success receipts retain the selection-binding digest and tracker
   reference. Expected binding failures append typed visible observations.
10. The pilot neither performs the write nor claims automatic selection,
    mutable lease renewal, hard denial, installation, shell coverage, colleague
    use, or fleet adoption.

## Capability Adoption

**Disposition: extend the existing owners.** Add one selection contract owner,
reuse the session tracker instead of creating a registry, route tracker writers
through one atomic mutation seam, extend the current outcome CLI, and let the
current pre-write wrapper lazily request the selected scenario. Adoption
evidence must include one real Plan #117 claimed session, not only unit tests.

## Scope And Non-Goals

In scope:

- one strict outcome-selection binding and exact-claim resolver;
- create-once storage in the existing linked session tracker;
- atomic/locked tracker writes that preserve unrelated fields;
- one explicit selection subcommand and one selected pre-write flag;
- selected success/failure receipt metadata;
- focused identity, tamper, concurrency-preservation, both-sign, and
  compatibility tests;
- one real Plan #117 positive selection observation, one isolated circular
  control, and retained evidence;
- plan, work graph, index, and roadmap reconciliation.

Not in scope:

- automatic semantic outcome selection or Project Graph lineage lookup;
- progress-receipt authoring, mutable lease renewal, recovery, restart review,
  break-glass, or owner-class WIP enforcement;
- claim/projection schema changes or default hook activation;
- outcome-based blocking, shell interception, installer, downstream repository,
  colleague, fleet, deployment, or release work;
- bulk project status changes, a new planning framework, or cost controls.

## Files Affected

- `enforced_planning/outcome_selection.py` (create)
- `enforced_planning/session_contracts.py` (update)
- `enforced_planning/session_lifecycle.py` (update)
- `enforced_planning/outcome_prewrite_observation.py` (update)
- `scripts/outcome_continuation.py` (update)
- `scripts/prewrite_claim_gate.py` (update)
- `tests/test_outcome_selection.py` (create)
- `tests/test_outcome_prewrite_observation.py` (update)
- `tests/test_session_contracts.py` (update)
- `examples/owner-real-outcome-observe/plan117-owner-progress.json` (create)
- `examples/owner-real-outcome-observe/plan117-circular.json` (create)
- `docs/evidence/plan117_durable_outcome_selection_binding.json` (create)
- `docs/plans/117_durable_outcome_selection_binding_observe.md` (create/update)
- `docs/plans/117_durable_outcome_selection_binding_observe_work_graph.json` (create/update)
- `docs/plans/CLAUDE.md` (update)
- `ROADMAP.md` (update)

## Plan

### Critical Path Classification

| Increment | Class | Behavior or blocker changed |
|---|---|---|
| Persist one exact-session selection atomically | `vertical` | Continuation identity stops being chosen independently on every write. |
| Resolve selected state through the ordinary receipt | `vertical` | Session/worktree/branch/scenario drift becomes visible at the real adapter. |
| Observe one real positive and one circular control | `vertical` | The selected path proves both signs while preserving ordinary admission. |
| Automatic selection, mutable lease, or hard block | deferred | These require representative calibration and separate promotion evidence. |

### Steps

1. Add failing focused tests for strict binding, idempotence, replacement denial,
   exact identity, scenario tamper, and tracker-field preservation.
2. Add one locked atomic tracker mutation seam and route existing tracker
   writers plus selection through it.
3. Extend the outcome CLI with exact-live-claim selection and the pre-write
   wrapper with mutually exclusive selected observation.
4. Prove unchanged no-option/explicit behavior, selected both signs, stale
   session/branch/worktree failures, and ordinary decision/exit preservation.
5. Execute and retain one real Plan #117 claimed-session selection and pre-write
   observation; retain the isolated circular negative control.
6. Reconcile evidence, plan, graph, index, and roadmap without promotion.

## Required Tests

| Check | What it invalidates |
|---|---|
| strict selection and create-once idempotence | the same session can silently switch outcomes |
| exact claim/tracker/session/worktree/branch binding | stale or foreign state can authorize observation |
| scenario file and typed-content digest binding | selected authority changes in place |
| atomic tracker update and heartbeat preservation | concurrent/lifecycle writes erase or truncate selection |
| selected positive and circular negative paths | the durable path cannot discriminate progress from motion |
| missing/stale/tampered binding receipt | selected failures become silent permissive fallbacks |
| no-option and explicit-scenario CLI regressions | the existing ordinary/Plan #116 boundaries changed |
| ordinary allow/deny and exit preservation | observation accidentally became enforcement |
| Plan #108/#114/#116 focused regressions | binding relies on a regression in an existing owner |
| plan/work-graph validation | execution or promotion boundaries are missing |

## Acceptance Criteria

- [ ] One exact live session can select one strict immutable scenario into its
  existing linked tracker; identical reselection is idempotent and a different
  selection is rejected.
- [ ] Binding and lookup validate stable claim identity, tracker identity,
  session, repository, worktree, branch, claim source, scenario file, scenario
  content, contract, lease, outcome lineage, and target.
- [ ] Tracker creation/update/selection writes are locked and atomic, and a
  normal heartbeat/resume-style update preserves `outcome_selection`.
- [ ] `--outcome-selected` derives the scenario only from exact live session
  state; it is mutually exclusive with `--outcome-scenario`.
- [ ] Missing, stale, foreign, replaced, or tampered selection state appends a
  typed visible observation failure without changing ordinary admission or its
  exit code.
- [ ] A selected positive scenario produces `would_allow/active_in_scope`; an
  isolated selected circular control produces
  `would_deny/recovery_required`.
- [ ] No-option and explicit Plan #116 behavior remain compatible, and focused
  Plan #108/#114/#116 regressions pass.
- [ ] Retained real evidence binds the Plan #117 claim, tracker, selection,
  scenario, ordinary receipt, correlation receipt, revisions, and digests.
- [ ] Evidence and status truthfully say manual opt-in observe pilot—not
  automatic selection, mutable lease, enforcement, installation, or fleet use.

## Failure And Reset Rules

| Failure | Response |
|---|---|
| tracker mutation can truncate or lose unrelated fields | keep selection unshipped and repair the atomic owner before another adapter run |
| heartbeat or claim refresh invalidates stable identity | remove mutable claim fields from the identity digest only after proving exact session identity remains intact |
| a different selection can replace the first | reject replacement and require a separately reviewed restart/change path |
| selected lookup needs projection changes | stop the unit and plan that prerequisite instead of widening the fast gate |
| ordinary decision or exit changes | revert selected wrapper coupling; retain standalone selection evidence |
| real selected observation cannot bind exactly | retain the mismatch as the result; do not claim durable ownership |
| circular and progress scenarios do not differ | inspect receipt/lease lineage; do not tune ordinary claim admission |

## Pre-Made Decisions

- Use the existing linked session tracker; do not create another live registry.
- Bind stable exact-session identity, not mutable heartbeat or cost telemetry.
- Make selection create-once and explicit for this pilot.
- Extend the existing outcome and pre-write owners; do not create a second gate.
- Keep ordinary claim admission authoritative and observe-only.
- Treat the Project Meta history calibration as representative failure-mode
  evidence, not as causal proof or automatic outcome labels.
- Test on Enforced Planning first; normal-project calibration and any blocking
  promotion remain downstream.
