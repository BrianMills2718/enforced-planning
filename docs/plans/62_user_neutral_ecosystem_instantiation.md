# Plan #62: User-Neutral Ecosystem Instantiation

**Status:** Planned
**Type:** design + implementation
**Priority:** High
**phase_ref:** "Shareable loop-engineering ecosystem"
**goal_ref:** "portable-governance-cleanroom"
**Blocked By:** #61
**Blocks:** real consumer pilot and agent-adapter slices

## Goal

Turn the clean-room alpha from a synthetic demonstration into a user-neutral
template contract. A new consumer must be able to provide an instance id,
project inventory, and policy-pack metadata without importing Brian’s personal
projects, filesystem paths, credentials, or policy content.

## Boundary

Shareable owns: schema, CLI, generated layout, lifecycle receipts, loop
contracts, portable procedures, and example fixtures.

Consumer-owned: project names and paths, policy decisions, component sources,
credentials, deployment choices, and local operating conventions.

Out of scope for this slice: production sandboxing, signed supply-chain
verification, hosted control planes, real LLM agents, and migration of Brian’s
personal project inventory.

## Modality

The schema and isolation checks are deductive: acceptance tests can be written
before implementation. The onboarding experience is exploratory: the readout is
whether an independent consumer can instantiate and verify the template without
author guidance. Do not claim usability from unit tests alone.

## Contract

`consumer-config.yaml` → validated `ConsumerSpec` → generated clean-room tree
and receipt → structural verification → deterministic loop configuration.

Required invariants:

- all consumer paths are relative to the generated root;
- the generated tree contains no personal sentinel or absolute home path;
- project ids are unique and inventory is the sole project authority;
- policy-pack content is supplied or explicitly marked example;
- component revisions are recorded but never inferred from personal workspace state;
- reset removes only receipt-owned artifacts.

## Acceptance Criteria

1. A consumer config can generate a clean-room root with two non-Brian project
   ids and pass structural verification.
2. Missing, duplicate, absolute, or workspace-relative project paths fail loudly.
3. Generated output contains no `/home/brian`, `BrianMills2718`, personal project
   names, or credentials.
4. The same consumer config is deterministic: plan hashes and generated files
   are stable across fresh roots.
5. The README explains ownership boundaries and the first five-minute path
   without requiring this repository’s maintainer context.
6. An adversarial external-root exercise records both positive and negative
   controls; onboarding usability remains an exploratory readout, not an A-grade
   production claim.

## Thin Slice Order

1. Define and validate `ConsumerSpec` plus a neutral example config.
2. Render inventory, policy metadata, and component lock from that spec.
3. Add CLI `init`/`plan`/`apply` support and receipt ownership tests.
4. Run an independent-consumer exercise from a copied example directory.
5. Audit personal leakage, path traversal, determinism, and reset boundaries;
   update the concern register before the next adapter slice.

## Evidence Grades At Start

| Criterion | Grade | Evidence class |
|---|---|---|
| User-neutral config contract | D | doc |
| Isolation and personal-data exclusion | B | existing alpha tests; new consumer fields untested |
| Deterministic rendering | B | existing plan hashes; consumer inputs untested |
| Independent onboarding | F | no independent consumer exercise yet |

## Concerns

- A config format can accidentally become a second policy authority; inventory
  and policy ownership must remain explicit.
- “Shareable” does not mean safe for hostile repositories; retain alpha wording.
- The first independent-consumer exercise should be run by someone or a clean
  session that does not rely on Brian-specific assumptions.

