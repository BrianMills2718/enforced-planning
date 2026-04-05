# Research: Documentation Authority Governance and Enforcement

**Date:** 2026-04-05
**Status:** Research / For Review

---

## Question

How should the ecosystem prevent documentation drift where multiple files act
authoritative at once, stale handoffs remain "live," and advisory checks exist
without blocking enforcement?

## Trigger

A DIGIMON documentation audit exposed a repeated pattern that is broader than
one repo:

- top-level docs overstated benchmark performance relative to current status
- multiple files disagreed about the active plan
- stale handoffs remained adjacent to current ones
- plan indexes and plan files drifted apart
- the repo had useful validation commands, but not a complete authority model

This is not a DIGIMON-only problem. It is a missing cross-project governance
layer.

## Existing Framework Pieces That Already Solve Part of This

`enforced-planning` already has several adjacent mechanisms:

- static documentation graph pattern:
  `patterns/09_documentation-graph.md`
- source-to-doc coupling pattern:
  `patterns/10_doc-code-coupling.md`
- plan status consistency checks:
  `patterns/23_plan-status-validation.md`
- deterministic truth-surface drift validation:
  `scripts/check_truth_surface_drift.py`
- semantic review layer for prose drift:
  `scripts/review_truth_surface_semantic.py`
- enforcement wiring through pre-commit and CI:
  `.pre-commit-hooks.yaml`, `hooks/git/pre-commit`

What is still missing is a higher-level model of:

- which file is canonical for each concern
- which surfaces are merely derived or historical
- how to prevent duplicate live handoffs
- how to validate agreement between declared authority and repo reality

## Observed Failure Pattern

The core failure is not "docs were stale." The core failure is:

1. too many surfaces can plausibly act authoritative
2. nothing encodes which one wins for a given concern
3. enforcement focuses on local couplings, not whole-concern authority
4. humans and agents must remember the authority map from context

That does not scale.

## Candidate Solution Shapes

### Option A: More Couplings Only

Extend doc-code couplings and truth-surface configs, but do not add a new
authority model.

Pros:

- minimal new concepts
- reuses existing validators

Cons:

- couplings answer "what changes with what," not "which file is canonical"
- duplicate active handoffs remain possible
- top-level docs can still contradict status docs without any explicit concern
  ownership

Assessment: insufficient.

### Option B: Canonical Concern Map + Metadata + Validator

Add a shared governance layer with:

- canonical concern map per repo
- per-doc metadata declaring authority tier and concern
- validator that checks uniqueness and drift
- hook/CI enforcement

Pros:

- directly encodes authority, not just adjacency
- portable across repos
- composes cleanly with existing couplings and truth-surface checks

Cons:

- introduces new metadata and config surface
- requires rollout/migration work

Assessment: strongest option.

### Option C: Generate Most Docs From One Registry

Push toward one generated active-work/status/handoff surface and minimize
handwritten docs.

Pros:

- reduces manual drift

Cons:

- only feasible for some surfaces
- product/architecture docs remain prose and still need authority rules

Assessment: good complement, not a full solution.

## Recommended Model

Use three layers:

1. **Authority declaration**
   - per-repo concern map
   - per-doc metadata for concern, authority tier, lifecycle
2. **Deterministic validation**
   - one canonical doc per concern
   - no duplicate active handoffs
   - supersession chains are consistent
   - generated/derived docs point back to canonical sources
3. **Enforcement**
   - pre-commit for changed metadata and declared authority files
   - CI for full-repo validation
   - completion/merge workflows invoke the same validator

This fits the framework principle:

- programmatic for structural coverage
- agents for semantic review or auto-fix
- humans for decisions about the authority model itself

## What Should Stay Shared vs Project-Specific

### Shared

- metadata schema
- validator engine
- common failure codes
- enforcement hook/CI recipes
- rendering helpers for authority summaries

### Project-Specific

- list of concerns
- which file is canonical for each concern
- artifact truth checks beyond generic authority logic
- repo-specific derived surfaces

## Enforcement Conclusion

`make doc-truth-check` is useful as an operator entrypoint, but it is not enough.
The actual enforcement must be:

- pre-commit hook when relevant authority surfaces change
- CI gate on pull requests
- optional merge/finish workflow invocation

Anything softer recreates the same "warn and hope" failure mode.

## Off-The-Shelf vs Custom

What should be reused:

- pre-commit hook framework
- GitHub Actions / existing CI runner
- existing `enforced-planning` validators and hook patterns

What still appears custom:

- concern-level canonical authority model
- duplicate-live-surface detection
- cross-surface semantic governance for repo-local doc stacks

Generic style/doc lint tools are not enough here. This is about repo-specific
truth and authority, not grammar or formatting.

## Open Questions

1. Should metadata live in frontmatter, HTML comments, or a sidecar manifest?
2. Should historical docs require metadata, or can archive paths imply status?
3. Should every concern have exactly one canonical surface, or can some support
   an intentionally small set of co-canonical files?
4. Should the validator auto-rewrite generated pointers, or only fail loudly?
5. Should the concern map live in `meta-process.yaml`, `relationships.yaml`, or
   a dedicated authority config?

## Recommendation

Proceed with a dedicated shared design and implementation plan:

- authority metadata schema
- concern map config
- deterministic validator
- pre-commit + CI enforcement
- rollout guidance for governed repos
