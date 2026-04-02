# Plan #10: Framework Truth-Surface and Onboarding Reconciliation

**Status:** In Progress
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** cleaner consumer adoption, Plan #7 execution sprint

---

## Gap

**Current:** The canonical methodology docs are strong, but the framework still
has a few operator-facing truth regressions:

- onboarding docs tell consumers to run truth-surface tools that `install.sh`
  does not install
- README describes an installed repo structure that the installer does not
  create
- completed scope-sprint surfaces still disagree about whether the slice is
  fully committed
- Plan #1 remains framed around the older "Data Boundaries" wording instead of
  the newer capability/boundary model

**Target:** The framework's installer, onboarding docs, active/complete truth
surfaces, and backlog language all agree with the actual code and current
methodology.

**Why:** `enforced-planning` cannot ask governed repos to trust truth-surface
discipline if its own onboarding and status surfaces still drift from runtime
reality.

---

## References Reviewed

- `CLAUDE.md`
- `README.md`
- `GETTING_STARTED.md`
- `install.sh`
- `PLANNING_OPERATING_MODEL.md`
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md`
- `docs/plans/01_boundary_enforcement.md`
- `docs/plans/06_governed-repo-truth-surface-adoption-pilot.md`
- `docs/plans/08_truth-surface-adoption-pilot-execution-sprint.md`
- `docs/plans/09_scoped-truth-surface-validation.md`
- `docs/plans/CLAUDE.md`
- `docs/ops/OVERNIGHT_SPRINT_2026_04_02_SCOPE.md`
- `docs/ops/TRUTH_SURFACE_SCOPE_TODO.md`
- `templates/truth_surface_drift.yaml.example`

---

## Files Affected

- `CLAUDE.md`
- `README.md`
- `GETTING_STARTED.md`
- `install.sh`
- `templates/truth_surface_drift.yaml.example`
- `docs/plans/01_boundary_enforcement.md`
- `docs/plans/06_governed-repo-truth-surface-adoption-pilot.md`
- `docs/plans/08_truth-surface-adoption-pilot-execution-sprint.md`
- `docs/plans/10_framework-truth-surface-and-onboarding-reconciliation.md`
- `docs/plans/CLAUDE.md`
- `docs/ops/OVERNIGHT_SPRINT_2026_04_02_FRAMEWORK_RECONCILIATION.md`
- `docs/ops/TRUTH_SURFACE_FRAMEWORK_RECONCILIATION_TODO.md`
- `docs/ops/TRUTH_SURFACE_SCOPE_TODO.md`

---

## Plan

### Phase A — Sprint Contract and Scope Freeze

Success criteria:
- one active sprint tracker exists and is referenced by root `CLAUDE.md`
- the scope is limited to framework truth/onboarding reconciliation, not Plan #7
- any pre-existing unrelated dirt is explicitly left untouched

### Phase B — Installer and Onboarding Truth

Success criteria:
- docs truthfully describe how a consumer repo gets truth-surface tooling
- installer behavior and docs agree on installed files and invocation paths
- the truth-surface template guidance is generic enough for consumer reuse

### Phase C — Internal Truth-Surface Reconciliation

Success criteria:
- stale TODO/tracker items from the scoped-validation sprint are corrected
- Plans #6 and #8 note the scoped follow-on truthfully
- the framework no longer contains obvious self-contradictions about completed work

### Phase D — Backlog Truth and Handoff

Success criteria:
- Plan #1 is reframed around the current capability/boundary model
- `docs/plans/CLAUDE.md` stays consistent with actual remaining work
- the next step after this sprint is explicit and bounded

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| N/A | docs/install reconciliation | This slice is doc/install truth reconciliation rather than new runtime behavior |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | Framework references/templates must remain internally consistent |
| `git diff --check` | Doc/template edits stay structurally clean |

---

## Acceptance Criteria

- [ ] Root `CLAUDE.md` points to this sprint while it is active.
- [ ] README and getting-started guidance match the real installer behavior.
- [ ] The installer copies or clearly delegates any truth-surface assets the docs tell adopters to use.
- [ ] Scoped-sprint tracker/TODO surfaces are truthfully closed.
- [ ] Plans #6 and #8 reflect the measured scoped follow-on instead of freezing at the pre-scope recommendation.
- [ ] Plan #1 is restated in the current capability/boundary vocabulary.
- [ ] The next bounded follow-on after this cleanup is explicit.

---

## Open Questions

- [ ] Should truth-surface scripts be installed directly into governed repos, or should the framework docs switch to framework-root invocation instead?
      - Working assumption for this sprint: install the truth-surface scripts and template into governed repos so the docs remain repo-local and operational.
