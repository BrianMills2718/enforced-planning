# Plan #62: User-Neutral Ecosystem Instantiation

**Status:** In Progress
**Type:** design + implementation
**Priority:** Critical
**phase_ref:** "Shareable governed-delivery proof"
**goal_ref:** "prove-configurable-governed-delivery-repeat"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** poc
**Blocked By:** #61, #113
**Blocks:** shared-contract extraction decision and broader independent-consumer claims

---

## Gap

**Current:** Plan #113 proved one authentic governed task, but its preparation
and verification contract is hard-coded to `projects/hello-app`,
`src/hello_app.py`, and the `--name Ada` example. The clean-room already accepts
a consumer-owned project inventory, yet the governed-delivery path cannot use a
different inventory or task profile.

**Target:** Let a consumer provide one validated, path-neutral governed-task
profile. Preserve the existing `hello-app` behavior as the default profile, then
complete a fresh `status-cli` task in a custom one-project clean-room. Bind the
profile, baseline, result, framework revision, and independent checks into the
second receipt.

**Why:** A second, materially different consumer is the smallest test of
configurability. It can expose the real reusable seam before the framework is
shared with colleagues or its contracts are extracted to `data-contracts`.

## User Outcome

A user can declare a different project and ordinary feature request without
editing Enforced Planning internals, then receive the same plan-aligned,
documentation-current, course-correcting, independently verified delivery path.

## Canonical Behavioral Example

**Starting input/state:** A custom consumer config materializes only
`projects/status-cli`. A consumer-owned task profile selects that project and
requests JSON output. Its governed baseline prints:

```text
python src/status_cli.py
-> status-cli: adapter-placeholder
```

The requested command initially fails because `--json` is not implemented.

**Action:** The current Codex session adopts a bounded plan in the generated
`status-cli` repository and implements:

```text
python src/status_cli.py --json
```

**Expected observable result:** The command prints exactly
`{"project_id":"status-cli","status":"adapter-placeholder"}`; default output
is unchanged; one concise README and one completed consumer plan describe the
behavior; only declared paths change; and the independent verifier accepts a
receipt bound to the profile and Git revisions.

**Behavioral evidence:** Unobserved until the fresh external-root run completes.

**Substrate/process evidence:** Focused profile-validation, default-profile
regression, negative-path, progress-control, and receipt-binding tests.

**Failure signal:** A hard-coded `hello-app` assumption, unsafe profile path,
unknown adapter, stale README/plan, undeclared write, unchanged repeated failure,
or mismatched profile/revision returns an exact failing check or error code.

## Authority Used

- `CLAUDE.md` — source-repository authority and execution profiles.
- `PLANNING_OPERATING_MODEL.md` — outcome-first planning and adoption evidence.
- `docs/plans/60_loop_engineering_cleanroom_alpha.md` — external-root ownership.
- `docs/plans/61_cleanroom_deterministic_verified_loop.md` — independent loop
  and receipt boundaries.
- `docs/plans/113_governed_delivery_authentic_vertical.md` — accepted first
  vertical, stable example, and pre-made deferrals.
- `enforced_planning/cleanroom_alpha.py` — consumer inventory and placeholder
  materialization seam.
- `enforced_planning/governed_delivery.py` — current hard-coded task seam.

## Research

This is a local composition and portability question. The accepted first receipt,
current source, and a fresh second consumer provide more direct evidence than
additional web research. The authority list above records the exact code, plans,
and evidence reviewed before adopting this slice.

## Landscape And Prior Art

### Alternatives

1. **Treat the first receipt as portability proof** — rejected; one hard-coded
   profile does not establish configurability.
2. **Mutate a real existing project such as `llm_client` or `data-contracts`** —
   deferred; that creates adoption and ownership scope before the profile seam
   itself is known to work.
3. **Add a generalized plugin/runtime framework** — rejected for this slice;
   two validated source adapters and one generic behavioral contract are enough
   to expose the next seam.
4. **Extend the existing clean-room and governed-delivery path with one external
   profile** — adopted; it preserves the stable example and proves a different
   inventory, source adapter, command, output, and task repository.

### Project implications

Add only a validated profile seam, one observed adapter, generic checks, the
copied example, and exact receipt evidence. Preserve the default vertical and do
not broaden Enforced Planning into a model runtime or feedback platform.

**Refresh trigger:** Revisit shared contracts or a new top-level repository only
after the second receipt exposes a real cross-project consumer or distribution
boundary.

## Modality Assessment

| Part | Mode | Treatment |
|---|---|---|
| Profile schema, paths, commands, hashes | Deductive | Strict Pydantic validation and both-sign tests. |
| Adapter selection and baseline failure | Deductive | Known adapter registry; fail loud on unknown or incompatible source. |
| Real worker completion | Exploratory | Run once in a fresh external root and retain exact failures and fixes. |
| Colleague usability | Exploratory | Remains unclaimed; a second generated consumer is not colleague adoption. |

## Boundaries And Non-Goals

Enforced Planning owns the profile schema, two bounded source adapters, generic
behavior/document/plan checks, CLI, and receipts. The external clean-room owns
its inventory. The generated `status-cli` Git repository owns its source, task
plan, README, tests, and result commit.

This slice does not add self-improving policy, feedback automation, fleet
migration, a new top-level repository, `llm_client` integration, shared
`data-contracts` registration, arbitrary executable adapters, deployment,
release, dashboards, or generalized security/privacy hardening.

## Durable Contract

`consumer-config.json` selects the clean-room inventory.
`governed-task-profile.json` validates to the native governed-task contract and
selects one known source adapter. Preparation copies the validated contract into
the task repository; later probes and verification read only that stored copy.

Required invariants:

- project and file paths are root-relative, traversal-free, and match the
  clean-room inventory;
- durable commands store `python`, never a machine-local interpreter path;
- adapter selection is explicit and closed over known implementations;
- the requested command extends the default command and initially fails;
- README examples and behavioral checks derive from the stored profile;
- preparation and verification receipts include the canonical profile digest.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| `load_governed_task_profile` | optional JSON profile | validated path-neutral task contract | Enforced Planning | preparation CLI |
| source adapter | clean-room placeholder + profile | working default and failing requested baseline | Enforced Planning | coding agent |
| generic checks | stored profile + Git task state | behavior/plan/docs/scope facts | independent harness | coding agent/verifier |
| bound receipt | profile + baseline/result/framework | digest-bound terminal verdict | independent verifier | user/operator |

## Capability Adoption

**Disposition: extend.** Extend `enforced_planning.governed_delivery` and the
canonical clean-room consumer inventory. Do not introduce another materializer,
installer, planning framework, or verifier. The default Plan #113 example must
continue to pass through the same seam.

## Files Affected

- `enforced_planning/governed_delivery.py` (update)
- `scripts/governed_delivery.py` (update)
- `tests/test_governed_delivery.py` (update)
- `examples/cleanroom-ecosystem/status-cli-profile.json` (create)
- `examples/cleanroom-ecosystem/README.md` (update)
- `docs/evidence/plan62_status_cli_delivery_receipt.json` (create)
- `docs/plans/62_user_neutral_ecosystem_instantiation.md` (update)
- `docs/plans/62_user_neutral_ecosystem_instantiation_work_graph.json` (create)
- `docs/plans/CLAUDE.md` (update)
- `ROADMAP.md` (update)

## Plan

1. Add focused failing tests for an external `status-cli` profile, unsafe paths,
   unknown adapters, profile digest binding, and the unchanged default profile.
2. Generalize task paths, commands, outputs, README checks, and receipts around
   the validated stored profile. Add only the existing hello adapter and the new
   manifest-status adapter.
3. Add `prepare --profile` to the JSON CLI and document the copied-example path.
4. Materialize a custom one-project clean-room in a fresh external root; prepare
   and persist the initial failing probe.
5. As the real worker, create the generated consumer plan, implement `--json`,
   update the concise README, run its checks, and commit only declared paths.
6. Run the independent verifier, retain the portable receipt, reconcile plan and
   roadmap status, run terminal checks, publish, and close the lane.

## Required Tests

| Test | What it invalidates |
|---|---|
| Existing default prepare/verify | Generalization broke the stable `hello-app` vertical. |
| External status profile prepare | CLI or module still assumes the default inventory/task. |
| Unsafe profile paths/commands | Consumer configuration can escape or serialize local state. |
| Unknown/incompatible adapter | Preparation silently guesses how to replace a placeholder. |
| Profile digest mismatch | Receipt can certify a different contract than the one executed. |
| Existing progress and negative controls | Configurability weakened plan, docs, scope, or course correction. |
| Fresh authentic status run | Fixtures pass while a different real task cannot complete. |

## Acceptance Criteria

- [ ] The unchanged default profile still prepares and verifies the Plan #113
  `hello-app --name Ada` example.
- [ ] A copied JSON profile selects `projects/status-cli`, a different source
  adapter, source path, commands, outputs, title, and task id without source edits.
- [ ] Absolute/traversing paths, personal sentinels, unsafe commands, and unknown
  adapters fail loudly before Git initialization.
- [ ] The fresh status baseline preserves its default output and fails only the
  requested `--json` behavior.
- [ ] The real worker changes only source, concise README, one plan, and its plan
  index; the result is clean and committed.
- [ ] Default and `--json` outputs match the canonical example exactly.
- [ ] The same plan-authority, documentation, progress, self-report, portability,
  and independent-verifier controls pass for the second profile.
- [ ] The terminal receipt binds profile id/digest, framework, baseline, result,
  session, checks, and verdict without an external-root path.
- [ ] Focused tests, clean-room regressions, plan validation, and repository
  self-test pass on the exact integrated candidate.
- [ ] The licensed claim remains: two configured governed-delivery tasks have
  completed; colleague usability and autonomous policy improvement remain open.

## Authentic Evidence

Unobserved. Completion requires a fresh external root and a retained receipt.

## Failure And Replan Rules

| Failure | Required response |
|---|---|
| Generalization breaks `hello-app` | Restore compatibility before the second profile proceeds. |
| Profile needs arbitrary executable hooks | Stop at the concrete adapter boundary; do not add a plugin system. |
| Two probes repeat unchanged failure | Record a changed assumption and tactic before another probe. |
| Custom inventory cannot host preparation | Repair only the observed clean-room/profile seam. |
| A second consumer creates a real shared typed-contract owner | Record the seam; extraction remains a separate decision after this receipt. |

## Pre-Made Decisions

- Reuse Plan #62 rather than create a competing follow-on plan.
- Preserve `hello-app --name Ada` as the stable regression example.
- Use a custom generated `status-cli` repository, not an existing shared project.
- Use the current Codex session as the authentic worker; no paid model call.
- Keep native Pydantic contracts in Enforced Planning for this slice.
- Feedback-system work remains downstream of repeatable governed delivery.
