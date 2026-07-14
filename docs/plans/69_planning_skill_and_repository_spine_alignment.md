# Plan #69: Planning Skill and Repository Spine Alignment

**Status:** Complete (report-only consumer pilot; hard enforcement deferred)
**Type:** implementation + report-only consumer pilot
**Priority:** Critical
**phase_ref:** "portable documentation governance"
**goal_ref:** "ecosystem-context-integrity"
**adrs_referenced:** []
**research_citations:** ["agent_memory:sm-71392a4111a9"]
**Blocked By:** None
**Blocks:** [future] calibrated relationship-context rollout beyond the first consumer

`trace_evaluable: false # deterministic policy, skill, and repository-governance work`

---

## Mission

Align the canonical planning operating model, the `design-plan` and
`project-roadmapping` skills, and ecosystem skill policy around one coherent
repository-spine architecture. Prove the architecture in `inside-success` as a
report-only pilot before proposing any hard documentation or change-impact gate.

The user's governing success criterion is:

> the roadmap should be kind of the spine for all files in the repo whether
> documentation or code

The intended implementation distinguishes four complementary authorities:

1. `roadmap/README.md` is the human review front door.
2. `scripts/relationships.yaml` records reviewed semantic relationships and
   document justification/lifecycle declarations.
3. source docstrings explain local why and contract intent.
4. generated maps and the docstring wiki are disposable, non-authoritative
   projections.

---

## Gap

**Current:** The planning skills overlap in routing and artifact ownership,
`design-plan` can imply implementation after a planning request, local policy is
mixed with generic method, and the existing relationship-context framework has
not been exercised as the repository-wide code-and-documentation spine of a
consumer project.

**Target:** Planning requests preserve user mutation authority, skill routing is
deterministic, canonical artifacts have one owner, proportional profiles and
conditional overlays replace universal ceremony, and `inside-success` can be
navigated from outcome to code, tests, evidence, and licensed claim through a
report-only relationship graph.

**Why:** Without one control architecture, agents can create duplicate plans,
conflicting status surfaces, and documentation whose lifecycle and downstream
review obligations are unclear.

---

## References Reviewed

- `PLANNING_OPERATING_MODEL.md` — canonical planning hierarchy.
- `docs/plans/63_relationship_context_and_docstring_wiki.md` — static
  relationship graph and generated-wiki contract.
- `docs/plans/64_requirement_linked_test_relationships.md` — report-only test
  relationship semantics.
- `docs/plans/65_document_archive_lifecycle_report.md` — explicit document
  lifecycle reporting.
- `docs/plans/66_semantic_document_lifecycle_assessment.md` — lifecycle
  eligibility design and enforcement boundary.
- `docs/designs/RELATIONSHIP_CONTEXT_CONTRACT.md` — portable registry contract.
- `~/projects/.agents/skills/design-plan/` — current bounded-design procedure.
- `~/projects/.agents/skills/project-roadmapping/` — current project-roadmap
  procedure and prompt-only evaluations.
- `~/projects/project-meta/docs/ops/SKILL_POLICY.md` — canonical skill policy.
- `~/projects/project-meta/docs/ops/CLIENT_CAPABILITY_MATRIX.md` — client
  metadata portability limits.
- `~/projects/inside-success/README.md`, `plan/ROADMAP.md`,
  `plan/DOCUMENTATION_AUTHORITY_MAP.md`, and
  `plan/DOCUMENTATION_REVIEW_INDEX.md` — current consumer navigation and
  documentation authorities.
- User-supplied external skill review — routing, authority, proportionality,
  evidence, trust-boundary, and evaluation recommendations.
- Memory context: `agent-memory recall 'planning skill alignment roadmap
  relationships yaml documentation spine' --project enforced-planning` — one
  relevant installer import-closure finding; two unrelated operational records.

## Research Basis For This Slice

No external research is required. This is reconciliation of accepted local
methodology, current client behavior, a user-supplied review, and existing
portable governance tooling.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Request authority, routing, and artifact ownership | Deductive / plan-first | Conflicts and desired precedence are inspectable in current policy. | Define one canonical rule, add negative assertions, and lint the resulting skills. |
| Relationship and lifecycle compiler behavior | Deductive / plan-first | Existing typed parsers and deterministic reports define the contract. | Reuse the framework and prove import closure, determinism, and both-sign fixtures. |
| Inside Success semantic edges | Hybrid | File coverage is deterministic, but useful edge selection and review obligations require judgment. | Start report-only, review high-value capability slices, and measure false positives before enforcement. |
| Future hard-gate eligibility | Exploratory / ladder | One consumer cannot establish fleet-wide precision. | Produce a readout and explicit promotion criteria; do not enable a gate in this plan. |

**Exploratory readout:** The pilot must show useful outcome-to-implementation
navigation and correct positive/negative impact obligations without invented or
orphan relationships.

**Step-down path:** Every aggregate finding must identify the exact document,
source file/symbol, test, evidence record, or missing edge that caused it.

---

## Multi-Repo Coordination

| Repo | Files Modified | Merge Strategy |
|------|---------------|----------------|
| `enforced-planning` | operating model and this plan/index | Merge first; it owns the method consumed by the skills and pilot. |
| `.agents` | `design-plan`, `project-roadmapping`, and planning-skill eval fixtures | Merge after the operating-model slice. |
| `inside-success` | root entrypoint, `roadmap/**`, bounded relationship tooling/registry, and focused meta-tests | Merge after the skill contract is stable. |
| `project-meta` | skill policy/registry, enforcement matrix, and generated policy wiki if reconciliation requires changes | Merge last, after the pilot identifies the smallest policy delta. |

**Coordination notes:** Each repository uses a dedicated worktree and branch.
Verified slices are committed and pushed independently. The active
`inside-success` demo/recovery lane owns `Makefile`, `plan/STATUS.md`,
`plan/CONCERNS.md`, `plan/second_brain/**`, and `tests/second_brain/**`; this plan
must not modify those paths.

**Write-claim footprint:** Four scoped claims reserve only the files named in
the table above. Existing unrelated worktree changes remain untouched.

---

## Files Affected

- `PLANNING_OPERATING_MODEL.md` (modify)
- `docs/plans/CLAUDE.md` (modify)
- `docs/plans/69_planning_skill_and_repository_spine_alignment.md` (create)
- cross-repository files named in Multi-Repo Coordination (modified only in
  their separately claimed worktrees)

---

## Risk-Ordered Slices

| Slice | Outcome | Status |
|---|---|---|
| 1 | Canonical action boundary, routing precedence, and artifact ownership | Complete |
| 2 | Relationship graph, roadmap spine, docstring, and generated-projection roles aligned | Complete |
| 3 | Skill profiles/overlays and project-specific policy separation | Complete |
| 4 | Planning-only and routing evaluations with negative mutation assertions | Complete with automatic-trigger evidence invalidated, not scored |
| 5 | `inside-success` report-only repository-spine pilot | Complete |
| 6 | Held-out evaluation, policy reconciliation, and enforcement disposition | Complete; hard enforcement remains off |

## Acceptance Criteria

| Criterion | Evidence | Pass condition | Result |
|---|---|---|---|
| AC-1 action boundary | source + negative test | A planning/review-only request causes zero writes, installs, commits, pushes, or external mutations. | Pass at source, fixtures, and explicit fresh-client output; automatic-trigger proof remains limited because the available harness failed its positive control and the explicit run used a read-only sandbox. |
| AC-2 deterministic routing | source + routing tests | One bounded outcome routes to `design-plan`; multiple outcomes or a capability critical path route to `project-roadmapping`; a combined request roadmaps first and designs only the next one or two goals. | Pass for explicit fresh-client bounded and multi-outcome cases; automatic-trigger result is invalid/unscored. |
| AC-3 single artifact ownership | source review | Roadmap, capability graph, bounded design packet, project concerns, project evidence, relationship registry, docstrings, and generated projections each have one explicit authority. | Pass in the operating model and both compact skill routers. |
| AC-4 proportionality | fixtures + review | Small and standard profiles plus conditional overlays avoid irrelevant UI, LLM, Pydantic, workbench, or master-roadmap ceremony. | Pass; the bounded candidate output removed the baseline's project-graph and universal audit ceremony, and non-Python fixtures reject Pydantic assumptions. |
| AC-5 repository navigation | observed deterministic report | In `inside-success`, a reviewer can traverse an outcome to capability, implementation, tests, evidence, and claim or an explicit unimplemented/evidence gap. | Pass through `roadmap/PROJECT_MAP.md` and the RS-1 traceable wedge. |
| AC-6 impact precision | positive + negative tests | A representative high-value code change triggers its declared review obligations; an unrelated diff does not. | Pass: governed documentation change produced two expected obligations; unrelated wiki change produced zero. |
| AC-7 document lifecycle | schema-validated registry + report | Each reviewed narrative document has a role, justification, lifecycle source, and resolvable anchor; generated pages are excluded as authorities. | Pass for ten reviewed declarations; 1,535 undeclared legacy documents remain explicit migration debt. |
| AC-8 wiki contract | deterministic test/report | Every tracked source file is represented without one hand-authored YAML row per file; the generated docstring wiki is exhaustive, reproducible, and labeled non-authoritative. | Pass: 2,060/2,060 tracked artifacts and byte-identical 1,301,492-byte generated projections. |
| AC-9 plan lifecycle | source review | Completed plans remain immutable evidence; current truth points through explicit successors rather than rewriting history. | Pass through the existing lifecycle compiler and completed-plan negative controls; no completed plan was rewritten by this work. |
| AC-10 portable closure | import and CLI tests | The consumer-installed relationship tooling includes its full internal import closure and runs without importing the framework checkout implicitly. | Pass: six of six consumer-local CLIs run under isolated Python with empty `PYTHONPATH`. |
| AC-11 honest enforcement disposition | pilot report + coverage review | Hard enforcement remains off unless both-sign evidence demonstrates adequate precision for the exact proposed gate. | Pass: the pilot and ecosystem policy both remain report-only. |

## Stop Conditions

1. Do not move implementation code under `roadmap/`; the roadmap maps code
   ownership and capability topology but does not replace the repository's
   runtime/module structure.
2. Do not create a second canonical status, concern, evidence, or documentation
   inventory surface in `inside-success`.
3. Do not require one manual relationship row per tracked file.
4. Do not enable a hook, Make gate, merge gate, or lifecycle mutation in the
   report-only pilot.
5. Stop and reconcile if an existing active claim begins owning any path in this
   plan's footprint.

## Verification Plan

- Markdown and link validation for every changed documentation surface.
- `.agents` structural lint, policy lint, sync check, and focused evaluation
  assertions for routing, proportionality, repository trust, and zero mutation.
- `inside-success` focused parser/compiler/impact/docstring-wiki tests using both
  positive and negative fixtures.
- Byte-for-byte deterministic report replay and workspace-neutral output check.
- Import-closure test from the consumer worktree with framework paths removed
  from `PYTHONPATH`.
- Final diff review against all four write claims and active-lane registry.

## Progress Log

- 2026-07-14: Claimed four non-overlapping worktree footprints and confirmed
  current canonical branches.
- 2026-07-14: Reviewed the operating model, both skills and references, skill
  policy/client matrix, relationship/lifecycle plans, and current Inside Success
  navigation authorities.
- 2026-07-14: Classified the pilot as report-only and recorded the prior
  portable-installer import-closure failure as AC-10.
- 2026-07-14: Added the canonical request-mode boundary, deterministic skill
  routing, artifact ownership table, complementary human/machine spine,
  proportional profiles/overlays, multidimensional capability status, and
  claim-specific evidence contract to the operating model. Focused plan,
  documentation, link, and dependency checks pass; legacy dependency warnings
  remain pre-existing.
- 2026-07-14: Rewrote `design-plan` and `project-roadmapping` as compact
  routers/contracts with Small/Standard profiles, conditional overlays,
  repository trust boundaries, optional-skill fallbacks, and single-owner
  references. Added fixture-backed routing, mutation, proportionality, runtime,
  exploratory, migration, and repository-spine evaluations. Published as
  agent-skills commits `9c5b12a` and `c9fac60`.
- 2026-07-14: Invalidated the Claude trigger run after all positive controls
  produced zero invocations under both baseline and candidate. Fresh explicit
  Codex runs routed the bounded cross-repository case to `design-plan` and the
  one-repository multi-outcome case to `project-roadmapping`; the candidate
  removed baseline project-level ceremony from the bounded case. No automatic
  trigger improvement is claimed.
- 2026-07-14: Published the `inside-success` pilot at `5ab5c5d` with clickable
  native-authority navigation completed at `1df6925`. The root README now
  routes to `roadmap/README.md`; roadmap-owned narratives live in one directory
  while code/tests remain native. The pilot inventories 2,060 tracked
  artifacts, links 25/25 scoped tests with 2/2 declared requirements evidenced,
  passes 14 focused tests, and closes 13 staged obligations through nine
  co-updates plus four exact reviewed-unchanged dispositions.
- 2026-07-14: Published project-meta policy reconciliation at `1ce58912`.
  `goal-mapping` registry drift is replaced by `project-roadmapping`, the
  generated Agent Guide now preserves action mode and deterministic routing,
  22 focused policy tests pass, and the pre-existing coherence baseline improves
  from nine blockers/nine warnings to eight/eight without broad unrelated
  cleanup.

## Follow-On Concerns (Not Completion Blockers)

- `inside-success` has 1,535 undeclared legacy narrative documents and 625
  explicit source-summary diagnostics. These are a review queue, not grounds
  for a bulk semantic rewrite or hard gate.
- The existing Inside Success documentation-disposition ledger is already stale
  on untouched `main` (1,497 declared versus 1,696 current inventory records).
  The pilot reports but does not take ownership of that cleanup lane.
- The relationship-only governed-repo installer does not yet include the newer
  archive-lifecycle module/CLI. The pilot installed the canonical pair
  explicitly; the installer gap is recorded in `project-meta/policy_friction.md`.
- The Claude trigger harness could not observe any positive skill invocation.
  Explicit fresh-client output supports routing behavior, but automatic trigger
  improvement remains unlicensed until the harness has a passing positive
  control.
- Project-meta coherence still has eight unrelated legacy registry blockers and
  eight warnings after the directly relevant `goal-mapping`/
  `project-roadmapping` drift was fixed.
- Existing A-F evidence grades are widespread policy. Claim-specific evidence
  metadata should become canonical incrementally, with grades retained as a
  derived compatibility view until consumers and gates migrate.
- Static relationships can express topology and review obligations, not live
  deployment or coordination state.
