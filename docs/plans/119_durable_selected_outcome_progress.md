# Plan #119: Durable Selected Outcome Progress And Continuation

**Status:** Complete (observe-only current-head custody; portfolio admission and hard enforcement remain downstream)
**Type:** implementation (observe-only progress custody)
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "durable-selected-outcome-progress"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** pilot
**Overlays:** deductive, repository governance
**Blocked By:** #118
**Blocks:** Project Graph-bound product/maintenance lease admission and hard portfolio WIP enforcement

---

## Gap

**Current:** Plan #117 binds one immutable outcome scenario to an exact claimed
session, and Plan #118 preserves that binding across sanctioned runtime handoff
or replaces a stalled lineage through a causal restart. The selected scenario's
lease is nevertheless frozen at selection time. There is no command that can
append a later `OutcomeProgressReceiptV1`, no durable current-head lease, and no
way for selected pre-write observation or causal restart to consume evidence
produced after selection. A normal session-tracker refresh also preserves only
`outcome_selection`; it can erase the append-only transfer and restart histories
introduced by Plan #118. A selected lane can therefore retain its name while
silently losing either new progress or prior custody evidence.

**Target:** Add one strict append-only selected-progress transition stream to
the existing exact session tracker. Each transition binds the exact selected
binding and live claim, immutable receipt file bytes and typed receipt, exact
prior lease, and exact successor lease. Reconstruct the effective scenario and
current lease from the immutable selected scenario plus accepted transitions;
make selected pre-write observation, causal restart, and sanctioned session
handoff consume that reconstructed head. Preserve selection, progress,
transfer, and restart histories during ordinary tracker refresh. Keep ordinary
claim admission authoritative and add no second registry.

**Why:** An outcome lease that cannot change after real work is not a progress
control; it is a stale label. Portfolio-wide WIP admission would amplify that
defect by blocking or admitting projects from selection-time state rather than
current evidence. Durable current-head custody is therefore the last direct
state prerequisite before Project Graph can allocate and enforce product versus
maintenance outcome slots.

## User Outcome

Brian and his coding agents can select one outcome, record evidence-backed
progress as the work evolves, resume the same lane in a later runtime without
resetting its receipt lineage, and see the current lease—not the selection-time
lease—in the existing pre-write observation. Repeating an identical command is
byte-idempotent; a competing or stale receipt fails visibly.

## Canonical Behavioral Example

**Starting state:** One exact healthy claim has selected an immutable active
scenario with no post-selection receipts. A receipt file inside that worktree
binds the selected contract digest, the current last-receipt digest, one allowed
progress dimension, and revision-bound observation evidence.

**Action:** Invoke `outcome_continuation.py progress` for that exact claim and
receipt, repeat the exact command, then exercise selected pre-write observation.
In the lifecycle control, record a non-outcome receipt, hand off and resume the
same branch/worktree under a new exact session, and record a successor receipt
whose `prior_receipt_sha256` is the retained head.

**Expected observable result:** The first command appends one transition and
advances the current lease. The exact replay returns the retained transition
without changing tracker bytes. A stale-parent, changed-file, duplicate-ID, or
foreign-claim receipt is rejected without mutation. Selected pre-write reports
the effective scenario, current lease, and progress-head digests while leaving
the ordinary allow/deny result untouched. Session handoff changes exact runtime
identity but retains the progress chain, and the successor receipt extends that
same chain rather than starting over.

**Behavioral evidence:** At implementation revision `694620d4`, the real exact
Plan #119 owner claim selected `plan119-selected-base.json`, appended the strict
receipt `plan-119-current-head-custody`, advanced to current active lease
`19c53bb8`, and replayed without changing tracker digest `49231d04`. After the
ordinary projection was refreshed, selected pre-write retained ordinary
`allow/exact_live_claim` and reported one applied transition, effective scenario
`bb5f9410`, and `would_allow/active_in_scope`. Eighty-nine focused tests plus
Ruff and mypy passed, including recovery-required, tracker-refresh, causal
restart, and cross-session successor controls. The retained record is
`docs/evidence/plan119_durable_outcome_progress.json`.

**Failure signal:** A receipt is accepted against a stale parent; replay changes
tracker bytes; a tracker refresh erases custody history; session handoff loses
the current head; selected pre-write reports the base lease after progress;
restart ignores post-selection failure receipts; or any result is described as
hard enforcement, portfolio admission, independent review, or fleet adoption.

## References Reviewed

- `CLAUDE.md` — exact claims, worktree isolation, evidence, and closeout.
- `docs/plans/114_outcome_continuation_lease_enforcement.md` — receipt lineage,
  transition, admission, and recovery semantics.
- `docs/plans/117_durable_outcome_selection_binding_observe.md` — create-once
  selected scenario and ordinary-authority boundary.
- `docs/plans/118_causal_restart_lineage_and_session_handoff_observe.md` —
  restart and runtime-transfer custody contracts.
- `enforced_planning/outcome_selection.py` at `0a8c1005` — selected binding,
  transfer, restart, and pre-write resolution owners.
- `enforced_planning/session_contracts.py` at `0a8c1005` — reproduced refresh
  seam that preserves only `outcome_selection`.
- `project-meta@f6091b6b:policy/proposals/2026-08-20-outcome-continuation-lease-hard-gate.yaml`
  — approved outcome-continuation policy.
- `project-meta@a2349842:investigations/cross-project/2026-08-20-recurring-project-failure-modes.md`
  — calibrated circular-delivery and restart-laundering evidence.
- `project-meta@e2cb509c:learnings/entries/lrn-20260821T063558270519Z-bb1048ff9a.json`
  — Project Graph and lease-class prerequisites for portfolio admission.
- `project-meta@4db70b44:learnings/entries/lrn-20260821T071433993400Z-c03672c547.json`
  — an authentic stale pre-write projection showed that a registry-digest cache
  hit does not bind the producer revision or its claim-health semantics.

## Research

No web research is needed. The failure and owning seams are local, executable,
and revision-bound.

## Landscape And Prior Art

| Alternative | Boundary consequence | Disposition |
|---|---|---|
| Rewrite the selected scenario with new receipts | Breaks its immutable file and scenario digests and turns evidence history into mutable state. | Rejected. |
| Mutate `OutcomeSelectionBindingV1.lease_*` in place | Makes the binding internally disagree with its selected scenario and destroys create-once identity. | Rejected. |
| Store only the latest lease | Hides the receipts and prior states that explain how the lease changed. | Rejected. |
| Add a global outcome database | Duplicates the accepted claim-linked tracker and precedes Project Graph ownership design. | Rejected. |
| Append self-contained transitions in the existing tracker | Retains exact history, supports deterministic reconstruction, and composes with current locks and handoff. | Adopted. |
| Implement portfolio WIP admission first | Would enforce stale selection-time leases and let an arbitrary first writer choose the global slot. | Deferred immediately behind this plan. |

**Alternatives:** Mutate the base scenario or binding, retain only a latest
lease, add another registry, enforce portfolio admission first, or extend the
existing tracker with self-contained transitions. The table records why only
the final option preserves both immutable selection and inspectable progress.

**Project implications:** Extend the existing outcome-selection, pre-write,
tracker, restart, and handoff owners. Do not add a parallel registry or claim
surface. Treat Project Graph admission as the next consumer of the resulting
current-head lease rather than part of this implementation.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| selected progress append | exact live claim + selected tracker + strict receipt file | append-only receipt/prior-lease/successor-lease transition | `outcome_selection` progress owner | coding-agent outcome CLI |
| selected current-head reconstruction | immutable base scenario + transfer aliases + accepted progress history | effective scenario and current lease | `outcome_selection` resolver | pre-write observer, causal restart, session transfer |
| custody-preserving tracker refresh | refreshed session contract + existing custody fields | refreshed tracker with selection/progress/transfer/restart histories intact | `session_contracts` | session start and lifecycle updates |
| current-head selected observation | ordinary pre-write receipt + resolved effective scenario | advisory correlation with base/effective/head/lease digests | outcome pre-write observer | Brian and coding-agent sessions |

These are internal Enforced Planning capabilities. No LLM call is required;
the unit validates deterministic receipt lineage and custody rather than
classifying the semantic truth of evidence.

## Boundaries And Contracts

1. `OutcomeProgressTransitionV1` retains the exact selected binding snapshot and
   digest, receipt ref/file digest/model/digest, prior lease snapshot/digest,
   successor lease snapshot/digest, and timezone-aware recording time.
2. A receipt file must be inside the exact live claim worktree and validate as
   strict `OutcomeProgressReceiptV1`. Its contract and dimension must match the
   immutable selected contract, and its `prior_receipt_sha256` must equal the
   reconstructed current head.
3. `tracker.outcome_progress_transitions` is append-only. The current head is
   reconstructed by replaying transitions attached to the current binding or a
   sanctioned session-transfer ancestor of that binding. Causal-restart
   predecessor bindings are not aliases of the successor.
4. Exact accepted receipt-file replay is idempotent and performs no tracker
   write, including no timestamp change. A changed file, competing receipt with
   the same ID, forked parent, malformed history, or receipt already contained
   in the immutable base scenario fails with a stable error code.
5. `ResolvedOutcomeSelectionV1` carries the effective scenario and progress
   head. Selected pre-write still reopens and verifies the immutable base file,
   then evaluates the reconstructed effective scenario and records base,
   effective, lease, and head digests.
6. Ordinary pre-write claim admission, its receipt, native exit code, and
   enforcement mode remain authoritative. Plan #119 is observe-only.
7. Causal restart evaluates the reconstructed current predecessor lease and
   failure receipts. A base-active selection advanced to stalled may restart;
   post-selection evidence cannot be ignored by reverting to the base lease.
8. Sanctioned cross-session resume retains the entire progress stream. Its
   transfer receipt binds the effective lease and progress head, and a later
   receipt from the successor runtime extends the retained lineage.
9. Ordinary tracker refresh preserves the declared custody fields:
   `outcome_selection`, `outcome_progress_transitions`,
   `outcome_session_transfers`, and `outcome_selection_transitions`. Invalid
   field shapes fail rather than being silently copied or dropped.
10. This plan does not implement Project Graph ownership lookup, product versus
    maintenance lease classes, a one-product ceiling, hard pre-write blocking,
    independent review, installer/fleet rollout, deployment, release, or cost
    controls.

## Capability Adoption

**Disposition: extend existing owners.** Add progress contracts and mutation to
`outcome_selection.py`, reuse `transition_lease` and the existing claim/tracker
locks, expose one `progress` subcommand through the existing outcome CLI, and
extend selected pre-write correlation rather than adding a wrapper or registry.
Teach `session_contracts.py` to preserve all declared custody fields. Update
restart and transfer only where they consume the current progress head.

## Files Affected

- `enforced_planning/outcome_selection.py`
- `enforced_planning/outcome_prewrite_observation.py`
- `enforced_planning/session_contracts.py`
- `scripts/outcome_continuation.py`
- `tests/test_outcome_selection.py`
- `tests/test_outcome_prewrite_observation.py`
- `tests/test_session_contracts.py`
- `examples/owner-real-outcome-observe/plan119-selected-base.json`
- `examples/owner-real-outcome-observe/plan119-progress-receipt.json`
- `docs/evidence/plan119_durable_outcome_progress.json`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/119_durable_selected_outcome_progress.md`
- `docs/plans/119_durable_selected_outcome_progress_work_graph.json`
- `docs/plans/CLAUDE.md`
- `ROADMAP.md`

## Plan

### Critical Path Classification

| Increment | Class | Behavior or blocker changed |
|---|---|---|
| Append and reconstruct exact selected progress | `vertical` | A selected lease reflects evidence produced after selection rather than remaining a stale label. |
| Consume the current head at pre-write, restart, refresh, and runtime handoff | `vertical` | The existing agent entrypoints continue one evidence lineage instead of resetting it. |
| Retain one owner-real receipt and observation | `vertical` | The mechanism is exercised through the same boundary an agent uses, not only fixtures. |
| Project Graph portfolio admission | deferred direct blocker | It follows immediately after current-head lease state is trustworthy. |

## Work Units

### OPRG-01 — Durable current-head progress custody

Implement the strict transition, append/replay/conflict behavior, current-head
reconstruction, tracker refresh preservation, CLI, and focused unit controls.

Pass when:

- one exact receipt advances the expected lease and is retained append-only;
- exact replay is byte-idempotent;
- stale parent, duplicate ID, changed file, tamper, and foreign claim fail
  without mutation; and
- existing Plan #114/#117/#118 behavior remains green.

### OPRG-02 — Selected observation and same-lane continuation

Make selected pre-write, causal restart, and sanctioned runtime handoff consume
the current head. Exercise recovery-required and recovery-to-active decisions,
tracker refresh, restart from appended stalled evidence, and post-handoff
successor receipt lineage.

Pass when:

- selected observation reports the effective lease and receipt chain;
- ordinary decision and exit behavior remain unchanged;
- tracker refresh retains every custody field; and
- a successor runtime extends the predecessor receipt head.

### OPRG-03 — Owner-real evidence and truthful closeout

Select the Plan #119 base scenario in the real claimed lane, append one authentic
behavioral receipt, observe it through the ordinary selected pre-write path,
retain revision-bound evidence, and reconcile guide/plan/graph. The Plan #110
owner released the shared plan index and roadmap at `9f37b041`; reconcile those
surfaces only after the executable unit is accepted.

Pass when the retained evidence binds claim, tracker, binding, receipt,
transition, effective scenario, lease, ordinary receipt, selected correlation,
commands, and exact candidate revision without claiming enforcement or fleet
adoption.

## Verification Strategy

Focused invalidation budget:

1. Model and mutation tests in `tests/test_outcome_selection.py`.
2. Effective selected-observation tests in
   `tests/test_outcome_prewrite_observation.py`.
3. Tracker preservation controls in `tests/test_session_contracts.py`.
4. Existing continuation/restart/session-transfer regression subset.
5. One real exact-session selection, progress append, replay, and selected
   pre-write observation from the same entrypoints an agent uses.

## Accepted Evidence

- Implementation candidate: `694620d4db7318b749b0123a09534daf6dd39871`.
- Exact selection binding: `2237689a37522f4aaea1b4392f1736c261da915beffbc3ec62dc273e74782ef8`.
- Exact receipt and transition: `3d7b3c9c` and `de207305c`; successor lease
  `19c53bb8` remained active.
- Exact replay left tracker bytes at
  `49231d043596354ad7d6fc043c092878caed95b54af5b9f823ff36e9acb7fec1`.
- Authentic selected pre-write retained ordinary receipt
  `prewrite_c7fcf87237d34dfdbdde7f6a3c984518` as
  `allow/exact_live_claim` and correlated it as
  `ocor-101609502b1b40b59bdb0b86cf6eaed0`,
  `would_allow/active_in_scope`.
- Focused verification: 89 tests passed; Ruff and mypy passed at the receipt's
  source revision.
- A first authentic observation exposed a stale cached claim-health projection.
  It was refreshed and rerun rather than omitted; the limitation and durable
  Project Meta learning are retained in the evidence record.

Broad suite, installer propagation, downstream repository adoption, portfolio
admission, and release checks are outside this development increment.

## Acceptance Criteria

1. One exact post-selection receipt advances the lease, is retained with exact
   prior/successor snapshots, and replays without changing tracker bytes.
2. Forked, conflicting, tampered, foreign, or base-duplicate receipts fail
   before tracker mutation with stable machine-readable reasons.
3. Selected pre-write evaluates the effective scenario/current lease while the
   ordinary claim decision and exit behavior remain unchanged.
4. Tracker refresh and sanctioned cross-session resume retain the entire
   progress, transfer, restart, and selection custody lineage; the successor
   runtime can extend the retained receipt head.
5. Causal restart uses post-selection stalled or parked evidence rather than
   the stale base lease.
6. One real Plan #119 selection, progress append, exact replay, and selected
   observation is retained at the accepted candidate revision.
7. Focused Plan #114/#117/#118 regressions pass and all evidence remains
   explicit that portfolio admission and hard enforcement are not implemented.

## Promotion Boundary

Acceptance proves durable current-head outcome evidence within one selected,
claim-linked Enforced Planning lane and lossless sanctioned runtime continuation.
It does not prove semantic truth of receipts, independent reviewer identity,
Project Graph ownership, portfolio slot allocation, hard denial, or fleet use.
The immediate next design frontier is Project Graph-bound product/maintenance
lease classification and deliberate portfolio admission using this current head.

## Terminal Closeout

Merge OPRG-01 through OPRG-03 as one coherent observed pilot after focused
evidence passes. The shared paths were released by Plan #110 at `9f37b041`, so
the final increment reconciles the Plan #119 index and roadmap before merging.
Push, merge, close the sanctioned worktree/claim, and retain the projection
producer-drift finding through Project Meta's typed learning register.
