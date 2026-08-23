# Plan #125: Planning Integrity Loop

**Status:** In Progress — PI-02, PI-02B, and PI-02C accepted; PI-02F ready through its source-scoped v7 custody-bootstrap phase; PI-02E waits for that repair; PI-02D waits for successor custody
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
**Blocks:** no consumer-project work; supplies one measured control to AES and project rewrites

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

The first provider proof is the authentic installed Make lifecycle in this
repository. AES then consumes the result through a pinned installed-package
proof. A valuable project reboot may begin in parallel and expose new control
defects; it does not wait for AES or Plan 125 to become a complete platform.
Current portfolio selection makes WhyGame provisional and does not authorize
product work in this plan.

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
   lane creation resolves the canonical default-integration tip to one full Git
   commit once, validates plan,
   configuration, work graph, and approval bytes at that commit, retains it in
   the claim, and passes the
   same immutable revision through claim, branch, worktree, and session
   creation. Existing branch or worktree identities must match it. Direct
   plan-bound claim acquisition reuses the same custody checks, so omitting
   Make or supplying an older passing commit is not a bypass. A retained
   non-tip revision is allowed only for an already-retained lane through the
   session-resume/recovery lifecycle; `--resume` alone never authorizes a new
   non-tip claim. Explicitly unplanned light work retains its current bounded
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
11. **Observation is evidence.** `observe` preserves nonblocking behavior but
   exposes the complete typed Planning Integrity result and findings through
   the start boundary; a silent allow is not observation or feedback.
12. **Unambiguous parsing and installation.** Duplicate governed headings or
   governed fields reject across supported CommonMark ATX heading and bold-field
   dialects, the canonical plan-template field form must parse, configuration
   paths must be portable
   repository-relative paths, and every installed profile includes the full
   import dependency closure for its advertised entrypoint.
13. **Ownership-aware rollback.** The start transaction never overwrites a
   pre-existing claim slot and deletes only the worktree, branch, claim, and
   tracker artifacts created by that invocation. Branch ownership comes from
   the worktree helper's creation receipt, not a pre-creation probe. A failed
   retry or intervening branch creator cannot lose prior state.
14. **Truthful staged activation and migration.** A pre-worktree claim is an
   exact revision-bound reservation and intentionally has no tracker. Worktree
   creation may tolerate only that missing activation field; session start must
   then validate the execution identity and add the tracker. An already-running
   legacy claim with no recorded start revision remains readable but cannot be
   auto-promoted to schema v4 by inventing historical custody.

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
- parsed frontier rows and authored acceptance criteria; and
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
| Start-gate integration and revision custody | fully_specifiable_now | Configured coordinated/release start resolves one full commit once, validates plan/config there, retains it in the claim, and passes it through claim, worktree, and session creation; direct claims and pre-existing branch/worktree identities use the same rule | Complete when dirty bytes, an older passing caller-supplied commit, an existing mismatched branch/worktree, and symbolic-HEAD movement all fail without claiming or executing the wrong revision | plan readiness, claim acquisition, session lifecycle, Make/install surfaces |
| Observe-mode feedback | fully_specifiable_now | Nonblocking observation returns the typed integrity result and findings through the operator-visible start result | Complete when an incomplete observed plan is allowed but its findings are visible in the real CLI output | readiness result and installed CLI |
| Parser and installation fail-loud edges | fully_specifiable_now | Duplicate governed headings/fields and absolute or traversing plan paths reject; worktree-only install carries the advertised readiness CLI's transitive imports | Complete when the corrupt fixtures reject and a clean worktree-only installed readiness CLI executes | parser, installer and focused boundary tests |
| Operator documentation coupling | fully_specifiable_now | The config reference describes the contract, while the canonical worktree operator guide must name the new exact-revision prerequisite at the real claim/start entrypoint | Complete when the coupling check sees the guide updated in its separately claimed path | operator guide and relationship coupling |
| Runtime course-correction join | fully_specifiable_now | Selection now validates the qualified plan at the immutable outcome baseline; authentic PI-02E dogfood found that the prewrite bootstrap exception still infers lifecycle purpose only from path shape and can admit a qualified planned claim before selection | Complete when an exact `UNPLANNED` bootstrap claim remains admitted, the same safe paths on a qualified planned claim require selection, and the retried PI-02E both-sign proof discriminates | outcome bootstrap identity, prewrite admission, and focused tests |
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

### Course-correction receipt — operator documentation coupling

The PI-02 commit hook reported that changing
`enforced_planning/coordination_claims.py` requires an aligned update to
`docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`. The selected outcome's
immutable allowed scope did not include that guide. Acknowledging the warning
would leave the operator path stale, while expanding the existing claim would
invalidate its exact outcome-selection binding. Plan 125 therefore adds the
bounded `pi-02d-sync-operator-guide` work unit and makes AES depend on it. This
is a plan revision caused by an observed write-scope and dependency-graph
change, exactly as the reassessment contract requires.

### Course-correction receipt — runtime plan-revision binding

The PI-02 start gate proves only that a lane began from a conforming revision.
A direct probe of `OutcomeSelectionBindingV1` and `OutcomeContractV1` found that
continuation already immutably binds `claim_plan_ref`, the outcome-contract
digest, and `baseline_revision`, but does not require the qualified plan at that
baseline revision to pass Planning Integrity. Therefore start admission alone
cannot support the broader claim that later continuation remains attached to
the accepted plan revision. Plan 125 adds `pi-02c-bind-runtime-plan`: selection
will reuse the existing contract digest and exact baseline revision, revalidate
Planning Integrity there, and deny stale or incomplete baselines. No new
planner, receipt lineage, or continuation engine is introduced.

### Course-correction receipt — adversarial revision-custody review

Independent boundary review rejected the first PI-02 candidate. It proved that
a caller could validate an older passing `start_point` while claiming a
different current branch/worktree, because the accepted revision was neither
retained in the claim nor threaded through session upsert. The same review
found a worktree-only install whose advertised readiness CLI lacked transitive
imports, duplicate governed headings that silently selected the first section,
an absolute `plans_dir` silently reinterpreted as repository-relative, and an
`observe` path that allowed without reporting findings. These are not deferred
hardening: each breaks the exact admission or feedback claim. PI-02 therefore
returns to `ready`, expands its selected write scope to the lifecycle owner and
focused tests, and requires an authentic installed entrypoint plus both-sign
revision-custody controls before acceptance.

The review also proved that the start transaction's unconditional cleanup can
delete a pre-existing branch after session-upsert failure, while direct claim
retry can update an existing claim and later rollback can unlink that prior
state. PI-02 therefore makes claim creation explicitly new-slot-only for this
entrypoint and makes rollback conditional on artifacts owned by the exact
invocation.

A second adversarial pass found two subtler custody failures. First, cleanup
decided branch ownership from a pre-creation probe even though the worktree
helper later returned the authoritative `created_branch` fact; a branch
appearing between those events could be deleted. Second, a running schema-v3
claim with a tracker but no retained revision could be rewritten as schema v4
using the caller's current revision, fabricating historical evidence. PI-02 now
drives rollback from the helper receipt and refuses that legacy promotion.

The authentic installed Make vertical then reproduced the maintenance bootstrap
failure directly: the pre-worktree reservation was classified weak for lacking
the tracker that session start creates. The lifecycle is now explicit. Claim
admission creates a revision-bound reservation without a tracker; worktree
creation accepts only that narrow staged omission; session activation supplies
the tracker or rolls the invocation-owned state back.

The provider commit hook then named two coupled operator surfaces rather than
silently treating code tests as documentation adoption:
`docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` for the claim/worktree
lifecycle and `GETTING_STARTED.md` for the installed first-success path. Both
remain in the separately claimed PI-02D unit; PI-02 acceptance records the
exact coupling rather than claiming those docs already changed.

### Course-correction receipt — selected-outcome work-unit transition

The first authentic PI-02D start from source main at
`0a6d9e28840ba15c4bb33920404ebe11ed51e7cd` passed Planning Integrity and
created the exact revision-bound claim and worktree, but configured
selected-outcome admission rejected session activation with
`outcome_admission_state_invalid`: the deliberately staged claim had no tracker
from which a selection could be resolved. Rollback removed the new branch,
worktree, and claim. The prior Plan 125 allocation remains active but is bound
to the closed PI-02 claim, so it cannot authorize the separately scoped PI-02D
unit.

This is an execution-graph omission, not evidence for weakening admission or
calling planned work unplanned. Independent review also proved that the
restricted bootstrap claim cannot become the successor lane: it is schema v3
with a tracker but no retained `start_revision`, and the accepted custody guard
correctly refuses to fabricate historical v4 evidence. The active v3 allocation
does not become invalid merely because its creating claim closed; its material
defect for PI-02D is that the immutable contract excludes both documentation
paths.

PI-02B therefore repairs only the circular activation boundary. An exact new
schema-v4 reservation may attach its tracker with an explicit
`selection_pending` result, never a selected `PASS`; heartbeat and prewrite
remain denied until allocation and selection exist. A narrowly scoped unplanned
maintenance lane is permitted only because the planned entrypoint itself is the
reproduced defect. After that repair, PI-02E uses the normal plan-bound path and
the existing disposition, allocation, and selection owners to park v3 and
select v4 on the exact live successor claim. PI-02D becomes ready only after
that transition is durably accepted. No automatic allocation, cross-claim
transfer engine, or unplanned documentation path is introduced.

### Acceptance receipt — staged selected activation

PI-02B landed through provider commit
`a79a9c09b436542c69e5b52c64aff85c43ed5c37` and merge
`daffdb123da4edbfd24286eb89d8278cec6bd1ac`; the authentic normal Make path
then exposed one remaining defaulting defect. The reservation stored the
human-readable session goal while session start derived its canonical slug.
The attach-only guard correctly stopped mutation, but treated those equivalent
representations as different. Follow-up commit
`e19f245f977e492c14d661f9ea47327f4b01ead7` and merge
`a05b9ede580d398fe178354fa027ebb5c96600f2` canonicalized that comparison
without weakening exact broader-goal, scope, work-unit, revision, or session
identity checks. Independent negative review changed the reserved name to a
different goal and observed denial before receipt, tracker, or claim mutation.

The repeated normal Make path created one schema-v4 claim whose retained start
revision and worktree HEAD both equal
`a05b9ede580d398fe178354fa027ebb5c96600f2`. Selection-pending receipt
`spact-33c0ac9a81d2440cb146813896eed2a6` records `defer`, the exact graph
digest, and `missing_tracker_path` as the sole staged health issue. After
tracker attachment, heartbeat receipt
`oadm-3fbfcfe2379f4901914febe7160b12b0` and prewrite receipt
`oadm-0dae756525014219a25fe8516815ed43` both deny with
`outcome_selection_required`; the prewrite resolution is `selection_missing`.
The no-change proof lane then closed through the sanctioned lifecycle.

The exercise also exposed a circular acceptance sentence: PI-02B required a
post-selection allow even though PI-02E, the owner of allocation and selection,
could not start until PI-02B was accepted. PI-02B now owns the pre-selection
denials it implements. PI-02E owns the post-selection heartbeat, in-scope
prewrite, and out-of-scope denial. PI-02E also waits for PI-02C, so the real
successor selection exercises runtime plan-revision binding rather than
creating selected state immediately before that control is added.

### Course-correction receipt — runtime authorization reachability

The first PI-02B acceptance graph made PI-02C structurally ready and made
PI-02E wait for it. Adversarial reachability review rejected that order as
operationally incomplete: source `enforce_selected` leaves a new PI-02C claim
at `selection_pending`, while the prepared v4 contract authorizes the
transition artifacts and documentation paths but not
`enforced_planning/outcome_selection.py` or its tests. A direct normal PI-02C
start therefore could attach its tracker but could not authorize any owned
write. Graph-schema validity was not execution readiness.

PI-02C now declares the missing two-phase entry sequence instead of adding a
second planner or using unplanned source maintenance. Its restricted,
write-free bootstrap phase commits an exact v5 scenario, allocation request,
and v3 disposition request whose immutable scope includes only the PI-02C
source/test paths plus its Plan-numbered transition artifacts. The normal
revision-bound PI-02C claim then attaches as `selection_pending`; the existing
portfolio owners park v3 and allocate/select v5 on that exact claim before the
first source mutation. Ordinary claim authority and selected scope must both
admit the target. PI-02E remains the post-PI-02C reselection owner so its later
selection exercises the newly accepted runtime plan-binding control. It uses
the same two-phase shape: a restricted bootstrap commits the v6 transition
inputs, then the normal exact PI-02E claim attaches pending, parks v5, and
allocates/selects v6 before heartbeat or documentation prewrite may succeed.

### Acceptance receipt — runtime plan-revision binding

PI-02C landed through provider commit
`70daaa3b5f26bcd5cfee409c7294f4f31bbb0305` and squash merge
`b692dd9adc57aff76cdf66c2110ac32a8344e3ed`. The public selection entrypoint
now validates the qualified plan at the outcome contract's immutable baseline
before creating a binding or mutating the tracker. A focused run across
selection, readiness, and plan validation passed 106 tests; Ruff passed the two
changed files. Real-Git controls distinguish exact, missing, incomplete,
ambiguous, mismatched-project, and symbolic baselines while preserving off,
observe, below-floor, and unplanned compatibility.

This is a development checkpoint, not terminal proof. PI-02C was selected
before the new runtime check existed. PI-02E is therefore the first authentic
successor selection required to exercise the merged control from main; failure
returns PI-02C to repair rather than being explained away by the synthetic
suite.

### Course-correction receipt — bootstrap identity must not come from paths

The first authentic PI-02E retry from merged main created an exact schema-v4
planned claim at revision `566526ccfd4e805fef1742810b342b5710ea9707` and
correctly denied heartbeat with `outcome_selection_required`. Its prewrite
negative control did not deny. Receipt
`oadm-de41b5ad5e6d4327ae08354299f86ee2` returned
`admission_bootstrap_allowed` because all three claimed transition paths match
the Plan-numbered bootstrap allowlist. The classifier never inspected the
claim's qualified `plan_ref` or work-unit identity.

This is a real authorization bypass, not a documentation discrepancy and not
evidence for weakening selected-outcome enforcement. PI-02F adds the smallest
semantic discriminator available in the current claim contract: only an exact
`UNPLANNED` claim may receive the path-scoped bootstrap exception. A qualified
planned claim with identical paths must continue through selected admission.
The repair does not add a claim schema field, change the bootstrap path set, or
alter ordinary claim authority. PI-02E remains blocked until the public
prewrite regression and the explicit bootstrap compatibility control both
pass.

The first PI-02F source claim then supplied a second required negative control.
Receipt `oadm-470822df5cdc42748e02e0af2382e791` denied its owned source path with
`outcome_selection_required`: graph readiness and ordinary claim ownership did
not make the repair executable because v6 deliberately excluded provider
source and tests. The uncommitted focused patch was preserved before closeout.
PI-02F therefore adopts the already-proven two-phase route rather than
bypassing the denial: a restricted bootstrap commits source-scoped v7 inputs,
then the normal exact claim parks v5 and selects v7 before the patch is
replayed.

### Failure-mode taxonomy reassessment

**Review charter:** The target is Plan 125 after PI-02B; the stage is the first
source pilot; the next decision is whether the plan can authorize an authentic
PI-02C source increment and still reach an installed AES consumer. Evidence is
the normal-Make receipts, exact claims/scopes, PRs 176–179, the selected-outcome
configuration, and the current work graph. The review excludes fleet rollout,
the portfolio product choice, and generalized planner hardening. It stops once
the next executable vertical and any decision-blocking correction are clear.

The taxonomy identifies one observed blocker group: **coherent but
un-executable** design. Graph validation accepted PI-02C even though its
runtime authorization state admitted none of its write paths; adversarial
review then found the same missing bootstrap transition in PI-02E. The
two-phase v5 and v6 contracts above are the cheapest corrections. Their exact
falsification is an authentic normal claim that remains denied before selection
and admits one in-scope target only after the declared allocation/selection
transition.

The reassessment rejects three tempting expansions. A new planner, automatic
claim transfer, and a generalized runtime-reachability checker do not improve
the next PI-02C readout and are not added. The missing checker step-down is a
real later methodology concern, promoted only before the next Company Planning
release or a second occurrence outside Plan 125. The session-name repair is not
treated as case-shaped because an independent negative control changed the
goal and failed before mutation; exact scope, goal, revision, work unit, and
session identity remain guarded.

Recent work also reaches the reassessment trigger for process capture: two
consecutive documentation/graph increments followed the authentic PI-02B
proof. Therefore the next Plan 125 increment must execute the v5 PI-02C
bootstrap, selection, and source boundary. Another planning-only increment
requires a newly reproduced blocker. PI-02E remains conditionally planned from
PI-02C output, and the plan still stops framework expansion after the installed
AES projection so independently valuable project rewrites continue as the
primary stress-test mechanism.

### External AES stress-test inputs and sequencing

Project Meta main retains four reproduced AES findings as
`lrn-20260822T233333074816Z-3383b7e6b7`,
`lrn-20260822T233333139399Z-35b111d53f`,
`lrn-20260822T233817822769Z-8170697c3a`, and
`lrn-20260822T234607126109Z-3b260bf667`. They establish that missing checkers
must not project `PASS`, self-attested prerequisites must not admit policy,
Git revisions and `sha256:` content digests have distinct typed semantics, and
authentic rewrites are the preferred stress-test mechanism. Those defects keep
the affected AES controls measured/nonblocking. They do not broaden Enforced
Planning ownership or pause an independently valuable consumer vertical.

## Plan

**Critical-path classification: vertical.** The visible vertical is an agent
being denied on an incomplete plan, admitted on a complete plan, and shown a
revision-bound human-readable planning state through installed AES.

1. **PI-01 — accepted design and graph.** Freeze this contract, its work graph,
   current roadmap boundary, and focused checks.
2. **PI-02 — Enforced Planning semantic admission.** Implement the typed
   contract, unambiguous config/parser, visible observe result, one-revision
   custody across Make/readiness/claim/worktree/session creation, direct-claim
   admission, complete installation propagation, and both-sign mutation-order
   tests.
3. **PI-02B — staged selected-activation repair.** Allow only an exact new v4
   plan reservation to attach its tracker as `selection_pending`; keep
   heartbeat and prewrite denied until the existing allocation and selection
   owners establish selected state.
4. **PI-02C — runtime plan binding.** Through its declared restricted
   custody-bootstrap phase, prepare and select the exact PI-02C claim before
   source mutation. Then require selected outcome admission to validate the
   immutable outcome contract's baseline revision against the claim's
   qualified plan, so continuation is revision-bound.
5. **PI-02F — bootstrap identity repair.** Require the path-scoped prewrite
   bootstrap exception to carry exact `UNPLANNED` claim identity. Prove an
   explicit bootstrap remains admitted and a qualified planned claim with the
   same paths requires selected state. Use a restricted v7 input bootstrap and
   select the exact source claim before replaying the repair patch.
6. **PI-02E — successor work-unit custody.** After PI-02C and PI-02F are
   accepted, use the newly enforced binding through a restricted v6
   input-bootstrap phase, then open the normal exact successor claim, park the
   active v5 allocation, and
   select the documentation-scoped v6 contract. Prove that claim can become a
   healthy revision-bound work-unit lane without bypassing source outcome
   admission.
7. **PI-02D — operator documentation sync.** From that selected successor lane,
   document exact-revision Planning Integrity at the canonical worktree/claim
   entrypoint and installed first-success path, then pass the focused coupling
   check.
8. **PI-03 — AES installed integration.** Consume a pinned Enforced Planning
   candidate, retain an immutable result, and project the planning fields into
   AES's existing topic without new authority.
9. Stop framework expansion. In parallel once a project-local plan is ready,
   the selected anchor repository owns its exploratory lineage/value probe and
   useful product vertical. Observed governance failures return as focused
   regressions; they narrow trust in the affected control rather than stopping
   unrelated consumer progress.

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
11. The resolved full start revision is stored in the claim and is identical
    across plan and graph readiness, claim, worktree creation, and session
    upsert; an older
    passing caller-supplied revision, a pre-existing mismatched branch or
    worktree, and symbolic-HEAD movement cannot switch the executed revision.
12. Observe mode visibly returns the typed findings without blocking, while
    duplicate governed sections/fields and non-portable `plans_dir` values fail
    loudly.
13. A clean worktree-only installation can execute the advertised
    `scripts/meta/check_plan_readiness.py` entrypoint without source-path
    imports or missing transitive dependencies.
14. Injected session-start failure after attaching a matching pre-existing
    branch preserves that branch and its ref; an occupied claim slot is rejected
    before mutation, and rollback releases only the exact claim created by the
    current start transaction.
15. A branch created between admission and the worktree helper remains intact
    when the helper reports it did not create the branch, and a running legacy
    v3 claim cannot acquire a fabricated v4 `start_revision` during session
    refresh.
16. The authentic installed Make path visibly prints the complete observe-mode
    result, creates one exact reservation/worktree/tracker chain, and closes the
    bootstrap loop without weakening ordinary claim-health reporting.
17. `--resume` plus an old passing commit cannot create a new claim even when
    matching branch/worktree artifacts exist; retained non-tip recovery routes
    through the existing session-resume lifecycle.
18. A governed heading with optional CommonMark closing hashes or indentation
    participates in duplicate detection, and a plan authored with the canonical
    template's `**Disposition:** value` form passes when its value is supported.
19. The sanctioned worktree helper always compares its resolved start revision
    with a plan-bound reservation even when the optional
    `--claim-start-revision` caller assertion is omitted; only a fully identified
    exact staged reservation may omit its not-yet-created tracker.
20. Under configured selected-outcome enforcement, an exact new v4 staged
    reservation may attach its tracker only as `selection_pending`; corrupting
    any staged invariant produces no tracker and rolls back invocation-owned
    branch/worktree/claim state, while heartbeat and prewrite remain denied
    until exact allocation and selection succeed.
21. A prewrite bootstrap exception requires exact `UNPLANNED` claim identity in
    addition to a complete bootstrap-safe path set; a qualified planned claim
    using only those paths still returns `outcome_selection_required` until it
    has an exact selection.

## Required Tests

- focused parser/result tests: complete, omitted, malformed state, missing
  trigger, unsupported version, and stale digest;
- configuration tests for `off`, `observe`, `enforce`, malformed values, and
  adoption-floor compatibility;
- start-gate mutation-order test proving semantic denial precedes claim and
  worktree creation;
- direct-claim and dirty-working-tree negative controls proving the configured
  gate cannot be omitted and binds the exact start revision;
- revision-custody controls for an older passing caller-supplied commit,
  existing branch/worktree mismatch, and symbolic-HEAD movement between
  readiness and mutation;
- a split-revision control proving plan and work-graph/approval bytes always
  come from the same retained commit;
- transaction-ownership controls for pre-existing claim and branch state plus
  injected branch-creation race and session-start failure;
- a legacy v3 claim-with-tracker control proving session refresh cannot invent
  v4 revision custody;
- an authentic selected-activation A/B proving exact v4 tracker attachment
  returns only `selection_pending`, any corrupted invariant leaves zero
  invocation-owned mutation, and heartbeat/prewrite remain denied before
  selection;
- a bootstrap-identity regression proving the explicit `UNPLANNED` bootstrap
  path remains allowed while a qualified planned claim with identical safe
  paths cannot bypass selected admission;
- observed-failure output control proving findings are visible without denial;
- duplicate governed-heading/field and absolute/traversing configuration-path
  rejection controls;
- regression tests for unplanned light work, historical plan compatibility,
  and existing outcome admission;
- installer idempotence, installed-wrapper parity, and a clean worktree-only
  readiness-CLI execution proving import dependency closure; and
- one AES installed-consumer proof with delete/regenerate comparison.

Do not run a fleet suite or comparative benchmark before the installed AES
boundary works. The terminal Enforced Planning self-test is required because
the installer/shared gate boundary changes.

## Files Affected

- `enforced_planning/plan_validation.py`
- `enforced_planning/plan_readiness.py`
- `enforced_planning/coordination_claims.py`
- `enforced_planning/outcome_admission.py`
- `enforced_planning/session_lifecycle.py`
- `enforced_planning/session_contracts.py`
- `scripts/check_plan_readiness.py`
- `scripts/check_coordination_claims.py`
- `scripts/validate_plan.py`
- `scripts/install_governed_repo.py`
- `scripts/session_start.py`
- `scripts/meta/session_start.py`
- `scripts/worktree-coordination/create_worktree.py`
- `scripts/meta/worktree-coordination/create_worktree.py`
- `Makefile`
- `meta-process.yaml`
- `templates/Makefile.worktree.block.template`
- `templates/meta-process.yaml.example`
- `templates/meta-process.future.yaml.example`
- `templates/plan.md.template`
- `scripts/relationships.yaml`
- `docs/reference/CONFIG_REFERENCE.md`
- `CLAUDE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` (PI-02D only)
- `GETTING_STARTED.md` (PI-02D only)
- `tests/test_validate_plan.py`
- `tests/test_plan_readiness.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_install_governed_repo.py`
- `tests/test_outcome_admission.py`
- `tests/test_session_cli.py`
- `tests/test_session_contracts.py`
- `tests/test_create_worktree.py`
- `ROADMAP.md`
- `docs/plans/CLAUDE.md`
- `docs/plans/125_planning_integrity_loop.md`
- `docs/plans/125_planning_integrity_loop_work_graph.json`
- `examples/owner-real-outcome-admission/plan125-planning-integrity-scenario.json`
- `examples/owner-real-outcome-admission/plan125-planning-integrity-allocation.json`
- `examples/owner-real-outcome-admission/plan125-planning-integrity-disposition.json`

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
- The unchanged default branch currently reproduces
  `tests/test_governed_delivery.py::test_prepare_creates_governed_failing_baseline`
  because `enforced_planning/outcome_continuation.py` trips the personal-sentinel
  portability check. It does not invalidate PI-02B's focused boundary, but no
  repo-wide green-suite or release claim may omit it; resolve or explicitly
  adjudicate it before provider promotion.
- The pre-commit dead-code detector reports `tool_available: false` because
  vulture is absent. Do not claim dead-code validation from that warning; make
  the tool available or disposition the check at a release boundary where its
  result protects an actual decision.

## Rollback And Non-Claims

Setting repository planning-integrity mode to `off` is the configuration-only
rollback. Reverting the implementation commit restores the previous validator
and start gate. Receipts remain evidence and never grant authority.

Completion proves one portable planning-integrity vertical and AES self-use. It
does not prove plan optimality, fleet adoption, automatic semantic judgment,
WhyGame value, or stable `1.0` guarantees. A project rewrite may use the controls
that have passed while treating the remaining controls as observations; this
plan is not a platform-completion gate for that rewrite.
