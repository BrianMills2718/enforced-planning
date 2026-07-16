# Plan #71: Effective-Policy Resolution Pilot

**Status:** Planned
**Type:** implementation
**Priority:** High
**phase_ref:** "Portable governance control plane"
**goal_ref:** "ecosystem-policy-coherence"
**adrs_referenced:** ["ADR-2026-06-26-ecosystem-organization-four-buckets"]
**research_citations:** []
**Blocked By:** project-meta#225 — versioned three-policy definition pack must publish first
**Blocks:** [future] effective-policy manifests and risk-profile rollout

---

## Gap

**Current:** Enforced Planning supplies configurable booleans and strictness
keys in `meta-process.yaml`, but configuration is unevenly consumed. The clearest
counterexample is `quality.doc_coupling.strict`: the configuration reference
truthfully says the live pre-commit hook does not read it and blocks
unconditionally. Policy detection and enforcement are frequently coupled in the
same script or hook. The governed-repo audit then collapses installed mechanical
signals into `governed` versus `partial`, which does not establish the effective
policy configuration or its assurance.

**Target:** Consume Project Meta's versioned three-policy pack, resolve a
deterministic effective mode for a concrete project/action/scope, return one
standard evaluation contract, and apply `off`, `audit`, `warn`, or `block`
through a separate enforcer. Provide agent-drivable `effective` and `explain`
commands and prove the existing doc-coupling/plan checks through a shadow pilot
before changing default behavior.

**Why:** A configuration key that does not control behavior is worse than no
configuration: it gives agents and reviewers a false explanation for why an
action was allowed or blocked. The pilot must make three real checks truthful
without becoming a generic policy language.

## References Reviewed

- `CLAUDE.md` — portable-framework ownership and execution policy.
- `meta-process.yaml` and `templates/meta-process.yaml.example` — live configuration surface.
- `templates/meta-process.future.yaml.example` — explicitly advisory vocabulary.
- `docs/reference/CONFIG_REFERENCE.md:1-105` — consumed versus inert settings; doc-coupling strictness defect at line 86.
- `enforced_planning/governed_repo_audit.py:725-856` — current binary mechanical classification.
- `scripts/check_doc_coupling.py` and `tests/test_check_doc_coupling.py` — evaluator-like logic and current CLI enforcement switch.
- `hooks/git/pre-commit` and `tests/test_pre_commit_hook.py` — hardcoded `--strict` adapter.
- `scripts/check_plan_tests.py`, `scripts/validate_plan.py`, and focused tests — existing plan checks.
- `enforced_planning/hook_wiring.py` and `tests/test_generate_hook_wiring.py` — installed hook ownership.
- `~/projects/project-meta/policy/registry.yaml` — ecosystem policy catalog and evidence map.
- `~/projects/project-meta/docs/plans/225_versioned-policy-definition-pack.md` — upstream definition-pack plan.
- `~/projects/investigations/cross-project/2026-07-16-policy-control-plane-gap-assessment.md` at `d413309` — contracted external-review assessment.
- Memory recall: existing doc-coupling `verify_sync` and false-positive history; no existing general resolver was found.

## Research Basis For This Slice

The external review's proposed control-plane fields and modes were compared
against Project Meta Plans 199, 204, and 208, the 167-row policy registry,
enforcement liveness, violation observability, this repo's configuration
reference, and the governed-repo audit. The review's generic-language warning
is retained: wrap existing real checks first.

## Request Mode, Depth, and Execution Profile

- **Authoring request:** plan only. This document does not authorize runtime implementation.
- **Design depth:** Standard; the change introduces a shared runtime decision seam.
- **Execution profile:** production-internal pilot. It affects local hooks and
  agent workflows but remains opt-in and rollbackable during shadow operation.
- **Overlays:** runtime-state and repository-governance.
- **Required now:** deterministic resolution, typed records, fail-loud invalid
  configuration, focused integration tests, explanation, and legacy-equivalence
  readout.
- **Deferred:** generic rule language, compositional profiles,
  `require_approval`, quarantine, fleet rollout, and universal manifests.

## Modality Assessment

| Part | Mode | Why | Planning treatment |
|---|---|---|---|
| Resolution precedence and mode behavior | Deductive | Inputs, precedence, and outcomes are specifiable. | Strict contracts and exhaustive mode tests. |
| Evaluator/enforcer separation | Deductive | Responsibility and failure behavior are knowable. | Typed interfaces and adapter tests. |
| Friction/value of the pilot | Exploratory | False-positive and remediation effects must be observed. | Shadow comparison with case-level readout; no invented threshold. |

**Exploratory readout:** For every pilot invocation, compare legacy decision,
resolved mode, evaluation outcome, enforcement decision, and operator-visible
message. Classify mismatches as intended correction, policy-definition defect,
resolver defect, adapter defect, or unresolved.

**Stopping rule:** After one representative positive and negative case for each
pilot policy plus the known doc-coupling strictness counterexample, stop and
review. Do not broaden the policy set during the pilot.

**Step-down path:** Every aggregate mismatch count links to the exact policy,
project fixture, changed resources, evaluation, resolved-from chain, and legacy
decision.

## Requirements

1. The resolver consumes a validated, immutable `PolicyDefinitionPack`; it does
   not redefine policy meaning or silently accept an unpinned registry.
2. Resolution precedence for this pilot is exactly:
   definition default -> project override -> exact scope override -> one valid
   time-bounded exception.
3. Multiple applicable values at the same precedence, unknown policy IDs,
   unsupported modes, expired exceptions, malformed timestamps, or override
   ceiling violations fail loud.
4. The pilot supports `off`, `audit`, `warn`, and `block` only.
5. Evaluators determine conformance; enforcers determine operational effect.
6. An evaluator never inspects its effective mode to weaken the finding.
7. An enforcer never recomputes policy conformance.
8. `off` skips evaluation but still produces a resolution/execution record.
9. `audit` records and allows silently; `warn` records, notifies, and allows;
   `block` records and rejects on a failed evaluation.
10. `indeterminate` and `error` never silently become pass. The definition must
    declare their pilot disposition, defaulting to block for `block` mode and
    visible allow for `audit`/`warn`.
11. Existing behavior remains available behind an explicit legacy adapter
    during the shadow pilot; there is no silent fallback if the resolver fails.
12. A project cannot claim effective-policy support merely because it has
    `meta-process.yaml`; it must have a valid pack/config and observed adapter
    coverage for the policy being claimed.

## Boundary Diagram

```text
Project Meta PolicyDefinitionPack (immutable, pinned)
                         |
                         v
Consumer meta-process policy config ---> EffectivePolicyResolver
Action context ------------------------->          |
Scope override / exception ------------>          v
                                      ResolvedPolicy
                                             |
                        +--------------------+-------------------+
                        v                                        v
              PolicyEvaluator                          PolicyEnforcer
              (detect only)                            (mode only)
                        |                                        |
                        +-------------> PolicyExecutionRecord <--+
                                              |
                                      explain / shadow readout
```

## Boundary Responsibilities

| Boundary | Owned state/rules | Inputs/outputs | Failure behavior | Forbidden responsibility |
|---|---|---|---|---|
| Pack loader | Validated pinned definitions and digest | bytes/path -> `PolicyDefinitionPack` | Reject invalid/digest drift | Selecting project mode |
| Effective resolver | Precedence, override ceiling, exception applicability | definition + config + context -> `ResolvedPolicy` | Reject ambiguity/unsupported value | Evaluating repository conformance |
| Evaluator adapter | One policy's factual conformance | action context -> `PolicyEvaluation` | Return typed `indeterminate`/`error` | Deciding warn/block |
| Enforcer | Mode-to-effect mapping | resolved policy + evaluation -> `EnforcementDecision` | Fail loud on impossible combination | Re-running policy logic |
| Recorder/explainer | Exact decision provenance and human/agent projection | records -> JSON/text | Never omit a blocking cause | Becoming definition authority |

## Capabilities

| Capability | Producer/owner | Consumer | Boundary claim |
|---|---|---|---|
| Publish reviewed policy meaning | Project Meta Plan 225 | pack loader | A pinned `PolicyDefinitionPack` supplies meaning and override ceilings; it does not select local modes. |
| Resolve effective policy | `enforced-planning` | hooks, validators, agents, and CLI callers | Strict context plus pack/config produces one explainable `ResolvedPolicy`. |
| Evaluate factual conformance | policy-specific adapters | shared enforcer | Evaluation is mode-invariant and retains evidence/resources. |
| Apply enforcement effect | shared enforcer | hook/command caller | Resolved mode plus evaluation produces skip, allow, notify, or block without re-evaluating the rule. |
| Explain a decision | recorder/CLI | agents and operators | JSON and human projections expose the same resolution and evidence chain. |

This plan does not advertise policy-definition ownership, portfolio assurance,
generic policy evaluation, or fleet rollout as Enforced Planning capabilities.

## Domain Model

| Concept | Key invariants |
|---|---|
| `PolicyMode` | Closed enum: `off`, `audit`, `warn`, `block` |
| `PolicyDefinitionRef` | Policy ID, semantic version, pack ID/version/digest |
| `PolicyContext` | Project ID, repo root, action kind, exact resource paths, aware `as_of` |
| `PolicyOverride` | One policy ID, one scope selector, one supported mode, source identity |
| `PolicyException` | Stable ID, policy ID, exact scope, reason, approval reference, aware expiry, optional compensating control |
| `ResolutionStep` | Source class, source reference, candidate mode, accepted/rejected reason |
| `ResolvedPolicy` | Definition ref, effective mode, ordered resolution steps, applicable exception, canonical digest |
| `PolicyEvaluation` | Policy/version, outcome, severity, message, evidence, affected resources, remediation |
| `EnforcementDecision` | Allow/allow-and-notify/block/skip-off plus reason and record references |
| `PolicyExecutionRecord` | Context digest, resolved policy, optional evaluation, enforcement decision, timestamp |

Evaluation outcomes are:

`pass | fail | not_applicable | indeterminate | error | exception_applied`

An exception does not erase the underlying failed evaluation. The execution
record retains the evaluation and marks the exception in the enforcement
decision; `exception_applied` is reserved for an exception evaluator record or
a rendered compatibility view, not a replacement for factual failure.

## Contracts

```python
resolve_policy(
    definition: PolicyDefinition,
    config: ProjectPolicyConfig,
    context: PolicyContext,
) -> ResolvedPolicy

resolve_all_policies(
    pack: PolicyDefinitionPack,
    config: ProjectPolicyConfig,
    context: PolicyContext,
) -> tuple[ResolvedPolicy, ...]

evaluate_policy(
    resolved: ResolvedPolicy,
    context: PolicyContext,
) -> PolicyEvaluation

enforce_policy(
    resolved: ResolvedPolicy,
    evaluation: PolicyEvaluation | None,
) -> EnforcementDecision
```

The public Python seam uses strict Pydantic models with field descriptions.
Configuration files reject unknown keys. CLI JSON is generated from the same
models; human text is a projection. System-assigned IDs and digests are not
caller-controlled.

## Configuration Schema

The pilot adds one deliberately small live section:

```yaml
meta_process:
  policy_control:
    schema_version: "1"
    definition_pack:
      path: policy/packs/enforced-planning-pilot-v1.yaml
      sha256: <64-hex digest>
    policies:
      doc-code-coupling:
        mode: warn
      pre-commit-plan-validation:
        mode: block
    scope_overrides:
      - policy_id: doc-code-coupling
        scope: generated/**
        mode: audit
    exceptions:
      - exception_id: exc-generated-transition
        policy_id: doc-code-coupling
        scope: generated/**
        reason: Migration output is checked by the generator digest.
        approval_ref: ADR-XXXX
        expires_at: 2026-09-01T00:00:00Z
        compensating_control: generated-output-hash-check
```

Slice 1 implements only pack + project policy modes. Slice 2 adds exact scope
overrides and exceptions after Slice 1's resolver/explanation contract passes.
No profile syntax or arbitrary parameter map is accepted.

## Backward Runtime Pass

1. **Final transition:** a hook or command either allows, allows with notice,
   blocks, or skips because mode is off; it emits one `PolicyExecutionRecord`.
2. **Runtime producer:** the enforcer applies the already resolved mode to the
   evaluator result.
3. **Evidence/preconditions:** pinned definition pack, validated project config,
   exact action context, evaluation evidence, and aware time.
4. **Prior-state guarantee:** the installer has placed a supported resolver and
   adapter version; the pack digest matches; config validation passed.
5. **Recovery:** invalid configuration or digest mismatch blocks the pilot path
   with an explanation. Operators may explicitly select the documented legacy
   adapter during shadow operation; there is no automatic fallback.

## Pilot Adapters

| Policy ID | Existing evaluator/mechanism | Pilot adapter |
|---|---|---|
| `doc-code-coupling` | `check_doc_coupling.py` returns strict violations and warnings; hook hardcodes `--strict` | Preserve factual findings; move mode effect to shared enforcer |
| `pre-commit-plan-validation` | staged plan validation in the pre-commit path | Normalize validation findings; shared enforcer selects audit/warn/block |
| `pre-commit-plan-index-regen` | staged plan-index freshness check | Normalize freshness finding; shared enforcer selects audit/warn/block |

Read-gating is a named dependency subplan, not a hidden fourth pilot: Project
Meta must first assign it one canonical policy ID and definition. Its shell/tool
hook semantics can then be mapped in a successor without widening this pilot.

## Files Affected

- `enforced_planning/policy_control.py` (create: strict models and resolver)
- `enforced_planning/policy_adapters.py` (create: factual evaluator adapters)
- `scripts/policy.py` (create: `effective` and `explain` CLI)
- `scripts/check_doc_coupling.py` (modify: expose mode-invariant findings)
- `hooks/git/pre-commit` (modify only after shadow evidence)
- `meta-process.yaml` (modify for self-hosted pilot configuration)
- `templates/meta-process.yaml.example` (modify)
- `docs/reference/CONFIG_REFERENCE.md` (modify)
- `enforced_planning/governed_repo_audit.py` (modify in Slice 4)
- `tests/test_policy_definitions.py` (create)
- `tests/test_policy_resolution.py` (create)
- `tests/test_policy_enforcement.py` (create)
- `tests/test_policy_scope_and_exceptions.py` (create)
- `tests/test_policy_cli.py` (create)
- existing hook, doc-coupling, plan-validation, and audit tests (modify)

## Risk-Ordered Slices

### Slice 1 — Resolve and explain two levels without changing hook behavior

**Vertical scope:** validate the three-policy fixture/published pack, load
project modes, resolve default -> project override, expose `policy effective`
and `policy explain`, and generate JSON plus human output.

**De-risks:** whether definition ownership, pack pinning, and project config can
compose without duplicating policy authority.

**Success:** positive fixtures resolve deterministically; ambiguous, unknown,
unsupported, ceiling-violating, and digest-drift fixtures fail loud.

**Audit:** attempt to bypass the override ceiling, supply duplicate policy
config, use a stale digest, and claim a policy absent from the pack.

**Cleanup:** remove any duplicated policy prose from fixtures; keep exact source
references instead.

### Slice 2 — Separate one evaluator from enforcement and shadow the hook

**Vertical scope:** adapt `doc-code-coupling` end to end; preserve its factual
finding, apply all four modes outside the evaluator, retain legacy comparison,
and record the known inert-`strict` counterexample.

**De-risks:** whether separation changes factual results or merely makes effect
configuration truthful.

**Success:** violation + off/audit/warn/block produces skip/allow-silent/
allow-notify/block respectively; positive cases remain allowed; legacy and new
decisions are compared case by case.

**Audit:** confirm evaluator output is invariant across modes and resolver
failure never invokes the legacy path silently.

**Cleanup:** remove the inert `quality.doc_coupling.strict` key or make it an
explicit migration alias with one removal version; update the config reference.

### Slice 3 — Add exact scope override, expiring exception, and remaining adapters

**Vertical scope:** add exact scope resolution and one expiring exception
contract, then adapt plan validation and index freshness.

**Success:** precedence and expiry tests pass; same-level conflicts, naive
timestamps, expired exceptions, scope escapes, and unauthorized modes fail.

**Audit:** prove an exception cannot change another policy, broader path, later
time, or underlying evaluation result.

### Slice 4 — Observed pilot and status reclassification

Run representative positive/negative cases in shadow mode, retain the readout,
and decide whether each adapter is equivalent, corrected, defective, or
indeterminate. Update governed-repo reporting from a binary claim to separate:

- installation status;
- configuration validity;
- effective enforcement coverage;
- last observed verification/assurance.

This slice may recommend broader rollout; it cannot silently start it.

## Required Tests

### New Tests

| Test file | Required cases |
|---|---|
| `tests/test_policy_definitions.py` | strict pack parsing, version/digest, duplicate/unsupported definitions |
| `tests/test_policy_resolution.py` | default/project precedence, ceiling rejection, deterministic explanation |
| `tests/test_policy_enforcement.py` | all mode/outcome combinations, evaluator invariance, fail-loud invalid states |
| `tests/test_policy_scope_and_exceptions.py` | exact scope, conflict, aware expiry, scope isolation, retained failure |
| `tests/test_policy_cli.py` | `effective`/`explain` JSON and human parity |
| existing hook tests | shadow and activated adapters preserve expected positive/negative behavior |

### Existing Tests

- `tests/test_check_doc_coupling.py`
- `tests/test_pre_commit_hook.py`
- `tests/test_check_plan_tests.py`
- `tests/test_validate_plan.py`
- `tests/test_generate_hook_wiring.py`
- `tests/test_audit_governed_repo.py`
- `python scripts/self_test.py`

The full test suite is terminal evidence after the adapters and installer files
change, not a required loop after each internal model edit.

## Acceptance Criteria

| ID | Criterion | Evidence class | Target grade |
|---|---|---|---|
| C71-1 | Exact Project Meta pack revision and digest are validated before real-policy resolution | source + test | A |
| C71-2 | Resolver precedence and override ceilings are deterministic and explainable | test | A |
| C71-3 | Evaluations are invariant across enforcement modes | negative + positive tests | A |
| C71-4 | `off`, `audit`, `warn`, and `block` produce their declared effects | integration test | A |
| C71-5 | Invalid config, ambiguity, stale digest, and expired exceptions fail loud | negative tests | A |
| C71-6 | Three real existing policies run through the shared contracts without copied policy semantics | source + integration test | A |
| C71-7 | Shadow evidence records concrete legacy/new decisions and friction disposition | observed | B initially; A only with retained test fixtures |
| C71-8 | Governed-repo status no longer implies assurance from installed files alone | source + test | A |
| C71-9 | Profiles, approval, quarantine, generic parameters, and fleet manifests remain deferred | doc/source review | D, intentionally unimplemented |

## Failure Modes and Rollback

| Failure | Required response |
|---|---|
| Resolver becomes a rule DSL | Remove expressions/operators; retain lookup, precedence, validation, and explanation only |
| Evaluator behavior changes by mode | Block slice; restore mode-invariant evaluator contract |
| Invalid config falls back to legacy | Block slice; remove fallback and require explicit legacy selection during shadow pilot |
| Exception hides the underlying violation | Retain failed evaluation and represent exception only in enforcement decision |
| Pack requires Brian-specific paths/state | Fix Project Meta pack boundary before continuing |
| Pilot adds more policies to make metrics look better | Freeze allowlist and defer expansion to successor review |
| New path causes more false blocks | Keep adapter in audit/warn, classify concrete cases, revise definition or implementation |

Rollback is project-local selection of the explicit legacy adapter plus removal
of the pilot config. Existing check scripts and hooks remain intact until their
activated adapter passes focused and terminal evidence.

## Multi-Repo Coordination

| Repo | Files modified | Merge strategy |
|---|---|---|
| `project-meta` | Plan 225 registry definition/pack publication | Merge and publish exact digest first |
| `enforced-planning` | resolver/models/CLI/adapters/tests/config docs/installer | Implement only after separate authorization and exact upstream pin |
| pilot consumer | local `meta-process.yaml` only after adapter tests | Shadow first; no fleet rollout |

Project Meta owns policy meaning and portfolio evidence. Enforced Planning owns
portable resolution and enforcement mechanics. The consumer owns local mode and
scope selection within the definition's ceiling.

## Dependency Subplan — Read-Gating Definition

**Blocks:** adding read-gating to the pilot or claiming complete governance-mode coverage.

**Current stub:** read-gating remains on its current hook path and outside this
pilot's effective-policy claims.

**Unknowns:** canonical Project Meta policy ID, whether the evaluator can be
separated cleanly from tool-hook effect, and the cross-client observation
boundary.

**Instrument:** register/review one definition in Project Meta, then run focused
positive/negative hook fixtures without changing enforcement.

**Readout:** one stable definition and one typed factual evaluation that does
not depend on enforcement mode.

**Promotion:** update the Plan 71 adapter table/contracts and create a successor
slice; do not insert it into the frozen three-policy pilot.

## Pre-Made Decisions and Alternatives

1. **Use Project Meta's pack, not a second hand-maintained policy catalog.**
2. **Use explicit precedence, not “last YAML wins.”** Same-level conflicts fail.
3. **Separate evaluation from enforcement.** This is the root fix for inert
   strictness configuration and cross-channel duplication.
4. **Start with four modes.** Approval and quarantine need concrete workflows
   and actors before they can be truthful contracts.
5. **No profiles in the pilot.** Profiles are convenient projections over
   definitions/configuration only after conflict semantics are observed.
6. **No universal effective-policy manifest yet.** Record per-invocation
   execution evidence first; promote a manifest only when real runtime callers
   consume the resolver consistently.
7. **Replace binary terminology only after evidence.** Documentation may say
   “governance-capable” now; the audit's output migration belongs to Slice 4 so
   consumers get compatibility handling and tests.

## Open Questions

None block plan review. Implementation remains unauthorized until the Project
Meta definition pack is published and the Plan 71 owner confirms the exact pin.

## Policy Friction Logged

The following implementation-side defect is recorded in
`project-meta/policy_friction.md` and retained here because it directly affects
this plan's dependency gate:

- **Policy:** `fail-loud-plan-dependency-check`
- **Friction:** `make check-deps REPO=.` printed an `ERROR` for unresolved
  `project-meta#225` but exited with status 0, allowing automation to treat a
  failed dependency check as successful.
- **Recommendation:** Return nonzero whenever any `ERROR` row is emitted; keep
  warnings non-blocking, and add a negative test for one missing cross-project
  plan reference.
