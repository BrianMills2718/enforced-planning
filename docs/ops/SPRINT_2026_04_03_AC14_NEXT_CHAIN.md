# Sprint: AC14 Front-Half-First Chain

**Created:** 2026-04-03
**Scope:** `/home/brian/projects/ac14/`
**Session type:** Continuous autonomous execution — NEVER STOP

---

## Context

AC14 is a decomposition-first coding-agent thesis project. After gate 2
(`monolithic_wins`, decisive loss), the active thesis pivot is
**front-half-first**: prove AC14's discovery/draft/freeze chain can produce
valid structured-spec artifacts before comparing back-half generation.

**Current state:** Plan #90 is IN PROGRESS. The first front-half-first smoke
gate (`front_half_first_smoke_1`) returned `blocked_on_front_half`. Diagnosis
(Plan #89) identified two concrete blockers:

1. **AC14 side:** `_validate_draft_blueprint_plan()` raises on invalid bindings
   (unknown components/ports) immediately, with no persisted diagnostics and no
   retry — wasting the smoke budget and leaving nothing for diagnosis.
2. **Monolithic side:** Generated `run_case(record)` systems access
   `record["source_port_name"]` instead of using `record` directly — a nested
   source-port contract mistake.

---

## 24-Hour Plan (ordered, each phase explicitly bounded)

### Phase 1 — Complete Plan #90: Contract and Observability Repair

**Goal:** Fix both blockers so Plan #91's smoke rerun tests repaired code, not the same bugs.

**Acceptance criteria (all four must be green before moving to Phase 2):**
- [ ] Invalid structured-spec draft-plan responses persist `failed_draft_plan_diagnostics_{attempt}.json` before exiting
- [ ] One bounded repair retry loop exists: if attempt 1 fails validation, call LLM again with binding errors in prompt context; fail after attempt 2 with persisted diagnostics
- [ ] Monolithic runtime contract: prompt explicitly states `run_case(record)` takes the raw record dict directly; validator or runtime wraps KeyError with a clear contract error message
- [ ] Targeted tests cover both new surfaces (diagnostics persist, retry triggers, monolithic contract error)

**Files to modify:**
- `ac14/blueprint_planning.py` — repair loop + diagnostics persistence
- `prompts/draft_blueprint_plan_from_structured_spec.yaml` — add `binding_errors` slot
- `ac14/front_half_first_empirical.py` — clearer runtime contract error
- `prompts/generate_monolithic_runtime_system_from_structured_spec.yaml` — explicit `record` guidance
- `tests/test_blueprint_planning.py` — diagnostics + retry tests
- `tests/test_front_half_first_empirical.py` — contract error test

**Verification command:**
```bash
python -m pytest -q tests/test_blueprint_planning.py tests/test_front_half_first_empirical.py tests/test_cli.py tests/test_make_targets.py && python -m mypy ac14 tests && python -m ruff check ac14 tests
```

**Commit:** `[Plan #90] contract repair: diagnostics persist + monolithic raw-record guard`

---

### Phase 2 — Run Plan #91: Front-Half-First Smoke Rerun

**Goal:** One fresh smoke artifact after the Plan #90 repairs.

**Acceptance criteria:**
- [ ] A new smoke artifact exists at `.ac14_out/front_half_first_smoke_2/smoke_readiness_report.json`
- [ ] Verdict is explicit: one of `ready_for_full_trials`, `blocked_on_front_half`, `blocked_on_harness`
- [ ] Next branch is explicit in TODO.md

**Execution command (from ac14/):**
```bash
make front-half-first-smoke  # or python -m ac14.cli front-half-first-smoke ...
```

**Branch logic (pre-decided, no deliberation):**
- `ready_for_full_trials` → immediately proceed to Phase 3a (Plan #88 full trial)
- `blocked_on_front_half` or `blocked_on_harness` → immediately proceed to Phase 3b (Plan #92 blocker boundary)

**Commit:** `[Plan #91] front-half-first smoke rerun — verdict: {actual verdict}`

---

### Phase 3a (conditional) — Run Plan #88: Full Trial Gate

**Activates only if Phase 2 verdict is `ready_for_full_trials`.**

**Acceptance criteria:**
- [ ] Full front-half-first trial artifact set exists
- [ ] Final empirical verdict is persisted explicitly
- [ ] Story surfaces (CLAUDE.md, TODO.md, AC14_NEXT_24_HOURS.md) updated from verdict

**Commit:** `[Plan #88] front-half-first full trial — verdict: {actual verdict}`

---

### Phase 3b (conditional) — Freeze Plan #92: Second Blocker Boundary

**Activates only if Phase 2 verdict is `blocked_*`.**

**Acceptance criteria:**
- [ ] One explicit blocker-boundary artifact exists citing the Phase 2 smoke artifact
- [ ] Next move is explicit and claim-bounded
- [ ] Full-trial budget remains closed

**Commit:** `[Plan #92] second blocker boundary — {summary of blockers}`

---

## Decisions Pre-Made (no stopping for these)

| Decision | Choice |
|----------|--------|
| Retry budget for structured-spec planning | 2 attempts max |
| Failed diagnostics filename pattern | `failed_draft_plan_diagnostics_{attempt}.json` |
| Smoke run output dir for Plan #91 | `.ac14_out/front_half_first_smoke_2/` |
| Monolithic guardrail: static or runtime | Runtime: wrap KeyError + update prompt |
| Full trial budget (Plan #88) | 5 trials, standard pattern |

## Stop Conditions (only these two apply)

1. An irresolvable thesis contradiction (not a bug, a real contradiction to the decomposition thesis)
2. An irreversible action affecting shared state (force push to main, etc.)

**Everything else is not a stop condition.** Test failure → fix and continue. Smoke blocked → branch to Phase 3b. Uncertainty → log and continue.
