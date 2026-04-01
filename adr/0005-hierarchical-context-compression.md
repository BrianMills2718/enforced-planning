# META-ADR-0005: Documentation Layers Are Hierarchical Context Compression

**Status:** Accepted
**Date:** 2026-02-09

## Context

AI coding assistants working on large codebases face a fundamental constraint: they can't hold the entire codebase in context. A project with 60+ source files totaling 15,000+ lines exceeds what any context window can absorb at once.

Two naive strategies both fail:
1. **Read everything** — doesn't fit, and most of it is irrelevant to the current task
2. **Read only the target file** — gives fragments without structural understanding. You can edit `executor.py` correctly only if you understand how it relates to `permission_checker.py`, `contracts.py`, `ledger.py`, and the artifact system. But you shouldn't have to read all of them.

The meta-process framework accumulated several documentation layers over time — glossary, ontology, domain models, ADRs, architecture docs, PRDs. These were initially justified as "good documentation practice." But their real value is something different.

## Decision

**Documentation layers are hierarchical compressions of the codebase.** Each layer is a lossy but useful compression of the layer below it, optimized for a different question an AI (or human) needs answered.

### The compression hierarchy

```
Zoom 0:  Code              (~15,000 lines)  "What does this line do?"
Zoom 1:  Architecture docs  (~2,000 lines)  "How does this system work?"
Zoom 2:  Ontology           (~300 lines)    "What entities exist and what fields do they have?"
Zoom 3:  Domain model       (~50 lines/domain) "How do concepts relate to each other?"
Zoom 4:  Glossary           (~30 terms)     "What does this word mean?"
Zoom 5:  Thesis             (~1 paragraph)  "Why does this project exist?"
```

Each layer answers questions that the layer below *can* answer but at much higher token cost. You don't need to read 900 lines of `artifacts.py` to know that an Artifact has an `id`, `content`, `state`, and `access_contract_id` — the ontology tells you in 20 lines. You don't need to read 5 files to understand that contracts mediate all access to artifacts — the domain model tells you in one sentence.

### ADRs are compression of rationale

ADRs compress a different axis — not structure but *decisions*. Code can tell you what exists but not why alternative approaches were rejected. ADRs are the only layer that captures information that doesn't exist anywhere in the code at all.

### The context graph routes between layers

The documentation graph (`relationships.yaml`, Pattern #09) is the routing layer. Given a file being edited, it determines which compressions to inject:

- Editing `executor.py` → inject governing ADRs (rationale), coupled docs (sync requirements), domain model concepts (structural context), relevant glossary terms (vocabulary)
- Planning a multi-file change → inject domain model (concept relationships), architecture docs (system interactions)
- New to the project → inject glossary (vocabulary), thesis (purpose)

The graph doesn't hold content — it routes to the right compression level for the current task.

### Staleness is cache invalidation

If a compression layer drifts from the code it compresses, it becomes a stale cache — actively harmful because it provides confident wrong answers. This means:

- Compression layers must be treated as caches that need invalidation
- Doc-code coupling enforcement (Pattern #10) is cache invalidation for architecture docs
- Governance sync (Pattern #08) is cache invalidation for ADR headers
- Layers without invalidation mechanisms (domain models, ontology, glossary) will drift and must be designed with maintenance in mind

### What each layer must justify

Every compression layer must provide information that:
1. Is **not efficiently available** from the layer below (otherwise it's redundant)
2. Is **consumed by something** — hooks, CI, humans, or AI context assembly
3. Has a **freshness mechanism** — automated enforcement, coupling checks, or explicit review triggers

Layers that fail these criteria should be collapsed into layers that pass them.

## Consequences

### Positive

- **Clear rationale** for why documentation layers exist — they're not bureaucracy, they're context compression for AI-scale codebases
- **Evaluation criterion** for each layer — does it compress uniquely useful information? Is it consumed? Is it fresh?
- **Design guidance** for the context graph — routing should match zoom level to task type
- **Justifies investment** in freshness mechanisms (coupling checks, governance sync) as cache invalidation infrastructure

### Negative

- **Higher bar for new layers** — adding a new documentation type must justify itself as a unique compression, not just "nice to have documentation"
- **Maintenance pressure** — treating layers as caches means stale ones should be deleted rather than ignored
- **Complexity** — the hierarchy itself is a concept that contributors must understand

### Implications for existing layers

| Layer | Unique compression? | Consumed? | Fresh? | Status |
|-------|---------------------|-----------|--------|--------|
| Thesis | Yes (purpose) | Humans | Stable (rarely changes) | Keep |
| Glossary | Yes (vocabulary) | Partially (mapped, not injected) | Manual | Keep, add injection |
| Domain model | Yes (concept relationships) | Partially (file_context edges) | Manual | Keep, add freshness |
| Ontology | Yes (entity schema) | Partially (conceptual_model edges) | Manual | Keep, add freshness |
| ADRs | Yes (rationale) | Yes (governance hooks) | Enforced (sync_governance) | Keep |
| Architecture docs | Yes (system behavior) | Yes (doc-code coupling) | Enforced (CI) | Keep |
| PRDs | Overlaps with ADRs + domain models | Partially (file_context) | Manual | Evaluate for collapse |

### Relationship to other meta-ADRs

- **META-ADR-0004** (Gate YAML Is Documentation): Same principle — don't duplicate, single source of truth
- Patterns #09 (Documentation Graph) and #27 (Conceptual Modeling) implement specific layers; this ADR provides the overarching rationale
