---
title: Evidence and Verification
type: verification
status: current
authority: derived
classification: internal
created: 2026-09-02
updated: 2026-09-02
sources: [src-repository-6b5684f88799-03d49981, src-repository-15cd61a14612-f66e192c, src-repository-6d892250b3e8-caba9f80]
---

# Evidence and verification

## Proof routes

| Claim | Authentic boundary | Native evidence route |
| --- | --- | --- |
| governed-repo install works | disposable or named consumer install/audit | [`scripts/install_governed_repo.py`](../scripts/install_governed_repo.py), [`scripts/audit_governed_repo.py`](../scripts/audit_governed_repo.py), installer tests |
| claims and worktrees are safe | claimed lane creation, prewrite, and atomic closeout | coordination/session tests and claim receipts |
| planning behavior matches the model | plan validation plus one consumer journey | [`scripts/validate_plan.py`](../scripts/validate_plan.py), plan/evidence artifacts |
| derived navigation is fresh | source change makes freshness fail until rebuild | effective-profile and docstring-wiki tests; current wiki `status` and `lint` |
| this rollout reduced sprawl | retired files are absent from normal context and recoverable in Git | [`docs/evidence/wiki-rollout/plan254/`](../docs/evidence/wiki-rollout/plan254/) |

## Wiki mechanism checks

Run these through the shared `wiki_methodology` owner, not a repository-local
copy:

1. `status` — Git-tracked capture currentness and pending sources.
2. `rebuild` — catalog, sources, backlinks, and reverse manifest.
3. bounded `search --write-receipt` — secondary discovery with exact file-back,
   bytes, token estimate, exclusions, and truncation.
4. `lint --strict` — hashes, provenance, links, indexes, supersession,
   derived-authority markers, and query receipt.

Positive output proves only the checked structural and currentness boundaries.
It cannot prove that the human-owned goal is semantically correct. Goal
ambiguity remains in the rollout concern queue and routes through
[[goal-and-requirements]].

Return to [[README]], [[architecture-and-capabilities]], or [[current-work]].
