# Plan #113: Governed Delivery Authentic Vertical

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Authentic governed-delivery proof frontier"
**goal_ref:** "prove-one-authentic-portable-governed-delivery-vertical"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** poc
**Blocked By:** #60, #61
**Blocks:** evidence-based design of the wider Agentic Engineering System

---

## Gap

**Current:** The clean-room can materialize a neutral two-project fixture and
run a deterministic repair loop. The repository does not yet prove that a real
coding-agent session can receive a bounded feature request, use installed
planning authority, keep documentation aligned, change course after repeated
non-progress, and finish only when an independent verifier accepts the result.

Plan #62 has implemented neutral metadata and placeholder-project generation,
but its independent-consumer and real-adapter criteria remain open. Plan #72
owns the roadmap-to-design handoff and system model, not this delivery proof.

**Target:** Add one portable governed-task overlay and verifier to the existing
clean-room. Use the current Codex session to complete the task in a fresh
generated `hello-app`, producing a committed plan/code/docs result and an
integrity-bound verifier receipt. Exercise negative controls for false
authority, undeclared writes, repeated non-progress, and worker self-report.

**Why:** The current ecosystem has substantial horizontal machinery but lacks
the smallest authentic observation that the pieces compose into useful work.
That observation should precede feedback-system expansion or another framework.

---

## User Outcome

A user can hand one ordinary feature request to a coding agent and receive a
working, documented, plan-aligned change whose completion is certified by an
independent verifier rather than the worker's own report.

---

## Canonical Behavioral Example

**Starting input/state:** A fresh neutral clean-room whose governed `hello-app`
prints `hello-app uses shared-lib` and whose acceptance test for a `--name`
option fails.

**Action:** The current Codex session adopts a bounded plan and implements:
`python src/hello_app.py --name Ada`.

**Expected observable result:** The command prints `Ada uses shared-lib`; the
default output remains unchanged; one concise README example and one truthful
completed plan describe the behavior; only declared task paths changed; and the
independent verifier writes a passing receipt bound to the baseline and result
revisions.

**Behavioral evidence:** Unobserved until the fresh external-root run completes.

**Substrate/process evidence:** Focused contract tests, progress-guard negative
controls, installed governed-repo audit, Git diff binding, and receipt digest.

**Failure signal:** Any missing behavior, stale or false authority reference,
undeclared write, incomplete plan, dirty result, repeated unchanged failure
without a course checkpoint, or worker-only completion claim returns a failing
verdict with an exact check id.

---

## References Reviewed

- `CLAUDE.md` — source-repo authority and execution profiles.
- `PLANNING_OPERATING_MODEL.md` — outcome-first plans, modality, adoption, and
  stage-aware verification.
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — claimed-lane lifecycle.
- `docs/plans/60_loop_engineering_cleanroom_alpha.md` — materialization and
  external-root ownership contract.
- `docs/plans/61_cleanroom_deterministic_verified_loop.md` — independent
  verifier, bounded loop, and trace contract.
- `docs/plans/62_user_neutral_ecosystem_instantiation.md` — implemented neutral
  config boundary and still-open consumer/adaptor criteria.
- `docs/plans/72_engineering-control-plane-system-model-and-planning-handoff.md`
  — distinct system-model and handoff scope.
- `enforced_planning/cleanroom_alpha.py`, `scripts/cleanroom_alpha.py`, and
  `tests/test_cleanroom_alpha.py` — current capability seam.
- `scripts/install_governed_repo.py` — canonical governed-consumer installer.
- Memory recall step — the canonical recall command was attempted before this
  assessment but retrieval did not run because the configured OpenRouter
  embedding route reported HTTP 402 insufficient credits. It contributed no
  findings and no alternate paid route was used.

## Research Basis For This Slice

The user supplied the prompt/context/harness/loop vocabulary and approved a
clean-spine, selective-reuse direction. No additional web research is needed:
the decision is whether existing local capabilities compose, and source plus an
authentic run can answer it more directly.

## Landscape And Prior Art

**Alternatives:**

1. Repair every current policy and feedback mechanism first — rejected for this
   slice because it repeats horizontal construction before an outcome proves
   which controls matter.
2. Create a new Agentic Engineering System repository first — deferred until a
   real vertical exposes a distribution or ownership seam that Enforced
   Planning cannot own.
3. Extend the existing clean-room with one governed delivery task — adopted
   because it reuses the materializer, installer, verifier pattern, and neutral
   external-root boundary while producing a new authentic observation.
4. Integrate `llm_client` or `data-contracts` now — deferred. The current Codex
   session is the authentic worker and the first task has no cross-project data
   contract requiring those optional adapters.

**Project implications:** Add only the task preparation, progress control,
verification, CLI, tests, example instructions, and exact evidence needed for
this vertical. Do not generalize an agent runtime or feedback platform.

**Refresh trigger:** Revisit these choices after the first receipt, or earlier
only if the existing installer/clean-room seam demonstrably cannot support the
task.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| Task, allowed paths, checks, and receipt | Deductive / plan-first | Inputs, Git state, commands, and failure conditions are deterministic. | Use strict local Pydantic contracts and both-sign tests. |
| Repeated non-progress control | Deductive / plan-first | Identical state plus repeated failing checks is observable. | Require a course checkpoint before another attempt. |
| Real coding-agent completion | Exploratory / ladder | The agent's path and mistakes are emergent. | Run one fresh task; retain attempt/checkpoint/verifier evidence. |
| Wider ecosystem usefulness | Exploratory / ladder | One task cannot establish portability for colleagues. | License only the one-vertical claim and defer broader adoption. |

**Exploratory readout:** A fresh prepared consumer ends at a clean committed
revision with a passing independent receipt and no undeclared writes.

**Step-down path:** Every failed probe names the concrete command, check id,
state digest, and next allowed action. Two unchanged failing probes require a
checkpoint naming the questioned assumption and changed tactic.

---

## Boundaries And Non-Goals

The Enforced Planning source repo owns the reusable task contract, progress
guard, verifier, and example. The disposable generated repo owns its task plan,
code, README, tests, Git history, and runtime evidence. Generated instructions
are orientation only; the generated repo's `CLAUDE.md` is its authority.

This plan does not include self-improving policy, fleet migration, a new top-
level repository, colleague-ready distribution claims, model comparison,
`llm_client` or `data-contracts` integration, dashboards, deployment, release,
or generalized security/privacy hardening.

## Capabilities

| Capability | Input | Output | Producer | Consumer | Cost |
|---|---|---|---|---|---|
| `prepare_governed_task` | clean-room root + framework revision | task contract + governed Git baseline | Enforced Planning | coding agent | free |
| `probe_governed_task` | task root + observed Git state | typed failing/passing probe and next action | independent harness | coding agent | free |
| `record_course_checkpoint` | failed probe lineage + changed assumption/tactic | durable checkpoint | progress guard | coding agent and verifier | free |
| `verify_governed_task` | task root + immutable baseline/result | integrity-bound verification receipt | independent harness | user/operator | free |

The contracts remain native to Enforced Planning for this slice. They are not
registered in the shared `data-contracts` repository until a second real
consumer creates a cross-project seam.

## Capability Adoption

**Disposition: extend.** This plan extends the canonical clean-room capability
owned by `enforced_planning.cleanroom_alpha` and consumes the canonical
`scripts/install_governed_repo.py` installer. The intended consumer is the
fresh generated `hello-app`; adoption is proved only when that consumer is
prepared through the selected seam and its committed result receives a passing
independent receipt. No parallel materializer or installer is introduced.

## Files Affected

- `enforced_planning/governed_delivery.py` (create)
- `scripts/governed_delivery.py` (create)
- `tests/test_governed_delivery.py` (create)
- `examples/cleanroom-ecosystem/README.md` (update)
- `docs/evidence/plan113_governed_delivery_receipt.json` (generated)
- `docs/plans/113_governed_delivery_authentic_vertical.md` (update)
- `docs/plans/CLAUDE.md` (update)
- `ROADMAP.md` (update)

---

## Plan

### Critical Path Classification

| Increment | Class | Behavior or blocker changed |
|---|---|---|
| Prepare + probe + verify one governed task | `vertical` | A real coding agent can cross the portable plan/docs/code/verifier path. |
| Enforce a checkpoint after repeated unchanged failure | `vertical` | A failing loop must question an assumption/change tactic before continuing. |
| Repair an installer or fixture incompatibility | `direct_blocker` only if reproduced | Removes the exact failure preventing the vertical. |

### Steps

1. Write focused failing tests for preparation, authority, declared paths,
   progress checkpoints, self-report rejection, and successful verification.
2. Implement the smallest task overlay, Pydantic contracts, progress guard,
   verifier, and JSON CLI on top of the existing clean-room and installer.
3. Materialize a fresh external root, prepare the governed `hello-app`, and
   observe its initial failing acceptance test.
4. As the real worker, create the consumer's bounded plan; implement the
   `--name` behavior; update only the concise README; run focused checks; and
   commit the result.
5. Run the independent verifier and retain its portable receipt in this repo.
6. Run focused negative controls, update this plan/index/roadmap truthfully,
   commit, push, integrate, and close the lane.

## Required Tests

| Test | What it invalidates |
|---|---|
| Fresh prepare + baseline probe | A fixture that starts passing or is not mechanically governed. |
| Positive authentic-style fixture | Behavior, docs, plan, Git, or receipt that cannot pass together. |
| False-authority negative control | A plan that treats generated instructions as governing authority. |
| Undeclared-write negative control | A worker changing paths outside the task contract. |
| Repeated-no-progress negative control | An unchanged failing loop continuing without a course checkpoint. |
| Self-report negative control | A worker-authored completion marker substituting for executed checks. |
| `tests/test_cleanroom_alpha.py` | Regression in the reused clean-room seam. |

Gate-time budget: focused tests and one fresh authentic run should consume no
more than roughly 20 percent of implementation time before the first receipt.
Run broader repository validation only at terminal integration because this
adds a portable public CLI/module surface.

## Acceptance Criteria

- [x] A fresh external root can be prepared through the canonical clean-room
  and governed-repo installer without personal paths or credentials.
- [x] Its initial feature probe fails for the missing `--name` behavior.
- [x] The current Codex session creates a bounded consumer plan and commits only
  declared code, documentation, and plan paths.
- [x] Default and `--name Ada` commands produce the exact expected outputs.
- [x] The README contains one concise runnable example and the plan is truthful,
  complete, and rooted in `CLAUDE.md` rather than generated orientation.
- [x] Two unchanged failing probes require a course checkpoint with a changed
  assumption/tactic before work can continue.
- [x] Worker self-report cannot produce a passing result.
- [x] The independent verifier emits a digest-bound receipt naming task,
  baseline revision, result revision, session, executed checks, and verdict.
- [x] Focused positive/negative tests, reused clean-room tests, plan validation,
  and terminal repository validation pass.
- [x] The exact receipt licenses only: “One real coding-agent task completed
  through the portable governed-delivery path with visible plan adherence,
  documentation alignment, course correction controls, and independent
  verification.”

## Authentic Evidence

- Framework/verifier revision: `757ebcb727eb5407318a1c80629d9b3e803282c7`
- Generated consumer baseline: `af8b4a9ddbb62dc133b80ceaf62e6cb38cf666af`
- Generated consumer result: `e5c00c1b4a3a13530ce12455f335977e636243b2`
- Independent receipt: `docs/evidence/plan113_governed_delivery_receipt.json`
- Receipt digest: `b162b168c2117e692b8eae631958ede9e1a5c56849e32fc02f36c10ddb286bcd`

The receipt is path-neutral and contains no disposable `/tmp` root. Its 15
checks all pass. The source revision is retained on the pushed Plan 113 branch;
terminal integration retained that exact ancestry. Final framework evidence:

- `ruff check enforced_planning/governed_delivery.py scripts/governed_delivery.py tests/test_governed_delivery.py` — pass.
- `pytest -q tests/test_cleanroom_alpha.py tests/test_governed_delivery.py` —
  41 passed.
- `python scripts/validate_plan.py --plan-file docs/plans/113_governed_delivery_authentic_vertical.md --warn-only` — no gaps or warnings.
- `python scripts/self_test.py` — file, Markdown-link, documentation, plan, and
  install checks all passed.

## Failure And Replan Rules

| Failure | Required response |
|---|---|
| Installer cannot govern the prepared repo | Record the exact audit failure; repair only that seam or use a visible bounded manual overlay. |
| Two probes have the same state digest and failure set | Stop retrying; record the questioned assumption and changed tactic before another probe. |
| Plan cites generated instructions as authority | Correct the plan to the nearest canonical `CLAUDE.md`; do not weaken the check. |
| A changed path is undeclared | Revert the accidental file or update the consumer plan/task contract truthfully before continuing. |
| Worker says complete but checks fail | Retain the failing verifier result and continue only from its concrete failure. |
| The vertical requires a new runtime/framework | Reassess expected value; add only a reproduced direct blocker, not speculative generalization. |

The first authentic preparation attempt exposed a concrete revision-binding
defect: a syntactically valid but hand-constructed component revision could be
recorded even when it did not equal the executing framework commit. Preparation
now compares the clean-room receipt to `git rev-parse HEAD` and fails with
`component_revision_mismatch`; the focused negative control passes. The invalid
external root is excluded from completion evidence.

The next fresh root exposed a second portability defect before source editing:
`governed-task.json` serialized this machine's absolute Python interpreter.
The durable contract now stores `python` and resolves the interpreter only at
execution time; preparation also requires the independent `portable_content`
check to pass before returning `prepared`. That root is likewise excluded from
completion evidence.

The first changed-state probe exposed a scope-parser defect: stripping the
whole porcelain status output removed the first line's leading status byte and
turned `README.md` into a phantom `EADME.md`. Git output now preserves leading
whitespace, with a focused working-tree negative control. Terminal receipts
also include the executing framework revision, and the check set rejects a
prepared component/verifier revision mismatch. The affected external root is
diagnostic evidence, not completion evidence.

## Pre-Made Decisions

- Reuse the existing clean-room and canonical installer.
- The current Codex session is the authentic worker; no paid model call or
  programmatic real-agent adapter is added.
- The independent deterministic verifier alone certifies completion.
- One local Pydantic contract owns this prototype seam; shared contract
  extraction waits for a second real consumer.
- A separate Agentic Engineering System repo waits for demonstrated distribution
  ownership need.
- Feedback-system work remains downstream of this authentic vertical.
