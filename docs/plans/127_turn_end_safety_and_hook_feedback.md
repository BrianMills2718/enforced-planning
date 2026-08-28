# Plan #127: Turn-End Safety and Hook Feedback Recurrence

**Status:** In Progress
**Status ID:** in_progress
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "empirical-ecosystem-improvement"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** quiet truthful agent turn endings and evidence-backed lifecycle-hook iteration

`trace_evaluable: false # deterministic lifecycle and reporting behavior`

## Gap

**Current:** Plan #126 at `8027b6d` refreshes the digest-bound claim projection
on canonical claim mutations, but a process can still terminate after the claim
write and before that derived refresh. The shared coordination hook still calls
an ordinary Codex or Claude `Stop` event “repository closeout,” blocks that turn
when the derived projection is stale or missing, and performs a synchronous
heartbeat plus full projection rebuild during `SessionStart`. With 1,512 registry
YAML files (1,473 completed), a fresh native-shaped start took 9.47 seconds while
projection construction alone took about 3.5 seconds. The Codex integrity guard
correctly rejects one corrupt rollout at physical line 28 / byte 294787 and accepts
a genuinely new session, but recovery bundle identity follows the growing rollout
digest and therefore creates another full bundle when the same incident is retried
after the host appends records. Content-free hook receipts exist, including started
receipts left without completion when hooks are interrupted, but have no recurrence
report. Actual lane closure remains a separate strict `session-close` command.

**Target:** A malformed current session still fails safely while a genuinely fresh
session starts normally. Repeated starts of one corrupt session reuse one stable
incident bundle even if its rollout keeps growing. `SessionStart` performs no
unbounded synchronous heartbeat/projection rebuild and stays comfortably below its
native timeout with a completed-claim-heavy registry. Ordinary response yield is
named and treated as a turn-end repository safety check. A stale projection is
repaired from the canonical claim registry within an explicit bound when practical;
projection-only unavailability after bounded repair degrades to a visible,
content-free warning rather than a repeated Stop denial. Known dirty state and active
mailbox requests still block when their required evidence is available. Pre-write
claim enforcement and `session-close` retain their existing fail-closed contracts.
Existing receipts feed one recurrence report that steps down to exact receipt IDs
and points to Plan #111's ecosystem-feedback command for disposition.

**Why:** A derived-cache race must not masquerade as unfinished user work or force
the user through repeated internal cleanup turns. Conversely, weakening mutation or
lane-close gates would hide real write custody problems. The existing receipts only
support improvement when they can be aggregated and traced back to concrete episodes.

## User Outcome

An operator can end an ordinary agent turn without being trapped by a stale claim
projection, can still see and fix real dirty-work or mailbox blockers, and can run one
command to identify recurring lifecycle-hook failures with exact receipt evidence.

## Canonical Behavioral Example

**Starting input/state:** A corrupt rollout that continues growing, a genuinely fresh
rollout, a completed-claim-heavy registry, a valid `Stop` payload, one intentionally
stale pre-write claim projection, a clean touched repository, and two prior completed
hook receipts with the same blocking reason.

**Action:** Run repeated integrity starts for the corrupt and fresh sessions, run a
native-shaped `SessionStart`, interrupt one fixture mutation between canonical claim
and projection writes, run the coordination hook, then run the hook-feedback report.

**Expected observable result:** The corrupt session remains blocked and names the same
recovery incident on repeat; the fresh session passes; startup completes below the
configured timeout without heartbeat/projection mutation; the interrupted derived
write cannot permanently block turn end; the hook repairs a bounded stale projection
and permits the turn without “closeout” language. The report marks the repeated reason
as recurrent and lists its exact receipt IDs. A separate dirty-repository control still
blocks, and a stale pre-write claim gate plus unsafe `session-close` still fail closed.

**Behavioral evidence:** Observed in a subprocess native-shaped Stop replay with a
claim written after projection generation; the hook repaired under the registry lock,
emitted no denial, and a strict digest-bound reload returned the new claim. A real
SessionStart against the completed-claim-heavy canonical registry completed in 0.21s
(hook receipt elapsed 12.035ms) without heartbeat or projection mutation.

**Substrate/process evidence:** Focused both-sign tests plus one native-shaped hook
replay against an isolated claim registry and receipt directory.

**Failure signal:** Any stale-projection Stop denial, any use of “repository closeout”
for ordinary response yield, a dirty-work false allow, weakened pre-write/session-close
control, or a recurrence summary that cannot step down to exact receipt IDs.

## References Reviewed

- `CLAUDE.md` — source-repository authority and lifecycle boundaries.
- `scripts/coordination_hook.py` — current Stop, repository-state, projection, mailbox,
  and receipt path.
- `scripts/hook_receipts.py` — existing privacy-reduced invocation receipts.
- `enforced_planning/prewrite_claim_projection.py` — digest-bound projection builder.
- `enforced_planning/coordination_claims.py` — canonical claim mutation and projection
  refresh owner.
- `scripts/session_close.py` and `enforced_planning/session_lifecycle.py` — actual strict
  lane-close contract.
- `docs/plans/126_atomic_projection_refresh.md` and commit `8027b6d` — root mutation-side
  repair already merged.
- `docs/plans/111_ecosystem_feedback_loop.md` — existing actionable-feedback transport;
  this plan must consume rather than duplicate it.
- `tests/test_coordination_hook.py`, `tests/test_coordination_messages.py`, and
  `tests/test_hook_receipts.py` — current behavioral controls.
- Fresh runtime evidence on 2026-08-28: the old and new rollout files, exact-session
  mailbox, claim registry, projection builder, hook receipts, and native-shaped hook
  replays were inspected directly; no prior transcript assertion is treated as authority.

## Research Basis For This Slice

No additional research beyond References Reviewed. Official OpenAI documentation did
not expose this custom local hook chain; the decision is based on installed configuration,
source, receipts, and reproduced runtime behavior.

## Landscape And Prior Art

**Alternatives:**

1. Keep blocking every Stop on projection drift — rejected because ordinary response
   yield is not lane closure and the real incident repeated after successful refreshes.
2. Fail open for every repository error — rejected because a known dirty session delta
   is a real recoverability failure.
3. Add a second feedback database — rejected because Plan #111 already owns actionable
   feedback transport and hook receipts already own content-free episode evidence.
4. Repair stale projection state, step down only projection-unavailability to warning,
   and aggregate existing receipts — selected as the narrow owned-seam extension.

**Project implications:** The portable terminology distinguishes `turn_end`,
`progress_checkpoint`, `agent_rotation_handoff`, `lane_close`, and `goal_complete`.
Only `turn_end` behavior changes here. Existing receipt files remain valid; reports
accept legacy `repository_closeout_*` reason codes as historical inputs.

**Refresh trigger:** Revisit if Codex or Claude changes native Stop/SessionEnd semantics,
if a real dirty-work escape is observed, or if Plan #111 changes feedback identity.

**Decision method:** Contract and failure-mode reasoning plus both-sign replay; no
multi-implementation benchmark is needed.

## Capability Adoption

**Disposition: extend.** Extend existing capabilities. `codex_session_integrity` remains the
sole integrity/recovery owner; the digest-bound claim projection remains the derived
authority cache; `hook_receipts` remains the content-free episode store; and Plan #111
remains the only actionable ecosystem-feedback transport. Consumer adoption is proven
through the configured native hooks plus authentic old/fresh `SessionStart` and `Stop`
replays, not isolated unit tests alone.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| stable session recovery incident | corrupt rollout plus first integrity issue | one reusable evidence bundle | `codex_session_integrity` | configured integrity hook and operator handoff |
| bounded advisory lifecycle read | native lifecycle payload plus derived claim projection | fast mailbox/start or turn-end allow/warning/block | coordination hook | Codex and Claude lifecycle adapters |
| hook recurrence report | existing content-free started/completed receipts | grouped reasons plus exact receipt IDs | hook receipt reporter | Plan #111 ecosystem-feedback command and operator |

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| Corrupt versus fresh rollout integrity | fully_specifiable_now | Integrity issue identity comes from the first malformed physical record; recovery never edits host persistence | Complete when a grown corrupt fixture reuses its first bundle and a fresh fixture passes | integrity module, focused tests, authentic replay evidence |
| Startup latency | fully_specifiable_now | SessionStart is advisory and must not synchronously heartbeat or rebuild the claim projection | Complete when a roughly 1,500-completed-claim fixture and authentic fresh start remain comfortably below timeout | coordination hook and startup tests |
| Projection crash window | fully_specifiable_now | Canonical claim mutation stays authoritative; derived projection may lag after termination | Complete when injected interruption cannot permanently deny ordinary Stop while pre-write and lane close deny | coordination hook, pre-write controls, lifecycle controls |
| Recurrence usefulness | exploration_required | Existing content-free receipts are grouped by stable hook/event/decision/reason/revision dimensions | Stop after exact receipt IDs support one Plan 111 disposition without copying content | recurrence report and operator guide |

## Reassessment Contract

- **Triggers:** the first authentic post-change `SessionStart`; any repair exceeding
  the configured native hook budget; two non-outcome increments; or a negative control
  showing dirty work, mailbox debt, pre-write authority, or lane closure became permissive.
- **Autonomous action:** preserve useful work and switch to bounded projection-only
  degradation for ordinary advisory/turn-end checks when a full repair cannot fit the
  hook budget; keep canonical mutation and closure gates strict.
- **Plan revision required:** a material change to recovery incident identity,
  lifecycle failure behavior, receipt schema, feedback owner, or claimed write scope.
- **Human decision required:** a scope fork, external/fleet mutation, irreversible
  publication, or spend boundary not already authorized.
- **Stopping rule:** stop after focused both-sign tests, framework self-test, and one
  authentic fresh-session/startup plus turn-end replay pass at the exact candidate.

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Turn-end versus lane-close semantics | Deductive | Native events and mutation boundaries are explicit. | Specify exact failure behavior and both-sign tests. |
| Projection repair | Deductive | Canonical registry and derived projection have digest contracts. | Bounded repair followed by explicit degraded behavior. |
| Feedback recurrence threshold | Exploratory | Useful thresholds depend on observed receipt volume. | Default to two exact repeated failures; expose the threshold as a report argument. |

**Exploratory readout:** Counts and exact receipt IDs by hook, event, decision, reason,
and hook revision.

**Step-down path:** Every aggregate contains bounded receipt references; operators can
record one selected episode through `ecosystem-feedback` with those references.

## Files Affected

- `scripts/coordination_hook.py` (modify)
- `scripts/codex_session_integrity.py` (modify)
- `scripts/codex_session_integrity_hook.py` (modify only if hook output needs the stable incident identity)
- `scripts/hook_receipts.py` (modify)
- `scripts/hook_feedback_report.py` (create)
- `Makefile` (modify)
- `tests/test_coordination_hook.py` (modify)
- `tests/test_codex_session_integrity.py` (modify)
- `tests/test_coordination_messages.py` (modify only if native-shaped helper coverage requires it)
- `tests/test_hook_receipts.py` (modify)
- `docs/guides/HOOK_LIFECYCLE_AND_FEEDBACK.md` (create)
- `docs/plans/126_atomic_projection_refresh.md` (update completed truth)
- `docs/plans/127_turn_end_safety_and_hook_feedback.md` (update evidence/status)
- `docs/plans/CLAUDE.md` (update queue)
- `ROADMAP.md` (update Phase 9 maintenance route)

## Plan

## Critical Path Classification

**Critical-path classification: vertical.** The visible vertical is a corrupt session
remaining safely stopped while a genuinely fresh session starts quickly and an
interrupted derived projection cannot trap ordinary response yield.

| Increment | Class | Behavior or named blocker changed |
|-----------|-------|-----------------------------------|
| Stale-projection Stop replay and narrow repair | `vertical` | Ordinary turn can end without a derived-cache denial. |
| Dirty/mailbox/pre-write/session-close controls | `direct_blocker` | Proves the repair did not weaken real boundaries. |
| Hook receipt recurrence report | `vertical` | Existing telemetry becomes an inspectable improvement input. |
| Terminology and operator guide | `enabler` | Keeps future agents from conflating turn, checkpoint, handoff, and closure. |

### Steps

1. Add failing controls for stable corrupt-session incident reuse, a fresh-session
   pass, completed-claim-heavy startup, stale Stop repair, interruption between claim
   and projection writes, projection-repair failure warning, dirty Stop denial, and
   unchanged pre-write/session-close strictness.
2. Give recovery bundles a stable corruption-incident identity and make `SessionStart`
   advisory/read-only with respect to claim heartbeats and projection refreshes.
3. Introduce a projection-specific exception, bounded repair/safe-degradation path,
   and turn-end terminology. Preserve compatibility aliases where external imports may exist.
4. Add strict receipt loading and recurrence grouping with exact receipt references,
   legacy reason compatibility, JSON output, and a Make target.
5. Document lifecycle vocabulary and the explicit bridge from a recurrent receipt
   group to Plan #111's `ecosystem-feedback record` command.
6. Run focused tests, framework self-test, and the canonical native-shaped replay;
   record exact evidence and update status.

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_coordination_hook.py` | `test_stop_repairs_stale_projection_before_turn_end_check` | Stale derived state self-repairs without denial. |
| `tests/test_coordination_hook.py` | `test_stop_warns_when_projection_repair_remains_unavailable` | Projection-only failure is visible but not a Stop block. |
| `tests/test_coordination_hook.py` | `test_session_start_skips_heartbeat_with_large_completed_registry` | Startup does not rebuild the projection and remains below its budget. |
| `tests/test_coordination_hook.py` | `test_interrupted_claim_projection_write_does_not_permanently_block_stop` | Crash-window stale state degrades or repairs at ordinary turn end. |
| `tests/test_codex_session_integrity.py` | `test_recovery_bundle_reuses_stable_incident_after_rollout_growth` | One corrupt session does not copy each larger rollout. |
| `tests/test_codex_session_integrity.py` | existing clean-session hook control | A genuinely fresh rollout passes. |
| `tests/test_coordination_messages.py` | existing dirty-repository cases | Known dirty session delta remains blocking. |
| `tests/test_prewrite_claim_projection.py` | existing stale projection cases | Mutation authority stays fail closed. |
| `tests/test_session_lifecycle.py` | existing unsafe close cases | Actual lane closure stays fail closed. |
| `tests/test_hook_receipts.py` | `test_hook_feedback_report_groups_recurrence_and_steps_down` | Recurrent groups expose exact receipts. |
| `tests/test_hook_receipts.py` | `test_hook_feedback_report_rejects_invalid_completed_receipt` | Malformed evidence fails loud. |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_coordination_hook.py tests/test_coordination_messages.py` | Turn and mailbox behavior unchanged outside the repair. |
| `tests/test_prewrite_claim_projection.py tests/test_session_lifecycle.py` | Strict mutation and lane-close boundaries preserved. |
| `tests/test_ecosystem_feedback.py` | Feedback transport remains the sole actionable owner. |

## Acceptance Criteria

- [x] A stale projection cannot produce a repeated ordinary Stop denial when the
  canonical registry is readable.
- [x] A corrupt current session fails safely, a genuinely fresh session passes, and
  repeated corrupt-session starts reuse one stable recovery incident after rollout growth.
- [x] `SessionStart` performs no synchronous heartbeat/projection rebuild and remains
  comfortably below its timeout with approximately 1,500 completed claims.
- [x] Interruption after a canonical claim write but before projection refresh cannot
  permanently block ordinary turn end; mutation and lane-close gates remain fail closed.
- [x] Projection-only unavailability after bounded repair warns and writes a receipt;
  it does not call ordinary response yield “closeout.”
- [x] Known dirty work and active mailbox requests still deny Stop.
- [x] Pre-write claim checks and `session-close` retain fail-closed behavior.
- [x] One report groups content-free receipts by stable dimensions, flags recurrence,
  and lists exact receipt IDs without copying prompt or response content.
- [x] The guide defines turn end, checkpoint, agent rotation/handoff, lane closure,
  goal completion, and the feedback disposition route.
- [x] Focused tests (170 passed), `python scripts/self_test.py`, and the authentic
  isolated replay pass.

## Open Questions

- [x] Should every Stop failure fail open? — **RESOLVED:** No. Only derived projection
  unavailability steps down after bounded repair; known dirty and mailbox failures block.
- [x] Should recurrence reporting create feedback automatically? — **RESOLVED:** No.
  Receipts contain episode evidence; Plan #111 requires explicit semantic fields and owns
  feedback disposition.

## Notes

This plan changes no user data, deployment, credential, external publication, or
downstream repository. Broader installed-repo propagation is separately triggered only
if the canonical source repair proves useful and installer adoption is requested.
