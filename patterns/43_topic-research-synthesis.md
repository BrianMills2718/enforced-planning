# Pattern: Topic Research Synthesis

## Problem

Investigation artifacts are often high-value in the moment but disappear as
reusable inputs:

- an agent researches a topic, makes a decision, and the reasoning lives only
  in chat or a one-off memo
- future ADRs repeat the same search because there is no durable topic surface
- plans cite local code/docs but do not show whether prior research was reused
- external research goes stale with no explicit refresh trigger

Result: research exists, but it does not compound.

## Solution

Separate two evidence artifacts:

1. **Investigation memo** — dated, question-driven, usually immutable
2. **Topic research synthesis** — living, reusable, and linked to freshness
   triggers

The synthesis is the durable start surface for a topic. It points to:

- related investigations
- related ADRs
- related capabilities or boundary docs
- external sources worth keeping
- open research questions
- freshness triggers

## Files

| File | Purpose |
|------|---------|
| `investigations/<scope>/YYYY-MM-DD-slug.md` | Dated memo answering one question |
| `research/<topic>/INDEX.md` or equivalent | Human-readable topic entrypoint |
| `research/<topic>/topic_manifest.yaml` *(optional but recommended)* | Lightweight machine-readable topic metadata |
| `research/<topic>/SYNTHESIS*.md` | Living topic synthesis |
| `research/<topic>/CLAUDE.md` *(optional)* | Directory-specific retrieval guidance |

The location may vary by repo or ecosystem. What matters is the role split,
not the exact path.

## Setup

### 1. Decide the topic scope

Group by retrieval question, not by where the research happened.

Good topic examples:
- `agent_memory`
- `tool_design`
- `orchestration`
- `structured_output`

Bad topic examples:
- `misc`
- `week_14_notes`
- `random_links`

### 2. Write investigation memos when answering concrete questions

Use a dated memo when the task is:
- compare frameworks
- assess a design direction
- explain why a decision changed
- evaluate a production pattern

### 3. Promote durable conclusions into topic synthesis

When an investigation contains conclusions that future work should reuse, copy
the conclusion layer into the topic synthesis and link back to the memo.

### 4. Add topic metadata

Recommended fields for a `topic_manifest.yaml`:

```yaml
topic: orchestration
status: active
last_reviewed: 2026-04-04
freshness_sla_days: 30
refresh_triggers:
  - new ADR on orchestration
  - major vendor framework release
  - runtime benchmark regression
related_investigations:
  - investigations/cross-project/2026-04-04-example.md
related_adrs:
  - docs/adr/0008-example.md
related_capabilities:
  - orchestrator.dispatch
```

## Usage

### When writing an ADR

The ADR `Research Basis` should prefer:

1. relevant investigation memo
2. relevant topic synthesis
3. external source or production source
4. explicit research skip statement

ADR research linkage is a strict doctrine: significant ADRs should either cite
their evidence chain or say explicitly why research was skipped.

### When writing a plan

Use:

- `References Reviewed` for repo-local code/docs you examined before planning
- `Research Basis For This Slice` for prior investigations, topic syntheses,
  external sources, or explicit research skip

This section should be treated as:

- strict for design, cross-project, or externally informed work
- recommended for trivial local work where repo-local references are sufficient

### When refreshing a topic

Refresh the synthesis when:

- a new investigation materially changes the conclusion
- a new ADR depends on the topic
- runtime evidence contradicts the current recommendation
- the freshness SLA or trigger is hit

Freshness metadata should start as advisory rather than blocking. The point is
to create reusable refresh triggers before attempting semantic enforcement.

## Recommended Sections for a Topic Synthesis

```markdown
# Topic: [Name]

## Current Recommendation
[What the ecosystem should currently do]

## Why
[Short rationale]

## Key Sources
- investigation memo(s)
- topic-local supporting notes
- external references

## Related ADRs
- ADR-XXXX

## Related Capabilities / Boundaries
- capability or boundary docs

## Open Questions
- what still needs research

## Freshness
- last reviewed
- triggers for refresh
```

## Limitations

- **Not a substitute for investigation** — syntheses summarize; they do not
  replace dated evidence
- **Can drift** — living syntheses need explicit refresh triggers
- **Not every topic needs one** — trivial local choices do not need a topic
  library entry

## See Also

- [Question-Driven Planning](28_question-driven-planning.md)
- [Gap Analysis](30_gap-analysis.md)
- [Planning Hierarchy](42_planning-hierarchy.md)
- [ADR](07_adr.md)
