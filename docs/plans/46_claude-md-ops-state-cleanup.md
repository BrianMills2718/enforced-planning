# Plan #46: CLAUDE.md Ops-State Cleanup

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** `enforced-planning/CLAUDE.md` has two problems identified in the 2026-04-05 doc review:
1. Lines 14-16 embed a sprint-specific execution order ("Plan #43 → Plan #44 → Plan #35 is mandatory"). Sprint execution order is operational state that belongs in the sprint tracker, not in CLAUDE.md which is canonical framework guidance. This will rot as soon as the sprint ends.
2. The Canonical Surfaces list includes `docs/ops/SPRINT_2026_04_05_COORDINATION_NEXT_CHAIN.md`, but the Notes section says "Historical sprint notes under docs/ops/ are evidence artifacts, not the active planning queue." The same file calls the sprint doc both canonical AND an evidence artifact — a direct contradiction.

**Target:** CLAUDE.md has no sprint-specific execution order. The sprint doc is either not listed in Canonical Surfaces OR its listing is clearly labeled as an active-tracker exception (not a permanent canonical surface).

**Why:** Agents read CLAUDE.md on every session. Sprint ops state in CLAUDE.md misleads agents about what's active long after the sprint is done. The contradiction creates ambiguity about doc authority.

---

## References Reviewed

- `CLAUDE.md` lines 13-16 (sprint execution order), lines 71-78 (Canonical Surfaces list), lines 147-152 (Notes)
- `docs/ops/SPRINT_2026_04_05_COORDINATION_NEXT_CHAIN.md` — the referenced sprint doc

---

## Research Basis For This Slice

No additional research needed. This is a direct cleanup of identified contradictions.

---

## Plan

### Steps

1. Remove lines 13-17 (the Continuous Execution Contract sprint-order paragraph that specifies Plan #43 → Plan #44 → Plan #35). Keep the rest of the Continuous Execution Contract — the general rules remain valid.
2. Remove `docs/ops/SPRINT_2026_04_05_COORDINATION_NEXT_CHAIN.md` from Canonical Surfaces list. Sprint tracker references belong in the active plan, not in the permanent CLAUDE.md.

---

## Required Tests

`python scripts/self_test.py` must pass.

## Acceptance Criteria

- [ ] No sprint-specific plan execution order in CLAUDE.md
- [ ] No sprint tracker doc listed in Canonical Surfaces (or clearly labeled as temporary active tracker)
- [ ] Notes section and Canonical Surfaces section are no longer contradictory
- [ ] `self_test.py` passes
