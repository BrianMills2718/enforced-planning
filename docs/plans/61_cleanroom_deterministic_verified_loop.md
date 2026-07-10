# Plan #61: Clean-Room Deterministic Verified Loop

**Status:** In Progress
**Type:** implementation
**Priority:** High
**phase_ref:** "Shareable loop-engineering alpha"
**goal_ref:** "portable-governance-cleanroom"
**adrs_referenced:** []
**research_citations:** []
**Blocked By:** #60
**Blocks:** Future real-agent adapter slice

---

## Gap

**Current:** Plan #60 can materialize, structurally verify, inspect, and reset a
portable synthetic ecosystem, but `run-demo` is an explicit deferral and the
fixture begins in a passing state.

**Target:** Add a deterministic, zero-LLM loop that observes the declared
`hello-app` failure, applies one declarative repair, reruns an independent
verifier, stops only on verifier success or configured limits, and writes a
tamper-evident canonical loop receipt.

**Why:** This proves the portable state, worker, verifier, stop, trace, budget,
and interruption contracts before authentication, model variance, or cost are
introduced by a real agent adapter.

---

## References Reviewed

- `CLAUDE.md` - continuous execution and worktree requirements
- `docs/plans/60_loop_engineering_cleanroom_alpha.md` - completed generator slice and deferred loop boundary
- `enforced_planning/cleanroom_alpha.py` - current importable generator, verifier, resetter, and deferred command
- `scripts/cleanroom_alpha.py` - current JSON CLI surface
- `tests/test_cleanroom_alpha.py` - existing positive and negative controls
- `notebooks/00_loop_engineering_cleanroom_alpha.ipynb` - existing journey contracts
- `project-meta/worktrees/ecosystem-policy-infra-review/docs/designs/LOOP_ENGINEERING_CLEANROOM_ALPHA_SPEC.md` - approved C3/A5 Slice 2 contract
- `agent-memory recall 'active decisions loop engineering cleanroom deterministic loop enforced-planning' --project enforced-planning` - no applicable active decision found

---

## Research Basis For This Slice

No additional external research is needed. This slice implements the approved,
deterministic local contract; real-client adapter selection remains deferred.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Loop transitions and stopping | Deductive / plan-first | Verifier results, iteration limits, and cost are deterministic. | Define typed receipts and both-sign controls before enforcement. |
| Declarative repair action | Deductive / plan-first | One exact text replacement has explicit pre/postconditions. | Put fixture knowledge in generated config, not generic runner code. |
| Crash recovery | Hybrid | Trace persistence is deterministic; process-level recovery policy will evolve. | Prove an interrupted receipt is valid and non-successful; defer automatic resume. |

**Exploratory readout:** A later real adapter must emit the same receipt without
changing verifier or stop semantics.

**Step-down path:** Every failed transition records verifier output, state
digest, action status, and a stable stop reason.

---

## Domain Model And Contracts

| Contract | Input | Output | Invariant |
|---|---|---|---|
| `LoopSpec` | JSON loop configuration | validated command, budget, guards, actions | no shell command strings; all paths stay under root |
| `DeclarativeTextReplacement` | guarded relative path + old/new text | action result + state digest | exactly one declared match; no arbitrary worker code |
| `run_demo_loop` | root + worker mode | `LoopRunReceipt` | worker claims never certify success |
| `verify_loop_trace` | receipt path | `LoopTraceVerification` | digest and transition ordering must validate |

The generic runner knows how to run guarded commands and declarative actions.
Only the generated fixture's `loop-spec.json` knows which file and text repair
the demo needs.

---

## Capabilities

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|-----------|--------------|---------------|----------|-------------|-----------|
| `load_loop_spec(root)` | clean-room root | `LoopSpec` | clean-room module | runner, CLI, tests | free |
| `run_demo_loop(root, mode)` | root + bounded worker mode | `LoopRunReceipt` | clean-room module | CLI, tests, future adapters/UI | free |
| `verify_loop_trace(path)` | trace path | `LoopTraceVerification` | clean-room module | CLI/tests | free |

### Capability Validation

- [ ] Input/output dataclasses have explicit JSON representations.
- [ ] Every capability is importable and reachable through JSON CLI commands.
- [ ] Invalid paths, verifier guards, trace digests, and transitions fail loudly.
- [x] Journey notebook contains the planned loop contract before code changes.

---

## Files Affected

- `docs/plans/61_cleanroom_deterministic_verified_loop.md` (create/update)
- `docs/plans/CLAUDE.md` (update)
- `notebooks/notebook_registry.yaml` (update)
- `notebooks/00_loop_engineering_cleanroom_alpha.ipynb` (update)
- `docs/evidence/plan61_cleanroom_deterministic_loop.md` (create/update)
- `enforced_planning/cleanroom_alpha.py` (modify)
- `scripts/cleanroom_alpha.py` (modify)
- `examples/cleanroom-ecosystem/README.md` (update)
- `tests/test_cleanroom_alpha.py` (modify)

---

## Plan

1. Record the Slice 2 contracts and honest pre-implementation coverage grades.
2. Add the generated failing expectation and declarative `loop-spec.json`.
3. Implement typed loop spec, action, transition, receipt, and trace-verification contracts.
4. Replace the deferred CLI with bounded worker modes and a trace-verification command.
5. Add positive controls plus self-certification, exhausted-budget, verifier-tamper, trace-tamper, repeated-failure, and interruption negative controls.
6. Exercise a fresh external root, update evidence/coverage, run broad validation, publish, and close the lane.

---

## Required Tests

### New Tests (TDD)

| Test | What It Verifies |
|---|---|
| `test_run_demo_repairs_known_failure_and_stops_on_verifier` | Initial failure is observed, declared repair is applied, verifier passes, and stop reason is exact. |
| `test_run_demo_rejects_self_certification` | Worker-reported success cannot produce a passing receipt. |
| `test_run_demo_exhausts_iteration_budget_on_noop_worker` | Repeated failure stops at the configured iteration limit. |
| `test_run_demo_rejects_tampered_verifier` | Guarded verifier files cannot change unnoticed. |
| `test_verify_loop_trace_rejects_tamper` | Receipt mutation breaks the canonical digest check. |
| `test_interruption_receipt_is_valid_and_not_successful` | An interruption between action and re-verification leaves durable, truthful state. |
| `test_cli_json_smoke` | `run-demo` and trace verification are agent-drivable JSON operations. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_cleanroom_alpha.py` | Slice 1 lifecycle and isolation remain intact. |
| `tests/test_check_notebook_registry.py` | Updated journey registry remains valid. |
| `python scripts/self_test.py` | Framework-wide contracts remain green. |

---

## Acceptance Criteria

- [ ] A5: the first verifier run fails, one declared action repairs the fixture,
  an independent verifier passes, and the loop stops within three iterations.
- [ ] The worker cannot self-certify; only a verifier pass yields success.
- [ ] Zero iteration budget, repeated verifier failure, and verifier tampering fail loudly.
- [ ] The canonical receipt records before/after state digests, verifier command
  and results, action status, budget use, component revision, stop reason, and timestamps.
- [ ] Trace tampering is detected and an interrupted run remains valid but unsuccessful.
- [ ] The generic runner contains no `hello-app`, `shared-lib`, or expected-message knowledge.
- [ ] Required tests, notebook validation, plan validation, external-root exercise,
  markdown checks, and `self_test.py` pass.

---

## Coverage

Pre-implementation baseline recorded before enforcing the Slice 2 gates:

| Requirement | Grade | Evidence class | Required to close | Positive control | Negative control |
|---|---|---|---|---|---|
| A5 verified repair loop | D | doc | test | known failing fixture repaired | no-op repeated failure |
| Independent success certification | D | doc | test | verifier passes after repair | self-certifying worker |
| Bounded stop conditions | D | doc | test | success within max iterations | zero/exhausted iteration budget |
| Canonical trace integrity | D | doc | test | valid receipt verifies | mutated receipt digest |
| Verifier integrity | D | doc | test | guarded verifier unchanged | verifier file mutation |
| Interruption truthfulness | D | doc | test | complete run receipt | interrupted in-progress receipt |
| Generic runner boundary | D | doc | test | declarative action succeeds | source scan for fixture names |

Grade distribution at start: A=0, B=0, C=0, D=7, F=0. The final evidence
document must re-grade each row; no criterion becomes A until source and its
automated positive/negative controls pass.

---

## Failure Modes And What To Try Next

| Failure | Disposition |
|---|---|
| Initial verifier unexpectedly passes | fail `initial_failure_not_observed`; repair fixture/config, do not claim loop proof |
| Guarded verifier digest differs | stop `verifier_integrity_failed`; require explicit rematerialization |
| Declarative match is absent or repeated | stop `worker_action_failed`; fix spec or fixture |
| Worker claims success | record rejection, run verifier, and stop only by verifier/budget |
| Iteration limit reached | stop `iteration_budget_exhausted` with failing verifier evidence |
| Process interrupted after action | persist `interrupted` receipt; do not infer success or auto-resume in this slice |
| Receipt digest or transition order changes | trace verification fails with exact finding |

---

## Pre-Made Decisions

- The deterministic worker uses no LLM and incurs zero model cost.
- Commands are argv arrays executed without a shell.
- Fixture-specific repair data lives in generated JSON config.
- Success requires an independent verifier exit code of zero.
- Automatic resume and real-client adapters are later slices.
- Security and supply-chain work remains alpha-scaled: path guards, verifier
  hashes, bounded writes, and trace integrity, not signing or sandboxing.

---

## Notes

This is a contract proof, not a production-grade autonomous coding system. The
security boundary is intentionally modest and explicit; it is sufficient to
test shareability and loop semantics without pretending to isolate hostile code.
