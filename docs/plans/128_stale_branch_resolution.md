/home/brian/code/active/enforced-planning/docs/plans/128_stale_branch_resolution.md

Create that file and paste this into it:

# Plan 128: Stale Branch Resolution and Coordination Hook Fallback Evaluation

## Overview
Two unmerged branches exist in enforced-planning without coordination claims or plan ownership:
- `fix/coordination-hook-fallback` (6eca744) — fallback for stale claim projection
- `fix/projection-staleness-atomicity` (8c47e3a) — atomic projection refresh

Plan #127 (Turn-End Safety) is complete. This plan evaluates whether these branches are ready for merge, superseded, or should be archived.

## Scope
1. Investigate both branches to understand the actual changes
2. Determine if coordination-hook-fallback is a real fix ready to merge
3. Determine if atomicity work is superseded by Plan #127 completion
4. Make a disposition decision: merge, keep, or archive
5. Clean up uncommitted prewrite_claim_gate.py change

## Success Criteria
- Both branches evaluated and understood
- Clear disposition for each (merged, kept, or archived)
- Working tree clean
- Decision recorded

## Blockers
None identified initially.

## Status
🟡 Proposed — ready to bootstrap worktree