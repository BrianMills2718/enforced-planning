# Worktree And Coordination Operator Guide

Status: active

This is the day-to-day authority for claims, worktrees, and cross-agent
coordination. Other documentation has narrower roles:

| Concern | Authority |
|---|---|
| Runtime mechanics and operator workflow | This guide |
| Host and repository configuration | `docs/reference/CONFIG_REFERENCE.md` |
| Personal repository eligibility/publication policy | Project Meta policy registry and `docs/ops/GIT_PUBLICATION_AUTHORITY_POLICY.md` |
| Instruction-hook consumer behavior | Agent Skills `README.md` |
| Rationale and rollout history | ADRs and plan files; not current operator handbooks |

## Canonical Truth Surfaces

| Truth | Surface |
|---|---|
| Live ownership | `~/.claude/coordination/claims/*.yaml` |
| Hook-optimized projection | `~/.claude/coordination/prewrite-authority-v1.json` |
| Current-work readout | `python scripts/meta/check_coordination_claims.py --list --json` |
| Consistency audit | `python scripts/check_coordination_consistency.py --repo PROJECT=/absolute/repo/path --verify-prewrite-projection --json` |
| Repository policy | `meta-process.yaml` |
| Worktree lifecycle | `make worktree*`, `scripts/meta/check_coordination_claims.py`, and `enforced_planning/worktree_lifecycle.yaml` |
| Publication gate | `make push-check` / `scripts/meta/check_push_safety.py` |

The older repo-local `.claude/active-work.yaml` plus legacy
`scripts/meta/worktree-coordination/check_claims.py` surface may still be
present in some repos for compatibility. They are not the canonical
cross-project coordination authority.

## Core Model

A **claim** is the canonical ownership record; a **lane** is the bounded work
derived from it; a **worktree** is the lane's checkout; and a **plan** defines
the outcome when planning is required. Claims are canonical and lanes are
derived—never maintain a second mutable lane registry.

The user-facing **Project Manager** prepares context, defines acceptance
criteria, may implement bounded single-writer work, delegates when useful, and
verifies results. **Orchestrator** names only the internal dispatch mechanism.
The Project Manager is delegation-only only when the operator explicitly sets
**coordinator-only** mode.

| Concept | Meaning | Grants mutation? |
|---|---|---|
| Launch directory | Navigation/start location, including non-Git `~/code` | No |
| Read target | Any repository whose governing instructions have been loaded | No |
| Write target | Exact repository/worktree selected by its matching healthy native-session claim | Only within that claim |
| Mutation authority | The live claim plus its declared paths | Yes, as bounded |

A session may hold healthy claims in multiple repositories. Every explicit
mutation target resolves independently to the one matching claim; the launch
directory and previously used repository do not select authority. Releasing a
claim removes only that write authority and never changes read access.

File tools select a claim from their explicit absolute target. Cross-root
mutating Bash selects a claim through one literal worktree-attesting form:
`/usr/bin/env -C <worktree> ...`, `git -C <worktree> ...`, or
`make -C <worktree> ...`. An unqualified relative mutation is accepted only
when exactly one healthy claim makes its target unambiguous; with zero or
multiple healthy claims it fails closed. This is target-aware claim resolution,
not a second portfolio or lane registry.

Subagents use their own `agent_id`, targets, and claims and inherit none of the
parent's mutation authority.

## Workspace-Root Maintenance Bootstrap

With no claim and a non-Git launch directory, the only mutation exception is
this typed transaction:

```text
/usr/bin/python3 <absolute-canonical-framework>/scripts/claim_bootstrap.py --request-json '<JSON>'
```

The request is one strict object; field order is irrelevant:

```json
{"schema_version":"1.0","operation":"maintenance_worktree","agent":"codex","project":"repo-name","scope":"fix/safe-branch","repo_root":"/absolute/repo","branch":"fix/safe-branch","claim_type":"program"}
```

The native client, project id, scope/branch, canonical Git root, GitHub origin,
and provider response must all agree. The provider owns operator-specific
eligibility; Enforced Planning owns protocol validation. Extra fields, unsafe
paths or branches, composition, subagents, ambiguous authority, existing lane
artifacts, and client mismatch are denied.

The optional `write_paths` array narrows initial ownership to literal
repository-relative paths, for example `["scripts/adapter.py", "tests/test_adapter.py"]`.
Omitting it requests the legacy-looking `["."]` scope, but new maintenance
bootstraps persist that scope as typed `bootstrap` custody: the real target is
available for instruction/read context while ordinary repository mutations are
denied. The canonical claim and tracker always retain the same physical
worktree identity; only the derived pre-write projection substitutes a
non-authorizing sentinel while bootstrap authority is disabled. The owning
native session must run
`make session-narrow` with explicit descendant `SESSION_WRITE_PATHS` before its
first repository write. A Project-Graph-registered repository that does not
install the Make target may invoke the canonical absolute `session_narrow.py`
runtime directly; it remains bound to the ambient native session, exact claim,
and strict descendant paths. Empty lists,
duplicates, traversal,
absolute paths, glob patterns, and mixed broad/narrow declarations are rejected.
Narrow creation uses the same registry overlap checks: it can coexist with
unrelated writers but cannot override another writer's overlapping claim.

Before creating anything, bootstrap verifies the remote default, fetches its
exact commit, and uses it as the lane base. It then creates the branch,
worktree, exact-session claim, tracker, and projection transactionally; failure
removes only artifacts created by that attempt. Checkout occurs only after the
claim is durable. Raw Make or shell escape forms are not authority surfaces.

### Brand-new local repository

The same exact native command surface can initialize a repository that does not
yet have a remote or Project Graph record:

```json
{"schema_version":"1.0","operation":"local_repository_worktree","agent":"codex","project":"weekly-plans","scope":"codex/initial-setup","repo_root":"/absolute/workspace/weekly-plans","branch":"codex/initial-setup","claim_type":"program"}
```

Run it from the repository's intended workspace parent. The target must be an
absent direct child of that directory, and the workspace parent must not itself
be inside a Git worktree. The project id must equal the target directory name;
the scope must equal a safe non-default task branch. Whole-repository ownership
is fixed to `write_paths: ["."]` for this first lane.

This transaction creates a local `main` branch with only `/worktrees/` ignored,
then creates the requested linked worktree, exact-session claim, tracker, and
projection. It configures no remote, performs no network request, and grants no
publication authority. Continue all project edits in
`<repo>/worktrees/<branch>/`. The live claim makes the canonical checkout
physically read-only, so do not run `git merge` there directly. After committing
the lane, use the same exact native command surface for the controlled local
integration:

```json
{"schema_version":"1.0","operation":"local_repository_integrate","agent":"codex","project":"weekly-plans","scope":"codex/initial-setup","repo_root":"/absolute/workspace/weekly-plans","branch":"codex/initial-setup","default_branch":"main"}
```

The integration transaction accepts only the current native owner of the
repository's sole live claim, a clean local-only canonical checkout on `main`,
a clean exact claimed worktree, a healthy canonical lock justified by that
claim, and an exact fast-forward. It unlocks only for that merge and restores
the same lock in `finally`, including when Git fails. Direct canonical-checkout
mutation remains forbidden. After integration, the ordinary session-close path
can prove local integration and close the lane.
Registration in Project Graph and remote publication remain separate authority
decisions.

`agent` identifies the client class; `session_id` identifies the runtime that
owns a live claim. Two Codex windows are therefore two writers even though both
claims say `agent: codex`. A live `agent + project + scope` slot may be refreshed
only by its exact owning session. A different session must use sanctioned
handoff/session-end plus session-resume before it may hand off, abandon, finish,
or close the lane; claim creation fails
without changing the claim or its derived projection.

New-lane creation is stricter: `require_new` bypasses same-owner refresh, then
rejects an occupied slot or creates the claim while holding the registry lock.
A concurrent exact-owner claim therefore cannot turn bootstrap into refresh.

A successful cross-session `session-resume` also writes one immutable
`claim_session_custody_transfer` receipt under the coordination root and returns
its exact path and SHA-256. The receipt binds the project, scope, repository,
worktree, branch, predecessor and successor sessions, transfer time, and exact
pre/post claim bytes. Downstream execution cursors may consume that receipt to
move their own lease without treating prose or a session ID alone as transfer
authority. Same-runtime resume returns no custody-transfer receipt. Claim,
tracker, projection, mutation evidence, and custody receipt are serialized under
the claim-registry then tracker locks. Non-Codex cross-session transfer restores
the exact predecessor claim and tracker bytes when a commit step fails. When a
successor mutation event was already appended, rollback appends a compensating
predecessor event whose terminal registry digest matches the restored authority.
Codex uses the durable fenced-transfer journal below instead of rollback, because
restoring pre-fence bytes would erase the evidence required to recover custody.
Resume never reports a successor while the claim and tracker disagree.

Codex-to-Codex custody transfer additionally requires
`--predecessor-process-pid` and `--predecessor-process-start-ticks`. Before
changing claim custody, `session-resume` proves that exact PID generation is a
direct Codex resume of the predecessor session, is using the successor runtime's
exact Codex executable, and has the claimed worktree as its current directory.
The state key also binds the exact pre-transfer claim-bytes SHA-256 so evidence
cannot cross custody epochs. It binds `/proc` start ticks against PID
reuse, opens an exact kernel pidfd before validation, and sends bounded
TERM/KILL escalation only through that handle. Before signaling, it fsyncs a
deterministic active intent. Before that signal boundary, `session-resume`
also writes a `session_takeover_reservation` into the predecessor claim under
the claim-registry lock. The reservation binds the exact pre-reservation claim
bytes, successor, worktree, PID, and start ticks; predecessor heartbeat and
progress mutations reject while it is active. A failed custody commit retains
the reservation so retry consumes the same fence epoch without signaling a
gone process, and only the successful successor commit removes it. After a
confirmed exit the process fence atomically finalizes an
immutable mode-0600 process-fence receipt; retry either resumes the same
start-tick identity or finalizes an already-absent/replaced predecessor without
signaling the replacement. The custody-transfer receipt embeds the exact fence
receipt path and SHA-256, and the custody transaction independently recomputes
the predecessor claim-bytes digest before consuming that fence epoch. The
consumer parses the referenced bytes as the typed process-fence receipt, checks
its predecessor, successor, worktree, PID generation, and epoch against both
the pre-transfer claim, exact requested PID/start generation, and fencing
result, and derives the custody binding only from that parsed receipt. Missing,
malformed, stale, ambiguous, or
mismatched process identity
fails before the claim or tracker changes; never replace this contract with a
process-name-wide kill.

After fencing, the reservation gains an exact-byte
`claim_session_transfer_journal`. The journal binds the predecessor tracker,
successor tracker, successor claim, claim epoch, and typed process-fence receipt
by SHA-256. The locked write order is journalized predecessor claim, immutable
custody receipt, successor tracker, then successor claim last. The final claim
write is the commit point and consumes the reservation. An abrupt stop after
the journal, receipt, or tracker write therefore leaves the durable reservation
and journal available for exact replay; the tracker may equal only the recorded
predecessor or successor bytes. Retry reuses the same process-fence receipt and
must not signal an absent or replacement process. An abrupt stop after the final
claim write is already committed and resumes through the ordinary same-runtime
path. Any bytes outside the journal's two allowed authority states fail closed.

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
   For bounded light maintenance without a numbered plan, use
   `make maintenance-worktree BRANCH=<name>`; the Make target builds one typed
   `maintenance_worktree` request and delegates claim, worktree, tracker, and
   explicit `UNPLANNED` linkage creation to the atomic claim-bootstrap
   transaction. `BRANCH` is the only required input and the agent defaults from
   the runtime. When the lane does not declare `SESSION_WRITE_PATHS`, the typed
   transaction supplies the one temporary program write scope itself (`.`): it
   is bounded by the named repository, branch, worktree, and native session,
   then must be narrowed before scoped implementation begins.
   In generated consumers, the installer owns `scripts/meta/claim_bootstrap.py`
   and the synchronized bootstrap authority module. Claimless host admission
   requires the exact rendered worktree block and exact installed wrapper/module
   digests, so unrelated Makefile content remains consumer-owned without being
   trusted as control code.
   An explicit `SESSION_WRITE_PATHS="..."` overrides that default and is
   claimed as given without bootstrap mode, reason, or target metadata; those
   fields describe only the implicit repository-wide `.` custody state. Do not read the
   bootstrap `.` as mandatory: discarding a declared scope made every
   maintenance lane claim the whole repository and therefore overlap every
   other active lane, and because the overlap message reads
   `<yours> <-> <theirs>`, the lane's own broad claim looked like someone
   else's. `make worktree` (plan-owned lanes) deliberately keeps every input
   explicit, including `SESSION_WRITE_PATHS="..."`.

   In a repository with hard selected-outcome admission, that maintenance
   claim is exempt from selecting a planned outcome only while its exact root
   identity and typed tracker still satisfy the maintenance contract. The
   ordinary pre-write gate remains authoritative: it selects the sole
   same-session claim whose declared `write_paths` cover every mutation target,
   then validates that selected claim's health. Parent and child claims with
   disjoint paths therefore do not conflict, but overlapping authority remains
   ambiguous and separate claims never combine to authorize one multi-target
   mutation. A generic `UNPLANNED` claim is not this exemption.

   The pre-commit canonical-checkout guard's escape hatch,
   `ALLOW_CANONICAL_CHECKOUT_COMMIT=1`, is metered per repository per session:
   the first use is recorded quietly, the second warns, the third is refused.
   The ledger is `<repo>/.git/canonical-checkout-hatch-uses`. A genuine emergency
   passes `CANONICAL_CHECKOUT_HATCH_OVERRIDE="<reason>"` alongside it, which is
   allowed and records the reason; `ENFORCED_PLANNING_HOOK_MODE=off` still
   disables the whole check suite for one reversible commit. The metering exists because the hatch used to be free: on
   2026-08-23 one session took it six times across two repositories rather than
   create a single worktree.
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
   - `plan_ref` (a canonical numbered/qualified plan authority, exact
     `goal:<outcome-id>` authority, or `UNPLANNED` only through the explicit
     maintenance path)
   - `branch`
   - `worktree_path`
   - `session_id`
   - `session_name` (the durable broader-goal name when it differs from the runtime ID)
   - narrow `write_paths` for write claims
4. Execute, commit verified slices, and keep docs/trackers truthful.
5. Push from the checked-out claimed branch. The installed `pre-push` hook runs
   the canonical deterministic push check automatically. Use `make push-check`
   directly when diagnosing a blocked push.
6. Merge/push from the safe root-anchored control session. Keep the source
   claim live until the default-branch integration is pushed. The push gate
   permits that overlap only for the exact native session when the claimed
   branch is an ancestor of `HEAD` and no claimed path changed after its tip;
   cross-session ownership or later claimed-path changes still block.
7. Record the lane disposition and use `session-close` to make the claim
   non-live, retain its completed audit record, remove the worktree, and safely
   delete the local branch.

### Legacy canonical-root claim reconciliation

An older operator lane may have recorded the canonical repository checkout as
its `worktree_path`. Ordinary `session-close` must never process that record as
a removable linked worktree. After the owning runtime is truly ended and the
branch is integrated, archive only its coordination metadata with:

```bash
python scripts/session_close.py \
  --agent codex --project PROJECT --scope SCOPE \
  --reconcile-canonical-root \
  --claim-sha256 EXACT_CLAIM_SHA256 \
  --tracker-sha256 EXACT_TRACKER_SHA256 \
  --json
```

This exceptional reconciliation fails closed unless the claim is exactly
`session_ended`, both preserved files match their supplied digests and each
other's identity, the recorded path is the existing clean canonical Git main
worktree, and its checked-out branch matches the claim. It records the exact
claim/tracker binding in the completed archive while retaining the repository
directory, worktree registration, checked-out branch, branch ref, repository
contents, and submodules. It never calls worktree removal or branch deletion.
Use ordinary `session-close` for real linked worktrees and
`--reconcile-missing-worktree` only for an already-absent recorded worktree.

### Append-only stores do not create contention

Two lanes declaring the same write path normally conflict, and the second lane
cannot be created. That is correct for any path where one lane's write can
destroy another's.

It is wrong for an append-only store, where every write creates a new
immutable file under a unique id through an atomic exclusive open. Two lanes
appending there produce different filenames, rewrite nothing, and merge
cleanly. Blocking the second lane prevents no loss and stops the work.

`APPEND_ONLY_WRITE_PREFIXES` in `enforced_planning/coordination_claims.py`
names those stores. `_compute_overlapping_write_paths` drops a pair when
**both** sides are append-only; one such path in a claim does not exempt the
rest of it.

The exemption covers a listed store and anything beneath it, and nothing else.
A parent that also reaches mutable siblings stays exclusive: claiming
`learnings` still conflicts, because it reaches `learnings.md`, which lanes
rewrite. Matching is on path segments, so a differently-named neighbour such
as `learnings/entries-archive` is unaffected.

Add a prefix only when writes to it are append-only all the way down — its
writer creates new files and never modifies, renames, or deletes an existing
one. Anything else belongs in an ordinary exclusive claim.

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

Mandatory rule: no live session without `plan_ref`. Bounded light maintenance
may use the explicit `UNPLANNED` marker through the typed workspace-root
maintenance transaction above or, from an already governed repository, through
`make maintenance-worktree`;
it is not an absent plan reference and does not require a manufactured work
graph. Exact `goal:<outcome-id>` is a real sequential
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

For the sanctioned repo-local `make worktree` flow, the default claim is a
healthy **program** claim with real `branch`, `worktree_path`, and `session_id`
metadata. That keeps lane tracking healthy without inventing a fake broad
write-path claim for the whole repo. A repository that requires
selected-outcome activation is stricter: a plan-bound staged lane with explicit
file ownership uses `SESSION_CLAIM_TYPE=write` and complete
`SESSION_WRITE_PATHS`. A broad program claim cannot attach as
selection-pending write authority.

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

One exact exception breaks the closeout circularity for a merged temporary
child claim that shares its parent's worktree and branch. Close that child
first with `session-close --terminalize-shared-child --disposition merged
--merge-commit <sha>`. The command requires the exact owning session,
`parent_scope`, one live parent with the same canonical repository, worktree,
and branch, and ordinary canonical merge ancestry. Worktree or branch arguments
must equal the child's recorded custody; caller overrides cannot substitute a
different parent's resources. The command archives only the child and reports
the worktree and branch retained for the parent. Then close the parent through
ordinary `session-close`; the child flag never removes or releases parent-owned
Git resources.

The compatibility `scripts/worktree-coordination/finish_pr.py` path also fails
closed. It resolves the repository owner through the isolated GitHub-account
seam, fetches the exact pull-request head, requires GitHub's complete required
check set, and runs the evidence-bound programmatic plus fresh-agent review from
the clean linked worktree. Its review specification must be an absolute path
both lexically and after symlink resolution outside the repository and its
worktrees. Installed-package consumers receive a standalone copy of the review
runtime so the finish entrypoint does not depend on a vendored package tree.
After review it rechecks the live head
and required checks, then requires canonical integration authority for the
exact native agent, canonical project, claim, reviewed work graph/unit, review
spec digest, base, and head. It holds the registry-backed authority guard while
passing that same full commit to `gh pr merge --squash --match-head-commit`.
A missing, rejected, stale, or claim-mismatched review never reaches merge. If
the merge succeeded but the process crashed before closeout, a retry re-observes
the exact GitHub merge, reruns the review and authority assertion, skips a
second merge, and resumes closeout. The helper does not request branch deletion as part of the
merge; only verified GitHub merge evidence is passed into the sanctioned
claim/worktree close lifecycle, which owns local branch deletion.
Before closeout, the helper fetches the canonical base ref and proves that the
reported merge commit is retained by `origin/<base>`. This makes the merge
object and updated remote-tracking ref available to squash-closeout validation
before the linked worktree or claim is removed.

Hooks provide the fast enforcement layer: they block direct merge commands and
route callers to `make finish BRANCH=<branch> PR=<number>
REVIEW_SPEC=/absolute/review-spec.json`. The expensive review never runs inside
`PreToolUse`, avoiding hook timeouts. This is operational enforcement on clients
with the governed hooks installed; GitHub branch protection remains useful for
repository-wide CI checks but no GitHub App is required for semantic signoff.
The installer also rejects unmarked legacy `make merge` or `make finish`
recipes, preventing a later duplicate target from overriding this transaction.

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
  --repo-root /absolute/example-repo \
  --work-graph docs/plans/42_example_work_graph.json \
  --work-unit-id unit-a \
  --branch plan-42-unit-a --worktree-path /absolute/example-repo/worktrees/plan-42-unit-a \
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

All three prune operations (`--prune`, `--prune-stale`, and
`--prune-completed`) accept `--agent`, `--project`, and `--scope`. Supplied
selectors are conjunctive and are applied before any registry mutation. The
JSON result reports both the count and the exact `project:scope` labels removed.
Unsupported agents and explicitly blank or whitespace-only project/scope
selectors fail before the claim registry lock is acquired.
Omitting every selector is an explicit fleet-wide cleanup and may remove every
claim eligible for that prune mode; use at least one selector for targeted
operator cleanup.

To remove claims that are already explicitly closed, use:

```bash
python scripts/meta/check_coordination_claims.py --prune-completed --json
```

That command only removes valid YAML claims whose status is `complete` or
`completed`. It does not prune active claims, even when their TTL has elapsed.
An exact-scope cleanup cannot prune unrelated completed claims.

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

### Representative outcome-admission decision

Plan #121 completed that first-consumer review without activating a hook. The
frozen suite contains 30 cases: 29 scored positive, negative, validation, and
held-out cases plus one unscored cross-repository calibration case. Run the
exact accepted candidate with:

```bash
python scripts/evaluate_outcome_admission.py \
  --cases evals/outcome_admission/plan121_cases.json \
  --population evals/outcome_admission/plan121_population_snapshot.json \
  --candidate-revision d30696a06f5120bb69df255137f2293dbc1a752e \
  --corruption-control
```

The canonical result digest is
`f7cd2b73f3565025e90b10dcd8cc883ff567fa39dddfd403d68ae174bf98a6b7`.
Two exact runs matched all 29 scored cases with zero critical false blocks,
zero critical false allows, zero unexpected defers, and complete safe-operation
recall and circular/bypass rejection. An independent verifier reproduced the
result, rejected changed fixture bytes and a nonexistent candidate revision,
and matched eight newly invented precedence and boundary cases.

This result licenses design and implementation of one hard Enforced Planning
consumer only. It does not activate host hooks, establish installer or fleet
adoption, support cross-repository allocation membership, judge the semantic
truth of progress evidence, or choose Brian's active product outcome. The
future hard consumer must preserve ordinary-authority precedence, passive
inspection/replay/preservation/closeout, a write-free allocation bootstrap,
active-child reuse, bounded recovery, legacy cutover until renewal, and visible
denial for missing, inactive, mismatched, stalled, or terminal outcome state.

### Planning Integrity at the worktree and direct-claim boundary

Planning Integrity is a versioned admission prerequisite configured in the
plan-authority repository; the current framework defaults to `enforce` unless
explicitly disabled. Same-repository consumers configure it locally:

```yaml
meta_process:
  plans:
    plans_dir: docs/plans
    integrity:
      mode: enforce       # off | observe | enforce
      contract_version: 1.0.0
      minimum_plan_number: 125
```

For an applicable coordinated or release lane, the sanctioned entrypoint does
this in order:

1. resolve the requested start point and canonical default-integration tip to
   full Git commits;
2. read the plan, `meta-process.yaml`, work graph, and approval bytes from that
   one immutable start revision;
3. validate Planning Integrity at those committed bytes;
4. query the configured plan-graph owner; and
5. only after both authorities admit the lane, create a revision-bound claim,
   branch/worktree, and session tracker that all retain the same start commit.

Dirty corrected bytes cannot rescue an incomplete start revision. Moving
symbolic `HEAD`, supplying an older passing commit for a new lane, or omitting
the Make wrapper from a direct plan-bound claim does not change the accepted
revision. These one-revision rules describe same-repository plans; the external
authority extension below preserves two independent revisions. A retained non-tip revision resumes only through the existing
session-resume/recovery lifecycle.

The first-success Make shape is:

```bash
make worktree \
  BRANCH=plan-125-bounded-unit \
  TASK="Execute the ready Plan 125 unit" \
  PLAN=125 \
  PLAN_READINESS_COMMAND="/path/to/plan-graph-python /path/to/plan_graph.py" \
  SESSION_CLAIM_TYPE=write \
  SESSION_GOAL="Deliver the broader accepted outcome" \
  SESSION_PHASE="Execute the selected bounded unit" \
  SESSION_WRITE_PATHS="docs/owned-surface.md" \
  SESSION_WORK_GRAPH="docs/plans/125_work_graph.json" \
  SESSION_WORK_UNIT_ID="ready-unit-id"
```

Use `PLAN_RESUME=1` only when the graph truthfully reports the plan already in
progress and no live claim owns it. The readiness command is explicit because
the portable framework does not own or discover a personal plan-graph
installation. Repositories without selected-outcome enforcement may retain the
default program claim; `SESSION_CLAIM_TYPE=write` is required when staged
selection must confer bounded file authority.

Direct plan-bound claim acquisition is not a bypass. Supply `--repo-root`, an
exact `--start-point`, `--plan`, `--work-graph`, and `--work-unit-id` to the
canonical `check_coordination_claims.py --claim` entrypoint. It reuses the same
committed Planning Integrity check and rejects a non-tip new claim, an occupied
slot, mismatched graph/unit scope, or incomplete plan before mutation.

`observe` mode preserves the nonblocking lane result but must expose the full
typed findings. `enforce` rejects missing, malformed, unsupported, unreadable,
or failing inputs. In either mode, `pass` means the declared structural
frontier conforms. It does **not** establish omitted-area coverage, semantic
correctness, usefulness, or plan optimality.

#### Cross-repository plan-authority contract

A qualified plan such as `project-meta#249` may govern an AES implementation
without a proxy copy of that plan in AES. Keep these inputs distinct:

| Custody | Make inputs | Committed bytes validated |
|---|---|---|
| Mutation target | `WORKTREE_REPO_ROOT`, `WORKTREE_PROJECT`, `WORKTREE_START_POINT` | target work graph, work-unit readiness, approvals, branch/worktree start |
| Plan authority | `PLAN_PROJECT`, `PLAN_REPO_ROOT`, `PLAN_START_POINT` | numbered plan and its integrity configuration |
| Bounded execution | `SESSION_WORK_GRAPH`, `SESSION_WORK_UNIT_ID`, native session and claimed paths | the selected target unit and that session's mutation ownership |

`PLAN_REPO_ROOT` must be an explicit absolute canonical repository matching the
qualified plan identity. `PLAN_START_POINT` must be a full immutable commit.
Both authority and target must resolve to their current default-integration
tips for a new lane. The target unit's `design_revision` must equal
`sha256:<exact committed plan digest>`. Missing, wrong, stale, or mismatched
inputs deny before claim/branch/worktree mutation; a launch directory supplies
neither identity nor authority. The same CLI inputs are `--plan-repo-root` and
`--plan-start-point` on readiness, claim, and session-start entrypoints.

External claims retain `plan_repo_root`, `plan_revision`, and `plan_sha256`
alongside the target `start_revision` and graph digest (claim schema v5,
tracker schema v3). Session activation and later refresh revalidate those exact
identities; omission during refresh preserves them, and explicit rebinding is
denied. A retained lane may keep its original revisions through the recovery
lifecycle; it cannot turn a stale revision into authority for a new lane.

Structural integrity mode `off` does not remove exact external plan custody:
one committed numbered plan and its digest are still required, without
changing that repository's policy. Local plans omit the two authority inputs
and retain their existing single-repository behavior and schema versions.
Supplying local overrides cannot substitute another repository or revision.
This is explicit authority binding, not automatic repository discovery or an
expansion of any claim's write paths. See Plan #130 for the AES acceptance
example and retained verification evidence.

When the consumer declares an installed `enforced-planning` dependency, the
worktree-only installer updates wrappers and Make targets without vendoring a
shadow package. Update the consumer's exact dependency pin and runtime through
its package workflow as well; wrapper installation alone does not upgrade the
framework implementation. A stale installed lifecycle fails visibly rather
than dropping the external-authority inputs.

### First-consumer hard outcome admission (explicit source pilot)

Plan #122 implements that one source consumer, but leaves every new path
default-off. The production owner is `enforced_planning/outcome_admission.py`;
the Plan #121 evaluator now calls the same owner instead of retaining a second
decision algorithm. Admission derives portfolio and continuation labels from
the exact live claim, tracker, selection, allocation ledger, scenario, and
effective lease. A caller can select the boundary and opt in to enforcement,
but cannot claim that an allocation is active or progress is healthy.

Inspect the fixed allocation-bootstrap scope before mutation with:

```bash
python scripts/outcome_admission.py bootstrap \
  --plan 122 \
  --write-path docs/plans/122_first_consumer_outcome_admission.md \
  --write-path docs/plans/122_first_consumer_outcome_admission_work_graph.json \
  --write-path examples/owner-real-outcome-admission/plan122-maintenance-scenario.json \
  --write-path examples/owner-real-outcome-admission/plan122-maintenance-allocation.json \
  --write-path examples/owner-real-outcome-admission/plan122-maintenance-disposition.json \
  --write-path docs/plans/CLAUDE.md \
  --write-path ROADMAP.md \
  --receipt-path /path/to/outcome-admission-v1.jsonl
```

The bootstrap allows only the exact nonempty plan, matching work graph,
Plan-numbered input examples, plan index, and roadmap shapes. It grants no Git
or claim authority. Any source, script, test, evidence, traversal, foreign-plan,
or arbitrary path returns nonzero. The sanctioned worktree bundle invokes the
same check only when `OUTCOME_ADMISSION_BOOTSTRAP_PLAN=<plan>` is set.

Once the exact allocation and selection exist, operators can inspect admission
without mutating lifecycle state:

```bash
python scripts/outcome_admission.py selected \
  --agent codex --project enforced-planning \
  --scope plan-122-first-consumer-outcome-admission \
  --session-id codex:EXACT_SESSION_ID \
  --boundary heartbeat --renewal \
  --receipt-path /path/to/outcome-admission-v1.jsonl
```

Hard lifecycle admission is explicit:

```bash
python scripts/session_heartbeat.py \
  --agent codex --project enforced-planning \
  --scope plan-122-first-consumer-outcome-admission \
  --session-id codex:EXACT_SESSION_ID \
  --outcome-selected \
  --outcome-admission-receipt-path /path/to/outcome-admission-v1.jsonl \
  --json

python scripts/prewrite_claim_gate.py \
  --client codex --mode enforce \
  --outcome-enforce-selected \
  --outcome-receipt-path /path/to/outcome-admission-v1.jsonl \
  --json
```

`session-start` and `session-heartbeat` also receive the same opt-in through
`OUTCOME_ADMISSION_SELECTED=true`; their receipt path comes from
`OUTCOME_ADMISSION_RECEIPT_PATH`. Session start, resume, and heartbeat are
renewal boundaries even when a lower-level caller omits a renewal hint. Hard
pre-write runs only after ordinary claim admission, so an ordinary denial stays
denied. An ordinary allow becomes nonzero when selected outcome admission
denies. Missing, malformed, inaccessible, inactive, mismatched, out-of-scope,
recovery-required, stalled, or terminal state fails visibly before lifecycle
mutation or pre-write success. Receipt append failure also fails the opted-in
operation.

Those flags remain the explicit compatibility path for repositories whose
`claims.outcome_admission_mode` is absent or `off`. Plan #123 activates the
same owner only in the Enforced Planning source repository:

```yaml
meta_process:
  claims:
    prewrite_mode: enforce
    outcome_admission_mode: enforce_selected
```

In that configured source checkout:

- `make outcome-bootstrap PLAN=N ...` performs the explicit bootstrap
  admission before claim, worktree, or session creation; the complete
  `SESSION_WRITE_PATHS` set must contain one unique Plan number and only that
  Plan's plan, work graph, allocation fixtures, plan index, or roadmap;
- source `make worktree`, `make session-start`, and
  `make session-heartbeat` prefer the canonical `scripts/session_*.py`
  owners when present, with installed `scripts/meta/` files only as fallback;
- ordinary session heartbeat renews liveness only; exact selected state is
  required only when the caller explicitly requests outcome-selected
  admission;
- native pre-write automatically requires selected state after ordinary
  authority, except for an exact restricted bootstrap claim writing one of its
  own bootstrap paths; and
- an explicit selected-outcome heartbeat flag gates that renewal through
  selected outcome admission; omitting it performs owner-bound liveness refresh
  only and never renews outcome state. Changing approval text, increasing
  elapsed time or cost, or passing a weaker ordinary mode cannot change an
  explicit selected-outcome decision.

Malformed mode values, ambiguous or mixed bootstrap claims, source smuggling,
missing selection, inactive allocation, and stalled or terminal continuation
all fail visibly before protected success. Set
`claims.outcome_admission_mode: off` or revert the activation commit to roll
back. The accepted Plan #122 explicit-pilot evidence remains
`docs/evidence/plan122_first_consumer_outcome_admission.json`; Plan #123's
source-activation evidence is
`docs/evidence/plan123_source_outcome_admission_activation.json`.

Plan #123 synchronizes source lifecycle mirrors and closes the installer's
runtime dependency closure, but it does not execute an installer against a
consumer, change a downstream config, install a user-level hook, establish
fleet adoption, solve cross-repository allocation membership, certify semantic
progress, or select Brian's active product outcome.

Important rule: do not name sessions after the immediate local task. A branch
like `plan-31-hygiene-gate` is fine for git, but the session name should derive
from the broader goal, such as `digimon-truthful-controller-grounding`.

Canonical lifecycle commands:

- `session-start`: create or refresh the claim-linked session contract
- `session-heartbeat`: refresh the lease and tracker timestamp
- `session-narrow`: atomically replace a claim's write paths with a strict
  owner/session-bound subset without renewing its heartbeat or expiry
- `session-status`: show live sessions derived from claims plus trackers;
  missing Codex display-index metadata is reported separately and never
  overrides independent heartbeat, progress, hook, or runtime evidence
- `session-end`: detach a terminating runtime from all of its exact-session
  claims without deleting branches, worktrees, trackers, or Git objects
- `session-finish`: record an explicit dirty handoff; a clean managed lane must
  use `session-close` and cannot retire ownership here
- `session-close`: clean up a claimed lane end-to-end by removing the worktree,
  safely deleting the local branch, archiving the exact terminal claim, and
  removing it from the live registry after merge/disposition preflight
- `create_publish_worktree.py`: create a merge/push control worktree only when
  the canonical main checkout is already clean

- `session-resume`: attach a new runtime to an existing plan-bound lane and,
  when selected state exists, append an exact lossless outcome transfer
- `session-handoff`: intentionally pause or transfer work with a durable note
- `session-abandon`: explicitly mark a dead lane as abandoned instead of
  leaving it stale forever

Every terminal mutation (`session-finish`, `session-close`, `session-handoff`,
and `session-abandon`) is bound to the exact claim-owning native session. A
foreign runtime must first use `session-resume`; supplying the predecessor's ID
does not impersonate it when the client exposes a different native identity.

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

Supported runtime adapters for actor-bound lifecycle mutations:

- Codex: `CODEX_THREAD_ID`
- Claude Code: `CLAUDE_CODE_SESSION_ID`
- OpenClaw: `OPENCLAW_SESSION_ID`

An explicit owner ID, process discovery, or an SSE port cannot self-attest a
foreign runtime for heartbeat, handoff, abandon, finish, or close. The adapters
only bind the ambient actor identity; they do not change the session contract
schema, tracker schema, or sanctioned repo lifecycle commands.

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
python /absolute/canonical-enforced-planning/scripts/session_end.py \
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

`session-status` is a strictly read-only observer. It takes shared locks only
when the existing writer-owned lock files can be opened without mutation. When
a lock is absent, it accepts only an optimistic claim/tracker snapshot whose
source bytes stay stable and whose lock remains absent; it never creates or
chmods lock files, creates directories, or prunes stale staging artifacts.

The Company Planning execution loop is admitted as one strict control-plane
mutation, not as an arbitrary Python command. The host adapter requires the
installed `company-planning` cache layout and matching plugin manifest, the
ambient native session's exact healthy worktree claim, and claim ownership of
`.company-planning/active-execution.json` (plus the nested history directory
for archive). A canonical external candidate JSON is read-only input; wrong
session/worktree bindings, untrusted script locations, and shell composition
remain denied.

Git revision and ref operands are identifiers rather than paths. Read-only
queries such as `git rev-list ... origin/topic...HEAD` therefore retain only an
explicit `git -C` directory as path evidence, and `git push origin <ref>` stays
claim-bound without treating `<ref>` as a file. Pytest node selectors retain
only the file portion before `::` for claim-path evaluation.

When this control blocks valid work, loses an expected session transition, or
creates avoidable process cost, record concrete evidence in Project Meta's
canonical feedback register:

```bash
make -C /absolute/project-meta policy-friction \
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
- `session-finish` fails when a dirty handoff lane owns authority surfaces with
  unresolved reconciliation obligations; clean lanes always proceed through
  `session-close`

The v0 authority store lives beside claims:

- `~/.claude/coordination/authority_obligations/*.yaml`

Current bounded scope:

- indexed authority surfaces such as plan indexes
- `resolution_mode: manual` means the landing lane must record debt if overlap
  is forbidden
- `resolution_mode: generated` means the surface should be regenerated instead
  of carrying durable manual debt

## Canonical Checkout Lock

While any lane claim is live against a repository, that repository's canonical
checkout is made physically read-only. This is not advice and not a hook: the
tracked files and the directories containing them lose their write bits, so
every writer is blocked identically -- `Edit`/`Write`, `sed -i`, a heredoc, a
Python script, `cp`, `mv`, `git checkout`, or a compiled binary.

The reason it is permission bits rather than a gate is coverage. Every
write-governing Claude Code hook in this estate is wired to `Edit|Write` and
none to `Bash`, while agents under bypass-permissions mode are told to edit with
`sed` and heredocs. Those never reach a gate. Permission bits are not a route
that can be missed.

Locking the files alone would not have worked, and this was measured rather than
assumed: `sed -i`, `mv -f`, and `cp -f` write a new inode and rename over the
old one, which needs write permission on the **directory**, not the file. A
file-only lock lets all three through. The directory half is the part that
actually enforces.

### What still works under a lock

- Everything inside `<repo>/worktrees/<branch>/`. Lane checkouts are untouched,
  which is what makes this safe to run while other sessions are working.
- `git worktree add`, `git commit` from a lane, ref and reflog updates, and
  `git fetch`. `.git/` is never locked.
- Every read in the canonical checkout, including `git status` and `git log`.
- Python imports; CPython silently skips `__pycache__` in a read-only directory.

`git checkout`, `git pull`, and `git merge` **in the canonical checkout** fail
while a lane is live. That is the collision being prevented. The lane-close path
unlocks first, so `finish_pr.py` can still rebase the canonical checkout after a
merge.

### What triggers it

Nobody runs a command for any of this.

| Trigger | Effect |
| --- | --- |
| `create_worktree.py` succeeds | Locks the canonical checkout of the new lane's repo |
| `SessionStart` hook | Reconciles every repository: locks those with a live lane, releases locks no live lane justifies |
| `safe_worktree_remove.py` succeeds | Releases the lock if no other lane is still live |
| `PreToolUse` / `PostToolUse` hook | Prints the recovery instructions when a lock blocks a write |

Reconcile is estate-wide, not repository-local: a session start in any repo that
has the hook installed reconciles every repository with a live lane claim.

### When it blocks you

The recovery is printed at the moment of blocking, by the hook, with the exact
command. Nothing needs to be looked up. If you are reading this instead, the
command is:

```bash
python3 scripts/worktree-coordination/canonical_lock.py --reconcile
```

That releases any lock whose lane claim is gone and leaves the rest alone. To
inspect rather than change anything, use `--status <repo>`.

### Stale locks

A session that dies without closing leaves its checkout read-only. `--reconcile`
repairs that, and it runs on session start, so the repair fires on the same
event as the next attempt to use the repository: whoever the stale lock would
inconvenience is by definition starting a session, and it is cleared before
their first tool call.

### It fails closed

If the claim registry is missing, or any claim file in it will not parse,
reconcile **keeps every existing lock** and exits non-zero with the offending
file named. An empty read of a registry that cannot be trusted must never be
mistaken for "no lane is live" -- that is the fail-open defect this estate
already has elsewhere.

### Proving it

```bash
python3 scripts/worktree-coordination/canonical_lock.py --self-test            # exits 0
python3 scripts/worktree-coordination/canonical_lock.py --self-test-unlocked   # exits 5
```

The second arm runs the identical probe with no lock in place. It must report
that every write route landed; if it reported anything blocked, the probe is
measuring nothing and it says so rather than passing. Only the first arm can
ever report `boundary_verified`.

## Session Safety

Some agent runtimes keep a persistent shell working directory. In those
environments, deleting a worktree from a session whose shell CWD still points
inside that worktree breaks subsequent shell commands.

The canonical `session_close.py` control path now re-anchors its own process to
the repository root before removing the claimed worktree. This makes exact
owner closeout safe even when a native pre-write adapter has rebound the
command into that worktree. It does not change the caller's persistent shell
CWD.

Practical rule for manual or non-canonical removal:

- keep one control session anchored at the canonical repo root
- run merge / finish / non-canonical cleanup from that root-anchored session
- do not delete a worktree from a session whose shell CWD is inside it

The `block-cd-worktree.sh`, `warn-worktree-cwd.sh`, and
`enforce-make-merge.sh` hooks enforce this safety rule for Claude Code style
sessions. That safety rule does not mean worktrees are optional; it means
cleanup must happen from a safe control session.

## Atomic Closeout Rule

Claim release and claimed-worktree cleanup must not be split into separate
manual steps.

After a task branch is merged, ordinary repository writes remain denied until
the claim is dispositioned. Two strict control paths remain available through
the installed runtime: the absolute mailbox command printed in the hook notice,
and the exact `session_close.py` command whose agent, project, scope, branch,
worktree, and ambient native session resolve to one live claim. Shell-composed,
cross-session, or retargeted variants are denied.

- use `session-close` for direct CLI closeout
- use `make worktree-remove BRANCH=...` in governed repos
- `session-finish` cannot mark a clean managed lane completed or release its
  claim; generic claim release likewise refuses while the managed worktree or
  branch exists

Terminal claim history is not live coordination input. `session-close`
immediately moves the exact completed YAML into the append-only completed-claim
archive and removes it from `claims/`, so hook cost scales with current owned
work rather than the lifetime number of finished lanes.

The sanctioned closeout flow is idempotent for already-missing worktree or
branch state so partial cleanup can be rerun safely.

Native lifecycle wiring also protects unclaimed and cross-repository work. At
`SessionStart` (or the first mutation boundary), the coordination hook records
status fingerprints for the Git repositories under the session's starting
scope. At `Stop`, it rescans that same scope and blocks the final response when
the session changed a repository's status and left it dirty. This catches a
generator that writes into sibling canonical checkouts even when the agent's
current directory is not itself a Git repository. Pre-existing unchanged dirt
does not become the current session's ownership merely because it was visible
at startup. Linked `worktrees/`, dependency environments, and package caches
are excluded from the fleet scan.

The native Stop gate is not a substitute for claimed-lane closeout. Commit and
push coherent work, restore the recorded baseline, or use the sanctioned
session-close dirty-handoff path; a final prose note alone does not clear the
gate.

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

A missing task branch cannot receive the `merged` disposition: once its tip is
absent, closeout has no branch evidence to compare with the canonical default.
Restore the branch from durable evidence before merged closeout, or use an
explicit supported non-merge disposition with the required recovery reference
or discard authorization. Missing worktree and branch paths are not themselves
evidence that integration occurred.

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

`session-resume` is the one lifecycle call that may legitimately run with no
live claim: the preserved-lane check refuses a new claim and names resume as the
recovery, so a fresh runtime arrives holding nothing and the poll cannot resolve
its session. That case degrades rather than raising, because crashing there
manufactures exactly the block this rule forbids -- and it left closing the lane
as the only named route that worked, making the documented recovery circular.
The degraded notice reports `polled: false` with
`degraded_reason: no_live_claim_owns_session`, and its summary says `NOT POLLED`
rather than `no active messages`: a poll that could not run must stay
distinguishable from a poll that found an empty inbox. Every other mailbox fault
still propagates. Resuming under a degraded poll does not clear the rule above —
a live-agent decision may still be pending, so do not cross a coordination
boundary until a claim is held and polling is restored.

## What Coordination Does And Does Not Do

What it does:

- records who claimed what scope
- exposes a readable current-work registry, including derived active lanes
- lets repos block conflicting or unsafe worktree flows
- makes in-flight ownership and overlap state visible through claims and the generated active-work registry; legacy Agent Memory remains an explicit historical source
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
- `python scripts/scan_coordination_mirrors.py --workspace-root <configured-projects-root> --fail-on-copied`

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
