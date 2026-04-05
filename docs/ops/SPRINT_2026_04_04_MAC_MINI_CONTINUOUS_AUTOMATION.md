# Sprint: Mac Mini Continuous Automation Bootstrap

**Created:** 2026-04-04
**Scope:** `/home/brian/projects/enforced-planning/`
**Execution mode:** Continuous autonomous execution
**Primary branch/worktree:** `plan-23-mac-mini-overnight-execution`

---

## Mission

Finish the next 24 hours of framework work needed to move toward Mac mini based
continuous automation without ambiguity in queue, support policy, upgrade
policy, dashboard/status direction, or measurement direction.

## Acceptance Criteria

- [x] Plan #23 is complete
- [x] Plan #19 is complete
- [x] Plan #20 is complete
- [x] Plan #21 is complete
- [x] Plan #22 is complete
- [x] Mac mini bootstrap guide exists and is truthful
- [x] `ROADMAP.md`, `docs/plans/CLAUDE.md`, and `CLAUDE.md` all reflect the same queue state

## Stop Conditions

Only these qualify:

1. irreversible shared-state action
2. genuine architectural decision not pre-made in the active plan set

Everything else is execution work, not a stop condition.

## Phase Queue

### Phase 1 — Execution Harness and Mac Mini Bootstrap Surfaces

**Plans:** #23

**Goal:** Make the overnight queue and Mac mini transfer path explicit before
executing Phase 8 slices.

**Outputs:**

- `docs/ops/SPRINT_2026_04_04_MAC_MINI_CONTINUOUS_AUTOMATION.md`
- `docs/guides/MAC_MINI_CONTINUOUS_AUTOMATION_BOOTSTRAP.md`
- strengthened `CLAUDE.md`

### Phase 2 — Support Matrix and Portability Contract

**Plans:** #19

**Goal:** Define what "portable" means by tool tier and evidence boundary.

### Phase 3 — Governed-Repo Upgrade Automation

**Plans:** #20

**Goal:** Define the registry, dry-run/apply semantics, and safety boundaries
for upgrading multiple governed repos.

### Phase 4 — Ecosystem Dashboard and Status Surfaces

**Plans:** #21

**Goal:** Define one canonical operator-facing ecosystem status surface.

### Phase 5 — Framework Self-Measurement and ROI

**Plans:** #22

**Goal:** Define the smallest credible metric model for framework value claims.

### Phase 6 — Queue Reconciliation and Closeout

**Plans:** #23

**Goal:** Mark every completed slice truthfully, verify the docs, and leave the
repo in a clean committed state from the worktree.

## Execution Rules

- Work in this sanctioned worktree until the overnight queue is complete.
- Commit every verified phase or sub-phase separately.
- Update this tracker and the numbered plan docs before moving on.
- If an uncertainty appears, write it here and in the affected plan instead of
  silently pausing.
