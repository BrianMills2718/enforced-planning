# Continuous Execution Contract

This is the canonical portable pattern for continuous or overnight autonomous
execution in governed repos. When a repo's CLAUDE.md references this doc, the
rules here are authoritative. Local CLAUDE.md sections may summarize; this doc
defines the precise terms.

This contract is an instance of **loop engineering** (coined June 2026): designing
a repeatable agent workflow with explicit stopping conditions, where the stopping
conditions are defined once and the agent runs until they are met. The two stop
conditions below are the loop's termination predicate.

---

## When This Contract Applies

This contract applies whenever the operator says "never stop," "run
continuously," "run all night," or any equivalent instruction authorizing
multi-phase autonomous execution without human checkpoints between phases.

---

## Core Rule

**Execute all phases in the active sprint tracker in order, without pausing
between them.** A completed phase is not a stop condition. A green test suite
is not a stop condition. A finished commit is not a stop condition. Update the
tracker, move to the next slice, keep executing.

---

## The Only Two Legitimate Stop Conditions

1. **An action that is BOTH irreversible AND affects shared state.** Examples:
   force push to a shared branch, drop a production table, delete production
   data, send external messages. If you are uncertain whether an action is
   irreversible AND shared-state-affecting, document the uncertainty in the
   sprint tracker and choose the safer alternative. Do not stop to ask.

2. **A genuine architectural decision not pre-made in the active sprint plan
   that cannot be safely defaulted.** If the plan pre-makes the decision (even
   implicitly), proceed. If the plan does not, and there is no safe default,
   document the gap in the sprint tracker and move to the next unblocked slice.
   Do not stop to ask unless every remaining slice is blocked by the same gap.

Everything else — uncertainty, tool failure, partial results, blocked
individual task, "should I continue?" — is NOT a stop condition.

---

## Execution Discipline

### Sprint Contract

Before starting a multi-phase run:
1. Write a sprint tracker doc (one active plan + one tracker with all phases listed)
2. Record success criteria, rollback points, and open uncertainties in the tracker
3. Update the active sprint pointer in CLAUDE.md to this tracker

During execution:
- Update the tracker after every commit — mark the just-completed phase ✅,
  record what was verified, and identify the next action
- The tracker survives context compression; conversational intent does not

### Commit Discipline

Every verified increment gets its own commit before the next phase starts.
Uncommitted work is invisible, unrecoverable, and unreviewed.

**Never end a session with uncommitted changes.** Commit or stash.

### Worktree Discipline

Every Plan-level phase runs in a dedicated worktree inside the repo:
```
git worktree add <repo>/worktrees/plan<N>-<slug> -b plan-<N>-<slug>
```

`worktrees/` must be in the repo's `.gitignore`. After a phase is verified:
1. Commit in the worktree
2. Merge to canonical branch (main)
3. Push
4. Record the `merged` disposition and close the claimed lane through the
   sanctioned `session-close` / `make worktree-remove` path
5. Confirm the worktree was removed and the local branch was safely deleted
6. Update the sprint tracker
7. Begin the next slice

A finished worktree that has not been merged, pushed, and removed is
operational clutter. The cleanup step is mandatory, not optional.

If a lane is intentionally not merged, it is not a normally completed slice.
Record one explicit non-merge disposition (`active`, `handoff`, `superseded`,
`abandoned`, `archived`, or `migrated`) with the evidence required by the
operator guide. Never infer deletion safety from a clean checkout, and never
mass-merge stale branches merely to make the worktree list shorter.

A long-lived branch does not require a long-lived checkout. Keep the branch on
its remote when needed; remove an inactive worktree and recreate it when work
resumes. Keep a worktree only while the lane is actively owned and has a next
action plus review trigger.

### Push Discipline

Push verified work after every merge. GitHub is recovery memory for real
progress. A local commit is not enough for overnight work.

Exception: do not force-push to shared branches without explicit operator
authorization (stop condition #1).

### Circuit Breaker

After 3 failed attempts on the same problem with no new information (different
error = new information; same error = not new information), log the finding in
the sprint tracker and move to the next highest-value unblocked slice. Do not
retry the same approach indefinitely.

---

## Blocked Tasks

A blocked individual task is not a stop condition. When a task is blocked:
1. Record the blocker precisely in the sprint tracker
2. Move to the next highest-value unblocked slice
3. Keep executing until there is no safe high-value unblocked work remaining

Only stop when every remaining slice in the sprint is blocked by the same gap
that qualifies as stop condition #2.

---

## End of Sprint

A sprint ends when ALL acceptance criteria in the tracker are ✅ green —
not after a single plan, not after feeling uncertain. When a sprint ends:

1. Mark the sprint tracker ✅ Complete
2. Push all repos
3. Clean all finished worktrees
4. If more work is needed, write a new sprint tracker before continuing

---

## What Each Legitimate Stop Condition Requires

When a stop condition IS reached:
1. Update the sprint tracker with current state
2. Commit all verified work
3. Push
4. Leave precise notes in the tracker so the next session can resume

---

## References

- `PLANNING_OPERATING_MODEL.md` — artifact dependency graph and planning hierarchy
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — claims, lanes, and worktree lifecycle
- ADR-0010 — agent_memory as required planning input
