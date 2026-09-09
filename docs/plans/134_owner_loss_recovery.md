# Plan #134: Resume-First Owner-Loss Recovery

**Status:** In Progress
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "prevent-owner-loss-and-false-serialization"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** [future] low-friction recovery from stale or dead claim owners

`trace_evaluable: false # deterministic claim, process, timer, and Git-worktree behavior`

---

## Gap

**Current:** Every governed writer gets a distinct linked worktree, but claim
admission still treats overlapping repository-relative paths as a hard conflict
even when the claims point at different physical worktrees. The installed
continuity timer is active in native owner-resume mode and retries exact
top-level Codex threads, but successor launch is disabled. Spawned-agent
threads are intentionally not queue-resumable. A quiet, dead, or unreachable
owner can therefore leave a logically overlapping claim that serializes a new
isolated lane even though Git already provides the physical write isolation.

**Target:** Keep resume-first prevention, but classify conflicts by the actual
mutation surface. Two live claims for the same physical worktree, canonical
checkout, or explicitly shared/non-Git state remain hard-exclusive. Claims for
different linked worktrees in the same Git repository report an advisory
integration overlap and do not prevent the new claimed lane from starting.
The status/checker surface reports the lifecycle action (`owner_resume_queued`,
`owner_resume_exhausted`, `isolated_recovery_available`, or `hard_conflict`)
instead of presenting bare `stale` as an ownership decision.

**Why:** A worktree is the physical write boundary. Treating a path that exists
in two different worktrees as one concurrently writable file confuses future
merge risk with immediate filesystem corruption. Preserve the old branch and
claim, let Git expose any later content conflict, and reserve hard blocking for
surfaces where isolation is actually absent.

## User Outcome

When an agent disappears, the system first attempts to resume its exact thread.
If that does not restore progress, another agent can start an independently
claimed linked worktree without deleting, killing, or stealing the predecessor
lane. The operator sees one actionable disposition rather than having to infer
meaning from `stale`.

## Canonical Behavioral Example

**Starting state:** Claim A owns `src/adapter.py` on branch/worktree A. Its owner
has stopped progressing. Claim B requests the same repository-relative path on
branch/worktree B. Both worktrees are valid linked Git worktrees of the same
canonical repository and neither claim declares shared state.

**Action:** The continuity sweep attempts the exact owner resume. Claim B then
uses the ordinary sanctioned worktree/claim entrypoint.

**Expected observable result:** Claim B is admitted with an
`isolated_worktree_overlap` advisory naming Claim A and its lifecycle state.
Both claims remain intact and write only inside their own physical worktrees.
A same-worktree request remains denied. A shared-state request remains denied.
No process is killed and no custody transfer is inferred from heartbeat age.

**Failure signal:** A distinct linked worktree is still blocked solely because
its repository-relative paths overlap; the same physical checkout becomes
multi-writer; a canonical checkout or shared-state surface becomes advisory;
the predecessor branch/claim is deleted; or silence alone transfers custody.

## Evidence Reviewed

- Live host probe at 2026-09-09T17:53Z: the user timer is enabled and runs
  `native_resume_delivery`; `successor_launch_enabled` is false.
- `enforced_planning/session_continuity.py` and `scripts/session_continuity.py`
  already provide activity classification, bounded exact-thread retry,
  progress fingerprints, consumption receipts, successor offers, and a
  fail-visible spawned-agent circuit breaker.
- `enforced_planning/session_process_fencing.py` requires an exact live Codex
  process generation before custody transfer; it cannot safely prove the
  identity of an already-dead predecessor.
- `enforced_planning/coordination_claims.py` owns path-overlap admission and
  currently does not distinguish physical worktree identity.
- Plan #110 requires path-local waits not to become whole-goal blockers; Plan
  #132 preserves strict overlap today and documents false serialization from
  overbroad claims.
- Pending Project Meta proposals
  `2026-09-02-blocking-claims-should-be-advisory-by-default.yaml` and
  `2026-09-01-prevent-authorized-work-abandonment.yaml` record the same policy
  direction but are not treated as implementation authority.

## Landscape And Decision

| Alternative | Disposition | Reason |
|---|---|---|
| Automatically take over a stale claim | Rejected | Silence cannot identify or fence an already-dead predecessor process, and custody transfer is unnecessary for isolated work. |
| Delete/prune the predecessor claim | Rejected | It discards useful recovery state and can race a merely quiet owner. |
| Enable native successor launch as the only repair | Deferred | It helps verified top-level live predecessors but does not handle already-dead or spawned-agent owners. |
| Admit distinct linked worktrees with an integration advisory | Selected | Uses the isolation already created for every agent, preserves both histories, and leaves content reconciliation to Git. |

This plan changes claim admission, not branch merge policy. It creates no new
registry and no automatic cleanup mechanism.

## Design Contract

1. Normalize each claim's `repo_root` and `worktree_path`; verify linked
   worktree membership using Git metadata before assigning advisory status.
2. A write-path overlap is hard when either claim lacks a trustworthy physical
   worktree identity, both resolve to the same worktree, either targets the
   canonical checkout, or either declares an explicitly shared/non-Git surface.
3. Otherwise, overlapping repository-relative write paths across distinct
   linked worktrees produce a typed `isolated_worktree_overlap` interaction but
   are excluded from hard-conflict admission.
4. The new claim retains the advisory interaction in machine-readable output;
   existing callers that only inspect the allow/deny result remain compatible.
5. Health/liveness labels remain observational. They may improve the suggested
   action but are not required to make distinct physical worktrees safe and do
   not transfer or erase custody.
6. Pre-write authorization remains exact-session and exact-worktree bound. An
   advisory overlap cannot authorize writes in the predecessor worktree.
7. The continuity timer keeps bounded owner-first resume enabled. This slice
   does not automatically kill or transfer an owner process.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| physical conflict classification | two normalized live claims plus verified Git worktree identities | hard conflict or typed isolated-worktree advisory | `coordination_claims` | claim creation, check/status surfaces |
| resume-first recovery disposition | claim health plus continuity delivery evidence and physical conflict class | actionable owner-resume, isolated-recovery, or hard-conflict result | existing continuity sweep plus claim interaction renderer | agents and operators starting or recovering work |
| exact-worktree mutation confinement | current native session, claimed worktree, and write path | allow only inside the selected claim's physical worktree | existing pre-write projection and hook | every governed repository mutation |

## Acceptance

- Both-sign tests admit overlapping paths in two valid distinct linked
  worktrees and return `isolated_worktree_overlap` evidence.
- Both-sign tests deny the same paths in one physical worktree, canonical
  checkout participation, unverified worktree identity, and explicitly shared
  state.
- Existing exact-session pre-write tests prove each owner remains confined to
  its own worktree.
- Existing resume delivery tests remain green, including bounded retries and
  spawned-agent fail-visible behavior.
- The focused claim and continuity suites pass, followed by the repository's
  terminal check before merge.

## Scope

**Included:** claim interaction classification and admission; actionable status
language; focused tests; operator documentation; source installation parity if
the changed files are installer-managed.

**Excluded:** automatic merge/rebase; deletion or pruning; force-push; process
killing; automatic custody transfer; deployment outside the existing host
timer; semantic judgment about whether predecessor work is valuable.
