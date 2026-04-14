# Enforced Planning Execution Brief

## Purpose

`enforced-planning` is the source repo for the portable planning and governance
framework used across Brian's project ecosystem.

This repo exists to make agent and human development work mechanically
governable through:

- bounded implementation plans
- deterministic validation
- governed repo installation and upgrade tooling
- read-gating and documentation coupling
- coordination and session lifecycle infrastructure

## Current Gate

Phase 9 is the active gate.

The framework capability set is effectively complete. The active work is now:

- fleet adoption
- framework maintenance
- dogfooding the recursive documentation spine before downstream rollout

## Active Workstreams

- installer and upgrade rollout
- ecosystem status and operator surfaces
- recursive documentation-spine dogfood in this repo
- downstream governed-repo adoption support

## Top Risks

- the framework can require documentation discipline downstream before proving
  the operator experience on itself
- top-level repo guidance can drift from validator and installer behavior
- documentation volume can grow faster than abstraction clarity if the
  execution brief and bounded summaries are not kept small

## Canonical Descent

- [PLANNING_OPERATING_MODEL.md](PLANNING_OPERATING_MODEL.md)
  - north star and canonical methodology
- [docs/overview/CURRENT_STATE.md](docs/overview/CURRENT_STATE.md)
  - current durable state of the framework
- [docs/overview/GAP_SUMMARY.md](docs/overview/GAP_SUMMARY.md)
  - highest-value deltas between current state and target state
- [ROADMAP.md](ROADMAP.md)
  - phase map and queued gates
- [docs/plans/CLAUDE.md](docs/plans/CLAUDE.md)
  - active numbered implementation queue

## Rules

- This brief stays small and execution-oriented.
- Deeper detail belongs in the linked lower-level docs, not here.
