# Plan #24: Documentation Authority Governance and Enforcement

**Status:** Planned
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** [future] governed-repo doc authority rollout

---

## Gap

**Current:** The framework validates several local documentation truths, but it
does not yet define or enforce which doc is authoritative for a given concern.
As a result, a repo can still have:

- duplicate live handoffs
- contradictory status surfaces
- stale top-level summaries that appear canonical
- multiple "active" docs for the same concern

**Target:** The framework provides one portable doc-authority governance slice
with:

- concern-level authority declarations
- per-doc metadata
- deterministic validator
- pre-commit and CI enforcement model
- rollout guidance for governed repos

**Why:** Without an explicit authority layer, existing validators catch local
drift but still permit whole-repo ambiguity about where truth lives.

---

## References Reviewed

- `patterns/09_documentation-graph.md` - static documentation graph boundary
- `patterns/10_doc-code-coupling.md` - existing source/doc coupling enforcement
- `patterns/23_plan-status-validation.md` - specialist plan-status consistency pattern
- `scripts/check_truth_surface_drift.py` - current truth-surface drift validator
- `.pre-commit-hooks.yaml` - existing enforcement wiring model
- `docs/designs/DOCUMENTATION_SURFACE_ARCHITECTURE.md` - existing source vs consumer doc-surface design

---

## Research Basis For This Slice

- `docs/research/2026-04-05-doc-authority-governance-notes.md` - compared solution shapes and identified the missing concern-level authority model
- DIGIMON documentation audit (2026-04-05 conversation + repo review) - demonstrated the concrete failure mode this shared slice is designed to prevent

---

## Capabilities

N/A - framework governance design slice only. The implementation will create a
shared validator and config pattern later, but this plan itself does not add a
cross-project runtime capability yet.

---

## Files Affected

- `docs/plans/24_doc-authority-governance-and-enforcement.md` (create)
- `adr/0009-doc-authority-governance-and-enforcement.md` (create)
- `docs/designs/DOC_AUTHORITY_GOVERNANCE_ARCHITECTURE.md` (create)
- `docs/reference/DOC_AUTHORITY_SCHEMA.md` (create)
- `scripts/validate_doc_authority.py` (create in later implementation slice)
- `tests/test_validate_doc_authority.py` (create in later implementation slice)
- `.pre-commit-hooks.yaml` (modify in later implementation slice)
- `hooks/git/pre-commit` (modify in later implementation slice)

---

## Plan

### Decisions Pre-Made

1. This belongs in shared `enforced-planning`, not in DIGIMON-local tooling.
2. Enforcement is required; `make doc-truth-check` is an entrypoint, not the
   control mechanism.
3. Concern-level authority is a new layer above doc-code coupling and
   truth-surface drift validation.
4. The first implementation slice should use a dedicated config and metadata
   schema, not merge directly into `relationships.yaml`.
5. The first slice should block structural ambiguity, not attempt semantic
   auto-repair.

### Steps

1. Define the authority model:
   - concern map
   - authority tiers
   - lifecycle states
   - supersession edges
2. Define the v0 metadata and repo config schema.
3. Specify validator rules and deterministic failure codes.
4. Specify enforcement points:
   - pre-commit
   - CI
   - optional finish/merge wiring
5. Define rollout stages for governed repos:
   - warn-only
   - blocking singleton concerns
   - generated surface integration
6. Defer semantic review and dashboard/reporting to later slices.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_validate_doc_authority.py` | duplicate concern tests | Duplicate active canonical docs fail deterministically |
| `tests/test_validate_doc_authority.py` | handoff uniqueness tests | Active handoff concern cannot have two active canonical docs |
| `tests/test_validate_doc_authority.py` | config mismatch tests | Repo config and doc metadata agree on canonical mapping |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/24_doc-authority-governance-and-enforcement.md --warn-only` | Plan remains valid |
| `python scripts/self_test.py --links --docs` | New governance docs integrate cleanly with existing surfaces |

---

## Acceptance Criteria

- [ ] The framework defines a portable concern-level documentation authority model
- [ ] The framework defines v0 doc metadata and repo-config schema
- [ ] The validator contract specifies deterministic duplicate-authority failures
- [ ] Enforcement points are explicit and blocking, not advisory-only
- [ ] Rollout guidance is phased and avoids big-bang adoption
- [ ] Declared checks pass

---

## Open Questions

1. Should the authority config later merge into `relationships.yaml`?
2. Is frontmatter sufficient as the sole metadata carrier?
3. Does v1 need an explicit co-canonical exception mechanism?

These do not block the first design slice.
