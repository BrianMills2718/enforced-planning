# Investigation: Session heartbeat exits successfully after updating zero claims

Date: 2026-07-16
Plan: 73
Scope: the sanctioned `make session-heartbeat` path for a live Plan-bound
session in a linked worktree

## Observed reproduction

From the active Plan 73 worktree, the sanctioned heartbeat command found the
session contract but printed:

```text
heartbeat: updated 0 claims for session codex:019f5870-691a-7672-9806-95abaf6740ba
```

The live claim at
`~/.claude/coordination/claims/codex_enforced-planning_plan-73-coordination-status-integrity.yaml`
contained that exact `session_id` and remained active.

## Atoms

| ID | Question | Dependencies | Status |
|---|---|---|---|
| A1 | How does the heartbeat CLI resolve the session and select claims to update? | none | answered |
| A2 | Which claim stores and repo identities can the session-start path write? | none | answered |
| A3 | What exact identity mismatch caused the reproduced claim to be skipped? | A1, A2 | answered |
| A4 | Can another independent path produce the same successful zero-update symptom? | A1 | answered |
| A5 | What smallest fail-loud repair preserves valid no-claim session behavior, if any? | A3, A4 | answered |

## Assumptions register

| # | Assumption | Confidence | How to verify | Round | Status |
|---|---|---|---|---|---|
| 1 | The heartbeat command and claim reader may resolve different canonical repo roots in a linked worktree. | medium | Trace both call paths and print their resolved roots under the reproduction. | 1 | **Wrong:** both use the canonical global claims directory; the mismatch is the Make-supplied project name. |
| 2 | A session started through the sanctioned worktree path is expected to own at least one live claim. | high | Read session lifecycle contracts and existing tests for claimless sessions. | 1 | confirmed for this scoped/branched path |
| 3 | The zero-update success is deterministic, not a timing race. | high | Re-run from the same worktree and inspect timestamps. | 1 | confirmed |

## Evidence log

- Runtime reproduction above: command exited zero and explicitly reported zero
  updated claims.
- The active claim was read directly and carried the exact reported session ID.
- `Makefile:111` derives `WORKTREE_PROJECT` from `$(notdir $(CURDIR))`. Runtime
  expansion is `plan-73-coordination-status-integrity` in the linked worktree
  and `enforced-planning` in the canonical checkout.
- `Makefile:243-283` sends that derived value to heartbeat, status, finish, and
  close, so the mismatch is not heartbeat-only.
- `enforced_planning/coordination_claims.py:824-873` filters first by the
  supplied project and only then updates heartbeat fields. The live claim owns
  project `enforced-planning`, so the worktree-directory name cannot match.
- `enforced_planning/session_lifecycle.py:659-709` forwards the project filter
  both to claim mutation and tracker discovery without requiring a nonzero
  match.
- `scripts/session_heartbeat.py:50-69` always returns zero, even when the
  lifecycle payload says `updated_count == 0`.
- The failed run left both the claim and tracker timestamps at their original
  `2026-07-16T21:37:26Z` values, confirming that no hidden mutation occurred.

### Answers

- **A1:** the CLI resolves the ambient Codex session correctly, but claim
  selection requires agent + caller-supplied project + optional scope/branch.
- **A2:** session start writes the global canonical claims store and a global
  project-namespaced tracker. The stored project is the canonical repo name
  supplied when the worktree was created from the root checkout.
- **A3:** the exact mismatch is `project=plan-73-coordination-status-integrity`
  from the worktree directory versus stored `project=enforced-planning`.
- **A4:** missing/expired claims or wrong agent, project, scope, branch, or
  session selectors all produce the same zero-match result at the low-level
  mutation helper. Those are valid diagnostic outcomes for that helper but are
  never success for the higher-level sanctioned session heartbeat.
- **A5:** derive `WORKTREE_PROJECT` through Git's common directory using the
  existing worktree resolver, and require `heartbeat_session` to update at
  least one claim. Keep `heartbeat_claims`' zero-result contract available to
  lower-level diagnostic callers.

## Contractions

The claim store and session ID are not the fault. One context-dependent Make
default feeds the wrong project identity to every session lifecycle target in a
linked worktree, and the heartbeat adapter turns the resulting zero-match into
success. The repair must therefore (1) derive the project from the canonical
repository root and (2) make a scoped heartbeat fail if it updates no claim.

After implementing those two changes, the same linked worktree resolved
`WORKTREE_PROJECT=enforced-planning`; the heartbeat updated exactly one claim
and its linked tracker to the same timestamp. An explicit wrong-project
negative control exited nonzero with every rejected selector in the error.

## Synthesis

### Root cause

The shared Make block equated the current directory's basename with project
identity. That is true in a canonical checkout and false by construction under
the required `<repo>/worktrees/<branch>/` layout. The lifecycle layer then
accepted zero matching claims as a successful heartbeat.

### Impact

Heartbeat, status, finish, and close all received the wrong default project
when invoked inside a linked worktree. Heartbeat was directly observed to leave
both claim and tracker stale while exiting successfully. The other commands
shared the bad selector and could hide or fail to locate the intended lane.

### Repair

- Added a canonical-project query to the existing worktree creation utility,
  backed by `git rev-parse --git-common-dir`.
- Changed the shared Make block to use that stable project identity.
- Made the higher-level heartbeat fail when it updates zero live claims.
- Added root/worktree identity, successful heartbeat, and wrong-project
  negative controls.

Confidence: high. The original runtime path was reproduced before the change,
the precise selector mismatch was observed, and both positive and negative
runtime paths were replayed after the change.

Open question: low-level direct callers of `heartbeat_claims` still receive a
zero-count result by design. They must interpret it explicitly; the sanctioned
session CLI now does so fail-loud.

## Synthesis

Root cause, impact, repair, confidence, and open questions pending.
