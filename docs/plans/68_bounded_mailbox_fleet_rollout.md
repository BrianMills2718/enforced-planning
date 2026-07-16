# Plan #68: Bounded Mailbox Fleet Rollout

**Status:** In Progress
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9 — fleet adoption and framework maintenance"
**goal_ref:** "autonomous-agent-control-plane"
**adrs_referenced:** []
**research_citations:** []
**Blocked By:** Plan #67 complete
**Blocks:** target-repo mailbox adoption without unrelated governance drift

## Objective

Add and exercise a `--coordination-messages-only` governed-repo installer mode
that deploys Plan 67's canonical mailbox, lifecycle adapters, and Claude hook
without refreshing unrelated policy, relationship, Makefile, or generated-agent
surfaces.

## Gap

Plan 67 added mailbox files to the full and worktree installer profiles, but a
target dry-run proposed 45–63 total changes. There was no way to adopt only the
mailbox seam without refreshing unrelated governance. The target state is an
explicit allowlisted profile supporting both local-package and upstream-
bootstrap consumers while rejecting repos with neither substrate.

## References reviewed

- `docs/plans/67_cross_client_mailbox_and_acknowledgement.md`
- `scripts/install_governed_repo.py`
- `enforced_planning/hook_wiring.py`
- `tests/test_install_governed_repo.py`
- Project Meta `scripts/_upstream_enforced_planning.py` and session wrappers
- OntoCanon local `enforced_planning/` and session wrappers
- DIGIMON governed-repo root and missing session-package/bootstrap boundary

## Boundaries

- The profile may sync only the mailbox core, shared lifecycle module, thin
  source/installed wrappers, one Claude notifier hook, and its settings entry.
- Existing claim/session dependencies are prerequisites; missing dependencies
  block rather than silently expanding into a full installer run.
- Target-repo rollout must use separate reviewed branches when another agent is
  active. It does not modify feature code or authorize message-driven work.
- Current unmanaged Codex sessions cannot be interrupted; adoption affects new
  lifecycle calls and Claude read boundaries.

## Acceptance criteria

| ID | Criterion | Evidence | Grade |
|---|---|---|---|
| C68-1 | Dry-run changes only the declared mailbox allowlist. | both-sign fixture test | A — exact local/upstream allowlist tests |
| C68-2 | Write mode installs runnable wrappers and the exact hook/settings entry idempotently. | clean install + repeat test | A — both deployment profiles run and repeat cleanly |
| C68-3 | A target missing the existing session substrate fails before mutation. | negative test | A — no-local/no-bootstrap target rejects before writes |
| C68-4 | Project Meta, OntoCanon, and DIGIMON dry-runs show bounded mailbox-only changes, with rollout staged outside active feature lanes. | target dry-run evidence | B — Project Meta 9 changes/no blocker; OntoCanon 13/no blocker; DIGIMON 9 planned changes plus explicit missing-substrate blocker |

## Failure modes and recovery

| Failure | Response |
|---|---|
| Profile proposes an unrelated path | Fail the allowlist test; do not roll out. |
| Target lacks Pydantic/PyYAML or session substrate | Block with the exact missing prerequisite. |
| Target has active overlapping governance work | Stage a separate plan/PR or defer; do not edit the active lane. |
| Hook settings cannot be parsed | Fail before writing any file. |

## Files affected

- `scripts/install_governed_repo.py`
- `enforced_planning/hook_wiring.py`
- `enforced_planning/coordination_messages.py`
- `scripts/meta/coordination_messages.py`
- `tests/test_install_governed_repo.py`
- `tests/test_coordination_messages.py`
- this plan and the plan index

## Verification-gap correction

The first Project Meta rollout exposed a partial-scope/environment-mismatch
gap: the installer tests executed the installed inbox wrapper under the
upstream-bootstrap profile, but did not execute the installed message CLI under
that same profile. The source meta wrapper still assumed a vendored local
package and failed on the real target. The fix makes the meta wrapper delegate
to the shared source CLI and executes both advertised installed CLIs under both
supported deployment profiles. The canonical Project Meta verification-gap log
was already exclusively claimed by other sessions, so this entry is retained
here as the required pending handoff rather than colliding with that log.

The first OntoCanon rollout then exposed a second target-profile gap: its
vendored claim registry still uses the canonical-directory-only
`check_claims(project)` signature. The mailbox now detects that explicit
capability, permits it only for the canonical claims directory, and fails loud
if a caller requests a custom directory that the installed registry cannot
honor. A compatibility test covers the older signature without silently
ignoring caller configuration.

## Next action

Land the verified framework profile, then open isolated Project Meta and
OntoCanon rollout branches. Keep DIGIMON blocked until its owning agent chooses
local-package or upstream-bootstrap governance adoption.
