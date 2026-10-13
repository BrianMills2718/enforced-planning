---
schema_version: "1.0"
artifact_type: design_plan
id: resume-recovers-missing-tracker
plan_id: resume-recovers-missing-tracker
status: proposed
planning_path: requested
method_conformance_receipt: docs/plans/resume-recovers-missing-tracker.receipt.json
conflict_surfaces:
  - {kind: repository_path, repository: "BrianMills2718/enforced-planning", target: "enforced_planning/session_lifecycle.py", access: write}
  - {kind: repository_path, repository: "BrianMills2718/enforced-planning", target: "tests/test_session_lifecycle.py", access: write}
  - {kind: repository_path, repository: "BrianMills2718/enforced-planning", target: "docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md", access: write}
  - {kind: repository_path, repository: "BrianMills2718/enforced-planning", target: "wiki/index.md", access: write}
trace_review_criteria:
  - criterion_id: outcome
    expected_outcome: pass
goal:
  outcome: "resume_session lets another session take over a lane claim that has no session tracker by rebuilding the tracker from the claim, so such a lane can then be closed with session-close"
  canonical_example: "A claude-code claim for demo:cross-agent-lane with status session_ended, session_id claude-code:headless-run and tracker_path null is resumed by claude-code:successor-run; the claim then names successor-run and a tracker under sessions/demo/ whose claim.session_id is successor-run"
  forbidden_substitutes: "claiming success from a check's last line or exit status alone; a change outside the listed files; a commit without the saved check output"
  boundaries: "only these files: enforced_planning/session_lifecycle.py, tests/test_session_lifecycle.py, docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md, wiki/index.md; no irreversible action and no spend; Brian's request as quoted is the scope"
  done_when: "python3 -m pytest tests/test_session_lifecycle.py: the new test test_resume_session_rebuilds_a_tracker_the_claim_never_recorded asserts resume returns action resumed, the persisted claim's session_id is the successor and its tracker_path points at a tracker in the patched trackers dir whose claim session_id and branch match; the other 21 lifecycle tests assert existing resume and handoff behaviour is unchanged The check's full output on the parent commit and on the change commit is committed as docs/plans/resume-recovers-missing-tracker.check.txt, and the commit is tagged [Goal resume-recovers-missing-tracker] with an Asked: line quoting the request."
  do_not_gate_on: "Brian's review of the plan page; work outside the listed files"
---

# Cross-session resume rebuilds a tracker a lane claim never recorded

## When a run fails or surprises us

This procedure is separate from the anticipated failure named in the disproof
under Success and disproof: it applies to any run that fails or surprises us.
Preserve the failed run itself: keep its complete output (command, every
line, exit status) and its execution trace id, never overwritten by a rerun.
Before selecting a fix,
read the complete inputs, prompts, tool arguments/results, intermediate stages
and final output, including the full check command/output and the changed files.
Cite the observed divergence and classify evidence absent, returned but unused
or contradicted, invalid expectation, or unresolved. An unresolved diagnosis
cannot authorize a causal repair; it permits only further investigation. Bind the targeted repair to a new
traced verification run; retain the failed original. Review every failing or
surprising item and a sample of passes. A complete review is distinct from a
passing run. Criterion `outcome` covers the entire requested success check.

## Actor and result

**Actor:** Brian, who asked for this change.

**Request (verbatim):** Brian 2026-10-13 "cant we do somehting int he menatime" (while the weekly fix owner waits; this fixes AES#783 found in its run)

**Desired result:** resume_session lets another session take over a lane claim that has no session tracker by rebuilding the tracker from the claim, so such a lane can then be closed with session-close

**Stable example:** A claude-code claim for demo:cross-agent-lane with status session_ended, session_id claude-code:headless-run and tracker_path null is resumed by claude-code:successor-run; the claim then names successor-run and a tracker under sessions/demo/ whose claim.session_id is successor-run

## Authority and non-goals

**Authority:** Brian asked for this change in his own repository; one agent makes it.

**Non-goals:** nothing outside the files listed under Vertical and reset. No irreversible action and no spend.

## Requirements

| Id | Requirement | Source | Check | Status |
| --- | --- | --- | --- | --- |
| R1 | resume_session lets another session take over a lane claim that has no session tracker by rebuilding the tracker from the claim, so such a lane can then be closed with session-close | asked: Brian 2026-10-13 "cant we do somehting int he menatime" (while the weekly fix owner waits; this fixes AES#783 found in its run) | the success check under Success and disproof, its output saved as `docs/plans/resume-recovers-missing-tracker.check.txt` | planned, not yet run |

Requirements the change's own claims imply: none beyond R1; the change presents nothing as following a standard, schema or contract.

## Success and disproof

**Success evidence:** python3 -m pytest tests/test_session_lifecycle.py: the new test test_resume_session_rebuilds_a_tracker_the_claim_never_recorded asserts resume returns action resumed, the persisted claim's session_id is the successor and its tracker_path points at a tracker in the patched trackers dir whose claim session_id and branch match; the other 21 lifecycle tests assert existing resume and handoff behaviour is unchanged

**Trace review:** two runs of the success check above are judged from their full output: one on the parent commit before the change (the disproof run: it must show the defect or the check failing, which proves the check can fail) and one on the commit that makes the change (the success run); no model, agent or LLM pipeline runs under this plan. Where the trace lives: the check's complete output, with the exact command and its exit status, is saved as `docs/plans/resume-recovers-missing-tracker.check.txt` and committed with the change. What must be seen in it beyond the final result: the command ran against the files listed under Vertical and reset at that commit, each check or test it reports appears by name with its result and none is skipped, and the exit status matches; for each model element listed under System model, the output shows what that line says. Both runs are saved in that one file, each headed by its commit: the disproof condition is judged from both (it holds if the success run still shows the defect, or if the before run already passes, meaning the check cannot detect it), and success from the success run.

**Disproof:** on the parent commit the new test fails with 'cross-session resume requires one existing exact session tracker' (shown before the change), or after the change any lifecycle test fails or the persisted claim still has tracker_path null

## System model

**System model:** `docs/model/ODD.md`, a file in this repository describing this repository only (not a shared model). Reachable from the documentation entry point `wiki/index.md`, which links `docs/model/ODD.md`.

**Model elements this change adds, changes or relies on, and what the saved check output must show of each:**

- process session-resume (relied on and changed; not yet in docs/model/ODD.md, which lists sessions as out of scope): the saved check output must show the new resume test passing with action resumed
- record lane claim, fields session_id and tracker_path (changed): the saved check output must show the test asserting session_id becomes the successor and tracker_path is set
- record session tracker, fields claim.session_id and claim.branch (created when missing): the saved check output must show the test asserting the rebuilt tracker carries the successor session_id and branch lane

**Views, freshness and reconciliation:** the applicable view is the requirement-to-verification link in the Requirements table (each requirement and the check that shows it, the check being source-linked by its command); no other view applies because the change adds, changes or relies on no entity, process, record, event or view beyond the elements listed above. Freshness: the model's drift test (`tests/test_relationship_context.py`, `tests/test_docstring_wiki.py`) runs inside the success check and its output is in the saved check file. If an element above is added, removed or renamed, the model, its view coverage and the saved check output are reconciled in the same commit, and otherwise the model needs no update because the elements keep their meaning.

## Capability reuse

Checked against the capability catalogue in agentic-capability-architecture-canonical (`reuse_candidates.yml` and `capability_registry.yml`):

- No catalogue entry fits, because this repairs the existing session-resume lifecycle step rather than adding or reusing a capability
- What the work needs that no entry provides: edits to this repository's own files (`enforced_planning/session_lifecycle.py`, `tests/test_session_lifecycle.py`, `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`, `wiki/index.md`); catalogue entries are cross-project capabilities, and none edits a repository's own source.

## Uncertainties

Material uncertainties. This one is the complete set; it is material because a file outside the list would
make the change exceed this plan's scope.

| Material uncertainty | Owner or resolving evidence |
| --- | --- |
| Whether the change needs files beyond the list below; if so it is out of scope for this plan | Resolved before editing: git diff --stat shows enforced_planning/session_lifecycle.py and tests/test_session_lifecycle.py, plus the operator guide paragraph the doc-code coupling hook requires and the wiki/index.md link to this plan |

## Vertical and reset

One vertical over these files (and the saved check output, `docs/plans/resume-recovers-missing-tracker.check.txt`):

- `enforced_planning/session_lifecycle.py`
- `tests/test_session_lifecycle.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `wiki/index.md`

The vertical delivers: resume_session lets another session take over a lane claim that has no session tracker by rebuilding the tracker from the claim, so such a lane can then be closed with session-close It is done when this holds: python3 -m pytest tests/test_session_lifecycle.py: the new test test_resume_session_rebuilds_a_tracker_the_claim_never_recorded asserts resume returns action resumed, the persisted claim's session_id is the successor and its tracker_path points at a tracker in the patched trackers dir whose claim session_id and branch match; the other 21 lifecycle tests assert existing resume and handoff behaviour is unchanged

Make the change, run the success check before and after it, commit. Reset: `git revert` of the commit. Not pursued: anything outside these files. This plan adds no coordinated-work ceremony: no work-unit graph, no review or release contract, no claim beyond the repository's own rules.

## Activation facts

Each fact, with its value and why:

- `shared_mechanism`: false -- the change edits only the listed files and adds no contract, algorithm or mechanism other code uses.
- `empirical_comparison_proposed`: false -- no alternatives are compared; the success check verifies the one change.
- `llm_central`: false -- the change makes no model call.
- `irreversible_or_spend_action`: false -- the change is reverted by `git revert` and spends nothing.
- `claims_external_standard`: false -- the work claims no external standard, schema or contract.
- `aes_governed_target`: false -- this repository has no `.aes/target.yaml` (checked by quick-adopt).
- `durable_documents_declared`: false -- `.agentic/repo.yaml` declares no `durable_documents` (checked by quick-adopt).
