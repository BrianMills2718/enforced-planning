# Plan #53: Agent-Memory Research Citations And Validation

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9"
**goal_ref:** "planning-provenance"
**adrs_referenced:** ["ADR-0010"]
**research_citations:** []
**Blocked By:** None
**Blocks:** ISSUE-017 closeout in project-meta

---

## Gap

**Current:** Plans require agent-memory recall for projects with prior session history, but there
is no machine-readable way to record which prior findings materially informed a plan. The
canonical template, parser, and validator do not recognize any structured citation field.

**Target:** The canonical plan template includes a `research_citations` header field, plan tooling
can parse and validate it, and plan validation warns when plan text appears to rely on prior
agent-session findings without declaring those citations.

**Why:** ADR-0010 made prior session findings a required planning input when available. Without a
structured citation surface, that provenance is invisible to linting, review, and downstream
automation.

---

## References Reviewed

- `docs/plans/TEMPLATE.md` - canonical header and research-section shape
- `docs/plans/CLAUDE.md` - plan index and numbering surface
- `PLANNING_OPERATING_MODEL.md` - current planning contract around agent-memory recall
- `adr/0010-agent-memory-as-planning-input.md` - authoritative provenance policy
- `enforced_planning/plan_validation.py` - current validation result model and CLI behavior
- `scripts/parse_plan.py` - existing plan metadata parsing utilities
- `tests/test_validate_plan.py` - validator regression surface
- `tests/test_parse_plan.py` - parser regression surface

---

## Research Basis For This Slice

No additional research beyond References Reviewed.

---

## Files Affected

- docs/plans/53_agent-memory-research-citations-and-validation.md (create)
- docs/plans/CLAUDE.md (modify)
- docs/plans/TEMPLATE.md (modify)
- PLANNING_OPERATING_MODEL.md (modify)
- enforced_planning/plan_validation.py (modify)
- scripts/parse_plan.py (modify)
- tests/test_validate_plan.py (modify)
- tests/test_parse_plan.py (modify)

---

## Implementation

Completed on 2026-04-09.

### What shipped

1. `docs/plans/TEMPLATE.md` now includes `**research_citations:** []` with
   explicit `agent_memory:<entry_id>` guidance in the research section.
2. `PLANNING_OPERATING_MODEL.md` now states that materially used prior-session
   findings should be recorded in `research_citations`.
3. `scripts/parse_plan.py` can now parse `research_citations` and expose it in
   CLI and JSON output.
4. `enforced_planning/plan_validation.py` now:
   - parses `research_citations`
   - warns on malformed entries
   - warns on duplicates
   - warns when research/reference sections suggest prior-session provenance
     but the header field is empty
   - exposes warnings in JSON payloads
5. Regression tests were added for parser and validator coverage.

---

## Plan

### Steps

1. Add `research_citations` to the canonical template and document when to use it.
2. Extend the parser/validator surfaces so the field is machine-readable.
3. Add warning-only validation for malformed, duplicate, or missing citations when prior-session
   provenance language appears in the plan body.
4. Add parser and validator regression tests covering valid, invalid, duplicate, and empty-field
   cases.
5. Re-run focused tests and validate this plan file with the updated checker.

---

## Required Tests

> **REQUIRED BEFORE IMPLEMENTATION:** declare the tests and gates that will prove
> the plan. Write them first where feasible.

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_parse_plan.py` | `test_parse_research_citations_*` | Parser reads the header field and normalizes missing/empty cases |
| `tests/test_validate_plan.py` | `test_validate_plan_*research_citations*` | Validator reports malformed, duplicate, and provenance-warning cases correctly |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `pytest -q tests/test_parse_plan.py tests/test_validate_plan.py` | Core plan parser/validator surfaces remain stable |
| `python scripts/validate_plan.py --plan-file docs/plans/53_agent-memory-research-citations-and-validation.md --warn-only` | The new plan remains valid under the updated checker |

---

## Acceptance Criteria

> Feature-level criteria (what the plan accomplishes):
- [x] `docs/plans/TEMPLATE.md` includes `research_citations` with an example `agent_memory:<entry_id>` value
- [x] Planning docs explain that the field is for prior agent-session findings, not repo-local or ADR citations
- [x] Parser tooling can read `research_citations` as a list of strings
- [x] Validator warns on malformed or duplicate `research_citations` entries
- [x] Validator warns when plan text suggests prior-session provenance but `research_citations` is empty
- [x] Validator payload exposes research-citation warnings in machine-readable output

> Process criteria (quality gates):
- [x] Required tests pass
- [x] `python scripts/validate_plan.py --plan-file docs/plans/53_agent-memory-research-citations-and-validation.md --warn-only` passes
- [x] Docs updated

---

## Verification Results

- `pytest -q tests/test_parse_plan.py tests/test_validate_plan.py` — passed
- `python -m py_compile scripts/parse_plan.py enforced_planning/plan_validation.py` — passed
- `python scripts/validate_plan.py --plan-file docs/plans/53_agent-memory-research-citations-and-validation.md --warn-only` — passed

---

## Notes

- Version 1 is intentionally shallow: validate citation shape and warning surfaces, not whether an
  `agent_memory` entry actually exists.
- The accepted citation syntax is `agent_memory:<entry_id>` with `<entry_id>` matching
  `[A-Za-z0-9._-]+`.
- The provenance heuristic is non-blocking. Plans should not fail solely because they mention prior
  session context without citations, but reviewers and automation should see the warning.
