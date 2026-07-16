# Plan #73: Coordination Status Integrity

**Status:** 🚧 In Progress
**Type:** implementation
**Priority:** Critical
**Blocked By:** None
**Blocks:** trustworthy continuous multi-agent execution status

## Objective

Prevent an agent or operator from treating a stale default-branch checkout or
an incomplete plan-bound claim as current, healthy coordination authority.

This plan reuses the existing claim, session, lane-registry, and worktree
closeout contracts. It does not create a new plan-owner registry.

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

## Rollback

Revert the shared implementation and generated-adapter changes as one commit.
The underlying Git, claim YAML, session tracker, and worktree lifecycle formats
remain unchanged, so no data migration or state rollback is required.
