# Coordination Runtime Target Architecture

## Purpose

This document freezes the intended steady-state architecture for cross-project
agent coordination after Plans 24-32.

The immediate goal is to stop coordination work from fragmenting into multiple
parallel identity systems. The claim/session lifecycle now exists. Adoption
work must consume it rather than reinvent it.

## Canonical Runtime Layers

### 1. Claim Layer

Claims are the canonical mutable coordination record.

They answer:

- who owns a lane
- which project / scope / branch / worktree is in play
- what write surface is reserved
- what runtime session owns the lane
- whether the lane is live, weak, or stale

Claims are the only mutable coordination surface that other systems may depend
on for ownership truth.

### 2. Session Layer

Session state is split across:

- compact claim-side metadata
- one linked tracker artifact

The session layer answers:

- what broader objective this runtime is pursuing
- what phase it is in
- what next phases are intended
- what stop conditions or handoff notes matter

Important rule: the session layer extends the claim model. It does not create a
second competing registry.

Every live session must be explicitly plan-bound. A runtime session is not just
"some shell in some worktree." It must declare:

- project
- plan reference
- bounded scope
- branch
- worktree path
- broader goal

That rule is what makes resume, recovery, and duplicate-lane detection
mechanically meaningful.

### 3. Lane Layer

Lanes are derived from live claims.

They are the operator-facing abstraction:

- one project
- one bounded mission
- one branch/worktree
- one plan or bounded sprint

Lanes are not hand-authored. They are rendered from claims.

### 4. Assignment Layer

Assignments are optional higher-level routing state for humans or queueing
systems. They are not session identity and they are not lane truth.

Assignments may answer:

- which project or category a session should work on next
- what queued item is available
- whether an agent instance should be blocked until it claims work

Assignments must consume canonical session identity from the claim/session
layer. They must not invent their own per-window identity file or overwrite a
global singleton session marker.

### 5. Queue Layer

The queue layer is future-facing. It sits *above* assignments, not below claims.

It answers:

- what work is available and has not been claimed
- what priority order applies at this moment
- what preconditions must be satisfied before a session may claim the next item

The queue may produce assignments, but it must route work into the same
claim/session lifecycle. Queue dispatch is not session identity.

#### Layer Boundaries (explicit)

| Layer | What it owns | What it does not own |
|-------|-------------|---------------------|
| Queue | Available work items, priority order, preconditions | Session identity, lane state, worktree paths |
| Assignment | Routing hints for which project/category to work on | Ownership — an assignment file does not mean a claim exists |
| Claim | Who owns what scope right now | Queue state — the queue does not read from claims directly |
| Session | Current objective, phase, stop conditions | Queue membership — sessions are not automatically re-queued |
| Lane | Derived operator view of a live claim | Queue position — lanes do not imply queue advancement |

The single most important rule: **queue dispatch ends in `session-start` + claim creation**. If the queue routed a session to work but no claim was created, the routing is not enforceable. The claim is the proof of ownership; the queue is the source of the next item to claim.

#### Precondition Semantics

Before a session may claim a queue item, the queue layer should verify:

1. No live claim already exists for the same `project + scope + plan_ref` combination
2. The item's declared blockers are either resolved or explicitly bypassed
3. If human override is in effect, the override is recorded (not silently applied)

#### Human Override Rule

Human-assigned routing may coexist with queue dispatch, but the queue state
must remain inspectable and bounded. If a human explicitly assigns a session to
out-of-order work, that assignment must still produce a canonical claim. The
queue may be paused or bypassed, not superseded invisibly.

#### Queue Implementation Roadmap (follow-on)

This design is intentionally implementation-deferred. A concrete follow-on
program does not require reopening the architecture, because the boundaries are
now explicit. The follow-on steps are:

1. **Queue storage**: a flat YAML file (`~/.claude/coordination/queue.yaml`) per
   workspace, listing work items with `item_id`, `project`, `plan_ref`, `priority`,
   `blockers`, and `status` (available/claimed/completed).

2. **Claim-on-start routing**: extend `session-start` to optionally accept
   `--queue-pop` which atomically: marks the next available item as claimed,
   creates the claim, and emits the session bootstrap context.

3. **Queue inspection**: `make queue-status` prints available/claimed/completed
   items with blockers, analogous to `make lane-list`.

4. **Human override integration**: an explicit `make queue-assign ITEM=N SESSION=X`
   command that records the override reason and still creates a canonical claim.

These steps do not change the claim/session/lane model — they add a structured
source of "what to claim next" on top of it.

## Recovery And Closeout Layer

Crash recovery and intentional stop/resume are lifecycle problems, not ad hoc
human conventions.

The canonical operational states are:

- `healthy`: live claim, truthful lifecycle, fresh heartbeat
- `handoff`: intentionally paused or transferred with explicit note
- `stale`: lifecycle or liveness facts show the claim is no longer truthful
- `completed`: cleanly finished and closed

The recovery rule is:

- a new runtime must explicitly resume an existing plan-bound lane
- it must not silently create a second active lane for the same
  `project + plan_ref + scope`
- stale lanes must be adjudicated as resumed, handed off, abandoned, or pruned

This keeps crash recovery in the canonical claim/session lifecycle instead of
leaving it to conversational memory.

## Authority Reconciliation Layer

Authoritative content and authoritative indexes are both truth surfaces, but
they do not have identical ownership rules.

The policy is:

- a lane may land authoritative artifacts in its claimed scope
- a lane may not opportunistically edit a separately claimed authority surface
- if that landing creates index or authority drift, the lane must record a
  formal reconciliation obligation
- the lane owning the affected authority surface may not close while such an
  obligation remains unresolved

This avoids silent overlap and also avoids silent drift.

## Startup Surfaces

Startup surfaces are the information shown to an agent or operator when a
session first opens. They must follow a strict ownership rule.

### Interactive vs Autonomous Session Types

**Interactive sessions** are human-driven (Claude Code interactive window,
Codex terminal, operator shell). They have no pre-assigned work at open time
and must not auto-adopt stale assignments.

**Autonomous sessions** are machine-driven (cron, overnight agent, pipeline).
They run against a pre-made plan and must be claim-bound before starting work.

### Startup Ownership Rule

A startup surface may display an assignment as *current* only if the current
session explicitly owns it via a claim. Specifically:

- For interactive sessions: if no claim exists for this session, show no
  current assignment. Do not surface a generic fallback file as if it were
  an active assignment.
- For autonomous sessions: the startup surface is the sprint tracker and the
  claim registry. A generic assignment file is not a sufficient routing signal
  for unattended execution.
- Other sessions' claims may be shown as *global context*, but must be labeled
  as such and never phrased as "your current work."

### Generic Fallback Files

Files like `claude-code.yaml` or `assignment.yaml` are compatibility-only
routing hints. They are not session identity. Do not promote them to startup
truth. If a repo still routes interactive sessions through a generic fallback
file, that is a coordination debt item — not a valid startup surface.

### Documented Failure Mode (2026-04-05)

A stale `claude-code.yaml` showing `theory-forge` as the current assignment
was displayed to a new interactive session that had never claimed that work.
Root cause: the startup brief used the generic fallback file as session truth.
Resolution: startup display must be claim-gated. Only session-owned claims
qualify as "current assignment."

## Explicit Anti-Patterns

These are rejected architectural directions:

- a single global `~/.claude/current_session_id` file
- tool-specific mutable identity registries parallel to claims
- per-window assignment files used as session truth
- queue systems that bypass claim creation and session bootstrap
- sessions with no explicit plan attachment
- closure gates that only warn on unresolved authority drift

Those all recreate the split-brain problem in a different file.

## Short-Term Program

### Plan 33

Adopt the canonical session contract in `ecosystem-ops/assignment_manager.py`
and other immediate consumers. Remove ad hoc identity assumptions like the
hardcoded `"claude-code"` fallback as routing truth.

### Plan 34

Repair live weak/stale claims in active repos using the sanctioned session
lifecycle tooling. The registry should become operationally trustworthy, not
just structurally richer.

### Plan 35

Design the longer-term queue-based assignment/routing system on top of the
claim/session model. Queue state may exist, but it must feed canonical session
bootstrap rather than replace it.

### Plan 37

Make plan attachment mandatory for live sessions and add explicit recovery
commands for resume, handoff, and abandon semantics after unclean exits.

### Plan 38

Add formal authority-drift reconciliation obligations and hard closeout gates
so claimed authority surfaces cannot close with unresolved downstream drift.

## Target Rule

Identity is resolved once, in the canonical coordination/session layer.

Lifecycle state is also resolved there:

- plan attachment is explicit
- resume/abandon/handoff are explicit
- authority drift is explicit and blocking at lane closeout

Everything else:

- reads it
- routes on top of it
- or renders operator views from it

Nothing else gets to define “who am I?” for coordination.
