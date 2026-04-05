# Plan #47: Phase 9 Roadmap Definition

**Status:** Complete
**Type:** design
**Priority:** Medium
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** enforced-planning ROADMAP.md has no Phase 9. After Plans #43, #44, and #35 complete, the "What's Next" section lists them plus four more bullets without naming a phase. This creates ambiguity about whether the framework enters maintenance mode or has a defined next phase.

**Target:** ROADMAP.md has a clear Phase 9 section. The framework's strategic direction after the coordination runtime surface is complete is explicitly stated — either "maintenance mode with named conditions for promotion" or "Phase 9: Fleet Adoption" with defined gates.

**Why:** Agents generating new work in enforced-planning will invent tasks unless the roadmap explicitly defines what comes next. "What's Next" without a phase label implies unlimited scope.

---

## References Reviewed

- `ROADMAP.md` — current Phase 8 + "What's Next" section
- `docs/backlog/DEFERRED_FEATURES.md` — visibility grammar, distributed governance (both deferred)
- `docs/plans/CLAUDE.md` — Plans #43 (in progress), #44 (planned), #35 (planned)
- 2026-04-05 doc review finding: "The framework is fully operational but there's no declared endpoint"

---

## Research Basis For This Slice

No external research needed. This is a strategic framing decision based on current state.

Pre-made decision: Phase 9 = "Fleet Adoption + Maintenance" (not a new capability phase). Rationale: the capability set is complete; the work remaining is adoption rollout (Mac mini pilot, multi-tool support, upgrade automation) and self-measurement. No new framework primitives are needed.

---

## Plan

### Steps

1. Add "Phase 9: Fleet Adoption and Framework Maintenance" section to ROADMAP.md with:
   - Gate: Plans #43, #44, #35 all complete
   - Items: Mac mini pilot execution, upgrade automation rollout, multi-tool adoption (Cursor/Windsurf when documented), ecosystem status renderer
   - Explicit note: no new framework primitives planned in Phase 9; deferred features remain in backlog with documented trigger conditions
2. Update "What's Next" section to reference Phase 9 items explicitly
3. Update deferred items table to clarify these become Phase 9 items vs. still-deferred

---

## Required Tests

`python scripts/self_test.py` must pass.

## Acceptance Criteria

- [ ] ROADMAP.md has a Phase 9 section with clear gate condition and items
- [ ] The "What's Next" recommendations map to Phase 9 explicitly
- [ ] Deferred vs. Phase 9 items are clearly distinguished
- [ ] `self_test.py` passes
