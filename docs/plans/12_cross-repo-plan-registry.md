# Plan #12: Cross-Repo Plan Registry and Ecosystem Dependency Map

**Status:** Complete
**Type:** feature
**Priority:** Medium
**Blocked By:** #11 — agent verification protocol (Phase 4 complete)
**Blocks:** check_plan_deps cross-repo resolution

---

## Gap

**Current:** Each governed repo maintains its own `docs/plans/CLAUDE.md` plan index.
No tooling exists to query plans across all repos, identify cross-repo plan dependencies,
or build an ecosystem-level picture of what work exists and where.

**Target:** Two complementary tools:
1. `build_plan_registry.py` — cross-repo plan table parser that produces a unified JSON
   registry of every plan across all governed repos
2. `build_ecosystem_dep_map.py` — cross-repo dependency aggregator that aggregates
   per-repo `inferred_*.json` files into an ecosystem-level dependency graph

**Why:** As the framework scales to 20+ repos, manual cross-repo coordination becomes
error-prone. The registry enables dependency validation across repo boundaries
(`check_plan_deps.py` can resolve `project#N` references). The dep map identifies
ecosystem backbone components (repos with many inbound edges — breaking them breaks
everything).

---

## Acceptance Criteria

- [x] `build_plan_registry.py` scans all repos marked with meta-process.yaml
- [x] Registry output is consumable JSON: `{plans: [{repo, number, title, status, blocks}]}`
- [x] `make plan-registry` target produces registry
- [x] `build_ecosystem_dep_map.py` aggregates per-repo inferred_*.json files
- [x] Dep map identifies cross-repo edges
- [x] `make ecosystem-deps` target produces dep map
- [x] Tests cover both scripts

---

## Implementation

### Scripts Shipped

**`scripts/build_plan_registry.py`**
- Scans governed repos via `GOVERNED_REPO_MARKER = "meta-process.yaml"`
- Parses `docs/plans/CLAUDE.md` plan tables via regex `PLAN_ROW_RE`
- Produces `generated/plan_registry.json`: `{repos, total_plans, plans: [...]}`
- CLI: `python build_plan_registry.py --roots ~/projects --output generated/plan_registry.json`

**`scripts/build_ecosystem_dep_map.py`**
- Aggregates per-repo `generated/inferred_*.json` files across all governed repos
- Builds `dep_graph` (source → targets) and `reverse_graph` (target → sources)
- Identifies cross-repo edges (source_repo ≠ target_repo)
- Produces `generated/ecosystem_dep_map.json`
- CLI: `python build_ecosystem_dep_map.py --roots ~/projects --output generated/ecosystem_dep_map.json`

### Makefile Targets Added

```makefile
plan-registry:   ## Build cross-repo plan registry (generated/plan_registry.json)
infer-all:       ## Run dependency inference across all governed repos
ecosystem-deps:  ## Build ecosystem dependency map (generated/ecosystem_dep_map.json)
```

---

## Results (at completion)

- **Plan registry:** 330 plans, 22 repos
- **Ecosystem dep map:** 14,177 edges total, 103 cross-repo edges
- **Ecosystem backbone:** `llm_client` identified as highest-centrality node (94 inbound
  edges from 12 repos) — breaking it breaks all 12 dependents
- **Generated files:** `generated/` is gitignored; re-generate with `make plan-registry`
  and `make ecosystem-deps`

---

## References

- `scripts/build_plan_registry.py` — plan registry builder
- `scripts/build_ecosystem_dep_map.py` — ecosystem dep map aggregator
- `ROADMAP.md` Phase 6 — Cross-Repo Governance
- `docs/designs/RELATIONSHIPS_V2_DESIGN.md` — V2 schema (validated couplings, inference)
