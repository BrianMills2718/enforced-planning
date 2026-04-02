# Plan #8: Truth-Surface Adoption Pilot Execution Sprint

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** 6, 7, default workflow wiring beyond advisory mode

---

## Gap

**Current:** The framework now has a deterministic truth-surface validator,
renderer, and a planned governed-repo pilot, but there is no active sprint
contract for executing that pilot continuously. The framework also lacks a
measured decision about whether the first repo-local adoption should stay purely
advisory, what drift classes remain outside deterministic coverage, and how the
pilot should feed the later LLM semantic-review layer.

**Target:** Complete the first governed-repo truth-surface adoption pilot in one
clean, actually governed repo; record real friction and drift findings; close
Plan #6 truthfully; and leave a precise measured handoff into Plan #7.

**Why:** A portable framework is still hypothetical until a real governed repo
consumes it under live coordination conditions. This sprint exists to make the
next 24 hours of work explicit, bounded, and continuous rather than relying on
implicit next steps.

---

## References Reviewed

- `CLAUDE.md`
- `PLANNING_OPERATING_MODEL.md`
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md`
- `docs/plans/06_governed-repo-truth-surface-adoption-pilot.md`
- `docs/plans/07_llm-semantic-truth-surface-review.md`
- `templates/truth_surface_drift.yaml.example`
- `scripts/check_truth_surface_drift.py`
- `scripts/render_truth_surface_status.py`
- `~/projects/project-meta/scripts/meta/audit_governed_repo.py`
- `~/projects/prompt_eval/CLAUDE.md`
- `~/projects/prompt_eval/docs/plans/CLAUDE.md`
- `~/projects/prompt_eval/meta-process.yaml`

---

## Files Affected

- `CLAUDE.md`
- `docs/plans/CLAUDE.md`
- `docs/plans/08_truth-surface-adoption-pilot-execution-sprint.md`
- `docs/ops/OVERNIGHT_SPRINT_2026_04_02_PILOT.md`
- `docs/ops/TRUTH_SURFACE_PILOT_TODO.md`
- pilot repo-local plan/config/docs in the chosen governed repo
- framework docs only if pilot evidence changes guidance

---

## Plan

### Phase A — Sprint Contract and Pilot Target Freeze

Success criteria:
- One active sprint tracker exists and is referenced by root `CLAUDE.md`.
- The chosen pilot repo is justified from measured repo state, not assumption.
- Uncertainties about target-repo cleanliness or active claims are recorded.

### Phase B — Repo-Local Pilot Plan and Config

Success criteria:
- The pilot repo has a bounded local plan for truth-surface adoption.
- A repo-local `truth_surface_drift.yaml` is created from the framework template.
- The configured truth surfaces are real repo-local files plus live runtime data.

### Phase C — Measured Validation and Drift Detection

Success criteria:
- The validator and renderer run successfully in the pilot repo.
- At least one real or intentionally simulated drift case is detected.
- The pilot produces a concrete status surface and a categorized findings list.

### Phase D — Framework Feedback and Next-Step Hardening

Success criteria:
- Plan #6 is updated truthfully from measured pilot evidence.
- The sprint tracker records whether default wiring should remain advisory.
- A precise handoff into Plan #7 is documented, including which semantic drift
  findings still need LLM/agent review.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| pilot repo-local | pilot-specific config test | Repo-local truth-surface config catches at least one known contradiction |
| pilot repo-local | renderer status test | Pilot status rendering is deterministic and usable as a live surface |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | Framework must remain internally consistent |
| repo-local validator run | Proves real consumption in the pilot repo |
| repo-local renderer run | Proves a generated current-state surface exists |

---

## Acceptance Criteria

- [x] Root `CLAUDE.md` points to one active sprint tracker for this work.
- [x] The pilot repo is chosen from measured conditions and documented.
- [x] The chosen repo consumes the validator and renderer through a real repo-local config.
- [x] At least one real or intentionally simulated drift case is detected.
- [x] Plan #6 is updated with measured findings and default-wiring guidance.
- [x] The sprint leaves a categorized semantic-drift backlog for Plan #7.

---

## Open Questions

- [x] Should the first pilot prefer the cleanest governed repo or the most coordination-heavy governed repo when those differ?
      - Resolved during Plan #8 / Plan #6: clean governed repo first (`prompt_eval`) so framework ergonomics are measurable before coordination-heavy noise dominates.
- [x] Does a canonical-root `!! ACTIVE (no claim)` warning in the target repo require a pilot blocker, or is a claimed clean worktree sufficient for the first slice?
      - Resolved during Plan #8: a claimed clean worktree was sufficient for the first pilot slice.
- [x] Which pilot findings are strong enough to justify default workflow wiring before any semantic LLM layer exists?
      - Resolved by Plan #9: scoped repo-local validation is now the right default operator view, while broader default workflow wiring beyond advisory mode still remains a separate follow-on decision.
