# Plan 66 semantic document lifecycle assessment mockup

> **Status:** proposed design seam awaiting human disposition. This is not a
> schema-valid fixture, LLM result, terminal-use certification, archive
> disposition, or provider-call authorization. IDs in compiled/reviewed records
> are illustrative system outputs and are absent from the model-facing payload.

## Decision this mockup makes reviewable

Can an LLM/human workflow represent what one complete document appears to say
about its lifecycle, preserve an apparent competing signal elsewhere in the
document, and inform archive preflight without turning “superseded” into
“archive now”?

The proving case is Greer's V8-B1 slice. It is useful because its opening note
says the slice was superseded and must not be implemented, while its final task
list still contains unchecked implementation work.

## 1. Exact source revision

```yaml
artifact_revision:
  repository_id: github:BrianMills2718/greer
  commit_oid: ae262c09c32083361d366bd90d63383e97d158ac
  path: plan/slices/2026-07-13-slice-v8b1-proposal-validation.md
  git_blob_oid: 6793aaa9e52e2362c472d291a681ffea0a86233a
  content_sha256: 5c65a002a13e11bdf772d3c27a9ecc5c5d3465ee2de0ad6b831e5b6d9919f081
  byte_length: 11446
  line_count: 212
  review_scope: complete_document
```

The proposer and reviewer receive all 212 ordered lines. These two excerpts are
shown because they bear most directly on lifecycle; they are not the entire
model input.

### Opening lifecycle note, lines 3-8

```text
> Sources: `investigations/2026-07-13-v8-proposal-validator-design.md` and every
> source enumerated there. Status: superseded before implementation by
> `investigations/2026-07-13-cross-document-ambiguity-resolution-osint.md` and
> revised ADR 004. Retained as historical design evidence; do not approve or
> implement this slice as written. The active replacement is
> `plan/slices/2026-07-13-slice-v8b2-layered-semantic-graph-contract.md`.
```

### Apparently open work, lines 208-212

```text
- [ ] Record Brian's mockup approval or warned override.
- [ ] Implement B.1a tests first, then the typed hard-gate skeleton.
- [ ] Audit/clean B.1a and triage the concern register.
- [ ] Implement B.1b tests/readout without provider calls.
- [ ] Run adversarial audit, coverage refresh, full gates, commit, and push.
```

The opening note is direct evidence about current lifecycle and use. The
unchecked list is direct evidence that the historical plan text contains
unfinished tasks. Whether those tasks remain current obligations is a semantic
question; a checkbox counter cannot decide it.

## 2. Current Plan 65 result

With no Greer document declaration yet, the exact current report is:

```yaml
candidate:
  path: plan/slices/2026-07-13-slice-v8b1-proposal-validation.md
  lifecycle: unknown
  declared: false
  readiness: blocked
  blockers:
    - code: document-undeclared
      message: Document has no reviewed role and purpose-bearing justification.
    - code: lifecycle-not-terminal
      message: Source-local lifecycle 'unknown' is not terminal for active use.
```

This is correct P2 behavior. The compiler refuses to interpret prose. Plan 66
must not weaken that boundary by hiding an LLM classifier inside the same
function.

## 3. Model-facing input shape

System-created revision IDs, hashes, evidence handles, and ordered units are
inputs. The LLM produces only semantic proposal content.

```yaml
task:
  semantic_scope: document_lifecycle_and_use_only
  question: >-
    What lifecycle, use, successor, and retention claims does this complete
    document appear to make about itself?
  constraints:
    - make every assertion standalone and name its subject
    - cite exact evidence handles and quotes
    - preserve plausible alternatives and challenging evidence
    - do not decide archive eligibility
    - do not assign IDs, authority, reviewer identity, or timestamps
source_scope:
  scope_kind: complete_document
  ordered_unit_handles: [ev1_line_0001, ..., ev1_line_0212]
  lifecycle_note_handle: ev1_lines_0003_0008
  unchecked_tasks_handle: ev1_lines_0208_0212
```

The real implementation uses native JSON Schema with Pydantic field
descriptions and opaque evidence handles. Ellipses here abbreviate display, not
the actual source scope.

## 4. ID-free semantic proposal

This illustrates a strong proposal. It is not a recorded model result.

```yaml
proposal_batch:
  proposals:
    - kind: lifecycle_status
      standalone_claim: >-
        The Greer V8-B1 proposal-validation slice states that the slice was
        superseded before implementation.
      subject_description: The Greer V8-B1 proposal-validation slice at plan/slices/2026-07-13-slice-v8b1-proposal-validation.md.
      lifecycle_state: superseded
      qualifier: before implementation
      origin:
        origin_kind: exact
        evidence_handle: ev1_lines_0003_0008
        exact_quote: "Status: superseded before implementation"
      supporting_evidence_handles: [ev1_lines_0003_0008]
      opposing_or_challenging_evidence_handles: []
      support_grade: direct
      alternatives: []
      blockers: []
      justification: The opening note explicitly labels the slice as superseded before implementation.

    - kind: retention_purpose
      standalone_claim: >-
        The Greer V8-B1 proposal-validation slice states that the slice is
        retained as historical design evidence.
      subject_description: The Greer V8-B1 proposal-validation slice at plan/slices/2026-07-13-slice-v8b1-proposal-validation.md.
      retention_purpose: historical_design_evidence
      origin:
        origin_kind: exact
        evidence_handle: ev1_lines_0003_0008
        exact_quote: "Retained as historical design evidence"
      supporting_evidence_handles: [ev1_lines_0003_0008]
      opposing_or_challenging_evidence_handles: []
      support_grade: direct
      alternatives: []
      blockers: []
      justification: The document directly states why the superseded slice remains present.

    - kind: operational_directive
      standalone_claim: >-
        The Greer V8-B1 proposal-validation slice instructs readers not to
        approve or implement the slice as written.
      subject_description: Readers acting on the Greer V8-B1 proposal-validation slice.
      action: approve_or_implement_slice_as_written
      directive: prohibited
      origin:
        origin_kind: exact
        evidence_handle: ev1_lines_0003_0008
        exact_quote: "do not approve or\n> implement this slice as written"
      supporting_evidence_handles: [ev1_lines_0003_0008]
      opposing_or_challenging_evidence_handles: []
      support_grade: direct
      alternatives: []
      blockers: []
      justification: >-
        The opening note directly instructs readers not to approve or implement
        the slice as written.

    - kind: successor_designation
      standalone_claim: >-
        The Greer V8-B1 proposal-validation slice identifies the Greer V8-B2
        layered semantic graph contract as the active replacement for V8-B1.
      subject_description: The Greer V8-B1 proposal-validation slice at plan/slices/2026-07-13-slice-v8b1-proposal-validation.md.
      successor_path_text: plan/slices/2026-07-13-slice-v8b2-layered-semantic-graph-contract.md
      designation: active_replacement
      origin:
        origin_kind: exact
        evidence_handle: ev1_lines_0003_0008
        exact_quote: |-
          The active replacement is
          > `plan/slices/2026-07-13-slice-v8b2-layered-semantic-graph-contract.md`.
      supporting_evidence_handles: [ev1_lines_0003_0008]
      opposing_or_challenging_evidence_handles: []
      support_grade: direct
      alternatives: []
      blockers: []
      justification: The opening note explicitly names an active replacement.

    - kind: work_item_signal
      standalone_claim: >-
        The Greer V8-B1 proposal-validation slice lists implementation and
        closeout work as unchecked task-list items.
      subject_description: The Greer V8-B1 proposal-validation slice at plan/slices/2026-07-13-slice-v8b1-proposal-validation.md.
      item_state: unchecked
      work_scope_description: implementation and closeout work
      origin:
        origin_kind: exact
        evidence_handle: ev1_lines_0208_0212
        exact_quote: |-
          - [ ] Record Brian's mockup approval or warned override.
          - [ ] Implement B.1a tests first, then the typed hard-gate skeleton.
          - [ ] Audit/clean B.1a and triage the concern register.
          - [ ] Implement B.1b tests/readout without provider calls.
          - [ ] Run adversarial audit, coverage refresh, full gates, commit, and push.
      supporting_evidence_handles: [ev1_lines_0208_0212]
      opposing_or_challenging_evidence_handles: [ev1_lines_0003_0008]
      support_grade: direct
      alternatives: []
      blockers:
        - The opening note says not to implement this superseded slice as written, so unchecked syntax does not establish current authority.
      justification: >-
        The task-list signal is preserved as a source-local claim; whether it
        represents current work is deferred to the terminal-use assessment.
```

Why this is acceptable:

- no assertion contains unresolved `it`, `this`, `he`, or an unexplained ID;
- each source claim names V8-B1 or its readers;
- the task list is not erased;
- the source claims do not say the slice is safe to archive; and
- the model supplies no system ID or authority field.

## 5. Deterministic exact compilation

The compiler reopens every quote in the pinned blob, assigns evidence/proposal
IDs, attaches the complete-scope digest, and rejects any mismatch. Example:

```yaml
compiled_proposal:
  proposal_id: lifecycle-proposal:greer-v8b1:r1
  source_revision:
    commit_oid: ae262c09c32083361d366bd90d63383e97d158ac
    git_blob_oid: 6793aaa9e52e2362c472d291a681ffea0a86233a
    content_sha256: 5c65a002a13e11bdf772d3c27a9ecc5c5d3465ee2de0ad6b831e5b6d9919f081
  complete_scope_bound: true
  whole_document_graph_complete: false
  exact_anchors:
    - exact_quote: "Status: superseded before implementation"
      byte_start: 172
      byte_end: 212
    - exact_quote: "Retained as historical design evidence"
      byte_start: 314
      byte_end: 352
    - exact_quote: "do not approve or\n> implement this slice as written"
      byte_start: 354
      byte_end: 405
    - exact_quote: |-
        The active replacement is
        > `plan/slices/2026-07-13-slice-v8b2-layered-semantic-graph-contract.md`.
      byte_start: 407
      byte_end: 506
    - exact_quote: |-
        - [ ] Record Brian's mockup approval or warned override.
        - [ ] Implement B.1a tests first, then the typed hard-gate skeleton.
        - [ ] Audit/clean B.1a and triage the concern register.
        - [ ] Implement B.1b tests/readout without provider calls.
        - [ ] Run adversarial audit, coverage refresh, full gates, commit, and push.
      byte_start: 11128
      byte_end: 11445
  proposer_provenance:
    actor_ref: model-or-human-proposer:r1
    method_ref: document-lifecycle-proposal:v1
    prompt_schema_trace_ref: trace:illustrative
```

The compiler proves quote and revision integrity. It does not prove that the
proposal is semantically faithful, and the lifecycle projection does not prove
that the document's complete semantic graph has been authored.

## 6. Separate semantic review

The reviewer sees the entire document, not only the compiled claims.

```yaml
semantic_review:
  review_id: lifecycle-review:greer-v8b1:r1
  proposal_digest: sha256:illustrative-proposal-digest
  source_scope_digest: sha256:illustrative-complete-scope-digest
  reviewer_ref: reviewer:model-or-human:r1
  review_method_ref: document-lifecycle-semantic-review:v1
  decisions:
    - proposal_kind: lifecycle_status
      semantic_status: resolved
      governance_recommendation: accepted
      reasoning: The status is directly and explicitly attributed to the V8-B1 slice.
    - proposal_kind: retention_purpose
      semantic_status: resolved
      governance_recommendation: accepted
      reasoning: The retention purpose is explicit and does not imply active authority.
    - proposal_kind: operational_directive
      semantic_status: resolved
      governance_recommendation: accepted
      reasoning: >-
        The explicit opening directive scopes the later unchecked tasks as
        historical plan content, while those tasks remain cited as challenging evidence.
    - proposal_kind: successor_designation
      semantic_status: resolved
      governance_recommendation: accepted
      reasoning: >-
        The document explicitly names V8-B2 as the active replacement; this
        does not prove that every durable V8-B1 claim was promoted.
    - proposal_kind: work_item_signal
      semantic_status: resolved
      governance_recommendation: accepted
      reasoning: >-
        The unchecked task syntax and work descriptions are explicit. Whether
        those items remain current is a separate analytic interpretation.
  residual_assessment:
    semantic_status: ambiguous
    reasoning: >-
      The document contains unchecked tasks, so an open-work interpretation is
      textually available when those lines are isolated. The explicit opening
      note makes terminal use the better-supported whole-document reading.
```

The reviewer can reject or withhold any proposal without modifying it. A later
review supersedes this record rather than editing it in place.

## 7. Source-local claim occurrences

After authority compilation, the source claims use the document narrative as
claimant. The model and reviewer remain provenance, not claimants of the source
content. The non-asserting proposition-content definitions are abbreviated
here; S1 must serialize and validate them before any executable claim.

```yaml
source_local_claims:
  - claim_id: claim:greer-v8b1:lifecycle:r1
    layer: source_local
    claimant_ref: document-narrative:greer-v8b1
    content_id: content:document-lifecycle-status:v1
    argument_bindings:
      subject_revision: greer-v8b1@ae262c09c32083361d366bd90d63383e97d158ac
      lifecycle_state: superseded
      qualifier: before_implementation
    standalone_projection: >-
      The Greer V8-B1 proposal-validation slice states that the slice was
      superseded before implementation.
    grounding_refs: [evidence:greer-v8b1:status]
    method_ref: document-lifecycle-semantic-authoring:v1
    graph_revision_id: docgraph:greer-v8b1:r1
    governance_decision_ref: lifecycle-review:greer-v8b1:r1

  - claim_id: claim:greer-v8b1:retention-purpose:r1
    layer: source_local
    claimant_ref: document-narrative:greer-v8b1
    content_id: content:document-retention-purpose:v1
    argument_bindings:
      subject_revision: greer-v8b1@ae262c09c32083361d366bd90d63383e97d158ac
      retention_purpose: historical_design_evidence
    standalone_projection: >-
      The Greer V8-B1 proposal-validation slice states that the slice is
      retained as historical design evidence.
    grounding_refs: [evidence:greer-v8b1:retention-purpose]
    method_ref: document-lifecycle-semantic-authoring:v1
    graph_revision_id: docgraph:greer-v8b1:r1
    governance_decision_ref: lifecycle-review:greer-v8b1:r1

  - claim_id: claim:greer-v8b1:directive:r1
    layer: source_local
    claimant_ref: document-narrative:greer-v8b1
    content_id: content:document-operational-directive:v1
    argument_bindings:
      subject_revision: greer-v8b1@ae262c09c32083361d366bd90d63383e97d158ac
      action: approve_or_implement_slice_as_written
      directive: prohibited
    standalone_projection: >-
      The Greer V8-B1 proposal-validation slice instructs readers not to
      approve or implement the slice as written.
    grounding_refs: [evidence:greer-v8b1:directive]
    method_ref: document-lifecycle-semantic-authoring:v1
    graph_revision_id: docgraph:greer-v8b1:r1
    governance_decision_ref: lifecycle-review:greer-v8b1:r1

  - claim_id: claim:greer-v8b1:successor:r1
    layer: source_local
    claimant_ref: document-narrative:greer-v8b1
    content_id: content:document-successor-designation:v1
    argument_bindings:
      subject_revision: greer-v8b1@ae262c09c32083361d366bd90d63383e97d158ac
      successor_path_text: plan/slices/2026-07-13-slice-v8b2-layered-semantic-graph-contract.md
      designation: active_replacement
    standalone_projection: >-
      The Greer V8-B1 proposal-validation slice identifies the Greer V8-B2
      layered semantic graph contract as the active replacement for V8-B1.
    grounding_refs: [evidence:greer-v8b1:successor]
    method_ref: document-lifecycle-semantic-authoring:v1
    graph_revision_id: docgraph:greer-v8b1:r1
    governance_decision_ref: lifecycle-review:greer-v8b1:r1

  - claim_id: claim:greer-v8b1:unchecked-tasks:r1
    layer: source_local
    claimant_ref: document-narrative:greer-v8b1
    content_id: content:document-work-item-signal:v1
    argument_bindings:
      subject_revision: greer-v8b1@ae262c09c32083361d366bd90d63383e97d158ac
      item_state: unchecked
      work_scope_description: implementation_and_closeout_work
    standalone_projection: >-
      The Greer V8-B1 proposal-validation slice lists implementation and
      closeout work as unchecked task-list items.
    grounding_refs: [evidence:greer-v8b1:unchecked-tasks]
    method_ref: document-lifecycle-semantic-authoring:v1
    graph_revision_id: docgraph:greer-v8b1:r1
    governance_decision_ref: lifecycle-review:greer-v8b1:r1
```

All five accepted source-local claims remain explicit in this review mockup.

## 8. Separate terminal-use candidate and assessment claims

The two interpretations are independently citable analytic claims. A third
analytic claim compares them. The analysis scope and occurrence detail carry
no assertion independently of their owning claim occurrences.

```yaml
analysis_scope:
  scope_id: scope:greer-v8b1:terminal-use:r1
  kind: terminal_use_scope
  question: >-
    Is the exact Greer V8-B1 document revision terminal for active use in the
    Greer repository?
  candidate_claim_ids:
    - claim:interpretation:greer-v8b1:terminal:r1
    - claim:interpretation:greer-v8b1:open-work:r1
  candidate_set_posture: open_includes_other_or_unknown
  other_or_unknown_available: true
  assumptions:
    - The opening lifecycle note is the document's current framing, not an unmarked quotation from another source.
  scope_revision_id: scope-revision:greer-v8b1:terminal-use:r1

candidate_claim_occurrences:
  - claim_id: claim:interpretation:greer-v8b1:terminal:r1
    layer: corpus_analytic
    claimant_ref: analyst:lifecycle-reviewer:r1
    content_id: content:document-terminal-use-interpretation:v1
    standalone_projection: >-
      At Greer commit ae262c09c32083361d366bd90d63383e97d158ac, the V8-B1
      proposal-validation slice is terminal for active use in the Greer repository.
    argument_bindings:
      target_revision: greer-v8b1@ae262c09c32083361d366bd90d63383e97d158ac
      use_scope: active_repository_work
    analytic_basis:
      - basis_claim_id: claim:greer-v8b1:lifecycle:r1
        relation: supports
      - basis_claim_id: claim:greer-v8b1:directive:r1
        relation: supports
      - basis_claim_id: claim:greer-v8b1:successor:r1
        relation: supports
      - basis_claim_id: claim:greer-v8b1:unchecked-tasks:r1
        relation: challenges
    method_ref: document-terminal-use-analysis:v1
    graph_revision_id: corpusgraph:document-lifecycle:r1
    analysis_scope_id: scope:greer-v8b1:terminal-use:r1
    governance_decision_id: decision:interpretation:greer-v8b1:terminal:r1

  - claim_id: claim:interpretation:greer-v8b1:open-work:r1
    layer: corpus_analytic
    claimant_ref: analyst:lifecycle-reviewer:r1
    content_id: content:document-terminal-use-interpretation:v1
    standalone_projection: >-
      At Greer commit ae262c09c32083361d366bd90d63383e97d158ac, the V8-B1
      proposal-validation slice may still own current implementation or
      closeout work in the Greer repository.
    argument_bindings:
      target_revision: greer-v8b1@ae262c09c32083361d366bd90d63383e97d158ac
      use_scope: active_repository_work
    analytic_basis:
      - basis_claim_id: claim:greer-v8b1:unchecked-tasks:r1
        relation: supports
      - basis_claim_id: claim:greer-v8b1:lifecycle:r1
        relation: challenges
      - basis_claim_id: claim:greer-v8b1:directive:r1
        relation: challenges
    method_ref: document-terminal-use-analysis:v1
    graph_revision_id: corpusgraph:document-lifecycle:r1
    analysis_scope_id: scope:greer-v8b1:terminal-use:r1
    governance_decision_id: decision:interpretation:greer-v8b1:open-work:r1

assessment_occurrence_detail:
  occurrence_detail_id: assessment-detail:greer-v8b1:terminal-use:r1
  kind: interpretation_assessment
  outcome: selected_candidate
  selected_candidate_claim_ids:
    - claim:interpretation:greer-v8b1:terminal:r1
  candidate_dispositions:
    claim:interpretation:greer-v8b1:terminal:r1: leading
    claim:interpretation:greer-v8b1:open-work:r1: less_supported
  comparative_likelihood_rationale: >-
    The document explicitly says it was superseded before implementation,
    prohibits implementation as written, and names an active replacement. The
    unchecked tasks are preserved but are scoped by that opening directive.
  analytic_confidence:
    band: high
    rationale: >-
      The decisive language is explicit and internally consistent; uncertainty
      remains about claim-promotion completeness, not the document's stated use status.
  information_gaps:
    - Whether every durable V8-B1 claim was preserved in current authority has not been assessed.
    - Whether any active reader, test, or gate still depends on the V8-B1 path has not been assessed.
  change_indicators:
    - A later Greer revision reactivates V8-B1 or removes the supersession directive.
    - Current authority identifies a V8-B1-only claim or evidence obligation.

assessment_claim_occurrence:
  claim_id: claim:assessment:greer-v8b1:terminal-use:r1
  layer: corpus_analytic
  claimant_ref: analyst:lifecycle-reviewer:r1
  content_id: content:terminal-use-interpretation-assessment:v1
  standalone_projection: >-
    The lifecycle reviewer assesses that the terminal-for-active-use
    interpretation is better supported than the current-open-work
    interpretation for Greer V8-B1 at commit
    ae262c09c32083361d366bd90d63383e97d158ac.
  argument_bindings:
    leading_candidate: claim:interpretation:greer-v8b1:terminal:r1
    competing_candidate: claim:interpretation:greer-v8b1:open-work:r1
  analytic_basis:
    - basis_claim_id: claim:interpretation:greer-v8b1:terminal:r1
      relation: evaluates
    - basis_claim_id: claim:interpretation:greer-v8b1:open-work:r1
      relation: evaluates
  occurrence_detail_id: assessment-detail:greer-v8b1:terminal-use:r1
  method_ref: document-terminal-use-assessment:v1
  graph_revision_id: corpusgraph:document-lifecycle:r1
  analysis_scope_id: scope:greer-v8b1:terminal-use:r1
  governance_decision_id: decision:assessment:greer-v8b1:terminal-use:r1
```

`high` is an explained qualitative judgment, not a probability or an archive
threshold. A configuration may omit confidence from a convenience projection;
the underlying reasoning and alternatives remain.

## 9. Resulting preflight — still blocked

The accepted terminal-use assessment can address only the lifecycle-semantic
question. It cannot erase Plan 65's other blocker or invent P4 evidence:

```yaml
augmented_preflight:
  candidate: plan/slices/2026-07-13-slice-v8b1-proposal-validation.md
  terminal_use_assessment_ref: claim:assessment:greer-v8b1:terminal-use:r1
  lifecycle_semantic_condition: satisfied_by_reviewed_claim
  transition_status: blocked
  remaining_blockers:
    - code: document-undeclared
      next_action: Add a reviewed role and purpose-bearing declaration through the separate relationship-governance lane.
    - code: durable-claim-promotion-unassessed
      next_action: Compare V8-B1's durable claims with named current authority and record exact promotion or no-current-claims reasoning.
    - code: current-evidence-retention-unassessed
      next_action: Determine whether any current gate requires this exact artifact or an exact replacement.
    - code: relationship-archive-effects-unassessed
      next_action: Classify active-path relationships as blocking, redirecting, lineage-only, or review-required.
    - code: archive-disposition-missing
      next_action: Obtain a revision-bound disposition only after every prior condition is resolved.
  licensed_actions: []
  explicitly_not_licensed:
    - mark_archive_eligible
    - move_file
    - rewrite_relationships
    - delete_historical_claims
```

This is the essential safety property: “the document is terminal for active
use” and “the document may be moved now” are different claims made by different
authorities over different evidence.

## 10. Required corruptions

The future fixture/tests must reject or surface each of these:

1. model output says only `It was superseded`;
2. model output contains a proposal ID, claim ID, reviewer, or archive decision;
3. exact quote is absent from or non-unique in the pinned blob;
4. review binds the path but not the commit/blob/content digest;
5. proposer receives only lines 3-8 while claiming complete-document review;
6. unchecked tasks are silently omitted from the reviewer input;
7. a lifecycle trace claims that the complete document graph is finished;
8. a checkbox or status regex selects the terminal-use posture;
9. source-local claimant is changed from the document narrative to the model;
10. terminal-use assessment deletes the less-supported open-work interpretation;
11. successor existence is treated as proof of complete claim promotion;
12. accepted terminal use clears `document-undeclared`;
13. P3 emits `archive_eligible`, moves a file, or rewrites relationships;
14. changed source bytes reuse the earlier review; or
15. a later assessment mutates the earlier source claims or assessment.

## Human disposition requested

Please review four material choices:

1. The five source-local assertions are lifecycle status, retention purpose,
   operational directive, successor designation, and the unchecked-task
   signal; each is standalone.
2. The unchecked tasks remain a less-supported competing terminal-use reading,
   not a reason for code to override the explicit opening note.
3. `terminal_for_active_use` satisfies only one semantic condition and leaves
   all declaration, promotion, evidence, relationship, disposition, and
   staleness gates intact.
4. Reusable semantic proposal/review/claim mechanics belong in onto-canon6;
   enforced-planning owns archive policy and preflight; Greer proves the case;
   Digimon is a later query consumer.

Acceptance permits only the schema-only S1 plan. It does not authorize an LLM
call, implementation on active onto-canon paths, a Greer relationship edit, or
an archive move.
