# Plan #60: Loop-Engineering Clean-Room Alpha Slice 1

**Status:** Complete
**Type:** implementation
**Priority:** High
**phase_ref:** "Shareable loop-engineering alpha"
**goal_ref:** "portable-governance-cleanroom"
**adrs_referenced:** []
**research_citations:** []
**Blocked By:** None
**Blocks:** Future deterministic loop slice

---

## Gap

**Current:** The shareable loop-engineering clean-room shape is specified in
project-meta, but enforced-planning does not yet ship a runnable portable
generator that can materialize, verify, and reset an external synthetic
ecosystem.

**Target:** Add a Slice 1 clean-room alpha in enforced-planning that plans,
materializes, verifies, reports status for, and resets a neutral external root
containing only two synthetic projects, a minimal policy pack, state
directories, and receipts.

**Why:** The ecosystem cannot become shareable until the portable governance
kernel can prove it can construct a bounded instance without Brian's project
inventory, paths, credentials, or personal policy content.

---

## References Reviewed

- `CLAUDE.md` - enforced-planning workflow and continuous execution contract
- `scripts/CLAUDE.md` - portable script placement guidance
- `docs/plans/TEMPLATE.md` - numbered plan structure
- `enforced_planning/notebook_registry_validation.py` - notebook registry schema
- `scripts/check_notebook_registry.py` - notebook validator entrypoint
- `project-meta/worktrees/ecosystem-policy-infra-review/docs/designs/LOOP_ENGINEERING_CLEANROOM_ALPHA_SPEC.md` - approved clean-room alpha specification
- `project-meta/worktrees/ecosystem-policy-infra-review/docs/ops/ECOSYSTEM_POLICY_AND_INFRASTRUCTURE_ADVERSARIAL_REVIEW_2026-07-09.md` - ecosystem shareability review
- `agent-memory recall 'active decisions loop engineering cleanroom governance enforced-planning' --project enforced-planning` - checked active-decision memory; no applicable clean-room decision found

---

## Research Basis For This Slice

No additional research beyond repo-local references and the approved
project-meta clean-room specification was needed. This slice is deterministic
packaging, ownership, and verification work; real-client adapter research is
deferred to a later slice.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Materialization contract | Deductive / plan-first | File layout, path safety, ownership, and receipts are deterministic. | Specify paths, receipts, and negative tests before implementation. |
| Verification checks | Deductive / plan-first | Isolation, synthetic inventory, secret sentinels, and symlink/path escape checks have crisp pass/fail criteria. | Implement as executable checks with exact findings. |
| New-user usefulness | Exploratory / ladder | Whether another user understands the clean room cannot be proven from local tests. | Defer to onboarding readout after Slice 1 and deterministic loop pass. |

**Exploratory readout:** Not part of Slice 1. Later onboarding asks whether a
new user can identify where projects, policy, state, and secrets belong without
private Brian context.

**Step-down path:** Every failed check reports the concrete path and check id.

---

## Capabilities

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|-----------|--------------|---------------|----------|-------------|-----------|
| `plan_cleanroom(spec)` | `CleanroomSpec` | `MaterializationPlan` | enforced-planning clean-room module | CLI, tests, future UI | free |
| `materialize_cleanroom(plan)` | `MaterializationPlan` | `InstallReceipt` | enforced-planning clean-room module | CLI, verifier, resetter | free |
| `verify_cleanroom(root, receipt)` | root path + optional receipt | `VerificationReport` | enforced-planning clean-room module | CLI, tests, future loop runner | free |
| `reset_cleanroom(root, receipt)` | root path + receipt | `ResetReport` | enforced-planning clean-room module | CLI, tests | free |

### Capability Validation

- [x] Input/output dataclasses are defined with explicit JSON serialization.
- [x] Each capability is reachable from an agent-drivable CLI command.
- [x] Schema and path validation fail loudly for invalid specs.
- [x] Journey notebook has a cell for each capability.

---

## Files Affected

- `docs/plans/60_loop_engineering_cleanroom_alpha.md` (create)
- `docs/plans/CLAUDE.md` (update)
- `notebooks/notebook_registry.yaml` (create)
- `notebooks/00_loop_engineering_cleanroom_alpha.ipynb` (create)
- `docs/evidence/plan60_cleanroom_alpha.md` (create/update)
- `enforced_planning/cleanroom_alpha.py` (create)
- `enforced_planning/notebook_registry_validation.py` (modify)
- `scripts/cleanroom_alpha.py` (create)
- `examples/cleanroom-ecosystem/README.md` (create)
- `tests/test_cleanroom_alpha.py` (create)
- `tests/test_check_notebook_registry.py` (modify)

---

## Plan

### Steps

1. Create the numbered plan, journey notebook, registry entry, and evidence placeholder.
2. Implement importable clean-room planning, materialization, verification, status, and reset functions.
3. Add an agent-drivable CLI wrapper with JSON output and fail-loud exit codes.
4. Add focused tests for happy path, idempotence, isolation, path escape, secret sentinel, symlink escape, undeclared project enrollment, foreign overwrite, and reset receipt tampering.
5. Run targeted tests, notebook validation, plan validation, markdown/link checks, and the repo self-test if the targeted gates pass.

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_cleanroom_alpha.py` | `test_plan_rejects_workspace_root` | The clean-room root cannot live under the shared projects workspace by default. |
| `tests/test_cleanroom_alpha.py` | `test_materialize_verify_status_and_reset` | The two-project fixture can be created, verified, reported, and reset from receipt-owned paths. |
| `tests/test_cleanroom_alpha.py` | `test_apply_refuses_foreign_overwrite` | The materializer does not overwrite existing unowned files. |
| `tests/test_cleanroom_alpha.py` | `test_verify_rejects_secret_sentinel` | Secret sentinels fail verification with an exact finding. |
| `tests/test_cleanroom_alpha.py` | `test_verify_rejects_symlink_into_workspace` | Symlinks into the projects workspace fail verification. |
| `tests/test_cleanroom_alpha.py` | `test_verify_rejects_undeclared_project` | Undeclared sibling projects are not silently enrolled. |
| `tests/test_cleanroom_alpha.py` | `test_reset_rejects_tampered_receipt_escape` | Reset refuses receipt paths that escape the clean-room root. |
| `tests/test_cleanroom_alpha.py` | `test_cli_json_smoke` | Agent-drivable CLI commands emit machine-readable JSON. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/check_notebook_registry.py --journey-id loop_engineering_cleanroom_alpha` | The journey notebook remains registered and mechanically valid. |
| `python scripts/validate_plan.py --plan-file docs/plans/60_loop_engineering_cleanroom_alpha.md --warn-only` | The plan stays parseable by the local validator. |
| `python scripts/self_test.py` | Broad framework validation after adding portable code. |

---

## Acceptance Criteria

> Feature-level criteria:
- [x] A clean external root can be planned without writing files.
- [x] Explicit apply materializes exactly the declared synthetic clean-room tree and writes an install receipt.
- [x] Verification fails loudly for path escape, symlink escape, secret sentinel, undeclared project enrollment, missing receipt, and foreign overwrite/reset tampering.
- [x] Verification passes on the generated fixture and reports exact check ids.
- [x] Status and reset are callable through JSON CLI commands.
- [x] Reset removes receipt-owned artifacts and refuses tampered receipt paths.
- [x] `run-demo` exists only as a machine-readable deferred command for Slice 2; it does not fake loop success.

> Process criteria:
- [x] Required tests pass.
- [x] Notebook registry validation passes for the journey.
- [x] Plan validation passes or warns only for known non-blocking repository-wide issues.
- [x] Docs updated.
- [x] Verified commit pushed.

---

## Open Questions

- [x] Should Slice 1 include a real agent loop? Answer: no. The approved spec scopes Slice 1 to C1-C2 and defers the deterministic loop to Slice 2.
- [x] Should the generated clean room be hand-copied from live workspace files? Answer: no. It must be materialized from canonical fixture source.
- [ ] Should the future canonical component name be `governance` before the physical repo rename? Status: OPEN. Slice 1 uses `governance` as a component id while keeping source code in `enforced-planning`.

---

## Notes

This is deliberately a shareable alpha, not production packaging. Security and
supply-chain depth stay minimal: no personal data or credentials, no destructive
defaults, bounded writes, explicit state locations, and negative controls before
any hard claims.
