# Plan #36: Research Synthesis Downstream Consistency

**Status:** Complete
**Type:** docs
**Priority:** Medium
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** `project-meta` now uses `research_synthesis` as the active local
path and treats `research_texts` as a compatibility alias, but
`enforced-planning` still has active guidance surfaces that describe the old
path as current truth.

**Target:** Active `enforced-planning` docs describe the Research Synthesis
Library truthfully, using `project-meta/research_synthesis/...` for forward
guidance while preserving historical references only where they remain the
truthful historical identifier.

**Why:** Leaving stale active references in a portable governance repo creates
rename drift across the ecosystem and teaches downstream repos the wrong
hot-path contract.

---

## References Reviewed

- `docs/plans/14_research-backed-adr-and-topic-research-integration.md`
- `ROADMAP.md`
- `patterns/38_agent-tool-design.md`
- `patterns/41_bookend-context-preservation.md`
- `scripts/worktree_paths.py`
- `~/projects/project-meta/docs/ops/RESEARCH_TEXTS_GOVERNANCE_AND_ORGANIZATION_2026-04-04.md`
- `~/projects/project-meta/research_synthesis/CLAUDE.md`

---

## Research Basis For This Slice

- `~/projects/project-meta/docs/ops/RESEARCH_TEXTS_GOVERNANCE_AND_ORGANIZATION_2026-04-04.md` - canonical explanation of the naming split and active-path contract
- `~/projects/project-meta/research_synthesis/CLAUDE.md` - current research-library root contract

---

## Files Affected

- docs/plans/36_research-synthesis-downstream-consistency.md (create)
- docs/plans/CLAUDE.md (modify)
- docs/plans/14_research-backed-adr-and-topic-research-integration.md (modify)
- ROADMAP.md (modify)
- patterns/38_agent-tool-design.md (modify)
- patterns/41_bookend-context-preservation.md (modify)
- scripts/worktree_paths.py (modify)
- investigations/cross-project/2026-04-05-research-synthesis-downstream-consistency.md (create)

---

## Plan

### Steps

1. Identify `research_texts` references inside active `enforced-planning`
   guidance and separate them from historical-only references.
2. Update the active surfaces to point at
   `~/projects/project-meta/research_synthesis/...` while preserving any needed
   historical/origin wording.
3. Record the slice in the plan queue and a dated investigation note.
4. Run focused validation so the doc changes stay truthful and mechanically
   clean.

---

## Required Tests

### Existing Checks

| Check | Why |
|------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/36_research-synthesis-downstream-consistency.md --warn-only` | plan format stays valid |
| `python scripts/check_markdown_links.py docs/plans/14_research-backed-adr-and-topic-research-integration.md docs/plans/36_research-synthesis-downstream-consistency.md ROADMAP.md patterns/38_agent-tool-design.md patterns/41_bookend-context-preservation.md investigations/cross-project/2026-04-05-research-synthesis-downstream-consistency.md` | changed docs keep valid links |

---

## Acceptance Criteria

- [x] Plan #36 is indexed in `docs/plans/CLAUDE.md`
- [x] Active `enforced-planning` guidance no longer treats `project-meta/research_texts` as the current hot path
- [x] Historical references remain untouched unless they are still acting as live operator guidance
- [x] The worktree-path helper comment matches the current projection truth
- [x] Declared validation checks pass

---

## Decisions

- This slice updates active guidance only; it does not attempt a full
  historical rewrite across completed plans.
- The stable project identifier and remote lineage may still retain
  `research_texts`; this slice only fixes active path guidance.
- `docs/plans/26_claim-session-auto-hydration-and-weak-lane-remediation.md`
  remains unchanged because its `--project research_texts` example may still be
  truthful to the stable project identifier rather than the active local path.
