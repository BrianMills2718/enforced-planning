# Pattern: Agent Harness Engineering

## Problem

Long-running autonomous agent tasks (>35 minutes, multi-session, or multi-agent) fail in predictable ways:
1. Agent tries to one-shot everything, runs out of context mid-implementation
2. Agent declares done prematurely without verification
3. Next session has no idea what the previous session did
4. Research consumes context that implementation needs
5. Agent makes the same mistake repeatedly because corrections accumulate in context

Research shows success rates decrease after ~35 minutes, and doubling task duration quadruples failure rate.

## Solution

Design a **legible environment** where each session can quickly understand state, pick up work, verify results, and leave a clean handoff.

### Three Pillars

**1. Legible Environment**
Any agent resuming material work must be able to recover project state within
the first few tool calls.

- **One state authority** — reuse the current plan, issue, task, or goal. Create
  a compact mission record only when cross-session or compaction risk would
  otherwise lose the framing.
- **No parallel projections** — do not maintain both a task list and progress
  file when one authority can hold the outcome, acceptance checks, demonstrated
  behavior, next increment, and resume event.
- **File system as shared memory** — durable state belongs in the selected
  authority rather than only in conversation history.

**2. Verification**
The agent must be able to check its own work. This is the single highest-leverage investment.

- For code: run tests, type-check, lint
- For UI: screenshot comparison, browser automation
- For data: structural validation, sample checks
- Prompt: "After each change, verify. Do not mark complete without passing verification."
- End-to-end tests catch what unit tests miss — give agents proper e2e tooling (puppeteer, Chrome DevTools)

**3. Trust Generic Tools**
Models perform better with tools they natively understand than with bespoke domain-specific tools.

- Start with bash, file read/write, web search
- Build specialized tools only when generic ones provably fail
- The foundation is a good documentation environment where models can use generic tools to retrieve context progressively
- Anthropic and Vercel independently confirmed this: simpler tool sets with better context produce better results than complex specialized tooling

### Execution Loop

Each session follows:
1. Read the selected state authority to understand the outcome and current state
2. Pick highest-priority incomplete task
3. Implement in thin verified slices
4. Verify (tests, checks — not "looks right")
5. Commit with descriptive message
6. Update the same authority only when durable cross-session state changed
7. Repeat until milestone or blocker

### Context Hygiene During Execution

- Delegate research to subagents (isolated context, summary returns)
- Compact proactively between task batches
- After 2 failed corrections on the same issue, clear context and restart with a better prompt
- Write structured notes to files during work, not just at handoff (agentic memory)

### Clean Handoff

Before ending unfinished multi-session work, update the one state authority,
commit verified changes, and record any blocker plus the exact resume event. A
completed bounded task with no residual state needs no separate handoff.

## Files

| File | Purpose |
|------|---------|
| `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md` | Continuous execution and state-preservation contract |
| `~/.claude/skills/design-subagents/SKILL.md` | Subagent design guide |

## Setup

For work that will genuinely span sessions or context compaction:

1. Select the smallest profile from the continuous execution contract
2. Reuse one existing state authority
3. Create a compact mission record only if no suitable authority exists
4. Set up only the verification needed to disprove the current claim

## Customization

- Task file format: simple markdown checklist, JSON with pass/fail state, or plan docs — whatever fits the project
- Progress file location: `.claude/tasks/`, `docs/plans/`, or project-specific convention
- Verification depth: proportional to task risk. Trivial changes need less; architectural changes need full e2e.

## Limitations

- Adds state-maintenance overhead when cross-session recovery is genuinely needed.
- File-system shared memory requires discipline — agents must actually read and update the files.
- Verification tooling (puppeteer, browser automation) has its own setup cost.
- Agent teams (multi-agent collaboration) add 3-4x token cost vs. single session.

## Origin

Synthesized from Anthropic's harness engineering experiments (Claw.ai clone), OpenAI's legible environment pattern (Codex), Manus team's file-system context management, and JaysonZAI's subagent workflow practices. Formalized after observing the same failure patterns across multiple projects in Brian's workspace.
