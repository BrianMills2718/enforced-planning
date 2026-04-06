# Plan #44: Interactive Startup Mode And Session-Owned Surface Policy

**Status:** ✅ Complete
**Type:** design
**Priority:** High
**Blocked By:** Plan #43 publish-lane safety
**Blocks:** Plan #35 queue/routing architecture freeze

## Goal

Define the shared coordination policy for startup surfaces so interactive
sessions only display session-owned work, while autonomous sessions remain
plan-bound, claim-backed, and explicitly routed.

## Why This Phase Exists

The live Claude Code startup brief showed a stale generic `claude-code.yaml`
assignment as if the current session had already been assigned work. That is a
real coordination failure:

1. interactive sessions are human-driven and should not auto-adopt stale work
2. autonomous sessions need stronger routing and ownership guarantees than
   generic tool-level fallback files
3. startup surfaces must distinguish context about other work from ownership of
   the current session

## Research

Reviewed before planning:

- `docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md`
- `docs/plans/33_assignment-layer-session-contract-integration.md`
- `docs/plans/35_queue-based-assignment-and-session-routing-architecture.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- live `ecosystem-ops` startup-brief failure on 2026-04-05 where a stale
  generic `claude-code.yaml` assignment surfaced as if the interactive Claude
  session already owned `theory-forge`

## Scope

### In Scope

- shared policy for interactive vs autonomous startup surfaces
- startup ownership rule: only session-owned assignments may display as current
  assignment
- relationship between startup surfaces, session contracts, assignments, and
  future queue/routing architecture
- downstream adoption guidance for repos like `ecosystem-ops`

### Out Of Scope

- implementing full queue-based routing in this slice
- redesigning the whole dashboard/assignment UX
- replacing session contracts with a second registry

## Pre-Made Decisions

| Topic | Decision | Why |
|---|---|---|
| Interactive startup rule | show only session-owned assignments | avoids generic fallback files masquerading as real ownership |
| Autonomous startup rule | require plan-bound claim/session context | keeps unattended work explicit and recoverable |
| Generic fallback treatment | compatibility-only, not startup truth | preserve older routing files without lying to operators |
| Other-claim display | contextual only, never phrased as current assignment | separates global state from current-session ownership |
| Queue relationship | Plan #35 must build on this policy, not redefine it | one coordination model |

## Files Expected

- `docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `ROADMAP.md`
- optional downstream adoption notes once the policy is implemented in consumers

## Acceptance Criteria

- the shared operator policy distinguishes interactive vs autonomous startup
  behavior clearly
- session-owned startup display rules are explicit
- Plan #35 can reference this plan instead of rediscovering the same boundary

## Verification

```bash
python scripts/self_test.py --docs
python scripts/check_markdown_links.py docs/plans/44_interactive-startup-mode-and-session-owned-surface-policy.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md ROADMAP.md
```
