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

**Step 1 — Write a mission file at session start.**
Create a progress/mission file (e.g., `PROGRESS.md`) containing: objective,
acceptance criteria, constraints, current phase, completed work. This file
lives on disk, outside the context window.

**Step 2 — Re-read the mission file every ~20 turns.**
Periodically verify current work still aligns with the objective. Correct
course if drifted.

**Step 3 — Re-anchor after compaction.**
When compaction fires (earlier context feels summarized or missing),
immediately re-read the mission file. It is the ground truth that compaction
cannot degrade.

**Step 4 — Update the mission file at each commit.**
Keep the "Completed" and "Current Phase" sections current so any future
session or agent starts with an accurate picture.

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
| `~/.claude/skills/long-running-task/SKILL.md` | Full protocol and mission file template |
| `~/projects/.claude/CLAUDE.md` | Root instruction referencing this pattern |
| Pattern 37 (Context Engineering) | General context management (this pattern extends it) |

## Setup

This pattern is activated by invoking `/long-running-task` at the start of
any long-running session. No additional configuration needed.

For optional enforcement, a PostToolUse hook can periodically check whether
a mission file exists and remind the agent to re-read it.

## Customization

- Adjust re-read frequency (default: every ~20 turns) based on task complexity
- For very short tasks (<15 min), skip the mission file and rely on context
- For multi-agent work, the mission file is the shared contract — all agents
  read the same file

## Limitations

- Cannot control Claude Code's internal compaction behavior
- Mission file requires agent discipline to create and maintain
- Re-reading adds a small context cost (~200 tokens per re-read)
- Does not prevent compaction from degrading non-mission context

## Requires

- Pattern 37 (Context Engineering) — general context management principles

## Origin

Derived from Claude Code's internal REACTIVE_COMPACT feature flag, analyzed
from the leaked TypeScript source (March 2026). See
`research_synthesis/agent_harness/MEMORY_AND_CONTEXT.md` for full analysis.
