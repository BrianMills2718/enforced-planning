# Research Synthesis Downstream Consistency Review

Date: 2026-04-05
Repo: enforced-planning
Plan: 36

## Question

Which remaining `research_texts` references in `enforced-planning` are still
acting as live guidance, and which are acceptable as historical or stable-id
artifacts?

## Findings

1. The main active drift was in live guidance, not in historical records:
   - Plan #14 still described `project-meta/research_texts/...` as the current
     research-library home.
   - `ROADMAP.md` still recommended project-meta topic-research adoption under
     `project-meta/research_texts`.
   - Patterns 38 and 41 still pointed readers to `research_texts/...` as live
     reference locations.
2. `scripts/worktree_paths.py` still used
   `project-meta/research_texts` as the example of an intentionally untracked
   canonical source path. That comment had become stale after the hot-path
   rename.
3. Not every remaining `research_texts` token should be changed:
   - completed plan docs may truthfully preserve the historical identifier
   - stable project ids may still legitimately use `research_texts`

## Uncertainties

1. The long-term stable project identifier is still unresolved; `project-meta`
   intentionally preserved the logical project id `research_texts` during the
   local-path rename.
2. The GitHub remote/repo lineage still uses `research_texts`, so some future
   docs may need dual-name wording rather than a pure rewrite.

## Decision

Limit this slice to active guidance surfaces and leave historical/stable-id
references unchanged unless they are misleading as live operator guidance.
