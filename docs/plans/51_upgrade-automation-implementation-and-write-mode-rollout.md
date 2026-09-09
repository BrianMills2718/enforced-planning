# Plan #51: Upgrade Automation Implementation and Write-Mode Rollout

**Status:** 🟡 Partial (dry-run shipped; safe claimed-worktree write mode implemented and verified against real repos 2026-09-02; an 18-repo fleet attempt the same day found 0/18 succeeding for several distinct, now-catalogued reasons, one already fixed at the source (PR #388); fleet-wide rollout not yet run)
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #20 (design)
**Blocks:** Phase 9 write-mode fleet rollout

---

## Native runtime identity repair (2026-09-09)

The first authorized Plan #134 fleet pilot proved that write mode still
hard-coded `WORKTREE_AGENT=claude-code`, including claim repair and closeout.
That made the sanctioned upgrader unusable from a native Codex session even
though the target repository remained untouched. Write mode now derives exactly
one agent from the runtime markers already governed by the coordination claim
contract, uses that identity throughout the lane lifecycle, and fails visibly
when the environment is absent or ambiguous. Focused both-sign tests cover
Codex detection and ambiguous-marker refusal; the real `prompt_eval` pilot is
the acceptance journey after this repair lands.

That pilot then reached a second compatibility boundary: older maintenance
wrappers cannot carry a multi-directory broad-scope declaration, while their
base `worktree` target is blocked by a newer qualified-plan gate. The upgrader
now uses the atomic maintenance wrapper with its universally supported `.`
bootstrap scope, then invokes `session-narrow` to reduce ownership to the exact
installer closure before `install --write`. A negative control proves a failed
narrowing attempt closes the lane without invoking the installer.

The first successful full install/audit pilot then reached a correct repo-local
doc-coupling refusal because the general installer changed unrelated workflow
helpers. Plan #134 adoption therefore uses a dedicated
`--coordination-claims-only` installer profile: the canonical claim module and
its stable CLI facade only. The profile is exact and idempotent in focused
tests, and the upgrader narrows its temporary bootstrap claim to those same two
paths before invoking it.

Same-day pilot retries also proved that date-only rollout branches collide with
intentionally retained session trackers. Rollout branch identities now include
the canonical Enforced Planning source revision. This preserves historical
trackers while making a new source revision a naturally distinct retry lane;
the upgrader fails before target mutation if that revision cannot be resolved.
Each attempt also carries a UTC suffix, so a retained tracker from a failed
attempt cannot block a retry at the same source revision. For delegating legacy
maintenance wrappers that drop broad-scope metadata, the upgrader retries the
base target only after the exact missing-mode/reason failure and supplies the
bootstrap reason plus exact target worktree itself.

One further live boundary appeared in `project-meta`: an intermediate wrapper
accepted the broad-scope fields but its base target then required a qualified
plan, so no lane was created. After that exact refusal, and only while the
target worktree is still absent, the upgrader now calls the current atomic
`maintenance_worktree` bootstrap transaction directly. That transaction keeps
the authority, native-session, fresh-remote, claim, tracker, and worktree
checks intact; `session-narrow` must still reduce the temporary `.` claim to
the two-file installer closure before any target mutation.

The same consumer also predates the `session-narrow` Make facade. When that
specific target is absent, the upgrader invokes the current stable narrowing
CLI directly against the same native-session-owned claim. This preserves the
strict-subset, target-worktree identity, conflict, projection, and receipt
checks that the newer Make target delegates to; any refusal still abandons the
lane before installer mutation.

For a legacy governed consumer with neither worktree Make target, the current
atomic transaction is the documented isolated fallback. It starts with the
final two-file installer scope rather than temporary `.` authority, so active
owners of unrelated paths remain non-blocking even when one of their old claim
records cannot prove a live worktree boundary. The same transaction still
checks repository authority, native ownership, remote freshness, claim
conflicts, tracker creation, and linked-worktree creation before returning.

---

## Implementation (2026-09-02)

`--write` now requires an explicit `--repo REPO_ID` (matching "Minimal First
Slice" below -- batch write-mode is still a later slice) and runs the exact
sequence this doc already specified: `make maintenance-worktree` (or the base
`worktree` target as a fallback for a repo whose installed Makefile predates
the convenience wrapper -- which several of the 25 currently-drifted repos
do, since that wrapper is itself part of the drift), `install_governed_repo.py
--write` and `audit_governed_repo.py --strict-governed` both run inside that
worktree, then commit + push + `gh pr create` only if there was a real diff.
Never merges. Never touches the primary checkout. A repo tagged
`owner: inside-success` in the registry is skipped with an explicit reason --
that authority is separate and must be passed explicitly with
`--authorize-owner inside-success`. PR creation also accepts an explicit,
allowlisted `--github-cli` account wrapper, keeping mutation authority distinct
from credential routing instead of relying on whichever global account happens
to be active.

Registry ids used as claim projects must match the canonical Project Graph id
for the resolved checkout, even when the GitHub repository has a different
name. The planning checkout is therefore registered as `inside-success`, which
matches both Project Graph and its repo-local `PROJECT`, rather than the remote
repository name `brians-2nd-brain-integration-work`.

On any failure the worktree is abandoned through the sanctioned
`session-close` path; uncommitted output is stashed, never discarded, so a
human can recover exactly what a sync attempt produced.

### Verification against real repos, not fixtures

Per this doc's "Verify against a REAL caller" pattern (and the hard lesson
from a same-day sibling regression, `lrn-20260902T164715155794Z-4d2c5ca668`
and `lrn-20260902T174949452389Z-53c1db6bda`): ran `--write` against five real
governed repos, not mocks.

- `osint_tools`, `qualitative_coding`, `theory-forge`: worktree creation,
  `install --write`, and `audit --strict-governed` all succeeded and correctly
  reclassified the repo (`partial` -> `governed`) once run; the commit step
  was then correctly *refused* by that repo's own local pre-commit
  doc-coupling hook, or (theory-forge) `install_governed_repo.py` itself
  refused because of a legacy `merge`/`finish` Make-target conflict it
  detected. Both are the safety design working as intended -- a repo-local
  policy blocking an automated bulk sync, not a bug in this script -- and the
  worktree was abandoned cleanly with the produced diff preserved in a stash.
- `orgchart`: reached a full commit (real diff, real content). Push was
  correctly refused by that repo's own push-check (`missing_plan_ref`) because
  its installed `maintenance-worktree` variant does not set `plan_ref` even
  with `ALLOW_UNPLANNED=1`, and `plan_ref` cannot be patched onto an existing
  claim afterward. This is the one genuine remaining gap this pass found:
  some installed Makefile variants pass "unplanned" authority differently, and
  this script does not yet detect or work around all of them.
- Found and fixed one real bug during this verification: a multi-line failure
  reason embedded in a `WORKTREE_DISPOSITION_REASON` Makefile variable broke
  Make's `"$(VAR)"` recipe-line expansion, silently preventing the
  abandoned-then-merged session-close retry from ever running and leaving
  worktrees/branches behind after every failed write attempt. Fixed by
  collapsing any multi-line reason to one line before it reaches a Makefile
  variable (`_single_line`); a regression test locks this in.

### What this does not yet cover

- Batch write-mode across many repos in one invocation (deliberately deferred,
  matching "Minimal First Slice"). Attempted manually across 18 repos on
  2026-09-02: 0 succeeded, for several distinct reasons (see below).
- `owner: inside-success` repos, which need their own explicit authorization
  before this script should touch them at all.

### `plan_ref` gap — root-caused and fixed at the source (2026-09-02)

Reproduced on a second repo, `llm_client`, during the 18-repo manual batch
attempt above. Root-caused past "some older installs have a quirk": the
session-start Makefile invocation was missing the same `ALLOW_UNPLANNED ->
--plan UNPLANNED` fallback the earlier `--claim` step already had, in both
the distributed template and this repo's own root Makefile. Fixed at the
source in `enforced-planning` PR #388 (merged,
`441a84e6248b47a9bcf3959be25d254e742a0e5b`); documented as a standing
invariant in `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`.

This closes the *cause*, not the two already-affected repos: `orgchart` and
`llm_client` both still have the old, un-fixed Makefile installed. Their next
`upgrade_governed_repos.py --write` run installs the corrected template as
part of the sync itself, so no separate repair is needed there -- but that
run hasn't happened yet.

### The 18-repo manual batch attempt (2026-09-02) — 0 of 18 succeeded

Distinct causes, not one bug: 5 repos have the already-documented broken
vendored `enforced_planning/__init__.py`; 2 (`greer`,
`graph_application_toolkit`) have no worktree/claim Makefile targets
installed; 1 (`ecosystem-ops`) has a plan-gate that refuses unplanned
maintenance work outright; 3 (`ac16`, `process_tracing`, `theory-forge`)
failed with an empty `write_error` string -- `install --write failed inside
worktree: ` with nothing after the colon, which is a bug in
`upgrade_governed_repos.py`'s own error capture, not yet fixed; 1
(`osint_tools`) got to a real commit and was correctly blocked by that
repo's own doc-code coupling pre-commit hook; 1 (`llm_client`) got to a real
commit and failed push on the `plan_ref` bug above (work preserved, then
formally abandoned as superseded once the root cause was confirmed); 3
(`ac15`, `digimon-for-kg-application`, `agent_memory`) failed with generic
tracebacks not yet individually diagnosed.

---

## Gap

**Current (as of Plan #20 completion):** The design for upgrade automation was complete, but
no implementation existed. The framework had `install_governed_repo.py` for single-repo installs
and `audit_governed_repo.py` for single-repo audits, but no script for fleet-wide operations.

**Target:** `scripts/upgrade_governed_repos.py` orchestrates install + audit across all registered
repos. Dry-run is safe and default; write-mode requires clean working trees. A 16/16 dry-run
pass is the trigger for write-mode rollout consideration.

---

## Implementation (2026-04-05)

`scripts/upgrade_governed_repos.py` was implemented and verified on 2026-04-05.

### What it does

1. Reads `governed_repos.yaml` — authoritative fleet registry
2. For each repo: verifies it exists, checks for local dirt (blocks `--write` if present)
3. Runs `install_governed_repo.py` (dry or write mode)
4. Runs `audit_governed_repo.py --json` to classify the repo
5. Emits per-repo result with classification, blockers, and exit code

### Safety model

| Condition | Behavior |
|-----------|----------|
| Repo path missing | SKIP with reason |
| Local dirt in `--write` mode | SKIP with reason |
| Missing root `CLAUDE.md` | Hard blocker; classify as `legacy`, SKIP |
| Install fails | Mark FAIL; continue other repos |
| Audit fails | Mark FAIL; report blockers |

### Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Default; never modifies files |
| `--write` | Fails closed until claimed-worktree orchestration is implemented |
| `--repo REPO_ID` | Upgrade one repo by ID |
| `--json` | Machine-readable JSON output |
| `--registry PATH` | Path to governed_repos.yaml (default: governed_repos.yaml) |

---

## Verification Results (2026-04-05)

Dry-run across 16 registered repos:

```
upgrade_governed_repos — DRY-RUN mode — 16 repo(s)
Result: 16 ok, 0 skipped, 0 failed of 16 total
```

All 16 repos passed dry-run with correct classification and no unexpected blockers.

---

## Acceptance Criteria

- [x] `scripts/upgrade_governed_repos.py` exists and is executable
- [x] Reads `governed_repos.yaml` without error (handles both `id`/`path` and `repo_id`/`repo_root` key formats)
- [x] `--dry-run` is the default; never modifies files
- [x] `--write` mode blocks if local dirt detected
- [x] Missing root `CLAUDE.md` is a hard blocker, repo classified as `legacy`
- [x] Per-repo results include classification and blockers
- [x] `--json` flag produces machine-readable output
- [x] 16/16 governed repos pass dry-run
- [ ] Write-mode rollout executed and verified — **deferred to Mac mini pilot** (Phase 9 trigger)

---

## Write-Mode Rollout (Phase 9 — Deferred)

Write-mode rollout is **not yet executed**. On 2026-08-03, audit confirmed the
implemented command wrote the full installer directly into primary checkouts
without claims, linked worktrees, commits, publication receipts, or sanctioned
closeout. `--write` now fails closed. The trigger is no longer only the Mac mini
pilot: the CLI must first implement the accepted worktree sequence in the design.

Rollout sequence when re-enabled:

1. Run `python scripts/upgrade_governed_repos.py --registry governed_repos.yaml --write --repo <one repo>` on a low-risk repo first
2. Verify audit passes and no unexpected mutations
3. Roll out repo-by-repo for the remaining 15 repos
4. Operators must manually approve each write if the repo has any active worktrees or claims

**Gate for automated rollout:** Mac mini pilot results show the dry-run pipeline running
unattended without producing false positives.

---

## References

- Design: `docs/designs/GOVERNED_REPO_UPGRADE_AUTOMATION.md`
- Predecessor: `docs/plans/20_governed-repo-upgrade-automation.md` (design-only)
- Registry: `governed_repos.yaml`
- Primitives: `scripts/install_governed_repo.py`, `scripts/audit_governed_repo.py`
