# Plan #129: Portable Roadmap Handoff Data-Contract Pilot

**Status:** Planned
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "portable-cross-project-contracts"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** Company Planning consumer snapshot and explicit portfolio validation

`trace_evaluable: false # deterministic contract export and compatibility behavior`

## Gap

**Current:** `RoadmapGoalHandoff` is a strict Pydantic producer model and Company
Planning already consumes its JSON-Schema counterpart, but the relationship is
not represented by a portable `contract-snapshot-v1` artifact. Compatibility
therefore depends on manual comparison and repository-local knowledge.

**Target:** Enforced Planning commits a deterministic producer snapshot for the
real `RoadmapGoalHandoff` seam. The snapshot is derived from the authoritative
local model, contains no runtime registry state or machine-local paths, and can
be consumed by `data_contracts` portfolio validation.

**Why:** This proves broader data-contract adoption on an authentic cross-project
boundary without moving the domain model into shared infrastructure or adding a
private Inside Success runtime dependency to this public framework.

## User Outcome

Brian can change the roadmap handoff model and immediately see whether its
committed cross-project contract snapshot is stale before downstream validation.

## Canonical Behavioral Example

**Starting input/state:** The committed snapshot matches
`RoadmapGoalHandoff.model_json_schema()`.

**Action:** Run the snapshot checker, then add a producer field without refreshing
the snapshot.

**Expected observable result:** The first check passes and the stale artifact
check exits nonzero with the exact snapshot path; writing refreshes deterministic
bytes that the shared portfolio validator can load.

**Behavioral evidence:** Focused tests plus the committed snapshot.

**Substrate/process evidence:** `contract-snapshot-v1`, exact producer/consumer
metadata, repeat-render byte equality, and shared portfolio validation downstream.

**Failure signal:** A stale model passes, runtime counters/timestamps or absolute
paths enter the artifact, or the public package requires the private custody fork.

## References Reviewed

- `enforced_planning/planning_handoff.py` — authoritative strict producer model.
- `tests/test_planning_handoff.py` — existing handoff validation and CLI coverage.
- `data_contracts` Plan #14 and PR #5 — deterministic snapshot and explicit
  portfolio contract.
- Company Planning `contracts/roadmap-goal-handoff.schema.json` — authentic
  consumer schema; current structural compatibility probe passes.
- `CLAUDE.md` — worktree, plan, and smallest-contract governance.
- Memory recall skipped: the current task supplied direct repository evidence and
  no retained decision was needed.

## Research Basis For This Slice

No additional research beyond References Reviewed.

## Landscape And Prior Art

**Alternatives:** A runtime dependency on the private custody fork would make the
public framework harder to install. Copying the domain model into `data_contracts`
would invert ownership. A deterministic dependency-free exporter preserves local
model authority while using the shared versioned artifact format.

**Project implications:** Enforced Planning owns the producer model and snapshot;
`data_contracts` owns snapshot validation; Company Planning owns its consumer
schema and snapshot. Revisit the dependency choice if the portable snapshot API
is released from the public `data-contracts` upstream.

**Refresh trigger:** A new snapshot schema version, public package release, or
consumer incompatibility.

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| snapshot derivation | Deductive | source model and wire shape are explicit | deterministic renderer and exact artifact test |
| consumer compatibility | Deductive | both JSON Schemas exist | explicit downstream portfolio pipeline |
| broader rollout | Exploratory | useful seams vary by project | stop after this authentic producer/consumer pilot |

## Capabilities

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|---|---|---|---|---|---|
| `enforced-planning.roadmap-goal-handoff` | none | `RoadmapGoalHandoff` | enforced-planning | company-planning | free |

### Capability Validation

- [x] Output schema is defined by a strict Pydantic model with field descriptions.
- [ ] Capability has an explicit definition-only registry snapshot entry.
- [ ] Producer and consumer schemas pass the declared portfolio pipeline.
- [x] Existing handoff fixtures exercise the capability journey.

## Capability Adoption

**Disposition: extend.** Extend the existing `RoadmapGoalHandoff` producer and
the shared `contract-snapshot-v1` transport. Do not create another handoff model,
registry service, discovery mechanism, or authority source.

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| producer snapshot | fully_specifiable_now | local Pydantic schema is authority | exact artifact/check tests pass | Enforced Planning snapshot |
| consumer edge | fully_specifiable_now | committed Company Planning schema exists | shared portfolio pipeline passes | Company Planning snapshot |
| public package dependency | conditional | dependency-free adapter preserves portability | revisit after public upstream release | optional later simplification |
| broader rollout | exploration_required | only authentic seams qualify | stop after two-project pilot | separate portfolio inventory |

## Reassessment Contract

- **Triggers:** snapshot format changes, consumer incompatibility, public
  `data_contracts` release, or two consecutive non-outcome increments.
- **Autonomous action:** preserve domain ownership, update adapters, and keep
  discovery explicit.
- **Plan revision required:** moving the domain model, adding a runtime service,
  or changing the handoff wire contract.
- **Human decision required:** publication policy or a breaking handoff version.
- **Stopping rule:** local both-sign checks, existing handoff tests, self-test,
  and the declared cross-project pipeline all pass.

## Files Affected

- `enforced_planning/data_contract_snapshot.py` (create)
- `contracts/data-contracts.snapshot.json` (create)
- `tests/test_data_contract_snapshot.py` (create)
- `docs/plans/129_data_contract_pilot.md` (create/modify)
- `docs/plans/129_data_contract_pilot_work_graph.json` (create)
- `docs/plans/CLAUDE.md` (modify)

## Plan

### Critical Path Classification

**Critical-path classification: vertical.** The model-to-artifact checker is the
smallest observable producer slice; portfolio validation is the corresponding
consumer slice.

| Increment | Class | Behavior or named blocker changed |
|---|---|---|
| deterministic producer export/check | `vertical` | model drift becomes locally observable |
| Company Planning snapshot and portfolio edge | `vertical` | real cross-project compatibility becomes executable |

### Steps

1. Define the dependency-free deterministic producer snapshot renderer and CLI.
2. Commit the exact snapshot derived from `RoadmapGoalHandoff`.
3. Add both-sign tests for current, stale, repeatable, and portable output.
4. Validate the downstream Company Planning consumer through an explicit
   portfolio manifest, then record the result without claiming broader rollout.

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_data_contract_snapshot.py` | `test_committed_snapshot_matches_model` | current model and committed artifact are identical |
| same | `test_snapshot_render_is_deterministic_and_portable` | repeated bytes match and local/runtime state is absent |
| same | `test_check_fails_for_stale_snapshot` | stale artifacts fail loud |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `tests/test_planning_handoff.py` | existing handoff semantics remain unchanged |
| `python scripts/self_test.py` | framework-wide governed verification remains green |

## Acceptance Criteria

1. The committed snapshot is derived from the authoritative local model.
2. Repeated rendering produces byte-identical output.
3. The artifact contains no timestamps, counters, errors, or absolute paths.
4. Check mode fails nonzero when the committed snapshot is stale.
5. Existing handoff tests and the framework self-test pass.
6. Company Planning's explicitly declared consumer edge passes shared portfolio
   validation before the pilot is called complete.

## Documentation Updates

Update this plan and the plan index. The snapshot itself is the machine-readable
integration artifact; do not duplicate the handoff's domain documentation.

## ADR

No ADR: this is a reversible artifact adapter around an existing authority seam.

## Implementation Approval

Authorized by Brian's 2026-08-29 approval to apply data contracts more broadly
and consistently across projects and proceed autonomously.
