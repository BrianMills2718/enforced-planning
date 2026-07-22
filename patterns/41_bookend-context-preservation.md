# Pattern: Bookend Context Preservation

## Problem

Long-running agent sessions undergo context compaction (automatic or manual).
Naive compaction summarizes everything equally, which destroys the original
task framing — the mission statement, acceptance criteria, and constraints
that define what the agent is trying to do.

After 3+ compaction cycles, the agent optimizes for what survived the
summaries, not the original intent. This manifests as:
- Agent "forgets" why it started and pursues tangential work
- Acceptance criteria drift or disappear
- Constraints are violated because they were compressed away
- Agent declares success against a degraded version of the original goal

This is the #1 failure mode in autonomous long-running work.

## Solution

Preserve the **bookends** of the conversation — the beginning (task framing)
and end (recent context) — and only compress the **middle** (completed tool
outputs). The file system provides the persistent bookend that survives any
number of compaction cycles.

### Protocol

**Step 1 — Select the state authority.**
Reuse the current plan, issue, task, or goal. Only when no suitable authority
exists and compaction would otherwise lose the framing, create one compact
mission record using the continuous execution contract's fields.

**Step 2 — Re-read at a real recovery boundary.**
Re-read the authority after compaction, at session resumption, or when the next
action becomes unclear. Do not use a turn counter as a mandatory ceremony.

**Step 3 — Re-anchor after compaction.**
When compaction fires, immediately re-read the selected authority. It is the
durable framing that compaction cannot degrade.

**Step 4 — Update only when durable state changes.**
Keep demonstrated behavior, current increment, blockers, and resume event
current at meaningful boundaries rather than mirroring every commit.

### Context Window Layout (REACTIVE_COMPACT)

```
┌──────────────────────┐
│ Task framing          │ ← PRESERVE: original prompt, system context,
│ (~first 50K tokens)   │   acceptance criteria, mission statement
├──────────────────────┤
│ Completed work        │ ← COMPRESS: finished tool outputs, file reads,
│ (middle section)      │   bash results, intermediate reasoning
├──────────────────────┤
│ Recent context        │ ← PRESERVE: active work, current state,
│ (~last 100K tokens)   │   recent decisions and results
└──────────────────────┘
```

Claude Code internally implements this layout (feature flag REACTIVE_COMPACT).
We complement it with the file-based mission protocol: belt and suspenders.

## Files

| File | Purpose |
|------|---------|
| `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md` | Full protocol and compact mission-record fields |
| `~/projects/.claude/CLAUDE.md` | Root instruction referencing this pattern |
| Pattern 37 (Context Engineering) | General context management (this pattern extends it) |

## Setup

This pattern is activated by selecting a continuous execution profile and
re-reading the current state authority through `/start` after a restart or
context compaction. No additional configuration is needed.

## Customization

- For very short tasks (<15 min), skip the mission file and rely on context
- For multi-agent work, all agents read the same selected authority

## Limitations

- Cannot control Claude Code's internal compaction behavior
- A durable authority requires agent discipline to maintain
- Re-reading adds context cost, so do it at recovery boundaries
- Does not prevent compaction from degrading non-mission context

## Requires

- Pattern 37 (Context Engineering) — general context management principles

## Origin

Derived from Claude Code's internal REACTIVE_COMPACT feature flag, analyzed
from the leaked TypeScript source (March 2026). See
`research_synthesis/agent_harness/MEMORY_AND_CONTEXT.md` for full analysis.
