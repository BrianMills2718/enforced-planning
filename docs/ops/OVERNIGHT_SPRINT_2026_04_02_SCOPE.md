# Overnight Sprint — 2026-04-02 — Scoped Truth-Surface Validation

**Status:** Complete
**Owner:** codex
**Primary Plan:** `docs/plans/09_scoped-truth-surface-validation.md`
**Underlying Goal:** make repo-local truth-surface validation actionable by separating local drift from unrelated ecosystem registry noise

## Non-Negotiable Execution Contract

- NEVER STOP unless there is a real blocker or an unresolved decision not covered by the active sprint.
- Finish the current phase, update this tracker, commit the verified slice, and continue immediately.
- Record uncertainties here instead of silently stopping.

## Phase Stack

### Phase A — Define scope model

Success criteria:
- config shape is explicit
- canonical repo identity rule is explicit
- known uncertainties are recorded before implementation

### Phase B — Implement scoped validator behavior

Success criteria:
- validator supports scoped filtering for active-work and reservations
- tests prove canonical identity derivation and scoped filtering

### Phase C — Replay `prompt_eval`

Success criteria:
- the pilot rerun is materially cleaner
- any remaining finding is attributable to `prompt_eval` or its own historical worktrees

### Phase D — Update framework guidance

Success criteria:
- docs explain local scoped review vs global review
- the recommendation is updated truthfully from measured replay evidence

## Current Phase

- Active phase: Phase D complete
- Next action: no new active sprint; fall back to `docs/plans/CLAUDE.md` and open the next bounded sprint before coding again

## Inherited Evidence From Plan #8

- `prompt_eval` successfully consumed the validator and renderer through a repo-local config.
- The first pilot findings were real but dominated by unrelated global registry drift.
- Framework portability issues found during the pilot were already fixed in commit `4a9196b`.

## Open Uncertainties

- Whether scoped mode should suppress out-of-scope findings entirely or preserve them as lower-priority background noise.
- Whether historical worktrees should be considered part of the same canonical repo identity by default. Current plan assumption: yes.

## Rollback Points

- `0f9623f` — pilot sprint contract
- `4a9196b` — repo-local config/runtime path hardening
- `1fdc80f` in `prompt_eval` — repo-local pilot adoption
- `aca6856` in `prompt_eval` — scoped repo-local replay
