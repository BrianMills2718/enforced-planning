# Plan #49: Canonical Continuous Execution Contract

**Status:** Complete
**Type:** implementation
**Priority:** Medium
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** The "never stop" execution contract and stop conditions are duplicated across 4 repos (enforced-planning, project-meta, ecosystem-ops, agent_memory) with divergent wording. The circuit-breaker rule appears in only 2 of the 4. Stop condition wording varies ("force push to origin" vs "affects shared state" vs "force push to shared remotes"). No canonical source exists. enforced-planning is the correct owner.

**Target:** `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md` exists as the canonical portable pattern. All four repos can reference it as their authority source.

**Why:** When the policy changes, it must currently be updated in 4 places. Divergent wording creates ambiguity about what the real boundaries are. A single canonical source eliminates both problems.

---

## References Reviewed

- `project-meta/CLAUDE.md` — 55-line NEVER STOP block (most detailed)
- `ecosystem-ops/CLAUDE.md` — similar block
- `agent_memory/CLAUDE.md` — table format variant
- `enforced-planning/CLAUDE.md` — "Continuous Execution Contract" section

---

## Plan

### Steps

1. Create `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md` with canonical content:
   - Core rule (never stop between phases)
   - Exactly two stop conditions (authoritative wording)
   - Commit discipline
   - Worktree discipline
   - Push discipline
   - Sprint contract requirement
   - Circuit breaker
   - Blocked task handling
   - Sprint end condition
2. Add Plan #49 to CLAUDE.md index

---

## Required Tests

`python scripts/self_test.py` must pass.

## Acceptance Criteria

- [x] `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md` exists
- [x] Contains exactly two stop conditions, authoritative wording
- [x] Contains circuit breaker rule
- [x] Contains worktree discipline and push discipline
- [x] `self_test.py` passes
