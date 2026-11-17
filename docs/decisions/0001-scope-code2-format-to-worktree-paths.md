---
description: Scope the code2 format to one capability, canonical repository resolution
---

# 0001 Scope the code2 format to worktree path resolution

Date: 2026-11-17
Status: accepted
Source: inferred by agent, 2026-11-17: (Brian, 2026-11-17: "option B is what i want").

## Context

Enforced Planning has about 70 modules and an existing documentation system (`PLANNING_OPERATING_MODEL.md`, `adr/`, AES files). The code2 format needs Lockstep requirements, but the full suite takes close to an hour, so a whole-repository migration is not feasible in one pass.

## Decision

Adopt the format for one capability with working code and thirteen existing tests: `enforced_planning.worktree_paths`. `make check` runs Lockstep, lint and that capability's tests; the old `check` (lint plus the full suite) becomes `make full`. Existing documents and the `adr/` records are unchanged.

## Consequences

Lockstep coverage reports one requirement. More capabilities join when their code next changes.

## Wrong if

An agent assumes `make check` ran the whole suite and merges a regression in an uncovered module; then `make check` must grow or the nightly `make full` must gate merges.
