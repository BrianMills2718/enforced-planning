---
schema_version: "1.0"
artifact_type: design_plan
id: claim-refusal-resolution
plan_id: claim-refusal-resolution
status: proposed
planning_path: requested
method_conformance_receipt: docs/plans/claim-refusal-resolution.receipt.json
trace_review_criteria:
  - criterion_id: outcome
    expected_outcome: pass
goal:
  outcome: "validate_claim_for_creation refuses broad-scope claims with one line per issue naming the triggering write path and the sanctioned resolution, instead of a bare code"
  canonical_example: "check_coordination_claims.py --claim ... --write-path newfile.json in a repo without that file prints: broad_scope_ambiguous: top-level path 'newfile.json' does not exist; ... Resolve: ... new_files ...; exit 1."
  forbidden_substitutes: "claiming success from a check's last line or exit status alone; a change outside the listed files; a commit without the saved check output"
  boundaries: "only these files: enforced_planning/coordination_claims.py, tests/test_check_coordination_claims.py; no irreversible action and no spend; Brian's request as quoted is the scope"
  done_when: "pytest tests/test_check_coordination_claims.py -k broad: the new test asserts the refusal for a missing top-level file starts with broad_scope_ambiguous, quotes 'llm_client_fallbacks.json' and names new_files and Resolve:, and the refusal for write path docs names 'docs' (existing_top_level_directory) and the --broad-scope-mode bounded / --broad-scope-reason flags; existing tests still match the bare codes; make check passes. The check's full output on the parent commit and on the change commit is committed as docs/plans/claim-refusal-resolution.check.txt, and the commit is tagged [Goal claim-refusal-resolution] with an Asked: line quoting the request."
  do_not_gate_on: "Brian's review of the plan page; work outside the listed files"
---

# Broad-scope claim refusals name the triggering path and the sanctioned resolution

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

**Request (verbatim):** Feedback loop (fix owner run for Brian) 2026-10-11, AES issue #407: "Add conformance checks that run each documented claim path through downstream enforcement and require every refusal to identify the triggering input and sanctioned resolution."

**Desired result:** validate_claim_for_creation refuses broad-scope claims with one line per issue naming the triggering write path and the sanctioned resolution, instead of a bare code.

**Stable example:** check_coordination_claims.py --claim ... --write-path newfile.json in a repo without that file prints: broad_scope_ambiguous: top-level path 'newfile.json' does not exist; ... Resolve: ... new_files ...; exit 1.

## Authority and non-goals

**Authority:** Brian asked for this change in his own repository; one agent makes it.

**Non-goals:** nothing outside the files listed under Vertical and reset. No irreversible action and no spend.

## Requirements

| Id | Requirement | Source | Check | Status |
| --- | --- | --- | --- | --- |
| R1 | validate_claim_for_creation refuses broad-scope claims with one line per issue naming the triggering write path and the sanctioned resolution, instead of a bare code. | asked: Feedback loop (fix owner run for Brian) 2026-10-11, AES issue #407: "Add conformance checks that run each documented claim path through downstream enforcement and require every refusal to identify the triggering input and sanctioned resolution." | the success check under Success and disproof, its output saved as `docs/plans/claim-refusal-resolution.check.txt` | planned, not yet run |
| R2 | existing callers that test membership of bare issue codes keep working | stated with the request | _broad_scope_contract_issues still returns bare codes; full pytest of tests/test_check_coordination_claims.py passes | planned, not yet run |

Requirements the change's own claims imply are listed above as R2 onward.

## Success and disproof

**Success evidence:** pytest tests/test_check_coordination_claims.py -k broad: the new test asserts the refusal for a missing top-level file starts with broad_scope_ambiguous, quotes 'llm_client_fallbacks.json' and names new_files and Resolve:, and the refusal for write path docs names 'docs' (existing_top_level_directory) and the --broad-scope-mode bounded / --broad-scope-reason flags; existing tests still match the bare codes; make check passes.

**Trace review:** two runs of the success check above are judged from their full output: one on the parent commit before the change (the disproof run: it must show the defect or the check failing, which proves the check can fail) and one on the commit that makes the change (the success run); no model, agent or LLM pipeline runs under this plan. Where the trace lives: the check's complete output, with the exact command and its exit status, is saved as `docs/plans/claim-refusal-resolution.check.txt` and committed with the change. What must be seen in it beyond the final result: the command ran against the files listed under Vertical and reset at that commit, each check or test it reports appears by name with its result and none is skipped, and the exit status matches; for each model element listed under System model, the output shows what that line says. Both runs are saved in that one file, each headed by its commit: the disproof condition is judged from both (it holds if the success run still shows the defect, or if the before run already passes, meaning the check cannot detect it), and success from the success run.

**Disproof:** The CLI refusal for a missing top-level file still prints only broad_scope_ambiguous, or any existing test that matches the bare code fails.

## System model

**System model:** `docs/model/ODD.md`, a file in this repository describing this repository only (not a shared model). Reachable from the documentation entry point `wiki/index.md`, which links `docs/model/ODD.md`.

**Model elements this change adds, changes or relies on, and what the saved check output must show of each:**

- none -- docs/model/ODD.md scopes the model to the repository inventory and docstring wiki and states claims are out of scope; this change alters claim refusal text only, adds no stored field and no view

**Views, freshness and reconciliation:** the applicable view is the requirement-to-verification link in the Requirements table (each requirement and the check that shows it, the check being source-linked by its command); no other view applies because the change adds, changes or relies on no entity, process, record, event or view beyond the elements listed above. Freshness: the model's drift test (`tests/test_relationship_context.py`, `tests/test_docstring_wiki.py`) runs inside the success check and its output is in the saved check file. If an element above is added, removed or renamed, the model, its view coverage and the saved check output are reconciled in the same commit, and otherwise the model needs no update because the elements keep their meaning.

## Capability reuse

Checked against the capability catalogue in agentic-capability-architecture-canonical (`reuse_candidates.yml` and `capability_registry.yml`):

- No catalogue entry fits, because this changes the wording of an existing claim-validation refusal rather than adding a capability
- What the work needs that no entry provides: edits to this repository's own files (`enforced_planning/coordination_claims.py`, `tests/test_check_coordination_claims.py`); catalogue entries are cross-project capabilities, and none edits a repository's own source.

## Uncertainties

Material uncertainties. This one is the complete set; it is material because a file outside the list would
make the change exceed this plan's scope.

| Material uncertainty | Owner or resolving evidence |
| --- | --- |
| Whether the change needs files beyond the list below; if so it is out of scope for this plan | Resolved before editing: git diff --stat in the worktree: 2 files (enforced_planning/coordination_claims.py, tests/test_check_coordination_claims.py), 82 insertions, 4 deletions |

## Vertical and reset

One vertical over these files (and the saved check output, `docs/plans/claim-refusal-resolution.check.txt`):

- `enforced_planning/coordination_claims.py`
- `tests/test_check_coordination_claims.py`

The vertical delivers: validate_claim_for_creation refuses broad-scope claims with one line per issue naming the triggering write path and the sanctioned resolution, instead of a bare code. It is done when this holds: pytest tests/test_check_coordination_claims.py -k broad: the new test asserts the refusal for a missing top-level file starts with broad_scope_ambiguous, quotes 'llm_client_fallbacks.json' and names new_files and Resolve:, and the refusal for write path docs names 'docs' (existing_top_level_directory) and the --broad-scope-mode bounded / --broad-scope-reason flags; existing tests still match the bare codes; make check passes.

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

