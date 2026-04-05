# Plan #16: Documentation and Adoption Surface Convergence

**Status:** Planned
**Type:** implementation
**Priority:** High
**Blocked By:** #17, #18
**Blocks:** trustworthy governed-repo adoption guidance, truthful framework status surfaces

---

## Gap

**Current:** The planning methodology docs are stronger than the product and
adoption docs. `README.md`, `GETTING_STARTED.md`,
`docs/guides/NEW_PROJECT_SETUP.md`, `hooks/README.md`, `ROADMAP.md`, and
`patterns/01_README.md` do not currently present one compendious framework
story. They mix source-repo and installed-repo perspectives, disagree on paths
and config keys, overstate convergence, and still over-center `agent_ecology2`.

**Target:** The repo has one compendious documentation stack:

- source-repo overview in `README.md`
- first-success adoption path in `GETTING_STARTED.md`
- deeper operator detail in `docs/guides/NEW_PROJECT_SETUP.md` only if still needed
- reference-only hook documentation in `hooks/README.md`
- forward-looking status in `ROADMAP.md`
- pattern catalog in `patterns/01_README.md`

All of these match the canonical installer and the canonical semantic-review
stack.

**Why:** A portable framework that cannot explain its own installation and
governance model truthfully is not ready for broad adoption. The framework
needs a stable product surface, not just a strong internal doctrine.

---

## References Reviewed

- `README.md` - current top-level framework story
- `GETTING_STARTED.md` - current fast-path adoption guidance
- `docs/guides/NEW_PROJECT_SETUP.md` - current detailed setup guide
- `hooks/README.md` - hook installation/reference surface
- `ROADMAP.md` - current phase map and next-work story
- `patterns/01_README.md` - pattern catalog and provenance framing
- `docs/reference/CONFIG_REFERENCE.md` - authoritative config key table
- `templates/meta-process.yaml.example` - current config shape
- `docs/designs/DOCUMENTATION_SURFACE_ARCHITECTURE.md` - proposed canonical doc-role split

---

## Research Basis For This Slice

- `docs/designs/DOCUMENTATION_SURFACE_ARCHITECTURE.md` - synthesized doc-role model and convergence target
- No additional research beyond References Reviewed.

---

## Files Affected

- README.md (modify)
- GETTING_STARTED.md (modify)
- docs/guides/NEW_PROJECT_SETUP.md (modify or reduce)
- hooks/README.md (modify)
- ROADMAP.md (modify)
- patterns/01_README.md (modify)
- CLAUDE.md (modify if the top-level quick-start/status pointers remain stale)
- docs/designs/DOCUMENTATION_SURFACE_ARCHITECTURE.md (reference only unless refinements are needed)
- ISSUES.md (modify for resolution status if complete)
- docs/plans/16_documentation-and-adoption-surface-convergence.md (modify)
- docs/plans/CLAUDE.md (modify)

---

## Plan

### Steps

1. Rewrite `README.md` around the source-repo perspective only.
2. Rewrite `GETTING_STARTED.md` around the installed-governed-repo perspective only.
3. Decide whether `docs/guides/NEW_PROJECT_SETUP.md` remains as a detailed guide
   or is collapsed into `GETTING_STARTED.md`.
4. Convert `hooks/README.md` into a reference surface, not a competing install guide.
5. Update `ROADMAP.md` so it shows real forward work rather than already-complete next steps.
6. Remove `agent_ecology2` as a framing device outside a short origin note.
7. Recheck all adoption docs for exact path/config agreement after Plans #17 and #18 land.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_self_test.py` or equivalent | installer/adoption doc reference assertions | Core onboarding docs reference the canonical installed paths rather than stale `enforced-planning/` copy-model paths |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/16_documentation-and-adoption-surface-convergence.md --warn-only` | Plan remains well-formed |
| `python scripts/self_test.py` | Framework file/template integrity and documented install surfaces remain coherent |
| `rg -n "agent_ecology2|strict_doc_coupling|copy `enforced-planning`" README.md GETTING_STARTED.md docs/guides hooks patterns` | Stale framing and obsolete config/path strings are removed or intentionally limited |

---

## Acceptance Criteria

- [ ] `README.md` is source-repo-oriented and does not silently switch to installed-repo perspective
- [ ] `GETTING_STARTED.md` describes the installed governed-repo layout and commands truthfully
- [ ] `docs/guides/NEW_PROJECT_SETUP.md` no longer duplicates or contradicts the fast-path guide
- [ ] `hooks/README.md` no longer competes with top-level install guidance
- [ ] `ROADMAP.md` shows actual next work
- [ ] Top-level docs use one tool-support matrix and one config vocabulary
- [ ] `agent_ecology2` appears only as provenance, not as the explanatory frame
- [ ] Declared checks pass

---

## Open Questions

- [ ] Should `docs/guides/NEW_PROJECT_SETUP.md` be retained as a separate doc after convergence, or folded into `GETTING_STARTED.md`? — Status: OPEN | Why it matters: affects long-term doc clutter and duplication risk

