# Plan #104: Plan-Lane Resumption Contract and Source Propagation

**Status:** Complete
**Type:** cross-repository lifecycle repair
**Priority:** Critical
**Landscape disposition:** inline
**phase_ref:** "plan-dag lifecycle recovery"
**goal_ref:** "recoverable-worktree-residue-cleanup"
**Blocked By:** None
**Blocks:** Project Meta Plan #234 WU-234-02 resumption and all plan-owned lane recovery after a session close

`trace_evaluable: false # deterministic coordination lifecycle`

## Objective

Allow an explicitly requested, plan-bound **resume** lane only when an
in-progress plan has no live lane, while preserving the existing fail-closed
start behavior for new, blocked, unknown, malformed, or already-owned plans.

## User Outcome

When a long-running session closes a completed or blocked worktree, an agent can
resume the same in-progress plan in a fresh claimed worktree without inventing a
new plan or bypassing claim ownership. A concurrent agent cannot create a
second root lane for that plan.

## Gap

**Current:** A plan whose static status is `in_progress` receives the truthful
graph decision `already_active`, but the installed start gate treats that state
as an unconditional rejection. After the only plan lane is closed, the next
safe lane cannot be created. The portable source lacks the installed Plan #74
readiness adapter entirely.

**Target:** A source-owned, explicitly opt-in resume operation can create one
fresh plan-bound lane only when the graph still identifies the plan as
actionable and the canonical registry has no matching live lane. The source
installer renders the same tested gate into Project Meta and other governed
consumers.

## Current Evidence

- `ecosystem-ops/plan_graph.py` returns `already_active` for plans whose static
  status is `in_progress` or `active`; it does not assert live lane ownership.
- Project Meta's installed `enforced_planning/plan_readiness.py` rejects every
  decision other than `ready`, before any claim, branch, worktree, or tracker
  mutation.
- Project Meta Plan #234 is `in_progress` on `origin/main` and has no live
  claim for Plan #234. It cannot therefore open its next sanctioned lane.
- The claim registry serializes claim check-and-write with `fcntl.flock`, and
  its hierarchy validation rejects multiple unparented `program` roots for the
  same project and normalized numbered plan.
- The readiness adapter and its CLI are presently committed in Project Meta
  (Plan #74 pilot) but absent from the Enforced Planning source repository.
  This is a source/installed-surface propagation defect, not permission to
  modify only the installed consumer.

## Research

- `ecosystem-ops/plan_graph.py` — canonical static readiness query and its
  `already_active` result for `in_progress`/`active` plan rows.
- Project Meta `enforced_planning/plan_readiness.py` and
  `scripts/meta/check_plan_readiness.py` — installed start gate and strict
  `ready`-only rejection.
- Project Meta `Makefile` — gate invocation before claim, branch, worktree,
  and tracker creation.
- Enforced Planning `enforced_planning/coordination_claims.py` — registry lock,
  claim hierarchy, and atomic create behavior.
- Enforced Planning `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` —
  canonical claim/lane semantics and explicit recovery rules.
- Project Meta Plan #234 on `origin/main` — real in-progress plan with no live
  Plan #234 claim and a blocked next unit.

## Landscape And Prior Art

**Disposition:** inline. The existing graph, registry, start gate, and
worktree lifecycle already supply each required responsibility. A second lane
registry, a graph-side claim lookup, or a new cleanup tool would duplicate a
canonical surface and weaken failure containment. The smallest viable change is
an explicit resume contract at the existing start-gate/claim-acquisition seam,
plus source propagation of the currently consumer-only adapter.

**Alternatives:** Treat `already_active` as `ready`; add a graph-owned mutable
lane registry; or close/reopen Plan #234 under a new plan. These were rejected
because they respectively permit duplicate owners, duplicate mutable authority,
or break the plan's execution lineage.

**Project implications:** Enforced Planning gains the portable source contract
and installer coverage; Ecosystem Ops retains static readiness only; Project
Meta consumes the resulting generated/installed surface and supplies the real
Plan #234 pilot. No repository gains authority to dispose of historical work.

## Boundaries

| Boundary | Owns | Must not do |
| --- | --- | --- |
| Ecosystem Ops plan graph | Static plan identity, dependency, and actionable status | Infer mutable claim/session ownership |
| Enforced Planning source | Portable readiness/resume contract, CLI/template propagation, tests | Store a second lane registry |
| Claim registry | Atomic live ownership and root/child hierarchy | Decide a plan's static readiness |
| Governed-repo Make entrypoint | Invoke the source-derived gate before claim/worktree creation | Treat a successful graph query as a claim |
| Project Meta Plan #234 | Historical-residue ownership decisions and packets | Redefine shared lifecycle behavior |

## Capabilities

| Capability | Producer/owner | Consumer | Boundary claim |
| --- | --- | --- | --- |
| Revision-bound plan readiness | Ecosystem Ops plan graph | Enforced Planning start gate | The graph reports static identity/status; it does not claim a lane. |
| Explicit safe lane resumption | Enforced Planning source contract and installed CLI | Governed-repo `make worktree` | Resume is opt-in and provisional; a matching live claim blocks it. |
| Atomic lane ownership | Canonical coordination-claim registry | Resume/start workflow | Registry-locked claim creation, not the graph result, is the final exclusive ownership guard. |
| Historical worktree disposition | Project Meta Plan #234 | Repository-specific cleanup packets | A resumed lane records owner evidence; it does not gain global deletion authority. |

## Contract

### Inputs

`check_plan_start_readiness` gains an explicit `resume_requested: bool = false`
input. The public CLI/Make surface must expose it as a clearly named resume
operation; it must never be inferred from branch naming, a stale worktree, or a
graph status.

The gate receives the existing qualified plan identity, execution profile,
repository, proposed lane/branch/worktree identity, and exact graph command.
It reads canonical live claims for the target repository only to test the
resume precondition.

### Decision table

| Graph decision | Resume requested | Matching live claim | Gate result |
| --- | ---: | ---: | --- |
| `ready` | either | either | allow normal start; existing semantics unchanged |
| `already_active` | no | either | reject |
| `already_active` | yes | zero | provisionally allow resume |
| `already_active` | yes | one or more | reject with exact matching claim identities |
| `blocked` or `unknown` | either | either | reject |
| invalid, mismatched, malformed, nonzero graph response | either | either | reject |

“Matching” means the same canonical repository plus the same normalized
numbered plan identity. A claim in `active`, `blocked`, or `handoff` status is
live and blocks resume. Completed claims do not.

### Atomicity and race behavior

The readiness result is only a provisional precondition. `make worktree` must
continue to acquire the canonical claim before it creates a branch, worktree,
or session tracker. The registry lock plus existing root-program hierarchy
validation is the final atomic guard: if two resumes observe zero claims, at
most one claim creation succeeds; the other fails before a worktree exists.

No code may make `already_active` universally equivalent to `ready`, relax
write-path conflicts, silently attach to another agent's lane, or use a stale
claim as proof that work is disposable.

### Compatibility and recovery

- Existing `ready` starts, unplanned light work, and non-resume callers keep
  their current behavior.
- Existing `already_active` callers fail exactly as before unless they opt into
  explicit resume.
- A failed gate or failed claim acquisition leaves no new branch, worktree,
  tracker, or claim from the failed attempt.
- Closing or handing off a lane remains governed by `session-close` and its
  disposition/recovery checks; this plan does not add a destructive cleanup
  path.

## Work-Unit Graph

| Unit | Class | Repository / write surface | Depends on | Evidence-first acceptance |
| --- | --- | --- | --- | --- |
| WU-104-01 | integration | Enforced Planning source: portable adapter, CLI/template, source tests | none | Failing both-sign resume tests and source/installer parity inventory |
| WU-104-02 | integration | Ecosystem Ops: graph CLI fixture/readiness behavior only if needed | WU-104-01 contract | Existing `already_active` payload remains revision-bound and documented; no claim lookup is added to graph |
| WU-104-03 | integration | Project Meta governed-consumer upgrade/pilot | WU-104-01, WU-104-02 | Installed gate accepts the zero-live-claim resume fixture and rejects its live-claim twin |
| WU-104-04 | verification | Project Meta Plan #234 resume lane | WU-104-03 | A fresh claimed Plan #234 lane opens, records the mailbox/disposition state, and can later close with no residue |

`WU-104-01` and `WU-104-02` may be combined only if source inspection proves
the graph payload requires no source change. `WU-104-03` is never ready until
the portable source and propagation path are reviewed and tested.

## Acceptance Criteria

| ID | Criterion | Required evidence |
| --- | --- | --- |
| AC-104-01 | Normal `ready` start behavior is unchanged. | Source-level positive regression test |
| AC-104-02 | `already_active` without explicit resume remains rejected. | Negative regression test |
| AC-104-03 | Explicit resume succeeds only for `already_active` plus zero matching live claims. | Positive fixture and structured gate result |
| AC-104-04 | A live `active`, `blocked`, or `handoff` matching claim rejects resume and identifies the blocking lane. | Three negative fixtures |
| AC-104-05 | `blocked`, `unknown`, malformed, mismatched, and nonzero graph responses reject with no lifecycle mutation. | Negative fixtures plus no-side-effect assertions |
| AC-104-06 | Two concurrent resume attempts cannot create two root lanes; the loser has no branch/worktree/tracker. | Lock/race regression test or deterministic injected-claim equivalent |
| AC-104-07 | The portable source owns the adapter, CLI/template, and tests; generated/installed Project Meta surfaces are propagated from it and pass the installer/upgrader check. | Source/installed parity test and generated-surface check |
| AC-104-08 | A real Project Meta Plan #234 resume opens one healthy claimed worktree and subsequent sanctioned closeout removes its claim/worktree/branch after its own disposition. | Revision-bound integration receipt; no historical lane is removed by this criterion |

## Non-Goals

- Bulk worktree cleanup, TTL-based claim release, or automatic stale-lane
  deletion.
- Allowing a second concurrent root lane, bypassing a live owner, or changing
  claims from the graph service.
- Altering graph dependency/status semantics solely to support resume.
- Deployment, release publication, force-push, or mutation of unrelated dirty
  primary checkouts.

## Verification

1. Focused Enforced Planning tests for readiness parsing, claim hierarchy, CLI,
   Make template/install propagation, and worktree no-side-effect failures.
2. Focused Ecosystem Ops `check-ready` tests for the retained
   `already_active` payload and revision identity.
3. A Project Meta installed-consumer fixture with zero and nonzero matching
   claims, followed by one real Plan #234 resume only after source propagation
   has landed.
4. `python scripts/self_test.py` in Enforced Planning and the affected
   repository's installed-entrypoint verification before claiming completion.

## Failure and Rollback

The change is additive and opt-in. Reverting the resume flag support restores
the existing fail-closed behavior. If propagation cannot prove source parity,
the Project Meta pilot stays blocked; it must not receive a hand-maintained
consumer-only fix.

## Completion Record

Completed 2026-07-27.

- AC-104-01 through AC-104-07 are covered by the source readiness, claim-race,
  Make/installer propagation, and no-side-effect regression suites. The focused
  source verification passed 44 tests and Ruff; the broader readiness and
  status-parser suites passed 193 tests after the explicit lifecycle-status
  parser repair.
- Ecosystem Ops PR #9 merged the leading-explicit-status parser fix at
  `f4d9295267efd4ee`; Enforced Planning PR #61 merged the operational source
  `PLAN_RESUME=1` Make path at `840162f0f268`.
- AC-104-08 used the real in-progress Project Meta Plan #234. The graph returned
  revision-bound `already_active`; one explicit resume created the healthy
  claimed `plan-234-residue-resume-20260727` lane, while a duplicate resume was
  rejected before lifecycle mutation.
- Project Meta PR #159 merged that lane's refreshed disposition receipt at
  `5f2608f6bead9256007f4cf9177334ce1906e9dd`. Sanctioned `session-close` then
  removed its worktree and local branch and released its claim. A fresh registry
  query returns no live claim for the scope. Plan #234 remains in progress and
  must explicitly resume again for its next accepted packet.
- The shared plan index update is intentionally deferred to its active Plan #106
  owner; this lane does not overwrite the separately claimed index surface.
