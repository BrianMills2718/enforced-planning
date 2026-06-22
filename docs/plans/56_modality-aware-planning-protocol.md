# Plan #56: Modality-Aware Planning Protocol

**Status:** ✅ Complete
**Type:** governance
**Priority:** High
**phase_ref:** "Phase 9"
**goal_ref:** "planning-methodology-maintenance"
**adrs_referenced:** []
**research_citations:** []
**Blocked By:** None
**Blocks:** [future] validator enforcement for required Modality Assessment

---

## Gap

**Current:** The local `/design-plan` skill correctly distinguishes deductive,
exploratory, and hybrid work, and the root project instructions already mention
it. The canonical enforced-planning model and plan templates did not consistently
carry that distinction, so agents could still over-specify emergent work or bury
the modality decision in chat.

**Target:** `PLANNING_OPERATING_MODEL.md`, plan templates, and compressed
patterns make modality diagnosis a first-class planning step. New plans ask
agents to state which parts are deductive/plan-first, exploratory/ladder, or
hybrid; exploratory slices must name the instrument, readout, and step-down path
instead of pretending a premature threshold is known.

**Why:** This keeps the useful part of `/design-plan` while avoiding a competing
framework. The skill becomes a front door into the existing operating model, not
a parallel policy surface.

---

## References Reviewed

- `../.claude/skills/design-plan/SKILL.md` - source skill reviewed for the modality protocol
- `PLANNING_OPERATING_MODEL.md` - canonical methodology surface
- `docs/plans/TEMPLATE.md` - canonical source-repo plan scaffold
- `templates/plan.md.template` - installable implementation-plan scaffold
- `templates/plan.md.docs-only` - installable documentation-plan scaffold
- `templates/CLAUDE.md.root` - installed root guidance for governed repos
- `patterns/15_plan-workflow.md` - compressed bounded-plan workflow
- `patterns/42_planning-hierarchy.md` - compressed planning hierarchy
- `docs/plans/CLAUDE.md` - plan index and status surface
- `ROADMAP.md` - Phase 9 maintenance queue
- Operational recall check for enforced-planning/design-plan active decisions - no relevant past sessions found

---

## Research Basis For This Slice

No additional research beyond References Reviewed.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Canonical docs and templates | Deductive / plan-first | The desired policy relationship is knowable: POM stays canonical, templates carry the planning prompt. | Update docs/templates and verify with existing doc/tool checks. |
| Future deterministic enforcement | Exploratory / ladder | It is not yet clear whether blocking validation on a Modality Assessment section reduces errors enough to justify friction. | Document prose/template enforcement now; defer validator enforcement until observed plan quality or friction shows it is worth mechanizing. |
| Skill relationship to enforced-planning | Hybrid | The skill is useful as a front door, but authority must remain in the operating model. | Integrate the concept into POM and templates; avoid creating a second canonical planning hierarchy. |

**Exploratory readout:** Future plan reviews show repeated missing or fake
modality assessments, or agents continue to pre-decide emergent work despite
the template prompt.

**Step-down path:** Inspect the concrete plan files or review findings that
miss modality diagnosis, then decide whether to add a validator check, a
template clarification, or a skill update.

---

## Files Affected

- PLANNING_OPERATING_MODEL.md (modify)
- ROADMAP.md (modify)
- docs/plans/CLAUDE.md (modify)
- docs/plans/TEMPLATE.md (modify)
- docs/plans/56_modality-aware-planning-protocol.md (create)
- patterns/15_plan-workflow.md (modify)
- patterns/42_planning-hierarchy.md (modify)
- templates/CLAUDE.md.root (modify)
- templates/plan.md.docs-only (modify)
- templates/plan.md.template (modify)

---

## Plan

### Steps

1. Review `/design-plan` and decide whether it adds value relative to the
   canonical operating model.
2. Promote the useful concept into `PLANNING_OPERATING_MODEL.md` as modality
   diagnosis before design.
3. Add Modality Assessment prompts to plan templates.
4. Update compressed pattern docs, plan index, and roadmap so the change is
   discoverable.
5. Run focused validation and commit the verified documentation slice.

---

## Required Tests

### New Tests (TDD)

No new code tests. This is a governance/documentation template update.

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/56_modality-aware-planning-protocol.md --warn-only` | New plan remains parseable and valid. |
| `python scripts/self_test.py` | Framework-level checks continue to pass after template and methodology edits. |

---

## Acceptance Criteria

> Feature-level criteria:
- [x] The usefulness judgment is documented: `/design-plan` is a modality front
  door, not a replacement framework.
- [x] `PLANNING_OPERATING_MODEL.md` defines deductive, exploratory, and hybrid
  planning treatment.
- [x] Plan templates prompt for Modality Assessment with instrument/readout and
  step-down guidance for exploratory work.
- [x] Pattern docs and roadmap/index surfaces point to the methodology change.

> Process criteria:
- [x] Required validation passes.
- [x] Docs updated.
- [x] Verified work is committed.

---

## Verification Results

- `python scripts/validate_plan.py --plan-file docs/plans/56_modality-aware-planning-protocol.md --warn-only` - passed
- `python scripts/check_markdown_links.py PLANNING_OPERATING_MODEL.md patterns/15_plan-workflow.md patterns/42_planning-hierarchy.md docs/plans/56_modality-aware-planning-protocol.md docs/plans/CLAUDE.md ROADMAP.md` - passed
- `python scripts/self_test.py` - passed

---

## Notes

Deterministic validation for the `## Modality Assessment` section is deliberately
not included in this slice. The current enforcement is prose plus templates.
Make it programmatic only if future plans keep missing or faking the diagnosis.

`python scripts/sync_plan_status.py --check` was also tried during verification
and reported every numbered plan as missing from the index. The index is visibly
populated; the script currently searches for an older `## Gap Summary` heading
while this repo uses `# Implementation Plans`. That parser compatibility issue
is a follow-up enforcement cleanup, not part of this documentation slice.
