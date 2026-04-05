# Enforced-Planning Pattern Catalog

Reusable development-process patterns for AI-assisted software development.

This file is the pattern catalog, not the onboarding guide.

- Start with [README.md](../README.md) for the framework-source overview
- Start with [GETTING_STARTED.md](../GETTING_STARTED.md) for a first successful
  governed-repo adoption path

## How To Read This Catalog

- **Core patterns** support the normal branch-based workflow
- **Worktree coordination** is an opt-in module for multiple concurrent agents
- **Requires** shows pattern dependencies, not installation order

## Core Patterns

| Pattern | Problem Solved | Complexity | Requires |
|---------|----------------|------------|----------|
| [CLAUDE.md Authoring](02_claude-md-authoring.md) | AI assistants lack project context | Low | — |
| [Testing Strategy](03_testing-strategy.md) | Inconsistent test approaches | Low | — |
| [Mocking Policy](04_mocking-policy.md) | When to mock, when not to | Low | — |
| [Mock Enforcement](05_mock-enforcement.md) | Green CI, broken production | Low | 04 |
| [Git Hooks](06_git-hooks.md) | CI failures caught late | Low | — |
| [ADR](07_adr.md) | Architectural decisions get lost | Medium | — |
| [ADR Governance](08_adr-governance.md) | ADRs not linked to code | Medium | 07 |
| [Documentation Graph](09_documentation-graph.md) | Can't trace decisions → code | Medium | 07, 10 |
| [Doc-Code Coupling](10_doc-code-coupling.md) | Docs drift from code | Medium | — |
| [Terminology](11_terminology.md) | Inconsistent terms | Low | — |
| [Structured Logging](12_structured-logging.md) *(proposed)* | Unreadable logs | Low | — |
| [Acceptance-Gate-Driven Development](13_acceptance-gate-driven-development.md) | AI drift, cheating, big bang integration | High | 07 |
| [Acceptance Gate Linkage](14_acceptance-gate-linkage.md) | Sparse file-to-constraint mappings | Medium | 13 |
| [Plan Workflow](15_plan-workflow.md) | Untracked work, scope creep | Medium | — |
| [Plan Blocker Enforcement](16_plan-blocker-enforcement.md) | Blocked plans started anyway | Medium | 15 |
| [Verification Enforcement](17_verification-enforcement.md) | Untested "complete" work | Medium | 15 |
| [Human Review Pattern](22_human-review-pattern.md) | Risky changes merged without review | Medium | 17 |
| [Plan Status Validation](23_plan-status-validation.md) | Status/content mismatch in plans | Low | 15 |
| [Phased ADR Pattern](24_phased-adr-pattern.md) | Complex features need phased rollout | Medium | 07 |
| [PR Review Process](25_pr-review-process.md) | Inconsistent review quality | Low | — |
| [Conceptual Modeling](27_conceptual-modeling.md) | AI accumulates misconceptions about architecture | Medium | — |
| [Question-Driven Planning](28_question-driven-planning.md) | AI guesses instead of investigating | Low | — |
| [Uncertainty Tracking](29_uncertainty-tracking.md) | Uncertainties forgotten across sessions | Low | — |
| [Gap Analysis](30_gap-analysis.md) | Ad-hoc planning misses gaps between current and target | Medium | 28 |
| [External LLM Review](31_external-llm-review.md) | AI misses issues humans would catch | Low | — |
| [Recurring Issue Tracking](32_recurring-issue-tracking.md) | Issues recur despite "fixes", going in circles | Low | — |
| [Uncertainty Resolution](33_uncertainty-resolution.md) | Uncertainties listed but never resolved | Low | 29 |
| [Engineering Workflow](34_engineering-workflow.md) | Architectural decisions exist in docs but not loaded before implementation | Medium | 02, 07, 10 |
| [Cruft Lifecycle](35_cruft-lifecycle.md) | Codebases accumulate dead code and stale abstractions without systematic response | Low | — |
| [Executable Journey Notebooks](36_executable-journey-notebooks.md) | Plans stay abstract, notebooks drift, phase contracts remain invisible | Medium | 03, 10, 15, 34 |
| [Context Engineering](37_context-engineering.md) | Agent quality degrades as context fills | Medium | — |
| [Agent Tool Design](38_agent-tool-design.md) | Poor tool descriptions cause agent failures and waste context | Medium | 37 |
| [Agent Harness Engineering](39_agent-harness-engineering.md) | Long-running tasks lose state or complete prematurely | Medium | 37 |
| [Agent-Drivable UI](40_agent-drivable-ui.md) | Critical UI workflows work only by manual clicking | Medium | 39 |
| [Bookend Context Preservation](41_bookend-context-preservation.md) | Long sessions lose task framing after compaction | Low | 37 |
| [Planning Hierarchy](42_planning-hierarchy.md) | Need a compressed view of the canonical artifact dependency graph | High | 15, 28, 30, 36 |
| [Topic Research Synthesis](43_topic-research-synthesis.md) | Research gets lost instead of compounding into reusable guidance | Medium | 28 |

## Worktree Coordination Module

Use this module only when multiple agents are operating concurrently on the
same codebase. Most repos should start with the simpler branch-based workflow.

See [worktree-coordination/README.md](worktree-coordination/README.md) for the
module-specific structure and rollout details.

| Pattern | Problem Solved | Complexity | Requires |
|---------|----------------|------------|----------|
| [Claim System](worktree-coordination/18_claim-system.md) | Parallel work conflicts | Medium | — |
| [Worktree Enforcement](worktree-coordination/19_worktree-enforcement.md) | Main directory corruption from parallel edits | Low | 18 |
| [Rebase Workflow](worktree-coordination/20_rebase-workflow.md) | Stale worktrees causing reverted changes | Low | 19 |
| [PR Coordination](worktree-coordination/21_pr-coordination.md) | Lost review requests | Low | 15, 18 |
| [Ownership Respect](worktree-coordination/26_ownership-respect.md) | Agents interfere with each other's work | Low | 18 |

## Recommended Adoption Order

Start with these:

- [CLAUDE.md Authoring](02_claude-md-authoring.md)
- [Plan Workflow](15_plan-workflow.md)
- [Question-Driven Planning](28_question-driven-planning.md)
- [Topic Research Synthesis](43_topic-research-synthesis.md)
- [Git Hooks](06_git-hooks.md)

Add these when the repo actually feels the pain:

- [Doc-Code Coupling](10_doc-code-coupling.md)
- [ADR](07_adr.md) and [ADR Governance](08_adr-governance.md)
- [Acceptance-Gate-Driven Development](13_acceptance-gate-driven-development.md)
- [Verification Enforcement](17_verification-enforcement.md)
- [Conceptual Modeling](27_conceptual-modeling.md)

Add the worktree module only when parallel-agent coordination becomes a real
problem.

## Notes

- Patterns are reusable governance/coordination ideas, not a strict one-shot
  rollout checklist.
- Some items, like [Git Hooks](06_git-hooks.md) and [Terminology](11_terminology.md),
  are closer to conventions or infrastructure than to coordination patterns.
- The planning operating model itself remains canonical in
  [PLANNING_OPERATING_MODEL.md](../PLANNING_OPERATING_MODEL.md).

## Origin

These patterns were first developed while working in `agent_ecology2`, but they
are documented here as standalone framework patterns rather than project-local
rules.
