# Coordination Handoff — 2026-04-05

## Current Mission

Continue the shared coordination hardening batch in `enforced-planning` after
landing:

- Plan #42: atomic closeout and claimed worktree removal
- Plan #43: publish-lane safety and dirty-primary-checkout handling

The active next slice is:

- Plan #44: interactive startup mode and session-owned surface policy

Broader goal:

- make startup and routing surfaces truthful enough that interactive sessions do
  not look auto-assigned, autonomous sessions remain plan-bound, and future
  queue/routing architecture can build on one explicit boundary

## Canonical Current State

### Repo: `enforced-planning`

- root path: `/home/brian/projects/enforced-planning`
- branch: `main`
- remote state: pushed through `2555787`
- latest landed commits:
  - `2555787` `[Merge] Land Plan 43 publish-lane safety`
  - `f7eda1f` `[Plan #43] Add publish-lane safety preflight`
  - `24f3b1a` `[Merge] Land Plan 42 atomic closeout lifecycle`
  - `0ae0ec7` `[Plan #42] Implement atomic claimed-lane closeout`

### Important root dirt in `enforced-planning` that is NOT this lane

Do not touch unless explicitly taking over that separate work:

- modified: `adr/README.md`
- untracked: `adr/0010-agent-memory-as-planning-input.md`

`git status --short --branch` in the root currently shows exactly:

```text
## main...origin/main
 M adr/README.md
?? adr/0010-agent-memory-as-planning-input.md
```

### Active worktree for continuation

- worktree path: `/home/brian/projects/enforced-planning_worktrees/plan-44-startup-mode-policy`
- branch: `plan-44-startup-mode-policy`
- active claim:
  - project: `enforced-planning`
  - scope: `startup-mode-policy`
  - plan: `Plan #44`
  - session name: `coordination-startup-truthfulness`
- session tracker:
  - `/home/brian/.claude/coordination/sessions/enforced-planning/codex__enforced-planning__codex-019d59cb-0577-7700-9a5f-0e7d40576a6a__coordination-startup-truthfulness.yaml`

### Other active claims not to overlap

- `project-meta:research-provenance-graph`
- `research_texts:topic-convergence`

## What Was Just Landed

### Plan #42

Plan #42 is fully landed, pushed, and self-proven:

- merged to `enforced-planning/main`
- pushed to origin
- claim released
- worktree removed
- branch deleted
- closeout performed with the new canonical `scripts/session_close.py`

Main outputs:

- `scripts/session_close.py`
- atomic closeout in `enforced_planning/session_lifecycle.py`
- `session-close` surfaced in installer/template/operator docs

### Plan #43

Plan #43 is fully landed and pushed on `main`.

Main outputs:

- `scripts/worktree-coordination/create_publish_worktree.py`
- `create_worktree.py` supports `--require-clean-main-root`
- publish-lane preflight now fails loud when canonical main checkout is dirty
- docs updated with the next-chain execution order

Main plan/docs added or updated:

- `docs/plans/43_publish-lane-safety-and-dirty-primary-checkout-handling.md`
- `docs/plans/44_interactive-startup-mode-and-session-owned-surface-policy.md`
- `docs/ops/SPRINT_2026_04_05_COORDINATION_NEXT_CHAIN.md`
- `CLAUDE.md`
- `ROADMAP.md`
- `docs/plans/CLAUDE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`

Verification that already passed for Plan #43 on trunk:

```bash
cd /home/brian/projects/enforced-planning
PYTHONPATH=. pytest -q tests/test_create_worktree.py tests/test_install_governed_repo.py tests/test_merge_pr.py
python scripts/self_test.py --docs
```

## Important Downstream Context

### `ecosystem-ops` startup-brief fix exists but is NOT landed to trunk

There is a pushed branch in `ecosystem-ops`:

- branch: `plan-23-session-brief-mode-gating`
- remote branch exists on origin
- last branch commit sequence:
  - `8c7e6df` `[Plan #23] Make startup brief session-owned and truthful`
  - `518a681` `[Plan #23] Record publish blocker for startup brief lane`

That branch suppresses generic fallback assignment display in startup-facing
surfaces and fixes v2-claim project rendering in `session_brief.py`.

Why it is not merged:

- `ecosystem-ops/main` root checkout is dirty with unrelated work
- there was a live publish-worktree failure during landing
- Plan #43 was created from that failure mode

Current `ecosystem-ops` root status snapshot:

```text
## main...origin/main
 M anomaly_triage.py
 M capability_registry.py
 M consistency_check.py
 M models.py
 M plan_graph.py
 M task_recommender.py
 M web/app.py
?? .claude/
?? assessments/_enrichment_20260405_1127.md
?? docs/plans/23_governance_deficit_priority_boost.md
?? tests/test_task_recommender.py
```

Operational mitigation already applied:

- stale generic assignment file `~/.claude/coordination/assignments/claude-code.yaml`
  was cleared, so new Claude Code startup no longer shows the false
  `theory-forge` assignment line

But the shared policy still needs to be landed in `enforced-planning` (Plan #44)
before deciding how to downstream it cleanly.

## Current Queue (frozen on disk)

See:

- `/home/brian/projects/enforced-planning/CLAUDE.md`
- `/home/brian/projects/enforced-planning/ROADMAP.md`
- `/home/brian/projects/enforced-planning/docs/ops/SPRINT_2026_04_05_COORDINATION_NEXT_CHAIN.md`

Mandatory order now:

1. Plan #44 — interactive startup mode and session-owned surface policy
2. Plan #35 — queue-based assignment and session routing architecture

Do not reorder casually without documenting why.

## Recommended Next Steps For The Next Agent

### 1. Resume Plan #44 in the existing worktree

Start here:

```bash
cd /home/brian/projects/enforced-planning_worktrees/plan-44-startup-mode-policy
git status --short --branch
```

Then read:

```bash
sed -n '1,260p' docs/plans/44_interactive-startup-mode-and-session-owned-surface-policy.md
sed -n '1,260p' docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md
sed -n '150,320p' docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md
```

### 2. Land Plan #44 as shared policy/design

Recommended implementation shape:

- update `docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md`
  - define explicit interactive vs autonomous startup semantics
  - define “session-owned startup surfaces only” rule
  - define how Plan #35 must build on that boundary
- update `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
  - operator-facing rule for startup surfaces
- update `ROADMAP.md`, `docs/plans/CLAUDE.md`, and `CLAUDE.md`
  - mark Plan #44 in progress/complete as appropriate
  - make next order explicit (`44 -> 35`)

Keep this a bounded documentation/policy slice unless a truly small shared-code
change is necessary.

### 3. Verify Plan #44

Expected verification commands:

```bash
cd /home/brian/projects/enforced-planning_worktrees/plan-44-startup-mode-policy
python scripts/self_test.py --docs
python scripts/check_markdown_links.py CLAUDE.md ROADMAP.md docs/plans/CLAUDE.md docs/plans/44_interactive-startup-mode-and-session-owned-surface-policy.md docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md
python scripts/validate_plan.py --plan-file docs/plans/44_interactive-startup-mode-and-session-owned-surface-policy.md --warn-only
```

### 4. Commit, merge, push, close Plan #44

Preferred pattern:

1. commit in the Plan 44 worktree
2. merge onto `/home/brian/projects/enforced-planning` root `main`
   - use `git -c merge.autostash=false merge --no-ff ...` if plain merge tries
     to autostash the unrelated ADR dirt
3. run post-merge verification on root `main`
4. push `origin main`
5. run `python scripts/session_close.py ...` from the root checkout to close the
   lane

## Known Workflow Edge Cases

These were hit live, not hypothetically:

1. `git merge` on the dirty `enforced-planning` root may fail with
   `fatal: stash failed` because some merge/autostash config tries to stash
   unrelated root dirt first.
   Safe workaround:

   ```bash
   git -c merge.autostash=false merge --no-ff <branch> -m "<message>"
   ```

2. Creating a secondary publish worktree from a repo with dirty/conflicted
   primary state can produce a broken checkout with mass deletions/untracked
   duplicates.
   Plan #43 now makes that fail loud before creation instead.

3. `ecosystem-ops` still has an unlanded branch for the startup-brief fix.
   Do not try to force-merge that branch without explicitly adjudicating the
   dirty root checkout there.

## If Time Remains After Plan #44

Move to Plan #35 in a new dedicated worktree and treat it as a design freeze,
not a queue implementation sprint. The key requirement is: queue/routing must
sit on top of the explicit startup/session policy, not create a parallel
identity model.
