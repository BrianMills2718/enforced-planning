# Plan #30: Session Bootstrap Contract And Tracker

**Status:** 📋 Planned
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #29
**Blocks:** truthful session intent, broader-goal naming, and restart-safe progress tracking across governed repos

## Gap

Claims are becoming good at ownership and liveness, but they still do not
capture the full session contract a human or another agent needs at startup:
broader goal, active plan trajectory, current phase, and intended next phases.

## Desired Outcome

A sanctioned session bootstrap creates one canonical runtime claim plus one
linked human-readable session tracker artifact. The claim stays the source of
truth for coordination-critical metadata; the tracker holds richer evolving
execution context.

## Decisions Pre-Made

- Do not create a second competing coordination registry.
- The claim remains canonical for coordination-critical fields.
- The tracker is a linked per-session artifact for verbose intent/progress.
- Session naming follows the broader goal, not the local subtask.

## Acceptance Criteria

1. A formal session contract schema exists.
2. The schema distinguishes claim fields from tracker-only fields.
3. A generated or template-backed tracker artifact exists for session start.
4. The broader-goal naming rule is explicit and testable.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_session_contract.py` | Session contract schema and tracker generation behave correctly |

