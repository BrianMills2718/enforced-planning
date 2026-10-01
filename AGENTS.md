# Enforced Planning

Status: active

Source repo for the portable planning and governance framework.

## Continuous Execution Contract

Continuous authorization uses one of three profiles from
`docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md`:

- `continuous-light` is the default for reversible single-writer development
  and functional PoCs. Reuse the existing task authority, run focused checks,
  and do not require a numbered plan, tracker, claim, or worktree solely because
  the user requested continuous work.
- `continuous-coordinated` adds one shared tracker, scoped claims, and worktrees
  when writers or dependent phases can collide.
- `continuous-release` adds immutable candidate and broad terminal controls for
  publication, migration, deployment, or another consequential terminal claim.

All profiles commit and push verified increments, preserve the user outcome,
and continue past a completed phase while authorized, dependency-ready,
outcome-advancing work remains and the next action is not irreversibly
dangerous. Keep one stable initiative example above smaller plan
examples. Optimize for expected user-visible value or decisive learning per
wall-clock hour. At roughly 15 minutes, at the next natural tool boundary,
compare the artifact being built with the accepted outcome and canonical
example across kind, scope, count, and depth; name the last visible result,
classify current work, and choose the next gap-closing action. At the earliest
of roughly 45 minutes, two consecutive non-outcome increments, failed
deliverable equivalence, or user concern about pace, perform the fuller strategy
reassessment. Switch reversible in-scope tactics when another action is
materially better. Neither check needs a new artifact, approval pause, narrower
success criterion, or automatic context reset.

Do not build parallel coordination identity systems in downstream repos.
Coordinated assignment and operator surfaces consume the canonical
claim/session model owned here.

Only these stop conditions are legitimate:

1. an irreversible action that affects shared state
2. a genuine architectural decision not already pre-made in the active plan
3. no authorized, dependency-ready, evidence-supported, goal-advancing next
   action remains that is not irreversibly dangerous after bounded
   investigation; persist a resumable handoff and return control instead of
   manufacturing work or passively polling

## Canonical Surfaces

- `PLANNING_OPERATING_MODEL.md`
  - canonical methodology and artifact dependency graph
- `README.md`
  - source-repo overview: what the framework is, what ships, and how governed
    repos install it
- `GETTING_STARTED.md`
  - first successful installed-consumer path
- `ROADMAP.md`
  - forward queue and phase map
- `docs/plans/AGENTS.md`
  - numbered implementation plan queue for this repo
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
  - canonical definitions for claims, lanes, worktrees, and lane lifecycle
- `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md`
  - canonical portable pattern for overnight/continuous autonomous execution
- `docs/reference/CONFIG_REFERENCE.md`
  - authoritative config table, including which keys are not yet enforced

## Source Repo vs Installed Repo

Keep the perspectives separate:

- In this source repo, scripts live under `scripts/`
- In installed governed repos, generated entrypoints live under `scripts/meta/`
- `scripts/install_governed_repo.py` is the canonical installer/upgrader
- `install.sh` is a convenience wrapper for the default path and a legacy
  compatibility entrypoint for `--full` and `--pre-commit`

## Tool Support

- Claude Code has the strongest native interactive enforcement path because
  read-gating is wired through `.claude/hooks/`
- Both clients use authored `AGENTS.md`, the plan/doc methodology, and
  deterministic validators
- The portable support matrix and rollout policy are tracked in the Phase 8
  plan queue, not in ad hoc sprint notes

## Commands

```bash
# Canonical governed-repo install / upgrade
python scripts/install_governed_repo.py --repo-root /path/to/project --check
python scripts/install_governed_repo.py --repo-root /path/to/project --write
python scripts/audit_governed_repo.py --repo-root /path/to/project --strict-governed

# Convenience / legacy shell wrapper
./install.sh /path/to/project
./install.sh /path/to/project --worktree-only
./install.sh /path/to/project --pre-commit
./install.sh /path/to/project --full

# Framework validation
python scripts/self_test.py
python scripts/validate_plan.py --plan-file docs/plans/NN_example.md --warn-only
python scripts/check_plan_capabilities.py docs/plans/

# Source-repo maintenance
python scripts/check_agents_sync.py --check
python scripts/sync_plan_status.py
python scripts/complete_plan.py --plan N
python scripts/outcome_admission.py --help
python scripts/session_start.py --help
python scripts/session_heartbeat.py --help
python scripts/session_status.py --help
python scripts/prewrite_claim_gate.py --help
python scripts/check_coordination_claims.py --progress --help
python scripts/session_end.py --help
python scripts/session_finish.py --help
python scripts/session_close.py --help
python scripts/session_resume.py --help
python scripts/session_narrow.py --help

# Tests
pytest -q
make test
```

Plan #123 activates hard selected-outcome admission only in this source
repository through
`meta_process.claims.outcome_admission_mode: enforce_selected`. Session
start/heartbeat and supported native pre-write now derive the exact selected
claim state without an outcome flag and deny before mutation or success.
`make outcome-bootstrap PLAN=N ...` is the only sanctioned **planned** new-lane
path: its entire claim must resolve to one Plan-numbered bootstrap surface
before it may create the restricted worktree/session. The unplanned exceptions
are the strictly parsed maintenance-worktree and brand-new local-repository
bootstraps documented in the operator guide. Both require a native top-level
client, a safe literal branch, and `claim_type: program`; maintenance also
requires a canonical governed repository, while local initialization is
restricted to an absent direct child of a non-Git workspace and creates no
remote. Neither admits composed shell, unknown JSON fields, borrowed subagent
identity, or ordinary unclaimed mutations. An exact maintenance claim that
still matches that typed root-and-tracker contract may pass source-repository
selected-outcome admission only after the ordinary pre-write gate selects the
sole claim whose declared write paths cover every target. Generic `UNPLANNED`
claims, overlapping target authority, and mutations spanning disjoint child
claims remain denied. After the graph is canonical, bind,
allocate, select, and only then expand that same claim. The canonical
`scripts/session_start.py` and `scripts/session_heartbeat.py` own source Make
execution; their `scripts/meta/` mirrors must remain byte-identical through the
installer-declared lineage. Setting the mode to `off` or reverting the
activation commit is the recoverable rollback. This source activation does not
configure a downstream repo, execute an installer target, or establish fleet
adoption.

## Repo Workflow

1. Use `docs/plans/AGENTS.md` and `ROADMAP.md` to find the next bounded slice.
2. Work from the matching numbered plan doc.
3. Prefer sanctioned worktrees for multi-phase or overnight execution lanes.
4. Keep source-repo docs truthful when installer behavior, support tiers, or
   plan status changes.
5. Run `python scripts/self_test.py` before landing documentation or installer
   changes.
6. Use session lifecycle commands for coordinated or release work; a reversible
   single-writer development task does not need a session/claim lifecycle.
7. Use `session-close` or `make worktree-remove` for claimed lane cleanup; do
   not manually split claim release from worktree removal.
   Before destructive cleanup, `session-close` refreshes the advertised
   `origin/main` history while the lane still owns writes. This keeps the
   start-revision range locally readable in partial clones after the lane ref
   and worktree are removed; a failed refresh remains a visible `NOT CHECKED`
   report rather than a false unchanged result. A caller closing a lane in a
   different repository must pass `--repo-root <canonical target repo>`;
   `make session-close` supplies `WORKTREE_REPO_ROOT` so fetch, merge-base, and
   shared-ref range evidence are read from that target repository.
   A legacy `session_ended` claim that recorded the canonical repository root
   is the one exception to physical cleanup: use `session-close
   --reconcile-canonical-root` with exact claim and tracker SHA-256 digests so
   only coordination metadata is archived and the repository and branch stay
   intact.
   A merged temporary child sharing its exact parent worktree and branch is the
   other metadata-only exception: close the child first with
   `session-close --terminalize-shared-child`, then close the retained parent
   normally. A different exact native runtime may close an existing linked
   worktree only after its claim is truly `session_ended`, its claim and tracker
   digests are supplied to `session-close --reconcile-session-ended`, and the
   ordinary merge or durable-recovery preflight passes. This terminal cleanup
   does not transfer write custody; continuing unmerged work still uses
   `session-resume`. A `session_ended` claim whose recorded session tracker
   never existed has no digest to supply and cannot be resumed, so it adds
   `--tracker-absent` (plus `--claim-sha256` and `--recovery-archive-dir`) to
   that same command: absence is verified, the worktree's status, head, and a
   recovery ref are captured first, uncommitted state is bundled under the
   named archive directory, and a lane with unsaved work keeps its worktree and
   branch while only the claim is dispositioned. Cross-session Codex `session-resume` requires the exact
   predecessor PID plus `/proc` start ticks, and fences that verified
   session/worktree process under the exact claim-bytes transfer epoch before
   claim custody changes.
8. One runtime session owns one unparented live claim root by default. Claim
   type does not exempt a lane from this lifecycle guard. Related work declares
   `parent_scope`; intentional additional roots require explicit parallel
   authorization.
   A new broad write claim must declare `bootstrap` or `bounded` intent plus a
   non-empty reason. Use `session-narrow` to reduce it; bootstrap claims cannot
   authorize ordinary repository writes until that owner/session-bound narrow
   succeeds.
9. A new plan-bound lane resolves the canonical default-integration tip once
   and retains that full revision through its pre-worktree claim, branch,
   worktree, and session tracker. Only an already-retained lane can resume from
   a non-tip through session-resume; a `--resume` flag is not provenance for a
   new claim. The pre-worktree claim intentionally lacks a tracker;
   session activation must add it or rollback only artifacts named as created
   by the worktree helper's receipt. Never infer historical revision custody for
   a running legacy claim.
   When a qualified plan belongs to another repository, Plan #130 separates
   that target start revision from the explicit `PLAN_REPO_ROOT` and full
   `PLAN_START_POINT` of the plan authority. Validate both current integration
   tips before new-lane mutation; retain both identities and the exact plan
   digest in the claim/tracker. Never copy a proxy plan into the target. See
   the operator guide's cross-repository plan-authority contract.
10. A PR does not need to be rebased onto the latest `main` before it can
    merge -- `main` moves too fast for a manual rebase to keep up (observed:
    repeated real merges landing within the ~1-2 minutes a single CI run
    takes). As of 2026-09-15 `main` has **no required status checks**: GitHub
    Actions jobs are refused on the account (billing/spending-limit), so Brian
    had Actions-backed merge requirements removed. Hosted CI provides no merge
    signal; run the focused local checks, open the PR, and merge with
    `gh pr merge --squash`. `finish_pr.py` passes the required-checks gate when
    the base branch configures none (PR #546). If required checks are
    restored, `gh pr merge --auto --squash` again waits for them. A real merge queue
    (serialized re-validation against the true tip) would be the stronger
    version of this, but is not available on the current plan tier for this
    repo -- confirmed by testing GitHub's own documented example against
    three different repos, all rejected identically. Real semantic overlap
    between two lanes is still caught independently by
    `push_safety.py`'s coordination-claim check, which does not depend on
    branch-protection strictness.

## Notes

- This repo is the framework source of truth; installed governed repos are
  consumers of generated/copied surfaces from here.
- `AGENTS.md` is the authored instruction authority for this source repo.
- Historical sprint notes under `docs/ops/` are evidence artifacts, not the
  active planning queue.
- `session_end.py`, `juice_checkpoint_hook.py`, `evidence_sample_launcher.sh`,
  and `learning_capture_hook.py` declare `scope: global_by_design` to
  consuming repos' `hooks/audit_hook_surface.py` (agent-skills): session
  lifecycle, the advisory pace pulse, evidence-sample dispatch, and the
  learning-disposition adapter are machine/session-wide, not per-project.

## Principles

- Governance is discriminating: checks report deterministic facts, and block
  only when the candidate can violate the protected contract and the selected
  execution mode requires blocking.
- Every repo gets the smallest stage-appropriate contract surface; development
  does not inherit coordinated or release controls solely because the framework
  can install them.
- Install is idempotent: running it twice leaves the repo in the same state
- Source truth is in this repo; installed repos are consumers of generated artifacts

## Workflow

1. Make changes to framework source
2. Run `python scripts/self_test.py` to validate
3. Run `python scripts/install_governed_repo.py --repo-root <consumer> --write` to propagate

## References

- `PLANNING_OPERATING_MODEL.md` — canonical methodology
- `docs/plans/AGENTS.md` — implementation plan queue
- `ROADMAP.md` — forward queue and phase map
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — worktree and lane lifecycle
