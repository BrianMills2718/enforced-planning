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

## Operating Result

The framework should let an agent enter a governed repository, load a bounded
and current authority path, execute an approved slice, prove the intended
behavior, and either continue from progress evidence or replan visibly.

Generated fixtures prove mechanics. Current owner-use evidence and the active
gap live in `ROADMAP.md`; eventual colleague packaging is not the current proof
frontier.

## Canonical Descent

- [PLANNING_OPERATING_MODEL.md](PLANNING_OPERATING_MODEL.md)
  - detailed canonical planning methodology
- [ROADMAP.md](ROADMAP.md)
  - current proof, active gap, phase map, and rollout order
- [docs/plans/AGENTS.md](docs/plans/AGENTS.md)
  - active numbered implementation queue

## Rules

- This brief owns purpose and the north-star summary; it stays small.
- `ROADMAP.md` is the only mutable current-state and gap summary.
- Completed implementation plans graduate stable contracts to reference docs;
  historical plans do not remain mandatory context.
- Deeper detail belongs in the linked lower-level docs, not here.
