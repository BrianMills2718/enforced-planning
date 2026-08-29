# META-ADR-0011: Curated Learning Register and On-Demand Legacy Memory

**Status:** Accepted
**Date:** 2026-08-29
**Supersedes:** ADR-0010 sections 1–3 for forward-writing workflows

## Context

ADR-0010 made Agent Memory a required planning input and a second write path for
operational knowledge. Operational evidence later showed that this default created
duplicated storage, automatic retrieval cost, and low-signal records. The ecosystem now
has stronger purpose-specific authorities:

- `project-meta/learnings/entries/` stores immutable, reviewable reusable findings.
- `~/.claude/coordination/claims/` and the generated active-work registry store live
  ownership and overlap state.
- Repository code, plans, ADRs, and investigations remain the primary current-state
  evidence for planning.
- The existing Agent Memory database contains historical records worth preserving.

## Decision

1. The version-controlled learning/v2 register is the canonical write path for new
   reusable operational findings. Do not duplicate new findings into Agent Memory.
2. Live coordination comes from claims and the active-work registry. Agent Memory is not
   a live decision or overlap-check surface.
3. Agent Memory is a read-only legacy archive. Query it explicitly when a task has a
   concrete reason to inspect historical episodic context; do not load it automatically.
4. Current-state assessment requires direct inspection of current code, documentation,
   plans, and applicable curated learnings. A legacy recall is optional evidence, not a
   universal planning gate.
5. New plans cite the immutable learning/v2 artifact path in References Reviewed.
   Existing `agent_memory:<entry-id>` research citations remain accepted and validated
   against the preserved database so historical plans do not break.

## Consequences

- New sessions do not need a resident Agent Memory server or an automatic recall call.
- Reusable findings have one durable, auditable owner.
- Coordination reflects live claims rather than stale semantic records.
- Historical knowledge remains recoverable without forcing its cost onto every task.
- Existing plan validators and historical citations remain compatible; new templates point
  directly to the version-controlled learning artifact.

## Evidence

- `project-meta/docs/ops/ADR-2026-08-29-on-demand-tool-loading-default.md`
- `project-meta/docs/ops/MCP_ON_DEMAND_MIGRATION_2026-08-29.md`
- `project-meta/learnings/entries/`
- Preserved legacy database: `~/projects/agent_memory/data/agent_memory.db`
