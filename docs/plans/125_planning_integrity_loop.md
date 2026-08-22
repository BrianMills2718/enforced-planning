# Plan #125: Planning Integrity Loop

**Status:** In Progress — design accepted; semantic admission implementation ready
**Type:** cross-repository shared-contract implementation
**Priority:** Critical
**phase_ref:** "Agentic Engineering first external consumer"
**goal_ref:** "enforce-plan-completeness-alignment-and-adaptation"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** pilot
**Planning integrity contract:** 1.0.0
**Blocked By:** #123
**Blocks:** substantive first-anchor implementation under Agentic Engineering Gate 2

---

## Decision

Adopt a portable Planning Integrity contract in Enforced Planning and make it
the deterministic admission prerequisite for selected repositories. Reuse the
existing plan validator, plan-start gate, work graph, selected-outcome
admission, progress receipts, course-correction decisions, and AES projection
seams. Do not build another planner, outcome engine, feedback store, or
documentation authority.

Company Planning remains an authoring and reasoning methodology. Enforced
Planning owns the portable typed contract and mechanical admission. AES owns
consumer-facing observation, evidence joining, variance, and policy feedback.
Project Meta continues to own portfolio ordering and project identity.

The first consumer will be AES itself through an installed-package proof. The
first valuable project reboot then uses the same contract; current portfolio
selection makes WhyGame provisional and does not authorize product work in this
plan.

## Gap

The canonical operating model already requires outcome-first planning,
epistemic classification, proportional checks, and course reassessment. The
runtime surfaces are disconnected:

- `plan_validation.py` hard-fails only gap, research, acceptance, documentation,
  and ADR omissions;
- user outcome, canonical behavior, critical-path class, and capability
  adoption remain warnings;
- the plan-start gate checks graph readiness but not semantic plan integrity;
- the installer derives consumer configuration, plan scaffolds, and worktree
  entrypoints from canonical templates, so root-only changes would create a
  false installed-consumer proof;
- outcome continuation can enforce selected progress, but a selected outcome
  is not proof that the owning plan classified uncertainty or defined when to
  revise itself; and
- AES has no joined planning-integrity evidence for its generated current,
  target, variance, and plan reading surface.

Consequential work can therefore be mechanically claimed and on-graph while
its plan remains semantically incomplete.

## User Outcome

Brian can delegate a consequential project outcome to coding agents and see
that every material part is either planned, conditionally planned, bounded for
exploration, blocked, awaiting his decision, or deliberately deferred; agents
remain aligned to the accepted revision, change reversible tactics when
evidence warrants, and require a visible plan revision when assumptions,
scope, or acceptance change materially.

## Canonical Behavioral Example

**Starting state:** A governed repository opts into Planning Integrity 1.0.0
for new plans. One proposed plan names a useful outcome and acceptance test but
omits its epistemic frontier and reassessment contract. A second plan includes
one fully specified implementation row and one bounded exploration row with a
question, probe, stopping rule, possible decisions, and downstream update.

**Action:** A coding agent attempts to open a coordinated implementation lane
from each plan, then records evidence that fires the exploratory row's declared
reassessment trigger.

**Expected result:** The incomplete plan is rejected before claim, branch,
worktree, or tracker mutation. The complete plan produces a revision-bound
`PASS` receipt and may start. When its trigger fires, existing outcome
continuation returns `course_correction_required`; reversible in-scope tactics
remain autonomous, while a material target or contract change requires a new
plan digest. AES renders the outcome, plan revision, frontier, observed state,
variance, and next decision without conversation context.

**Failure signal:** A missing frontier passes; a malformed checker reports
compliance; an old receipt validates changed plan bytes; exploratory work must
invent a result before it can start; an agent can omit the configured gate; a
minor tactic change creates approval ceremony; or AES treats generated output
as normative authority.

## Non-Goals

- Proving that a plan or tactic is globally optimal.
- Using an LLM judgment as a hard plan-admission authority.
- Replacing Company Planning, Project Meta, the work graph, outcome
  continuation, or the ecosystem feedback stream.
- Enforcing Planning Integrity fleet-wide in this slice.
- Selecting or implementing a WhyGame or other portfolio product feature.
- Adding a dashboard, generalized orchestration, or automatic policy
  promotion/demotion.
- Retroactively rewriting accepted historical plans.

## Landscape And Prior Art

**Disposition: inline.** The relevant alternatives are existing ecosystem
owners rather than an external build-versus-buy choice.

| Alternative | Consequence | Disposition |
|---|---|---|
| Add more prose to Company Planning | Improves authoring guidance but leaves start and execution admission unchanged. | Rejected as insufficient. |
| Build a new AES planner and drift engine | Duplicates mature Enforced Planning seams and creates conflicting authority. | Rejected. |
| Hard-block every historical plan immediately | Creates migration noise and false blocks before consumer calibration. | Rejected. |
| Add a versioned opt-in contract with an explicit per-repository adoption floor | Makes new plans enforceable while preserving old evidence and rollback. | Adopted. |

**Alternatives:** The table compares the material enforcement approaches.

**Project implications:** Enforced Planning gains one contract parser, strict
result, opt-in configuration, and start-gate join. AES consumes the result and
projects it. The first external project enables the contract from its first
plan. No Company Planning or Project Meta runtime dependency is added.

## Capability Adoption

**Disposition: extend.** Extend Enforced Planning's canonical
`plan_validation`, `plan_readiness`, and outcome-continuation seams. AES is the
intended first consumer. Proof requires an installed AES path plus both-sign
admission controls; isolated parser tests prove only implementation.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| semantic plan-integrity validation | exact plan bytes + repository adoption config | typed pass/fail/not-applicable result with findings and frontier | Enforced Planning plan validator | plan-start admission and AES evidence join |
| pre-mutation planning admission | qualified plan identity + exact integrity result + graph readiness | allow or visible denial before coordination state changes | Enforced Planning plan-start gate | sanctioned worktree/session entrypoints |
| adaptive execution linkage | accepted plan revision + selected outcome progress | continue, course correction, restart, or terminal decision | existing Enforced Planning outcome continuation | coding-agent lifecycle and human progress surface |
| four-layer planning projection | normative plan fields + immutable integrity/progress evidence | generated current, target, variance, and plan topic | AES projection | Brian and fresh coding agents |

## Requirements And Invariants

1. **Total classification, not total prediction.** Every material planned area
   has exactly one supported frontier state:
   `fully_specifiable_now`, `conditional`, `exploration_required`,
   `enabling_work_blocked`, `human_decision_required`, or
   `deliberately_deferred`.
2. **Executable uncertainty.** Every non-fully-specified row names the
   condition, question, blocker, decision, or resume trigger and the authority
   surface updated when it resolves.
3. **Outcome preservation.** Consequential plans retain a user outcome,
   canonical behavioral example, critical-path classification, capability
   adoption disposition, acceptance, and reassessment contract.
4. **Exact evidence.** A result binds repository-relative plan identity,
   content digest, contract version, validator revision, mode, findings, and
   frontier summary. Changed bytes invalidate the receipt.
5. **Bounded completeness claim.** A structural `PASS` proves that every
   declared frontier row is classified and executable; it does not prove that
   an author named every material area or chose an optimal plan. The typed
   result and AES projection carry this non-claim explicitly.
6. **Fail loud.** Missing, malformed, unreadable, unsupported-version, or
   checker-failure states never become `PASS`.
7. **Admission before mutation.** In enforcement mode, coordinated and release
   lane creation validates plan and configuration bytes from the exact Git
   start revision before claim, branch, worktree, or tracker mutation. Direct
   plan-bound claim acquisition reuses the same gate, so omitting Make is not a
   bypass. Explicitly unplanned light work retains its current bounded
   exception.
8. **Incremental adoption.** Repository configuration declares
   `off | observe | enforce`, contract version, and the first plan number to
   which enforcement applies. Historical lower-numbered plans remain visible
   and non-claimable as proof for the new contract.
9. **Adaptive execution.** Existing outcome continuation remains the runtime
   decision owner. Planning Integrity supplies revision and reassessment
   obligations; it does not duplicate continuation state.
10. **One human surface.** AES projects authoritative plan fields plus generated
   current evidence and variance; generated output remains disposable.

## Boundaries And Contracts

| Boundary | Owns | Does not own |
|---|---|---|
| Company Planning | authoring method and planning vocabulary | runtime admission or personal portfolio authority |
| Enforced Planning `PlanIntegrityResultV1` | structural semantic validation, exact plan digest, findings, frontier projection | truth of product judgments or global optimality |
| Enforced Planning plan-start gate | configuration, exact result join, allow/deny before mutation | portfolio priority or target selection |
| Existing outcome continuation | progress, stall, course-correction, restart and terminal decisions | plan authorship or documentation authority |
| AES | installed consumer evidence join and four-layer reading projection | claims, worktrees, plan parsing, or portfolio ownership |
| Project Meta | stable repository/project identity and portfolio sequence | repo-local plan validity |

`PlanIntegrityResultV1` must expose:

- `schema_version`, `contract_version`, and `disposition` (`pass | fail |
  not_applicable`);
- logical repository/plan identity and repo-relative plan path;
- plan SHA-256 and validator source revision;
- configured mode and adoption floor;
- typed blocking findings and nonblocking warnings;
- parsed frontier rows; and
- the exact user outcome, canonical example, critical-path class, capability
  disposition, reassessment summary, and structural-coverage non-claim needed
  by AES projection.

`PASS` means **declared planning-integrity structure passes**. It is not a
claim that the plan is globally optimal or that an omitted material area was
mechanically detected. Human/agent authorship review and subsequent observed
variance remain responsible for challenging frontier coverage.

Unknown fields reject at the enforcement boundary. Human Markdown is rendered
from the typed result rather than parsed downstream.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| Planning-integrity schema and parser | fully_specifiable_now | Deterministic Markdown contract, Pydantic result, exact-byte and validator-source digests, findings, and an explicit structural-coverage non-claim | Complete when positive, malformed, unfilled-template, and byte-distinct fixtures discriminate | `plan_validation.py`, config reference, installed wrapper |
| Start-gate integration | fully_specifiable_now | Configured coordinated/release start and direct plan-bound claim acquisition must validate the plan/config bytes at the exact Git start revision before mutation | Complete when incomplete committed bytes plus a complete dirty edit still leave no claim, branch, worktree, or tracker | plan readiness, claim acquisition, and Make/install surfaces |
| Runtime course-correction join | conditional | Reuse selected outcome continuation; add only the plan revision/reassessment evidence it demonstrably lacks | Extend only if focused integration shows the current receipt cannot carry the required reference | Plan 125 design or existing outcome contract owner |
| AES four-layer planning projection | fully_specifiable_now | Installed result joins generated current/variance/topic output without becoming normative | Complete when delete/regenerate preserves normative bytes and exact evidence refs | AES topic and proof receipt |
| First valuable project anchor | exploration_required | Portfolio audit selects by personal value, lineage, learning value, and bounded effort; WhyGame is provisional | Stop after one lineage/value probe can select or reject the candidate | Project Meta anchor decision and target repo plan |
| Fleet defaults and automatic promotion | deliberately_deferred | No rollout or auto-promotion from one consumer | Resume after a second independent consumer and measured false-block/false-allow evidence | Enforced Planning roadmap and AES release manifest |

## Reassessment Contract

- **Triggers:** two consecutive increments without outcome progress; about 45
  minutes without a visible or decision-changing result; a violated plan
  assumption; changed target kind/scope/count/depth; unexpected consumer
  incompatibility; or verification effort approaching implementation effort
  before the first authentic observation.
- **Autonomous action:** preserve useful work and switch reversible, in-scope
  tactics; update the current receipt and smallest affected authority.
- **Plan revision required:** material outcome, acceptance, shared contract,
  dependency graph, frontier state, or write-scope change.
- **Human decision required:** a material scope fork, external authority,
  irreversible shared action, or spend boundary not already authorized.
- **Stopping rule:** after the focused both-sign controls and one installed AES
  consumer prove the exact seam, stop framework expansion and proceed to the
  selected project anchor.

## Plan

**Critical-path classification: vertical.** The visible vertical is an agent
being denied on an incomplete plan, admitted on a complete plan, and shown a
revision-bound human-readable planning state through installed AES.

1. **PI-01 — accepted design and graph.** Freeze this contract, its work graph,
   current roadmap boundary, and focused checks.
2. **PI-02 — Enforced Planning semantic admission.** Implement the typed
   contract, config, parser, strict results, exact-start-revision Make/start
   admission, direct-claim admission, installation propagation, and both-sign
   mutation-order tests.
3. **PI-03 — AES installed integration.** Consume a pinned Enforced Planning
   candidate, retain an immutable result, and project the planning fields into
   AES's existing topic without new authority.
4. Stop. The selected anchor repository owns its own exploratory lineage/value
   plan and subsequent useful product vertical.

## Acceptance Criteria

1. A configured incomplete consequential plan deterministically returns
   `fail`, names exact findings, exits nonzero, and creates no claim, branch,
   worktree, or tracker.
2. A configured complete plan with one exploration row returns `pass`, retains
   that row's question/trigger/downstream update, and may proceed through the
   existing start gate.
3. Missing or malformed configuration, unsupported contract version, malformed
   frontier rows, unreadable plan bytes, and checker failure fail visibly in
   enforcement mode.
4. Plans below the explicit repository adoption floor retain compatibility;
   new plans at or above it cannot omit the contract.
5. Existing unplanned-light behavior and outcome-continuation decisions remain
   unchanged unless the new contract is selected.
6. An installed AES consumer—not a source-path import—joins the exact result to
   its existing generated documentation projection and preserves normative
   bytes across delete/regenerate.
7. Source and installed wrappers use the same implementation; the installer is
   idempotent for the changed files, and consumer configuration, plan, and
   worktree behavior comes from the actual canonical template owners.
8. The implementation does not modify Company Planning, Project Meta portfolio
   authority, WhyGame product source, fleet defaults, or external systems.
9. Every passing result and AES readout says that structural conformance does
   not establish omitted-area coverage or plan optimality.
10. Dirty complete bytes cannot admit an incomplete Git start revision, and a
    direct plan-bound claim cannot bypass configured enforcement.

## Required Tests

- focused parser/result tests: complete, omitted, malformed state, missing
  trigger, unsupported version, and stale digest;
- configuration tests for `off`, `observe`, `enforce`, malformed values, and
  adoption-floor compatibility;
- start-gate mutation-order test proving semantic denial precedes claim and
  worktree creation;
- direct-claim and dirty-working-tree negative controls proving the configured
  gate cannot be omitted and binds the exact start revision;
- regression tests for unplanned light work, historical plan compatibility,
  and existing outcome admission;
- installer idempotence and installed-wrapper parity for changed files; and
- one AES installed-consumer proof with delete/regenerate comparison.

Do not run a fleet suite or comparative benchmark before the installed AES
boundary works. The terminal Enforced Planning self-test is required because
the installer/shared gate boundary changes.

## Files Affected

- `enforced_planning/plan_validation.py`
- `enforced_planning/plan_readiness.py`
- `enforced_planning/coordination_claims.py`
- `scripts/check_plan_readiness.py`
- `scripts/check_coordination_claims.py`
- `scripts/validate_plan.py`
- `scripts/install_governed_repo.py`
- `Makefile`
- `meta-process.yaml`
- `templates/Makefile.worktree.block.template`
- `templates/meta-process.yaml.example`
- `templates/meta-process.future.yaml.example`
- `templates/plan.md.template`
- `scripts/relationships.yaml`
- `docs/reference/CONFIG_REFERENCE.md`
- `tests/test_validate_plan.py`
- `tests/test_plan_readiness.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_install_governed_repo.py`
- `ROADMAP.md`
- `docs/plans/CLAUDE.md`
- `docs/plans/125_planning_integrity_loop.md`
- `docs/plans/125_planning_integrity_loop_work_graph.json`

AES-owned paths are recorded in its own claimed lane after PI-02 is accepted.

## References Reviewed

- `PLANNING_OPERATING_MODEL.md`
- `EXECUTION_BRIEF.md`
- `GETTING_STARTED.md`
- `adr/0009-doc-authority-governance-and-enforcement.md`
- `enforced_planning/plan_validation.py`
- `enforced_planning/plan_readiness.py`
- `enforced_planning/outcome_continuation.py`
- `enforced_planning/governed_delivery.py`
- `docs/plans/113_governed_delivery_authentic_vertical.md`
- `docs/plans/123_source_outcome_admission_activation.md`
- `docs/plans/124_qualitative_coding_outcome_admission_pilot.md`
- `docs/reference/CONFIG_REFERENCE.md`
- `docs/reference/DOC_AUTHORITY_SCHEMA.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `scripts/relationships.yaml`
- `Makefile`
- `../agentic-engineering-system/ROADMAP.md`
- `../agentic-engineering-system/docs/architecture.md`

## Research

This is an extension of locally owned, already executed seams. Direct source,
focused tests, accepted receipts, and the current user-approved AES roadmap are
the relevant evidence. External research cannot determine the repository's
mutation ordering or contract compatibility and is therefore exempt from this
bounded integration decision.

## Uncertainty Register

- The existing outcome-continuation receipt may already carry every runtime
  reference needed by Planning Integrity; PI-02 must probe it before adding a
  field.
- AES's current topic schema may accept the result as existing evidence without
  a model change; PI-03 must prefer that path if exact joining remains honest.
- The portfolio audit may select a project other than WhyGame; this plan does
  not encode that product decision.

## Rollback And Non-Claims

Setting repository planning-integrity mode to `off` is the configuration-only
rollback. Reverting the implementation commit restores the previous validator
and start gate. Receipts remain evidence and never grant authority.

Completion proves one portable planning-integrity vertical and AES self-use. It
does not prove plan optimality, fleet adoption, automatic semantic judgment,
WhyGame value, or stable `1.0` guarantees.
