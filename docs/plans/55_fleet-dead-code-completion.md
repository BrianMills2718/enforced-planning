# Plan #55: Fleet Dead-Code Completion

**Status:** In Progress
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9"
**goal_ref:** "fleet-adoption"
**adrs_referenced:** ["ADR-0010"]
**Blocked By:** #53
**Blocks:** Phase 9 completion of reviewed dead-code governance across the remaining eligible repo fleet

---

## Gap

**Current:** Phase 9 already shipped the dead-code framework, the reviewed-audit contract, the publish-path enforcement layer, and the first governed consumer wave. `agentic_scaffolding` and `prompt_eval` now enforce `publish-check-extra := make check`; `research_v3` and `llm_client` are explicitly deferred on truthful blockers. `grounded-research` is now complete on branch `plan-55-grounded-research-dead-code` with the reviewed dead-code contract installed, repo-local findings cleaned, reviewed framework-sync audit entries frozen, and publish-check verified through push. The rest of the eligible fleet still has no closed outcome yet. Some repos do not yet have the reviewed dead-code contract rolled in, some are locally dirty before any worktree lane starts, and some already have partial governed surfaces without a reviewed audit.

**Target:** One explicit fleet-completion campaign that says:
- which remaining repos are in scope,
- which repos are already complete,
- which repos are deferred,
- which repos first need dead-code contract rollout versus audit-only work,
- the exact wave order for the remaining queue,
- and the entry/exit criteria for closing each repo.

**Why:** The next failure mode is not detector accuracy. It is ad hoc repo selection, repeated inventory work, and reopening already-made defer decisions. The campaign needs a fixed queue and a fixed completion contract.

---

## References Reviewed

- `docs/plans/52_coordination-publish-discipline-and-reviewed-dead-code-rollout.md` - first governed dead-code campaign contract
- `docs/plans/53_publish-check-extra-graduation-wave-1.md` - current truthful state for graduated and deferred repos
- `docs/plans/CLAUDE.md` - current plan index and status surface
- `ROADMAP.md` - Phase 9 framing
- `/home/brian/projects/research_v3/CLAUDE.md` - explicit `followthemoney` defer note for `research_v3`
- command inventory reviewed on 2026-04-12:
  - `git status --short --branch` across remaining candidate repos
  - `meta-process.yaml` + `Makefile` inspection for dead-code target/config presence across candidate repos
- Memory context: `agent-memory recall 'active decisions' --project enforced-planning` — 0 findings

---

## Research Basis For This Slice

No additional research beyond References Reviewed.

---

## Multi-Repo Coordination

| Repo | Files Modified | Merge Strategy |
|------|---------------|----------------|
| `enforced-planning` | `docs/plans/55_fleet-dead-code-completion.md`, `docs/plans/CLAUDE.md`, `ROADMAP.md` | Merge first |
| `grounded-research` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2A |
| `epistemic-contracts` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2A |
| `orgchart` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2A |
| `qualitative_coding` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2A |
| `ufotrust` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2A |
| `utils` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2A |
| `twitter_explorer` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2B |
| `onto-canon6` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2B |
| `agent_memory` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2B |
| `ecosystem-ops` | rollout/audit files (`Makefile`, `meta-process.yaml`, `dead_code_audit.json`, docs as needed) | Wave 2B |
| `phd_thesis_work` | governance-baseline repair plus rollout/audit files | Wave 2C |
| `wargame` | governance-baseline repair plus rollout/audit files | Wave 2C |
| `research_v3` | no dead-code execution in this campaign until blocker is reopened explicitly | Deferred |
| `llm_client` | no dead-code execution in this campaign until lint-debt blocker is reopened explicitly | Deferred |

**Coordination notes:** Every repo executes on a claimed worktree branch. Repos with pre-existing local dirt must not absorb that dirt into the dead-code lane. Either work from a clean worktree branch or record the repo as blocked on baseline cleanup first.

**Write-claim footprint:** this plan plus one repo-local branch per wave lane. Each repo’s dead-code work owns only its local rollout/audit surfaces and does not write across repos.

---

## Files Affected

- `docs/plans/55_fleet-dead-code-completion.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `ROADMAP.md` (modify)
- repo-local `Makefile`, `meta-process.yaml`, `dead_code_audit.json`, and governance docs in each in-scope repo as required by that repo’s actual baseline

---

## Plan

### Steps

1. Freeze the fleet scope and exclusions.
   - In scope: top-level repos with `meta-process.yaml` that are still missing a completed reviewed dead-code outcome.
   - Already complete for this campaign: `enforced-planning`, `agentic_scaffolding`, `prompt_eval`.
   - Explicitly deferred: `research_v3` (`followthemoney` bootstrap blocker) and `llm_client` (broad lint-debt blocker).
   - Out of scope: repos with no governed `meta-process.yaml` yet.
2. Run Wave 2A: low-friction repo rollout and audit.
   - `grounded-research`
   - `epistemic-contracts`
   - `orgchart`
   - `qualitative_coding`
   - `ufotrust`
   - `utils`
   For each repo: create claimed worktree branch, sync dead-code contract if missing, run `dead-code-audit`, classify findings, `dead-code-validate`, `publish-check`, commit, push, record outcome.
3. Run Wave 2B: higher-blast-radius or dirtier shared repos.
   - `twitter_explorer`
   - `onto-canon6`
   - `agent_memory`
   - `ecosystem-ops`
   Same repo contract as Wave 2A, but treat dirty primary checkouts and operational helper coupling as expected blockers to resolve before audit decisions.
4. Run Wave 2C: repos that first need baseline/governance repair.
   - `phd_thesis_work`
   - `wargame`
   These repos do not start with dead-code deletion. They first need the governed baseline truthful enough that dead-code review can be enforced and published safely.
5. Keep the explicit defer boundary intact.
   - `research_v3` remains on the shared publish gate until the user reopens the `followthemoney` decision in a dedicated lane.
   - `llm_client` remains outside this completion campaign until its lint baseline is addressed in a separate lane.
6. Close the fleet.
   - For every in-scope repo, end with exactly one of:
     - complete: reviewed dead-code contract installed and passing
     - deferred: explicit blocker recorded in the repo and the upstream tracker
     - blocked-on-baseline: specific prerequisite lane created before dead-code audit starts

### Execution Status

- `grounded-research`: complete on `plan-55-grounded-research-dead-code` (`9471041` pushed). Reviewed dead-code governance is installed and passing. Repo-local cleanup removed the dead findings in `models.py`, `shared_export.py`, `tyler_v1_adapters.py`, and `verify.py`. The lane also made the repo environment truthful enough for verification by declaring `httpx`, `beautifulsoup4`, and `pytest-asyncio`, and by teaching mypy to treat shared ecosystem packages (`llm_client`, `data_contracts`, `epistemic_contracts`, `open_web_retrieval`) as external imports.
- Wave 2A remaining queue: `epistemic-contracts`, `orgchart`, `qualitative_coding`, `ufotrust`, `utils`.

---

## Required Tests

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/check_markdown_links.py ROADMAP.md docs/plans/55_fleet-dead-code-completion.md docs/plans/CLAUDE.md` | Plan/doc surfaces remain valid |
| `python scripts/self_test.py --links --docs` | Shared doc/link validation stays green |
| `make dead-code` in each completed repo | Dead-code detector passes with reviewed dispositions |
| `make dead-code-validate` in each completed repo | Reviewed audit file is complete and valid |
| `make publish-check` in each completed repo | Repo passes the sanctioned publish gate before push |
| `git push` from each completed repo branch | Hook-enforced publication works end-to-end |

---

## Acceptance Criteria

- [ ] Plan #55 exists and names the remaining in-scope repos for dead-code completion
- [x] The plan states which repos are already complete and which are explicitly deferred
- [x] The plan defines the remaining execution waves and the repo order inside them
- [x] The plan states the per-repo exit states: complete, deferred, or blocked-on-baseline
- [x] `ROADMAP.md` Phase 9 includes the remaining fleet dead-code completion campaign
- [x] Required plan/doc validation passes

---

## Notes

- This campaign is not “run vulture everywhere.” The contract is: install or sync the reviewed dead-code surface, classify findings, validate them mechanically, and publish from a claimed branch.
- `publish-check-extra` graduation is a separate follow-on question. For the remaining fleet, the first objective is reviewed dead-code completion under the shared publish gate unless a repo already has a truthful green `make check`.
