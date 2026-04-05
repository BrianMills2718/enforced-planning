# Plan #48: ADR-0010 Guide Propagation

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` declares `KNOWLEDGE.md ## Active Decisions` as the canonical surface for in-flight architectural decisions (lines 12–13, 312, 321). ADR-0010 (accepted 2026-04-05) formally deprecated this surface in favor of `agent_memory` with `store_decision()`. The guide had not been updated. Additionally, ROADMAP.md Phase 6 was labeled "GATE MET — READY TO START" when both active items are complete and the two remaining items are permanently deferred.

**Target:** All three KNOWLEDGE.md coordination references in the guide updated to `agent-memory recall`. Phase 6 labeled COMPLETE.

**Why:** The WORKTREE_COORDINATION_OPERATOR_GUIDE.md is the active operator document agents read during coordination setup. An agent following the stale guide will write to a frozen file — the exact failure mode ADR-0010 was written to prevent. This is the highest-blast-radius ADR-0010 follow-through gap.

---

## References Reviewed

- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — lines 12–13, 312, 321
- `adr/0010-agent-memory-as-planning-input.md` — Decision #3: `## Active Decisions` deprecated
- `ROADMAP.md` — Phase 6 label

---

## Plan

### Steps

1. Update lines 12–13: replace `KNOWLEDGE.md ## Active Decisions` with `agent-memory recall 'active decisions' --project {project}` and note ADR-0010
2. Update line 312: replace `KNOWLEDGE.md` with `agent_memory`
3. Update line 321: replace `KNOWLEDGE.md` with `agent_memory`
4. Update ROADMAP.md Phase 6: "GATE MET — READY TO START" → "COMPLETE — 2 items permanently deferred"

---

## Required Tests

`python scripts/self_test.py` must pass.

## Acceptance Criteria

- [x] No KNOWLEDGE.md coordination references in WORKTREE_COORDINATION_OPERATOR_GUIDE.md
- [x] `agent-memory recall 'active decisions'` is the stated canonical surface
- [x] ROADMAP.md Phase 6 reads COMPLETE
- [x] `self_test.py` passes
