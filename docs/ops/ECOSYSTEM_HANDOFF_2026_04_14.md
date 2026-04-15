# Ecosystem Handoff — 2026-04-14

## Purpose

This file is the restart-safe handoff surface for unfinished work across the
repos that currently matter to the governed ecosystem.

It is meant to save the next runtime from rediscovering:

- which repos still have active or blocked queues
- which queues are probably stale versus genuinely current
- where live work exists outside the generated status snapshot
- what should be resumed first versus what should be left alone

## Scope Definition

This handoff treats a repo as relevant when any of the following are true:

- it has `In Progress`, `Blocked`, or non-placeholder `Planned` work in
  `generated/plan_registry.json`
- it has a live coordination claim on 2026-04-14 even if the generated plan
  registry does not show it
- it is `enforced-planning` itself and has unresolved source-repo hardening
  debt that affects the rest of the ecosystem

## Source Freshness

| Source | Timestamp | Notes |
|--------|-----------|-------|
| `generated/plan_registry.json` | 2026-04-02 17:27 PDT | Oldest source in this handoff. Good enough for queue shape, not trustworthy for minute-by-minute state. |
| `generated/ecosystem_status.json` | 2026-04-05 20:19 PDT | Fleet status snapshot. More recent than the plan registry, but still not same-day. |
| `~/.claude/coordination/claims/*.yaml` | 2026-04-14 | Current live-lane source. Use this to override stale generated status when they disagree. |
| manual repo assessment of `enforced-planning` | 2026-04-14 | Used for the framework-source hardening section below. |

## Executive Queue

1. `enforced-planning`
   - Highest leverage repo because it is the governance source repo and it is
     not yet cleanly self-hosting.
2. `Digimon_for_KG_application`
   - Densest active queue in the current registry: 2 in progress, 5 blocked,
     2 planned.
3. `ac14`
   - Critical verdict/diagnosis chain is still open.
4. `project-meta`
   - Runtime-evaluation lane is still marked in progress and may have newer
     truth outside the stale generated snapshot.
5. `osint_tools`
   - High-priority governed-baseline rollout is still active.
6. `grounded-research` and `epistemic-contracts`
   - Both have active dead-code rollout claims that are newer than the
     generated plan-registry snapshot.
7. `theory-forge`
   - One active pilot plus one blocked follow-on integration lane.
8. `open_web_retrieval`
   - Planned work only; no current live lane.
9. `agent_ecology2`
   - One medium-priority in-progress lane and several low-priority planned
     items.

## Repo-By-Repo Handoff

### `enforced-planning`

**Path:** `~/projects/enforced-planning`

**Current state**

- No new numbered plan is open in the current queue.
- `ROADMAP.md` says the framework capability set is complete and Phase 9 should
  be fleet adoption and maintenance, not more capability invention.
- The source repo still has unresolved hardening debt from the 2026-04-14
  assessment:
  - `pytest -q` was not green: 500 passed, 2 failed, 1 skipped.
  - `python scripts/self_test.py` passed, which means the failures are below
    the top-level smoke surface.
  - `ruff check scripts/ tests/ enforced_planning/` reported 219 issues.

**Concrete unresolved items**

- `scripts/check_agents_sync.py` and `scripts/render_agents_md.py` disagree
  about source-versus-installed provenance markers, so a freshly rendered
  `AGENTS.md` can be reported as drifted.
- `tests/test_edge_cases.py` still expects `check_doc_coupling.py` to be a
  compatibility wrapper even though the file is now a full implementation.
- `GETTING_STARTED.md` and `docs/guides/NEW_PROJECT_SETUP.md` claim consumer
  repos only need Python 3.9+, but `pyproject.toml` requires Python 3.11+ and
  the installed code uses modern typing syntax.
- `templates/Makefile.meta` still assumes a `src/` tree exists and therefore is
  not actually repo-agnostic.

**Recommended next move**

1. Open a hardening plan before any new framework capability work.
2. Get `pytest`, Ruff, and the source-repo docs/template contract green.
3. Reconcile the Python/runtime version story.
4. Run one measured pilot on two governed repos before doing more framework
   expansion.

### `Digimon_for_KG_application`

**Path:** `~/projects/Digimon_for_KG_application`

**Current queue from `plan_registry.json`**

- In Progress
  - Plan #22 — Benchmark-First Canonicalization And Projection Hardening
  - Plan #23 — Semantic Build Boundary And onto-canon6 Experiment
- Blocked
  - Plan #4 — Graph Build Rearchitecture
  - Plan #5 — Extraction Quality Repair
  - Plan #6 — Two-Pass Extraction Proof
  - Plan #12 — MuSiQue Representation Audit
  - Plan #13 — Benchmark Anchor Resolution
- Planned
  - Plan #18 — PTC Validation (conditional)
  - Plan #24 — Shared Run-Progress Integration For Graph Builds

**Interpretation**

- This is the highest-volume unfinished queue in the snapshot.
- The active frontier is Plans #22 and #23, not the older blocked extraction
  plans.
- The blocked older plans all look contingent on whether the current benchmark
  and routing work changes the real bottleneck.
- Plan #24 was recorded as blocked on `llm_client` Plan #22 in the plan
  registry; that shared plan is already complete in the same snapshot, so the
  remaining constraint is probably repo-local rather than shared-infra.

**Recommended next move**

1. Finish the decision-grade MuSiQue rerun for Plan #22.
2. Resolve the default-path convergence question inside Plan #23.
3. Only after those are settled, decide whether Plans #4/#5/#6/#12/#13 should
   be revived, rewritten, or retired.

### `ac14`

**Path:** `~/projects/ac14`

**Current queue**

- In Progress
  - Plan #72 — Second-Gate Verdict Interpretation
- Planned
  - Plan #73 — Resource Scaling Failure Diagnosis
- Blocked
  - Plan #37 — Directory Divergence Front-Half Proof

**Interpretation**

- The critical queue is concentrated and linear.
- The practical frontier is verdict interpretation first, then diagnosis.
- The blocked directory-divergence proof should not be resumed before the
  verdict/diagnosis chain is closed or reframed.

**Recommended next move**

1. Finish Plan #72.
2. Start Plan #73 immediately after if the verdict still points at scaling or
   runtime limits.
3. Re-evaluate Plan #37 only after those two are truthfully closed.

### `project-meta`

**Path:** `~/projects/project-meta`

**Current queue**

- In Progress
  - Plan #57 — Runtime implementation evaluation lane

**Interpretation**

- The generated snapshot is stale enough that `project-meta` should be treated
  carefully.
- Historical coordination claims from 2026-04-05 show a large amount of plan
  catalog and authority-stack repair landed there, so the generated
  cross-repo registry may lag the repo's real state.

**Recommended next move**

1. Read `~/projects/project-meta/docs/plans/CLAUDE.md` directly before acting.
2. Treat the repo-local plan index, sprint tracker, and any active claims as
   higher-authority than the 2026-04-02 generated fleet registry.
3. If Plan #57 is still live, continue it; otherwise refresh the ecosystem
   registry from a current checkout.

### `osint_tools`

**Path:** `~/projects/osint_tools`

**Current queue**

- In Progress
  - Plan #1 — Governed Baseline And Capability Ownership Rollout

**Interpretation**

- This looks like unfinished governance/productization rather than exploratory
  research.
- Because the plan number is low and the status is still in progress, the repo
  likely still needs baseline contract installation, ownership mapping, or
  rollout closeout.

**Recommended next move**

1. Read the Plan #1 doc and repo-local plan index.
2. Verify whether the governed baseline is fully installed and audited.
3. Finish or explicitly re-scope the capability-ownership rollout before
   starting new feature work in that repo.

### `grounded-research`

**Path:** `~/projects/grounded-research`

**Current live lane**

- Active coordination claim exists on 2026-04-14:
  - scope: `plan-55-grounded-research-dead-code`
  - goal: finish Plan #55 wave 2A by installing the dead-code contract,
    auditing findings, and publishing the repo outcome
  - current phase: `contract rollout and baseline inspection`

**Interpretation**

- This repo is not represented in the generated `plan_registry.json`, so the
  live claim is the only current machine-readable evidence of unfinished work.
- Because the claim is active and recent, treat the worktree and session
  tracker as the authoritative restart point.

**Recommended next move**

1. Resume the existing worktree if the lane is still alive.
2. Finish the contract rollout and first audit pass.
3. If the lane is dead, do not silently start a new one; either resume or
   close the existing claim truthfully.

### `epistemic-contracts`

**Path:** `~/projects/epistemic-contracts`

**Current live lane**

- Active coordination claim exists on 2026-04-14:
  - scope: `plan-55-epistemic-contracts-dead-code`
  - goal: complete wave 2A reviewed dead-code rollout
  - current phase: `Roll in governed dead-code contract and classify findings`
  - intended next phase: sync the dead-code contract, run detector, classify
    findings, and verify push-check

**Interpretation**

- Like `grounded-research`, this is active live work not yet reflected in the
  generated plan-registry snapshot.
- The current work appears to be governance hardening and publish-closeout.

**Recommended next move**

1. Resume the existing worktree/claim rather than creating a parallel lane.
2. Finish the rollout and publish-check path.
3. Close or hand off the lane explicitly when done.

### `theory-forge`

**Path:** `~/projects/theory-forge`

**Current queue**

- In Progress
  - Plan #4 — AC11 Graph Schema Compile Pilot
- Blocked
  - Plan #8 — AC14 Code Generation Integration

**Interpretation**

- The repo has one active pilot and one blocked follow-on integration lane.
- The graph-schema compile pilot is the real frontier; the code-generation
  integration should stay blocked until the pilot produces decision-grade
  evidence.

**Recommended next move**

1. Finish the AC11 pilot and document the result.
2. Re-evaluate whether Plan #8 should be unblocked, rewritten, or dropped.

### `open_web_retrieval`

**Path:** `~/projects/open_web_retrieval`

**Current queue**

- Planned
  - Plan #8 — Async/Sync Deduplication
  - Plan #12 — Multi-Provider Search & Fetch Adapters

**Interpretation**

- There is no active lane here in the snapshot.
- This is backlog, not an urgent restart point.
- It becomes relevant when a consuming repo actually needs adapter expansion or
  dedup cleanup.

**Recommended next move**

- Leave this backlog parked unless a consumer repo is blocked on it.

### `agent_ecology2`

**Path:** `~/projects/agent_ecology2`

**Current queue**

- In Progress
  - Plan #311 — V2 Discourse Agents
- Planned
  - Plan #118 — Computed Plan Status from Git History
  - Plan #138 — Provider-Level Union Schema Transformation
  - Plan #155 — V4 Architecture — Deferred Considerations
  - Plan #162 — Contract Artifact Lookup
  - Plan #207 — Executor Method Refactoring
  - Plan #209 — Trigger-Hook Integration
  - Plan #240 — Cross-CC Review Enforcement

**Interpretation**

- The real work here is Plan #311.
- Most of the rest of the queue is explicitly low-priority or deferred.

**Recommended next move**

- Keep Plan #311 as the only active line unless another repo now depends on one
  of the planned items.

## Placeholder Repos

The following repos only show a placeholder or example plan in the current
snapshot and do not deserve active engineering attention unless explicitly
promoted into a real queue:

- `agent_ecology3`
- `agent_ontology`
- `conspiracy_epistemics`
- `json-diff`
- `moltbot`
- `process_tracing`
- `sam_gov`
- `trajectory`
- `whygame4`

## Repos With No Unfinished Work Recorded In The Current Snapshot

The current generated surfaces do not show active unfinished work for:

- `llm_client`
- `prompt_eval`
- `agentic_scaffolding`
- `agent_memory`
- `ecosystem-ops`
- `qualitative_coding`
- `orgchart`
- `data_contracts`
- `research_v3`

Treat that as "no unfinished work recorded," not "guaranteed clean forever."

## Cross-Repo Concerns

### 1. Snapshot staleness is real

The fleet registry data used here is not same-day:

- `plan_registry.json` is from 2026-04-02
- `ecosystem_status.json` is from 2026-04-05

Live coordination claims already prove the generated surfaces are lagging for at
least `grounded-research` and `epistemic-contracts`.

### 2. `enforced-planning` should not expand until it hardens

The framework repo is still the source of truth for governance, but it is not
yet holding itself to the same cleanliness standard it asks of governed repos.

### 3. High-signal work is concentrated

The meaningful unfinished ecosystem work is concentrated in:

- `enforced-planning`
- `Digimon_for_KG_application`
- `ac14`
- `project-meta`
- `osint_tools`
- `grounded-research`
- `epistemic-contracts`
- `theory-forge`

Everything else should stay paused unless there is a concrete dependency pull.

## Recommended Operator Restart Sequence

1. Refresh `generated/plan_registry.json` and `generated/ecosystem_status.json`
   from a clean `enforced-planning` checkout.
2. Decide whether the next priority is framework hardening or one of the active
   product/model repos.
3. Resume or explicitly close the active dead-code rollout lanes in
   `grounded-research` and `epistemic-contracts`.
4. If resuming a repo-specific lane, open that repo's plan index and current
   plan doc before making any edits.

## Bottom Line

If the goal is maximum leverage, do this first:

1. harden `enforced-planning`
2. then choose between `Digimon_for_KG_application` and `ac14` as the main
   product-facing queue
3. keep `project-meta`, `osint_tools`, `grounded-research`, and
   `epistemic-contracts` truthful but secondary

Everything else can wait.
