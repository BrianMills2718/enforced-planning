---
schema_version: "1.0"
artifact_type: design_plan
id: docstring-wiki-classification-filter
plan_id: docstring-wiki-classification-filter
status: proposed
planning_path: requested
method_conformance_receipt: docs/plans/docstring-wiki-classification-filter.receipt.json
trace_review_criteria:
  - criterion_id: outcome
    expected_outcome: pass
goal:
  outcome: "docstring_wiki accepts --classification (repeatable) and --links, so a repository can generate a catalog of only its documents, each heading a relative link, with default output unchanged"
  canonical_example: "In DIGIMON, --output wiki/catalog.md --classification documentation --links lists docs/GLOSSARY.md as ### [docs/GLOSSARY.md](../docs/GLOSSARY.md) with its front-matter description."
  forbidden_substitutes: "claiming success from a check's last line or exit status alone; a change outside the listed files; a commit without the saved check output"
  boundaries: "only these files: enforced_planning/docstring_wiki.py, tests/test_docstring_wiki.py, docs/model/ODD.md; no irreversible action and no spend; Brian's request as quoted is the scope"
  done_when: "tests/test_docstring_wiki.py passes including the new catalog test, and default output on DIGIMON is byte-identical to main (2,035,575 bytes, cmp equal). The check's full output is committed as docs/plans/docstring-wiki-classification-filter.check.txt, and the commit is tagged [Goal docstring-wiki-classification-filter] with an Asked: line quoting the request."
  do_not_gate_on: "Brian's review of the plan page; work outside the listed files"
---

# Docstring wiki can publish a linked documentation-only catalog

## When a run fails or surprises us

This procedure is separate from, and distinct from, the anticipated failure modes the new test already covers (a non-documentation artifact leaking into the catalog, a wrong relative link, `--check` ignoring the options). An unresolved diagnosis permits investigation only and cannot authorize a causal repair.

Preserve the failed check and its execution trace id. Before selecting a fix,
read the complete inputs, prompts, tool arguments/results, intermediate stages
and final output, including the full check command/output and the changed files.
Cite the observed divergence and classify evidence absent, returned but unused
or contradicted, invalid expectation, or unresolved. Investigate an unresolved
cause before authorizing a causal repair. Bind the targeted repair to a new
traced verification run; retain the failed original. Review every failing or
surprising item and a sample of passes. A complete review is distinct from a
passing run. Criterion `outcome` covers the entire requested success check.

## Prior art and ownership

| Candidate found (searched 2026-10-10) | Disposition |
|---|---|
| Existing owner: enforced-planning `docstring_wiki.py` (renders every tracked artifact from source-local summaries) | **extend**: add an opt-in kind filter and linked headings; default output unchanged |
| Internal: `relationship_context.inventory_repository` classification (`source`, `test`, `documentation`, `archive`, ...) | **reuse** as the filter key; no second classifier |
| Internal: DIGIMON hand-built `docs/archive/*.md` indexes (Plan #221) | **bounded exception**: they record removed files with restore commits, which the generator cannot see; they are not a catalog of live documents |
| External: Sphinx `autosummary`, MkDocs `nav`/awesome-pages, pdoc | **bounded exception**: each renders a whole site from its own config; this plan needs only a filter on the generator these repos already run and check, so none is adopted; revisit if a repository wants a browsable docs site |

**Parallel-implementation check:** after DIGIMON adopts it, `rg -n "description:" -l scripts/ Makefile` in DIGIMON must show the catalog produced only by `enforced_planning.docstring_wiki` (a Makefile target), with no DIGIMON script that renders `wiki/catalog.md` itself.

## Irreversible actions and spend

No irreversible action or spend is proposed. Boundary: the change is a code commit on enforced-planning merged by squash; authorizer: Brian's standing merge rule for his own repositories (workspace AGENTS.md, 2026-10-03); containment: `git revert` of the squash commit restores the previous generator, and default output is byte-identical so no committed wiki in any repository goes stale. No money is spent and nothing is published or deleted.

## Actor and result

**Actor:** Brian, who asked for this change.

**Request (verbatim):** Brian 2026-10-10 "every document should have a kind of doc string explaining what it is for that projects into the wiki"

**Desired result:** docstring_wiki accepts --classification (repeatable) and --links, so a repository can generate a catalog of only its documents, each heading a relative link, with default output unchanged.

**Stable example:** In DIGIMON, --output wiki/catalog.md --classification documentation --links lists docs/GLOSSARY.md as ### [docs/GLOSSARY.md](../docs/GLOSSARY.md) with its front-matter description.

## Authority and non-goals

**Authority:** Brian asked for this change in his own repository; one agent makes it.

**Non-goals:** nothing outside the files listed under Vertical and reset. No irreversible action and no spend.

## Requirements

| Id | Requirement | Source | Check | Status |
| --- | --- | --- | --- | --- |
| R1 | docstring_wiki accepts --classification (repeatable) and --links, so a repository can generate a catalog of only its documents, each heading a relative link, with default output unchanged. | asked: Brian 2026-10-10 "every document should have a kind of doc string explaining what it is for that projects into the wiki" | the success check under Success and disproof, its output saved as `docs/plans/docstring-wiki-classification-filter.check.txt` | planned, not yet run |

Requirements the change's own claims imply: none beyond R1; the change presents nothing as following a standard, schema or contract.

## Success and disproof

**Success evidence (direct checks of the claimed property):** `test_documentation_catalog_lists_only_docs_as_relative_links` asserts that the filtered catalog contains `### [docs/decision.md](../docs/decision.md)` with that document's summary, and does not contain `src/service.py` or `tests/test_service.py` (the fixture's source and test artifacts), so a non-documentation artifact in the catalog fails it; it asserts `--check` passes with the same options and fails without them. Separately, `cmp` of the default (unfiltered) render on the DIGIMON plan-221-docs worktree from `main` and from this branch shows byte equality, which directly establishes the default output is unchanged. In summary: tests/test_docstring_wiki.py passes including the new catalog test, and default output on DIGIMON is byte-identical to main (2,035,575 bytes, cmp equal).

**Trace review:** the run whose full trace is judged is the success check above, run once on the commit that makes the change; no model, agent or LLM pipeline runs under this plan. Where the trace lives: the check's complete output, with the exact command and its exit status, is saved as `docs/plans/docstring-wiki-classification-filter.check.txt` and committed with the change. What must be seen in it beyond the final result: the command ran against the files listed under Vertical and reset at that commit, each check or test it reports appears by name with its result and none is skipped, and the exit status matches; for each model element listed under System model, the output shows what that line says. Success and disproof are both judged from that file.

**Disproof:** Default output differs from main on any repository, or a filtered catalog lists a non-documentation artifact.

## System model

**System model:** [docs/model/ODD.md](../model/ODD.md), reachable from `wiki/index.md` -> `README.md` (Canonical Docs). Applicable source-linked views: VIEW-DOCSTRING-WIKI only; the model is scoped to the inventory and docstring wiki, so claims, sessions and hooks are omitted because this change does not touch them. Freshness: the PROC-DOCSTRING-WIKI row is updated in this same change to name `--classification` and `--links`, and the saved check output reconciles the model rows with the test that verifies them (`tests/test_docstring_wiki.py`, listed as each row's verification).

**Model elements this change adds, changes or relies on, and what the saved check output must show of each:**

- VIEW-DOCSTRING-WIKI changes: gains a documentation-only linked variant; the test output must show the filtered catalog contains docs/decision.md as a relative link and no src/ or tests/ entries
- PROC-DOCSTRING-WIKI changes: --check compares byte-for-byte with the same options; the test must show --check passes with the options and fails without them

## Capability reuse

Checked against the capability catalogue in agentic-capability-architecture-canonical (`reuse_candidates.yml` and `capability_registry.yml`):

No catalogue entry fits, because what this work needs is a selection filter and link format inside the enforced-planning `docstring_wiki` renderer, and neither `reuse_candidates.yml` (no docstring, wiki-generation or repository-catalog entry) nor `capability_registry.yml` provides a repository-wiki generator. The work extends the existing module and adds no new catalogue capability; its first consumer is DIGIMON's `wiki/catalog.md` under DIGIMON Plan #221.

## Uncertainties

| Uncertainty | Owner or resolving evidence |
| --- | --- |
| Whether the change needs files beyond the list below; if so it is out of scope for this plan | Resolved before editing: git diff --stat: enforced_planning/docstring_wiki.py, tests/test_docstring_wiki.py, docs/model/ODD.md |

## Vertical and reset

One vertical over these files (and the saved check output, `docs/plans/docstring-wiki-classification-filter.check.txt`):

- `enforced_planning/docstring_wiki.py`
- `tests/test_docstring_wiki.py`
- `docs/model/ODD.md`

The vertical delivers: docstring_wiki accepts --classification (repeatable) and --links, so a repository can generate a catalog of only its documents, each heading a relative link, with default output unchanged. It is done when this holds: tests/test_docstring_wiki.py passes including the new catalog test, and default output on DIGIMON is byte-identical to main (2,035,575 bytes, cmp equal).

Make the change, run the success check, commit. Reset: `git revert` of the commit. Not pursued: anything outside these files.

## Activation facts

Shared mechanism: yes, `docstring_wiki` is run by several repositories, so the change is opt-in and default output is checked byte-identical. No comparison, no LLM at the centre, no irreversible action or spend, no external standard claimed, not an AES-governed target change.
