# Design: Documentation Authority Governance and Enforcement

**Date:** 2026-04-05
**Status:** Proposed

## Problem

Current governed-repo tooling validates several important local truths:

- file-to-doc couplings
- plan status consistency
- truth-surface drift against configured runtime facts

But it does not yet model a more basic governance question:

**Which document is authoritative for a given concern, and how is that enforced?**

Without that layer, a repo can still drift into a state where:

- multiple files appear authoritative for the same concern
- stale handoffs remain active beside current handoffs
- top-level docs contradict status docs
- archived or derived surfaces are mistaken for source-of-truth

The result is semantic and operational drift even when local validators pass.

## Goals

- define a portable authority model for governed repos
- make documentation authority explicit, not implicit in team memory
- enforce one canonical source per concern by default
- support derived, working, and historical surfaces without pretending they are
  canonical
- integrate with pre-commit, CI, and existing truth-surface validation

## Non-Goals

- replace doc-code coupling
- replace truth-surface drift configs
- solve prose quality or style linting
- require every repo to adopt every concern immediately

## Architecture

### Layer 1: Concern Map

Each governed repo declares a small set of documentation concerns, such as:

- `benchmark-status`
- `active-handoff`
- `active-plan-index`
- `roadmap`
- `product-story`

Each concern defaults to one canonical surface.

This layer answers:

- what concerns exist in this repo?
- which concern does each important doc belong to?
- what file is canonical for each concern?

### Layer 2: Document Metadata

Each important authority-bearing doc declares metadata:

- authority tier:
  - `canonical`
  - `derived`
  - `working`
  - `historical`
- concern
- lifecycle status:
  - `active`
  - `superseded`
  - `archived`
- supersession edges
- optional verification provenance

This layer answers:

- what role does this doc play?
- can it define current truth?
- has it been superseded?

### Layer 3: Validator

The validator enforces structural governance:

- one canonical active doc per concern by default
- no active doc superseded by another active doc
- no duplicate active handoffs
- required concerns exist when declared
- declared canonical files actually contain matching metadata
- derived docs cite their canonical upstream where configured

### Layer 4: Enforcement

The validator must run in three places:

1. pre-commit for staged authority surface changes
2. CI for full-repo validation
3. finish/merge workflow for repos that adopt governed completion flows

`make doc-truth-check` remains a human/agent entrypoint only.

## Relationship to Existing Framework Pieces

| Existing Piece | Relationship |
|----------------|--------------|
| `relationships.yaml` static graph | remains the durable graph of couplings and dependencies; authority config can either live beside it or later merge with it |
| `check_doc_coupling.py` | checks source/doc adjacency; authority validator checks concern-level uniqueness and lifecycle |
| `sync_plan_status.py` | remains the specialist plan-status validator; authority validator consumes its outcome or related metadata |
| `check_truth_surface_drift.py` | complementary layer; authority validator is structural and canonical-surface focused |
| semantic review | optional follow-on layer for canonical docs whose prose may still be misleading |

## Canonical Data Model

### Per-doc metadata

Recommended fields:

- `authority`
- `concern`
- `doc_status`
- `supersedes`
- `superseded_by`
- `canonical_source`
- `last_verified_against`

### Repo-level config

Recommended sections:

- `required_concerns`
- `allow_multi_canonical` exceptions
- `duplicate_live_surface_rules`
- `generated_surface_rules`

## Enforcement Semantics

### Fail Conditions

- two active canonical docs for the same concern
- active canonical doc marked superseded
- active handoff concern has more than one active doc
- canonical concern declared in config but file missing or mis-tagged
- derived doc missing configured canonical source reference

### Warn Conditions

- historical doc outside archive path
- canonical doc missing `last_verified_against`
- concern exists in metadata but not in repo config

### Optional Agent Layer

After deterministic validation, a repo may opt into agent review for:

- stale-but-structurally-valid prose
- misleading summaries
- generated summaries that no longer match canonical docs

That layer should never replace structural blocking rules.

## Rollout Strategy

### Stage 1: Advisory Adoption

- add metadata to canonical docs only
- run validator in warn-only mode locally and in CI

### Stage 2: Structural Enforcement

- block duplicate canonical concerns
- block duplicate active handoffs
- require required concerns to be present

### Stage 3: Generated Surface Integration

- generate authority summaries from config + metadata
- wire finish/merge flows to refuse stale authority states

## Why This Should Be Shared Infrastructure

The failure pattern is ecosystem-wide:

- any repo with plans, handoffs, status docs, and top-level summaries can drift
- the enforcement mechanism is generic
- only the concern names and file mappings vary by repo

This is exactly the kind of cross-project governance logic `enforced-planning`
should centralize.

## Key Uncertainties

1. **Config home**
   - Dedicated file is clearer.
   - Extending `relationships.yaml` reduces file count.
   - Recommendation: start with dedicated config, then revisit merge.
2. **Metadata encoding**
   - YAML frontmatter is easiest to validate.
   - HTML comments are lower-friction for Markdown-only repos.
   - Recommendation: frontmatter first, comments only as fallback.
3. **Co-canonical concerns**
   - Most concerns should have one canonical doc.
   - A small exception mechanism may be needed for split source/reference cases.
4. **Auto-fix scope**
   - Safe auto-fixes: generated pointers, index regeneration.
   - Unsafe auto-fixes: choosing which doc should become canonical.

## Recommended Next Step

Implement a first shared slice with:

- authority schema
- repo config schema
- deterministic validator
- pre-commit hook
- CI example wiring

Do not build semantic auto-repair or a cross-repo dashboard in the first slice.
