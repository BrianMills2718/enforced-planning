# Plan 112: Canonical Surface Runtime Control

**Status:** Complete
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

## Completion Evidence

- Shared controller and installer: enforced-planning PRs
  [#120](https://github.com/BrianMills2718/enforced-planning/pull/120),
  [#121](https://github.com/BrianMills2718/enforced-planning/pull/121), and
  [#122](https://github.com/BrianMills2718/enforced-planning/pull/122).
- Downstream adoption: Graph Application Toolkit PR
  [#43](https://github.com/BrianMills2718/graph_application_toolkit/pull/43),
  canonical revision `0e00edb39715b77e0028bc8a7c6483fa7a299968`.
- Cross-project report-only inventory: Project Meta PR
  [#403](https://github.com/BrianMills2718/project-meta/pull/403).
- The canonical Graph Application Toolkit surface passed its exact lease and
  frontend/backend identity audit on ports 5211/8011; compiled Chrome opened
  Projects, invoked New project, and observed the Goal step without console
  issues.

## Failure Behavior

- Registry or identity ambiguity fails loud.
- Stale leases are reported and may be pruned explicitly; they are never treated
  as live ownership.
- Untracked listeners are reported but never killed automatically.
- Runtime logs remain outside Git under the selected state root.

`trace_evaluable: false # deterministic process/HTTP integration controls`
