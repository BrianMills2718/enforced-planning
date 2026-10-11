---
schema_version: "1.0"
artifact_type: design_plan
id: lane-refusal-continuation
plan_id: lane-refusal-continuation
status: proposed
planning_path: requested
method_conformance_receipt: docs/plans/lane-refusal-continuation.receipt.json
trace_review_criteria:
  - criterion_id: outcome
    expected_outcome: pass
goal:
  outcome: "The root-lane and existing-tracker refusals from claim bootstrap print the exact make session-close command for each blocking lane and the SESSION_ALLOW_PARALLEL / different-BRANCH route, so an agent can continue without trial and error"
  canonical_example: "A session holding root lane agentic-engineering-system-canonical:aes-learning-loop-s1 that runs make maintenance-worktree in agent-skills gets a refusal containing 'make -C <that repo> session-close BRANCH=aes-learning-loop-s1' and 'SESSION_ALLOW_PARALLEL=1'."
  forbidden_substitutes: "claiming success from a check's last line or exit status alone; a change outside the listed files; a commit without the saved check output"
  boundaries: "only these files: enforced_planning/claim_bootstrap.py, tests/test_claim_bootstrap.py, wiki/index.md; no irreversible action and no spend; Brian's request as quoted is the scope"
  done_when: "(1) New tests in tests/test_claim_bootstrap.py assert that the zero-roots refusal text contains the blocking lane's session-close command with that lane's repo_root and branch and the SESSION_ALLOW_PARALLEL route, and that the existing-tracker refusal names session-close for that branch and the different-BRANCH route; existing refusal tests (match 'zero existing claim roots') still pass. (2) Runnability, checked live: while this session holds the lane-refusal-continuation root lane, running the patched bootstrap for a second root lane without SESSION_ALLOW_PARALLEL prints a refusal whose session-close command is then the exact command used to close this lane after merge, and that command exits 0 and removes the worktree, branch and claim (check_coordination_claims --check shows no active claims). The check's full output on the parent commit and on the change commit is committed as docs/plans/lane-refusal-continuation.check.txt, and the commit is tagged [Goal lane-refusal-continuation] with an Asked: line quoting the request."
  do_not_gate_on: "Brian's review of the plan page; work outside the listed files"
---

# Lane-claim refusals name the exact continuation command

## When a run fails or surprises us

This procedure is separate from the anticipated failure named in the disproof
under Success and disproof: it applies to any run that fails or surprises us.
Preserve the failed check and its execution trace id. Before selecting a fix,
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

**Request (verbatim):** Feedback loop licence 2026-10-08 (AES canonical issue #392, problem agent-feedback-log#49): "Emit the exact continuation command or workaround label in every lane-claim refusal so agents follow a known recovery path instead of discovering it empirically."

**Desired result:** The root-lane and existing-tracker refusals from claim bootstrap print the exact make session-close command for each blocking lane and the SESSION_ALLOW_PARALLEL / different-BRANCH route, so an agent can continue without trial and error.

**Stable example:** A session holding root lane agentic-engineering-system-canonical:aes-learning-loop-s1 that runs make maintenance-worktree in agent-skills gets a refusal containing 'make -C <that repo> session-close BRANCH=aes-learning-loop-s1' and 'SESSION_ALLOW_PARALLEL=1'.

## Authority and non-goals

**Authority:** Brian asked for this change in his own repository; one agent makes it.

**Non-goals:** nothing outside the files listed under Vertical and reset. No irreversible action and no spend.

## Requirements

| Id | Requirement | Source | Check | Status |
| --- | --- | --- | --- | --- |
| R1 | The root-lane and existing-tracker refusals from claim bootstrap print the exact make session-close command for each blocking lane and the SESSION_ALLOW_PARALLEL / different-BRANCH route, so an agent can continue without trial and error. | asked: Feedback loop licence 2026-10-08 (AES canonical issue #392, problem agent-feedback-log#49): "Emit the exact continuation command or workaround label in every lane-claim refusal so agents follow a known recovery path instead of discovering it empirically." | the success check under Success and disproof, its output saved as `docs/plans/lane-refusal-continuation.check.txt` | planned, not yet run |

Requirements the change's own claims imply: none beyond R1; the change presents nothing as following a standard, schema or contract.

## Success and disproof

**Success evidence:** (1) New tests in tests/test_claim_bootstrap.py assert that the zero-roots refusal text contains the blocking lane's session-close command with that lane's repo_root and branch and the SESSION_ALLOW_PARALLEL route, and that the existing-tracker refusal names session-close for that branch and the different-BRANCH route; existing refusal tests (match 'zero existing claim roots') still pass. (2) Runnability, checked live: while this session holds the lane-refusal-continuation root lane, running the patched bootstrap for a second root lane without SESSION_ALLOW_PARALLEL prints a refusal whose session-close command is then the exact command used to close this lane after merge, and that command exits 0 and removes the worktree, branch and claim (check_coordination_claims --check shows no active claims).

**Trace review:** two runs of the success check above are judged from their full output: one on the parent commit before the change (the disproof run: it must show the defect or the check failing, which proves the check can fail) and one on the commit that makes the change (the success run); no model, agent or LLM pipeline runs under this plan. Where the trace lives: the check's complete output, with the exact command and its exit status, is saved as `docs/plans/lane-refusal-continuation.check.txt` and committed with the change. What must be seen in it beyond the final result: the command ran against the files listed under Vertical and reset at that commit, each check or test it reports appears by name with its result and none is skipped, and the exit status matches; for each model element listed under System model, the output shows what that line says. Both runs are saved in that one file, each headed by its commit: the disproof condition is judged from both (it holds if the success run still shows the defect, or if the before run already passes, meaning the check cannot detect it), and success from the success run.

**Disproof:** A refusal from either site that lacks a continuation command, a printed session-close command that fails when run for its lane, or any existing claim_bootstrap test failing.

## System model

**System model:** `docs/model/ODD.md`, a file in this repository describing this repository only (not a shared model). Reachable from the documentation entry point `wiki/index.md`, which links `docs/model/ODD.md`.

**Model elements this change adds, changes or relies on, and what the saved check output must show of each:**

- none -- changes refusal message text only; no stored state, schema or view changes

**Views, freshness and reconciliation:** the applicable view is the requirement-to-verification link in the Requirements table (each requirement and the check that shows it, the check being source-linked by its command); no other view applies because the change adds, changes or relies on no entity, process, record, event or view beyond the elements listed above. Freshness: the model's drift test (`tests/test_relationship_context.py`, `tests/test_docstring_wiki.py`) runs inside the success check and its output is in the saved check file. If an element above is added, removed or renamed, the model, its view coverage and the saved check output are reconciled in the same commit, and otherwise the model needs no update because the elements keep their meaning.

## Capability reuse

Checked against the capability catalogue in agentic-capability-architecture-canonical (`reuse_candidates.yml` and `capability_registry.yml`):

- No catalogue entry fits, because this edits the wording of existing claim-bootstrap refusals rather than reusing or adding a capability
- What the work needs that no entry provides: edits to this repository's own files (`enforced_planning/claim_bootstrap.py`, `tests/test_claim_bootstrap.py`, `wiki/index.md`); catalogue entries are cross-project capabilities, and none edits a repository's own source.

## Uncertainties

Material uncertainties. This one is the complete set; it is material because a file outside the list would
make the change exceed this plan's scope.

| Material uncertainty | Owner or resolving evidence |
| --- | --- |
| Whether the change needs files beyond the list below; if so it is out of scope for this plan | Resolved before editing: grep -n 'zero existing claim roots\|tracker already exists' enforced_planning/claim_bootstrap.py -> 3 refusal sites at lines 1579, 1969, 1996, all in this one file; wiki/index.md gains the system-model link |

## Vertical and reset

One vertical over these files (and the saved check output, `docs/plans/lane-refusal-continuation.check.txt`):

- `enforced_planning/claim_bootstrap.py`
- `tests/test_claim_bootstrap.py`
- `wiki/index.md`

The vertical delivers: The root-lane and existing-tracker refusals from claim bootstrap print the exact make session-close command for each blocking lane and the SESSION_ALLOW_PARALLEL / different-BRANCH route, so an agent can continue without trial and error. It is done when this holds: (1) New tests in tests/test_claim_bootstrap.py assert that the zero-roots refusal text contains the blocking lane's session-close command with that lane's repo_root and branch and the SESSION_ALLOW_PARALLEL route, and that the existing-tracker refusal names session-close for that branch and the different-BRANCH route; existing refusal tests (match 'zero existing claim roots') still pass. (2) Runnability, checked live: while this session holds the lane-refusal-continuation root lane, running the patched bootstrap for a second root lane without SESSION_ALLOW_PARALLEL prints a refusal whose session-close command is then the exact command used to close this lane after merge, and that command exits 0 and removes the worktree, branch and claim (check_coordination_claims --check shows no active claims).

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

