# META-ADR-0008: ADRs Must Link to the Research That Informed Them

**Status:** Accepted
**Date:** 2026-04-04

## Context

A decision without traceable reasoning is a liability. When a future agent or developer
encounters an ADR, they need to be able to answer two questions:

1. **Why was this decided?** (the immediate rationale — already in the Decision section)
2. **What was looked at before deciding?** (the evidence base — currently missing)

Without the second question answered, the ADR is self-referential. It says "we decided X
because X was the right choice," but nothing tells the reader whether alternatives were
considered, what external evidence exists, or where the investigation lived.

This gap surfaces most acutely when:
- An ADR formalizes a pattern extracted from production code (e.g., circuit breakers from
  `static_pipeline`) — the source of the pattern is undocumented
- An ADR responds to external research (e.g., Anthropic's agent taxonomy, a benchmark paper)
  — the research is not linked
- A decision needs revisiting months later — the original context is lost because it lived
  only in a conversation or agent session

The `agentic_scaffolding` ADR-0001 (evaluator-optimizer loop, 2026-04-04) demonstrated the
correct pattern: a `## Research Basis` section with a table of sources, each annotated with
why it's relevant. This should be the standard, not a one-off.

## Decision

All ADRs — in enforced-planning and in any governed project repo — must include a
`## Research Basis` section immediately before or after `## Consequences`.

**Required table format:**

```markdown
## Research Basis

| Source | Relevance |
|--------|-----------|
| [Name (date)](url-or-path) | One sentence: what this source contributed to the decision |
| `path/to/investigation.md` | One sentence: what this investigation found |
| Production source: `project/src/file.py` | One sentence: what production pattern was formalized |
```

**Rules:**

- Every ADR must have the section. If there is genuinely no research basis (pure terminology
  choice, no alternatives considered), write: `No external research — terminology/convention
  decision only.`
- Investigations that triggered the ADR are the highest-value entries. Link the file path.
- External sources (papers, framework docs, articles) get URLs.
- Production source files get repo-relative paths when the ADR formalizes a pattern extracted
  from existing code.
- Relevance must be one sentence. Do not summarize the source — say what it contributed.

**This ADR is retroactively applied to all future ADRs. Existing ADRs in enforced-planning
(0001–0007) are grandfathered; they predate this convention.**

## Consequences

### Positive

- **Decisions are auditable**: future agents can trace why a decision was made and whether
  its premises still hold
- **Investigations become assets**: linking ADRs to investigations incentivizes writing them
  and makes them discoverable
- **Re-evaluation is possible**: if an external source is later superseded (e.g., a framework
  adds native support for something we built ourselves), the ADR flags where to look
- **Cross-project consistency**: the same format in every repo means agents know where to
  find the evidence base regardless of which project they're in

### Negative

- **Slight friction**: writing the table requires knowing the sources at ADR-writing time.
  If the ADR is written long after the investigation, sources may be hard to reconstruct.
  Mitigation: write the ADR immediately after or during the investigation, not weeks later.

### Neutral

- Does not change the Decision or Consequences sections — only adds a new required section.
- Existing ADRs (0001–0007) are not retroactively updated; the convention applies from 0008
  onward in enforced-planning and from the first ADR in any repo that adopts this format.

## Research Basis

| Source | Relevance |
|--------|-----------|
| `agentic_scaffolding/docs/adr/0001-evaluator-optimizer-loop-as-shared-infrastructure.md` | Demonstrated the Research Basis pattern in practice — the model this ADR formalizes |
| `investigations/cross-project/2026-04-04-evaluator-optimizer-pattern.md` | Showed that a decision (evaluator-optimizer as shared infra) whose investigation lived only in a conversation would have been unretrievable; prompted this formalization |
