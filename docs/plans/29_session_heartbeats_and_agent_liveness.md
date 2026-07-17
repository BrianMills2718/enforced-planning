# Plan #29: Session Heartbeats And Agent Liveness

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** truthful distinction between live agent-owned lanes and abandoned-but-not-yet-stale lane claims

---

## Gap

The coordination stack now knows claim identity (`agent`, `session_id`) and
lifecycle truth (`missing_worktree_on_disk`, `missing_branch_ref`,
`branch_merged_to_default`), but it still cannot answer a more basic question:
is the owning session still alive?

That gap shows up in lanes like `project-meta:lane-lifecycle-automation`:

- the claim exists
- the worktree exists
- the branch exists
- but there is no session liveness signal beyond timestamps and manual judgment

Without a heartbeat-backed lease model, the registry can tell “missing metadata”
and “mechanically stale lifecycle,” but not “session probably dead.”

## Desired Outcome

The canonical claim model should support session heartbeats so the registry can
distinguish:

- `healthy`: ownership metadata present and heartbeat fresh
- `weak`: missing required ownership metadata
- `stale`: lifecycle truth is broken or session heartbeat is stale
- compatibility legacy: older claims with no heartbeat data remain readable
  without being auto-classified as stale

---

## Research

- `enforced_planning/coordination_claims.py`
- `enforced_planning/active_work_registry.py`
- `scripts/check_coordination_claims.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_generate_active_work_registry.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- live registry output from `python scripts/generate_active_work_registry.py --stdout-json`
- live legacy weak claim: `~/.claude/coordination/claims/codex_lane-lifecycle-automation.yaml`

---

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Heartbeat field | Add `heartbeat_at` to claim-v2 | Keeps liveness explicit instead of overloading `updated_at` |
| Refresh path | Add explicit `--heartbeat` to the canonical claim CLI | Bounded, observable, and tool-agnostic |
| Session resolution | Reuse the existing runtime session resolution for Codex, Claude Code, and OpenClaw | Same adapter surface, no second identity system |
| Backward compatibility | Missing heartbeat alone makes a legacy live claim weak/uninstrumented, not stale or healthy | Keeps legacy claims readable without translating missing liveness evidence into success |
| Stale-session rule | A live claim becomes stale when `heartbeat_at` exists and is older than the configured freshness window | Distinguishes “no liveness instrumented yet” from “instrumented and stale” |
| Threshold config | Use an environment-configurable stale window, defaulting in the framework code | Keeps the first rollout deterministic while avoiding hardwired semantics |

---

## Files Affected

- `ROADMAP.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/29_session_heartbeats_and_agent_liveness.md`
- `docs/plans/CLAUDE.md`
- `enforced_planning/coordination_claims.py`
- `enforced_planning/active_work_registry.py`
- `scripts/check_coordination_claims.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_generate_active_work_registry.py`

---

## Acceptance Criteria

1. Claim-v2 supports `heartbeat_at` in normalized records and persisted YAML.
2. New claims created through the canonical surface stamp `heartbeat_at` at
   creation time.
3. The canonical CLI provides `--heartbeat` to refresh matching live claims for
   the current session and can backfill `session_id` for matching claims when it
   is missing.
4. The registry exposes heartbeat-backed liveness issues distinctly from
   lifecycle issues and can classify stale-session claims as `stale`.
5. Focused tests cover:
   - new-claim heartbeat stamping
   - heartbeat refresh for Codex
   - heartbeat refresh for Claude Code
   - stale-session classification from an old heartbeat
   - registry rendering of stale-session claims
6. Operator docs explain what heartbeats mean and how Codex/Claude Code lanes
   should refresh them.

---

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py` | Heartbeat refresh and stale-session registry classification work correctly |
| `python scripts/self_test.py --docs` | Touched docs and plans stay coherent |
| `python scripts/check_markdown_links.py ROADMAP.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/plans/CLAUDE.md docs/plans/29_session_heartbeats_and_agent_liveness.md` | Touched docs link cleanly |

## Completion

- [x] Claim-v2 supports `heartbeat_at`
- [x] `--heartbeat` refresh exists in the canonical CLI
- [x] Registry distinguishes stale-session from legacy no-heartbeat claims
- [x] Focused coordination tests pass
- [x] Operator docs explain the liveness model

## 2026-07-17 Activity-Bound Repair

An observed legacy claim exposed a remaining integrity gap: the native Codex
hook ran on `SessionStart`, `UserPromptSubmit`, and `PostToolUse`, but only
polled the mailbox. It did not refresh the existing claim heartbeat. A legacy
claim with no heartbeat could consequently retain `status: active` and be
reported as healthy even though no native runtime matched its synthetic session
ID.

The bounded repair:

- refreshes heartbeat metadata from each native activity event before mailbox
  polling;
- requires an exact existing session match, so activity cannot adopt or revive
  a synthetic, missing, or different session identity;
- reports a live claim with no heartbeat as
  `weak`/`missing_session_heartbeat`, while keeping it readable and distinct
  from an instrumented stale session;
- preserves the separate meanings of reservation status, session liveness, and
  attributable progress evidence.

Investigation:
`../../investigations/2026-07-17-activity-heartbeat-gap.md`.

## Verification

- `PYTHONPATH=. pytest -q tests/test_check_coordination_claims.py tests/test_generate_active_work_registry.py`
- `python scripts/self_test.py --docs`
- `python scripts/validate_plan.py --plan-file docs/plans/29_session_heartbeats_and_agent_liveness.md --warn-only`
- `python scripts/check_markdown_links.py CLAUDE.md ROADMAP.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/plans/CLAUDE.md docs/plans/29_session_heartbeats_and_agent_liveness.md docs/plans/30_session_bootstrap_contract_and_tracker.md docs/plans/31_session_cli_and_governed_repo_entrypoint_enforcement.md docs/plans/32_cross_tool_session_adapters_and_adoption_rollout.md`
