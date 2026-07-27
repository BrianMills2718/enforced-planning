# Plan #74: Plan-DAG-Governed Worktree Lifecycle

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9"
**goal_ref:** "plan-dag-governed-worktree-lifecycle"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** [future] fleet-wide plan-owned lane enforcement

---

## Gap

**Current:** The ecosystem-wide plan graph compiles explicit `blocked_by` and
`blocks` edges and reports ready plans. Governed-repository worktree creation
records a free-text plan reference, while plan completion and atomic session
closeout are separate operations. Neither worktree creation nor plan completion
consults both authorities. Clean, unclaimed, sometimes unmerged worktrees
therefore accumulate after agents move on.

**Target:** The canonical plan DAG decides whether a qualified plan may begin
implementation. Every plan-owned lane records the same qualified identity. A
plan cannot become complete until all owned lanes have a recoverable terminal
disposition. Independent ready plans remain concurrently executable.

**Why:** A week-long agent session is not a reliable lifecycle boundary. The
plan and its explicitly owned child lanes are durable boundaries.

---

## User Outcome

An operator can start any dependency-ready plan concurrently, while blocked
plans fail before worktree creation and completed plans leave no unresolved
worktrees, branches, claims, or session trackers.

## Canonical Behavioral Example

**Starting input/state:** `project-a#12` is blocked by incomplete
`project-a#11`; `project-a#13` has no blockers. Plan 13 owns one merged lane and
one dirty child lane.

**Action:** The operator attempts to create worktrees for Plans 12 and 13, then
runs plan close for Plan 13.

**Expected observable result:** Plan 12 is rejected with blocker evidence. Plan
13 starts. Plan close refuses completion while the dirty child lane is
unresolved, then succeeds after that lane receives a verified recovery
disposition and removes all plan-owned lifecycle state.

**Behavioral evidence:** Unobserved

**Substrate/process evidence:** Plan graph query, lifecycle inventory, contract
tests, installed-repository pilot, and negative fixtures.

**Failure signal:** A blocked plan creates a worktree, or a plan becomes complete
while an owned lane lacks a terminal disposition.

---

## References Reviewed

- `ecosystem-ops/plan_graph.py` — canonical graph compiler and ready-task query.
- `ecosystem-ops/docs/plans/72_qualified-plan-identity-and-dependency-edge-integrity.md`
  — qualified plan identity and report-only calibration.
- `enforced-planning/docs/plans/37_plan-bound-session-identity-and-resume-lifecycle.md`
  — existing plan/session identity.
- `enforced-planning/docs/plans/42_atomic-closeout-and-claimed-worktree-removal.md`
  — atomic lane closeout.
- `enforced-planning/docs/plans/59_worktree-lifecycle-disposition-enforcement.md`
  — merge-or-disposition safety.
- `project-meta/docs/plans/212_worktree-lifecycle-disposition-and-safe-closeout.md`
  — observed cleanup consequences and safe disposition rules.

## Research Basis For This Slice

No additional research beyond References Reviewed. The failure is an
integration gap between existing canonical capabilities.

## Landscape And Prior Art

**Alternatives:** Requiring sequential plan completion was rejected because it
blocks independent DAG nodes. Session-exit cleanup was rejected because sessions
may legitimately last for days. A second local plan graph was rejected because
`ecosystem-ops` already owns canonical compilation. Extend the existing graph
and shared lifecycle package.

**Project implications:** `ecosystem-ops` owns readiness computation;
`enforced-planning` owns the portable start/close contract and installer;
Project Meta owns the first governed policy pilot.

**Refresh trigger:** A replacement plan-graph authority, claim registry, or
plan-lifecycle model is adopted.

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| Ready-plan decision | Deductive | Explicit dependencies and statuses determine the answer. | Typed query plus positive and blocked fixtures. |
| Plan-owned lifecycle inventory | Deductive | Claims, sessions, worktrees, branches, and dispositions are observable. | Fail-loud inventory and terminal-state rules. |
| Fleet rollout strictness | Hybrid | Compatibility failures across installed repos are not fully known. | One pilot, audit readout, then bounded rollout. |

---

## Bounded Design

### Invariants

1. The ecosystem DAG remains the sole plan-readiness authority.
2. Plan identity is qualified by project plus plan identifier; bare plan numbers
   are never global identities.
3. A plan with incomplete hard blockers cannot open an implementation lane.
4. One worktree per plan is the default. Extra lanes require a `parent_plan_id`
   and distinct `lane_id`.
5. A plan may be marked complete only when every owned lane is `merged`,
   `recovery_preserved`, `transferred`, or `abandoned_recoverably`.
6. Session age and process exit never imply abandonment.
7. Missing DAG, identity, or lifecycle evidence fails closed in coordinated and
   release profiles. Lightweight explicitly unplanned work remains governed by
   its existing profile.

### Contracts

`PlanReadinessDecisionV1`:

- qualified plan ID and exact graph revision;
- `ready | already_active | blocked | unknown`;
- blocker IDs and evidence references;
- deterministic error variants for missing, ambiguous, cyclic, or stale input.

`PlanLaneIdentityV1`:

- qualified plan ID, lane ID, optional parent lane;
- repository, branch, worktree path, claim/session identities;
- creation revision and execution profile.

`PlanCloseResultV1`:

- qualified plan ID and submitted revision;
- every discovered lane and terminal disposition;
- merge/recovery evidence;
- actions performed and failures;
- final plan-status transition.

Unknown fields fail in internal enforcement contracts. Repeated close is
idempotent. Partial closeout records completed actions and fails before the plan
status changes.

### Compatibility

Existing free-text plan references remain readable during migration but cannot
license strict completion. Installed repositories receive wrapper changes only
after the source contract and pilot pass. No deployment or release behavior is
included.

---

## Work-Unit Graph

| Unit | Class | Availability | Depends on | Output |
|---|---|---|---|---|
| WU-74-01 | implementation | complete | none | Qualified `check-ready --json` query in `ecosystem-ops` |
| WU-74-02 | implementation | ready for execution | WU-74-01 (hard, satisfied) | Shared identity/readiness adapter and start gate in `enforced-planning` |
| WU-74-03 | implementation | blocked dependency | WU-74-02 (hard) | Plan-owned inventory and atomic `plan-close`/completion gate |
| WU-74-04 | integration | blocked dependency | WU-74-03 (hard) | Project Meta pilot, installer propagation, compatibility report |

### WU-74-01 — Canonical qualified readiness query

**Scope:** Add a machine-readable exact-plan query to `ecosystem-ops`; do not
change graph compilation or infer undeclared edges.

**Evidence first:** Tests for a ready same-project plan, blocked same-project
plan, cross-project blocker, ambiguous bare identity, cycle, missing plan, and
non-actionable status.

**Acceptance:** The command returns a revision-bound
`PlanReadinessDecisionV1`; negative cases fail nonzero without creating state.

**Observed evidence (2026-07-27):**

- `ecosystem-ops` commit `33fde90` added the strict contract and command; PR
  `BrianMills2718/ecosystem-ops#8` merged it to `main` at `68bb9c95`.
- `pytest -q tests/test_plan_graph.py` passed 70 tests, including all specified
  positive and negative readiness fixtures.
- `make check` passed 832 Python tests, 186 Vitest tests, typed-boundary checks,
  configured mypy scope, documentation checks, and UI policy checks.
- Real graph probes returned exit 0/`ready` for `enforced-planning#54` and exit
  2/`blocked` for `ecosystem-ops#75` at graph revision
  `b289f78b4a700301eae597e43b8587feda7dc1351a25931dc716c291b19f9c5a`.
- The child lane was closed with verified `merged` disposition; its worktree,
  local/remote feature branch, claim, and session tracker were removed.

### WU-74-02 — Portable start gate and lane identity

**Scope:** Add shared contracts and a configurable readiness adapter to
`enforced-planning`; installed `make worktree PLAN=...` uses the adapter.

**Evidence first:** Contract fixtures plus tests proving blocked plans do not
create a claim, branch, worktree, or tracker; ready plans create one fully
qualified lane.

**Acceptance:** The existing unplanned/light profile remains compatible, while
coordinated and release work fails closed on missing or negative readiness.

### WU-74-03 — Plan completion and atomic close

**Scope:** Inventory lanes by qualified plan identity, add `plan-close`, and
make `complete_plan.py` require a successful close result.

**Evidence first:** A fixture with merged, dirty, transferred, recovery-backed,
and partially missing lanes. Negative tests prove no status transition on any
unresolved lane.

**Acceptance:** Repeated close is idempotent; partial failures preserve recovery
state; successful completion leaves no unresolved owned lifecycle records.

### WU-74-04 — Pilot and rollout

**Scope:** Install the exact source revision into Project Meta, exercise one
ready and one blocked plan, then audit wrapper parity before broader rollout.

**Evidence first:** Installer idempotency, generated-surface sync, real
ready/blocked command receipts, and a no-residue plan-close receipt.

**Acceptance:** The pilot demonstrates the canonical behavioral example without
hard-coded workspace paths or a second graph store.

---

## Plan

### Critical Path Classification

| Increment | Class | Behavior or named blocker changed |
|---|---|---|
| WU-74-01 qualified ready-check query | `vertical` | An operator or wrapper can receive a deterministic ready/blocked result for one exact plan. |
| WU-74-02 start gate and lane identity | `vertical` | A blocked plan can no longer create implementation lifecycle state. |
| WU-74-03 atomic plan close | `vertical` | An unresolved owned lane prevents plan completion; a resolved plan closes without residue. |
| WU-74-04 pilot and rollout | `hardening` | Proves installation compatibility after the behavior exists; it does not create the behavior. |

### Steps

1. [x] Execute WU-74-01 with failing readiness fixtures first.
2. Execute WU-74-02 only after the qualified query contract is accepted.
3. Execute WU-74-03 only after created lanes carry qualified identity.
4. Pilot and propagate the exact verified source revision through WU-74-04.

---

## Files Affected

- `ecosystem-ops/plan_graph.py` and focused tests
- `enforced-planning/enforced_planning/` readiness and lifecycle contracts
- `enforced-planning/scripts/` start, completion, and close entrypoints
- `enforced-planning/scripts/install_governed_repo.py` and templates
- Project Meta installed wrappers and focused pilot tests

## Required Tests

- Contract and negative-fixture tests for all three versioned results.
- Plan-graph qualified identity and readiness tests.
- No-side-effect blocked-start integration test.
- Unresolved-lane completion rejection test.
- Idempotent successful plan-close integration test.
- Installer idempotency and Project Meta pilot checks.

## Acceptance Criteria

- [ ] Blocked plans cannot create implementation worktrees.
- [ ] Independent ready plans remain concurrently startable.
- [ ] Every created lane carries qualified plan identity.
- [ ] Plan completion rejects unresolved owned lanes.
- [ ] Successful plan close leaves recoverable terminal evidence and no lane residue.
- [ ] No second plan graph or hard-coded repository path is introduced.

## Non-Goals

- Automatically deleting dirty or unmerged historical worktrees.
- Closing plans because a session process exits or ages.
- Serializing independent ready plans.
- Deployment, release, or package publication.
- Inferring dependencies not explicitly accepted by the canonical graph.
