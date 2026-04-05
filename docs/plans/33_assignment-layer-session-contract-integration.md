# Plan #33: Assignment-Layer Session Contract Integration

**Status:** 📋 Planned
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #32
**Blocks:** truthful assignment routing in `ecosystem-ops` and any other coordination consumers

## Gap

`ecosystem-ops/assignment_manager.py` currently treats assignment identity as a
repo-local concern and uses a hardcoded `"claude-code"` fallback. That makes
multiple windows or multiple tools collide on the same assignment slot.

The session/claim model already exists in `enforced-planning`. The assignment
layer is now behind the architecture, not ahead of it.

## Desired Outcome

The assignment layer becomes a consumer of canonical session identity instead
of a parallel identity source.

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Immediate fix | Do not add a global `current_session_id` file | It would be another racing mutable truth surface |
| Identity source | Reuse the same runtime adapter logic used by claim/session lifecycle | One identity model across tools |
| Assignment scope | Assignment files may remain a routing surface for now | Lower-risk adoption slice than full queue replacement |
| Assignment key | Key assignment lookup by resolved session identity or broader-goal session contract, not raw `"claude-code"` | Avoid multi-window collisions |
| Architecture boundary | `ecosystem-ops` consumes the session model; it does not define coordination identity | Keeps shared infra canonical |

## Files Expected

- `ecosystem-ops/assignment_manager.py`
- `ecosystem-ops` tests for assignment lookup / hook inject behavior
- `enforced-planning/docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md`
- `enforced-planning/docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`

## Acceptance Criteria

1. `assignment_manager.py` no longer relies on hardcoded `"claude-code"` as
   coordination identity.
2. The current runtime session can be resolved automatically for Codex and
   Claude Code without a human-exported `AGENT_INSTANCE` requirement.
3. Assignment routing consumes canonical session identity rather than inventing
   a second mutable session registry.
4. The architecture docs explicitly say assignment is a consumer layer, not a
   source-of-truth layer.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/...assignment...` in `ecosystem-ops` | Assignment routing is keyed by canonical session identity |
| `python scripts/self_test.py --docs` in `enforced-planning` | Shared architecture/docs remain coherent |

## Risks

- `ecosystem-ops` may have local dirt or adjacent ongoing work; execute in a
  dedicated worktree and avoid unrelated files.
- If assignment semantics are overloaded between “who is this session?” and
  “what should it work on next?”, that ambiguity should be documented rather
  than papered over.
