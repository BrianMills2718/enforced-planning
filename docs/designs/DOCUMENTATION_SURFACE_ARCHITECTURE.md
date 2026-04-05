# Design: Documentation Surface Architecture and Convergence

**Date:** 2026-04-04
**Status:** Proposed

## Problem

`enforced-planning` currently mixes three different perspectives:

1. the framework source repo
2. the installed governed-repo view
3. historical extraction/provenance from `agent_ecology2`

The planning methodology is comparatively coherent, but the product surface is
not. Adoption docs, installer behavior, roadmap/status surfaces, and semantic
review tooling do not currently present one compendious story.

## Goals

- define one canonical role for each top-level doc surface
- separate source-repo guidance from installed-repo guidance
- reduce duplicated setup instructions
- reduce provenance noise so the framework reads as standalone
- make the future execution queue visible and ordered

## Non-Goals

- redesign the planning operating model itself
- remove historical evidence or archived sprint artifacts
- decide Phase 8 implementation details beyond queueing the work clearly

## Canonical Surface Roles

### Source-repo authority surfaces

These explain the framework itself:

- `PLANNING_OPERATING_MODEL.md`
  - canonical doctrine and artifact dependency graph
- `README.md`
  - source-repo overview: what the framework is, what ships, support matrix,
    install entrypoints, and where to go next
- `ROADMAP.md`
  - forward-looking phase map and current execution queue only
- `patterns/01_README.md`
  - catalog of available patterns and prerequisites
- `docs/reference/CONFIG_REFERENCE.md`
  - authoritative config key table, including which keys are not yet enforced
- `hooks/README.md`
  - hook reference and portability details, not first-time onboarding

### Installed governed-repo adoption surfaces

These explain how a consumer repo should look and behave after installation:

- `GETTING_STARTED.md`
  - shortest path to a first successful governed-repo install
- `docs/guides/NEW_PROJECT_SETUP.md`
  - detailed operator setup and troubleshooting
- `templates/meta-process.yaml.example`
  - canonical config shape

The adoption surfaces must describe the installed file layout exactly as the
canonical installer produces it.

## Canonical Perspective Split

Each doc must stay inside one of these perspectives:

- **framework-source perspective**
  - commands run from the `enforced-planning` repo
  - paths inside this repo
  - decisions about what the framework ships
- **installed-consumer perspective**
  - commands run from the governed repo root
  - installed file paths such as `scripts/meta/...`
  - expected local repo behavior after install

The same section should not silently switch perspectives.

## Canonical Installed-Repo Model

Until the installer convergence work lands, the docs should describe the model
that currently exists in the installed repo:

- `meta-process.yaml`
- `docs/plans/CLAUDE.md`
- `docs/plans/TEMPLATE.md`
- `scripts/meta/...`
- `scripts/relationships.yaml`
- `hooks/`
- `.claude/hooks/`
- `docs/meta-patterns/`

Docs must not describe a target repo that contains a copied
`enforced-planning/` subtree unless that model is restored intentionally.

## Canonical Semantic Review Model

The framework currently has two semantic-review paths:

- legacy repo-wide `review_truth_surfaces.py`
- newer config-driven `review_truth_surface_semantic.py`

That is not sustainable. The framework needs one canonical semantic-review
entrypoint, one output model, one Makefile workflow, and one promotion story.

## Provenance Policy

`agent_ecology2` should remain provenance only:

- one short origin note in `README.md`
- optional brief origin note in `patterns/01_README.md`

It should not be used as the main explanatory frame for adoption or for domain
term replacement tables in the top-level docs.

## Recommended Doc Stack

Ordered by first-pass reader flow:

1. `README.md`
2. `GETTING_STARTED.md`
3. `PLANNING_OPERATING_MODEL.md`
4. `patterns/01_README.md`
5. `ROADMAP.md`
6. deeper references (`hooks/README.md`, config reference, guides, pattern docs)

## Recommended Execution Order

1. converge installer authority
2. converge semantic-review authority
3. rewrite top-level adoption/docs against those decisions
4. continue Phase 8 execution planning from the cleaned product surface

## Open Decisions

- should `install.sh` delegate to `scripts/install_governed_repo.py`, or vice
  versa?
- should semantic review stay repo-wide (`--repo`) or config-driven
  (`--config`) as the canonical interface?
- should `docs/guides/NEW_PROJECT_SETUP.md` remain as a separate detailed guide,
  or be folded into `GETTING_STARTED.md` after convergence?
