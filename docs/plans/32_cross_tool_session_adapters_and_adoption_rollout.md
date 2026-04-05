# Plan #32: Cross-Tool Session Adapters And Adoption Rollout

**Status:** 📋 Planned
**Type:** implementation
**Priority:** High
**Blocked By:** Plans #29, #30, and #31
**Blocks:** practical multi-tool adoption of the session model

## Gap

The coordination/session model only solves real cross-project use once the same
contract works for Codex, Claude Code, and future runtimes without bespoke repo
logic.

## Desired Outcome

The framework ships adapter-backed session resolution and heartbeat/bootstrap
behavior for at least Codex and Claude Code, with a portable extension surface
for additional agents.

## Decisions Pre-Made

- Agent-specific identity resolution stays in adapters; the claim schema stays tool-agnostic.
- Codex and Claude Code are the first required adapters.
- OpenClaw or future agents can adopt the same interface without changing the
  core session contract.

## Acceptance Criteria

1. Codex and Claude Code session adapters are documented and tested.
2. Installer/operator docs explain the cross-tool contract.
3. Adoption rollout order across governed repos is explicit.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_session_cli.py` | Codex/Claude Code session adapter behavior is correct |

