# Plan #131: Terminal Closeout and Hook Hot-Path Repair

**Status:** Complete
**Type:** implementation
**Priority:** Critical

## User outcome

A claimed linked worktree has one terminal path: integrate or explicitly
disposition its branch, run `session-close`, and atomically remove the local
worktree, local branch, and live ownership record while retaining exact audit
history. Coordination hooks remain comfortably inside their three-second
budget as that history grows.

## Reproduced failures

- `session-finish` could mark a clean claimed lane `completed` while leaving
  its worktree and branch behind.
- generic claim release could detach live ownership from an existing managed
  Git lane.
- plan completion could mark matching claims completed independently of lane
  cleanup.
- terminal YAML stayed in the synchronous claim registry until an optional
  prune, producing 1,692 files and 5.29–8.34 second PreToolUse callbacks.
- the legacy completed-claim drain recomputed registry/projection freshness per
  removed record; a full-size copy still exceeded 60 seconds under one lock.

## Adopted design

1. `session-finish` owns dirty handoff only; clean managed lanes must use
   `session-close`.
2. generic release refuses an existing managed worktree or branch; it remains
   available for pre-worktree transactional rollback.
3. plan completion verifies that its lane closeouts already happened instead
   of manufacturing completed claim state.
4. `session-close` writes the terminal claim, records its closeout receipt,
   archives the exact YAML bytes, removes the live-registry file, refreshes the
   projection, and records the archive-bound prune receipt under the same
   registry lock.
5. non-worktree plan-claim completion uses the same immediate archive path.
6. the legacy drain advances its digest-bound projection from one lock-owned
   snapshot and performs one terminal full rebuild, not two full scans per
   removed record.

## Acceptance criteria

- Clean `session-finish`, plan completion with a live lane, and generic release
  of an existing managed lane all fail without changing ownership.
- Successful `session-close` removes worktree, local branch, and live YAML and
  leaves an intrinsically validated exact-byte archive receipt.
- Per-record prune receipts retain an exact digest chain while full registry
  rebuild count remains constant with claim count.
- A migration removes the accumulated completed YAML from the live registry.
- The configured coordination hook completes below one second after migration,
  with the three-second timeout retained as a circuit breaker.
- Focused lifecycle, installer, merge, hook, and complete-plan tests pass;
  pre-existing unrelated failures are demonstrated against untouched `main`.

## Rollback

Revert the implementation commit. Archived claim receipts are append-only and
remain valid audit evidence; they do not need to be restored to the hot
registry for rollback.

## Verification evidence

- Selected lifecycle, claim, hook, merge, complete-plan, and installer
  regressions: `303 passed, 8 deselected`.
- Framework self-test: `ALL CHECKS PASSED`.
- Live migration: 1,650 completed YAML records archived and removed; the hot
  registry fell from 1,701 files to 51 while active and retained statuses were
  preserved.
- Seven authentic `PreToolUse` hook probes after migration completed in
  0.1497–0.1692 seconds (0.1552-second median), below the one-second acceptance
  criterion and the three-second circuit breaker.
- The eight deselected failures were scoped before acceptance: the three known
  session/claim baseline failures, one existing mutation-audit fixture failure,
  and four existing installer expected-surface drift failures reproduce on
  untouched `main`.
