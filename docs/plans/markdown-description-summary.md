---
schema_version: "1.0"
artifact_type: design_plan
id: markdown-description-summary
status: proposed
method_conformance_receipt: docs/plans/markdown-description-summary.receipt.json
trace_review_criteria:
  - criterion_id: outcome
    expected_outcome: pass
goal:
  outcome: "When a Markdown document carries its own front-matter description line, the repository inventory and docstring_wiki report that line as the document's summary, so the generated wiki shows what the document's author wrote where they edit it"
  canonical_example: "docs/described.md has 'description: Why plans archive after completion.' and a '## Decision' section; inventory_repository reports summary 'Why plans archive after completion.' with summary_source 'markdown:front-matter:description'; docs/typed.md with only title/type front matter reports its first body paragraph, never 'title: Typed'"
  forbidden_substitutes: "a second wiki generator; a summary read from a separate index file instead of the document; a test that only checks the code path runs without asserting the summary text and its source label"
  boundaries: "enforced-planning only, files enforced_planning/relationship_context.py and tests/test_relationship_context.py plus this plan; claimed worktree markdown-description-summary; no irreversible action; merge after the repository's own check passes"
  done_when: "the front-matter test passes on the branch and fails on HEAD, judged from the full pytest output of both runs; the full tests/test_relationship_context.py and tests/test_docstring_wiki.py run on the branch passes with every test listed; the change merges with make check passing"
  do_not_gate_on: "Brian reading the plan; AES durable-docs milestone M4; DIGIMON documentation consolidation"
---

# Markdown summaries prefer the document's own description line

Each section below answers the checklist items quoted in it; the gate judges only that
section's text. Replace every `TODO(answer ...)` line before running `cli.py check`. Quote
values in the front matter: an unquoted ` #` starts a YAML comment and cuts the value.

## Route

> **CORE-ROUTE** (blocking): The selected Company Planning route equals the deterministic path classification of the recorded structural facts.

Route: `prototype`, recorded in [markdown-description-summary.path-decision.json](markdown-description-summary.path-decision.json). The recorded structural facts are one writer, reversible, boundary known, and none of the coordination facts (no concurrent writers, shared contract mutation, persistent migration, governed registry or consequential external mutation), which classify to `prototype`.

## Standard conformance

> **OV-STANDARD-CONFORMANCE-RULES** (blocking): The plan names each external standard, schema or contract the work claims to follow, where its machine-readable rules live, and which of those rules the work's artifacts must satisfy. Where the standard publishes no machine-readable rules, the plan says so and names the written rules its check will encode instead.

> **OV-STANDARD-CONFORMANCE-GATE** (blocking): A named check tests the work's artifacts against those rules and runs in the merge or release gate, not only once by hand. The plan's disproof includes: an artifact labelled as conforming to the standard violates one of its rules. Anything the work adds beyond the standard is labelled as an extension.

**Standard followed:** AES canonical clause AES-CTX-004 and its Decision 0013 (BrianMills2718/agentic-engineering-system-canonical, `docs/architecture/SYSTEM_BOUNDARY.md` and `docs/decisions/0013-truth-lives-where-it-is-edited.md`, merged at `af999ab9a`). It publishes no machine-readable rules. The written rule this work's check encodes is Decision 0013 item 1 for documents: a document's summary is the `description` front-matter line authored in that document, and item 2: the generated wiki shows that in-document copy. Those are the rules the artifacts (`ArtifactRecord.summary` and the generated wiki line) must satisfy; they are recorded as RULE-MD-SUMMARY in `docs/model/ODD.md`.

**Gate:** `tests/test_relationship_context.py::test_markdown_front_matter_description_outranks_body` encodes that rule. It runs in this repository's merge gate, `make check` (its `test-quick` step runs `python -m pytest tests/ -q`), on every change, not once by hand.

**Disproof addition:** the approach is wrong if an artifact labelled as following AES-CTX-004 (a document with a `description` line) is reported with any other summary or source label, which is a violation of the rule.

**Extensions beyond the standard:** the fallback order after the description (semantic section, then first paragraph) and the `summary_source` labels are enforced-planning's own behaviour, labelled as this repository's extension, not part of AES-CTX-004, in the artifact itself (the `_markdown_record` docstring in `enforced_planning/relationship_context.py`, which the generated docstring wiki also shows), in `docs/model/ODD.md`, and here.

## Prior art and ownership

> **OV-PRIOR-ART-DISPOSITION** (blocking): Existing ownership, internal lineage, and relevant external prior art were searched, and each candidate found is dispositioned as reuse, extend, compose, supersede, or bounded exception.

> **OV-PRIOR-ART-PARALLEL-CHECK** (blocking): The plan names one concrete structural check or consumer-path observation that would detect a silent parallel implementation of the same concern.

| Candidate found (searched 2026-10-10) | Disposition |
|---|---|
| Existing owner: enforced-planning `relationship_context.py` `_markdown_record` and `docstring_wiki.py` (already lists every tracked Markdown file with a summary) | **extend**: this plan adds the description-first rule here |
| Internal lineage: project-meta `docs/designs/CONTEXT_ENGINEERING_AND_DERIVED_DOCUMENTATION_2026-08-24.md` (Amendment A, rules generated into implementors) and AES canonical Decision 0003 item 3 | **reuse** as the governing idea; no code |
| Internal: `wiki_methodology` `wiki/_schema.md` page properties (YAML front matter with `title`, `type`, `status`) | **reuse** its front-matter convention; the `description` key sits beside those properties |
| Internal: AES canonical plan `aes-durable-docs` R13 (DOC-NO-DESCRIPTION, CATALOG-STALE) | **compose**: its checker calls `docstring_wiki --check` and keys off this plan's `summary_source` label instead of building a generator |
| External: Obsidian / Dataview front-matter properties; Jekyll and Hugo `description` front matter; Python PEP 257 module docstrings | **reuse** the convention (a `description` key in leading YAML front matter, parsed with PyYAML, the repository's existing dependency); no external tool is adopted because the generator already exists |

**Parallel-implementation check:** `rg -n "front.?matter|safe_load" enforced_planning/ scripts/docstring_wiki.py` must show the Markdown front-matter description read only in `_split_front_matter`; and on AES canonical, `aes-durable-docs` CATALOG-STALE must call `docstring_wiki --check` rather than its own renderer (consumer-path observation at its M4).

## Actor and result

> **CORE-ACTOR-RESULT-EXAMPLE** (blocking): The plan names the actor it serves, the desired result, and one stable, concrete, user-visible example of that result.

**Actor:** an agent (or Brian) reading a repository's generated docstring wiki to decide which document answers a question, and the agent editing a document, who sees and updates its description line in place (AES canonical AES-CTX-004, Decision 0013).

**Result:** a document's own `description` front-matter line is its summary in the relationship inventory and in `generated/docstring_wiki.md`.

**Example:** `docs/described.md` beginning `---\ndescription: Why plans archive after completion.\n---` with a `## Decision` section is listed in the generated wiki as "Why plans archive after completion." (source `markdown:front-matter:description`); `docs/typed.md` whose front matter has only `title:` and `type:` is listed by its first body paragraph, not by the text `title: Typed`.

## Requirements

> **CORE-REQUIREMENTS-TRACED** (blocking): The plan lists its requirements: what was asked for, and what the delivered work's own claims imply. A claim here is what the work is presented as being or doing to its users, for example work presented as following a standard, schema or contract (which implies conformance to it) or an output labelled as showing something (which implies it shows it correctly); the plan's own format and front matter are not such claims, and the details a check examines (what a trace must show) belong to that check rather than being separate requirements. Each requirement names the check that verifies it (a test, script, gate step, or named review of a run) and its status: passing, failing, planned and not yet run, or deferred with a stated reason; deferred requirements are carried onto every release or completion record the plan names. A plan fails this item if it has no requirements list, if any requirement has neither a check nor an explicit deferral with its reason, or if the plan presents the work as following a named standard, schema or contract, or as having another property its users rely on, that its requirements list omits.

| ID | Requirement | Check | Status |
|---|---|---|---|
| R1 | A non-empty string `description` in a document's leading YAML front matter is its summary, labelled `markdown:front-matter:description`, and outranks section and first-paragraph summaries (asked: Brian 2026-10-10) | `tests/test_relationship_context.py::test_markdown_front_matter_description_outranks_body`, `described` case | passing on branch; failing on HEAD |
| R2 | Front-matter keys other than `description` never become a summary (implied: the inventory claims summaries come from source prose) | same test, `typed` case | passing on branch |
| R3 | Malformed front matter does not crash the inventory and falls back to the existing section/first-paragraph rule | same test, `broken` case | passing on branch |
| R4 | Existing summary behaviour for documents without front matter is unchanged (implied: the docstring wiki is a maintained output) | `tests/test_relationship_context.py`, `tests/test_docstring_wiki.py` | passing on branch (12 passed) |

| R5 | Conforms to AES canonical clause AES-CTX-004 (Decision 0013): a fact about one document, its summary, is taken from the document itself, and the generated wiki shows that copy | the R1 test (the description inside the document wins over every other source) plus, after merge, `scripts/docstring_wiki.py --write` on AES canonical showing Decision 0013 by its own description | R1 part passing on branch; generated-wiki part planned, run after merge |

## Success and disproof

> **CORE-SUCCESS-DISPROOF** (blocking): The plan defines the evidence that would show success and a concrete condition that would disprove the approach. Each success measure is the property the plan claims, or a check that directly tests that property, not a stand-in for it: a count, a picture, a readability judgment, or the pipeline agreeing with itself (hashes, labels, byte equality) does not show correctness or conformance it does not test. A plan fails this item if it has no disproof condition, or if a success measure is such a stand-in for the claimed property and the plan names no direct check of that property.

> **CORE-TRACE-REVIEW** (blocking): Every success or acceptance criterion in the plan is judged from the full trace of a run, not only its final outcome: it names the run whose full trace is examined (for example the session, its tool and LLM calls, commits, check output, or messages), where that trace lives, and what must be seen in that trace beyond the final outcome. A criterion that names only an outcome, such as tests passing, a PR merged, a test fixture reproducing the journey, or a status reading succeeded, fails this item. A criterion for which no run exists, such as a pure document edit, passes only when the plan states that exemption and its reason explicitly.

**Success evidence (direct checks of the claimed property):** the new test asserts the exact summary text and its source label for each of the three cases (R1-R3); it passes with the change and fails when `relationship_context.py` is restored from HEAD, which shows the test exercises the change rather than passing trivially. The two existing test files pass unchanged (R4).

**Disproof:** the approach is wrong if, after merge, running `scripts/docstring_wiki.py --repo-root <AES canonical checkout> --write` lists `docs/decisions/0013-truth-lives-where-it-is-edited.md` by anything other than its front-matter description once that file carries one, or if any test in the two files fails.

1. **Run:** `python3 -m pytest tests/test_relationship_context.py tests/test_docstring_wiki.py` on the branch, then the front-matter test alone with `relationship_context.py` restored from HEAD (`git show HEAD:...`). **Trace:** the complete pytest output of both runs (each test id with its result, the counts line, exit status), pasted in the pull request body. **Must be seen beyond the outcome:** the new test id listed as passed on the branch and failed on HEAD, with the failing assertion showing the old summary text; every other test id listed as passed. Recorded 2026-10-10: branch 12 passed, exit 0; HEAD 1 failed, exit 1.
2. **Run:** `make check` in the worktree before merge. **Trace:** its full output with counts and exit status, pasted in the pull request body. **Must be seen:** the counts line and exit status 0, and no test in the two files above skipped.

## When a run fails or surprises us

> **CORE-TRACE-DEBUGGING** (blocking): The plan includes a separate When a run fails or surprises us procedure, distinct from anticipated failure modes. It requires preserving the failed run and its trace id; reading full inputs, prompts, each tool call arguments/results, intermediate stages and final output before selecting a fix; citing the observed divergence; classifying evidence absent, evidence returned but unused or contradicted, invalid expectation, or unresolved; and linking a targeted repair to a new traced verification run while retaining the original failure. Unresolved diagnoses permit investigation but cannot authorize a causal repair. Review completeness is separate from the run verdict.

This procedure is separate from, and distinct from, the anticipated failure modes the test already covers (malformed YAML, a non-string description). It applies to any failure or surprise in the runs above.

1. Preserve the failed run: keep its full pytest output and the worktree state; record the failing test id as the trace id.
2. Read the full inputs before choosing a fix: the fixture document text, the inventory JSON record for that file (`summary`, `summary_source`, `diagnostics`), each intermediate stage (`_split_front_matter` result, `_markdown_sections` output) and the final generated wiki line.
3. Cite the observed divergence: the expected versus actual summary or source label, quoted.
4. Classify it as one of: evidence absent (the description was never parsed), evidence returned but unused or contradicted (parsed but overridden), invalid expectation (the test's expected text is wrong), or unresolved.
5. Link a targeted repair to a new traced verification run (the same pytest command, full output kept) while keeping the original failed output. An unresolved diagnosis permits investigation only and cannot authorize a causal repair. Whether this review was complete is judged separately from the run's pass/fail verdict.

## System model

> **CORE-SYSTEM-MODEL** (blocking): The plan links the project's system model (a path such as docs/model/ODD.md) or carries the one-line exemption `System model: [docs/model/ODD.md](../model/ODD.md), reachable from `wiki/index.md` -> `README.md` (Canonical Docs). This repository's model is scoped to the inventory and docstring wiki only; claims, sessions and hooks are out of its scope.

Elements this work adds, changes or relies on, and what the examined runs must show of each:
- **RULE-MD-SUMMARY** (added clause: description first): the pytest run must show the `described` case reporting the description text with `summary_source` `markdown:front-matter:description`, and the `typed` case reporting its body paragraph.
- **ENT-ARTIFACT** (relied on; fields unchanged): the same run must show `summary` and `summary_source` populated for each fixture file.
- **PROC-INVENTORY** and **PROC-DOCSTRING-WIKI** (relied on): `tests/test_docstring_wiki.py` must pass in the same run.
- **VIEW-DOCSTRING-WIKI** (relied on): the after-merge run on AES canonical must show Decision 0013's line in `generated/docstring_wiki.md` carrying its description.

Source-linked views: VIEW-DOCSTRING-WIKI is the only view; no diagram is needed for three processes. Freshness and drift: `make docstring-wiki-check` fails on a stale generated view, and the model's RULE-MD-SUMMARY names the tests that would fail if the code drifted from it. Reconciliation in this change: the model file is created in this same commit with RULE-MD-SUMMARY matching the code, the view list has its one view, and the verification evidence is the test output named in Success and disproof.

## Capability reuse

> **CORE-CAPABILITY-REUSE** (blocking): The plan answers capability reuse against the capability catalogue in agentic-capability-architecture-canonical, which has two files: `reuse_candidates.yml`, whose entries under `candidates:` are cross-project capabilities with their selected off-the-shelf implementations, each named by its `id` (for example `documents_to_text`) and marked candidate or promoted; and `capability_registry.yml`, whose entries under `capabilities:` are the packages that repository holds, each named by its key (for example `approvals`) with the capability ids it `provides` (for example `approval.resolve`). An entry from either file counts. The plan names each catalogue capability the work reuses, by its id, key or provided id; names each new capability the work adds together with its first consumer (the project, command or workflow in this plan that uses it); and, where no entry covers what the work needs, states `No catalogue entry fits, because <reason>`, the reason saying what the work needs that no entry provides. A plan may give more than one of these answers. A plan fails this item if it gives none of them, if it claims reuse without naming the catalogue entry or id reused (reusing code or a contract that is not a catalogue entry does not count), if it adds a capability without naming its first consumer, or if it says no entry fits without a reason.

No catalogue entry fits, because what this work needs is a rule for which Markdown text the enforced-planning relationship inventory reports as a document's summary, and neither `reuse_candidates.yml` (searched 2026-10-10: no docstring, wiki-generation or relationship-inventory entry) nor `capability_registry.yml` in agentic-capability-architecture-canonical provides a document-summary or repository-wiki generator. The work extends the existing enforced-planning module `relationship_context.py` (used by `scripts/docstring_wiki.py`) and adds no new capability, so there is no new first consumer.

## Authority and non-goals

> **CORE-AUTHORITY-NONGOALS** (blocking): The plan states who holds authority over the work and what it explicitly will not do (non-goals).

**Authority:** Brian (2026-10-10, quoted in Decision 0013 of AES canonical); enforced-planning is his repository and his standing rule permits merging after local checks. The implementing agent decides implementation inside the boundaries in the front matter.

**Non-goals:** no new generator or catalog file; no diagnostic code for missing descriptions (AES durable-docs keys its DOC-NO-DESCRIPTION check off `summary_source`); no change to Python docstring handling; no edits to any other repository; no rewriting of existing documents.

## Irreversible actions and spend

> **CORE-IRREVERSIBLE-SPEND** (blocking): For each irreversible action or spend the plan proposes, it names the boundary, who must authorize it, and how it is contained.

None proposed. Every change is a git commit in a claimed worktree, revertible by one revert. The only spend is this plan's adoption-verifier model calls (a few cents through Brian's OpenRouter route under his standing planning-verification authority), contained by the verifier's single pass per item.

## Uncertainties

> **CORE-UNCERTAINTIES** (blocking): The plan lists its material uncertainties, and each one has an owner or the evidence that would resolve it.

| Uncertainty | Owner or resolving evidence |
|---|---|
| Whether some repository's documents use a `description` key with another meaning (for example a schema description) that would now become their summary | Resolved after merge by `make docstring-wiki` on AES canonical and DIGIMON: the diff of generated wiki lines shows every changed summary; owner: the implementing agent |
| Whether long folded descriptions read well as one-line wiki summaries | Resolved by the same generated-wiki diff; owner: the implementing agent |

## Activation facts

> **CORE-ACTIVATION-FACTS** (blocking): No activation fact that the plan triggers is declared false. Declaring a fact true when the plan does not strictly need it is acceptable, because it only adds checks; judge only facts declared false. empirical_comparison_proposed is triggered when the plan proposes an A/B test, benchmark, bake-off, or other experiment comparing alternative designs, models, or candidates to choose among them; checking the built result against an expected outcome (an acceptance test, fixture replay, or regression check) is verification and does not trigger it. shared_mechanism is triggered by a new shared mechanism, contract, or algorithm; llm_central by behavior that centrally depends on LLM calls; irreversible_or_spend_action by a proposed irreversible action or spend. claims_external_standard is triggered when the plan claims, or presents its work as, following, implementing or conforming to a standard, schema or contract owned outside the repository being changed (for example a model presented as DM2, or output said to match a published schema); conforming to the repository's own contracts does not trigger it; aes_governed_target when the target repository is governed by an AES target (`.aes/target.yaml`). These two facts are optional: an undeclared one is shown as false and is judged like a declared false.

Declared: `shared_mechanism` true (the summary-selection rule lives in the shared relationship inventory that every repository's generated docstring wiki uses); `empirical_comparison_proposed` false (no comparison of alternatives; the with/without run is verification of the built change); `llm_central` false (the change makes no LLM calls); `irreversible_or_spend_action` true (the adoption verifier's model calls are a small spend; see Irreversible actions and spend); `claims_external_standard` true (the work follows AES canonical clause AES-CTX-004, owned outside enforced-planning; requirement R5 covers it); `aes_governed_target` false (enforced-planning has no `.aes/target.yaml`).

## Vertical and reset

> **OV-PROTO-VERTICAL-RESET** (blocking): The plan names the minimal vertical result, the reset boundary, and the non-goals, without adding coordinated-work ceremony.

**Minimal vertical result:** one document with a description line appears in the generated wiki with that line as its summary, proven by one focused test run with and without the change.

**Reset boundary:** if the change regresses any existing summary test or the generated wiki on AES canonical shows unexpected summaries, revert the single commit and return to the HEAD behaviour; nothing else depends on it yet.

**Non-goals:** see Authority and non-goals. No coordinated-work ceremony is added: one writer, one worktree, one pull request, and the checks the repository already runs.
