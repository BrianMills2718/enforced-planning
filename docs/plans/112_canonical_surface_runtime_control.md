# Plan 112: Canonical Surface Runtime Control

**Status:** In Progress
**Type:** implementation
**Priority:** High
**phase_ref:** "Governed repository operations"
**goal_ref:** "reliable-agentic-engineering-control-plane"
**Blocked By:** None
**Blocks:** Graph Application Toolkit canonical-runtime adoption

## Gap

Governed repositories can declare a canonical UI in `ui/registry.yaml`, but the
portable framework does not bind that declaration to the process, Git revision,
ports, or worktree actually serving it. Healthy stale previews can therefore be
mistaken for the current UI.

## Outcome

Provide a portable, installed controller that:

- starts a canonical or preview surface from its repository registry;
- reserves canonical ports for the canonical integration lineage;
- records an exact process/start-time/worktree/revision lease;
- verifies a runtime identity endpoint before reporting readiness;
- reports stale, mismatched, and duplicate runtime state;
- stops only the process represented by an exact lease; and
- prevents sanctioned worktree closeout while that worktree owns a live lease.

## Files Affected

- `enforced_planning/surface_runtime.py`
- `scripts/surface_runtime.py`
- `scripts/install_governed_repo.py`
- `enforced_planning/session_lifecycle.py`
- `templates/Makefile.worktree.block.template`
- `Makefile`
- focused tests and operator documentation

## Acceptance Criteria

1. A canonical launch from the wrong branch, a dirty checkout, or an occupied
   canonical port fails before starting a process.
2. A successful launch writes an atomic lease containing exact repository,
   revision, PID, process-start identity, mode, command, ports, and URLs.
3. Readiness requires the served identity to match surface ID, mode, and source
   revision; a liveness-only or stale identity fails and is cleaned up.
4. Preview launches cannot claim canonical ports and receive independent leases.
5. Stop validates PID start identity before signaling the process group.
6. Session closeout refuses to remove a worktree with a live surface lease.
7. The governed-repo installer includes the module, CLI, and Make entrypoints.
8. Graph Application Toolkit consumes this exact installed path in a follow-on
   repository-owned adoption increment.

## Failure Behavior

- Registry or identity ambiguity fails loud.
- Stale leases are reported and may be pruned explicitly; they are never treated
  as live ownership.
- Untracked listeners are reported but never killed automatically.
- Runtime logs remain outside Git under the selected state root.

`trace_evaluable: false # deterministic process/HTTP integration controls`
