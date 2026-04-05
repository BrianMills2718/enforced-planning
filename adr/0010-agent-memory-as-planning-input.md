# META-ADR-0010: Agent Operational Memory Is a Required Planning Input

**Status:** Accepted
**Date:** 2026-04-05

## Context

The planning operating model (`PLANNING_OPERATING_MODEL.md`) defines a partial-order
dependency graph for planning artifacts: North Star → Investigations → Topic Syntheses →
Current-State Assessment → Gap Analysis → Capabilities → Roadmap → Plan → Code.

Notably absent: any mechanism for agents to consult what they (or other agents) already
learned in prior sessions before writing a plan. Without this, the planning model assumes
investigations and topic syntheses are the only prior knowledge — but the ecosystem also
has:

- `agent_memory`: a structured operational memory store (SemanticMemory, ProceduralMemory,
  EpisodicMemory) with embeddings, provenance, bi-temporal validity, and cross-agent sharing.
  MCP-accessible. 570 records as of 2026-04-05.
- KNOWLEDGE.md files: flat append-only log of per-project findings. Historically the
  primary write target, but now frozen (M3 complete 2026-04-02). Existing entries were
  imported to agent_memory.

The ecosystem also has two knowledge systems that served overlapping purposes and were
never formally unified:

1. KNOWLEDGE.md — append-only markdown, per-project, human and agent-readable, used for
   operational findings AND active coordination signals (`## Active Decisions`).
2. agent_memory — structured store implementing `agent_ops:SemanticMemory`,
   `agent_ops:ProceduralMemory`, `agent_ops:EpisodicMemory` (from the agent_ops_minimal
   vocabulary pack in onto-canon6).

The agent_ops vocabulary (`onto-canon6/ontology_packs/agent_ops_minimal/0.1.0/`) already
types the relevant entities: SemanticMemory explicitly "Replaces KNOWLEDGE.md entries";
DecisionRecord types what `## Active Decisions` was doing; ScopeClaim is already
implemented as coordination claims YAML.

Investigation `2026-04-05-knowledge-md-vs-agent-memory-state.md` confirmed: KNOWLEDGE.md
files are still being written to daily because root CLAUDE.md still instructs agents to
append to them. The freeze announced in MEMORY_LAYER.md did not take effect because
operational guidance was never updated.

## Decision

### 1. agent_memory is the single source of truth for operational knowledge

All operational findings (bug patterns, schema gotchas, workarounds, performance
findings, architectural discoveries) go through `store_finding()` via the `/learned`
skill. The write path is `agent_memory`. KNOWLEDGE.md is frozen; existing files are
historical archives.

**Rationale**: Two diverging systems for the same purpose produces the "agents repeat
mistakes" failure mode described in `01_NORTH_STAR.md`. agent_memory fixes the structural
problems of KNOWLEDGE.md (not queryable, no provenance, no expiry, no cross-agent
sharing model) while the agent_ops vocabulary provides the typed model.

### 2. Memory recall is a required step in the planning flow

Before writing a plan, agents must call `agent-memory recall '{topic}' --project
{project}` (or equivalent MCP tool call). This sits inside the Current-State Assessment
step of the planning hierarchy — it is not a new artifact type, but a required activity
within current-state assessment.

Placement in dependency graph:
```
Current-State Assessment
  ├── Read CLAUDE.md, existing plans, relationships.yaml
  ├── Read KNOWLEDGE.md (historical, if present — legacy read)
  └── recall() from agent_memory for prior session findings  ← NEW REQUIRED STEP
      ↓
Gap Analysis
```

For the plan template, this is expressed as an additional item in `## References
Reviewed`: agents must include `agent-memory recall "{topic}"` output summary alongside
code and doc references.

**Strict for**: cross-project plans, plans involving shared infrastructure, plans where
prior session data is likely to exist (≥ 1 prior session on this project in agent_memory).
**Recommended for**: new projects with no prior memory.

### 3. Active in-flight decisions use coordination claims, not KNOWLEDGE.md

The `## Active Decisions` section in KNOWLEDGE.md is deprecated. In-flight architectural
decisions are stored as SemanticMemory records in agent_memory with `category="decision"`
and `tags=["in-flight"]`, and a short TTL (default 48h). Scope claims (who is writing
where) continue to live in `~/.claude/coordination/claims/` as they do today.

This is consistent with the agent_ops vocabulary: `agent_ops:DecisionRecord` "seeds
episodic and procedural memory formation" — it belongs in the memory store, not a
markdown coordination file. `agent_ops:ScopeClaim` is already implemented as claims YAML.

**Known gap**: `store_decision()` does not yet exist in agent_memory. Until it is added,
decisions are stored as SemanticMemory with `category="decision"` tag. Plan to add
`store_decision()` is tracked in agent_memory backlog.

### 4. agent_ops vocabulary is the semantic model

The `agent_ops:` namespace (from `onto-canon6/ontology_packs/agent_ops_minimal/0.1.0/`)
defines the types for all operational memory. enforced-planning does not invent parallel
terminology. When this ADR or its implementing plans refer to memory records, they use
agent_ops type names.

## Consequences

**What becomes easier:**
- Agents don't repeat mistakes or rediscover known workarounds — prior session findings
  are recalled before planning
- One write path (`store_finding()` / `/learned`) instead of two diverging systems
- Active decisions are queryable alongside other memory (no separate file to check)
- Cross-agent learning works: Codex findings are visible to Claude Code via shared
  agent_memory

**What becomes harder or requires follow-up:**
- KNOWLEDGE.md files must be marked as frozen (already done in MEMORY_LAYER.md;
  root CLAUDE.md must be updated — see Plan A)
- Agents working in repos without agent_memory MCP available need a fallback (read
  historical KNOWLEDGE.md if present; write via CLI fallback)
- `store_decision()` needs to be implemented in agent_memory to fully supersede the
  `## Active Decisions` markdown pattern
- governed_repo_audit.py should check for KNOWLEDGE.md presence as a historical signal
  (does this repo have knowledge to import?) but not as a required live artifact

## Research Basis

- Investigation: `project-meta/investigations/cross-project/2026-04-05-knowledge-md-vs-agent-memory-state.md`
- Architecture spec: `project-meta/vision/components/MEMORY_LAYER.md` (M3 complete)
- Vocabulary spec: `project-meta/vision/components/AGENT_OPS_VOCABULARY_SPEC.md`
- North Star failure modes: `project-meta/vision/01_NORTH_STAR.md` ("agents repeat mistakes")
- Capability PRD: `project-meta/investigations/cross-project/2026-04-05-agentic-environment-capability-prd.md`
