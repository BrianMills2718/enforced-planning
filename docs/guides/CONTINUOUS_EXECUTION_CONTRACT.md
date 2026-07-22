# Continuous Execution Contract

This is the canonical portable pattern for continuous or overnight autonomous
execution in governed repos. When a repo's CLAUDE.md references this doc, the
rules here are authoritative. Local CLAUDE.md sections may summarize; this doc
defines the precise terms.

This contract is an instance of **loop engineering**: designing a repeatable
agent workflow with explicit stopping conditions, where the agent continues
while a safe, authorized, outcome-advancing action remains.

---

## When This Contract Applies

This contract applies whenever the operator says "never stop," "run
continuously," "run all night," or any equivalent instruction authorizing
multi-phase autonomous execution without human checkpoints between phases.

---

## Select An Execution Profile

Continuous authorization controls persistence, not process weight. Select the
smallest profile that protects the actual work:

| Profile | Use when | Required control surface |
| --- | --- | --- |
| `continuous-light` | Reversible single-writer development, a functional PoC, or a bounded local sequence | Reuse the existing plan/task authority, focused verification, ordinary commits and pushes, and a concise final state |
| `continuous-coordinated` | Multiple writers, repositories, or dependent phases can collide | One shared tracker, scoped claims, worktrees where writes overlap, focused increment checks, and explicit integration |
| `continuous-release` | Work will publish, migrate, deploy, or make a consequential terminal claim | Coordinated controls plus an immutable candidate, broad terminal verification, rollback/recovery evidence, and release disposition |

Default to `continuous-light`. Move to a stronger profile only when concurrency,
shared-state effect, irreversibility, or the claim being made requires it. A
specialized skill, existing repository complexity, or the phrase "run all
night" does not itself promote the profile.

---

## Core Rule

Execute the authorized outcome path without pausing merely because one phase,
test run, or commit completed. Continue to the next bounded action only while it
materially advances the stable initiative example, removes a reproduced direct
blocker, or completes a control required by the selected profile. A locally new
variation of an already-proven mechanism is not automatically strategic
progress.

Process artifacts, gate repair, cleanup, reconciliation, and hardening do not
count as product progress unless current evidence shows they directly block the
canonical behavior or selected terminal claim.

---

## The Legitimate Stop Conditions

1. **An action that is BOTH irreversible AND affects shared state.** Examples:
   force push to a shared branch, drop a production table, delete production
   data, send external messages. If you are uncertain whether an action is
   irreversible AND shared-state-affecting, record the uncertainty in the
   active authority and choose the safer alternative. Do not stop to ask.

2. **A genuine architectural decision not pre-made in the active authority
   that cannot be safely defaulted.** If the plan pre-makes the decision (even
   implicitly), proceed. If the plan does not, and there is no safe default,
   document the gap and move to the next unblocked slice.
   Do not stop to ask unless every remaining slice is blocked by the same gap.

3. **No safe, authorized, evidence-supported, goal-advancing next action remains
   after bounded investigation.** Do not invent a new phase merely to remain
   active, retain a write claim while waiting, or repeatedly poll unchanged
   external state. Persist the current state, evidence, owner or blocker, and
   exact resume event; release or narrow claims; then return control.

Everything else — uncertainty, tool failure, partial results, blocked
individual task, "should I continue?" — is NOT a stop condition while a bounded
next action remains.

---

## Execution Discipline

### State Contract

For `continuous-light`, reuse the current task, plan, issue, or progress record.
Do not create a tracker, numbered plan, claim, or handoff solely because the run
is continuous. Before starting, state the user outcome, stable initiative
example when the task spans several increments, current profile, and stop
conditions in the existing authority or conversation.

For `continuous-coordinated` and `continuous-release`, use one shared tracker
that records phases, ownership, success criteria, rollback points, and open
uncertainties. Update it at meaningful integration boundaries, not merely to
mirror every command.

When a run is likely to cross context compression and no durable authority
already owns its state, create one progress record. Do not create two.

### Commit Discipline

Every verified increment gets its own commit before the next phase starts.
Uncommitted work is invisible, unrecoverable, and unreviewed.

**Never end a session with uncommitted changes.** Commit or stash.

### Worktree Discipline

`continuous-light` may use the current clean branch or one ordinary feature
branch. A worktree and claim are required only when they isolate concurrent or
otherwise conflicting writes.

`continuous-coordinated` and `continuous-release` use scoped worktrees for
overlapping lanes:

```
git worktree add <repo>/worktrees/plan<N>-<slug> -b plan-<N>-<slug>
```

`worktrees/` must be in the repo's `.gitignore`. After a claimed lane is
verified:

1. Commit in the worktree
2. Merge to canonical branch (main)
3. Push
4. Record the `merged` disposition and close the claimed lane through the
   sanctioned `session-close` / `make worktree-remove` path
5. Confirm the worktree was removed and the local branch was safely deleted
6. Update the shared tracker
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
error = new information; same error = not new information), record the finding
in the active authority and move to the next highest-value unblocked slice. Do
not retry the same approach indefinitely.

At the earliest of three completed increments, roughly four hours of continuous
execution, twice the expected effort, user confusion about the deliverable, or
parallel demos replacing one integrated product, reassess strategy. State what
the user can newly do, whether stakeholder observation advanced, whether work
is converging on one cumulative product, how effort split among outcome,
enabling, and process work, and whether the next increment is still the shortest
path to the stable initiative example.

Continue when those answers support the strategy. Otherwise stop creating
successor plans and reset scope or sequencing around the initiative example,
even when each increment is green. This checkpoint occurs in conversation or
the existing state authority; it is not a new report, approval gate, or stop
condition. A commit, green process test, new schema, refreshed manifest, or
policy artifact is enabling evidence rather than strategic progress by itself.

After the strategy decision, reconcile only roadmap-facing documentation whose
authority or status changed or whose duplication can misdirect the next action.
Use `keep`, `update`, `consolidate`, `archive`, or `delete`; preserve one current
authority, extract live claims and redirect active references before archival,
and delete only demonstrably dead material. Do not turn the checkpoint into a
broad cleanup phase or create a cleanup artifact solely to record that no change
was needed.

---

## Blocked Tasks

A blocked individual task is not a stop condition. When a task is blocked:
1. Record the blocker precisely in the active authority
2. Move to the next highest-value unblocked slice
3. Keep executing until there is no safe high-value unblocked work remaining

Only stop when every remaining action in the authorized run is blocked by the
same gap that qualifies as stop condition #2, or bounded investigation confirms
stop condition #3.

---

## End of Run

A continuous run ends when its authorized outcome criteria are satisfied or a
legitimate stop condition applies. Do not extend the run by inventing another
process phase.

For `continuous-light`, commit and push verified work and state the bounded
result, remaining gaps, and exact next behavior.

For `continuous-coordinated` or `continuous-release`:

1. Mark the shared tracker complete for the authorized scope
2. Push affected repositories
3. Clean finished worktrees and release claims
4. Record any next authorized outcome without automatically starting it

---

## What Each Legitimate Stop Condition Requires

When a stop condition IS reached:
1. Update the active authority with current state
2. Commit all verified work
3. Push
4. Leave precise notes only when another session must resume
5. Record the owner or blocker and exact resume event
6. Release or narrow claims that no longer authorize active work

---

## References

- `PLANNING_OPERATING_MODEL.md` — artifact dependency graph and planning hierarchy
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — claims, lanes, and worktree lifecycle
- ADR-0010 — agent_memory as required planning input
