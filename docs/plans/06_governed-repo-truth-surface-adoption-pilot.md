# Plan #6: Governed Repo Truth-Surface Adoption Pilot

**Status:** Planned
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** default workflow wiring beyond advisory mode

---

## Gap

**Current:** `enforced-planning` now has a portable truth-surface validator and renderer, but no governed repo has yet adopted them through a real repo-local config and measured rollout surface. The framework guidance is still proven only inside the framework repo itself.

**Target:** Run one bounded pilot adoption in a governed repo with a real tracker, real plan index, real registry state, and real measured audit output. Use the result to decide whether truth-surface validation should remain advisory or move toward default wiring in closeout workflows.

**Why:** Portable framework code is not enough. A coordination safeguard becomes real only after at least one governed repo consumes it truthfully and the resulting friction/benefit is measured.

---

## References Reviewed

- `docs/plans/04_truth-surface-drift-validation-and-enforcement.md`
- `docs/plans/05_truth-surface-validator-completion-sprint.md`
- `PLANNING_OPERATING_MODEL.md`
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md`
- `templates/truth_surface_drift.yaml.example`
- `scripts/check_truth_surface_drift.py`
- `scripts/render_truth_surface_status.py`

---

## Files Affected

- pilot repo plan/docs/config surfaces (repo-local)
- `enforced-planning` docs only if adoption findings change framework guidance

---

## Plan

### Steps

1. Choose one governed repo with live tracker + registry + audit surfaces.
2. Create a repo-local truth-surface config from the template.
3. Run validator and renderer against real surfaces.
4. Record friction, false positives, and missing invariants.
5. Update framework guidance only from measured pilot evidence.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| repo-local | pilot-specific | The chosen repo's config catches at least one real or simulated drift case |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | Framework must remain internally consistent |
| repo-local validation run | The pilot must prove real consumption, not just framework tests |

---

## Acceptance Criteria

- [ ] One governed repo consumes the validator and renderer through a real repo-local config.
- [ ] At least one real or intentionally simulated drift case is detected in that repo.
- [ ] The pilot documents whether default workflow wiring should stay advisory or tighten.

---

## Open Questions

- [ ] Which governed repo is the best first pilot: `project-meta`, another coordination-heavy repo, or a smaller clean candidate?
- [ ] Should the first pilot target an already-known drift case or a cleaner repo to establish baseline ergonomics first?
