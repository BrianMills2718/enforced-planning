# Plan #52: Coordination Publish Discipline And Reviewed Dead-Code Rollout

**Status:** Planned
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** Phase 9 dead-code campaign execution across governed repos

---

## Gap

**Current:** The coordination enforcement surface now exists in `enforced-planning` (`push-check`, `review-claim`, `raise-concern`), and a first wave of dead-code governance has already been rolled into `agentic_scaffolding`, `llm_client`, `research_v3`, and `prompt_eval`. But the rollout state is inconsistent: some repos are still ahead on shared default branches, the operator workflow is not yet frozen as a single campaign contract, and resuming dead-code execution now would continue from process debt rather than from a normalized lane model.

**Target:** `enforced-planning` owns one explicit Phase 9 rollout contract that says:
- work happens on claimed worktree branches, not on shared default branches
- `make push-check` is the required pre-publish gate
- cross-lane concerns use `review-claim` + `raise-concern`
- repos already ahead on default branches are reconciled before more rollout
- dead-code execution resumes repo-by-repo under the reviewed audit workflow

**Why:** The next failure mode is not dead-code detection accuracy. It is pushing more cleanup from inconsistent branch state, creating avoidable coordination ambiguity while trying to reduce code ambiguity.

---

## References Reviewed

- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — canonical worktree/claim/session model
- `ROADMAP.md` — Phase 9 fleet-adoption framing
- `docs/plans/CLAUDE.md` — current plan index
- `docs/plans/43_publish-lane-safety-and-dirty-primary-checkout-handling.md` — publish-lane predecessor
- `docs/plans/51_upgrade-automation-implementation-and-write-mode-rollout.md` — current Phase 9 rollout precedent
- `investigations/enforced-planning/2026-04-09-coordination-publish-discipline-and-dead-code-rollout.md` — current-state assessment for this slice
- Memory context: `agent-memory recall 'active decisions' --project enforced-planning` — 0 findings

---

## Research Basis For This Slice

No additional research beyond References Reviewed.

---

## Multi-Repo Coordination

| Repo | Files Modified | Merge Strategy |
|------|---------------|----------------|
| `enforced-planning` | plan/doc/tooling surfaces for rollout contract | Merge first |
| `llm_client` | reviewed dead-code execution under task branch | Merge after `enforced-planning` contract lands |
| `research_v3` | branch reconciliation + reviewed dead-code execution | Reconcile branch state before more cleanup |
| `prompt_eval` | branch reconciliation + reviewed dead-code execution | Reconcile branch state before more cleanup |
| `agentic_scaffolding` | fold pilot into governed campaign flow | Resume after contract is canonical |

**Coordination notes:** The framework repo defines the contract first. Consumer repos should not continue the dead-code wave until the publish-discipline workflow and repo order are explicit.

**Write-claim footprint:** `enforced-planning/docs/plans/52_coordination-publish-discipline-and-reviewed-dead-code-rollout.md`, `enforced-planning/docs/plans/CLAUDE.md`, `enforced-planning/ROADMAP.md`, and the future repo-local dead-code campaign branches.

---

## Files Affected

- `docs/plans/52_coordination-publish-discipline-and-reviewed-dead-code-rollout.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `ROADMAP.md` (modify)

---

## Plan

### Steps

1. Land the campaign contract in `enforced-planning`.
   - Create Plan #52.
   - Add the plan to `docs/plans/CLAUDE.md`.
   - Update `ROADMAP.md` Phase 9 so the branch-publish discipline + dead-code campaign is visible as current fleet adoption work.
2. Reconcile current process debt before more cleanup.
   - Identify repos ahead on shared default branches.
   - Move follow-on work to worktree branches for `enforced-planning`, `research_v3`, and `prompt_eval`.
   - Treat the existing local `main` commits as rollout debt to normalize, not as a precedent.
3. Resume dead-code execution under the reviewed workflow.
   - Repo order: `llm_client` first, then `research_v3`, then `prompt_eval`, then `agentic_scaffolding`.
   - For each repo: create claimed worktree branch, run reviewed dead-code workflow, classify findings, delete/integrate/retain with evidence, run `dead-code-validate`, then run `push-check` before publishing.
4. Record cross-lane concern handling as part of the campaign.
   - Use `review-claim` when one agent inspects another lane’s write surface.
   - Use `raise-concern` to route concerns to a PR comment when published, otherwise to the local inbox.
5. Close the loop on rollout state.
   - After each repo wave, update the plan tracker and campaign notes with branch state, findings disposition, and whether any dormant feature was preserved under a real `plan_ref`.

---

## Required Tests

- `python scripts/self_test.py --links --docs`
- `python scripts/check_markdown_links.py ROADMAP.md docs/plans/52_coordination-publish-discipline-and-reviewed-dead-code-rollout.md docs/plans/CLAUDE.md`

---

## Acceptance Criteria

- [ ] Plan #52 exists and defines the rollout order, publish discipline, and concern-routing rules
- [ ] `docs/plans/CLAUDE.md` includes Plan #52
- [ ] `ROADMAP.md` Phase 9 explicitly mentions the branch-publish discipline + reviewed dead-code campaign
- [ ] The plan states that repos ahead on shared default branches must be reconciled before more dead-code execution
- [ ] The plan states the repo order for the dead-code campaign
- [ ] Required doc/link validation passes

---

## Notes

- This plan intentionally treats branch reconciliation as part of the dead-code campaign, not as a separate cosmetic cleanup item.
- Desired-but-unfinished features remain planning artifacts until they are either integrated or explicitly retained under a live `plan_ref`.
