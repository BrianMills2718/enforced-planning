# Overnight Sprint — 2026-04-02 — Semantic Truth-Surface Review

**Status:** In Progress
**Owner:** codex
**Primary Plan:** `docs/plans/11_semantic-truth-surface-review-execution-sprint.md`
**Underlying Goal:** implement the first optional semantic truth-surface review slice so deterministic and advisory semantic findings can coexist truthfully

## Non-Negotiable Execution Contract

- NEVER STOP unless there is a real blocker or an unresolved decision not covered by this sprint.
- A green unit-test slice is not a stop condition; update the tracker, commit, and move to the next phase.
- Record uncertainties here instead of silently stopping.

## Phase Stack

### Phase A — Sprint activation and contract freeze

Success criteria:
- root `CLAUDE.md` points to this active sprint
- Plan #11 is marked in progress
- Plan #7's operational defaults are frozen through this sprint rather than reopened ad hoc

### Phase B — Semantic review entrypoint and prompt contract

Success criteria:
- one prompt-backed semantic review entrypoint exists
- the entrypoint uses `llm_client` structured output with required call metadata
- the first slice fails loud if `llm_client` is unavailable or misconfigured

### Phase C — Deterministic + semantic rendering

Success criteria:
- rendered status can show semantic findings beside deterministic findings
- semantic findings remain clearly advisory-only
- promotion-candidate findings are recorded explicitly

### Phase D — Verification and closeout

Success criteria:
- tests cover structured semantic output parsing and merged rendering
- framework self-test and targeted tests pass
- Plans #7 and #11 are updated truthfully from implementation evidence
- next bounded follow-on is explicit

## Current Phase

- Active phase: Phase A
- Next action: wire this sprint into `CLAUDE.md`, mark Plan #11 in progress, then implement the semantic review entrypoint and prompt

## Open Uncertainties

- Whether the active environment will expose `llm_client` through the public import path without extra setup. Working rule for this sprint: the runtime must fail loud with a clear instruction if shared infra is not installed correctly.

## Rollback Points

- Pending first verified slice
