# Investigation: Activity Heartbeat Gap

**Date:** 2026-07-17
**Scope:** coordination claim liveness and native Codex activity
**Status:** root cause established; bounded repair in progress

## Question

Why could an active coordination claim with an unobserved mailbox message look
like a live working lane, and what is the smallest repair that makes the status
epistemically honest?

## Atomic Findings

### A1. `status: active` is a reservation state, not proof of a live session

The claim lifecycle uses an explicit status and expiry to represent reserved
scope. Session liveness is derived separately from `heartbeat_at`.

Source:

- `enforced_planning/coordination_claims.py:417`
- `docs/plans/29_session_heartbeats_and_agent_liveness.md`

### A2. A live claim with a session ID but no heartbeat is currently reported as healthy

`claim_liveness_issues()` deliberately returns no issue when `heartbeat_at` is
missing for backward compatibility. `claim_runtime_status()` therefore reports
such a claim as healthy when no other health issue applies.

Observed example:

- claim: `mac-deployment-adversarial-audit`
- session: `codex:inside-success:mac-deployment-adversarial-audit:20260716`
- claim status: `active`
- heartbeat: absent
- reported runtime health: `healthy`

Source:

- `enforced_planning/coordination_claims.py:417-457`
- `docs/plans/29_session_heartbeats_and_agent_liveness.md`

### A3. Native Codex activity already invokes a coordination hook, but that hook only polls mail

The installed hook runs at `SessionStart`, `UserPromptSubmit`, and
`PostToolUse`. Its implementation polls and observes mailbox requests, but does
not refresh the matching claim heartbeat.

Source:

- `scripts/coordination_hook.py:56-122`
- `enforced_planning/hook_wiring.py:276-288`

### A4. A synthetic or obsolete session ID cannot be revived by a real native client event

Native Codex supplies a runtime UUID, normalized as `codex:<uuid>`. A claim
bound to a descriptive synthetic ID will not match that runtime identity. Its
mail remains unobserved and its heartbeat cannot truthfully be refreshed by the
current client.

Source:

- `scripts/coordination_hook.py:83-86`
- `enforced_planning/coordination_claims.py:987-1036`

### A5. Repository commits are progress evidence but do not identify the owning claim

Git history records repository changes, not the session ID or coordination
claim that produced them. A fresh commit therefore cannot establish that a
particular claim owner is alive. Claim liveness requires a matching session
heartbeat; work progress requires separately attributable evidence.

### A6. Existing coordination integrity policy already treats incomplete session contracts as weak

Plan 73 established that incomplete plan-bound claims are weak rather than
healthy. The missing-heartbeat compatibility rule is the remaining semantic
hole: an uninstrumented claim can still be displayed as healthy.

Source:

- `docs/plans/73_coordination_status_integrity.md`

## Assumptions Tested

| Assumption | Result | Evidence |
|---|---|---|
| Heartbeat support does not exist | Wrong | Explicit heartbeat field, CLI, classifier, and tests exist |
| Native Codex activity refreshes the heartbeat | Wrong | The activity hook only polls the mailbox |
| Recent Git commits prove the Mac claim is alive | Unsupported | Commits are not bound to claim or session identity |
| Missing heartbeat means stale | Too strong | It means liveness is uninstrumented; the honest status is weak, not stale |

## Root Cause

The status projection collapsed three independent facts:

1. **reservation state** — whether a claim still reserves scope;
2. **session liveness** — whether the exact owning runtime recently emitted a
   heartbeat;
3. **progress evidence** — whether attributable work advanced.

The native activity adapter omitted the heartbeat refresh, while the
backward-compatibility rule translated missing evidence into healthy liveness.
Together these behaviors made an active but uninstrumented legacy claim look
alive.

## Repair

1. Refresh the exact matching claim heartbeat at every native Codex activity
   hook before mailbox polling.
2. Do not let the native hook adopt a claim with a missing or different session
   identity.
3. Classify a live, session-bound claim with no heartbeat as
   `weak`/`missing_session_heartbeat`, while keeping it readable and not calling
   it stale.
4. Add both-sign tests: matching activity refreshes the heartbeat; a different
   runtime does not.

## Policy Friction Pending Handoff

The central policy-friction ledger is actively write-claimed by Project Meta
Plan 224, so this exact entry is retained here for its owner:

- **Policy:** `coordination-active-vs-live-status`
- **Friction:** An active TTL claim with no heartbeat or matching runtime can be
  presented as healthy, while repository commits and unobserved mailbox state
  invite an unsupported inference that its owner is working.
- **Recommendation:** Expose reservation state, session liveness, and progress
  evidence as separate dimensions. Missing heartbeat must be
  `uninstrumented`/weak rather than alive; native activity should refresh only
  an exact matching session claim.

Additional workflow friction observed during landing:

- **Policy:** `worktree-pr-merge`
- **Friction:** `gh pr merge --delete-branch` failed after a clean, mergeable PR
  because GitHub CLI attempted a local branch operation while `main` was
  correctly checked out in the canonical worktree.
- **Recommendation:** The sanctioned worktree landing procedure should merge
  remotely first and treat local/remote feature-branch cleanup as a separate
  best-effort step.

## Synthesis

This is a real policy and adapter gap, not evidence that all heartbeat
infrastructure failed. The safe bounded repair is to connect existing native
activity to the existing heartbeat mechanism and make absence of liveness
evidence visible. No takeover or Mac-side action is required to implement the
shared correction.
