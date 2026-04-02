# Plan #2: Canonical Planning Operating Model

**Status:** Complete
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** Plan #3, Plan #4

---

## Gap

**Current:** The planning methodology is documented across multiple patterns, the
plan template, `GETTING_STARTED.md`, and inherited `project-meta` docs. The
current hierarchy is useful but not canonical enough: capability/boundary work
appears after roadmap phases, TDD/gates are not placed clearly enough before
implementation, and agents must synthesize the operating model from several
places.

**Target:** `enforced-planning` has one canonical methodology document that
defines the planning operating model, the required dependency order between
artifacts, the role of TDD/tests/gates, the place of journey notebooks, and the
legacy-repo bootstrap sequence. Pattern docs, templates, and onboarding docs
reference that document instead of independently restating the hierarchy.

**Why:** Without one canonical operating model, governed repos drift in how they
interpret plans, capabilities, notebooks, and tests. A portable framework needs
one authority for the methodology itself before repo-local policies can build on
top of it.

---

## References Reviewed

- `CLAUDE.md` - framework positioning and extraction boundary
- `README.md` - current onboarding and planning claims
- `GETTING_STARTED.md` - adoption flow and planning guidance
- `patterns/15_plan-workflow.md` - plan workflow and TDD stance
- `patterns/28_question-driven-planning.md` - investigate-before-plan rule
- `patterns/30_gap-analysis.md` - current-vs-target planning discipline
- `patterns/36_executable-journey-notebooks.md` - notebook role and alignment model
- `patterns/42_planning-hierarchy.md` - current artifact hierarchy
- `templates/plan.md.template` - current bounded-plan contract

---

## Files Affected

- `PLANNING_OPERATING_MODEL.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `README.md` (modify)
- `GETTING_STARTED.md` (modify)
- `patterns/42_planning-hierarchy.md` (modify)
- `patterns/15_plan-workflow.md` (modify)
- `templates/plan.md.template` (modify, only if wording must align)

---

## Plan

### Steps

1. Create one canonical planning-operating-model document in
   `enforced-planning` that defines the artifact dependency graph.
2. Define the recommended initialization order for new and legacy repos:
   north star, questions, current-state assessment, gap analysis,
   capabilities/boundaries, roadmap, plans, notebooks, tests/gates, code,
   observability.
3. State explicitly that the hierarchy is a partial-order dependency model, not
   a rigid one-pass waterfall, and identify what must precede what.
4. Clarify that tests/gates should be predeclared before implementation and
   should follow TDD where feasible.
5. Update pattern/onboarding docs to reference the canonical operating model
   rather than restating it inconsistently.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| N/A | N/A | Doc-only change |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | Framework docs/templates still resolve expected files |
| `python -m pytest tests/ -q` | Existing framework tests remain green |

---

## Acceptance Criteria

- [x] `PLANNING_OPERATING_MODEL.md` is the single canonical methodology surface
      for hierarchy/order semantics.
- [x] The operating model clearly distinguishes strict dependencies from
      recommended sequencing.
- [x] Capabilities/boundaries are placed before roadmap/phases in the operating
      model where they define the enduring system shape.
- [x] Tests/gates are defined as pre-code planning artifacts, not only
      post-code verification.
- [x] `README.md`, `GETTING_STARTED.md`, and Pattern 42 point to the canonical
      operating model instead of competing with it.

---

## Open Questions

- [x] Should journey notebooks be required only for non-trivial multi-stage work,
      or should the operating model position them as the default for all bounded
      plans above a certain complexity?
      - Resolved: required for non-trivial multi-stage work; optional for simpler slices.
- [x] Should ADRs be represented as a cross-cutting layer in the canonical diagram
      rather than as a numbered level?
      - Resolved: yes; ADRs are cross-cutting durable decisions.

---

## Notes

This plan intentionally covers the methodology authority surface only. Static
linkage-graph changes and runtime truth-surface validation are follow-on plans,
not part of this first canonicalization slice.
