# Plan #73: Coordination Status Integrity

**Status:** ✅ Complete
**Type:** implementation
**Priority:** Critical
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** trustworthy continuous multi-agent execution status

## Objective

Prevent an agent or operator from treating a stale default-branch checkout or
an incomplete plan-bound claim as current, healthy coordination authority.

This plan reuses the existing claim, session, lane-registry, and worktree
closeout contracts. It does not create a new plan-owner registry.

## User Outcome

When Brian asks whether a plan is stuck or which agent owns it, the ordinary
status commands answer from current repository authority and complete live
session records. They do not report an old checkout or an incomplete claim as
healthy.

## Canonical Behavioral Example

**Starting input/state:** two agents work on Plan 0141 while the canonical
default checkout may be behind its fetched remote.

**Action:** run repository and session status, then activate the second lane.

**Expected observable result:** current authority is reported exactly; one
unparented `program` claim is the coordinator; the second claim names it as
`parent_scope`; and both sessions are healthy.

**Behavioral evidence:** observed real OntoCanon consumer slice.

**Substrate/process evidence:** deterministic stale/current, incomplete-claim,
hierarchy, concurrent-activation, installer, and consumer tests.

**Failure signal:** a stale checkout exits successfully, an incomplete claim is
healthy, a heartbeat updates zero claims, or two coordinator roots activate.

## Gap

The coordination runtime can protect file paths and render live lanes, but its
ordinary status surface can consume a stale default-branch checkout and its
health classifier does not require the complete session metadata already
defined for plan-bound continuous work. The target is a fail-closed freshness
read plus truthful reuse of the existing session contract.

## Research

References reviewed before implementation:

- `enforced_planning/coordination_claims.py`
- `enforced_planning/session_contracts.py`
- `enforced_planning/session_lifecycle.py`
- `enforced_planning/active_work_registry.py`
- `docs/plans/25_lane-model-and-active-lane-registry.md`
- `docs/plans/31_session_cli_and_governed_repo_entrypoint_enforcement.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `templates/Makefile.meta`
- the retained OntoCanon Plan 0141 incomplete claim and 171-commit stale-root
  reproduction recorded in the cross-project investigation

## Landscape And Prior Art

**Alternatives:** add a second plan-owner registry; infer ownership from file
claims alone; or reuse the existing claim/session hierarchy. The first two were
rejected because they create split authority or cannot represent coordination.

**Project implications:** canonical claims remain the only mutable ownership
authority; `program` plus `parent_scope` represents plan coordination; status
refreshes remote metadata without changing worktree bytes; existing closeout
owns cleanup.

**Refresh trigger:** reconsider only if coordination moves beyond one shared
local claim registry or a remote lease service becomes an explicit requirement.

## Current And Target Delta

Current:

- `make status` prints local Git state and succeeds even when the default branch
  is materially behind its tracked remote.
- claim health requires branch, worktree, and session ID, but can report a
  plan-bound claim healthy when `repo_root`, `session_name`, `broader_goal`, or
  `tracker_path` is absent.
- `session-status` renders absent goal/phase values as `None :: None` and still
  recommends `continue`.

Target:

- the shared repository-status command refreshes remote metadata and fails loud
  when the checked-out default branch is behind or freshness cannot be verified;
- feature worktrees remain usable and receive explicit base-drift visibility
  without being mistaken for the canonical default-branch status surface;
- plan-bound session claims missing their existing session-contract metadata
  are `weak`, name every missing field, and direct the operator to repair the
  session contract;
- parallel claims for the same normalized project/plan identity reuse one
  existing root `program` claim, and every subordinate claim names that root
  through `parent_scope`;
- the derived active-work registry renders the root/child grouping without
  becoming a second ownership authority;
- the generated Make target and installed governed-repo script use the shared
  implementation.

## Design

### Requirements

1. Current-authority status must bind the local default branch to its tracked
   remote after an observed fetch.
2. Status must not merge, reset, checkout, stash, or otherwise mutate working
   files or branch refs.
3. Remote failure is `freshness_unknown`, not success.
4. A non-default feature worktree reports default-branch drift but does not fail
   solely because the feature branch is not its remote default.
5. Existing legacy claims remain readable. Plan-bound live `program`, `write`,
   and `research` claims without the full existing session contract are weak.
6. Claim creation's pre-worktree reservation remains possible; the completed
   sanctioned `make worktree` flow must end healthy after `session-start` fills
   the session metadata.
7. One complete session claim may run alone without a synthetic coordinator.
   When a second live session joins the same normalized project/plan identity,
   exactly one unparented `program` claim is the root and every other claim
   names its scope as `parent_scope`.

### Boundaries And Contracts

- `enforced_planning.repository_status` owns read-only Git freshness
  inspection and its typed result.
- `scripts/project_status.py` and `scripts/meta/project_status.py` are thin CLI
  adapters.
- `coordination_claims.claim_health_issues` remains the canonical claim-health
  classifier; no new claim store or status authority is introduced.
- `session_lifecycle.status_sessions` remains the session projection and adds
  explicit health issues/recovery action.
- `coordination_claims` derives plan identity and hierarchy validity from the
  canonical live claims; it does not persist a lease or owner record.
- `active_work_registry` adds a derived plan-hierarchy view whose root and
  child scopes always point back to canonical claim files.
- `templates/Makefile.meta` and the framework Makefile route `status` through
  the shared command.

### Failure Behavior

- fetch fails: print the exact remote failure and exit nonzero;
- no Git repository/default branch/remote ref: return a typed unknown state and
  exit nonzero when current authority is required;
- checked-out default behind remote: print commits and fail without mutation;
- feature branch: show canonical default-branch drift and current branch status;
- incomplete plan claim: report `weak`, list missing fields, and recommend
  `repair_session_contract`.
- duplicate plan roots, parallel rootless claims, or orphan/wrong parents:
  reject new session activation and report `repair_claim_hierarchy` for
  readable legacy claims.

## Non-Goals

- A second mutable plan-owner or lease registry.
- Automatic fast-forward, merge, rebase, reset, or cleanup.
- Global serialization of disjoint agents.
- Fleet-wide rollout beyond the shared installer and the bounded OntoCanon
  consumer repair.
- Historical worktree deletion in this slice.

## Acceptance Criteria

| ID | Criterion | Evidence class | Expected grade |
|---|---|---|---|
| AC1 | A local default branch one commit behind a reachable remote exits nonzero and reports `stale`; no local ref or worktree bytes change. | test | A |
| AC2 | A current default branch exits zero and reports the exact local/remote commit identity. | test | A |
| AC3 | An unreachable remote exits nonzero as `freshness_unknown`, never current. | test | A |
| AC4 | A feature worktree remains status-readable while exposing canonical default-branch drift. | test | A |
| AC5 | The observed Plan 0141-shaped claim is `weak` with missing repo/goal/session/tracker issues; session status never prints `healthy None :: None`. | test | A |
| AC6 | A claim produced by the sanctioned session-start path remains healthy. | test | A |
| AC7 | Installed governed repos receive the shared project-status adapter and Make target. | test | A |
| AC8 | Two live sessions for the same normalized project/plan identity are healthy only with exactly one root `program` claim and correctly parented subordinate claims; sequential or concurrent duplicate roots, rootless parallel claims, and wrong parents fail loud. | test | A |
| AC9 | The sanctioned session-start CLI/Make path can declare `claim_type` and `parent_scope`, while a single standalone session remains backward-compatible. | test | A |
| AC10 | The derived active-work payload and Markdown identify each normalized plan root and its child scopes without creating mutable hierarchy state. | test | A |

## Plan

### Critical Path Classification

| Increment | Class | Observable result |
|---|---|---|
| Freshness and session-health repair | `direct_blocker` | Status can be trusted before substantive work resumes. |
| Root/child claim hierarchy | `direct_blocker` | Parallel plan ownership is unambiguous. |
| Installer and OntoCanon adoption | `enabler` | The shared behavior is usable in the affected consumer. |

## Thin Slices

1. **Freshness instrument:** typed Git status plus the stale/current/unknown
   negative controls; wire the framework command.
2. **Session-health repair:** reproduce the incomplete Plan 0141 claim, tighten
   health classification and recovery output, preserve complete-session green.
3. **Portable adoption:** install the adapter/Make target through the existing
   governed-repo installer and verify one generated consumer fixture.
4. **Existing-claim hierarchy:** enforce and render one root `program` claim
   plus parented subordinate claims when execution becomes parallel.
5. **Bounded OntoCanon rollout:** update only the installed adapter/Make target
   after the shared commit is independently reviewable.

## Verification

```bash
PYTHONPATH=. pytest -q \
  tests/test_repository_status.py \
  tests/test_check_coordination_claims.py \
  tests/test_session_cli.py \
  tests/test_generate_active_work_registry.py \
  tests/test_install_governed_repo.py
python scripts/self_test.py --docs
```

## Completion Evidence

Completed on 2026-07-16.

- Shared implementation and the installed-entrypoint repair are on Enforced
  Planning `main` at `434e487`.
- The focused repository-status, claim, session, registry, and installer suite
  passed: 83 tests. The post-repair installer suite passed: 23 tests. Changed
  code passed Ruff and strict mypy in the shared source environment.
- The full Enforced Planning suite produced the same 12 pre-existing failures
  on the Plan 73 branch and untouched `main`; Plan 73 introduced no additional
  failure. The failures are the recorded environment/baseline issues in agent
  projection, governed-repo fixture, and worktree-link tests.
- OntoCanon consumed the exact governed coordination profile in commit
  `9d70cef4`, now on its `main`. The installer is idempotent with no blockers,
  all five mirror/import tests pass, the complete OntoCanon pytest suite exits
  successfully, and changed files pass Ruff.
- Observed OntoCanon runtime evidence: canonical `make status` reports `main`
  current and clean at `9d70cef4`; feature status reports the current remote
  default separately; `session-status` reports the rollout claim healthy; and
  `make session-heartbeat` updated exactly one canonical claim.
- Final closeout dogfood reproduced a stale feature-upstream edge case after
  canonical-default merge proof. Closeout now bypasses Git's feature-upstream
  `branch -d` heuristic only after proving the branch tip is contained in the
  pushed default branch; the exact divergent-upstream regression test passes.
- AC1–AC10 achieved grade A: each criterion has source plus deterministic test
  evidence, with the bounded consumer path additionally observed live.

## Rollback

Revert the shared implementation and generated-adapter changes as one commit.
The underlying Git, claim YAML, session tracker, and worktree lifecycle formats
remain unchanged, so no data migration or state rollback is required.
