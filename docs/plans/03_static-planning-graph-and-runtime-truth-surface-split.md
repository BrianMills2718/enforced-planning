# Plan #3: Static Planning Graph and Runtime Truth-Surface Split

**Status:** Complete
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** Plan #4

---

## Gap

**Current:** `relationships.yaml` and adjacent linkage docs mostly describe
static governance relationships, but the ecosystem is also trying to reason
about live tracker state, worktrees, claims, reservations, and rollout truth
surfaces. The conceptual boundary between static planning/documentation graph
semantics and runtime coordination state is not stated canonically.

**Target:** The framework explicitly defines:
- one static planning/governance graph with typed edge classes
- one runtime coordination state layer
- one validator layer that checks agreement between them

The plan also specifies how `relationships.yaml` should evolve without becoming
an overloaded store for live runtime facts.

**Why:** The current truth-surface drift problem cannot be solved cleanly by
adding more prose or by stuffing mutable execution state into the static
documentation graph. The architecture needs a clear split before new validation
or enforcement work lands.

---

## References Reviewed

- `patterns/42_planning-hierarchy.md`
- `patterns/15_plan-workflow.md`
- `patterns/36_executable-journey-notebooks.md`
- `templates/plan.md.template`
- `~/projects/project-meta/docs/ops/DOCUMENTATION_PLANNING_LINKAGE_SYSTEM.md`
- `~/projects/project-meta/scripts/relationships.yaml`
- `~/projects/project-meta/docs/ops/AUTHORITATIVE_COORDINATION_ROLLOUT.md`

---

## Files Affected

- `patterns/09_documentation-graph.md` (modify or supersede)
- `scripts/relationships.yaml` (schema note only in this phase)
- `docs/STATIC_GRAPH_AND_RUNTIME_TRUTH.md` (create)
- `templates/relationships.yaml.example` (create or modify if adopted)

---

## Plan

### Steps

1. Define the static graph responsibilities for `relationships.yaml`:
   required reading, update coupling, capability/boundary authority,
   plan/notebook alignment, and optional `verify_sync`.
2. Define the runtime state responsibilities that must remain outside that file:
   active claims, reservations, landing state, worktree state, and tracker phase
   truth.
3. Define a truth-surface validator contract that checks agreement between static
   declarations and runtime state without conflating them.
4. Specify any schema changes needed for the static graph to support the extended
   planning methodology cleanly.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| N/A | N/A | Design-only phase |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | Framework docs/templates remain coherent |

---

## Acceptance Criteria

- [x] The framework states unambiguously which concerns belong in the static
      graph and which belong in runtime coordination state.
- [x] The next schema shape for `relationships.yaml` is defined in typed edge
      classes rather than generic “related docs” semantics.
- [x] The validator layer is described as a separate concern rather than hidden
      inside the static graph.

---

## Open Questions

- [x] Should static-graph edge classes be encoded directly in `relationships.yaml`
      or in a versioned schema document that `relationships.yaml` conforms to?
      - Resolved: encode the edge classes directly in the canonical scaffold and document the semantics separately.
- [x] How much plan/notebook/capability alignment should be encoded in the static
      graph versus discovered from plan parsing?
      - Resolved: encode durable alignment surfaces in the graph; let plan parsing infer transient execution facts.

---

## Notes

This plan is intentionally downstream of Plan #2. The hierarchy/order model must
be canonical before the graph schema is refined around it.
