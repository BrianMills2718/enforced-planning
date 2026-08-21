# Plan #122: First-Consumer Outcome Admission Gate

**Status:** Complete — opt-in first source consumer implemented and accepted; activation excluded
**Type:** implementation (hard opt-in source consumer; activation excluded)
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "first-consumer-outcome-admission"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** pilot
**Overlays:** deductive, first-consumer integration
**Blocked By:** #121
**Blocks:** source-repository activation evidence and any later installer/fleet promotion

---

## Decision

Implement one canonical production outcome-admission owner and bind it to the
Enforced Planning source repository's sanctioned lifecycle without enabling it
by default. The first consumer consists of:

1. one narrow, source-owned allocation-bootstrap check before the sanctioned
   `make worktree` bundle creates a plan-owned claim, worktree, and session;
2. exact selected-outcome admission before an explicitly opted-in session
   start/renewal or heartbeat mutation; and
3. exact selected-outcome admission after ordinary claim admission but before
   an explicitly opted-in native pre-write returns success.

The gate must derive portfolio and continuation state from the existing claim,
tracker, selection, allocation ledger, and effective scenario. Public lifecycle
callers may choose whether this unactivated pilot runs, but they may not assert
that an allocation is active or that a lease is healthy.

Plan #121's signed-off pure candidate becomes a regression consumer of the new
production decision rather than a second implementation. The retained Plan
#121 revision remains immutable evaluation evidence.

## Plan

**Critical-path classification: vertical.** This unit is accepted only when
the stable Plan #122 journey crosses bootstrap, exact allocation/selection,
heartbeat, and pre-write through public commands. The production contracts and
adapters are enablers inside that vertical; they do not advance status alone.

Implement the pure owner and frozen-suite delegation first, then the exact
selected-state resolver, adapters, and append-only evidence. Exercise the real
positive lane before adding generalized hardening. Use only focused regression
checks until the authentic boundary has been observed.

## Capability Adoption

**Disposition: extend.** Extend the existing `outcome_continuation`,
`outcome_portfolio`, `outcome_selection`, ordinary claim, session lifecycle,
and pre-write owners. Supersede only the duplicate decision algorithm inside
the current Plan #121 evaluator by delegating it to the production owner. Do
not add a second allocation, selection, claim, tracker, or lease registry.

## Gap

Plan #121 proved the admission ordering on 29 scored frozen cases and eight
fresh adversarial cases, but its candidate accepts already-classified states.
It does not reopen live claim, tracker, selection, allocation, or continuation
evidence, and no lifecycle entrypoint consumes its answer.

This leaves two ways to keep circular work moving:

- a sanctioned session heartbeat can renew liveness without selected outcome
  progress; and
- an ordinary claimed write can return success even when selected outcome
  continuation reports stalled or recovery-required.

A naive fix creates a bootstrap deadlock: portfolio allocation requires a live
claimed worktree and a scenario inside it, while a new-work gate would require
allocation before creating either. The production consumer therefore needs one
narrow bootstrap that can create only plan/index and outcome-admission input
artifacts. It cannot authorize source, test, product, or arbitrary repository
writes.

## References Reviewed

- `CLAUDE.md` — source-repository workflow, first-consumer boundary, and
  proportional verification authority.
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — canonical claim,
  session, worktree, selection, progress, and portfolio lifecycle.
- `docs/plans/121_outcome_admission_false_block_evaluation.md` and
  `docs/evidence/plan121_outcome_admission_evaluation.json` at `2b4643e` —
  signed decision ordering, controls, non-claims, and promotion scope.
- `enforced_planning/outcome_admission_evaluation.py` at `2b4643e` — evaluated
  pure candidate and frozen adapter surface.
- `enforced_planning/outcome_selection.py` at `2b4643e` — exact claim/tracker,
  selected scenario, active allocation, and current-head resolver.
- `enforced_planning/outcome_portfolio.py` at `2b4643e` — append-only active
  allocation authority.
- `enforced_planning/session_lifecycle.py`, `scripts/session_start.py`, and
  `scripts/session_heartbeat.py` at `2b4643e` — mutation entrypoints.
- `scripts/prewrite_claim_gate.py` at `2b4643e` — ordinary authority and
  observe-only selected correlation boundary.
- `Makefile` and `scripts/worktree-coordination/create_worktree.py` at
  `2b4643e` — sanctioned bootstrap orchestration and scoped claim check.

## Research

No web research is needed. The uncertainty is local and executable: whether
the accepted ordering can derive its inputs from current exact lifecycle state
and deny before mutation without changing default behavior. Exact source,
public-command execution, and both-sign runtime receipts answer that question.

## User Outcome

Brian gets a real enforcement seam that can stop "I approve, continue" from
renewing or writing a circular selected outcome. The same seam still permits a
bounded allocation bootstrap, active outcome work, one declared recovery
action, passive inspection/replay/preservation/closeout, and time-bounded
legacy cutover until renewal.

The visible first-consumer proof is one actual Enforced Planning lane that:

- passes the bootstrap gate with only Plan #122 and outcome-admission input
  artifacts;
- allocates and selects an exact Project Graph-bound maintenance outcome;
- passes opted-in heartbeat and pre-write admission while active; and
- exercises equivalent synthetic live state through the same public commands
  to reject missing selection, bootstrap source-write smuggling, and circular
  continuation.

## Canonical Behavioral Example

**Starting state:** Ordinary claim authority allows a write to the exact
Plan #122 target. The claim-linked tracker retains a schema `1.1.0` selected
outcome whose exact portfolio allocation is active.

**Action:** Invoke the source-owned pre-write adapter with ordinary enforcement
and explicit selected-outcome admission enabled.

**Expected result:** An active or bounded-recovery effective lease returns zero
with `outcome_admission_active` or `bounded_recovery_active`. A
recovery-required, stalled, terminal, missing, mismatched, disposed, or
out-of-scope selection returns nonzero even though ordinary claim authority and
operator approval would otherwise allow the write.

**Failure signal:** Any live entrypoint trusts caller-supplied portfolio or
continuation labels; ordinary denial is overridden; bootstrap permits a source
or test path; legacy state renews without allocation; outcome failure becomes a
notice while the opted-in hard command exits zero; or default unactivated calls
change behavior.

## Production Contract And Ordering

The canonical `OutcomeAdmissionRequestV1` and `OutcomeAdmissionDecisionV1`
preserve Plan #121's exact ordering:

1. calibration-only scope defers and cannot be promoted;
2. ordinary authority denial remains denial;
3. dedicated safe operations remain allowed;
4. grandfathered work remains allowed only until renewal;
5. allocation bootstrap allows only the fixed first-consumer artifact set;
6. every renewed mutation requires the exact active portfolio allocation; and
7. only active in-scope or one bounded recovery continuation is allowed.

Stable denial reasons remain:

- `ordinary_authority_denied`
- `admission_bootstrap_scope_violation`
- `admission_bootstrap_state_invalid`
- `portfolio_allocation_required`
- `portfolio_slot_occupied`
- `portfolio_allocation_inactive`
- `portfolio_allocation_mismatch`
- `outcome_selection_required`
- `out_of_scope`
- `recovery_required`
- `outcome_stalled`
- `outcome_terminal`

The live selected resolver translates existing typed source errors into those
reasons. Unknown, malformed, inaccessible, or internally inconsistent state
fails visibly; it never becomes `allow`.

## Bootstrap Boundary

The source consumer uses `portfolio_allocate` as the already-evaluated
bootstrap boundary. Its request must name a positive Plan number and at least
one exact write path. Every path must be one of:

- `docs/plans/<plan>_*.md`
- `docs/plans/<plan>_*_work_graph.json`
- `examples/owner-real-outcome-admission/plan<plan>-*.json`
- `docs/plans/CLAUDE.md`
- `ROADMAP.md`

No caller-provided glob or alternate prefix is accepted. In particular,
`enforced_planning/**`, `scripts/**`, `tests/**`, and evidence files are not
bootstrap artifacts. The bootstrap decision grants no ordinary Git authority;
the existing exact scoped claim remains mandatory.

After exact allocation and selection, the same claim may expand its write paths
without invalidating the selected claim identity because that identity already
binds project, scope, session, repository, worktree, branch, tracker, source
file, and plan authority. The admission resolver reopens every bound object
before renewal or write.

## First-Consumer Integration

| Boundary | Integration | Hard behavior when explicitly enabled | Default behavior |
|---|---|---|---|
| sanctioned plan/claim/worktree/session bootstrap | `make worktree` calls the production CLI before mutation | deny empty or non-bootstrap write scope | unchanged/off |
| session start or renewal | `session_start` optional selected admission | deny missing/inactive/mismatched/stalled/terminal state before mutation | unchanged/off |
| heartbeat | `session_heartbeat` optional selected admission | deny non-admitted renewal before timestamp mutation | unchanged/off |
| native pre-write | ordinary decision followed by selected admission | ordinary deny stays deny; outcome deny changes opted-in allow to nonzero | observation/default unchanged |
| safe inspection, replay, preservation, closeout | dedicated production decision only | allow after ordinary authority | existing commands unchanged |

One public read-only CLI exposes bootstrap and selected decisions with strict
JSON. Admission receipts are append-only and bind boundary, ordinary result,
claim/selection/allocation/effective-scenario digests, decision, and reason.
Receipt failure causes the opted-in hard operation to fail; it is not silently
discarded.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| production admission decision | typed ordinary/scope/portfolio/continuation request | typed allow/deny/defer and stable reason | `outcome_admission` | live resolvers and Plan #121 regression |
| narrow bootstrap | plan number plus exact requested write paths | allow or scope-violation decision | source-owned bootstrap classifier | sanctioned worktree bundle |
| exact selected-state resolution | exact live claim identity plus boundary/target | derived portfolio and effective continuation request | existing selection/allocation/continuation owners through `outcome_admission` | session and pre-write entrypoints |
| append-only admission evidence | exact derived request and decision | digest-bound receipt | outcome admission owner | operator evidence and tests |
| explicit first-consumer adapters | opt-in CLI flags | mutation continues or exits nonzero before mutation/success | lifecycle and pre-write scripts | Enforced Planning source consumer |

## Failure Behavior

- Ordinary authority is evaluated first and cannot be revived.
- Missing selection is `deny/outcome_selection_required`.
- A classed binding with missing, disposed, foreign, or changed allocation is a
  typed portfolio denial.
- A target mismatch is `deny/out_of_scope`.
- Recovery-required, stalled, complete, and parked effective leases deny with
  their stable continuation reason, except one contract-declared bounded
  recovery action.
- Bootstrap with no write paths or any non-artifact path is
  `deny/admission_bootstrap_scope_violation`.
- Receipt append failure fails the opted-in operation before its mutation.
- Default calls without the new explicit opt-in preserve current behavior.

## Landscape And Prior Art

| Alternative | Consequence | Disposition |
|---|---|---|
| Import the evaluation case model into lifecycle code | Lets fixture-oriented, caller-classified state masquerade as live evidence. | Rejected. |
| Reimplement admission independently in every script | Creates drift and inconsistent precedence. | Rejected. |
| Require allocation before any claim/worktree | Deadlocks the existing allocation owner. | Rejected. |
| Auto-allocate the first bootstrap lane | Lets task ordering select Brian's portfolio. | Rejected. |
| Treat outcome denial as another observe notice | Preserves the circular continuation failure. | Rejected for explicit hard mode. |
| One production decision plus exact live resolver and narrow bootstrap | Reuses current owners, fails visibly, and is reversible before activation. | Adopted. |

**Alternatives:** The table covers fixture-state reuse, duplicated script
logic, bootstrap deadlock, accidental allocation, observe-only non-enforcement,
and the adopted single-owner composition.

**Project implications:** Enforced Planning is the only consumer in this plan.
Existing claim, tracker, portfolio, selection, and continuation owners remain
canonical. The installer, generated downstream surfaces, and consumer
configuration remain unchanged until a later activation decision.

## Files Affected

- `enforced_planning/outcome_admission.py`
- `enforced_planning/outcome_admission_evaluation.py`
- `enforced_planning/outcome_selection.py`
- `enforced_planning/session_lifecycle.py`
- `scripts/outcome_admission.py`
- `scripts/session_start.py`
- `scripts/session_heartbeat.py`
- `scripts/prewrite_claim_gate.py`
- `Makefile`
- `tests/test_outcome_admission.py`
- focused existing outcome/session/pre-write tests when required
- `examples/owner-real-outcome-admission/plan122-*.json`
- `docs/evidence/plan122_first_consumer_outcome_admission.json`
- `docs/plans/122_first_consumer_outcome_admission.md`
- `docs/plans/122_first_consumer_outcome_admission_work_graph.json`
- `docs/plans/CLAUDE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `ROADMAP.md`
- `CLAUDE.md`

## Work Unit OAG-01 — Implement and exercise first-consumer admission

Create the production decision and live resolver, make the Plan #121 evaluator
consume that decision, add explicit first-consumer adapters, and run the stable
Plan #122 example through real bootstrap, allocation, selection, heartbeat, and
pre-write commands. Retain both allow and deny evidence without enabling any
installed hook or downstream consumer.

Pass when:

- all 30 frozen Plan #121 decisions still match through the production owner;
- bootstrap allows only the fixed Plan #122/index/example paths and rejects one
  source path through the public command;
- selected state is derived from exact current claim/tracker/scenario/ledger
  evidence rather than caller-supplied status labels;
- an active exact selection passes opted-in heartbeat and pre-write;
- missing selection and circular continuation fail through the same public
  entrypoints before mutation or success;
- ordinary authority denial remains denial;
- unactivated/default behavior remains byte- and exit-compatible in focused
  regressions; and
- evidence explicitly excludes hook activation, installer/fleet adoption,
  cross-repository membership, and product selection.

## Acceptance Criteria

| ID | Criterion | Result | Evidence |
|---|---|---|---|
| OAG01-A1 | One production decision owns admission ordering and reproduces every frozen Plan #121 case | accepted | production-owner delegation, 30 frozen decisions, ordinary-denial control |
| OAG01-A2 | Bootstrap permits only the fixed nonempty Plan/index/roadmap/input scope | accepted | allow receipt plus source-smuggling and focused malformed-scope denials |
| OAG01-A3 | Selected admission derives exact current canonical state | accepted | claim, tracker, binding, Project Graph, allocation, scenario, and lease digests |
| OAG01-A4 | Explicit lifecycle and pre-write adapters deny before mutation or success while defaults remain compatible | accepted | missing/disposed no-mutation heartbeats, ordinary-allow/outcome-deny pre-write, default regressions |
| OAG01-A5 | One real Plan #122 lane retains both-sign public-command evidence and truthful non-claims | accepted | active allow, parked deny, circular-state deny, focused verification, exact candidate |

## Accepted Evidence

- Exact implementation candidate:
  `8eae9b3e3e12634571134e26ab7422bcab7457af`; all production source digests
  are retained in
  `docs/evidence/plan122_first_consumer_outcome_admission.json`.
- The fixed seven-path bootstrap returned
  `allow/admission_bootstrap_allowed` in receipt
  `oadm-bd4076263f354ffaa1118bc4c054e0ff`; adding
  `enforced_planning/outcome_admission.py` returned
  `deny/admission_bootstrap_scope_violation` in
  `oadm-9a8164f1ffc248d290a02c3d6c25b5d3`.
- Missing selection returned `deny/outcome_selection_required` through the
  public selected command and heartbeat. The heartbeat timestamp did not
  change.
- The exact Project Meta revision
  `58ba96b01da2bad35cd3feae034d86c705bf2b9a` admitted maintenance allocation
  `8a63b760df3d31eaee288567c1220fe556f2d62f28f0e4564fe391a4df6bf081`.
  The retained selection binding
  `4773865d1486a5a03306cae9bb758d8d020c49746195b630e33d530ed6e7d460`
  then allowed the public selected check, opted-in heartbeat, and an
  ordinary-authorized hard pre-write.
- Parking that allocation caused the same selected check and heartbeat to
  return `deny/portfolio_allocation_inactive`; heartbeat bytes remained
  unchanged. The hard pre-write also returned nonzero even though ordinary
  authority still returned `allow/exact_live_claim`.
- The equivalent circular-state public-command control returned
  `deny/outcome_stalled` from selected admission and hard pre-write and left
  target bytes unchanged.
- Focused verification passed 191 tests, including every frozen Plan #121
  decision, live-state adapters, default compatibility, lifecycle, ordinary
  projection, and public CLIs. Changed source passed focused Ruff and mypy;
  Makefile dry-runs and `git diff --check` passed.
- The first authentic pre-write composition exposed a plural-field adapter
  mismatch. The fixed adapter now requires exactly one string in
  `normalized_target_paths`; the reusable finding is retained at
  `project-meta:learnings/entries/lrn-20260821T095107688885Z-8bba26ab79.json`.
- Retained acceptance artifact:
  `docs/evidence/plan122_first_consumer_outcome_admission.json`.

## Promotion Boundary

This accepted result licenses a separately reviewed source-repository
activation pilot.
It does not activate a hook, change `meta-process.yaml` defaults, modify the
installer, propagate generated mirrors, claim fleet adoption, resolve
cross-repository allocation membership, certify progress semantics, or choose
Brian's active product outcome.

## Trace Evaluation

`trace_evaluable: false # deterministic local contracts and lifecycle state`

## Terminal Closeout

The design preceded production implementation, and the exact bootstrap and
selected-outcome inputs preceded the authentic run. Merge only this opt-in
consumer and its both-sign evidence, close the claimed lane, and treat source
activation as a new bounded promotion with its own rollback and evidence.
