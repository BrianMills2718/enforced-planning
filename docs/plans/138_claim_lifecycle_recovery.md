---
plan_id: "enforced-planning#138"
dependencies: []
dependencies_reviewed: "2026-09-15"
---
# Plan #138: Claim Lifecycle Recovery

**Status:** In Progress
**Type:** maintenance
**Priority:** Critical
**goal_ref:** "claim-lifecycle-root-repair"
**Blocked By:** None
**Landscape disposition:** linked

## Gap

**Current:** Generic session upsert can persist a claim before proving its Git
checkout exists. Once that claim becomes unhealthy, the pre-write guard denies
the same session's canonical recovery command. The typed maintenance exemption
also disagrees with bootstrap about whether `start_revision` must exist.

**Target:** Creation fails before durable state when Git identity is invalid;
exact self-owned recovery stays reachable; and maintenance bootstrap and
admission enforce one start-revision contract.

## User outcome

A typed session start cannot create a live claim for a missing or mismatched
Git checkout, and an exact self-owned session-end command remains reachable
when claim health has already failed.

## Canonical behavioral example

**Starting state:** A native session has no claim, then attempts to start one
against a missing checkout; separately, its already-owned claim loses its
recorded checkout.

**Action:** Submit the typed start request, then submit the exact canonical
session-end command for the unhealthy owned claim.

**Expected result:** The invalid start writes no claim or tracker. The exact
recovery command is admitted and terminates ownership.

**Failure signal:** The start reports success, leaves claim residue, or the
unhealthy claim prevents the exact owning session from ending it.

## References Reviewed

- `enforced_planning/claim_bootstrap.py` — typed claim writer and worktree transaction.
- `enforced_planning/session_target.py` — current Git-identity health checks.
- `enforced_planning/outcome_admission.py` — maintenance exemption contract.
- `scripts/prewrite_claim_gate.py` — claimless control-command admission.
- Existing claim-bootstrap, host-gate, session-close, and maintenance-admission tests.

## Capability Adoption

**Disposition: extend.** Repair the existing claim/session lifecycle; do not add
a second recovery command, registry, or ownership model.

## Capabilities

| Capability | Change | Owner | Consumer and proof |
|---|---|---|---|
| Session claim creation | Require existing exact Git checkout identity before generic upsert | Enforced Planning | Claim-bootstrap focused tests and real typed request |
| Unhealthy-claim recovery | Admit only the exact self-owned canonical session-end command | Enforced Planning host pre-write gate | Missing-worktree recovery test and installed-hook replay |
| Maintenance admission | Require the verified bootstrap start revision consistently | Enforced Planning outcome admission | Typed maintenance classifier test and authentic maintenance lane |

## Landscape And Prior Art

**Disposition: linked.** Extend the existing typed bootstrap, session target,
outcome admission, and canonical closeout owners. Their current contracts are
the relevant prior art; no external mechanism changes this repair decision.

## Plan

**Critical-path classification: direct_blocker.** Prevent invalid state first,
then preserve the exact recovery route and verify the full lifecycle.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| Invalid session upsert | fully_specifiable_now | Upsert requires exact existing Git identity | Missing/mismatched identity fails before creation | Claim bootstrap tests |
| Recovery reachability | fully_specifiable_now | Only the exact owning native session may end itself | Exact recovery passes; foreign/composed controls fail | Host pre-write tests |
| Maintenance exemption | fully_specifiable_now | Bootstrap and exemption share verified start revision | Real receipt and focused classifier test agree | Outcome admission tests |

## Reassessment Contract

**Triggers:** A valid existing session-start consumer lacks Git identity, or
manual session-end can target another native session.

**Autonomous action:** Preserve the fail-closed ownership boundary and revise
the narrow validator or strict command grammar.

**Plan revision required:** Any new recovery authority or non-Git claim target.

**Human decision required:** None for this reversible correctness repair.

**Stopping rule:** Focused suites and one real create/reject/recover/close path pass.

## Observed failure

On 2026-09-15 a generic `session_start_or_update` request reported success for
a nonexistent worktree. The guard then detected the unhealthy claim but denied
the canonical recovery command. Maintenance bootstrap also stores a verified
`start_revision` while its outcome exemption required that field to be absent.

## Acceptance Criteria

- Reject missing or mismatched Git identity before claim/tracker creation.
- Preserve the valid exact-checkout control.
- Admit exact self-owned session-end for an unhealthy claim.
- Deny foreign identity, storage overrides, and composed commands.
- Accept the verified maintenance start revision in the exemption contract.

## Files Affected

- `enforced_planning/claim_bootstrap.py`
- `enforced_planning/outcome_admission.py`
- `scripts/prewrite_claim_gate.py`
- `tests/test_claim_bootstrap.py`
- `tests/test_host_prewrite_claim_gate.py`
- `tests/test_outcome_admission.py`
- Plan #138 bootstrap artifacts
