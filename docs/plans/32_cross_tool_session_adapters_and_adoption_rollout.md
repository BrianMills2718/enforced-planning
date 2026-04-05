# Plan #32: Cross-Tool Session Adapters And Adoption Rollout

**Status:** ✅ Complete
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

## Files Expected

- `enforced_planning/session_contracts.py`
- `enforced_planning/coordination_claims.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `README.md`
- `GETTING_STARTED.md`
- `docs/reference/CONFIG_REFERENCE.md`
- `tests/test_check_coordination_claims.py`
- `tests/test_session_cli.py`

## Decisions Pre-Made

- Agent-specific identity resolution stays in adapters; the claim schema stays tool-agnostic.
- Codex and Claude Code are the first required adapters.
- OpenClaw or future agents can adopt the same interface without changing the
  core session contract.
- Runtime adapters may differ in how they discover `session_id`, but they must
  all produce the same claim and tracker contract.
- Adoption rollout order is framework source repo first, then governed repos
  that already use sanctioned worktree entrypoints.
- Docs must explain both the common contract and the tool-specific identity
  discovery points.

## Acceptance Criteria

1. Codex and Claude Code session adapters are documented and tested.
2. Installer/operator docs explain the cross-tool contract.
3. Adoption rollout order across governed repos is explicit.
4. The common contract does not require tool-specific fields on the claim.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_session_cli.py` | Codex/Claude Code session adapter behavior is correct |
| `python scripts/self_test.py --docs` | README, quickstart, and operator docs stay coherent after adapter rollout |

## Completion

- [x] Codex and Claude Code session adapters are documented and tested
- [x] Installer/operator docs explain the cross-tool contract
- [x] Adoption rollout order across governed repos is explicit
- [x] The common contract stays tool-agnostic

## Verification

- `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_session_cli.py`
