# Plan #55: Enforced-Planning Recursive Doc Spine Dogfood

**Status:** Complete
**Type:** implementation
**Priority:** High
**phase_ref:** "Owner-first agentic-system dogfood"
**goal_ref:** "bounded-current-documentation-authority"
**adrs_referenced:** ["ADR-0009"]
**research_citations:** []
**Landscape disposition:** linked
**Execution profile:** development
**Blocked By:** none
**Blocks:** integrated owner-first context-and-continuation proof

---

## Gap

**Current:** The recursive documentation-spine mechanics landed in April 2026,
but this plan and two overview snapshots continued to describe them as
unimplemented. The original self-hosted configuration also made a completed
delivery plan permanent required context and expanded one code-surface read to
11 documents / 13,052 words.

**Target:** The framework uses one compact, current authority path on itself:

- `EXECUTION_BRIEF.md` owns purpose and the north-star summary.
- `ROADMAP.md` owns mutable current proof, active gap, and roadmap state.
- `docs/plans/CLAUDE.md` indexes delivery plans without becoming their source.
- stable maintained code points to `DOC_AUTHORITY_SCHEMA.md`, not this completed
  implementation plan.
- compatibility pages resolve old links without duplicating current state.
- any claim with explicit `write_paths`, including a sanctioned `program`
  claim, is recognized as an authority-surface owner.

**Why:** Documentation governance is useful only if the agent can load enough
truth to act without reading a historical archive or following stale status.

## User Outcome

Brian and his agents can enter this repository, load a small authoritative
context for the documentation-governance surface, and receive a visible
reconciliation obligation when another live owner controls a drifting index.

## Canonical Behavioral Example

**Starting state:** Ask `file_context` for
`enforced_planning/doc_authority.py` while an active `program` claim owns
`docs/plans/CLAUDE.md` through explicit `write_paths`.

**Action:** Load required context and run the documentation-authority validator.

**Expected result:** Required context contains four documents / 2,577 words,
with `DOC_AUTHORITY_SCHEMA.md` as the stable primary spec. Index drift is
reported as `missing_reconciliation_obligation` with the live owner, not as
unowned drift.

**Failure signal:** Historical Plan 55 remains mandatory context, stale overview
pages claim the feature is absent, context exceeds the configured budget, or a
`program` claim with `write_paths` is ignored.

## References Reviewed

- `CLAUDE.md` — repository workflow and canonical surfaces.
- `EXECUTION_BRIEF.md` — compact purpose and north-star summary.
- `ROADMAP.md` — current proof frontier and active gap owner.
- `docs/reference/DOC_AUTHORITY_SCHEMA.md` — maintained doc-spine contract.
- `adr/0009-doc-authority-governance-and-enforcement.md` — dedicated authority
  configuration decision.
- `scripts/doc_authority.yaml` — self-hosted concern and code-surface mapping.
- `enforced_planning/doc_authority.py` — validator and live-owner resolution.
- `enforced_planning/file_context.py` — required-context boundary.
- `enforced_planning/plan_validation.py` — plan-reference enforcement.

## Research Basis For This Slice

No external research was needed. Direct self-hosting evidence, current Git
history, focused tests, and the live coordination registry govern this repair.

## Landscape And Prior Art

Plan 54 defined the recursive-spine design. Commits `23eb18bb`, `94e9610e`,
and `b2d9a539` implemented and extended it. This repair does not add a second
documentation system; it makes the existing one truthful and smaller.

Alternatives rejected:

1. Keep separate mutable current-state and gap-summary pages — rejected because
   they had already drifted while `ROADMAP.md` remained the active queue.
2. Keep this completed plan as the code surface's primary spec — rejected
   because delivery history should not become permanent operating context.
3. Treat only literal `write` claims as owners — rejected because ownership is
   expressed by scoped `write_paths`, and `program` is a sanctioned claim type.

## Capability Adoption

**Disposition: extend and subtract.** Reuse the existing doc-authority,
file-context, plan-validation, and coordination-claim capabilities. Remove
duplicate mutable authority and graduate the maintained contract to the stable
schema reference. No new documentation layer or registry is introduced.

## Files Affected

- `EXECUTION_BRIEF.md`
- `docs/overview/CURRENT_STATE.md`
- `docs/overview/GAP_SUMMARY.md`
- `docs/reference/DOC_AUTHORITY_SCHEMA.md`
- `docs/plans/55_enforced-planning_recursive_doc_spine_dogfood.md`
- `scripts/doc_authority.yaml`
- `enforced_planning/doc_authority.py`
- `tests/test_validate_doc_authority.py`

## Plan

### Critical Path Classification

| Increment | Class | Outcome changed |
|---|---|---|
| Compact the self-hosted authority path | `vertical` | Agents load current authority within the configured budget. |
| Recognize `program` claim write ownership | `direct_blocker` | Drift routes to its live owner instead of being mislabeled unowned. |
| Reconcile the plan index | `integration` | The repo-wide authority check becomes clean after its current owner updates the shared index. |

### Steps

1. Replace duplicate mutable current/gap authorities with compatibility
   pointers to `ROADMAP.md`.
2. Make the stable schema reference the primary spec for maintained doc-spine
   code surfaces.
3. Reproduce and fix live-owner detection for `program` claims with
   `write_paths`.
4. Prove the compact context path and focused validator behavior.
5. Integrate the existing plan-index owner's reconciliation, then align this
   plan and its index row in the now-unclaimed surface.

## Acceptance Criteria

- [x] One compact root brief plus one mutable roadmap cover purpose, north star,
  current proof, active gap, and roadmap concerns.
- [x] Old current-state and gap-summary URLs resolve without owning mutable
  truth.
- [x] Maintained code surfaces point to a stable reference rather than a
  completed implementation plan.
- [x] Required context for `enforced_planning/doc_authority.py` is reduced from
  11 documents / 13,052 words to 4 documents / 2,577 words.
- [x] A `program` claim with explicit `write_paths` is recognized as the live
  owner of an authority surface.
- [x] Focused doc-authority, plan-validation, and file-context tests pass.
- [x] Documentation and link self-tests pass.
- [x] The repo-wide doc-authority check is clean after the separately claimed
  plan index reconciles its remaining historical entries.

## Evidence

- Historical implementation: `23eb18bb`, `94e9610e`, and `b2d9a539`.
- Focused regression: `test_validate_doc_authority_recognizes_program_claim_write_ownership`.
- Focused suite: 43 tests passed across doc authority, plan validation, file
  context, and recursive closure.
- Documentation self-test: links and docs passed.
- Context observation: four required documents, including the root, totaling
  2,577 measured words; no doc-spine budget warning.
- Remaining validator findings are plan-index reconciliation obligations on a
  separately claimed shared surface, not failures of this doc-spine vertical.

## Failure And Replan Rules

| Failure | Required response |
|---|---|
| Compact context omits the maintained contract | Restore the smallest stable spec edge; do not restore the historical plan chain. |
| A compatibility page becomes mutable authority again | Move the state to `ROADMAP.md` and retain only the pointer. |
| An owner claim is still mislabeled unowned | Inspect explicit `write_paths` and path overlap before adding claim-type exceptions. |
| Index reconciliation expands this lane into archive cleanup | Keep the obligation with the existing index owner and proceed to the integrated owner-first proof. |

## Completion Disposition

The Plan 114 lane reconciled the shared historical index entries and released
the index. This lane then aligned Plan 55's row and fixed artifact identity,
partial/proposed status, explicit lifecycle precedence, and worktree-local
validation. The repo-wide doc-authority check is therefore a candidate check,
not a report about some other checkout.
