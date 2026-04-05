# Enforced Planning

Source repo for the portable planning and governance framework.

## Continuous Execution Contract

This repo is currently running in explicit continuous-execution mode.

- Treat this as the canonical overnight execution contract for the repo, not a
  soft preference.
- Do not stop at plan creation, green tests, or one completed commit.
- Execute the active numbered queue continuously until all planned phases are
  complete or a documented stop condition is reached.
- Work in sanctioned worktrees between merges/pushes rather than piling new
  overnight work onto a dirty primary checkout.
- Commit every verified slice so rollback is cheap and exact.
- Merge and push verified slices from the root-anchored control session, then
  clean the finished worktree and release the lane claim before starting the
  next slice.
- If a concern or uncertainty appears, document it in the active plan or sprint
  tracker immediately; do not leave it only in chat.

Non-negotiable execution rules for continuous runs:

1. every active implementation slice gets its own numbered plan
2. every active implementation slice runs in its own sanctioned worktree
3. every verified increment gets a commit before the next slice starts
4. no finished slice is left only on a worktree branch; merge/push/cleanup is
   part of completion, not optional follow-up
5. if a stop condition is hit, document it in the active plan and repo tracker
   before ending the session

Only two stop conditions are legitimate:

1. an irreversible action that affects shared state
2. a genuine architectural decision not already pre-made in the active plan

## Canonical Surfaces

- `PLANNING_OPERATING_MODEL.md`
  - canonical methodology and artifact dependency graph
- `README.md`
  - source-repo overview: what the framework is, what ships, and how governed
    repos install it
- `GETTING_STARTED.md`
  - first successful installed-consumer path
- `ROADMAP.md`
  - forward queue and phase map
- `docs/plans/CLAUDE.md`
  - numbered implementation plan queue for this repo
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
  - canonical definitions for claims, lanes, worktrees, and lane lifecycle
- `docs/reference/CONFIG_REFERENCE.md`
  - authoritative config table, including which keys are not yet enforced

## Source Repo vs Installed Repo

Keep the perspectives separate:

- In this source repo, scripts live under `scripts/`
- In installed governed repos, generated entrypoints live under `scripts/meta/`
- `scripts/install_governed_repo.py` is the canonical installer/upgrader
- `install.sh` is a convenience wrapper for the default path and a legacy
  compatibility entrypoint for `--full` and `--pre-commit`

## Tool Support

- Claude Code has the strongest native interactive enforcement path because
  read-gating is wired through `.claude/hooks/`
- Other tools use generated `AGENTS.md`, the plan/doc methodology, and
  deterministic validators
- The portable support matrix and rollout policy are tracked in the Phase 8
  plan queue, not in ad hoc sprint notes

## Commands

```bash
# Canonical governed-repo install / upgrade
python scripts/install_governed_repo.py --repo-root /path/to/project --write
python scripts/audit_governed_repo.py --repo-root /path/to/project --strict-governed

# Convenience / legacy shell wrapper
./install.sh /path/to/project
./install.sh /path/to/project --worktree-only
./install.sh /path/to/project --pre-commit
./install.sh /path/to/project --full

# Framework validation
python scripts/self_test.py
python scripts/validate_plan.py --plan-file docs/plans/NN_example.md --warn-only
python scripts/check_plan_capabilities.py docs/plans/

# Source-repo maintenance
python scripts/render_agents_md.py --stdout
python scripts/sync_plan_status.py
python scripts/complete_plan.py --plan N

# Tests
pytest -q
make test
```

## Repo Workflow

1. Use `docs/plans/CLAUDE.md` and `ROADMAP.md` to find the next bounded slice.
2. Work from the matching numbered plan doc.
3. Prefer sanctioned worktrees for multi-phase or overnight execution lanes.
4. Keep source-repo docs truthful when installer behavior, support tiers, or
   plan status changes.
5. Run `python scripts/self_test.py` before landing documentation or installer
   changes.

## Notes

- This repo is the framework source of truth; installed governed repos are
  consumers of generated/copied surfaces from here.
- `AGENTS.md` is a generated mirror, not a second authority.
- Historical sprint notes under `docs/ops/` are evidence artifacts, not the
  active planning queue.
