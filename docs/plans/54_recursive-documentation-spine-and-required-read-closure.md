# Plan #54: Recursive Documentation Spine And Required-Read Closure

**Status:** Planned
**Type:** design
**Priority:** High
**phase_ref:** "Phase 9"
**goal_ref:** "documentation-governance"
**adrs_referenced:** ["ADR-0009", "ADR-0010"]
**research_citations:** []
**Blocked By:** None
**Blocks:** [future] recursive doc-spine validation and read-gating rollout

---

## Gap

**Current:** The framework already requires current-vs-target framing inside
plans, and it already models concern-level documentation authority. But it does
not yet model the abstraction ancestry that keeps the big picture visible during
implementation:

- governed repos can declare canonical concerns, but not one recursive
  `primary_parent` spine per document
- read-gating can require local couplings and ADRs, but it does not require the
  full ancestor chain from a leaf spec back to the repo's top-level execution
  brief
- `current_docs`, `target_docs`, and `gap_docs` are supported as optional
  architecture metadata, but the framework does not yet require repos to expose
  those surfaces as first-class authority concerns
- large repos accumulate useful leaf docs while still making it easy for agents
  to miss the higher-level system story

**Target:** Extend the shared documentation-governance model with one recursive
documentation spine:

1. one small root execution brief per repo,
2. one `primary_parent` per authority-bearing doc,
3. one `primary_spec` per managed code surface,
4. explicit mandatory extra reads via `required_context`,
5. repo-level required concerns for target state, current state, and gap
   summary, with the option for one doc to satisfy multiple concerns in small
   repos,
6. role-based size and required-read budgets,
7. deterministic validator and read-gating semantics,
8. explicit dogfooding in `enforced-planning` before downstream rollout.

**Why:** Agents and humans need progressive disclosure with enforced ancestry.
Without it, doc volume grows while the top-level architecture and active gate
become easier to lose during implementation.

---

## References Reviewed

- `PLANNING_OPERATING_MODEL.md` - canonical artifact dependency graph and strict planning dependencies
- `GETTING_STARTED.md` - governed-repo install surface and current minimum contract
- `patterns/42_planning-hierarchy.md` - compressed planning-layer reference
- `patterns/30_gap-analysis.md` - current/target/gap discipline and gap-summary role
- `docs/plans/41_doc-authority-governance-and-enforcement.md` - existing concern-level authority design decisions
- `adr/0009-doc-authority-governance-and-enforcement.md` - authority-governance ADR
- `docs/designs/DOC_AUTHORITY_GOVERNANCE_ARCHITECTURE.md` - existing authority layers and rollout
- `docs/reference/DOC_AUTHORITY_SCHEMA.md` - current dedicated authority-config shape
- `docs/designs/RELATIONSHIPS_V2_DESIGN.md` - existing graph/policy approach and coupling semantics

---

## Research Basis For This Slice

No additional research beyond References Reviewed.

---

## Files Affected

- `docs/plans/54_recursive-documentation-spine-and-required-read-closure.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `docs/designs/RECURSIVE_DOCUMENTATION_SPINE_AND_REQUIRED_READ_CLOSURE.md` (create)

---

## Plan

### Steps

1. Define the recursive documentation-spine model and the root execution-brief
   requirement.
2. Define edge semantics:
   - `primary_parent`
   - `primary_spec`
   - `governed_by`
   - `required_context`
   - `related`
   - `supersedes`
3. Define the mandatory read-closure algorithm for code edits and plan authoring.
4. Define how target-state, current-state, and gap-summary docs become required
   authority concerns while still allowing small repos to compress them into one
   file.
5. Define role-based size budgets and required-read budget limits.
6. Define the dedicated-config schema extension, validator rules, read-gating
   integration points, and rollout stages.
7. Define the dogfooding requirement: `enforced-planning` is the first repo to
   adopt the recursive doc-spine contract before the framework requires it
   elsewhere.

---

## Required Tests

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/54_recursive-documentation-spine-and-required-read-closure.md --warn-only` | The new design plan must satisfy the current plan contract |
| `python scripts/self_test.py --links --docs` | New design docs and plan-index references must integrate cleanly |

---

## Acceptance Criteria

> Feature-level criteria (what the plan accomplishes):
- [ ] The design defines a recursive documentation spine with one `primary_parent` per authority-bearing doc and one root execution brief per repo
- [ ] The design defines required-read closure from code surface to `primary_spec` and full ancestor chain
- [ ] The design defines explicit `required_context` edges with a mandatory `reason` and optional `when`
- [ ] The design defines how target-state, current-state, and gap-summary docs become required authority concerns
- [ ] The design allows one doc to satisfy multiple concerns in small repos while still supporting deeper recursive decomposition in larger repos
- [ ] The design uses role-based size/read budgets instead of fixed hand-maintained tiers
- [ ] The design remains compatible with Plan #41's dedicated-config decision for the first implementation slice
- [ ] The design states clearly that `enforced-planning` is the first-adopter dogfood repo before downstream rollout

> Process criteria (quality gates):
- [ ] Declared checks pass
- [ ] Docs updated

---

## Open Questions

- [ ] Should required-read budget overages be warning-only in v1 or blocking for repos that fully adopt the spine? — Status: OPEN | Why it matters: budget enforcement changes rollout friction substantially
- [ ] Should plan validation require direct citation of the exact target/current/gap docs, or is citing the leaf spec plus its ancestor chain sufficient once ancestry is machine-readable? — Status: OPEN | Why it matters: affects how redundant the plan-writing surface becomes

---

## Notes

- This is a design slice, not the implementation rollout. It should freeze the
  model first, then let a later implementation slice wire validators, hooks, and
  migration tooling.
- The first implementation slice should land in `enforced-planning` itself so the
  framework proves the operator experience before it asks other repos to adopt
  the same contract.
- The intended improvement is not "more docs." It is explicit progressive
  disclosure with a bounded mandatory context surface.
