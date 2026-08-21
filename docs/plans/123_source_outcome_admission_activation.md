# Plan #123: Source Outcome-Admission Activation

**Status:** In Progress — bounded source-only activation design adopted
**Type:** implementation (reversible source activation; downstream propagation excluded)
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "source-outcome-admission-activation"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** pilot
**Overlays:** deductive, activation, first-consumer adoption
**Blocked By:** #122
**Blocks:** any installer, generated-mirror fleet, or downstream activation claim

---

## Decision

Activate Plan #122's accepted gate in the Enforced Planning source repository
through one explicit source configuration, while leaving every downstream
repository and installer target unchanged.

The source configuration makes selected-outcome admission automatic at three
boundaries:

1. the sanctioned bootstrap entrypoint may create only a restricted design and
   allocation-input lane before selection exists;
2. later session start/renewal and heartbeat derive and enforce the exact
   selected outcome without a caller opt-in flag; and
3. the already-installed native pre-write adapter derives and enforces the
   exact selected outcome after ordinary claim admission without a caller
   outcome flag.

Configuration absence remains `off`. The source repository sets the mode to
`enforce_selected`; no installer run, generated downstream update, host-wide
hook mutation, or fleet claim is part of this plan.

## Plan

**Critical-path classification: vertical.** The visible result is not a new
configuration model by itself. Acceptance requires a real source-repository
journey in which the public Make bootstrap creates the restricted lane, the
lane becomes exact Plan #123 authority, the maintenance outcome is allocated
and selected, and then lifecycle and native pre-write enforce it without the
Plan #122 flags.

Work in this order:

1. create and commit the Plan #123 design, work graph, scenario, and allocation
   input under the accepted Plan #122 bootstrap;
2. refresh the same restricted claim to exact Plan #123/work-unit authority;
3. allocate and select the exact Project Graph-bound maintenance outcome;
4. expand the claim only after selected admission succeeds;
5. implement source configuration, automatic adapters, canonical-consumer
   adoption, and focused controls;
6. exercise the real configured allow and equivalent configured deny paths,
   retain rollback evidence, then park the allocation and merge.

## Capability Adoption

**Disposition: extend and adopt.** Extend the production
`outcome_admission` owner with strict source configuration and bootstrap-plan
resolution. Extend the existing session lifecycle and native pre-write
adapters to consume that configuration. Do not create another claim, tracker,
portfolio, selection, continuation, or hook registry.

The authentic bootstrap exposed an adoption defect before design authoring:
`make worktree` executes `scripts/meta/session_start.py`, while Plan #122
changed `scripts/session_start.py`. The stale generated consumer rejected
`--outcome-bootstrap-plan` even though canonical-source tests and Makefile
dry-runs passed. Plan #123 therefore also:

- makes source-repository Make lifecycle calls resolve the canonical source
  scripts when they exist, with installed mirrors as the consumer fallback;
- synchronizes the source repository's declared generated lifecycle mirrors
  through their installer lineage; and
- runs an authentic Make bootstrap without a private script override.

The reusable finding is retained at
`project-meta:learnings/entries/lrn-20260821T101600047477Z-097761bc73.json`.

## Gap

Plan #122 proved hard decisions only when callers supplied
`--outcome-selected`, `--outcome-enforce-selected`, or the corresponding Make
variables. The behavior is correct, but a coding agent can continue circular
work simply by using the old command shape. That is the exact failure mode this
initiative is meant to stop: approval keeps flowing while enforcement remains
optional.

Activation also needs a non-circular start. A new outcome cannot be selected
until a claim, tracker, scenario, and allocation input exist, but an active hard
gate must not allow arbitrary source work while those are missing. The source
bootstrap therefore creates one restricted claim whose entire write scope
classifies as a single Plan-numbered bootstrap. Configured pre-write may allow
only those exact claimed bootstrap targets. Heartbeat and source expansion
still require selection.

## References Reviewed

- `docs/plans/122_first_consumer_outcome_admission.md` and
  `docs/evidence/plan122_first_consumer_outcome_admission.json` at
  `94e3443e9f779de141b2a0b75c838bf8d87d574d` — accepted decision ordering,
  authentic both-sign evidence, and promotion boundary.
- `enforced_planning/outcome_admission.py` — production decision, bootstrap,
  selected-state resolution, and receipt owner.
- `enforced_planning/session_lifecycle.py`, `scripts/session_start.py`, and
  `scripts/session_heartbeat.py` — lifecycle mutation boundaries.
- `scripts/prewrite_claim_gate.py` — native ordinary enforcement and opt-in
  Plan #122 selected enforcement.
- `Makefile`, `scripts/meta/session_start.py`, and
  `scripts/install_governed_repo.py` — real source consumer, stale generated
  mirror, and declared mirror lineage.
- `meta-process.yaml`, `enforced_planning/hook_wiring.py`, and
  `docs/reference/CONFIG_REFERENCE.md` — current source pre-write enforcement
  mode, native hook wiring, and public configuration authority.
- `docs/plans/108_prewrite_claim_enforcement.md` — accepted ordinary source
  enforcement pilot, native matcher behavior, and source-only rollback pattern.
- `project-meta:learnings/entries/lrn-20260821T101600047477Z-097761bc73.json`
  at `376b775faa8c407e8fe4a5cfb73b78e023f1236c` — actual-consumer adoption
  finding from the failed Plan #123 bootstrap.

## Research

No web research is needed. The uncertainty is executable and local: whether
the source configuration reaches the actual Make, lifecycle, and native hook
entrypoints, permits the narrow bootstrap, and denies missing/circular state
without explicit outcome flags. Authentic commands and exact receipts answer
that question.

## User Outcome

Brian no longer has to remember to ask a coding agent to use the progress gate
inside Enforced Planning. Once the source pilot is active, ordinary approval,
elapsed time, and willingness to spend cannot renew or write a selected outcome
whose exact allocation or continuation lease no longer permits work.

The system still has a usable start: one sanctioned command creates only the
new Plan, graph, and allocation inputs; the agent must then bind the lane to the
plan and select an active allocation before source work or heartbeat renewal.

## Canonical Behavioral Example

**Starting state:** `meta-process.yaml` sets source outcome admission to
`enforce_selected`. A native pre-write payload targets an exact claimed source
file. The operator text says "I approve, continue" and cost telemetry is
arbitrarily high, but the caller supplies no outcome flag.

**Action:** Invoke the installed source pre-write hook command exactly as the
client does.

**Expected result:** If the exact selected allocation and effective lease are
active and the target is in scope, the command returns zero and appends both
ordinary and outcome-admission receipts. Missing, disposed, mismatched,
recovery-required, stalled, or terminal state returns nonzero before success.
During initial bootstrap, only a target inside the claim's uniquely resolved
Plan-numbered bootstrap scope may succeed.

**Failure signal:** Omitting an outcome flag bypasses admission; a stale
generated lifecycle consumer rejects the sanctioned bootstrap; arbitrary
source paths pass before selection; ordinary denial is revived; denial mutates
heartbeat or target bytes; changing cost or approval changes the decision; or
downstream repositories change.

## Source Configuration Contract

`meta_process.claims.outcome_admission_mode` is a strict enum:

- absent or `off`: preserve Plan #122's explicit-only behavior;
- `enforce_selected`: automatically require exact selected admission for
  source session start/renewal, heartbeat, and ordinary-authorized native
  pre-write, with the restricted bootstrap exception.

Malformed values fail visibly. Explicit Plan #122 CLI flags remain available
for diagnostics and tests, but cannot turn off an active configured mode at a
native source boundary. The existing append-only default admission stream
remains the evidence owner; no portable personal path is added to config.

## Bootstrap And Upgrade Contract

Add one sanctioned `make outcome-bootstrap` entrypoint. It requires a positive
`PLAN`, branch, task, broader goal, phase, and nonempty write paths. It delegates
to the existing worktree bundle using the light, explicitly unplanned profile
and Plan #122's exact bootstrap admission. It does not allocate or select an
outcome and does not grant source scope.

A claim qualifies for configured bootstrap pre-write only when all its write
paths resolve to one positive Plan number and every path passes the production
bootstrap classifier for that number. Plan/index/roadmap-only ambiguity,
multiple Plan numbers, empty scope, or one foreign path denies. The target must
also be one of those exact claimed paths.

After the plan and graph exist, refresh the same restricted claim with exact
`enforced-planning#<plan>` and work-unit authority while explicitly retaining
bootstrap admission. Allocate and select next. Only then may a configured
selected session refresh expand the claim to source paths.

## Automatic Enforcement Ordering

1. Ordinary claim authority remains first for pre-write and can never be
   revived.
2. An exact configured bootstrap may allow only its claimed bootstrap target.
3. Every other configured new/renewed lifecycle mutation requires the exact
   active allocation and selected continuation state.
4. Configured native pre-write requires the same exact selected state and
   target scope after ordinary allow.
5. Receipt append failure fails the configured operation.

No public parameter accepts caller-supplied portfolio or continuation labels.

## Activation And Rollback

Activation is the tracked Enforced Planning `meta-process.yaml` change plus the
canonical source consumer and existing installed source hook wiring. It does
not modify user-level hooks or another repository.

Rollback is one recoverable Git change: set the source mode to `off` or revert
the Plan #123 activation commit through the ordinary claimed PR path while the
pilot allocation is active. If a false block prevents native edits, the exact
Plan #123 merge commit is the recovery ref for a Git revert; native pre-write is
a client guardrail, not OS-level isolation. Parking the allocation is evidence
and slot cleanup, not rollback of the configured policy.

## Landscape And Prior Art

| Alternative | Consequence | Disposition |
|---|---|---|
| Keep explicit flags and improve prose | Leaves the circular omission bypass intact. | Rejected. |
| Hard-code selected flags in every Make command | Duplicates policy and leaks source defaults into future consumers. | Rejected. |
| Activate host/fleet hooks now | Exceeds Plan #122 evidence and mixes source utility with rollout. | Rejected. |
| Require selection before any worktree | Recreates the bootstrap deadlock. | Rejected. |
| Trust canonical tests while retaining stale generated consumers | Repeats the authentic Plan #123 failure. | Rejected. |
| Source config + one production loader + restricted bootstrap + actual-consumer proof | Makes the first consumer unavoidable and preserves a reversible downstream boundary. | Adopted. |

**Alternatives:** The table covers optional prose, duplicated flags, premature
fleet rollout, bootstrap deadlock, false adoption evidence, and the adopted
source-only composition.

**Project implications:** Only Enforced Planning sets the new key in this plan.
The parser and generated surfaces may understand an absent key, but the
installer is not run against any consumer and no downstream config is changed.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| strict source activation config | `meta-process.yaml` or absence | `off` or `enforce_selected` | production admission owner | lifecycle and pre-write adapters |
| unique bootstrap-plan resolver | exact claim write paths | one Plan number or visible denial | production admission owner | configured native pre-write |
| sanctioned outcome bootstrap | exact Plan-numbered artifact scope | restricted claim/worktree/session | Make entrypoint + existing owners | new source outcome lanes |
| automatic selected lifecycle | exact live configured repository | mutation or typed denial before mutation | session lifecycle | source Make/CLI callers |
| automatic selected pre-write | ordinary native decision + config | success or typed outcome denial | native pre-write adapter | installed source hook |
| adoption evidence | actual Make/hook execution | receipts, digests, mutation checks | Plan #123 pilot | promotion decision |

## Failure Behavior

- Missing or invalid configuration fails visibly; absence alone remains off.
- Configured `enforce_selected` with ordinary pre-write not in `enforce` mode
  fails rather than degrading to observe.
- Bootstrap with ambiguous Plan identity or any non-bootstrap claim path denies.
- Missing selection denies lifecycle renewal and non-bootstrap write.
- Inactive/mismatched allocation and stalled/terminal continuation deny.
- Ordinary denial remains denial without requiring selected state.
- Outcome receipt failure denies before protected success.
- A generated mirror mismatch fails the authentic Make integration test.
- Rollback failure retains the activation branch and exact recovery ref; it is
  never reported as successful rollback.

## Files Affected

- `enforced_planning/outcome_admission.py`
- `enforced_planning/session_lifecycle.py`
- `scripts/outcome_admission.py`
- `scripts/prewrite_claim_gate.py`
- `scripts/session_start.py`
- `scripts/session_heartbeat.py`
- `scripts/meta/session_start.py` (regenerated from canonical source)
- `scripts/meta/session_heartbeat.py` (regenerated from canonical source)
- `scripts/install_governed_repo.py` only if required to preserve declared mirror lineage
- `Makefile`
- `meta-process.yaml`
- `GETTING_STARTED.md`
- `docs/reference/CONFIG_REFERENCE.md`
- `tests/test_outcome_admission.py`
- `tests/test_session_cli.py`
- `tests/test_install_governed_repo.py`
- `examples/owner-real-outcome-admission/plan123-*.json`
- `docs/evidence/plan123_source_outcome_admission_activation.json`
- `docs/plans/123_source_outcome_admission_activation.md`
- `docs/plans/123_source_outcome_admission_activation_work_graph.json`
- `docs/plans/CLAUDE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `CLAUDE.md`
- `ROADMAP.md`

## Work Unit SOAA-01 — Activate and exercise the source consumer

Adopt the canonical lifecycle source at the real Make boundary, add the strict
source mode and bootstrap resolver, make lifecycle and native pre-write consume
it automatically, and execute the stable Plan #123 journey without outcome
flags. Retain an exact rollback and all negative controls.

Pass when:

- the real `make outcome-bootstrap` succeeds without a private script override
  and creates only the declared restricted lane;
- the restricted lane upgrades to exact Plan #123 authority, allocates, selects,
  and then expands only after admission;
- configured session start/heartbeat and native pre-write enforce selected
  state without Plan #122 flags;
- active exact state allows, while missing/circular/inactive state denies before
  mutation or success and ordinary denial retains precedence;
- config absence/off preserves current behavior in focused regressions;
- the source generated lifecycle mirrors match their canonical sources through
  the declared lineage;
- rollback is executable and digest-bound; and
- no installer target, downstream repository, user-level hook, deployment,
  release, product selection, or fleet claim changes.

## Acceptance Criteria

1. One strict production loader owns the source mode, defaults absence to off,
   rejects malformed values, and is consumed by both lifecycle and pre-write.
2. One unique-plan bootstrap resolver rejects empty, ambiguous, mixed,
   traversal, source, test, evidence, and foreign-Plan claim scopes.
3. The actual source Make entrypoint uses the canonical lifecycle implementation
   and its generated mirrors are synchronized through the declared lineage.
4. Configured lifecycle start/renewal and heartbeat require selected admission
   without an outcome flag and deny before mutation on failure.
5. Configured native pre-write preserves ordinary precedence, allows exact
   bootstrap or active selected work, and returns nonzero for circular/missing/
   inactive state without an outcome flag.
6. Authentic source activation retains exact config, claim, selection,
   allocation, lease, ordinary, outcome, target-byte, and rollback evidence.
7. Evidence explicitly excludes installer execution against consumers,
   downstream/fleet adoption, host-wide activation, semantic progress
   certification, cross-repository membership, and product selection.

## Promotion Boundary

Completion proves one persistent Enforced Planning source activation and a
sanctioned start/rollback path. It may license a separate normal-project pilot.
It does not license installer defaults, generated downstream propagation,
fleet enforcement, cross-repository allocation membership, semantic validation
of progress, or selection of Brian's active product project.

## Trace Evaluation

`trace_evaluable: false # deterministic local configuration, lifecycle, and hook state`

## Terminal Closeout

Commit and push this design before source implementation. Keep the bootstrap
claim restricted until the exact Plan #123 graph exists, then allocate/select
before expansion. Freeze the activation candidate before the authentic
configured run. Park the maintenance allocation after retained both-sign and
rollback evidence, merge through a PR, and use sanctioned session closeout.
