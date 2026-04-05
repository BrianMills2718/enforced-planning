# META-ADR-0009: Governed Repos Must Declare Documentation Authority and Enforce It

**Status:** Proposed
**Date:** 2026-04-05

## Context

The framework already enforces several important local truths:

- doc-code couplings
- plan status consistency
- truth-surface drift against configured runtime facts

But governed repos can still fail in a more basic way: multiple documents can
simultaneously appear authoritative for the same concern.

Common examples:

- a stale handoff remains active beside the real current handoff
- top-level docs advertise performance or status that no longer matches the
  canonical status surface
- plan index, current status, and roadmap disagree on what work is active

When this happens, neither humans nor agents can reliably answer "which file is
truth?" without reconstructing context from memory. That is not a governed
system.

## Decision

Governed repos must support a documentation authority model with:

1. **Concern-level authority**
   - repos declare documentation concerns such as `roadmap`,
     `benchmark-status`, or `active-handoff`
2. **Per-doc metadata**
   - authority tier, concern, lifecycle status, and supersession edges
3. **Deterministic validation**
   - duplicate active canonical docs fail by default
   - duplicate active handoffs fail by default
   - required concerns must exist
4. **Blocking enforcement**
   - validator runs in pre-commit and CI for adopted repos

The default policy is:

- one active canonical doc per concern
- other docs for that concern must be explicitly `derived`, `working`, or
  `historical`
- advisory commands are not sufficient; enforcement must block merges or
  commits once the repo opts into the governance slice

## Consequences

### Positive

- repos encode authority explicitly instead of relying on team memory
- stale handoffs and duplicate status surfaces become mechanically detectable
- existing truth-surface and coupling validators gain a clear authority layer to
  build on
- the pattern is portable across all governed repos

### Negative

- important docs need metadata
- repos must define a concern map instead of letting authority remain implicit
- rollout requires migration effort and some short-term friction

### Neutral

- this does not replace doc-code coupling or semantic review
- this does not require every repo to adopt every concern immediately

## Research Basis

| Source | Relevance |
|--------|-----------|
| `docs/research/2026-04-05-doc-authority-governance-notes.md` | Summarized the cross-project failure pattern and compared solution shapes; this ADR adopts the concern-map-plus-validator model |
| `patterns/09_documentation-graph.md` | Established that durable static governance belongs in an explicit graph rather than runtime memory |
| `patterns/10_doc-code-coupling.md` | Showed why file-to-doc adjacency checks are necessary but insufficient for concern-level authority |
| `patterns/23_plan-status-validation.md` | Demonstrated the existing specialist pattern for status consistency that this ADR generalizes upward |
| `Digimon_for_KG_application/CURRENT_STATUS.md` | Concrete example of a valid status surface that can still be contradicted by other repo docs when authority is not explicit |

## Open Uncertainties

- whether authority config should remain a dedicated file or merge into
  `relationships.yaml`
- whether frontmatter should be the only metadata carrier
- whether a small co-canonical exception mechanism is needed in v1
