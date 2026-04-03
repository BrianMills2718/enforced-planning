# Enforced Planning — Issue Tracker

Observed problems, concerns, and technical debt for the **enforced-planning** framework itself.

Items start as **unconfirmed** observations and get triaged into confirmed issues, plans, or dismissed.

**Last reviewed:** 2026-04-03

---

## Status Key

| Status | Meaning | Next Step |
|--------|---------|-----------|
| `unconfirmed` | Observed, needs investigation | Investigate to confirm/dismiss |
| `monitoring` | Confirmed concern, watching for signals | Watch for trigger conditions |
| `confirmed` | Real problem, needs a fix | Create a plan |
| `planned` | Has a plan (link to plan) | Implement |
| `resolved` | Fixed | Record resolution |
| `dismissed` | Investigated, not a real problem | Record reasoning |

---

## Open

### MP-003: Large scripts untested

| Field | Value |
|-------|-------|
| Status | `planned` |
| Severity | medium |
| Reported | 2026-04-03 |

`complete_plan.py` (597 lines), `parse_plan.py` (438 lines), `sync_plan_status.py` (456 lines),
and `check_plan_tests.py` (552 lines) have no dedicated test files. If they break, no CI catch.

**Plan:** Phase 6 of sprint `docs/ops/SPRINT_2026_04_03_ALL_ISSUES.md` — 35+ tests across the
three highest-priority scripts.

---

### MP-004: Claude-Code-specific hooks not disclosed in README

| Field | Value |
|-------|-------|
| Status | `planned` |
| Severity | low |
| Reported | 2026-04-03 |

README calls the framework "portable" and lists "Claude Code, etc." as tool-compatible.
The "etc." is empty — hooks (`.claude/hooks/`), CLAUDE.md convention, and read-gating are
all Claude Code-specific. Cursor/Windsurf users will hit a dead end.

**Plan:** Phase 2c of sprint — explicit tool compatibility callout in README and GETTING_STARTED.

---

### MP-005: meta-process.yaml.example has unimplemented config keys

| Field | Value |
|-------|-------|
| Status | `planned` |
| Severity | low |
| Reported | 2026-04-03 |

Several keys in `meta-process.yaml.example` are not consumed by any script:
`planning.question_driven_planning`, `planning.uncertainty_tracking`,
`planning.dependency_probe_policy`, `capability_ownership.*`, `messaging.*`.
Adopters copy them and get placebo configuration.

**Plan:** Phase 2d of sprint — audit every key, mark unimplemented ones `# [PLANNED]`.

---

### MP-006: TRAYCER_COMPARISON.md at wrong location

| Field | Value |
|-------|-------|
| Status | `planned` |
| Severity | low |
| Reported | 2026-04-03 |

Research document sitting at repo root alongside framework docs.

**Plan:** Phase 2b of sprint — move to `docs/research/TRAYCER_COMPARISON.md`.

---

### MP-007: Planning hierarchy defined in 3+ places with variations

| Field | Value |
|-------|-------|
| Status | `planned` |
| Severity | medium |
| Reported | 2026-04-03 |

PLANNING_OPERATING_MODEL.md (143 lines), Pattern 42, and GETTING_STARTED.md all define
the planning hierarchy. Each has slight variations. Adopters disagree on which is canonical.

**Plan:** Phase 3 of sprint — POM becomes explicitly canonical; Pattern 42 reduced to summary;
GETTING_STARTED leads with POM.

---

### MP-008: docs/ops/ has stale sprint documents cluttering root

| Field | Value |
|-------|-------|
| Status | `planned` |
| Severity | low |
| Reported | 2026-04-03 |

9 `OVERNIGHT_SPRINT_*.md` and `TRUTH_SURFACE_*_TODO.md` files in `docs/ops/` are closed
work artifacts that create noise when reading the directory.

**Plan:** Phase 2a of sprint — move all to `docs/ops/archive/`.

---

## Resolved

### MP-001: Plan #12 file missing from docs/plans/

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-03 |
| Resolved | 2026-04-03 |

`docs/plans/CLAUDE.md` index listed Plan #12 as complete but the file didn't exist.
**Fix:** Created `docs/plans/12_cross-repo-plan-registry.md` (Phase 1b of sprint).

---

### MP-002: verify_coupling.py API mismatch

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | high |
| Reported | 2026-04-03 |
| Resolved | 2026-04-03 |

`_load_llm_client()` imported `from llm_client import complete` which doesn't exist.
Same bug previously fixed in `review_truth_surfaces.py`.
**Fix:** Changed to `call_llm_structured`; updated `verify_coupling()` to use `response_model=`
and unpack `(judgment, _llm_result)` tuple. Updated 3 test mocks. 288 tests pass.

---

## Dismissed

(No dismissed items yet.)
