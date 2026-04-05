# Enforced Planning Framework — Roadmap

**Updated:** 2026-04-05
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
| #1 | Capabilities section in plan template | ✅ Complete (template done, pre-commit hook wired as check #6) |

### Phase 3: Truth-Surface Validation (COMPLETE)

**Gate:** Deterministic validator that checks agreement between static declarations and runtime facts.

| Plan | What | Status |
|------|------|--------|
| #4 | First truth-surface drift validator | ✅ Complete |
| #5 | Validator completion (audit parity, renderer) | ✅ Complete |
| #6 | Governed repo adoption pilot | ✅ Complete |
| #8 | Adoption pilot execution sprint | ✅ Complete |
| #9 | Scoped validation by canonical repo identity | ✅ Complete |

### Phase 4: Relationships V2 — Inference + Agent Verification (COMPLETE)

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
| **Pre-commit enforcement** | Hook that validates locked couplings on commit | ✅ Complete (`check_locked_couplings.py` wired into pre-commit, 24 tests) |
| **Agent verification protocol** | Bounded mission spec for "validated" couplings (`Plan #11`) | ✅ Complete (181 tests, shipped) |

### Phase 5: Semantic Review Layer (COMPLETE)

**Gate:** LLM/agent layer that catches semantic drift (stale prose, misleading summaries) that deterministic checks can't express.

| Plan | What | Status |
|------|------|--------|
| #7 | LLM semantic truth-surface review | ✅ Complete (semantic review layer shipped; canonical path now `review_truth_surface_semantic.py`) |
| — | Promote stable LLM findings into deterministic checks | ✅ Complete (`promote_to_deterministic.py`, `make promote`; 3 candidates identified, 3 fixed in this session) |

**Note:** Plan #7 (semantic review) and Plan #11 (agent verification protocol) both complete. Plan #7 specializes the verification pattern established by Plan #11.

**Convergence outcome:** Plan #18 made the config-driven path canonical.
`review_truth_surface_semantic.py` now owns semantic review, append-only review
history, and promotion input. `review_truth_surfaces.py` remains only as a
deprecated compatibility wrapper.

### Phase 6: Cross-Repo Governance (GATE MET — READY TO START)

**Gate:** Multiple repos using V2 relationships.yaml with inference + enforcement + agent verification. Ecosystem-wide dependency map.

| Item | What | Status |
|------|------|--------|
| Cross-repo plan index | Consumable plan registry across all repos | ✅ Complete (327 plans, 22 repos, `make plan-registry`) |
| Ecosystem dependency map | Inference engine run across all active repos | ✅ Complete (22 repos, 14177 edges, 103 cross-repo; `make infer-all && make ecosystem-deps`) |
| Visibility grammar | Bazel-style `__pkg__`/`__subpackages__` for doc governance scope | 📋 Deferred — see `docs/backlog/DEFERRED_FEATURES.md` |
| Distributed governance | Per-directory `.governance.yaml` (Buck2 pattern) | 📋 Deferred — see `docs/backlog/DEFERRED_FEATURES.md` |

### Phase 7: Onboarding Reconciliation (COMPLETE)

**Gate:** GETTING_STARTED.md, README, and pattern docs all align with the canonical operating model and V2 tooling.

| Plan | What | Status |
|------|------|--------|
| #10 | Framework truth-surface and onboarding reconciliation | ✅ Complete |

**Follow-on result:** Plans #16, #17, and #18 completed the second convergence
pass, so the product surface now has one canonical installer story, one
canonical semantic-review path, and a cleaner source-vs-installed doc split.

### Phase 8: Multi-Tool Support and Ecosystem Observability (DESIGN COMPLETE — IMPLEMENTATION NEXT)

**Gate (measurable proxy — verifiable within this repo):**
All three conditions green as of 2026-04-04 overnight sprint:
1. ✅ `.pre-commit-hooks.yaml` integration tested end-to-end — documented in `docs/evidence/phase8_precommit_test.md`
2. ✅ `install.sh --pre-commit` verified in a repo that has no `.claude/` directory — documented in same evidence file
3. ✅ `render_agents_md.py` produces an 84-line AGENTS.md that a Codex agent can navigate — documented in same evidence file

> **Gate outcome**: All three proxy conditions pass. Phase 8 work may begin.
> Evidence committed to `docs/evidence/phase8_precommit_test.md`.

> **Why a proxy gate?** "≥ 3 teams" is unverifiable from inside the repo. The proxy
> gate above tests the same underlying capability (non-Claude-Code adoption is
> possible) with artifacts that can be committed and reviewed here.

| Plan | What | Status |
|------|------|--------|
| #19 | Multi-tool support matrix, support tiers, and rollout policy | ✅ Complete |
| #20 | Governed-repo upgrade automation and registry model | ✅ Complete |
| #21 | Ecosystem dashboard and status surfaces | ✅ Complete |
| #22 | Framework self-measurement and ROI metrics | ✅ Complete |

### Coordination Runtime Surface (PACKAGEIZED — HEALTHY LANE SURFACE)

**Gate:** Live coordination state is package-backed, mechanically consistent,
and readable as bounded active lanes instead of only raw claims.

| Plan | What | Status |
|------|------|--------|
| #24 | Coordination-state packageization and consistency gate | ✅ Complete |
| #25 | Lane model and active-lane registry | ✅ Complete |
| #26 | Claim session auto-hydration and weak-lane remediation | ✅ Complete |
| #27 | V2 worktree entrypoints and claim propagation | ✅ Complete |
| #28 | Stale claim lifecycle and cleanup automation | ✅ Complete |
| #29 | Session heartbeats and agent liveness | ✅ Complete |
| #30 | Session bootstrap contract and tracker | ✅ Complete |
| #31 | Session CLI and governed-repo entrypoint enforcement | ✅ Complete |
| #32 | Cross-tool session adapters and adoption rollout | ✅ Complete |
| #33 | Assignment-layer session contract integration | ✅ Complete |
| #34 | Weak-claim remediation and live-lane migration | ✅ Complete |
| #35 | Queue-based assignment and session routing architecture | 📋 Planned |
| #37 | Plan-bound session identity and resume lifecycle | ✅ Complete |
| #38 | Authority-drift reconciliation gates | ✅ Complete |
| #39 | Worktree-aware markdown-link validation and root resolution | ✅ Complete |
| #40 | Overnight coordination implementation sprint | ✅ Complete |
| #41 | Documentation authority governance and enforcement | ✅ Complete |
| #42 | Atomic closeout and claimed worktree removal | ✅ Complete |

**Deferred item blockers:**

| Item | Blocked By | Would Unblock |
|------|-----------|--------------|
| Multi-tool hook support | No Cursor/Windsurf equivalent of `.claude/hooks/` is publicly documented yet. Unblocks: any non-CC adopter. | Plan #19 support-tier decision + concrete adapter path |
| Adoption automation | Need ≥ 5 governed repos before upgrade automation is worth building. Currently at ~3. | 5+ governed repos |
| Framework self-measurement | Metric definitions are complete, but collection/reporting is not implemented yet. | future implementation slice on top of Plans #21 and #22 |

**Long-term deferred (no near-term consumer):** Visibility grammar and distributed governance moved to `docs/backlog/DEFERRED_FEATURES.md`.

## What's Next (recommended priority order)

1. **Queue/routing architecture freeze**
   Land Plan #35 so future task-queue or assignment work builds on the canonical
   claim/session model instead of creating parallel identity systems.

2. **Mac mini pilot governed-repo rollout**
   Execute the first controlled pilot from `docs/guides/MAC_MINI_CONTINUOUS_AUTOMATION_BOOTSTRAP.md` using a sanctioned worktree lane.

3. **Future implementation slice: ecosystem status renderer and metrics collection**
   Implement `make ecosystem-status`, `generated/ecosystem_status.json`, and rendered operator metrics on top of Plans #21 and #22.

4. **Project-meta topic-research adoption**
   Apply the portable topic-research pattern in `project-meta/research_synthesis`
   with manifests, ADR links, and freshness metadata for high-value topics.

## Design Principles

- **Programmatic for coverage, agents for judgment, humans for direction** (root CLAUDE.md)
- **No "shoulds"** — every validation outcome has a concrete action (fix/escalate/block)
- **Incremental adoption** — repos can use V1 forever; V2 is opt-in with migration path
- **Inference + overrides > exhaustive declarations** — scan first, declare exceptions
- **Stolen patterns** — Pants (inference), Nx (dependsOn), Bazel (dep types) — credited in design doc
