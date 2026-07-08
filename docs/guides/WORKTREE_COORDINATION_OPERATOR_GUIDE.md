# Worktree And Coordination Operator Guide

This is the authoritative operator guide for sanctioned worktree usage and
cross-agent coordination in governed repos. Use this document for day-to-day
workflow. Keep rationale, rollout history, and boundary design in the pattern
and project-meta docs; do not treat them as competing operator handbooks.

## Canonical Truth Surfaces

- Cross-project coordination claims: `~/.claude/coordination/claims/*.yaml`
- Readable current-work snapshot: `~/.claude/coordination/active-work-registry.yaml`
- Repo-local in-flight architectural decisions: `agent-memory recall 'active decisions' --project {project}` (ADR-0010: `agent_memory` is the canonical store; `KNOWLEDGE.md ## Active Decisions` is deprecated)
- Repo opt-in switch: `meta-process.yaml`
- Sanctioned repo-local worktree interface: `make worktree`,
  `make worktree-list`, `make worktree-remove`, `make review-claim`,
  `make raise-concern`
- Canonical installed claim CLI for governed repos:
  `scripts/meta/check_coordination_claims.py`
- Canonical push gate for governed repos:
  `scripts/meta/check_push_safety.py` / `make push-check`

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

## Default Flow

1. Keep the canonical repo checkout on `main` or `master`.
2. Create one sibling worktree per bounded task:
   `git worktree add ../<repo>_worktrees/<branch> -b <branch> <trunk>`.
   In sanctioned repos prefer `make worktree BRANCH=... TASK="..." [PLAN=N]`.
3. Give each worktree one mission and one plan or one bounded temporary plan
   doc. Do not let a worktree become a second long-lived control plane.
4. Keep generated proof artifacts inside the worktree until they are
   intentionally promoted.
5. Merge back quickly. If a worktree starts owning root truth surfaces for
   days, it is no longer acting like a worktree slice.

## Lane Lifecycle

1. Define the bounded mission in a numbered plan or one temporary sprint/plan
   document.
2. Create the worktree/branch for that lane.
3. Create a live claim with real ownership metadata:
   - `project`
   - `scope`
   - `intent`
   - `plan_ref`
   - `branch`
   - `worktree_path`
   - `session_id`
   - narrow `write_paths` for write claims
4. Execute, commit verified slices, and keep docs/trackers truthful.
5. Run `make push-check` before publishing from the safe root-anchored control session.
6. Merge/push from the safe root-anchored control session.
7. Release the claim when the lane is done.

Mandatory rule: no live session without `plan_ref`, except explicitly marked
unplanned emergency work. If work resumes in a new runtime, reattach it to the
existing plan-bound lane instead of silently creating a new one.

For the sanctioned repo-local `make worktree` flow, the default claim is a v2
**program** claim with real `branch`, `worktree_path`, and `session_id`
metadata. That keeps lane tracking healthy without inventing a fake broad
write-path claim for the whole repo.

If any of `branch`, `worktree_path`, `session_id`, or required write ownership
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
equivalent source entrypoint is `scripts/check_coordination_claims.py`. If older
live claims are missing `session_id`, repair them explicitly with:

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

Important rule: do not name sessions after the immediate local task. A branch
like `plan-31-hygiene-gate` is fine for git, but the session name should derive
from the broader goal, such as `digimon-truthful-controller-grounding`.

Canonical lifecycle commands:

- `session-start`: create or refresh the claim-linked session contract
- `session-heartbeat`: refresh the lease and tracker timestamp
- `session-status`: show live sessions derived from claims plus trackers
- `session-finish`: refuse unsafe closeout and require clean or explicit handoff state
- `session-close`: clean up a claimed lane end-to-end by removing the worktree,
  deleting the local branch, and releasing the claim together
- `create_publish_worktree.py`: create a merge/push control worktree only when
  the canonical main checkout is already clean

Next lifecycle additions to keep the model truthful after crashes or intentional
session closure:

- `session-resume`: attach a new runtime to an existing plan-bound lane
- `session-handoff`: intentionally pause or transfer work with a durable note
- `session-abandon`: explicitly mark a dead lane as abandoned instead of
  leaving it stale forever

Supported runtime adapters:

- Codex: `CODEX_THREAD_ID`
- Claude Code: `CLAUDE_SESSION_ID` or `CLAUDE_CODE_SSE_PORT`
- OpenClaw: `OPENCLAW_SESSION_ID` or `OPENCLAW_RUN_ID`

Those adapters only resolve runtime identity. They do not change the session
contract schema, the tracker schema, or the sanctioned repo lifecycle commands.

## Crash / Resume Policy

The coordination stack uses lease semantics, not perfect real-time presence.

- if a machine crashes or a window closes, the session stops heartbeating
- once the heartbeat ages out, the lane becomes stale
- the next runtime must explicitly choose to resume, hand off, abandon, or
  prune that lane

Do not treat "I reopened the repo" as implicit recovery. Recovery must be
explicitly attached to the same `project + plan_ref + scope` lane or declared
as a new parallel lane.

Parallel live lanes on the same `project + plan_ref + scope` should fail unless
the operator explicitly allows parallelism.

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

- `scripts/validate_doc_authority.py --check` validates indexed authority drift
- `scripts/validate_doc_authority.py --record-obligation ...` records formal
  reconciliation debt
- `scripts/validate_doc_authority.py --list-obligations --json` shows current
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

## Publish-Lane Rule

Publish lanes are control surfaces for shared-state actions such as merge and
push. They should not be created from a dirty or unmerged canonical main
checkout.

- use `create_publish_worktree.py` for explicit publish-lane creation
- do not improvise raw `git worktree add` from a dirty primary checkout
- if the canonical main checkout is dirty, treat that as a publish blocker and
  document it explicitly rather than creating an ambiguous publish lane

## What Coordination Does And Does Not Do

What it does:

- records who claimed what scope
- exposes a readable current-work registry, including derived active lanes
- lets repos block conflicting or unsafe worktree flows
- makes in-flight architectural decisions visible through `agent_memory` (query: `agent-memory recall 'active decisions' --project {project}`)

What it does not do:

- real-time presence
- automatic conflict resolution
- automatic discovery of another agent mid-session

What concern routing adds:

- `make review-claim` marks review intent on another lane's write paths
- `make raise-concern` routes the concern to a PR comment when the target branch
  is already published, otherwise to the repo-local inbox channel
- review overlap is visible coordination state, not silent out-of-band chatter

Agents only see what has been written to claims, the active-work registry, or
`agent_memory`. If those surfaces are stale, the agent view is stale.

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
