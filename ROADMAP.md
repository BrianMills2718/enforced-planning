# Enforced Planning Framework — Roadmap

**Updated:** 2026-04-02
**Canonical methodology:** `PLANNING_OPERATING_MODEL.md`

## Vision

A portable framework where:
- Programmatic checks catch structural governance violations exhaustively
- Agents verify semantic drift and fix or escalate — no "warn and hope"
- Humans set direction, review escalations, and make architectural decisions
- Every repo in the ecosystem can adopt incrementally without big-bang migration

## Phase Map

### Phase 1: Core Framework (COMPLETE)

**Gate:** Portable patterns, templates, and scripts that any repo can install.

| Plan | What | Status |
|------|------|--------|
| — | 27 patterns + opt-in modules | ✅ Shipped (pre-extraction) |
| — | Plan template with acceptance criteria, tests, capabilities | ✅ Shipped |
| — | Read-gating hooks, doc-code coupling, git hooks | ✅ Shipped |
| — | `install.sh` for governed repo bootstrap | ✅ Shipped |

### Phase 2: Canonical Methodology (COMPLETE)

**Gate:** Single source of truth for the planning artifact dependency graph.

| Plan | What | Status |
|------|------|--------|
| #2 | Planning Operating Model (canonical methodology) | ✅ Complete |
| #3 | Static Graph / Runtime Truth split | ✅ Complete |
| #1 | Capabilities section in plan template | 🚧 Partial (template done, pre-commit hook pending) |

### Phase 3: Truth-Surface Validation (COMPLETE)

**Gate:** Deterministic validator that checks agreement between static declarations and runtime facts.

| Plan | What | Status |
|------|------|--------|
| #4 | First truth-surface drift validator | ✅ Complete |
| #5 | Validator completion (audit parity, renderer) | ✅ Complete |
| #6 | Governed repo adoption pilot | ✅ Complete |
| #8 | Adoption pilot execution sprint | ✅ Complete |
| #9 | Scoped validation by canonical repo identity | ✅ Complete |

### Phase 4: Relationships V2 — Inference + Agent Verification (IN PROGRESS)

**Gate:** Dependency inference engine running in CI; agent verification protocol for "validated" couplings; no "soft/warn" tier.

| Item | What | Status |
|------|------|--------|
| Design doc | `docs/designs/RELATIONSHIPS_V2_DESIGN.md` | ✅ Complete |
| Plan dep format | `#N`, `project#N`, `[future]` in template + `check_plan_deps.py` | ✅ Complete |
| Inference engine | `infer_dependencies.py` — markdown links, imports, plan refs | ✅ Complete |
| V2 schema | `relationships.yaml` V2 with locked/generated/validated types | ✅ Complete |
| Migration script | `migrate_relationships.py` V1→V2 | ✅ Complete |
| Tests | 149 tests (42 new for V2 tools) | ✅ Complete |
| Self-import filter | Inference skips repo's own package imports | ✅ Complete |
| Makefile targets | `make infer`, `make check-deps`, `make check-caps`, `make migrate-rels` | ✅ Complete |
| **V2 adoption pilot** | Migrate a real governed repo's relationships.yaml to V2 | ✅ Complete (llm_client: 4 couplings migrated, 425 inferred edges, read-gate verified) |
| **Pre-commit enforcement** | Hook that validates locked couplings on commit | 📋 Planned |
| **Agent verification protocol** | Bounded mission spec for "validated" couplings (`Plan #11`) | ✅ Complete (181 tests, shipped) |

### Phase 5: Semantic Review Layer (PLANNED)

**Gate:** LLM/agent layer that catches semantic drift (stale prose, misleading summaries) that deterministic checks can't express.

| Plan | What | Status |
|------|------|--------|
| #7 | LLM semantic truth-surface review | ✅ Complete (207 tests, review_truth_surfaces.py shipped) |
| — | Promote stable LLM findings into deterministic checks | 📋 Planned (promotion_candidate field tracks this) |

**Dependency:** Phase 4 agent verification protocol should be designed first — Plan #7 is a specialization of the same pattern (agent verifies coupling, reports finding).

### Phase 6: Cross-Repo Governance (PLANNED)

**Gate:** Multiple repos using V2 relationships.yaml with inference + enforcement + agent verification. Ecosystem-wide dependency map.

| Item | What | Status |
|------|------|--------|
| Cross-repo plan index | Consumable plan registry across all repos | 📋 Planned |
| Visibility grammar | Bazel-style `__pkg__`/`__subpackages__` for doc governance scope | 📋 Deferred |
| Distributed governance | Per-directory `.governance.yaml` (Buck2 pattern) | 📋 Deferred |
| Ecosystem dependency map | Inference engine run across all active repos | ✅ Prototype (10 repos scanned) |

### Phase 7: Onboarding Reconciliation (COMPLETE)

**Gate:** GETTING_STARTED.md, README, and pattern docs all align with the canonical operating model and V2 tooling.

| Plan | What | Status |
|------|------|--------|
| #10 | Framework truth-surface and onboarding reconciliation | ✅ Complete |

## What's Next (recommended priority order)

1. ~~**Phase 4: V2 adoption pilot**~~ ✅ Done — llm_client migrated, read-gate verified, inferred_deps.json committed.

2. **Phase 4: Agent verification protocol** — Plan #11 written. Implement `verify_coupling.py`, prompt template, fix applicator, `make verify-couplings`. This unblocks both Phase 5 (semantic review) and the "no shoulds" enforcement model.

3. ~~**Phase 5: Plan #7**~~ ✅ Done — review_truth_surfaces.py shipped with 26 tests.

4. ~~**Phase 7: Plan #10**~~ ✅ Done — installer, GETTING_STARTED, Plan #1, Plans #6/#8 all reconciled.

5. **Phase 6: Cross-repo governance** — Only after V2 is proven in 3+ repos.

## Design Principles

- **Programmatic for coverage, agents for judgment, humans for direction** (root CLAUDE.md)
- **No "shoulds"** — every validation outcome has a concrete action (fix/escalate/block)
- **Incremental adoption** — repos can use V1 forever; V2 is opt-in with migration path
- **Inference + overrides > exhaustive declarations** — scan first, declare exceptions
- **Stolen patterns** — Pants (inference), Nx (dependsOn), Bazel (dep types) — credited in design doc
