# Overnight Sprint — 2026-04-02 — Truth-Surface Adoption Pilot

**Status:** In Progress
**Owner:** codex
**Primary Plan:** `docs/plans/08_truth-surface-adoption-pilot-execution-sprint.md`
**Underlying Goal:** complete the first governed-repo truth-surface adoption pilot and leave a measured handoff into semantic review work

## Non-Negotiable Execution Contract

- NEVER STOP unless there is a real blocker or an unresolved decision not covered by the active sprint.
- A completed commit or green test run is not a stop condition.
- Finish the active phase, update this tracker, commit the verified slice, and continue immediately to the next unblocked phase.
- Record uncertainties here instead of silently stopping.

## Phase Stack

### Phase A — Freeze pilot target and sprint contract

Success criteria:
- root `CLAUDE.md` points here
- target repo is chosen from measured state
- pilot uncertainties are recorded

### Phase B — Create repo-local pilot plan and config

Success criteria:
- pilot repo has a bounded local plan
- repo-local `truth_surface_drift.yaml` exists
- config points at real tracker/index/registry/audit surfaces

### Phase C — Run measured validation and drift detection

Success criteria:
- validator and renderer run successfully
- at least one drift case is detected
- findings are categorized into deterministic coverage vs semantic backlog

### Phase D — Close framework feedback loop

Success criteria:
- Plan #6 is updated truthfully
- next default-wiring recommendation is documented
- Plan #7 handoff is explicit and evidence-based

## Current Phase

- Active phase: Phase A
- Next action: update framework active-sprint surfaces, then open the repo-local pilot in the chosen governed repo

## Measured Pilot Target Selection

- `project-meta`: dirty canonical root; not the clean first pilot
- `llm_client`: dirty active feature branch; not the clean first pilot
- `prompt_eval`: clean canonical root, governed, plan index present, capability source present, governed audit passes, but canonical root is flagged `!! ACTIVE (no claim)`
- `data_contracts`: clean canonical root, but claims/worktrees are disabled, so it is a weaker coordination pilot

Chosen target: `prompt_eval`

Reason:
- best combination of clean repo state and real governed coordination surfaces
- stronger pilot than `data_contracts` because claims/worktrees are enabled
- `!! ACTIVE (no claim)` warning is recorded as a real uncertainty, not ignored

## Open Uncertainties

- Whether the canonical-root `!! ACTIVE (no claim)` warning in `prompt_eval` should become a pilot blocker in later enforcement phases.
- Whether the first pilot should intentionally simulate drift if the live repo is too internally consistent to produce a real contradiction.
- Which findings should remain advisory until the semantic-review layer exists.

## Rollback Points

- none yet for this sprint
