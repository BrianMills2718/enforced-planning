# Plan #20: Governed-Repo Upgrade Automation

**Status:** Complete
**Type:** design
**Priority:** High
**Blocked By:** None
**Blocks:** [future] governed-repo fleet upgrades

---

## Gap

**Current:** The framework has a canonical installer/upgrader for one repo at a
time, but it does not yet define the governed-repo registry, upgrade workflow,
or safety model for rolling framework updates across multiple repos.

**Target:** The framework has one bounded upgrade-automation design:

- how governed repos are registered or discovered
- how versioned upgrades are applied
- how dry-run, drift review, and rollback are handled
- what remains source-of-truth in the framework repo vs in consumer repos

**Why:** Once multiple repos adopt the framework, manual one-off upgrade work
will become the new source of drift.

---

## References Reviewed

- `scripts/install_governed_repo.py` - current canonical installer/upgrader
- `install.sh` - current convenience and legacy wrapper modes
- `README.md` - current installer authority language
- `GETTING_STARTED.md` - current governed-repo contract
- `ROADMAP.md` - Phase 8 adoption-automation placeholder
- `docs/plans/17_governed-repo-installer-convergence.md` - installer convergence decisions

---

## Research Basis For This Slice

- `docs/plans/17_governed-repo-installer-convergence.md` - defines the current installer authority and mode split
- No additional research beyond References Reviewed.

---

## Capabilities

N/A - internal framework design slice; does NOT cross project boundaries or
create callable capability surfaces.

---

## Files Affected

- ROADMAP.md (modify)
- README.md (modify)
- scripts/install_governed_repo.py (modify in later implementation slices)
- docs/designs/GOVERNED_REPO_UPGRADE_AUTOMATION.md (create)
- docs/plans/20_governed-repo-upgrade-automation.md (modify)
- docs/plans/CLAUDE.md (modify if status changes)

---

## Plan

### Steps

1. Define the registry/discovery model for governed repos.
2. Define the upgrade contract:
   - dry-run
   - apply
   - drift report
   - rollback expectations
3. Decide whether upgrades are driven from one CLI, Make target, or registry
   workflow.
4. Define safety boundaries for local dirt, partial governed repos, and legacy
   rollout modes.
5. Convert the design into later implementation slices only after the registry
   and safety model are explicit.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_install_governed_repo.py` or successor | multi-repo upgrade contract tests | Upgrade automation respects dry-run/apply boundaries and reported drift |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/20_governed-repo-upgrade-automation.md --warn-only` | Plan remains valid |
| `python scripts/self_test.py` | Installer authority docs remain coherent while automation is designed |

---

## Acceptance Criteria

- [x] The framework defines how governed repos are registered or discovered
- [x] The upgrade workflow has explicit dry-run/apply/rollback semantics
- [x] The design states how local dirt and partial governed repos are handled
- [x] The roadmap points to a numbered automation plan instead of a vague placeholder
- [x] Declared checks pass

---

## Decision

Upgrade automation should:

- use an explicit governed-repo registry rather than discovery by scan
- compose the existing installer and audit primitives
- treat dry-run as mandatory
- block write-mode upgrades on local dirt or partial governed state
- use branch/worktree rollback rather than bespoke file-snapshot rollback
