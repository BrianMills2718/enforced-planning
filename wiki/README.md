---
title: Enforced Planning Wiki
type: synthesis
status: current
authority: derived
classification: internal
created: 2026-09-02
updated: 2026-09-02
sources: [src-repository-fe0693bf70aa-ba174ff4, src-repository-6b5684f88799-03d49981, src-repository-15cd61a14612-f66e192c, src-repository-c469e0e86916-1ffbe173, src-repository-39a1cd180ea8-79b1f98b]
---

# Enforced Planning wiki

This is the compact, interlinked navigation layer for Enforced Planning. It is
derived from immutable captures of native repository authority. When wording
here and a native plan, ADR, configuration file, test, or code path disagree,
the native artifact wins.

## Start by intent

| Need | Follow this route | Native authority reached |
| --- | --- | --- |
| Why this project exists; what must not drift | [[goal-and-requirements]] | [`README.md`](../README.md), [`PLANNING_OPERATING_MODEL.md`](../PLANNING_OPERATING_MODEL.md), and repository instructions |
| Architecture, ownership, and executable capabilities | [[architecture-and-capabilities]] | accepted ADRs, config, implementation, and tests |
| Current priorities and the active plan frontier | [[current-work]] | [`ROADMAP.md`](../ROADMAP.md), [`docs/plans/CLAUDE.md`](../docs/plans/CLAUDE.md), and the selected plan |
| What proves behavior and where evidence lives | [[evidence-and-verification]] | tests, scripts, and rollout receipts |
| Development history | `git log --oneline --all` | Git; historical sprint trackers are deliberately absent from current navigation |

The initial route is graph navigation, not keyword or vector search. Use the
bounded search command only when this map does not expose the subject:

```bash
python3 /path/to/wiki_methodology/foundation/llm-wiki/skills/wiki-configure/scripts/wiki.py \
  --workspace . --json search "subject" --max-bytes 4096 --write-receipt
```

Every fallback is a signal to add or repair a link here; it is not a reason to
make search the primary entrypoint.

## Source safety

- Captures are append-only under [`raw/sources/`](../raw/sources/).
- `_sources.md`, `_catalog.md`, backlinks, and the reverse manifest are
  rebuildable projections.
- `status` checks whether each `tracks_current` capture still represents the
  canonical Git path; `lint --strict` fails actionably on drift.
- [[log]] records compact wiki maintenance only. Project development history
  stays in Git rather than in default agent context.

## Captured basis

This route was compiled from the repository instructions
([`src-repository-fe0693bf70aa-ba174ff4`](../raw/sources/2026/src-repository-fe0693bf70aa-ba174ff4/source.md)),
project overview ([`src-repository-6b5684f88799-03d49981`](../raw/sources/2026/src-repository-6b5684f88799-03d49981/source.md)),
planning model ([`src-repository-15cd61a14612-f66e192c`](../raw/sources/2026/src-repository-15cd61a14612-f66e192c/source.md)),
roadmap ([`src-repository-c469e0e86916-1ffbe173`](../raw/sources/2026/src-repository-c469e0e86916-1ffbe173/source.md)),
and plan index ([`src-repository-39a1cd180ea8-79b1f98b`](../raw/sources/2026/src-repository-39a1cd180ea8-79b1f98b/source.md)).
