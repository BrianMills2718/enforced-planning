# Worktree And Coordination Operator Guide

This is the authoritative operator guide for sanctioned worktree usage and
cross-agent coordination in governed repos. Use this document for day-to-day
workflow. Keep rationale, rollout history, and boundary design in the pattern
and project-meta docs; do not treat them as competing operator handbooks.

## Canonical Truth Surfaces

- Cross-project coordination claims: `~/.claude/coordination/claims/*.yaml`
- Automatically refreshed hook projection:
  `~/.claude/coordination/prewrite-authority-v1.json`
- Human/operator current-work readout:
  `python scripts/meta/check_coordination_claims.py --list --json`
- Claims/worktrees/projection consistency audit:
  `python scripts/check_coordination_consistency.py --repo PROJECT=/absolute/repo/path --verify-prewrite-projection --json`
- Repo-local in-flight architectural decisions: `agent-memory recall 'active decisions' --project {project}` (ADR-0010: `agent_memory` is the canonical store; `KNOWLEDGE.md ## Active Decisions` is deprecated)
- Repo opt-in switch: `meta-process.yaml`
- Sanctioned repo-local worktree interface: `make worktree`,
  `make worktree-list`, `make worktree-remove`, `make review-claim`,
  `make raise-concern`
- Canonical installed claim CLI for governed repos:
  `scripts/meta/check_coordination_claims.py`
- Canonical push gate for governed repos:
  `scripts/meta/check_push_safety.py` / `make push-check`
- Canonical closeout disposition vocabulary:
  `enforced_planning/worktree_lifecycle.yaml`

The older repo-local `.claude/active-work.yaml` plus legacy
`scripts/meta/worktree-coordination/check_claims.py` surface may still be
present in some repos for compatibility. They are not the canonical
cross-project coordination authority.

## Canonical Terms

- **claim**: the canonical low-level ownership record. Claims say who is
  claiming which project/scope/write paths, on which branch/worktree, for what
  intent.
- **lane**: a bounded execution slice derived from one or more live claims.
  In practice a lane is the operator-facing unit of work: one project, one
  branch/worktree, one plan or bounded sprint, one mission.
- **worktree**: the git checkout where a lane executes.
- **plan**: the pre-made execution contract that tells the lane what success,
  failure, and next actions mean.

Important rule: **claims are canonical, lanes are derived**. Do not invent a
second mutable lane registry by hand. Update claims; regenerate readable lane
surfaces from them.

`agent` identifies the client class; `session_id` identifies the runtime that
owns a live claim. Two Codex windows are therefore two writers even though both
claims say `agent: codex`. A live `agent + project + scope` slot may be refreshed
only by its exact owning session. A different session must use sanctioned
handoff/session-end plus session-resume, or close the lane; claim creation fails
without changing the claim or its derived projection.

The legacy `~/.claude/coordination/active-work-registry.yaml` and tracked
`generated/runtime/active_work_registry.*` files may survive as compatibility,
historical, or explicitly regenerated snapshot surfaces. They are not live
ownership authority. Do not consult them instead of the canonical claim CLI or
the digest-bound projection, and do not compare an old committed snapshot with
today's claims as a health test.

For repositories that set `meta_process.claims.prewrite_mode: observe`, native
Claude `Edit|Write` and Codex `apply_patch` calls are evaluated before mutation
and violations are recorded without blocking. After measured calibration
passes, `enforce` turns the same violations into pre-tool denials. `off` is the
portable default. This is a native agent-hook guardrail, not filesystem
isolation; arbitrary shell/process writes remain outside this gate.

The YAML claim registry remains authoritative. The low-latency hook consumes a
digest-bound JSON projection refreshed by sanctioned claim mutations. A stale
or missing projection is an observe violation and an enforce denial; do not
promote a repository to `enforce` while any active claim writer still uses a
legacy mutation path that does not refresh the projection.

Sanctioned claim writers stage atomic replacements in a same-filesystem sibling
directory outside the live registry. While holding the registry lock, writers
remove abandoned sanctioned staging files older than five minutes, including
strictly recognized legacy staging files in the registry; unrelated files are
left untouched. Session resume, handoff, abandon, and finish update the claim
and refresh the pre-write projection in the same locked mutation.

## Default Flow

1. Keep the canonical repo checkout clean and on its canonical default branch,
   normally `main`. Use it as the root-anchored integration/control session,
   not as an implementation lane.
2. Create one claimed linked worktree per bounded task inside the repo:
   `<repo>/worktrees/<branch>/`. Ensure `worktrees/` is in `.gitignore`.
   In sanctioned repos use
   `make worktree BRANCH=... TASK="..." [PLAN=N]`; do not create new lanes in
   `~/worktrees/`, `_worktrees/`, `<repo>_worktrees/`, or ad hoc sibling paths.
3. Give each worktree one mission and one plan or one bounded temporary plan
   doc. Do not let a worktree become a second long-lived control plane.
4. Keep generated proof artifacts inside the worktree until they are
   intentionally promoted.
5. Merge desired work back quickly. If a worktree starts owning root truth
   surfaces for days without an active owner, next action, and review trigger,
   it is no longer acting like a bounded worktree slice.

## Lane Lifecycle

1. Define the bounded mission in a numbered plan or one temporary sprint/plan
   document.
2. Create the worktree/branch for that lane.
3. Create a live claim with real ownership metadata:
   - `project`
   - `scope`
   - `intent`
   - `plan_ref` (a canonical numbered/qualified plan authority or exact
     `goal:<outcome-id>` authority)
   - `branch`
   - `worktree_path`
   - `session_id`
   - `session_name` (the durable broader-goal name when it differs from the runtime ID)
   - narrow `write_paths` for write claims
4. Execute, commit verified slices, and keep docs/trackers truthful.
5. Push from the checked-out claimed branch. The installed `pre-push` hook runs
   the canonical deterministic push check automatically. Use `make push-check`
   directly when diagnosing a blocked push.
6. Merge/push from the safe root-anchored control session.
7. Record the lane disposition and use `session-close` to make the claim
   non-live, retain its completed audit record, remove the worktree, and safely
   delete the local branch.

The default disposition for completed desired work is `merged`. Every finished,
stale, or out-of-policy lane must have one disposition before cleanup:

- `merged`: intended changes are integrated into the canonical default branch
- `active`: lane remains owned with a current next action and review trigger
- `handoff`: another runtime or owner is expected to resume the same lane
- `superseded`: equivalent or replacement work is already authoritative
- `abandoned`: unique work is intentionally discarded with explicit rationale
- `archived`: unique work has durable recovery state outside the local branch
- `migrated`: the lane continues in a correctly located replacement worktree

Cleanliness is not a disposition. A clean worktree can still contain committed
work that is absent from the canonical default branch.

The exact closeable/non-closeable vocabulary and recovery/discard classes are
loaded from `enforced_planning/worktree_lifecycle.yaml`. Invalid, blank,
duplicate, or overlapping configuration fails at import rather than silently
changing closeout semantics.

Mandatory rule: no live session without `plan_ref`, except explicitly marked
unplanned emergency work. Exact `goal:<outcome-id>` is a real sequential
outcome authority, not an alias for `UNPLANNED`. If work resumes in a new
runtime, reattach it to the existing plan- or goal-bound lane instead of
silently creating a new one.

A runtime session may own one unparented live claim root by default. Claim type
classifies work and path-conflict behavior; it does not exempt a lane from
session-root lifecycle enforcement. Related work must declare `parent_scope`.
Before opening an unrelated root, close or transfer the existing root; use
`SESSION_ALLOW_PARALLEL=1` / `--allow-parallel` only when multiple roots are an
intentional part of the adopted plan graph. The claim check runs before branch
or worktree creation and counts `active`, `blocked`, and `handoff` roots.

For the sanctioned repo-local `make worktree` flow, the default claim is a v2
**program** claim with real `branch`, `worktree_path`, and `session_id`
metadata. That keeps lane tracking healthy without inventing a fake broad
write-path claim for the whole repo.

If any of `branch`, `worktree_path`, `session_id`, `session_name`, or required write ownership
is missing for a live write/program/research claim, the claim is weak and the
registry should treat the lane as attention-worthy rather than healthy.

Stale is a different class of problem. A live claim is **stale** when the lane
state is no longer truthful even though the claim still says `active`. The
canonical stale diagnostics are:

- `missing_worktree_on_disk`
- `missing_branch_ref`
- `branch_merged_to_default`
- `stale_session_heartbeat`

Stale outranks weak. A stale claim should be cleaned up, not merely tolerated.
`branch_merged_to_default` is also a high-severity enforcement failure: the
standard `--check` command exits nonzero until the owner runs sanctioned
`session-close` or records an explicit supported non-merge disposition. The
check prefers `origin/<default>` over a stale local default checkout, so a
merged remote pull request cannot remain hidden merely because local `main`
has not advanced.

The sanctioned `scripts/merge_pr.py` helper treats post-merge `session-close`
failure as a high-severity command failure, including when the local worktree
is already absent. `session-close` itself refuses physical cleanup while any
other live claim still references the same canonical worktree path and lists
the sibling scopes that must be disposed or transferred first.

Squash merges require an explicit `--merge-commit <sha>` receipt. Closeout
accepts it only when that one-parent commit is retained by the canonical
default ref and its exact binary patch equals the task branch's cumulative
patch from the merge base. An arbitrary commit already on `main` does not
license closeout. The sanctioned merge helper captures and forwards GitHub's
reported merge commit automatically.

### Work-unit readiness binding

Every new numbered or qualified plan-bound claim with write ownership must
name its exact canonical work unit:

```bash
python scripts/meta/check_coordination_claims.py --claim \
  --agent codex --project example --scope unit-a --intent "Implement unit A" \
  --plan example#42 --claim-type write --write-path src/unit_a.py \
  --repo-root ~/projects/example \
  --work-graph docs/plans/42_example_work_graph.json \
  --work-unit-id unit-a \
  --branch plan-42-unit-a --worktree-path ~/projects/example/worktrees/plan-42-unit-a \
  --session-id codex:<thread-id> --session-name example-plan-42
```

The claim command reads the graph from the canonical remote default ref. It
fails before writing a claim when the unit or readiness state is not `ready`,
or when any `control_approval_types` entry lacks exactly one non-empty approval
revision. A successful claim retains `work_graph_sha256`, `work_unit_id`, and
the exact approval revisions. Existing historical claims remain readable, but
creating or refreshing a plan-bound claim with write ownership cannot omit this binding.

An exact `goal:<outcome-id>` ref is the narrow exception for one sequential
outcome lane that has no work-graph consumer. It may own write paths without a
manufactured graph or unit, and the sanctioned session entrypoint must preserve
that exact ref on the actual write claim. This exception does not apply to
`Plan #N`, `project#N`, descriptive strings, or other plan-shaped authorities;
those still require canonical graph and unit readiness and must not degrade to
`UNPLANNED` to get a write claim.

Use `SESSION_WORK_GRAPH` and `SESSION_WORK_UNIT_ID` with `make worktree` and
`make session-start`; these variables propagate the same validation through
the sanctioned entrypoints.

Liveness is heartbeat-backed:

- `session_id` identifies which runtime session owns the lane
- `heartbeat_at` says when that session last refreshed its lease
- missing `heartbeat_at` on an older live claim is compatibility debt, not
  automatically stale
- once a claim has a heartbeat, an overly old heartbeat becomes
  `stale_session_heartbeat`

The canonical v2 claim CLI now auto-resolves `session_id` from supported tool
runtime env vars when possible. In governed repos the installed local entrypoint
is `scripts/meta/check_coordination_claims.py`. In the framework repo the
equivalent source entrypoint is `scripts/check_coordination_claims.py`.

For an interactive runtime, `session_id` is the client-provided native session
identity, never a branch, lane, task, or invented label. When the native runtime
marker is available, sanctioned claim and session-start entrypoints reject a
different explicit identity. Hooks that receive an exact native ID but run
without its ambient environment may still pass that ID explicitly. Transfer or
takeover changes ownership; fabricating a replacement session ID does not.

If older live claims are missing `session_id`, repair them explicitly with:

```bash
python scripts/meta/check_coordination_claims.py --hydrate-session-ids --agent codex --project your-repo
```

Use narrower filters such as `--scope` or `--branch` when you only want to
repair one bounded lane.

To clean up claims that are mechanically provable stale, use:

```bash
python scripts/meta/check_coordination_claims.py --prune-stale --json
```

That command is intentionally separate from `--prune`, which only removes
expired claims. Use `--prune-stale` when worktree/branch lifecycle drift has
left a live claim no longer truthful.

To remove claims that are already explicitly closed, use:

```bash
python scripts/meta/check_coordination_claims.py --prune-completed --json
```

That command only removes valid YAML claims whose status is `complete` or
`completed`. It does not prune active claims, even when their TTL has elapsed.

To refresh the heartbeat for the current live session, use:

```bash
python scripts/meta/check_coordination_claims.py --heartbeat --agent codex --project your-repo
```

For Claude Code, the same command shape applies with `--agent claude-code`.
Session identity is auto-resolved from the supported runtime env vars when
available.

Heartbeat proves that a runtime is still attached; it does not prove that work
advanced. New or explicitly upgraded claims therefore carry one separate
durable progress event:

- `progress_at`: server-recorded UTC time of the last accepted event
- `progress_kind`: `claim_started`, `verified_commit`, `accepted_artifact`,
  `new_diagnostic`, or `integration_result`
- `evidence_ref`: exact durable evidence for that advancement
- `next_action`: the concrete next useful action
- optional paired `expected_quiet_until` and `quiet_reason`

Record advancement on one exact owned scope from the current native runtime:

```bash
python scripts/check_coordination_claims.py --progress \
  --agent codex --project enforced-planning --scope your-exact-scope \
  --progress-kind verified_commit --evidence-ref commit:abc123 \
  --next-action "run the focused integration check"
```

The installed `scripts/meta/check_coordination_claims.py` entrypoint accepts
the same arguments after the governed-repository wrapper is updated. The
command requires exactly one live claim owned by the native session, timestamps
the event itself, updates the claim atomically, refreshes the pre-write
projection, and emits the existing backward-compatible typed session-mutation
receipt. A new event without a quiet interval clears an obsolete interval.

By default, a complete event becomes `stalled` at 60 minutes without another
accepted event. `COORDINATION_PROGRESS_STALE_MINUTES` may set a positive numeric
window; invalid values fail visibly. A quiet interval suppresses the stall only
before its timezone-aware deadline, must end after `progress_at`, and cannot
extend beyond the claim expiry. Equality with the quiet deadline is expired.

`stalled` is report-only. It preserves the claim, session, write ownership,
push authority, and worktree; `--prune-stale` does not remove it. The operator
must record real advancement, move to ready work, or hand off explicitly.
Heartbeat, blocker records, handoff, tracker timestamps, Git activity, and file
dirt do not advance `progress_at`. A stale lifecycle or heartbeat still
outranks a progress stall. Claims with no progress fields retain legacy
behavior; partial, invalid, or future-dated events are `weak` contract defects,
not genuine stalls.

This operational claim progress is distinct from the tracker-backed selected
outcome progress described below. Neither stream renews the other implicitly;
an accepted outcome receipt may be named explicitly as `evidence_ref`.

## Session Contract Model

The coordination stack uses one canonical mutable object plus one linked
tracker:

- the **claim** remains canonical for coordination-critical fields
- the **session tracker** holds richer evolving execution context

Claim-side session fields should stay compact:

- `repo_root`
- `session_name`
- `broader_goal`
- `tracker_path`

Tracker-only session fields hold restart-safe execution context:

- `current_phase`
- `intended_next_phases`
- `depends_on_repos`
- `requires_shared_infra_changes`
- `stop_conditions`
- `notes`
- `outcome_selection` when an exact session has explicitly selected one
  create-once outcome scenario
- `outcome_progress_transitions` as append-only exact receipt, prior-lease, and
  successor-lease custody for work completed after selection
- `outcome_session_transfers` as append-only receipts for sanctioned runtime
  handoffs that preserve the selected scenario and lease
- `outcome_selection_transitions` as append-only retained predecessor and
  successor state for explicit causal restarts

Tracker creation, heartbeat, resume-style updates, and explicit refreshes use
the same locked atomic mutation boundary. Once `outcome_selection` exists, a
same-runtime refresh preserves the selection plus progress, transfer, and
restart histories and rejects an implicit change to the bound claim identity
instead of silently replacing or erasing custody. A sanctioned cross-session
resume uses the explicit transfer path below.

### Durable outcome selection observe pilot

Plan #117 adds an explicit, manual observe-only path for binding one exact live
session to one immutable outcome scenario:

```bash
python scripts/outcome_continuation.py select \
  --scenario examples/owner-real-outcome-observe/plan117-owner-progress.json \
  --execution-authority enforced-planning#117 \
  --agent codex --project enforced-planning \
  --scope plan-117-outcome-selection-binding
```

The selection command resolves exactly one healthy live claim, validates its
linked tracker and execution authority, requires the scenario to live inside
the claimed worktree, and stores one digest-bound selection. Identical replay
is idempotent. A different scenario, claim/session identity, branch, worktree,
tracker, authority, target, or modified scenario fails visibly.

An opted-in pre-write observation then resolves only that stored choice:

```bash
python scripts/prewrite_claim_gate.py \
  --client codex --mode observe --outcome-selected --json
```

`--outcome-selected` and `--outcome-scenario` are mutually exclusive. The
ordinary claim decision is recorded first and remains authoritative; the
selected outcome appends `would_allow`, `would_deny`, or a typed observation
failure without performing or blocking the write. This pilot is not automatic
selection, mutable progress-lease renewal, installed hook activation, or fleet
enforcement.

### Restart-safe outcome custody observe pilot

Plan #118 distinguishes routine runtime turnover from a deliberate mechanism
restart.

When a selected lane is eligible for cross-session `session-resume`, the
lifecycle command first validates the old claim, tracker, binding, scenario,
contract, and lease. It then changes the claim identity and tracker binding
together, appends one `OutcomeSessionTransferV1`, and preserves every outcome
and lease digest. The prior runtime no longer resolves the selection. If the
claim write, derived claim projection, successor normalization, or tracker
transition fails after mutation begins, the exact preflight claim and tracker
bytes are restored; an unsuccessful rollback raises a visible
`session_transfer_incomplete` error rather than reporting success. Lanes with
no selected outcome keep the existing resume behavior.

A stalled or deliberately parked lineage cannot be replaced with `select`.
Create a strict `RestartDeltaV1` inside the same claimed worktree, then use the
explicit command:

```bash
python scripts/outcome_continuation.py restart \
  --successor-scenario examples/owner-real-outcome-observe/plan118-active-successor.json \
  --restart-delta examples/owner-real-outcome-observe/plan118-restart-delta.json \
  --agent codex --project enforced-planning \
  --scope plan-118-restart-lineage-design
```

The successor must keep the same owner class, project, outcome, intended
consumer, canonical journey, progress dimensions, target, and execution
authority; it must name a different lineage that directly lists the selected
predecessor. The delta names both the prior and changed hypothesis/mechanism,
one bounded action, the next canonical observation, and the stopping
condition. An accepted restart replaces only the current binding and appends
an `OutcomeRestartTransitionV1` containing the full predecessor binding,
contract, lease counters, failure boundary/count, and failed-evidence refs.
Exact replay is idempotent; competing deltas fail visibly.

This remains same-project observe-mode custody. It does not semantically prove
that a mechanism is meaningfully different, provide an independent reviewer
identity, resolve owner-class WIP through Project Graph, allow cross-project
successors, activate outcome blocking, install hooks, or claim fleet adoption.

### Durable selected progress observe pilot

Plan #119 keeps the selected scenario immutable while allowing later evidence
to advance its lease. Create one strict `OutcomeProgressReceiptV1` inside the
exact claimed worktree. Its contract digest and dimension must match the
selected outcome, and `prior_receipt_sha256` must equal the current selected
head. Append it through the existing CLI:

```bash
python scripts/outcome_continuation.py progress \
  --receipt examples/owner-real-outcome-observe/plan119-progress-receipt.json \
  --agent codex --project enforced-planning \
  --scope plan-119-durable-outcome-progress
```

The command resolves exactly one healthy live claim and its selected binding,
reconstructs the current lease from the base scenario plus retained progress,
and appends one `OutcomeProgressTransitionV1`. That transition contains the
exact receipt file/model digests and full prior/successor lease snapshots.
Exact accepted file replay returns the retained transition without rewriting
tracker bytes. A stale parent, changed file, duplicate receipt ID, malformed
history, foreign claim, or receipt already present in the base scenario fails
before mutation.

`--outcome-selected` now evaluates the reconstructed effective scenario. Its
correlation receipt names the immutable base digest, effective scenario digest,
progress count/head, and current lease. Ordinary claim admission and native
exit behavior remain authoritative. A malformed progress stream becomes a
typed observation failure, never a permissive fallback or an outcome-based
deny.

Sanctioned cross-session resume retains the progress stream and binds its
current lease/head in `OutcomeSessionTransferV1`; the successor runtime can
append the next receipt against that retained head. Causal restart likewise
uses post-selection stalled or parked evidence rather than the stale base
lease. A restart starts a distinct successor lineage, so predecessor progress
remains historical and is not replayed into the successor lease.

This pilot establishes current-head custody only. It does not classify product
versus maintenance leases, allocate a portfolio slot through Project Graph,
hard-block writes, prove receipt semantics independently, install hooks, or
claim fleet adoption.

### Project Graph-bound portfolio admission pilot

Plan #120 adds deliberate portfolio admission for new schema `1.1.0` outcome
contracts. Each such contract declares exactly one `portfolio_class`:
`product`, `maintenance`, or `external_obligation`. Allocation resolves the
project from an exact full 40-character Project Meta commit, requires one
active Project Graph record with a complete reviewed repository-governance
authority, and retains digests for the graph bytes, project record, review,
and resolved authority. A branch name, local clone location, or available Git
identity cannot substitute for that authority.

Allocation is always an explicit operator action; `select` never allocates a
slot implicitly:

```bash
python scripts/outcome_continuation.py allocate \
  --scenario examples/owner-real-outcome-observe/plan120-maintenance-scenario.json \
  --request examples/owner-real-outcome-observe/plan120-maintenance-allocation.json \
  --project-graph-repo /path/to/project-meta \
  --project-graph-revision <full-40-character-commit> \
  --agent codex --project enforced-planning \
  --scope plan-120-project-graph-portfolio-admission

python scripts/outcome_continuation.py select \
  --scenario examples/owner-real-outcome-observe/plan120-maintenance-scenario.json \
  --execution-authority enforced-planning#120 \
  --agent codex --project enforced-planning \
  --scope plan-120-project-graph-portfolio-admission \
  --portfolio-ledger /path/to/outcome-portfolio-allocations-v1.json
```

One active `product` allocation is allowed per resolved Project Graph owner
class. `maintenance` and `external_obligation` share one global non-product
slot. The append-only ledger is reconstructed under a file lock before every
mutation; exact request replay is byte-inert, while a competing request,
changed replay, malformed history, owner mismatch, or exceeded cap fails
visibly without allocating.

Release a slot only through an explicit `parked` or `completed` disposition:

```bash
python scripts/outcome_continuation.py dispose-allocation \
  --request examples/owner-real-outcome-observe/plan120-maintenance-disposition.json \
  --agent codex --project enforced-planning \
  --scope plan-120-project-graph-portfolio-admission \
  --portfolio-ledger /path/to/outcome-portfolio-allocations-v1.json
```

A classed selection and every later selected-outcome resolution require the
bound allocation to remain active with the retained allocation digest. A
disposed allocation therefore invalidates later selected observation instead
of silently reopening capacity. Legacy schema `1.0.0` scenarios remain
readable and retain their byte-compatible digest, but they are not evidence of
portfolio admission.

This pilot does not yet bind ordinary plan creation, claim creation, worktree
creation, or authoritative pre-write admission to an allocation. It does not
choose Brian's active product outcome, alter ordinary claim authority, install
hooks, or establish fleet adoption. Those boundaries require a representative
false-block review before the ratchet can become mandatory.

Important rule: do not name sessions after the immediate local task. A branch
like `plan-31-hygiene-gate` is fine for git, but the session name should derive
from the broader goal, such as `digimon-truthful-controller-grounding`.

Canonical lifecycle commands:

- `session-start`: create or refresh the claim-linked session contract
- `session-heartbeat`: refresh the lease and tracker timestamp
- `session-status`: show live sessions derived from claims plus trackers
- `session-end`: detach a terminating runtime from all of its exact-session
  claims without deleting branches, worktrees, trackers, or Git objects
- `session-finish`: refuse unsafe closeout and require clean or explicit handoff state
- `session-close`: clean up a claimed lane end-to-end by removing the worktree,
  safely deleting the local branch, and releasing the claim together after
  merge/disposition preflight
- `create_publish_worktree.py`: create a merge/push control worktree only when
  the canonical main checkout is already clean

- `session-resume`: attach a new runtime to an existing plan-bound lane and,
  when selected state exists, append an exact lossless outcome transfer
- `session-handoff`: intentionally pause or transfer work with a durable note
- `session-abandon`: explicitly mark a dead lane as abandoned instead of
  leaving it stale forever

Human-facing services have a separate but connected runtime lifecycle:

- `make surface-up SURFACE=<id>` starts the registry-declared canonical surface
  only from its clean integration lineage and verifies its served identity.
- `make surface-preview SURFACE=<id>` starts a candidate on noncanonical ports
  and records an independent preview lease.
- `make surface-status`, `make surface-audit SURFACE=<id>`, and
  `make surface-down SURFACE=<id> [LEASE=<id>]` inspect or end exact leases.
- `session-close` refuses to remove a worktree while a live lease records that
  worktree as its owner. Stop the exact lease first; never broadly kill matching
  process names.

The runtime declaration remains in the consumer repository's
`ui/registry.yaml`. Runtime leases and logs live under `$SURFACE_STATE_ROOT`,
`$XDG_STATE_HOME/governed-surfaces`, or the default
`~/.local/state/governed-surfaces`; they are operational state, not Git
authority.

Supported runtime adapters:

- Codex: `CODEX_THREAD_ID`
- Claude Code: `CLAUDE_SESSION_ID` or `CLAUDE_CODE_SSE_PORT`
- OpenClaw: `OPENCLAW_SESSION_ID` or `OPENCLAW_RUN_ID`

Those adapters only resolve runtime identity. They do not change the session
contract schema, the tracker schema, or the sanctioned repo lifecycle commands.

## Crash / Resume Policy

The coordination stack uses lease semantics, not perfect real-time presence.

- if the client emits a real `SessionEnd`, the configured hook changes every
  exact-session live claim to `session_ended`
- `session_ended` is non-live ownership but not terminal disposition; the
  preserved lane must be resumed, taken over, or closed through merge/recovery
- if a machine crashes or a client cannot emit `SessionEnd`, the session stops
  heartbeating
- once the heartbeat ages out, the lane becomes stale
- the next runtime must explicitly choose to resume, hand off, abandon, or
  prune that lane
- a different runtime may resume only after explicit `handoff`, true
  `session_ended`, or `stale_session_heartbeat`; a healthy `active` or `blocked`
  lane remains owned by its exact `session_id`
- client UI state such as "resolved" is not lifecycle or liveness evidence and
  cannot authorize takeover

Do not treat "I reopened the repo" as implicit recovery. Recovery must be
explicitly attached to the same `project + plan_ref + scope` lane or declared
as a new parallel lane.

Parallel live lanes on the same `project + plan_ref + scope`, and a second
unparented root owned by the same runtime across any project, fail unless the
operator explicitly allows parallelism.

Never wire this transition to a turn-level `Stop` event. `Stop` fires while a
runtime can continue; only the client's true `SessionEnd` event may retire
ownership. Session end is deliberately non-destructive and cannot substitute
for `session-close`.

### Resume an in-progress plan with no live lane

Resume is explicit and still consults both authorities: Ecosystem Ops supplies
the revision-bound static plan decision, then the canonical claim registry
performs the final atomic ownership check. For the standard workspace layout:

```bash
make worktree \
  BRANCH=plan-234-next-lane \
  TASK="Resume Plan 234" \
  PLAN=234 PLAN_PROJECT=project-meta PLAN_RESUME=1 \
  PLAN_READINESS_COMMAND="python $HOME/projects/ecosystem-ops/plan_graph.py" \
  SESSION_GOAL="Resolve recoverable historical workspace worktree residue" \
  SESSION_PHASE="Execute the next accepted Plan 234 packet"
```

The command is allowed only when the graph returns `already_active` for the
exact qualified plan and the registry has no matching live lane. Omitting
`PLAN_RESUME=1`, a negative or malformed graph response, or a matching live
claim fails before creating a claim, branch, worktree, or tracker. The
readiness command is explicit because the portable framework does not assume a
personal workspace location; governed workspace repositories may provide a
repo-local default through their own canonical configuration.

## Session-End Hooks, Observability, And Feedback

The source-owned adapter is:

```bash
python ~/projects/enforced-planning/scripts/session_end.py \
  --agent codex --hook
```

Claude Code uses the same adapter with `--agent claude-code`. The hook receives
native JSON on stdin and accepts only `hook_event_name: SessionEnd`. Configure
it under the user-level `SessionEnd` hook, not `Stop`, so every repository uses
one canonical implementation. Clients without a verified end hook rely on the
heartbeat stale path and explicit `make session-end`.

Inspect live state with `make session-status`. Inspect preserved ended state or
one runtime across repositories with:

```bash
python scripts/session_status.py --include-ended --json
python scripts/session_status.py --session-id codex:<thread-id> --include-ended --json
```

The JSON end receipt names the session, end time, reason, and every affected
`project:scope`. Claim YAML is the durable audit record; the generated active
work registry remains a derivative and no second mutable lane store is added.

When this control blocks valid work, loses an expected session transition, or
creates avoidable process cost, record concrete evidence in Project Meta's
canonical feedback register:

```bash
make -C ~/projects/project-meta policy-friction \
  POLICY=policy-session-bound-lane-lifecycle \
  FRICTION="<observed failure and command>" \
  RECOMMENDATION="<smallest corrective change>"
```

## Consumer Rule

Downstream coordination consumers such as assignment managers, dashboards, or
future queue routers must consume canonical claim/session identity. They must
not introduce:

- a global singleton current-session file
- their own per-window identity registry
- a second mutable source of truth for session ownership

Assignment and queue layers are allowed as routing layers only when they sit on
top of the canonical claim/session lifecycle.

## Authority Drift Policy

Authority drift is what happens when a lane lands a new authoritative artifact
but does not reconcile the separately owned authority surface that indexes,
summarizes, or governs it.

Policy:

1. A lane may land authoritative artifacts in its claimed scope.
2. A lane may not opportunistically edit a separately claimed authority
   surface.
3. A lane that creates authority drift must record a formal reconciliation
   obligation.
4. The lane owning the affected authority surface may not close while that
   obligation remains unresolved.

This is a hard gate, not a warning-only convention. Warnings are too easy to
ignore during expedited execution.

Current implementation:

- In the canonical Enforced Planning repository,
  `scripts/validate_doc_authority.py --check` validates indexed authority drift.
- In an installed governed repository, use
  `scripts/meta/validate_doc_authority.py --check`.
- `scripts/meta/validate_doc_authority.py --record-obligation ...` records formal
  reconciliation debt
- `scripts/meta/validate_doc_authority.py --list-obligations --json` shows current
  open or resolved debt
- `session-finish` now fails when the closing lane owns authority surfaces with
  unresolved reconciliation obligations

The v0 authority store lives beside claims:

- `~/.claude/coordination/authority_obligations/*.yaml`

Current bounded scope:

- indexed authority surfaces such as plan indexes
- `resolution_mode: manual` means the landing lane must record debt if overlap
  is forbidden
- `resolution_mode: generated` means the surface should be regenerated instead
  of carrying durable manual debt

## Session Safety

Some agent runtimes keep a persistent shell working directory. In those
environments, deleting a worktree from a session whose shell CWD still points
inside that worktree breaks subsequent shell commands.

Practical rule:

- keep one control session anchored at the canonical repo root
- run merge / finish / closeout from that root-anchored session
- do not delete a worktree from a session whose shell CWD is inside it

The `block-cd-worktree.sh`, `warn-worktree-cwd.sh`, and
`enforce-make-merge.sh` hooks enforce this safety rule for Claude Code style
sessions. That safety rule does not mean worktrees are optional; it means
cleanup must happen from a safe control session.

## Atomic Closeout Rule

Claim release and claimed-worktree cleanup must not be split into separate
manual steps.

- use `session-close` for direct CLI closeout
- use `make worktree-remove BRANCH=...` in governed repos
- do not run `session-finish --release-claim` and later try to remove the
  worktree as a second operation

The sanctioned closeout flow is idempotent for already-missing worktree or
branch state so partial cleanup can be rerun safely.

Mailbox messages are a separate closeout precondition. `session-close` refuses
to close a lane while actionable messages remain addressed to its exact session.
The recipient must read and explicitly acknowledge them first. When the work
cannot be completed before closeout, the only supported exception is an
explicit, durable deferral recorded against that same recipient session:

```bash
python scripts/session_close.py \
  --agent codex --project example --scope example-lane \
  --mailbox-disposition deferred \
  --mailbox-note "Deferred at closeout; successor must reconcile the linked review request."
```

This does not transfer a message to another session and never authorizes an
agent to acknowledge someone else's inbox. A separate handoff must create and
route a new message to its exact recipient.

Atomicity does not replace integration safety. Before any mutation,
`session-close` must establish one of these conditions:

1. the local branch is already integrated into the canonical default branch;
   or
2. the operator supplied an explicit supported non-merge disposition and the
   closeout preflight proved that unique commits will remain recoverable or are
   intentionally abandoned.

Committed ancestry is not sufficient while the claimed worktree still contains
staged, modified, or untracked work. `branch_merged_to_default` may classify the
branch only after the worktree is clean, so closeout cannot erase changes that
were never represented by the compared commits.

The default closeout path does not merge automatically. Merge and verification
remain explicit root-anchored control-session actions. `git branch -D` must not
be used as a substitute for merge/disposition evidence.

Normal merged closeout:

```bash
make session-close BRANCH=plan-59-safe-closeout
```

For a squash merge, provide the exact canonical one-parent merge commit through
the same sanctioned wrapper. It forwards the evidence unchanged to
`session-close`, which rejects a commit whose patch is not exactly equivalent
to the lane branch; a failed check leaves the worktree, branch, claim, and
tracker intact.

```bash
make worktree-remove \
  BRANCH=plan-59-safe-closeout \
  WORKTREE_MERGE_COMMIT=<canonical-squash-commit>
```

### Exact missing-worktree reconciliation

Use this exceptional path only for a preserved `session_ended` claim whose
recorded worktree no longer exists. It does not remove a filesystem path. The
operator must supply the exact tracker digest captured from the one identity-
matched tracker plus ordinary merge or recovery evidence. Live claims, a
present worktree, tracker ambiguity or digest drift, sibling live ownership,
and invalid merge/recovery evidence fail before claim or tracker mutation.

```bash
python scripts/session_close.py \
  --agent codex --project enforced-planning --scope plan-106-example \
  --reconcile-missing-worktree \
  --tracker-sha256 "$(sha256sum /absolute/path/to/tracker.yaml | cut -d' ' -f1)" \
  --merge-commit <canonical-merge-or-squash-commit> \
  --json
```

The JSON response and completed claim retain a `missing_worktree_reconciliation`
receipt. Do not use this path to close a live, handoff, or existing worktree.

Explicit archive closeout for an unmerged branch whose exact tip remains on a
durable remote or tag ref:

```bash
make session-close \
  BRANCH=experiment-branch \
  WORKTREE_DISPOSITION=archived \
  WORKTREE_DISPOSITION_REASON="preserve reviewed experiment without merging" \
  WORKTREE_RECOVERY_REF=refs/remotes/origin/experiment-branch
```

Intentional abandonment of unique commits is exceptional and requires both a
reason and `WORKTREE_ALLOW_DISCARD_UNIQUE=1`. `active` and `handoff` are valid
lane dispositions but are not valid `session-close` outcomes because their
work remains live.

Before changing the Git worktree registry, `session-close` verifies that the
current user can traverse and write every directory needed for recursive
removal. Read-only dependency trees and root-owned caches fail at this
preflight, leaving the worktree registration and claim unchanged. Preserve or
repair the reported path, then retry; do not manually remove `.git/worktrees`
metadata to work around the failure.

Successful closeout retains the claim YAML with `status: completed`, the
disposition, default-branch result, reason, recovery ref when used, and close
timestamp. It is no longer active coordination state. Explicit
`--prune-completed` housekeeping may remove completed history later.

Branch lifetime and worktree lifetime are separate. A substantial remote
feature branch may remain after its inactive local worktree is removed and can
be recreated when work resumes. Persistent worktrees are reserved for active,
owned lanes with a plan/claim, pushed upstream, next action, and review trigger.

## Publish-Lane Rule

Publish lanes are control surfaces for shared-state actions such as merge and
push. They should not be created from a dirty or unmerged canonical main
checkout.

- use `create_publish_worktree.py` for explicit publish-lane creation
- do not improvise raw `git worktree add` from a dirty primary checkout
- if the canonical main checkout is dirty, treat that as a publish blocker and
  document it explicitly rather than creating an ambiguous publish lane

## Mailbox Response Lifecycle

Mailbox delivery is not complete merely because a hook displayed a message.
Every active message addressed to the current exact session must receive a
durable acknowledgement with one truthful disposition:

- `accepted`: the recipient accepts the requested action or handoff
- `declined`: the recipient will not perform it; include the reason
- `deferred`: the recipient cannot act now; include the owner or resume event
- `information_only`: the message required awareness but no action

Inspect the exact-session inbox at these natural boundaries:

1. session start or resume;
2. before beginning a new work unit;
3. after a major phase when another lane can change the next action; and
4. before claim transfer, lane closeout, or final handoff.

For a question, review request, handoff, or coordination request, the
acknowledgement note or `response_ref` must state the decision or point to its
durable answer. An informational message needs no reply message; acknowledge it
as `information_only`. Do not create acknowledgement loops by replying only to
confirm that an acknowledgement was received.

Use the repo-local inbox wrapper to poll:

```bash
python scripts/meta/coordination_inbox.py \
  --agent codex --project example --session-id codex:<thread-id> --json
```

Use the canonical mailbox CLI to acknowledge one message with a strict request:

```bash
python scripts/meta/coordination_messages.py acknowledge --request-json \
  '{"current_session_id":"codex:<thread-id>","message_id":"msg_<32-hex>","disposition":"information_only","note":"Read; no action requested."}'
```

Native lifecycle notices render every active message under an emphatic
`ACKNOWLEDGEMENT REQUIRED` heading. The notice includes the exact session and
message IDs plus a shell-safe acknowledgement command template. Replace its
disposition and note placeholders truthfully, then run it before crossing the
next natural work boundary. The notice intentionally repeats on later lifecycle
events until the acknowledgement receipt exists.

Host mailbox adapters enforce two boundaries after a notice is visible:

- `PreToolUse` denies the common mutation tools (`Bash`, `Edit`, `Write`, and
  `apply_patch`) while a displayed message remains active. One structurally
  exact acknowledgement command for that session and message remains allowed.
- `Stop` denies final-response delivery while any displayed message remains
  active. The client resumes the same turn so the agent can record a truthful
  disposition.

Read-only investigation remains available, and neither gate chooses a
disposition automatically. Each denied boundary appends an idempotent boundary
record with the native event identity; acknowledgement results expose elapsed
response time. These records expose ignored notices and response latency
without changing claim authority or historical receipt schemas.

Observation and acknowledgement are distinct append-only receipts. An
`observed` receipt proves only that the message was exposed to the session; it
does not satisfy this response rule. Claims remain the write-ownership source,
and no mailbox disposition grants, transfers, or releases a claim.

The sender's lifecycle poll surfaces each new acknowledgement once, including
its disposition, note, or response reference. This is a derived notification
over the acknowledgement receipt, not a reply message, so it does not create a
new acknowledgement obligation or a confirmation loop.

The closeout gate mechanically rejects active unacknowledged messages before
mutation. If normal disposition is impossible, closeout supports only an
explicit durable `deferred` acknowledgement with a note; the successor still
needs a separately routed handoff. If polling is unavailable, follow the
degraded-mailbox rule in the workspace instructions and record the limitation;
never fabricate an acknowledgement. An adapter failure emits a visible warning
but cannot truthfully assert mailbox debt or manufacture a block. The agent must
not cross a boundary when a live-agent decision may be pending until canonical
polling is restored.

## What Coordination Does And Does Not Do

What it does:

- records who claimed what scope
- exposes a readable current-work registry, including derived active lanes
- lets repos block conflicting or unsafe worktree flows
- makes in-flight architectural decisions visible through `agent_memory` (query: `agent-memory recall 'active decisions' --project {project}`)
- persists immutable cross-client messages and append-only observation and
  acknowledgement receipts beside the canonical claim registry
- injects mailbox notices at native session start, user prompt, and post-tool
  lifecycle events; both supported clients enforce mutation and final-response
  boundaries with `PreToolUse` and `Stop`

What it does not do:

- real-time presence
- automatic conflict resolution
- guaranteed asynchronous interruption of an arbitrary existing client session

What concern routing adds:

- `make review-claim` marks review intent on another lane's write paths
- `make raise-concern` routes the concern to a PR comment when the target branch
  is already published, otherwise to the canonical JSON coordination mailbox
- a PR comment reports `fallback_published`; it never counts as mailbox
  observation or acknowledgement
- review overlap is visible coordination state, not silent out-of-band chatter

Codex and Claude discovery is lifecycle-polled unless a separately certified
managed app-server owns the thread. Project-local Codex hooks require project
trust and one-time review through `/hooks`; a changed hook is skipped until its
new definition is trusted. Neither client's hook is real-time presence. The
compatibility `check-inbox.sh` and `notify-inbox-startup.sh` paths now redirect
to the JSON mailbox and never read or mutate `.claude/messages/inbox/`.

## Repo Opt-In Contract

A repo truthfully opts into sanctioned worktree coordination when:

- `meta_process.claims.enabled: true`
- `meta_process.worktrees.enabled: true`

Opted-in repos are expected to expose:

- `make worktree BRANCH=... TASK="..." [PLAN=N]`
- `make worktree-list`
- `make worktree-remove BRANCH=...`

If a repo declares the opt-in flags but does not expose the sanctioned
entrypoints and local scripts, that is contract drift and should be fixed.

Maintenance commands:

- `python scripts/audit_governed_repo.py --repo-root <repo> --json`
- `python scripts/scan_coordination_mirrors.py --workspace-root ~/projects --fail-on-copied`

## Startup Surface Ownership Policy

Startup surfaces (the brief, assignment file, or claim state shown at session
open) must respect a strict ownership rule:

**Interactive sessions** (human-driven Claude Code windows, Codex terminals):
- display only work that the *current session* explicitly owns via claim
- if no claim exists for this session, show no assignment — do not surface
  generic fallback files as if they were a current assignment
- other sessions' claims may be shown as *global context*, but must be labeled
  as such and never phrased as "your current work"

**Autonomous sessions** (cron, overnight runs, agent pipelines):
- must create or resume an explicit plan-bound claim before starting work
- must not proceed with work that has no verifiable claim ownership
- startup surfaces for autonomous sessions are the claim registry and sprint
  tracker; generic assignment files are not sufficient

**Generic fallback files** (e.g. `claude-code.yaml`, `assignment.yaml`):
- treated as routing *hints* only — not as session identity
- do not promote generic files to "current session" truth at startup
- if a repo still uses a generic fallback file, log a coordination drift warning
  and proceed without auto-adopting the assignment

**Failure mode to avoid:** A stale generic assignment file surfacing as the
current session's assignment when the actual operator just opened a new
interactive window. This was observed live on 2026-04-05: `claude-code.yaml`
showed `theory-forge` as the session's work when the session had never claimed
it. Resolution: startup display must be claim-gated, not fallback-file-gated.

See `docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md` for the
architecture basis of this policy (Startup Surfaces section).

## Related Docs

- `README.md` for framework overview
- `patterns/worktree-coordination/README.md` for module structure
- `docs/reference/CONFIG_REFERENCE.md` for config key semantics
