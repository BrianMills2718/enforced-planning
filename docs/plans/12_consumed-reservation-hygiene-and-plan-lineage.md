# Plan #12: Consumed Reservation Hygiene and Plan Lineage

**Status:** 📋 Planned
**Type:** design
**Priority:** High
**Blocked By:** 6, 7, 9, 11
**Blocks:** deterministic promotion of prompt-eval pilot findings; safer plan allocation after deleted worktrees

---

## Gap

**Current:** The first real semantic pilot in `prompt_eval` exposed a deeper coordination problem than simple prose drift. Historical consumed reservations can continue pointing at deleted worktree plan files after the worktree is removed. Those stale reservations can then surface as local truth-surface failures, and in the prompt-eval case they also collided with a newly reused plan number, which made the semantic layer report misleading tracker summaries.

**Target:** Define and then implement one truthful hygiene model for consumed reservations and plan lineage so the framework can answer these questions deterministically:
- when a consumed reservation should still count as authoritative history
- when a missing worktree-local `plan_file` should be rewritten or canonicalized
- whether consumed reservations should block plan-number reuse
- which parts of that state should appear in repo-local operator views by default

**Why:** The prompt-eval pilot proved that semantic review can describe the symptom, but the root problem is still runtime coordination lineage. Without a clear policy here, any future deterministic promotion risks encoding the wrong invariant.

---

## References Reviewed

- `docs/plans/04_truth-surface-drift-validation-and-enforcement.md`
- `docs/plans/06_governed-repo-truth-surface-adoption-pilot.md`
- `docs/plans/07_llm-semantic-truth-surface-review.md`
- `docs/plans/09_scoped-truth-surface-validation.md`
- `docs/plans/11_semantic-truth-surface-review-execution-sprint.md`
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md`
- `install.sh`
- `~/projects/prompt_eval_worktrees/plan-16-semantic-truth-surface-pilot/docs/plans/15_semantic-truth-surface-review-pilot.md`
- `~/projects/prompt_eval_worktrees/plan-16-semantic-truth-surface-pilot/docs/ops/TRUTH_SURFACE_STATUS.md`
- `~/projects/prompt_eval_worktrees/plan-16-semantic-truth-surface-pilot/truth_surface_drift.yaml`
- `~/projects/prompt_eval_worktrees/plan-16-semantic-truth-surface-pilot/KNOWLEDGE.md`

---

## Files Affected

- `docs/plans/12_consumed-reservation-hygiene-and-plan-lineage.md`
- `docs/plans/CLAUDE.md`
- future runtime-coordination scripts and tests once the policy is decided

---

## Pre-Made Decisions

1. This plan starts as a design/policy slice, not immediate implementation.
2. The prompt-eval pilot evidence is sufficient to justify the plan; no further pilot repo is required before scoping the hygiene model.
3. Deterministic promotion of the semantic findings is blocked on this plan, because promotion without lineage policy could hard-code the wrong rule.
4. The first implementation slice after this plan should stay within shared coordination infrastructure, not consumer-repo code.

---

## Questions To Resolve

1. Should a consumed reservation with a missing worktree-local `plan_file` be:
   - kept as-is and treated as a hard failure,
   - rewritten to a canonical repo plan path when the canonical file exists,
   - or archived into a different historical state?
2. Should consumed reservations block reuse of the same plan number within the canonical repo namespace?
3. Should repo-local `check_coordination_claims.py --check` surface historical consumed reservations by default, or only active work plus an explicit historical mode?
4. What is the sanctioned cleanup path when a proof or temporary worktree is removed after consuming a reservation but before canonical landing?
5. Which of these invariants belong in deterministic truth-surface validation versus registry-hygiene tooling?

---

## Plan

### Phase A — Lineage Policy

Success criteria:
- one explicit policy exists for consumed reservation lifecycle
- plan-number reuse semantics are explicit
- canonicalization versus hard-failure semantics are explicit

### Phase B — Operator Surface Policy

Success criteria:
- the framework states what repo-local operators should see by default
- historical consumed reservations are either in or out of the default repo-local view intentionally, not accidentally

### Phase C — Implementation Slice Definition

Success criteria:
- one bounded follow-on implementation plan is ready
- it names the exact scripts/tests/docs to change and which uncertainties are already closed

---

## Acceptance Criteria

- [ ] The framework documents one unambiguous consumed-reservation lifecycle policy.
- [ ] The framework documents whether plan-number reuse is legal after consumed historical reservations.
- [ ] The framework documents whether repo-local truth-surface validation should treat missing historical consumed reservation paths as local failures, downgraded hygiene warnings, or a separate category.
- [ ] The next implementation slice can proceed without reopening the same lineage questions.

---

## Notes

- The prompt-eval pilot already delivered the measured evidence needed for this plan.
- The core uncertainty is policy, not code mechanics.
