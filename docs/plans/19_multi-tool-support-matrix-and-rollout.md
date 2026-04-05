# Plan #19: Multi-Tool Support Matrix and Rollout

**Status:** Complete
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** [future] non-Claude-Code governed-repo adoption

---

## Gap

**Current:** The framework now states that Claude Code has the strongest native
support, but it still does not define a canonical support matrix across tools
or what "portable" means by support tier.

**Target:** The framework has one explicit support matrix covering:

- native interactive enforcement
- generated governance surfaces
- deterministic validator portability
- legacy or optional rollout surfaces

**Why:** Without support tiers, adopters cannot tell whether a tool is fully
supported, partially supported, or only compatible at the documentation layer.

---

## References Reviewed

- `README.md` - current framework-source support statement
- `GETTING_STARTED.md` - current installed-consumer support statement
- `hooks/README.md` - current hook portability boundary
- `ROADMAP.md` - Phase 8 queue and gate language
- `docs/evidence/phase8_precommit_test.md` - current proxy evidence for non-Claude-Code adoption
- `docs/plans/16_documentation-and-adoption-surface-convergence.md` - doc-role split and convergence target

---

## Research Basis For This Slice

- `docs/evidence/phase8_precommit_test.md` - current evidence base for the Phase 8 proxy gate
- No additional research beyond References Reviewed.

---

## Capabilities

N/A - internal framework design slice; does NOT cross project boundaries or
create callable capability surfaces.

---

## Files Affected

- ROADMAP.md (modify)
- README.md (modify)
- GETTING_STARTED.md (modify)
- hooks/README.md (modify)
- docs/designs/PHASE8_TOOL_SUPPORT_MATRIX.md (create)
- docs/plans/19_multi-tool-support-matrix-and-rollout.md (modify)
- docs/plans/CLAUDE.md (modify if status changes)

---

## Plan

### Steps

1. Define the support tiers the framework will use (`native`, `portable`,
   `legacy`, `unsupported` or equivalent).
2. Define which framework features belong to each tier:
   - read-gating
   - generated `AGENTS.md`
   - deterministic validators
   - raw git-hook rollout
   - semantic review
3. Decide what evidence is required before a tool can move from one tier to
   another.
4. Document the matrix in one canonical design/doc surface.
5. Rewrite top-level docs against that matrix so "portable" has one meaning.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `scripts/self_test.py` or successor | support-matrix doc assertions | Top-level docs reference the same support-tier language |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/19_multi-tool-support-matrix-and-rollout.md --warn-only` | Plan remains valid |
| `python scripts/self_test.py` | Documentation surfaces remain coherent after support-matrix changes |

---

## Acceptance Criteria

- [x] One support-tier vocabulary exists
- [x] `README.md`, `GETTING_STARTED.md`, and `hooks/README.md` use the same support matrix
- [x] The framework defines what evidence is needed to claim support for another tool
- [x] The roadmap points to the numbered plan rather than a vague multi-tool bucket
- [x] Declared checks pass

---

## Decision

The canonical support tiers are:

- `native-interactive`
- `portable-governed`
- `legacy-compatible`
- `unsupported`

Claude Code is currently the only `native-interactive` tool. Other tools should
not be claimed beyond `portable-governed` until a concrete workflow and
committed evidence artifact exist.
