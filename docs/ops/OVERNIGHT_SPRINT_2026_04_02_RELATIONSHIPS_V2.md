# Overnight Sprint — 2026-04-02 — Relationships V2 Implementation

**Status:** Active
**Owner:** claude-code
**Started:** 2026-04-02 10:45 PDT
**Design doc:** `docs/designs/RELATIONSHIPS_V2_DESIGN.md`
**Scope:** enforced-planning, ecosystem-ops, data_contracts (NOT project-meta — claimed by another agent)

## Operating Rule

**NEVER STOP.** A completed phase is not a stop condition. Update this tracker,
commit the slice, and move to the next phase immediately.

Only stop for:
- irreversible high-blast-radius action
- genuine architectural decision not covered here

## Acceptance Criteria (sprint complete when ALL green)

- [ ] Plan dependency format standard in template (`#N`, `project#N`, `[future]`)
- [ ] Plan dependency checker validates format (check_plan_deps.py)
- [ ] Dependency inference engine scans markdown links, imports, plan refs
- [ ] Inference engine tested on enforced-planning + ecosystem-ops repos
- [ ] relationships.yaml V2 schema defined with coupling types (locked/generated/validated)
- [ ] Migration script converts V1 → V2 format
- [ ] enforced-planning test suite expanded to ≥25 tests
- [ ] Cross-doc consistency: root CLAUDE.md references PLANNING_OPERATING_MODEL.md
- [ ] All changes committed and pushed
- [ ] All tests pass in modified repos

---

## Phase Stack

### Phase 0 — Sprint setup
**Status:** ✅ COMPLETE
Write this tracker, update CLAUDE.md pointer.

### Phase 1 — Plan dependency format in template + checker
**Status:** not started
**Repos:** enforced-planning
**Pass when:** Template has structured dep format, checker validates it

Pre-made decisions:
- Format: `#N` (same project), `project#N` (cross-project), `[future]` (conceptual)
- Optional condition after `—` dash (human-readable, not parsed)
- Checker: new script `scripts/check_plan_deps.py`
- Validates: `#N` resolves to existing plan, `project#N` resolves, `[future]` tracked as metadata
- Run against enforced-planning plans + ecosystem-ops plans as test

Steps:
1. Update `templates/plan.md.template` Blocked By/Blocks format
2. Create `scripts/check_plan_deps.py`
3. Test against existing plans
4. Commit

### Phase 2 — Dependency inference engine (Layer 1)
**Status:** not started
**Repos:** enforced-planning
**Pass when:** `scripts/infer_dependencies.py` produces JSON graph from any repo

Pre-made decisions:
- Python script, ~200-400 lines
- Scans: markdown links, file path strings, import statements, plan refs (`Plan #N`, `ADR-N`)
- Output: JSON file with inferred edges `{source, target, type, evidence}`
- Inline suppression: `<!-- governance: no-dep -->` or `# governance: no-dep`
- CLI: `python scripts/infer_dependencies.py /path/to/repo [--output inferred.json]`
- Does NOT require relationships.yaml to exist — pure inference

Steps:
1. Create `scripts/infer_dependencies.py`
2. Implement markdown link scanner
3. Implement import statement scanner
4. Implement plan reference scanner
5. Implement inline suppression
6. Test on enforced-planning repo
7. Test on ecosystem-ops repo
8. Commit

### Phase 3 — relationships.yaml V2 schema + migration
**Status:** not started
**Repos:** enforced-planning
**Pass when:** V2 schema documented, migration script works on real files

Pre-made decisions:
- Schema: version 2 with `coupling_types:` and `overrides:` sections
- Three types: locked (block commit), generated (run command), validated (agent verify)
- Migration: read V1, add `type: locked` as default for existing couplings
- `scripts/migrate_relationships.py` — reads V1, writes V2
- Test with project-meta's relationships.yaml as input (read-only, don't modify — claimed repo)

Steps:
1. Define V2 schema in a schema doc or as Pydantic model
2. Create `scripts/migrate_relationships.py`
3. Test migration on project-meta's file (read-only)
4. Create example V2 file for enforced-planning itself
5. Commit

### Phase 4 — Expand enforced-planning test suite
**Status:** not started
**Repos:** enforced-planning
**Pass when:** ≥25 tests, all passing, edge cases covered

Pre-made decisions:
- Focus on new scripts: check_plan_deps.py, infer_dependencies.py, migrate_relationships.py
- Also cover: check_plan_capabilities.py, check_truth_surface_drift.py
- Edge cases: empty plans, circular deps, missing fields, malformed refs
- Use pytest, test files in tests/

Steps:
1. Check current test count
2. Write tests for check_plan_deps.py
3. Write tests for infer_dependencies.py
4. Write tests for migrate_relationships.py
5. Run full suite
6. Commit

### Phase 5 — Integration: run inference on real repos
**Status:** not started
**Repos:** enforced-planning, ecosystem-ops
**Pass when:** Inferred graph for 2+ repos exists and shows real dependencies

Steps:
1. Run inference on enforced-planning — verify output
2. Run inference on ecosystem-ops — verify output
3. Compare inferred deps to manually declared deps — report coverage
4. Commit results as example output

### Phase 6 — Cross-document consistency fixes
**Status:** not started
**Repos:** root CLAUDE.md, enforced-planning
**Pass when:** Root CLAUDE.md references PLANNING_OPERATING_MODEL.md

Steps:
1. Add reference in root CLAUDE.md "How to Build" section
2. Check for other stale references
3. Commit

### Phase 7 — Coordination TTL update
**Status:** not started
**Pass when:** Default claim TTL is 24h, not 2h

Steps:
1. Find TTL config in ~/.claude/coordination/ or claim-writing scripts
2. Update default
3. Document

### Phase 8 — Final verification and push
**Status:** not started
**Pass when:** All repos pushed, all tests pass, tracker green

Steps:
1. Run tests in enforced-planning
2. Run tests in ecosystem-ops
3. Push all repos
4. Update this tracker

---

## Open Uncertainties (log here, don't block)

- Import statement scanning may need to handle relative imports specially
- Coordination TTL may be hardcoded in Claude Code internals, not configurable
- V2 migration may need to handle edge cases in existing relationships.yaml files

---

## Progress Log

| Time (PDT) | Phase | What |
|-------------|-------|------|
| 10:45 | 0 | Sprint started, tracker written |
