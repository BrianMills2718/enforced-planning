# Design: relationships.yaml V2 — Inference + Agent Validation + Enforcement

**Status:** Design draft
**Author:** claude-code (with Brian's direction on cognitive economics)
**Date:** 2026-04-02
**Depends on:** PLANNING_OPERATING_MODEL.md, STATIC_GRAPH_AND_RUNTIME_TRUTH.md

## Problem

The current `relationships.yaml` requires manually declaring every doc-to-code
coupling. This produces two failure modes:

1. **False positives** — manually declared couplings that no longer matter
2. **Missed dependencies** — real semantic relationships that nobody declared

The current enforcement model also uses "soft" (warn) couplings, which are
ineffective in an agentic ecosystem. Agents don't browse warnings.

## Design Principles

### Three-Actor Cognitive Economics

Every system in this ecosystem has three kinds of actors with different
strengths:

| Actor | Good at | Bad at | Role in governance |
|-------|---------|--------|--------------------|
| **Programmatic code** | Exhaustive scanning, deterministic checks, speed | Judgment, ambiguity, semantic understanding | Coverage: find all links, all references, all structural dependencies |
| **LLM/agents** | Contextual judgment, semantic understanding, exploration, writing fixes | Completeness guarantees, cost at scale | Judgment: decide if a coupling is *actually* stale, author fixes |
| **Humans** | Long-term vision, taste, priorities | Routine checks, repetitive validation | Direction: set policy, review agent escalations, make architectural decisions |

The governance system must play to each actor's strengths:
- Programmatic for **coverage** (find all couplings)
- Agents for **judgment** (verify and fix)
- Humans for **direction** (set policy, review escalations)

### No "Shoulds"

Every validation outcome must have a concrete agent-executable action:
- **Fix it** — agent resolves automatically
- **Escalate it** — agent creates a task for human review
- **Block it** — system prevents the commit/merge

"Warn and hope someone reads it" is not a valid action.

## Proposed Architecture

### Layer 1: Dependency Inference (Programmatic)

Automatically detect dependencies by scanning:

1. **Markdown links** — `[text](../vision/FRAMEWORK.md)` creates a coupling
2. **File path references** — any `vision/FRAMEWORK.md` string in code or docs
3. **Import statements** — `from llm_client import ...` creates a cross-project coupling
4. **Plan references** — `Plan #N`, `#N`, `ADR-N` create plan-to-plan or plan-to-ADR couplings
5. **Config references** — YAML/JSON files referencing other files by path

Output: an inferred dependency graph, updated on every commit.

Inline suppression: `<!-- governance: no-dep -->` or `# governance: no-dep` to
suppress a specific inferred link.

### Layer 2: Manual Declarations (relationships.yaml)

`relationships.yaml` becomes the **override and policy layer**, not the
exhaustive declaration:

```yaml
version: 2

# Override inferred dependencies
overrides:
  "docs/plans/28_multi-brain.md":
    suppress:
      - "vision/archive/*"              # link exists but is historical
    add:
      - "vision/MULTI_BRAIN_V0.md"      # referenced by concept, not link

# Coupling types — replaces soft: true
coupling_types:
  generated:
    action: regenerate                   # run regenerate_cmd automatically
    actor: programmatic
  validated:
    action: agent_verify                 # agent checks if actually stale, fixes or escalates
    actor: agent
  locked:
    action: block                        # commit blocked until coupling satisfied
    actor: programmatic

# Couplings with explicit types
couplings:
  - sources: ["patterns/15_plan-workflow.md"]
    docs: ["PLANNING_OPERATING_MODEL.md"]
    type: locked                         # these MUST stay aligned

  - sources: ["generated/agent_docs/**/*.md"]
    docs: ["CLAUDE.md"]
    type: generated
    regenerate_cmd: "python scripts/check_agent_docs_sync.py --check"

  - sources: ["vision/FRAMEWORK.md"]
    docs: ["vision/ECOSYSTEM_STATUS.md"]
    type: validated                      # agent checks if status is still accurate
```

### Layer 3: Agent Verification (LLM/Agent)

When a `validated` coupling fires:

1. Agent reads the changed source file (the diff)
2. Agent reads the coupled doc
3. Agent judges: "Is this doc still accurate given the source change?"
4. If stale: agent either fixes the doc or creates a bounded task
5. If fine: agent marks the coupling as verified for this commit

Implementation: Codex SDK or Claude Code agent SDK task with a bounded mission.
Runs in the daily pipeline or as a post-commit hook, not blocking every commit.

### Plan Dependencies

Plan-to-plan dependencies use a structured format in the template:

```markdown
**Blocked By:**
- #137 — must demonstrate the problem first
- llm_client#17 — API must ship first
- [future] improved benchmark infrastructure

**Blocks:**
- #138
- [future] DIGIMON production reliability
```

Format rules:
- `#N` — plan reference within same project (resolved by checker)
- `project#N` — cross-project plan reference
- `— description` — optional condition (human-readable, not parsed for enforcement)
- `[future]` prefix — conceptual/aspirational, not a real plan reference

The checker validates that `#N` and `project#N` references resolve. `[future]`
entries are tracked as conceptual blocks (metadata, not violations).

## Coupling Types (replacing hard/soft/generated)

| Type | When it fires | What happens | Who acts |
|------|--------------|--------------|----------|
| `locked` | Source changes in same commit | Commit blocked until coupled doc also updated | Programmatic (pre-commit hook) |
| `generated` | Source changes | Regeneration command runs automatically | Programmatic (script) |
| `validated` | Source changes | Agent verifies doc is still accurate; fixes or escalates | Agent (Codex/Claude Code SDK) |

No "soft" tier. Everything has a concrete action with a concrete actor.

## Stolen Patterns (credit where due)

| Source | Pattern | How we use it |
|--------|---------|---------------|
| **Pants** | Dependency inference from imports + override syntax | Layer 1 inference + `overrides:` section |
| **Pants** | `# pants: no-infer-dep` inline suppression | `# governance: no-dep` inline suppression |
| **Nx** | `dependsOn` for task pipelines | Plan dependency format (`#N`, `project#N`) |
| **Bazel** | Three dependency types (srcs/deps/data) | Three coupling types (locked/generated/validated) |
| **Bazel** | Visibility grammar | Deferred — useful when cross-repo governance scales |
| **Renovate** | Regex patterns for detecting references | Plan reference detection (`Plan #N`, `ADR-N`) |

## What This Replaces

| Current | Proposed |
|---------|----------|
| Manual coupling declarations only | Inference + manual overrides |
| `soft: true` (warn) | `type: validated` (agent verifies) |
| `verify_sync` command | `type: generated` with `regenerate_cmd` |
| No coupling type (implicit hard) | `type: locked` (explicit) |
| Free-text `blocked_by` | Structured `#N` / `project#N` / `[future]` |
| checker guesses if reference is real | Format rules make it unambiguous |

## Migration

1. Existing `relationships.yaml` files keep working (version 1 format)
2. New repos adopt version 2 format
3. One-time migration script converts version 1 → version 2 (preserving
   existing couplings, adding `type:` fields)
4. Inference engine runs alongside manual declarations — doesn't replace them
   until coverage is validated

## Non-Goals

- This design does not define the inference engine implementation (that's a
  separate plan)
- This design does not define the agent verification protocol (bounded mission
  spec is a separate plan)
- This design does not change runtime coordination state (that's covered by
  STATIC_GRAPH_AND_RUNTIME_TRUTH.md)

## Open Questions

- Should `validated` couplings block merges if the agent can't verify in time,
  or should they create async tasks? Recommendation: async tasks with a
  staleness SLA.
- Should inference run on every commit or as a periodic batch? Recommendation:
  periodic batch (daily) with the override layer checked on every commit.
- Where does the inferred graph persist? Recommendation: generated JSON file,
  git-tracked, regenerated by inference engine.
