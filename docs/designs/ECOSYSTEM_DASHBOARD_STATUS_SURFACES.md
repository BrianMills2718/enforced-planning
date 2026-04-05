# Design: Ecosystem Dashboard and Status Surfaces

**Date:** 2026-04-04
**Status:** Accepted

## Purpose

Define one canonical operator-facing status surface for the governed-repo
ecosystem so operators can answer "what is the current state of the framework
fleet?" without stitching together multiple unrelated outputs.

## Operator Questions

The canonical status surface must answer these questions:

1. Which repos are in the governed fleet, and what tier are they in?
2. What plans are currently in progress, blocked, or newly queued across the
   ecosystem?
3. Which repos are central or risky from a dependency/coupling perspective?
4. Which repos are healthy, partial, or blocked from upgrade/adoption work?
5. Which advisory surfaces are fresh enough to trust, and which are stale?

## Canonical Surface

The canonical operator surface should have two layers built from the same
sources:

1. `generated/ecosystem_status.json`
   - machine-readable source of truth for automation and future UI
2. `docs/ops/ECOSYSTEM_STATUS.md`
   - rendered human-readable summary for operators

The future entrypoint should be one command:

```bash
make ecosystem-status
```

That target should build the JSON payload first and then render the Markdown
summary from it.

## Why This Shape

- JSON keeps the data reusable by automation, CI, and future dashboards
- Markdown keeps the first operator surface reviewable in git
- one renderer avoids hand-maintained status prose
- a future web dashboard can consume the JSON without redefining the contract

## Reuse vs Replace

### Reuse

The ecosystem status build should reuse existing machine-readable surfaces:

- `generated/plan_registry.json`
  - plan queue and per-repo plan state
- `generated/ecosystem_dep_map.json`
  - cross-repo dependency and backbone visibility
- governed-repo audit outputs
  - adoption and health classification
- semantic-review outputs
  - advisory freshness and review recency
- explicit governed-repo registry from the upgrade-automation design
  - determines the intended fleet rather than guessing from filesystem scans

### Reposition, Not Replace

These surfaces remain useful, but they are not the canonical ecosystem operator
surface:

- `ROADMAP.md`
  - strategic queue, not live ecosystem status
- `docs/plans/CLAUDE.md`
  - per-repo plan index, not fleet status
- `scripts/worktree-coordination/meta_status.py`
  - repo-local coordination helper, not cross-repo operator status
- sprint trackers in `docs/ops/`
  - execution artifacts, not canonical operator dashboards

## Status Model

The first canonical JSON payload should include:

```json
{
  "generated_at": "2026-04-04T00:00:00Z",
  "fleet": {
    "repo_count": 0,
    "governed_count": 0,
    "partial_count": 0,
    "legacy_count": 0
  },
  "plans": {
    "total": 0,
    "in_progress": [],
    "blocked": [],
    "newly_planned": []
  },
  "dependencies": {
    "cross_repo_edges": 0,
    "highest_centrality_repos": []
  },
  "health": {
    "audit_pass": [],
    "audit_fail": [],
    "upgrade_blockers": []
  },
  "advisory": {
    "semantic_review_freshness": [],
    "stale_surfaces": []
  }
}
```

Exact field names may change during implementation, but the five sections above
should remain the stable contract.

## Trust Boundaries

The status surface must separate deterministic and advisory data clearly:

- deterministic
  - plan registry
  - dependency map
  - governed-repo audit classifications
  - explicit registry metadata
- advisory
  - semantic review findings
  - freshness heuristics

The rendered Markdown summary should label advisory sections explicitly rather
than mixing them into hard status counts.

## Minimum Viable Slice

The first implementation slice should do only this:

1. read explicit governed-repo registry
2. ingest existing generated plan/dependency outputs
3. ingest governed-repo audit classifications or reports
4. emit `generated/ecosystem_status.json`
5. render `docs/ops/ECOSYSTEM_STATUS.md`

It should not try to ship a web UI, background daemon, or live polling system.

## Non-Goals

The first slice should not:

- replace repo-local coordination tools
- become a general observability platform
- merge advisory semantic findings into deterministic pass/fail counts
- require a database or service process

## Relationship to Later Work

- Plan #22 should define which ROI metrics are computed from this status
  surface
- Plan #23 can point Mac mini bootstrap work at this generated status surface
  as the future operator summary
- future UI work should consume `generated/ecosystem_status.json` rather than
  inventing a second data model

## References

- `docs/plans/12_cross-repo-plan-registry.md`
- `docs/designs/GOVERNED_REPO_UPGRADE_AUTOMATION.md`
- `scripts/worktree-coordination/meta_status.py`
- `ROADMAP.md`
