# Plan #130: Cross-Repository Plan Authority Binding

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "cross-repository-plan-authority"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** Project Meta Plan #249 AES implementation lane

`trace_evaluable: false # deterministic two-repository admission behavior`

## Gap

**Current:** The portfolio readiness query resolves a qualified plan such as
`project-meta#249`, but `resolve_canonical_work_unit_binding()` then validates
that plan against the target repository and target start revision. The observed
`/home/brian/code/agentic-engineering-system` probe therefore reported Plan 249
missing even though the readiness query had resolved its authority in Project
Meta. No branch, worktree, or claim was created.

**Target:** A plan-bound claim records and validates two exact Git identities:
the mutation target repository/revision containing the work graph, and the
qualified plan authority repository/revision containing the numbered plan. A
cross-repository claim succeeds only when both are explicit, their repository
identities match the qualified reference, and the target work unit binds the
exact plan digest.

**Why:** Copying a proxy Plan 249 into AES would duplicate authority. Treating
the target checkout as the plan authority makes the supported qualified-plan
syntax unusable at precisely the cross-repository boundary it represents.

## User Outcome

An agent can start a claimed worktree in one governed repository under a plan
owned by another registered repository without copying the plan or weakening
target-repository mutation controls.

## Canonical Behavioral Example

**Starting input/state:** Project Meta owns accepted Plan 249; AES owns a ready
`249_..._work_graph.json`; both repositories are clean at exact remote-default
revisions; the session targets AES.

**Action:** Create the AES worktree with `project-meta#249`, the AES work graph,
and explicit Project Meta plan-authority root/revision.

**Expected observable result:** Planning Integrity validates Plan 249 from
Project Meta, work-unit integrity validates the graph from AES, the resulting
claim retains both revision identities, and the worktree/session starts at the
AES revision.

**Behavioral evidence:** Unobserved until the authentic AES Plan 249 bootstrap
passes after source installation.

**Substrate/process evidence:** Two temporary Git repositories, strict claim
round-trip tests, installed Make/session propagation tests, and wrong-root,
missing-root, stale-plan, digest-mismatch, and target-revision controls.

**Failure signal:** The plan is searched for in AES, a mismatched plan root is
accepted, the claim loses either revision, or the worktree starts from the plan
repository revision instead of the AES revision.

## References Reviewed

- `enforced_planning/coordination_claims.py` — the reproduced binding defect:
  parsed qualified repository identity is passed to planning validation while
  `repo_root` and `start_point` still name the target repository.
- `enforced_planning/session_lifecycle.py` — session activation revalidates the
  work-unit binding and must preserve the additional authority identity.
- `enforced_planning/plan_readiness.py` — the local admission wrapper still
  conflates the qualified plan repository with the target lane repository;
  both exact roots/revisions must be carried through this precondition too.
- `enforced_planning/outcome_admission.py` and
  `enforced_planning/session_contracts.py` — staged activation revalidates the
  binding and tracker serialization must retain its external authority fields.
- `scripts/session_start.py`, `Makefile`, and
  `scripts/install_governed_repo.py` — source and installed propagation path.
- `CLAUDE.md` and `GETTING_STARTED.md` — source workflow and first installed
  consumer path.
- `docs/plans/125_planning_integrity_loop.md` — revision-bound plan-integrity
  contract this repair must preserve.
- `docs/reference/CONFIG_REFERENCE.md` — current claims/worktree configuration
  surface; no new discovery setting is added.
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — work-unit readiness,
  Planning Integrity, and hard outcome-admission sections; its cross-repository
  plan-authority contract owns the operator invocation rules.
- `tests/test_check_coordination_claims.py`, `tests/test_session_cli.py`, and
  `tests/test_install_governed_repo.py` — current contract and installer
  controls.
- Project Meta Plan #249 at `334846bf` and AES work graph at `7bf24b9` — the
  authentic two-repository reproduction.
- Memory recall skipped: the current session retained the exact traceback,
  repositories, revisions, and no-residue probe.

## Research Basis For This Slice

No additional research beyond References Reviewed. This is a reproduced local
framework defect with one bounded correction.

## Landscape And Prior Art

**Alternatives:** A proxy plan in AES was rejected because it creates a second
authority. Inferring a sibling checkout from directory layout was rejected
because it guesses host topology. Trusting the readiness subprocess without
retaining plan bytes was rejected because direct claim creation would lose the
same proof. The selected design carries an explicit plan-authority root and
revision alongside the existing target root and revision.

**Project implications:** Qualified plan identity becomes a real two-repository
contract. Local plans keep their existing one-repository path. No Project Graph,
Company Planning, AES product, or Data Contracts semantics move into this repo.

**Refresh trigger:** A portable plan-authority resolver or signed readiness
receipt may later replace the explicit root, but only if it preserves both exact
revision identities and direct-claim safety.

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| authority/target separation | Deductive | the observed roots and revisions are exact | strict typed fields and two-repo controls |
| installed propagation | Deductive | Make/session/installer owners are known | source and generated-parity tests |
| fleet resolver | Exploratory | portable host discovery is not selected | explicitly excluded |

**Exploratory readout:** None in this slice; stop after one authentic AES
bootstrap proves the explicit contract.

**Step-down path:** A failed authentic probe reports which identity, revision,
digest, or propagation surface disagreed.

## Capabilities

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|---|---|---|---|---|---|
| `resolve_canonical_work_unit_binding` | target root/revision, qualified plan, plan-authority root/revision, work graph/unit | exact target + plan authority binding | enforced-planning | governed-repo claim/session entrypoints | free |

### Capability Validation

- [x] Both repository identities and revisions are strict and explicit.
- [x] Claim persistence retains target and plan-authority custody.
- [x] Source Make/session and installed fixture copies propagate the same fields.
- [ ] Authentic AES under Project Meta Plan 249 starts without a proxy plan.

## Capability Adoption

**Disposition: extend.** Extend the existing qualified-plan and claim-binding
seam. Do not add a repository-discovery service, proxy-plan format, second claim
model, or Project Graph implementation.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| reproduced defect | fully_specifiable_now | target root is incorrectly reused for plan validation | two-repo red control passes after repair | Plan 130 evidence |
| binding record | fully_specifiable_now | claim already retains target start revision and graph digest | both authority and target fields round-trip | claim schema |
| installed propagation | fully_specifiable_now | Make/session/installer surfaces are explicit | generated parity and installed consumer pass | AES install |
| automatic authority discovery | deliberately_deferred | no portable resolver selected | revisit only with signed portable resolver | separate plan |
| Plan 249 semantics | deliberately_deferred | Project Meta remains authority | AES worktree starts | resume Plan 249 unchanged |

## Reassessment Contract

- **Triggers:** the fix requires a proxy plan, guessing a filesystem layout,
  changing readiness decision semantics, or touching more than the existing
  claim/session/admission/readiness/installer propagation seams.
- **Autonomous action:** keep plan and target custody separate, add exact fields,
  and narrow failing fixtures to the first disagreeing identity.
- **Plan revision required:** changing claim schema shape, adding a resolver, or
  changing the digest binding rule.
- **Human decision required:** moving plan authority, weakening direct-claim
  validation, or accepting a proxy plan as canonical.
- **Stopping rule:** focused both-sign tests, framework self-test, installed AES
  propagation, and the authentic `~/code -> AES under project-meta#249`
  worktree start all pass.

## Files Affected

- `enforced_planning/coordination_claims.py`
- `enforced_planning/session_lifecycle.py`
- `enforced_planning/session_contracts.py`
- `enforced_planning/outcome_admission.py`
- `enforced_planning/plan_readiness.py`
- `scripts/session_start.py`
- `scripts/meta/session_start.py` (generated parity mirror)
- `scripts/check_plan_readiness.py`
- `Makefile`
- `templates/Makefile.worktree.block.template` (canonical installed Make source)
- `scripts/install_governed_repo.py`
- `tests/test_check_coordination_claims.py`
- `tests/test_session_cli.py`
- `tests/test_session_contracts.py`
- `tests/test_outcome_admission.py`
- `tests/test_plan_readiness.py`
- `tests/test_install_governed_repo.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/reference/CONFIG_REFERENCE.md`
- `docs/plans/125_planning_integrity_loop.md` (additive external-authority extension)
- `CLAUDE.md` and its generated `AGENTS.md` mirror
- `GETTING_STARTED.md` (installed dependency custody during bounded upgrade)
- Plan 130 plan, work graph, outcome fixtures, index, roadmap, and evidence

## Operator Contract

For an external plan, keep `WORKTREE_REPO_ROOT`, `WORKTREE_START_POINT`, and
`WORKTREE_PROJECT` bound to the mutation target. Supply `PLAN_PROJECT` for the
authority repository, `PLAN_REPO_ROOT` as its explicit absolute canonical root,
and `PLAN_START_POINT` as its full immutable Git commit. The same fields flow
through readiness, claim creation, and session activation. Local plans omit the
two new variables and retain their existing one-repository behavior.

Example authority split for the authentic consumer:

| Input | Value |
|---|---|
| mutation repository | `/home/brian/code/agentic-engineering-system` |
| qualified plan | `project-meta#249` |
| plan authority root | `/home/brian/code/active/project-meta` |
| target graph | `docs/plans/249_contract_coupled_derived_documentation_work_graph.json` |
| work unit | `P249-AES01` |

The external plan digest remains mandatory when the authority repository's
structural integrity mode is off. This binds committed bytes without enabling a
new enforcement policy there. New lanes require current integration tips;
refreshing a retained lane preserves its original exact custody.

The selected outcome scenario remains byte-immutable. Implementation-support
scope revisions are recorded in this plan, its work graph, and the live claim;
the existing selected product target remains `coordination_claims.py`.

## Plan

### Critical Path Classification

**Critical-path classification: direct_blocker.** The complete increment is the
smallest repair that lets the already-ready Plan 249 AES slice acquire its own
authority.

| Increment | Class | Behavior or named blocker changed |
|---|---|---|
| exact cross-repository binding | `direct_blocker` | qualified plan validation no longer searches the mutation target |
| source/session/installer propagation | `direct_blocker` | the repaired contract survives worktree creation and session activation |
| authentic AES bootstrap | `vertical` | Plan 249 obtains a real claimed AES worktree with no proxy plan |

### Steps

1. Retain exact target and plan-authority identity/revision/digest fields.
2. Validate local and qualified paths with independent Git roots.
3. Propagate the fields through claim CLI, session lifecycle/tracker, staged
   outcome admission, plan-readiness admission, Make, and installer.
4. Run focused negative controls, self-test, and installed AES parity.
5. Start and close the authentic Plan 249 AES lane, then return to Plan 249.

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_check_coordination_claims.py` | `test_cross_repository_work_unit_binding_separates_target_and_plan_revisions` | correct root/revision succeeds |
| same | `test_cross_repository_claim_denials_leave_no_residue` | relative, unresolvable, stale, and digest mismatch deny atomically |
| same | `test_cross_repository_claim_persists_external_plan_authority_custody` | plan authority and target custody survive persistence |
| same | `test_cross_repository_binding_retains_plan_bytes_when_integrity_is_off` | digest custody does not silently depend on structural enforcement mode |
| `tests/test_session_cli.py` | `test_cross_repository_session_retains_plan_custody_and_rejects_rebinding` | staged activation, tracker, refresh, and rollback preserve both identities |
| `tests/test_plan_readiness.py` | `test_external_plan_readiness_keeps_target_lane_revision_separate` | readiness does not substitute plan revision for execution revision |
| `tests/test_install_governed_repo.py` | `test_installed_worktree_surface_preserves_external_plan_authority` | installed consumer receives exact plan-authority variables and flags |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| focused coordination/session/installer suites | local-plan behavior and compatibility remain unchanged |
| `python scripts/self_test.py` | framework-wide verification remains green |
| authentic AES Plan 249 bootstrap | proves the user-visible blocker is removed |

### Verified Source Checkpoint — 2026-08-30

The four initial cross-repository controls failed before implementation. The
current focused six-file suite reports **321 passed, 8 failed**; the same suite
on untouched canonical `2634cf3` reports **304 passed, the identical 8 failed**.
Those failures are retained as pre-existing baseline debt, not hidden or changed
inside this repair. The framework self-test, syntax/undefined-name check, and
source/mirror byte parity pass. A read-only authentic Project Meta `334846bf` /
AES `7bf24b9` binding returns the expected Plan 249 digest and independent target
revision. Installation and actual worktree bootstrap/closeout remain pending.

The first source-entrypoint AES bootstrap subsequently passed with schema-v5
claim and schema-v3 tracker custody. Before installation, the worktree-only
preview exposed a related propagation defect: it would vendor framework source
into AES despite AES's declared pinned dependency. An observed failing fixture
now covers that case; the limited installer reuses the existing dependency
detection/filter and leaves package version changes to the consumer's pin.
The initial recovery lane uses the repaired canonical source entrypoint; a
separate post-install lane must prove the ordinary installed route.

The required operator-guide update initially overlapped the stale retained
`fix/session-resume-admission-20260829` lane. Inspection found a clean worktree
with one empty unique commit, `bb19cbb560795ef9f669a8a266ccd041b86efd83`.
The sanctioned session-abandon lifecycle retired that live claim; branch,
worktree, commit, and tracker were preserved. This does not declare the older
session-resume repair complete. The current claim now explicitly owns the
coupled documentation surfaces.

Exact commands, identities, and baseline failure names are retained in
[the Plan 130 evidence receipt](../evidence/plan130_cross_repository_plan_authority.json).

## Acceptance Criteria

1. A qualified cross-repository plan is validated from an explicit matching
   plan-authority repository/revision while its work graph and mutation start
   remain bound to the target repository/revision.
2. Missing authority root, repository-id mismatch, stale/unresolvable plan
   revision, plan-digest mismatch, and target-revision mismatch each fail before
   branch, claim, or worktree residue.
3. The persisted claim and session tracker retain both authorities without
   treating an absolute navigation directory as mutation authority.
4. Local same-repository plan claims remain compatible.
5. Source Make, session CLI/lifecycle, installer output, and installed AES use
   one contract; generated copies are not edited independently.
6. Focused suites, framework self-test, and the authentic AES bootstrap pass.
7. Enforced Planning and AES finish with named remote commits, clean owned
   worktrees, and terminal claims before Plan 249 product implementation resumes.

## Failure Modes

- **Proxy authority:** a local plan copy satisfies validation. Reject and keep
  qualified authority explicit.
- **Revision substitution:** the plan SHA becomes the target start SHA. Assert
  both independently.
- **Ambient discovery:** a sibling directory is guessed. Require an explicit
  authority root/revision.
- **Readiness-only trust:** direct claim creation skips plan bytes. Revalidate
  the exact authority plan during claim binding.
- **Propagation drift:** source passes but installed AES drops fields. Retain
  installer and authentic consumer controls.

## Documentation Updates

Update the operator guide only for the new explicit authority inputs and the
distinction between plan authority, target work graph, and mutation claim.

## Implementation Approval

Authorized by Brian's Plan 249 `/goal` contract: Enforced Planning remains
read-only unless execution reproduces a framework defect, in which case the
repair receives its own bounded plan. The exact defect was reproduced before
any AES branch, claim, or worktree was created.
