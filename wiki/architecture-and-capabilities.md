---
title: Architecture and Capabilities
type: architecture
status: current
authority: derived
classification: internal
created: 2026-09-02
updated: 2026-09-02
sources: [src-repository-6b5684f88799-03d49981, src-repository-15cd61a14612-f66e192c, src-repository-3a517734fc69-949f2e8e, src-repository-6d892250b3e8-caba9f80, src-repository-96eb39bc8147-cb5e4de7]
---

# Architecture and capabilities

## Ownership map

| Layer | Canonical seam | What it owns |
| --- | --- | --- |
| Methodology | [`PLANNING_OPERATING_MODEL.md`](../PLANNING_OPERATING_MODEL.md) | artifact hierarchy, authority, evidence, and planning behavior |
| Configuration | [`meta-process.yaml`](../meta-process.yaml) and [`docs/reference/CONFIG_REFERENCE.md`](../docs/reference/CONFIG_REFERENCE.md) | effective governed-repository modes |
| Installation | [`scripts/install_governed_repo.py`](../scripts/install_governed_repo.py) | canonical install and upgrade path |
| Runtime package | [`enforced_planning/`](../enforced_planning/) | typed claims, sessions, readiness, audit, context, and lifecycle behavior |
| Operator entrypoints | [`Makefile`](../Makefile) and [`scripts/`](../scripts/) | stable commands over the runtime owners |
| Verification | [`tests/`](../tests/) and repository evidence | both-sign contract checks and authentic receipts |

The framework treats documentation as hierarchical context compression: every
layer must provide unique compression, have a consumer, and remain fresh. The
context graph routes agents between layers; it does not make a derived layer
authoritative.[^adr5]

## Main capabilities

- install or audit the governed-repository contract;
- render instruction surfaces and enforce read-first context;
- bind plans to claims, sessions, worktrees, and closeout;
- validate documentation coupling and planning integrity;
- expose current effective profile and derived-wiki freshness;
- retain exact evidence for what ran, at which revision, with which result.

The portable governance/wiki work extends the existing installer, audit, config,
and derived-wiki owners. It explicitly rejects a second installer, policy
language, wiki format, or authority source.[^plan128]

## Exact implementation routes

- Claim semantics: [`enforced_planning/coordination_claims.py`](../enforced_planning/coordination_claims.py)
- Session lifecycle: [`enforced_planning/session_lifecycle.py`](../enforced_planning/session_lifecycle.py)
- Plan validation: [`enforced_planning/plan_validation.py`](../enforced_planning/plan_validation.py)
- Effective profile: [`enforced_planning/effective_project_profile.py`](../enforced_planning/effective_project_profile.py)
- Installer tests: [`tests/test_install_governed_repo.py`](../tests/test_install_governed_repo.py)
- Coordination tests: [`tests/test_coordination_claims.py`](../tests/test_coordination_claims.py)

Return to [[README]] or follow [[current-work]] and
[[evidence-and-verification]].

[^adr5]: [`src-repository-3a517734fc69-949f2e8e`](../raw/sources/2026/src-repository-3a517734fc69-949f2e8e/source.md), accepted ADR 0005.
[^plan128]: [`src-repository-96eb39bc8147-cb5e4de7`](../raw/sources/2026/src-repository-96eb39bc8147-cb5e4de7/source.md), current portable governance/wiki plan.
