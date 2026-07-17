# Enforced Planning

Source repo for the portable planning and governance framework.

## Continuous Execution Contract

Continuous authorization uses one of three profiles from
`docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md`:

- `continuous-light` is the default for reversible single-writer development
  and functional PoCs. Reuse the existing task authority, run focused checks,
  and do not require a numbered plan, tracker, claim, or worktree solely because
  the user requested continuous work.
- `continuous-coordinated` adds one shared tracker, scoped claims, and worktrees
  when writers or dependent phases can collide.
- `continuous-release` adds immutable candidate and broad terminal controls for
  publication, migration, deployment, or another consequential terminal claim.

All profiles commit and push verified increments, preserve the user outcome,
and continue past a completed phase while a safe, authorized, outcome-advancing
next action remains. After three consecutive increments add no canonical
behavior and remove no reproduced direct blocker, replay the smallest canonical
example and re-scope instead of adding more process machinery.

Do not build parallel coordination identity systems in downstream repos.
Coordinated assignment and operator surfaces consume the canonical
claim/session model owned here.

Only these stop conditions are legitimate:

1. an irreversible action that affects shared state
2. a genuine architectural decision not already pre-made in the active plan
3. no safe, authorized, evidence-supported, goal-advancing next action remains
   after bounded investigation; persist a resumable handoff and return control
   instead of manufacturing work or passively polling

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
- `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md`
  - canonical portable pattern for overnight/continuous autonomous execution
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
python scripts/session_start.py --help
python scripts/session_heartbeat.py --help
python scripts/session_status.py --help
python scripts/session_finish.py --help
python scripts/session_close.py --help

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
6. Use session lifecycle commands for coordinated or release work; a reversible
   single-writer development task does not need a session/claim lifecycle.
7. Use `session-close` or `make worktree-remove` for claimed lane cleanup; do
   not manually split claim release from worktree removal.

## Notes

- This repo is the framework source of truth; installed governed repos are
  consumers of generated/copied surfaces from here.
- `AGENTS.md` is a generated mirror, not a second authority.
- Historical sprint notes under `docs/ops/` are evidence artifacts, not the
  active planning queue.

## Principles

- Governance is discriminating: checks report deterministic facts, and block
  only when the candidate can violate the protected contract and the selected
  execution mode requires blocking.
- Every repo gets the smallest stage-appropriate contract surface; development
  does not inherit coordinated or release controls solely because the framework
  can install them.
- Install is idempotent: running it twice leaves the repo in the same state
- Source truth is in this repo; installed repos are consumers of generated artifacts

## Workflow

1. Make changes to framework source
2. Run `python scripts/self_test.py` to validate
3. Run `python scripts/install_governed_repo.py --repo-root <consumer> --write` to propagate

## References

- `PLANNING_OPERATING_MODEL.md` — canonical methodology
- `docs/plans/CLAUDE.md` — implementation plan queue
- `ROADMAP.md` — forward queue and phase map
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — worktree and lane lifecycle
