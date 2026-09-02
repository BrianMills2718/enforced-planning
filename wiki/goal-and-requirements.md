---
title: Goal and Requirements
type: project
status: current
authority: derived
classification: internal
created: 2026-09-02
updated: 2026-09-02
sources: [src-repository-fe0693bf70aa-ba174ff4, src-repository-6b5684f88799-03d49981, src-repository-15cd61a14612-f66e192c]
---

# Goal and requirements

## Goal stated by native authority

Enforced Planning is the portable planning and governance framework that lets
humans review goals, requirements, plans, and decisions upstream while coding
agents execute bounded work and prove the result downstream. Its source
repository owns the installer, planning model, claims, sessions, sanctioned
worktrees, and deterministic verification surfaces.[^instructions][^overview][^model]

That statement is a synthesis of aligned native authorities, not a goal inferred
from the current code. This repository does not yet expose one separately named
PRD or goal file that alone owns the full wording; the ambiguity is retained in
the rollout concern queue rather than silently resolved here.

## Requirements that protect the goal

1. Human intent outranks generated orientation. Goals, requirements, accepted
   plans, and ADRs are native authority; this wiki is derived navigation.
2. Reversible agent execution uses the smallest valid plan/claim/worktree
   contract for the real coordination boundary.
3. Implementation claims require focused behavioral evidence and an authentic
   consumer path, not only code presence or isolated tests.
4. Current operating state comes from [`ROADMAP.md`](../ROADMAP.md), the
   [plan index](../docs/plans/CLAUDE.md), claims, and runtime receipts—not stale
   sprint documents.
5. The framework reuses one canonical capability owner and installer rather
   than creating downstream copies.

## Non-goals and danger boundaries

- Do not reconstruct a missing project goal from code or tests.
- Do not let the wiki supersede plans, ADRs, config, code, or evidence.
- Do not present historical development trackers as current instructions.
- Do not confuse generated `AGENTS.md` or installed consumer files with their
  canonical source owner.

Continue through [[architecture-and-capabilities]] for ownership and seams,
[[current-work]] for the live frontier, or [[evidence-and-verification]] for
proof.

[^instructions]: [`src-repository-fe0693bf70aa-ba174ff4`](../raw/sources/2026/src-repository-fe0693bf70aa-ba174ff4/source.md), repository instructions at `ecbf214664cd6db2d3bbc2e0689e2107927414cd`.
[^overview]: [`src-repository-6b5684f88799-03d49981`](../raw/sources/2026/src-repository-6b5684f88799-03d49981/source.md), repository overview at the same revision.
[^model]: [`src-repository-15cd61a14612-f66e192c`](../raw/sources/2026/src-repository-15cd61a14612-f66e192c/source.md), canonical planning operating model at the same revision.
