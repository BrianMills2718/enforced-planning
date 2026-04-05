# Enforced Planning Architecture Decision Records

ADRs for the enforced-planning patterns themselves, not the agent ecology system.

## Why Enforced Planning ADRs?

The enforced-planning documentation defines reusable development patterns for AI-assisted projects. Like any architecture, these patterns involve decisions with tradeoffs that should be documented.

Without ADRs:
- Decisions get lost or forgotten
- Rationale isn't preserved
- Changes happen without clear reasoning
- New contributors don't understand why things are the way they are

## Scope

These ADRs cover decisions about:
- Terminology choices for the enforced-planning framework
- Process structure and hierarchy
- Enforcement mechanisms
- Documentation organization

They do NOT cover:
- Agent ecology system architecture (those are in `docs/adr/`)
- Implementation details of specific patterns

## ADR Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-acceptance-gate-terminology.md) | Acceptance Gate Terminology | Accepted |
| [0002](0002-thin-slice-enforcement.md) | Thin-Slice Enforcement | Accepted |
| [0003](0003-plan-gate-hierarchy.md) | Plan-Gate Hierarchy | Accepted |
| [0004](0004-gate-yaml-is-documentation.md) | Gate YAML Is Documentation | Accepted |
| [0005](0005-hierarchical-context-compression.md) | Documentation Layers Are Hierarchical Context Compression | Accepted |
| [0006](0006-path-portability-first.md) | Path Portability First for Autonomous Tooling | Proposed |
| [0007](0007-autonomous-workspace-portability-enforcement.md) | Autonomous Workspace Portability Enforcement | Proposed |
| [0008](0008-adr-research-linkage.md) | ADRs Must Link to the Research That Informed Them | Accepted |
| [0009](0009-doc-authority-governance-and-enforcement.md) | Governed Repos Must Declare Documentation Authority and Enforce It | Proposed |
| [0010](0010-agent-memory-as-planning-input.md) | Agent Operational Memory Is a Required Planning Input | Accepted |

## Format

Enforced-planning ADRs follow this format (see ADR-0008 for the Research Basis requirement):

```markdown
# META-ADR-NNNN: Title

**Status:** Proposed | Accepted | Deprecated | Superseded
**Date:** YYYY-MM-DD

## Context
What is the issue that we're seeing that is motivating this decision?

## Decision
What is the change that we're proposing and/or doing?

## Consequences
What becomes easier or more difficult to do because of this change?

## Research Basis

| Source | Relevance |
|--------|-----------|
| [Name](url-or-path) | What this contributed to the decision |
```

**The `Research Basis` section is required** (ADR-0008). If there is genuinely no research
basis, write: `No external research — terminology/convention decision only.`

## Portability

These ADRs travel with the enforced-planning patterns. When adopting the patterns for another project, the ADRs explain the reasoning behind process decisions.
