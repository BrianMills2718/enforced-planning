# Repo Workflow (Enforced Planning source repo)

Moved word for word from the root `AGENTS.md` on 2026-11-17 to keep that file under the
12,000-byte instruction cap. The root `AGENTS.md` routes here; these steps carry the same
authority as when they lived there.

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
   has a metadata-only close route: use `session-close
   --reconcile-canonical-root` with exact claim and tracker SHA-256 digests so
   only coordination metadata is archived and the repository and branch stay
   intact.
   Completed active canonical environment maintenance uses the separate
   `session-close --retain-canonical-environment` option with exact claim and
   tracker digests. It requires the exact native owner, an active write claim
   restricted to ignored `.venv`, and a clean pushed canonical default branch;
   the checkout, environment and branch are retained without ending the runtime.
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
