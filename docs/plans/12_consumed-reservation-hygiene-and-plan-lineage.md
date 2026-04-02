# Plan #12: Consumed Reservation Hygiene and Plan Lineage

**Status:** ✅ Complete
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

## Policy Decisions

1. Consumed reservations remain immutable lineage records. They must not be silently deleted.
2. Consumed reservations are split conceptually into two lifecycle states:
   - `landed`: the reserved work consumed a plan number and landed into canonical repo history
   - `historical-unlanded`: the reserved work consumed a plan number in a temporary/proof/worktree path but did not land into canonical repo history
3. When consumed work lands canonically, lineage should point at canonical repo truth. The authoritative `plan_file` should be rewritten or canonicalized to the canonical repo plan path rather than left pointing at a temporary worktree path.
4. When a temporary or proof worktree is removed before canonical landing, the reservation should not keep pretending it points at a live plan file. It should be moved into an explicit `historical-unlanded` state or equivalent archival representation.
5. Repo-local truth-surface checks should not fail hard on `historical-unlanded` lineage by default. That state should appear as a separate hygiene/history category or warning class rather than as an ordinary local runtime failure.
6. Repo-local truth-surface checks should fail hard when lineage claims a canonical landed state but the canonical plan file is missing or contradictory.
7. Consumed plan numbers are not reusable within the canonical repo namespace. Temporary experimentation must use a separate proof/temporary mechanism rather than reusing a consumed canonical plan number.
8. Worktree removal/cleanup must require explicit lineage resolution: canonicalize to landed history, archive as `historical-unlanded`, or block cleanup until one of those outcomes is chosen.
9. Deterministic promotions from semantic findings are blocked until the implementation distinguishes landed lineage from historical-unlanded lineage.

---

## Monitoring Concerns And Uncertainties

These do not block the policy decision, but they must be monitored in the implementation slice:

1. Canonicalization may be lossy if the framework cannot reliably determine which canonical plan file corresponds to an older worktree-local consumed reservation.
2. Some repos may already contain historical consumed reservations that refer to proof branches or transient worktrees with no canonical successor. The migration path for those records must be explicit and auditable.
3. Disallowing consumed-number reuse is the cleanest lineage policy, but it may increase pressure on plan-number allocation in repos that currently create many disposable proof branches.
4. Repo-local operators may still want optional visibility into `historical-unlanded` records during deep diagnostics even if those records are not part of the default hard-fail view.
5. Cleanup tooling must not make it easy to misclassify landed work as `historical-unlanded` just to silence warnings.
6. The distinction between registry-hygiene warnings and repo-local runtime failures must stay obvious in rendered status surfaces so operators do not underreact to true canonical-landed contradictions.

## Implementation Follow-On Shape

The next implementation slice should:
- add explicit lineage state for consumed reservations or the minimal equivalent representation needed to distinguish landed from historical-unlanded history
- add canonicalization on landing
- add cleanup-path enforcement for temporary/proof worktrees
- update repo-local rendering so historical-unlanded lineage appears separately from hard local failures
- add migration or audit handling for pre-existing stale consumed reservations

---

## Acceptance Criteria

- [x] The framework documents one unambiguous consumed-reservation lifecycle policy.
- [x] The framework documents whether plan-number reuse is legal after consumed historical reservations.
- [x] The framework documents whether repo-local truth-surface validation should treat missing historical consumed reservation paths as local failures, downgraded hygiene warnings, or a separate category.
- [x] The next implementation slice can proceed without reopening the same lineage questions.

---

## Notes

- The prompt-eval pilot already delivered the measured evidence needed for this plan.
- The core policy is now decided. Remaining uncertainty is in migration, rollout ergonomics, and how to represent lineage state most cleanly in the shared runtime registry.
