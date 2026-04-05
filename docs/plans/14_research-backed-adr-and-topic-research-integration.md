# Plan #14: Research-Backed ADRs and Topic Research Integration

**Status:** Complete
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** [future] project-meta topic research manifest adoption

---

## Gap

**Current:** `enforced-planning` already requires investigation before planning
and now locally requires ADR `Research Basis` via ADR-0008, but research is not
yet a first-class artifact in the planning hierarchy. The ADR pattern/template
surfaces are inconsistent with ADR-0008, plans do not distinguish local file
review from reusable research, and there is no portable pattern for topic-level
research that compounds over time.

**Target:** The portable framework names research and investigation as explicit
artifacts with clear roles. ADRs, plans, and capability docs can all point to
durable evidence surfaces. Templates and patterns are aligned. The framework
also documents how governed repos can maintain living topic research linked to
ADRs, capabilities, and refresh triggers.

**Why:** A decision without a recoverable evidence chain becomes unauditable.
Agents need a durable path from "what was researched" to "what was decided" to
"what should be refreshed now." Without that path, research stays local to one
session and ADRs become self-referential.

---

## References Reviewed

- `PLANNING_OPERATING_MODEL.md` - current canonical artifact dependency graph
- `patterns/07_adr.md` - current ADR pattern still reflects the pre-ADR-0008 template
- `patterns/15_plan-workflow.md` - current plan structure and `References Reviewed`
- `patterns/28_question-driven-planning.md` - investigation-before-plan discipline
- `patterns/30_gap-analysis.md` - current-vs-target framing
- `patterns/42_planning-hierarchy.md` - compressed hierarchy view
- `adr/README.md` - local ADR index and updated `Research Basis` doctrine
- `adr/0008-adr-research-linkage.md` - accepted rule for ADR evidence linkage
- `templates/CLAUDE.md.docs-adr` - portable ADR template surface that still needs propagation
- `~/projects/project-meta/research_synthesis/CLAUDE.md` - current topic-oriented research library contract
- `~/projects/project-meta/research_synthesis/autonomous_agents/SYNTHESIS_2026-03-24.md` - example of reusable synthesis pointing back to raw investigation
- `~/projects/project-meta/research_synthesis/agentic_memory/SOTA_SURVEY_2026_04.md` - example of research intended to inform future design work
- `~/projects/investigations/cross-project/2026-04-04-enforced-planning-research-methodology-review.md` - critique and recommended target model

---

## Research Basis For This Slice

- `~/projects/investigations/cross-project/2026-04-04-enforced-planning-research-methodology-review.md` - primary critique of the current methodology and target evidence model
- `~/projects/project-meta/research_synthesis/autonomous_agents/SYNTHESIS_2026-03-24.md` - concrete example of reusable synthesis that points back to raw investigation
- `~/projects/project-meta/research_synthesis/agentic_memory/SOTA_SURVEY_2026_04.md` - example of topic research intended to drive future design decisions rather than a one-off task

---

## Files Affected

- PLANNING_OPERATING_MODEL.md (modify)
- patterns/01_README.md (modify)
- patterns/07_adr.md (modify)
- patterns/15_plan-workflow.md (modify)
- patterns/42_planning-hierarchy.md (modify)
- patterns/43_topic-research-synthesis.md (create)
- templates/CLAUDE.md.docs-adr (modify)
- templates/plan.md.template (modify)
- templates/plan.md.docs-only (modify)
- GETTING_STARTED.md (modify)
- scripts/parse_plan.py (modify)
- adr/README.md (modify if needed for consistency only)
- tests/test_parse_plan.py (modify)
- [future] project-meta/research_synthesis/*/topic_manifest.yaml (adoption outside this repo)

---

## Plan

### Steps

1. Promote research and investigation to named artifacts in the planning
   operating model and compressed hierarchy pattern.
2. Propagate ADR-0008 through the portable ADR pattern and ADR template
   surfaces so the doctrine and scaffolds match.
3. Extend the plan template to distinguish:
   - `References Reviewed`
   - `Research Basis For This Slice`
4. Define a portable topic research pattern for governed repos:
   - dated investigation memo vs living topic synthesis
   - optional lightweight topic manifest
   - freshness triggers and ownership
5. Decide what enforcement should be blocking vs advisory:
   - ADR `Research Basis` likely strict
   - plan `Research Basis For This Slice` likely strict for design/cross-project work, advisory for trivial local work
   - topic manifest freshness likely advisory first
6. Document downstream adoption guidance for `project-meta/research_synthesis`
   without hardcoding project-meta specifics into the portable pattern.
7. Reconcile worktree merge strategy separately:
   - merge `plan-13`
   - selectively salvage `plan-10`
   - prune empty worktrees after audit

---

## Required Tests

> **REQUIRED BEFORE IMPLEMENTATION:** declare the tests and checks that will
> prove the framework changes are coherent.

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_parse_plan.py` | `test_parse_research_basis_*` | Plan parser can read the new research section cleanly and ignore explicit skip statements |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `pytest -q tests/test_validate_plan.py tests/test_parse_plan.py tests/test_complete_plan.py` | Core plan validation/parsing surfaces must remain stable |
| `python scripts/validate_plan.py --plan-file docs/plans/14_research-backed-adr-and-topic-research-integration.md --warn-only` | Plan format remains valid |

---

## Acceptance Criteria

- [x] `PLANNING_OPERATING_MODEL.md` names investigation memos and topic research syntheses as explicit artifact roles
- [x] `patterns/42_planning-hierarchy.md` reflects the same hierarchy truthfully
- [x] `patterns/07_adr.md` and `templates/CLAUDE.md.docs-adr` require `Research Basis`
- [x] `templates/plan.md.template` and `templates/plan.md.docs-only` distinguish reviewed references from research basis
- [x] The framework defines a portable pattern for living topic research plus freshness triggers
- [x] Guidance clearly separates portable framework doctrine from project-meta-specific adoption details
- [x] `scripts/parse_plan.py` can return the new research basis section
- [x] Merge guidance for `plan-10` and `plan-13` is captured so worktree cleanup does not happen ad hoc
- [x] Declared tests/checks pass

---

## Decisions

- The portable framework names `topic_manifest.yaml` as the recommended
  filename and shape, but keeps it optional so governed repos can adopt the
  concept without overfitting to one ecosystem layout.
- Missing `Research Basis For This Slice` is treated as blocking for non-trivial,
  design, cross-project, or externally-informed plans, and recommended for
  trivial local plans.
- Topic freshness starts as advisory metadata. Repos should capture review dates,
  SLAs, and refresh triggers before attempting blocking semantic freshness gates.

---

## Notes

### Recommended Merge Sequence For Current Worktrees

1. Commit or stash current local changes on `enforced-planning` main before any merge work.
2. Merge `plan-13-rename-safe-merge-cleanup` first; it is small and low-risk.
3. Do not merge `plan-10-framework-reconciliation` wholesale; salvage still-valid changes by theme.
4. Audit `plan-74` through `plan-83`, then prune if they remain empty relative to main.

### Downstream Adoption Shape

The portable framework should define the doctrine. `project-meta` can then adopt
it with:

- topic folders under `research_synthesis/`
- a small topic manifest per folder
- links from topic synthesis -> investigations -> ADRs -> capabilities
- freshness triggers for high-value areas such as memory, orchestration, and
  tool design
