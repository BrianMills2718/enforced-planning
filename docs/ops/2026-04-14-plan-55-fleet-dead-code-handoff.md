# Plan #55 Fleet Dead-Code Campaign Handoff

Date: 2026-04-14
Plan: `docs/plans/55_fleet-dead-code-completion.md`
Campaign branch: `plan-55-fleet-dead-code-completion`
Campaign commit at handoff start: `aee9772`

## Purpose

This handoff captures the unfinished work across the repos that still matter to the
reviewed dead-code rollout. It is the durable resume surface for the current state
of Wave 2A, the blocked lanes that should not be forced, and the deferred repos
that must not be silently reopened.

The key operational distinction is:

- some repos are already complete on pushed feature branches and only need PR/merge
- some repos are clean and ready for the next dead-code lane
- some repos are blocked on baseline branch state and need a separate reconciliation lane before dead-code work starts
- some repos are explicitly deferred by prior decision and should stay deferred until reopened deliberately

## Current Truth

| Repo | Campaign Status | Ground Truth | Next Action |
|------|-----------------|--------------|-------------|
| `enforced-planning` | in progress | clean pushed tracker branch `plan-55-fleet-dead-code-completion` at `aee9772`; root checkout `main` is dirty and should not be used | continue campaign from the worktree branch only |
| `grounded-research` | complete | pushed branch `plan-55-grounded-research-dead-code` at `9471041` | open PR / merge when ready |
| `epistemic-contracts` | complete | pushed branch `plan-55-epistemic-contracts-dead-code` at `1f2cfe7` | open PR / merge when ready |
| `orgchart` | blocked-on-baseline | only governed checkout is `20251008_mvp`, ahead of origin by 3 local commits | baseline reconciliation lane first |
| `qualitative_coding` | not started | `main...origin/main [ahead 4]` | treat as baseline-reconciliation candidate before dead-code |
| `ufotrust` | ready | `main...origin/main`, clean | next low-friction dead-code lane |
| `utils` | ready | `master...origin/master`, clean | next low-friction dead-code lane after `ufotrust` |
| `twitter_explorer` | not started | `trip-backup-20260224_152221...origin/trip-backup-20260224_152221 [ahead 4]` | baseline reconciliation before dead-code |
| `onto-canon6` | not started | `main...origin/main [ahead 4]` | baseline reconciliation before dead-code |
| `agent_memory` | not started | `master...origin/master` with modified `AGENTS.md` | clean or isolate local dirt before dead-code |
| `ecosystem-ops` | not started | `main...origin/main [ahead 3]` with large modified/untracked assessment set | separate baseline cleanup lane first |
| `phd_thesis_work` | blocked-on-baseline | `master...origin/master [ahead 4]` plus untracked `Makefile` and `docs/plans/` | baseline/governance repair before dead-code |
| `wargame` | blocked-on-baseline | `master` with untracked `Makefile` and `docs/plans/*` | baseline/governance repair before dead-code |
| `research_v3` | deferred | explicit defer on `followthemoney` bootstrap blocker | do not reopen in this campaign without a dedicated decision lane |
| `llm_client` | deferred | explicit defer on broad lint debt; current checkout is unrelated feature branch `fix/instructor-retry-unwrapping` ahead 2 | do not reopen in this campaign without a dedicated baseline lane |

## Repo Details

### `enforced-planning`

- Active campaign branch: `plan-55-fleet-dead-code-completion`
- Active pushed commit before this handoff doc: `aee9772`
- Root checkout state is not safe for direct work:
  - `main...origin/main [ahead 2]`
  - modified: `docs/ops/ECOSYSTEM_STATUS.md`
  - untracked: `FRICTION.md`
- Use only the worktree branch at:
  - `/home/brian/projects/enforced-planning_worktrees/plan-55-fleet-dead-code-completion`
- Plan #55 already records:
  - `grounded-research` complete
  - `epistemic-contracts` complete
  - `orgchart` blocked-on-baseline
- Immediate unfinished work in this repo:
  - land this handoff doc
  - keep Plan #55 updated as each repo closes or is blocked
  - continue Wave 2A in a truthful order based on baseline cleanliness, not the original low-friction assumption

### `grounded-research`

- Dead-code lane is complete on pushed branch `plan-55-grounded-research-dead-code` at `9471041`.
- Worktree path:
  - `/home/brian/projects/grounded-research_worktrees/plan-55-grounded-research-dead-code`
- What was finished:
  - reviewed dead-code contract installed
  - repo-local dead findings removed in `models.py`, `shared_export.py`, `tyler_v1_adapters.py`, and `verify.py`
  - `dead_code_audit.json` created with only reviewed `framework_sync` retained findings
  - repo environment made truthful enough for verification by declaring `httpx`, `beautifulsoup4`, and `pytest-asyncio`
  - mypy override added for shared ecosystem packages used as external imports
- What remains unfinished:
  - PR / merge only
- Important caution:
  - root checkout still shows `dead_code_enabled=false` because the reviewed dead-code contract is only on the pushed feature branch, not merged to `main`

### `epistemic-contracts`

- Dead-code lane is complete on pushed branch `plan-55-epistemic-contracts-dead-code` at `1f2cfe7`.
- Worktree path:
  - `/home/brian/projects/epistemic-contracts_worktrees/plan-55-epistemic-contracts-dead-code`
- What was finished:
  - reviewed dead-code contract installed
  - repo-local dead-code targets added
  - `vulture` added to dev extras
  - `dead_code_audit.json` created
  - all 23 findings classified as inherited `framework_sync`
- What remains unfinished:
  - PR / merge only
- Important caution:
  - same as `grounded-research`: root checkout does not reflect the pushed feature branch until merged

### `orgchart`

- Current checkout: `20251008_mvp...origin/20251008_mvp [ahead 3]`
- Last visible local commits:
  - `19c5695` `[Plan #26] Add governance sections + install governed-repo contract (governed)`
  - `a8459f8` `[Governance] Add standard Makefile with help, test, status, cost, errors targets`
  - `ed5ff58` `[Trivial] Add subtree instruction routers for orgchart`
- Why this is blocked:
  - there is no clean default-branch governed baseline to start from
  - creating a Plan #55 dead-code branch from the current tip would publish unrelated local history
  - creating a branch from `origin/master` would skip the only known governed baseline
- Required unfinished work:
  - dedicated reconciliation lane to decide whether the three local commits are now the intended base or need their own publish/merge path first
  - only after that decision should a dead-code lane be started

### `qualitative_coding`

- Current checkout: `main...origin/main [ahead 4]`
- Dead-code contract state in root checkout:
  - `dead_code_enabled=false`
  - no explicit dead-code targets
  - no `publish-check`
- Why this is not the next safe lane despite the original Wave 2A order:
  - local `main` already contains unpublished commits
  - starting a dead-code branch from that tip may absorb unrelated history
- Required unfinished work:
  - inspect the 4 local commits and decide whether they are intended baseline or unrelated local drift
  - if they are intended baseline, publish or branch them explicitly first
  - if they are unrelated, start from the remote default instead

### `ufotrust`

- Current checkout: `main...origin/main`
- Repo appears clean and is the best next execution candidate.
- Current root checkout state:
  - dead-code disabled
  - no explicit dead-code targets
  - no `publish-check`
- Recommended unfinished work:
  1. create claimed worktree branch `plan-55-ufotrust-dead-code`
  2. install governed dead-code contract
  3. enable dead-code in `meta-process.yaml`
  4. add dead-code targets to `Makefile`
  5. add `vulture` to dev extras
  6. bootstrap `.venv`
  7. run `make dead-code-audit`
  8. classify repo-local findings vs inherited `framework_sync`
  9. verify `make publish-check`
  10. commit and push

### `utils`

- Current checkout: `master...origin/master`
- Repo appears clean and is the second-best next execution candidate after `ufotrust`.
- Expected unfinished work is the same rollout pattern as `ufotrust`.

### `twitter_explorer`

- Current checkout: `trip-backup-20260224_152221...origin/trip-backup-20260224_152221 [ahead 4]`
- Dead-code disabled, no dead-code targets, no `publish-check`
- Unfinished work before any dead-code lane:
  - determine whether `trip-backup-20260224_152221` is the real active baseline or a local-only holding branch
  - avoid running the campaign on top of those 4 unpublished commits without explicit intent

### `onto-canon6`

- Current checkout: `main...origin/main [ahead 4]`
- Dead-code disabled, no dead-code targets, no `publish-check`
- Unfinished work before any dead-code lane:
  - reconcile the local `main` divergence first
  - only then start a worktree branch for dead-code

### `agent_memory`

- Current checkout: `master...origin/master`
- Dirty file:
  - `AGENTS.md`
- Dead-code disabled, no dead-code targets, no `publish-check`
- Unfinished work before any dead-code lane:
  - determine whether the `AGENTS.md` modification is intentional local work or drift
  - either commit/branch it or clear it before starting dead-code

### `ecosystem-ops`

- Current checkout: `main...origin/main [ahead 3]`
- Dirty and high-noise:
  - modified tracked files including `tool_registry.json`
  - large untracked `assessments/` set
- Dead-code disabled, no dead-code targets, no `publish-check`
- This is not ready for dead-code execution.
- Required unfinished work:
  - separate baseline cleanup / assessment-ingest lane
  - dead-code only after the working tree and branch state are isolated

### `phd_thesis_work`

- Current checkout: `master...origin/master [ahead 4]`
- Untracked governance surfaces already exist:
  - `Makefile`
  - `docs/plans/`
- Dead-code disabled, no dead-code targets, no `publish-check`
- This matches the original Plan #55 expectation: governance/baseline repair first, dead-code second.

### `wargame`

- Current checkout: `master`
- Untracked governance surfaces:
  - `Makefile`
  - `docs/plans/CLAUDE.md`
  - `docs/plans/TEMPLATE.md`
- Dead-code disabled, no dead-code targets, no `publish-check`
- Same handling as `phd_thesis_work`: baseline/governance repair lane before dead-code.

### `research_v3`

- Explicitly deferred.
- Do not reopen in Plan #55 without first reopening the dependency decision recorded on the `plan-53-research-v3-followthemoney-defer` lane.
- The meaningful blocker is unchanged:
  - deterministic `followthemoney` bootstrap is not resolved truthfully enough for stricter repo gating

### `llm_client`

- Explicitly deferred.
- Current root checkout is unrelated feature work:
  - `fix/instructor-retry-unwrapping...origin/fix/instructor-retry-unwrapping [ahead 2]`
- The meaningful blocker is unchanged:
  - broad existing lint debt prevents truthful graduation or reopening inside this campaign
- Do not mix Plan #55 dead-code work with the current feature branch state.

## Recommended Resume Order

Use this order, which is stricter than the original Wave 2A ordering because it reflects the baseline drift discovered during execution:

1. `ufotrust`
2. `utils`
3. `qualitative_coding` baseline reconciliation
4. `orgchart` baseline reconciliation
5. reassess whether any Wave 2B repo is cleaner than the remaining Wave 2A blocked lanes

## Commands That Were Working

These were the reliable commands on the successful lanes:

```bash
python /home/brian/projects/enforced-planning_worktrees/plan-55-fleet-dead-code-completion/scripts/install_governed_repo.py --repo-root . --write --json
python -m venv .venv && .venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install -e '.[dev]'
make dead-code-audit
make dead-code
make dead-code-validate
make publish-check
git push -u origin <branch>
```

## Do Not Lose

- `grounded-research` complete branch: `plan-55-grounded-research-dead-code` at `9471041`
- `epistemic-contracts` complete branch: `plan-55-epistemic-contracts-dead-code` at `1f2cfe7`
- `enforced-planning` tracker branch: `plan-55-fleet-dead-code-completion` at `aee9772` before this handoff doc
- `orgchart` is intentionally blocked, not forgotten
- `research_v3` and `llm_client` are intentionally deferred, not available for silent scope creep
