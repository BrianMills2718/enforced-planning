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

## Explicit Anti-Patterns

These are rejected architectural directions:

- a single global `~/.claude/current_session_id` file
- tool-specific mutable identity registries parallel to claims
- per-window assignment files used as session truth
- queue systems that bypass claim creation and session bootstrap

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

## Target Rule

Identity is resolved once, in the canonical coordination/session layer.

Everything else:

- reads it
- routes on top of it
- or renders operator views from it

Nothing else gets to define “who am I?” for coordination.
