# Plan #30: Session Bootstrap Contract And Tracker

**Status:** ✅ Complete
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

## Files Affected

- `CLAUDE.md`
- `ROADMAP.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/30_session_bootstrap_contract_and_tracker.md`
- `docs/plans/31_session_cli_and_governed_repo_entrypoint_enforcement.md`
- `docs/plans/32_cross_tool_session_adapters_and_adoption_rollout.md`
- `docs/plans/CLAUDE.md`
- `enforced_planning/coordination_claims.py`
- `enforced_planning/active_work_registry.py`
- `enforced_planning/session_contracts.py`
- `tests/test_session_contracts.py`

## Decisions Pre-Made

- Do not create a second competing coordination registry.
- The claim remains canonical for coordination-critical fields.
- The tracker is a linked per-session artifact for verbose intent/progress.
- Session naming follows the broader goal, not the local subtask.
- Compact session metadata belongs on the claim as `repo_root`,
  `session_name`, `broader_goal`, and `tracker_path`.
- Tracker artifacts should render nested `claim` and `tracker` sections so the
  split is machine-readable and human-readable in one file.
- Session tracker artifacts live under `~/.claude/coordination/sessions/` by
  default, not in the governed repo worktree.

## Acceptance Criteria

1. A formal session contract schema exists.
2. The schema distinguishes claim fields from tracker-only fields.
3. A generated or template-backed tracker artifact exists for session start.
4. The broader-goal naming rule is explicit and testable.
5. The canonical claim model can preserve the compact session metadata without
   creating a second registry.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_session_contracts.py tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py` | Session contract schema, tracker generation, and compatibility with the claim/registry surfaces behave correctly |
| `python scripts/self_test.py --docs` | The updated operator and plan docs remain coherent |
| `python scripts/check_markdown_links.py CLAUDE.md ROADMAP.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/plans/CLAUDE.md docs/plans/30_session_bootstrap_contract_and_tracker.md docs/plans/31_session_cli_and_governed_repo_entrypoint_enforcement.md docs/plans/32_cross_tool_session_adapters_and_adoption_rollout.md` | Touched docs and plans link cleanly |

## Completion

- [x] A formal session contract schema exists
- [x] Claim fields and tracker-only fields are explicitly separated
- [x] A generated tracker artifact exists
- [x] Broader-goal naming is explicit and testable
- [x] Compact session metadata can ride on the canonical claim model

## Verification

- `PYTHONPATH=. pytest -q tests/test_session_contracts.py tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py`
