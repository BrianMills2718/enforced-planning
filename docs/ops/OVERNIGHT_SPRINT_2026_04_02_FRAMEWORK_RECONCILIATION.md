# Overnight Sprint — 2026-04-02 — Framework Truth-Surface Reconciliation

**Status:** Complete
**Owner:** codex
**Primary Plan:** `docs/plans/10_framework-truth-surface-and-onboarding-reconciliation.md`
**Underlying Goal:** make the framework's onboarding, installer behavior, and internal truth surfaces agree before the next adoption or semantic-review wave

## Non-Negotiable Execution Contract

- NEVER STOP unless there is a real blocker or an unresolved decision not covered by the active sprint.
- Finish the current phase, update this tracker, commit the verified slice, and continue immediately.
- Record uncertainties here instead of silently stopping.

## Phase Stack

### Phase A — Sprint Contract and Scope Freeze

Success criteria:
- root `CLAUDE.md` points here while the sprint is active
- unrelated pre-existing dirt is explicitly left untouched
- the sprint does not expand into Plan #7 implementation

### Phase B — Installer and Onboarding Truth

Success criteria:
- installer behavior and consumer docs agree on truth-surface tooling availability
- installed directory structure is described truthfully
- the truth-surface template is generic enough for reuse

### Phase C — Internal Truth-Surface Reconciliation

Success criteria:
- stale scope-sprint TODO/tracker items are corrected
- Plans #6 and #8 acknowledge the scoped follow-on
- the framework no longer contradicts itself about recently completed work

### Phase D — Backlog Truth and Handoff

Success criteria:
- Plan #1 is restated in current capability/boundary language
- plan index remains truthful
- the next bounded follow-on is explicit

## Current Phase

- Active phase: Complete
- Next action: start `docs/plans/11_semantic-truth-surface-review-execution-sprint.md` before implementing the optional semantic-review layer

## Open Uncertainties

- None. The installer/consumer-doc direction for truth-surface tooling was resolved inside this sprint: repo-local scripts plus repo-local scaffold.

## Rollback Points

- `a4ad670` — sprint contract + active tracker wiring
