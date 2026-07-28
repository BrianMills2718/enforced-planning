# Plan #107: Claim Readiness And Merge Closeout Enforcement

**Status:** Complete
**Type:** implementation
**Priority:** Critical

**Landscape disposition:** linked

This closes enforcement gaps in the existing Plan #28 stale-claim lifecycle,
Plan #42 atomic closeout, Plan #59 disposition enforcement, and Plan #74
plan-DAG worktree lifecycle rather than introducing another ownership system.

## User Outcome

An agent cannot begin a blocked or approval-gated write unit merely by creating
a claim, and a merged lane cannot continue looking actively owned without an
immediate visible failure telling its owner to close or explicitly dispose it.

## Research

This plan is grounded in the existing implementation and authorities:

- `enforced_planning/plan_readiness.py` checks plan readiness before the Make
  workflow but does not bind the decision into the claim.
- `enforced_planning/coordination_claims.py` owns atomic claim acquisition and
  already classifies `branch_merged_to_default`, but previously used only the
  potentially stale local default branch and returned success from `--check`.
- `enforced_planning/session_lifecycle.py` and Plan #42 already provide the
  sanctioned disposition-aware `session-close` operation.
- Plan #106 provided the negative control: a blocked MF-03B write claim was
  created before the canonical exact-approval record existed, while merged
  MF-03A/MF-03B claims continued to report healthy.

## Landscape And Prior Art

This plan extends the existing coordination stack rather than creating a
parallel ownership mechanism. [Plan #28](28_stale_claim_lifecycle_and_cleanup_automation.md)
defines stale-claim lifecycle behavior, [Plan #42](42_atomic-closeout-and-claimed-worktree-removal.md)
owns atomic disposition-aware closeout, [Plan #59](59_worktree-lifecycle-disposition-enforcement.md)
enforces supported dispositions, and [Plan #74](74_plan-dag-governed-worktree-lifecycle.md)
binds plan-DAG readiness to worktree creation. The remaining gap is the claim
boundary itself: readiness and approval evidence was not retained with write
ownership, and merged active claims were diagnostic output rather than a
failing condition.

## Goal

Make claim acquisition and post-merge ownership truthful by construction:

1. a plan-bound write claim cannot be created without a canonical work-unit
   binding;
2. a blocked work unit or a controlled unit missing its declared approval is
   rejected before the claim is written; and
3. an active claim whose branch is already integrated into the canonical
   remote default branch is a high-severity validation failure until it receives
   a supported closeout disposition.

## Boundary

Included:

- additive claim fields binding the exact canonical work graph and work unit;
- claim-time validation of unit status and declared approval records;
- remote-default-aware merged-branch detection;
- nonzero `--check` status for merged-but-active ownership;
- propagation through the sanctioned worktree/session entrypoints;
- deterministic positive and negative tests and operator documentation.

Excluded:

- automatic deletion of claims, branches, or worktrees;
- inference that merge always completes deployment or runtime verification;
- a new human-identity or cryptographic approval service;
- changes to mailbox delivery or host configuration.

## Contract

Every new live plan-bound claim with write ownership must name a repository-relative work
graph and exact work-unit ID. The claim loader reads that graph from the
canonical remote default ref (falling back to the local default only when no
remote default exists), requires unit and readiness status `ready`, requires
one non-empty canonical approval for every declared control approval type, and
stores the graph hash plus approval revisions in the claim.

Existing claims remain readable. Refreshing or creating a plan-bound claim with write ownership
claim uses the new contract; omitting the binding fails loud.

An active claim is `high_severity` when its branch tip is an ancestor of the
canonical remote default branch and differs from the default-branch starting
tip. `--check` returns nonzero for this condition. Operators must use
`session-close` with `merged`, or record a supported non-merge disposition when
the lane genuinely remains outside the default branch.

## Canonical Behavioral Example

Input: Plan #106 MF-03B has `status=blocked`, `readiness.status=blocked`, and no
readiness approval in the work graph on `origin/main`.

Action: an agent requests a plan-bound write claim for MF-03B.

Observable result: claim creation exits nonzero before writing a claim file. If
the unit later becomes canonically `ready` with an exact readiness approval, the
claim succeeds and retains the graph hash, work-unit ID, and approved revision.
After its branch lands, `--check` exits nonzero until `session-close` records a
terminal disposition.

## Files Affected

- `Makefile`
- `enforced_planning/coordination_claims.py`
- `enforced_planning/session_lifecycle.py`
- `scripts/check_coordination_claims.py`
- `scripts/session_start.py`
- `scripts/merge_pr.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_create_worktree.py`
- `tests/test_session_cli.py`
- `tests/test_merge_pr.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/CLAUDE.md`
- `docs/plans/107_claim_readiness_and_merge_closeout_enforcement.md`

## Plan

### Critical Path Classification

| Increment | Class | Behavior or named blocker changed |
|---|---|---|
| Work-unit readiness and approval binding | `direct_blocker` | Blocked or approval-incomplete units cannot acquire write ownership. |
| Remote-default merged-ownership detection | `direct_blocker` | Merged lanes cannot remain silently active. |
| Make/session propagation and operator documentation | `hardening` | Sanctioned entrypoints expose and explain the enforced contract. |

## Acceptance Criteria

- A blocked unit cannot create a claim and leaves no claim file.
- A controlled ready unit with a missing approval cannot create a claim.
- A ready unit with exact declared approvals creates a digest-bound claim.
- A branch merged only to `origin/main` is detected even when local `main` is
  stale.
- `--check --json` returns nonzero and identifies the merged active claim as
  high severity.
- Existing legacy claims remain readable.
- Focused tests, Ruff, strict mypy, self-test, plan validation, and
  `git diff --check` pass.

## Verification Evidence

- `pytest -q tests/test_check_coordination_claims.py tests/test_plan_readiness.py tests/test_session_cli.py tests/test_create_worktree.py tests/test_session_contracts.py tests/test_merge_pr.py`
  — 108 passed.
- `python scripts/self_test.py` — all checks passed.
- Ruff passed on every changed Python implementation and test surface.
- Strict mypy passed on the five changed Python implementation surfaces.
- Plan validation and `git diff --check` passed without warnings or errors.
- The full suite completed with 822 passed, 1 skipped, and 16 failures. A clean
  `origin/main` archive at `9f0d11d` completed with 808 passed, 1 skipped, and
  22 failures; the remaining failures are inherited agent-rendering, governed
  audit, markdown-link, registry-fixture, and legacy doc-authority fixture
  failures outside Plan #107's enforcement boundary.
