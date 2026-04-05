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

The queue layer is future-facing.

It should answer:

- what work is available
- what priority order applies
- what preconditions must be true before claiming the next item

The queue may produce assignments, but it should still route work into the same
claim/session lifecycle.

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
