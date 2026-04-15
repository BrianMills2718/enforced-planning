# Plan #55: Enforced-Planning Recursive Doc Spine Dogfood

**Status:** Planned
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9"
**goal_ref:** "documentation-governance"
**adrs_referenced:** ["ADR-0009", "ADR-0010"]
**research_citations:** []
**Blocked By:** #54
**Blocks:** [future] downstream recursive doc-spine rollout to governed repos

---

## Gap

**Current:** Plan #54 defines the recursive documentation-spine model, but
`enforced-planning` itself does not use it yet.

- this repo has no dedicated root execution brief
- target-state, current-state, and gap-summary concerns are not encoded as a
  machine-readable authority spine
- `scripts/doc_authority.yaml` only governs indexed authority surfaces and does
  not describe document ancestry, concern coverage, or code-surface ownership
- `enforced_planning/file_context.py` computes required reads from
  `relationships.yaml` only, so it cannot require the parent-doc chain or
  explicit doc-spine `required_context`
- `enforced_planning/plan_validation.py` cannot yet enforce that plans cite the
  target/current/gap/ancestor docs required by the doc spine

**Target:** `enforced-planning` becomes the first repo to dogfood the recursive
documentation-spine contract in a bounded, reviewable slice:

- add one small root `EXECUTION_BRIEF.md`
- reuse `PLANNING_OPERATING_MODEL.md` as the `north_star` concern
- add durable `docs/overview/CURRENT_STATE.md` and
  `docs/overview/GAP_SUMMARY.md` authority docs instead of reusing generated ops
  artifacts
- keep `ROADMAP.md` as the `roadmap` concern and `docs/plans/CLAUDE.md` as the
  `active_plan_index` concern
- extend `scripts/doc_authority.yaml` and `enforced_planning/doc_authority.py`
  to validate the bounded doc spine
- extend `enforced_planning/file_context.py` and
  `enforced_planning/plan_validation.py` so the framework's own validators and
  read-gating use ancestor closure plus explicit required context for the
  bounded dogfood scope

**Why:** The framework should prove the operator experience on itself before it
requires downstream repos to adopt the same structure. This slice turns the
methodology into a real self-hosted contract instead of a design-only claim.

---

## References Reviewed

- `docs/plans/54_recursive-documentation-spine-and-required-read-closure.md` - frozen design contract for the recursive spine
- `docs/designs/RECURSIVE_DOCUMENTATION_SPINE_AND_REQUIRED_READ_CLOSURE.md` - config shape, edge semantics, and rollout stages
- `docs/plans/41_doc-authority-governance-and-enforcement.md` - existing dedicated-config decision and authority-governance rollout
- `docs/designs/DOC_AUTHORITY_GOVERNANCE_ARCHITECTURE.md` - current authority layers and validator scope
- `docs/reference/DOC_AUTHORITY_SCHEMA.md` - current v0 schema that this slice will extend
- `EXECUTION_BRIEF.md` - root execution brief that this repo will now dogfood explicitly
- `PLANNING_OPERATING_MODEL.md` - current north-star / methodology surface for this repo
- `docs/overview/CURRENT_STATE.md` - durable current-state surface for the bounded dogfood slice
- `docs/overview/GAP_SUMMARY.md` - bounded gap surface that the implementation plan rolls up into
- `README.md` - current top-level overview surface that should remain overview, not become the root execution brief
- `ROADMAP.md` - current phase map and active execution queue
- `docs/ops/ECOSYSTEM_STATUS.md` - generated fleet status surface that should not be reused as the durable current-state concern
- `enforced_planning/doc_authority.py` - current indexed-surface validator implementation
- `enforced_planning/file_context.py` - current required-read and context-loading implementation
- `enforced_planning/plan_validation.py` - current plan validation enforcement surface
- `scripts/doc_authority.yaml` - current repo-local authority config
- `relationships.yaml` - existing relationships/read-gating config that must remain the coupling surface, not the new spine home
- `tests/test_validate_doc_authority.py` - current authority validator tests
- `tests/test_validate_plan.py` - current plan validation tests
- `adr/0009-doc-authority-governance-and-enforcement.md` - governing ADR for the dedicated authority-config model
- `adr/0010-agent-memory-as-planning-input.md` - governing ADR for memory-aware planning inputs
- `tests/test_file_context_scope.py` - current file-context and scope-policy tests

---

## Research Basis For This Slice

No additional research beyond References Reviewed.

---

## Files Affected

- `EXECUTION_BRIEF.md` (create)
- `docs/overview/CURRENT_STATE.md` (create)
- `docs/overview/GAP_SUMMARY.md` (create)
- `docs/plans/55_enforced-planning_recursive_doc_spine_dogfood.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `ROADMAP.md` (modify)
- `docs/reference/DOC_AUTHORITY_SCHEMA.md` (modify)
- `docs/designs/RECURSIVE_DOCUMENTATION_SPINE_AND_REQUIRED_READ_CLOSURE.md` (modify if implementation details need clarification)
- `scripts/doc_authority.yaml` (modify)
- `enforced_planning/doc_authority.py` (modify)
- `enforced_planning/file_context.py` (modify)
- `enforced_planning/plan_validation.py` (modify)
- `scripts/validate_doc_authority.py` (modify if CLI surface needs new report options)
- `tests/test_validate_doc_authority.py` (modify)
- `tests/test_validate_plan.py` (modify)
- `tests/test_file_context_scope.py` (modify or split)
- `tests/test_doc_spine_file_context.py` (create if the new closure tests deserve a dedicated file)

---

## Plan

### Decisions Pre-Made

1. Dogfooding starts in `enforced-planning`; downstream rollout stays blocked
   until this repo proves the operator experience.
2. The root execution brief will be a new `EXECUTION_BRIEF.md`. `README.md`
   remains the framework-source overview and adoption entrypoint.
3. `PLANNING_OPERATING_MODEL.md` remains the canonical `north_star` doc for
   this repo.
4. `docs/overview/CURRENT_STATE.md` and `docs/overview/GAP_SUMMARY.md` will be
   new durable authority docs. Generated `docs/ops/ECOSYSTEM_STATUS.md` is not
   the durable `current_state` concern.
5. `ROADMAP.md` remains the `roadmap` concern and `docs/plans/CLAUDE.md`
   remains the `active_plan_index` concern.
6. The first implementation slice keeps recursive spine metadata in
   `scripts/doc_authority.yaml`; it does not merge the spine into
   `relationships.yaml`.
7. The first dogfood scope is bounded. It covers the documentation-governance
   subsystem and the framework's own plan/doc-authority/read-gating surfaces,
   not every file in the repo.
8. Required-read closure for managed surfaces is the union of:
   - existing `relationships.yaml` required reads
   - doc-spine `primary_spec`
   - the full `primary_parent` chain
   - applicable `governed_by`
   - explicit `required_context`
9. Broken structure blocks immediately: missing required concerns, unknown
   `primary_parent`, ancestry cycles, unknown `primary_spec`, and
   `required_context` entries without a `reason`.
10. Budget overages warn in v1. They do not block the first dogfood slice.
11. `validate_plan` must require plans touching managed dogfood surfaces to cite
    the leaf spec, ancestor chain, and required extra context in
    `References Reviewed`.

### Steps

1. Create the bounded authority spine for `enforced-planning` itself:
   - add `EXECUTION_BRIEF.md`
   - add `docs/overview/CURRENT_STATE.md`
   - add `docs/overview/GAP_SUMMARY.md`
   - wire the concern map and primary-parent chain
2. Extend `scripts/doc_authority.yaml` to schema v2 with:
   - `doc_spine.root_doc`
   - `doc_spine.required_concerns`
   - `doc_spine.max_required_read_docs`
   - `doc_spine.max_required_read_words`
   - `role_budgets`
   - per-doc entries with `concerns`, `role`, `primary_parent`,
     `governed_by`, and `required_context`
   - bounded `code_surfaces` entries with `primary_spec`
3. Extend `enforced_planning/doc_authority.py` to validate:
   - required concern coverage
   - root-doc existence and uniqueness
   - `primary_parent` referential integrity
   - ancestry cycles
   - `primary_spec` referential integrity for managed code surfaces
   - `required_context.reason` presence
   - role-budget and required-read-budget warnings
4. Extend `enforced_planning/file_context.py` so doc-spine closure augments the
   existing `relationships.yaml` required-read surface for bounded managed files.
5. Extend `enforced_planning/plan_validation.py` so plans touching bounded
   managed surfaces must cite the doc-spine closure in `References Reviewed`.
6. Update the top-level planning surfaces so the new dogfood slice is visible:
   - add this plan to `docs/plans/CLAUDE.md`
   - add the Phase 9 dogfood item to `ROADMAP.md`
7. Verify the dogfood slice with focused tests plus the existing doc-link and
   plan-validation checks.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_validate_doc_authority.py` | `test_validate_doc_authority_fails_when_required_concern_missing` | Missing `execution_brief` / `north_star` / `current_state` / `gap_summary` / `roadmap` / `active_plan_index` concerns fail deterministically |
| `tests/test_validate_doc_authority.py` | `test_validate_doc_authority_fails_on_primary_parent_cycle` | Recursive ancestry cycles are blocking failures |
| `tests/test_validate_doc_authority.py` | `test_validate_doc_authority_fails_when_code_surface_primary_spec_missing` | Managed code surfaces must point to a known primary spec |
| `tests/test_validate_doc_authority.py` | `test_validate_doc_authority_warns_when_required_read_budget_exceeded` | Budget overages warn instead of block in v1 |
| `tests/test_doc_spine_file_context.py` | `test_collect_context_includes_doc_spine_primary_spec_and_ancestor_chain` | File context includes primary spec plus full ancestor chain |
| `tests/test_doc_spine_file_context.py` | `test_collect_context_includes_required_context_with_reason` | Explicit required context is added to required reads when applicable |
| `tests/test_validate_plan.py` | `test_validate_plan_requires_doc_spine_closure_for_managed_surface` | Plans affecting managed dogfood files must cite the doc-spine closure |
| `tests/test_validate_plan.py` | `test_validate_plan_accepts_plan_when_doc_spine_closure_is_cited` | Properly cited ancestry and required-context docs satisfy plan validation |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/55_enforced-planning_recursive_doc_spine_dogfood.md --warn-only` | The implementation plan itself must satisfy the existing plan contract |
| `pytest -q tests/test_validate_doc_authority.py tests/test_validate_plan.py tests/test_file_context_scope.py` | Existing validator behavior must remain intact while the new spine is added |
| `python scripts/validate_doc_authority.py --check --repo-root .` | The repo's own dogfood config validates after implementation |
| `python scripts/self_test.py --links --docs` | New docs integrate cleanly with existing references |

---

## Acceptance Criteria

> Feature-level criteria (what the plan accomplishes):
- [ ] `enforced-planning` has one explicit root execution brief plus durable `north_star`, `current_state`, `gap_summary`, `roadmap`, and `active_plan_index` concerns wired into a bounded recursive doc spine
- [ ] `scripts/doc_authority.yaml` and `enforced_planning/doc_authority.py` support schema v2 doc-spine metadata for this bounded dogfood slice
- [ ] The authority validator blocks malformed ancestry and missing concern coverage while warning on budget overages
- [ ] `enforced_planning/file_context.py` includes doc-spine required-read closure for the managed dogfood surfaces without replacing existing `relationships.yaml` couplings
- [ ] `enforced_planning/plan_validation.py` requires doc-spine closure docs in `References Reviewed` for plans that affect managed dogfood surfaces
- [ ] `README.md` remains overview/adoption guidance rather than becoming the root execution brief

> Process criteria (quality gates):
- [ ] Required tests pass
- [ ] Docs updated
- [ ] Repo-local dogfood config validates cleanly

---

## Open Questions

- [ ] After the dogfood slice lands, should stable code surfaces continue to use plan docs as `primary_spec`, or should they graduate to subsystem spec/reference docs? - Status: OPEN | Why it matters: affects the steady-state maintenance model after implementation is complete
- [ ] Should v1 budget warnings become blocking once a repo opts into full recursive-spine adoption beyond the bounded dogfood scope? - Status: OPEN | Why it matters: affects rollout friction for downstream governed repos

---

## Notes

- This plan is intentionally narrower than a full-repo migration. The purpose is
  to prove the mechanics and operator experience on the framework's own
  documentation-governance subsystem first.
- The first implementation slice should not silently duplicate the same
  semantics in `scripts/doc_authority.yaml` and `relationships.yaml`. Couplings
  stay in `relationships.yaml`; recursive abstraction ancestry stays in the
  authority config for now.
