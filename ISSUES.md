# Enforced Planning — Issue Tracker

Observed problems, concerns, and technical debt for the **enforced-planning** framework itself.

Items start as **unconfirmed** observations and get triaged into confirmed issues, plans, or dismissed.

**Last reviewed:** 2026-04-04

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

(No open framework documentation or planning-governance issues are currently tracked here.)

---

## Resolved

### MP-003: Large scripts untested

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

Dedicated test files now exist for the plan/governance scripts that previously
lacked direct coverage, including `parse_plan.py`, `complete_plan.py`,
`sync_plan_status.py`, and `check_plan_tests.py`.

---

### MP-004: Claude-Code-specific hooks not disclosed in README

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | low |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

The top-level docs now explicitly describe the support matrix: Claude Code has
the strongest native hook surface, while other tools use generated `AGENTS.md`
and deterministic validators.

---

### MP-005: meta-process.yaml.example has unimplemented config keys

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | low |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

The config surface is now split: `templates/meta-process.yaml.example` is the
minimal functional starter surface, while
`templates/meta-process.future.yaml.example` carries broader planned/advisory
vocabulary.

---

### MP-006: TRAYCER_COMPARISON.md at wrong location

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | low |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

The repo root no longer carries the stray research document that triggered this
issue.

---

### MP-007: Planning hierarchy defined in 3+ places with variations

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

`PLANNING_OPERATING_MODEL.md` is now explicitly canonical, Pattern 42 is the
compressed view, and the adoption docs point back to the canonical source
instead of trying to redefine the hierarchy independently.

---

### MP-008: docs/ops/ has stale sprint documents cluttering root

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | low |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

The earlier `OVERNIGHT_SPRINT_*` and `TRUTH_SURFACE_*_TODO` clutter was moved
out of the root operator surface. Remaining `docs/ops/` files are a much
smaller set of operator artifacts and sprint records.

---

### MP-011: Adoption docs disagree on installed paths, config keys, and support model

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | high |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

`README.md`, `GETTING_STARTED.md`, `docs/guides/NEW_PROJECT_SETUP.md`, and
`hooks/README.md` now agree on the canonical installer, installed paths,
support matrix, and config vocabulary.

---

### MP-012: Top-level docs still over-center `agent_ecology2`

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

Top-level docs now keep `agent_ecology2` as provenance only instead of using it
as the explanatory frame for adoption.

---

### MP-013: Roadmap and plan queue do not form a compendious forward-looking status surface

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

The roadmap and plan index now expose the live execution queue directly instead
of relying on stale "what's next" prose.

---

### MP-009: Installer authority split between `install.sh` and `install_governed_repo.py`

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | high |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

`scripts/install_governed_repo.py` is now the canonical governed-repo
installer/upgrader. `install.sh` delegates the default path and clearly scopes
legacy compatibility modes.

---

### MP-010: Two live semantic truth-surface review stacks

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | high |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

The config-driven semantic review path is now canonical:
`scripts/review_truth_surface_semantic.py --config ...`. The repo-wide
`review_truth_surfaces.py` path remains only as a deprecated compatibility
wrapper, and promotion now consumes canonical append-only review history.

---

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
