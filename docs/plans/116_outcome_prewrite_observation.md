# Plan #116: Outcome Continuation Pre-Write Observation

**Status:** Planned
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "correlate-outcome-admission-with-one-real-claimed-write"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** linked
**Execution profile:** pilot
**Overlays:** runtime state, exploratory, repository governance
**Blocked By:** #115
**Blocks:** durable lease binding, native activation, and outcome-enforcement promotion

---

## Gap

**Current:** Plan #115 proves that the unchanged Plan #114 evaluator admits
real merged owner progress and selects the existing pre-write claim adapter as
the smallest next seam. The operator still runs continuation admission
separately from the real claimed write, so the outcome decision has no exact
ordinary pre-write receipt, session, claim, worktree, branch, or payload
correlation.

**Target:** Extend the existing source-repository pre-write adapter with one
explicit, observe-only scenario option. For the same exact current Plan #116
Codex `apply_patch` payload, retain one ordinary claim `allow` plus correlated
`would_allow` observation under an active owner-progress scenario, and one
ordinary claim `allow` plus correlated `would_deny` observation under a
recovery-required control. Outcome observation cannot change the ordinary
claim decision, stdout JSON, or exit code. The adapter is exercised by an exact
manual replay; no hook wiring, claim mutation, or installer propagation occurs.

**Why:** This is the smallest executable bridge from correct outcome admission
to a real supported write identity. It directly tests false-block isolation and
correlation before choosing durable lease ownership or native activation.

## User Outcome

Brian and his agents can see, on a real Brian-owned claimed write, whether
genuine progress would permit continuation and circular motion would stop—while
calibration remains incapable of blocking legitimate work.

## Canonical Behavioral Example

**Starting state:** The current Codex session owns one healthy Plan #116 claim
and one exact evidence path. Its digest-bound pre-write projection is current.
Two immutable scenarios share the same outcome contract, request operation,
target path, ordinary approval text, cost telemetry, and elapsed telemetry. The
active scenario carries the Plan #115/Plan #55 owner-progress lineage; the
recovery scenario adds two explicitly synthetic non-outcome receipts.

**Action A:** Pipe one exact Codex `PreToolUse/apply_patch` payload through
`scripts/prewrite_claim_gate.py --json` with the active scenario and a temporary
outcome-observation ledger.

**Result A:** The existing ordinary decision remains `allow` /
`exact_live_claim`, exit code remains `0`, and one appended observation binds
its ordinary receipt ID and exact identities to `effect=would_allow` and
`reason_code=active_in_scope`.

**Action B:** Replay the byte-identical payload with the recovery-required
scenario.

**Result B:** The ordinary decision is still `allow` / `exact_live_claim` and
exit `0`; the correlated outcome observation is `would_deny` /
`recovery_required` with `enforcement_applied=false`.

**Delivery classification:** Both are `manual_adapter_replay`. They prove the
current source adapter and claim boundary, not automatic Codex hook delivery.

**Failure signal:** Outcome mode changes ordinary admission or exit; the
observation cannot name its exact ordinary receipt and current claim identity;
scenario target identity differs from the real payload but is accepted; a
claim denial is mislabeled as an outcome denial; default pre-write invocations
load or require the new observer; or evidence implies native/hard enforcement.

## References Reviewed

- `CLAUDE.md` — repository claim, evidence, verification, and closeout authority.
- `GETTING_STARTED.md` — current installed-consumer and tool-support boundary.
- `docs/reference/CONFIG_REFERENCE.md` — supported Codex/Claude pre-write
  events, staged observe/enforce semantics, and shell bypass limitation.
- `docs/plans/115_owner_real_outcome_observe.md` and
  `docs/evidence/plan115_owner_real_outcome_observation.json` — owner-real
  progress result, manual-friction readout, selected seam, and falsifier.
- `docs/plans/114_outcome_continuation_lease_enforcement.md` and
  `enforced_planning/outcome_continuation.py` — canonical typed evaluator and
  both-sign lease behavior.
- `docs/plans/108_prewrite_claim_enforcement.md`,
  `enforced_planning/prewrite_claim_fast.py`, and
  `scripts/prewrite_claim_gate.py` — existing native payload normalization,
  exact claim identity, ordinary decision, and append-only receipt owner.
- Project Meta `outcome-continuation-lease-hard-gate` at approved revision
  `f6091b6b2f2a5357d0fdbbe88b157435a2ce07fb` — observe before enforcement and
  never use spend/time as authority.
- Project Meta `owner-first-agentic-system-dogfooding` — current Brian-owned
  work before colleague or fleet rollout.

## Research

No web research is required. Plan #115 already executed the selected local
decision seam, and Plan #108 owns the exact supported write boundary. The
decision-relevant research is an executable same-payload observation against
the current claim and projection, with retained ordinary and outcome receipts.

Automatic host delivery, false-block behavior, and scenario/claim ambiguity
remain exploratory and may be claimed only from retained runtime evidence.

## Landscape And Prior Art

| Candidate | Evidence and implication | Disposition |
|---|---|---|
| Add another pre-write hook command | `scripts/prewrite_claim_gate.py` already owns supported payload normalization and ordinary receipts. | Rejected as duplicate delivery. |
| Mutate claim YAML with contract and lease state first | Plan #115 proves the evaluator but not that durable claim binding is needed to observe one exact write. | Deferred; this plan uses explicit immutable scenarios. |
| Add correlation directly to `scripts/prewrite_claim_gate.py` only | Durable observation typing, scenario binding, and append semantics would become difficult to test without adapter subprocess setup. | Rejected as hidden script-owned domain logic. |
| Add a small typed observer consumed lazily by the existing adapter | Keeps Plan #114 pure, preserves the default dependency-light path, and isolates one reusable correlation seam. | Adopted. |
| Wire installer/native hooks or block writes | Representative same-payload observations do not yet exist. | Deferred until reviewed false-block/bypass evidence. |

## Boundaries And Domain Rules

| Boundary | Owns | Must not own |
|---|---|---|
| Plan #114 evaluator | contract, receipt, lease transition, and operation admission | claim identity or hook delivery |
| ordinary pre-write adapter | native payload normalization, exact current claim decision, ordinary receipt | outcome authority or mutable lease state |
| outcome pre-write observer | immutable scenario load, actual-target binding, correlation, and append-only observation | ordinary admission, hook installation, or claim mutation |
| observation ledger | content-free calibration evidence | live authority, scenario selection, or automatic promotion |

Rules:

1. `--outcome-scenario` is opt-in and source-repository-only in this plan. With
   the option absent, the adapter does not import the outcome observer, create
   an outcome ledger, or change default output/exit behavior.
2. An outcome scenario requires an explicit evidence classification:
   `owner_real_progress` or `synthetic_recovery_control`. Delivery is fixed to
   `manual_adapter_replay`; this plan exposes no native-delivery flag.
3. Observation runs after the ordinary pre-write decision. The observer
   consumes that returned decision; it never re-resolves claim authority.
4. If the ordinary decision is not `allow`, record
   `not_evaluated_claim_denied`. Never turn an ownership/identity failure into
   an outcome denial.
5. For ordinary `allow`, the scenario request must be `product_write`, have one
   target path, and equal the adapter's single normalized target path. A
   mismatch is `observe_violation` and cannot block.
6. The observer calls Plan #114 `evaluate_scenario` directly. It does not
   duplicate transition or admission logic.
7. `would_allow`, `would_deny`, and `observe_violation` all set
   `enforcement_applied=false`. Outcome errors or ledger-append errors are loud
   advisory diagnostics but preserve the ordinary adapter result and exit.
8. Observations include paths and identity/digest metadata, never patch bodies,
   prompts, secrets, or file contents.
9. Approval, cost, and elapsed telemetry remain decision-inert. Arbitrary shell
   writes remain unsupported bypasses.

## Contracts

### `OutcomePreWriteObservationV1`

- schema version, stable observation ID, and timezone-aware timestamp;
- correlated ordinary pre-write receipt ID, decision, reason, and mode;
- client, session, project, claim scope/source, repository, worktree, branch,
  and normalized target paths copied from the ordinary decision;
- scenario ref/digest, evidence class, contract/receipt/lease digests when
  evaluation succeeds;
- `effect`: `would_allow | would_deny | observe_violation |
  not_evaluated_claim_denied`;
- outcome reason, lease state, operation, details, and limitations;
- fixed `delivery_source=manual_adapter_replay` and
  `enforcement_applied=false`.

Unknown fields fail loud. Appends use a file lock, flush, and `fsync`; the
ledger is evidence, not mutable current authority.

## Capability Adoption

**Disposition: extend.** Reuse the Plan #114 evaluator and Plan #108 adapter.
Add one typed correlation module and lazy opt-in call; do not add another
admission implementation, claim registry, hook command, or installer surface.
Adoption requires both signs against one current claimed-write payload.

## Scope And Non-Goals

In scope:

- strict typed outcome pre-write observation and append-only writer;
- lazy explicit-scenario option in the existing source adapter;
- default-path, mismatch, ordinary-denial precedence, and non-blocking tests;
- active and recovery-required immutable scenarios with one exact target;
- same-payload owner-real manual replay and retained both-sign correlation;
- truthful plan/index/roadmap reconciliation.

Not in scope:

- claim-schema mutation, outcome binder, or projection fields for outcome data;
- durable current lease storage or automatic progress classification;
- hook wiring, host config, installer, fleet, colleague, or external-user work;
- outcome-based blocking, break glass, restart review, or promotion;
- arbitrary shell/process write coverage;
- spend, subscription, elapsed-time, deployment, or release controls.

## Files Affected

- `enforced_planning/outcome_prewrite_observe.py` (create)
- `scripts/prewrite_claim_gate.py` (update)
- `tests/test_outcome_prewrite_observe.py` (create)
- `examples/owner-real-outcome-observe/plan116-prewrite-active.json` (create)
- `examples/owner-real-outcome-observe/plan116-prewrite-recovery.json` (create)
- `docs/evidence/plan116_outcome_prewrite_observations.json` (create)
- `docs/plans/116_outcome_prewrite_observation.md` (create/update)
- `docs/plans/116_outcome_prewrite_observation_work_graph.json` (create/update)
- `docs/plans/CLAUDE.md` (update)
- `ROADMAP.md` (update)

## Plan

### Critical Path Classification

| Increment | Class | Behavior or blocker changed |
|---|---|---|
| typed observer plus lazy adapter call | `vertical` | One ordinary claimed write gains correlated outcome advice without blocking |
| same-payload active/recovery current-claim replay | `vertical` | both outcome signs are observed at the real supported boundary |
| repair an exact scenario/claim correlation defect | `direct_blocker` only | removes only a reproduced obstacle to the same replay |
| claim binding, native activation, installer, or enforcement | deferred | none is required to answer the Plan #116 observation question |

### Steps

1. Add failing both-sign tests for strict observations, actual-target binding,
   claim-denied precedence, default lazy behavior, and admission/exit isolation.
2. Implement the typed observer and append-only writer by consuming Plan #114
   models and evaluator directly.
3. Add the explicit scenario/evidence-class options to the existing adapter;
   lazy import and invoke only after its ordinary decision exists.
4. Create active and recovery scenarios that share one exact Plan #116 path and
   decision-inert context.
5. Replay one byte-identical current Codex payload through both scenarios,
   retain ordinary and correlated outcome receipts, and evaluate the Plan #115
   falsification condition.
6. Run focused tests, lint, types, plan/work-graph validation, integrate to
   canonical main, and close without native or enforcement promotion.

## Required Tests

| Test | What it invalidates |
|---|---|
| strict observation model and append round trip | correlation evidence is malformed or lossy |
| no-scenario lazy/default path | existing adapter gains dependency, output, or ledger side effects |
| active same-target scenario | real progress is not observable as `would_allow` |
| recovery same-target scenario | circular continuation is not observable as `would_deny` |
| target/operation mismatch | unrelated immutable input is correlated to the real write |
| ordinary claim-denial precedence | ownership failure is mislabeled outcome denial |
| observation/evaluation failure isolation | calibration blocks or changes ordinary admission |
| same-payload adapter replay | unit models pass while current session/claim correlation is unusable |

## Acceptance Criteria

- [ ] With no outcome option, the adapter follows its existing import, output,
  receipt, and exit path and creates no outcome observation.
- [ ] Each outcome observation correlates one exact ordinary receipt and copies
  its current session, claim, repository, worktree, branch, and target identity.
- [ ] The same exact current Plan #116 payload produces ordinary `allow` in both
  runs, `would_allow/active_in_scope` for the active scenario, and
  `would_deny/recovery_required` for the recovery scenario.
- [ ] Outcome evaluation, mismatch, and ledger failures cannot change the
  ordinary decision or exit code; failures remain visible.
- [ ] An ordinary claim denial is `not_evaluated_claim_denied`, not an outcome
  denial.
- [ ] Approval, cost, and elapsed telemetry are identical and ignored in both
  outcome signs.
- [ ] Retained evidence includes exact revisions, payload digest, ordinary
  receipt IDs, scenario/contract/receipt/lease digests, effects, delivery
  classification, enforcement flag, and limitations.
- [ ] Focused tests, lint, types, plan/work-graph checks, and authentic manual
  replay pass on the integrated candidate.
- [ ] No claim mutation, native delivery, installer, shell, enforcement,
  colleague, or fleet claim is made.

## Failure And Reset Rules

| Failure | Response |
|---|---|
| scenario cannot bind the exact current target | retain mismatch and make durable claim/session scenario binding the next prerequisite; do not infer identity |
| observer changes ordinary decision or exit | remove adapter effect and add a metamorphic regression before any replay |
| active/recovery scenarios disagree with Plan #114 CLI | reuse the pure evaluator directly and repair only input/correlation logic |
| ordinary claim gate denies the current payload | repair the current claim/projection identity first; do not report an outcome denial |
| native hook does not deliver the observer | keep manual replay classification; activation is explicitly later |
| shell target is unresolved | record unsupported bypass; do not infer a path |

## Pre-Made Decisions

- Plan #116 observes only; it cannot promote itself to enforcement.
- Explicit immutable scenarios precede mutable claim/lease binding.
- The existing adapter and ordinary receipt remain the only write-correlation
  boundary; the observer never grants claim authority.
- Default pre-write behavior stays dependency-light and unchanged through a
  lazy opt-in import.
- Both signs use the same real payload; the recovery lease remains an explicit
  synthetic control, not a fabricated historical owner failure.
- Progress, not approval, money, or elapsed time, controls outcome advice.
