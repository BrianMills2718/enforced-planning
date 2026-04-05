# Design: Framework Self-Measurement

**Date:** 2026-04-04
**Status:** Accepted

## Purpose

Define the smallest credible metric model for measuring whether
`enforced-planning` is being adopted, whether it is catching drift, and whether
later ROI claims are evidence-backed rather than anecdotal.

## Measurement Principles

- prefer deterministic metrics over narrative claims
- label advisory metrics explicitly
- do not claim financial ROI without a real baseline study
- compute from committed or generated artifacts, not hidden operator memory
- reuse the canonical ecosystem status surface instead of inventing parallel
  measurement state

## Canonical Measurement Surface

The canonical measurement surface should be a section within
`generated/ecosystem_status.json` with a rendered summary in
`docs/ops/ECOSYSTEM_STATUS.md`.

Plan #22 depends on Plan #21 deliberately: metrics should be exposed through
the operator-status contract, not through a separate scoreboard.

## Canonical Metric Set

### 1. Fleet Adoption Metrics

| Metric | Definition | Type | Primary Source |
|--------|------------|------|----------------|
| `registered_repo_count` | Repos present in the explicit governed-repo registry | deterministic | governed-repo registry |
| `governed_repo_count` | Registered repos that pass strict governed audit | deterministic | governed-repo audit reports |
| `partial_repo_count` | Registered repos that are intended consumers but fail strict governed audit | deterministic | governed-repo audit reports |
| `tool_tier_distribution` | Count of repos or workflows by support tier | deterministic | registry metadata + support matrix |

### 2. Queue and Execution Metrics

| Metric | Definition | Type | Primary Source |
|--------|------------|------|----------------|
| `plans_in_progress` | Count of plans currently marked in progress across the fleet | deterministic | plan registry |
| `blocked_plan_count` | Count of plans explicitly blocked | deterministic | plan registry |
| `time_to_close_plan` | Duration from plan creation to completion for plans with reliable dates | deterministic after instrumentation | plan files or future status metadata |

### 3. Drift-Catch Metrics

| Metric | Definition | Type | Primary Source |
|--------|------------|------|----------------|
| `deterministic_findings_open` | Current unresolved deterministic governance findings | deterministic | audit outputs + validators |
| `deterministic_findings_fixed` | Findings that were present and later cleared | deterministic after history capture | status history or audit history |
| `promotion_candidates_count` | Semantic findings promoted into deterministic checks | deterministic | promotion output/history |

### 4. Semantic Review Metrics

| Metric | Definition | Type | Primary Source |
|--------|------------|------|----------------|
| `semantic_reviews_run` | Number of canonical semantic review runs in scope | deterministic | semantic review history |
| `semantic_findings_open` | Advisory findings still present in latest review payload | advisory summary from deterministic history | semantic review latest payload |
| `semantic_to_deterministic_ratio` | Promoted findings divided by total meaningful findings | advisory-to-deterministic bridge | semantic history + promotion history |

### 5. Upgrade and Sync Metrics

| Metric | Definition | Type | Primary Source |
|--------|------------|------|----------------|
| `repos_upgrade_ready` | Registered repos eligible for write-mode upgrade | deterministic | registry + audit status |
| `repos_upgrade_blocked` | Registered repos blocked by dirt, partial state, or missing governance | deterministic | dry-run upgrade reports |
| `last_upgrade_age_days` | Days since last successful framework sync per repo | deterministic after upgrade reports exist | upgrade reports/history |

## Concrete Definitions

### What counts as "adoption"

A repo counts as adopted only when all of these are true:

1. it appears in the explicit governed-repo registry
2. it is intended to consume the framework (`tier != source-only`)
3. it passes strict governed audit

Repos that are registered but fail strict governed audit are `partial`, not
adopted.

### What counts as "drift caught"

A drift case counts as caught only when:

1. a deterministic validator or semantic review emitted a finding
2. the finding was recorded in a committed/generated artifact
3. a later artifact shows the finding resolved or promoted

Unrecorded anecdotes do not count.

## Trust Boundaries

### Deterministic and trustworthy enough for dashboards

- governed-repo registry
- governed-repo audit reports
- plan registry
- ecosystem dependency map
- semantic review run counts and stored payload presence
- promotion-to-deterministic history

### Advisory or incomplete

- semantic finding severity or usefulness
- time-to-close metrics without reliable created/completed timestamps
- claims about productivity improvement
- claims about bugs prevented unless tied to a recorded finding lifecycle

## Metrics We Explicitly Do Not Claim Yet

Do not claim any of these until dedicated instrumentation exists:

- engineer hours saved
- dollar ROI
- merge-speed improvement
- bug-prevention rate in production
- universal semantic-review precision/recall

These may become later research or experiment slices, but they are not part of
the current canonical metric surface.

## Minimum Viable Slice

The first implementation slice should compute only:

1. fleet adoption counts
2. plan queue counts
3. dependency backbone highlights
4. deterministic finding counts
5. semantic review run/findings counts
6. upgrade-ready vs blocked counts

That is enough to make credible operational claims without overreaching.

## Relationship to Existing Tools

- `scripts/build_plan_registry.py`
  - plan queue metrics
- `scripts/build_ecosystem_dep_map.py`
  - dependency backbone metrics
- `scripts/audit_governed_repo.py`
  - adoption and health metrics
- `scripts/review_truth_surface_semantic.py`
  - semantic-review counts and latest advisory state
- `scripts/promote_to_deterministic.py`
  - promotion metrics
- `scripts/governed_repo_experiment.py`
  - optional future friction studies, not part of the canonical minimum metric set

## Recommended Next Implementation Order

1. add the metric section to `generated/ecosystem_status.json`
2. render the metric summary in `docs/ops/ECOSYSTEM_STATUS.md`
3. add history capture only for metrics that need trend lines
4. defer financial or productivity ROI studies until baseline instrumentation exists

## References

- `docs/designs/ECOSYSTEM_DASHBOARD_STATUS_SURFACES.md`
- `docs/designs/GOVERNED_REPO_UPGRADE_AUTOMATION.md`
- `scripts/build_plan_registry.py`
- `scripts/build_ecosystem_dep_map.py`
- `scripts/audit_governed_repo.py`
- `scripts/review_truth_surface_semantic.py`
- `scripts/promote_to_deterministic.py`
