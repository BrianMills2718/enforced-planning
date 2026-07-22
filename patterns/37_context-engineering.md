# Pattern: Context Engineering

## Problem

Agent performance degrades as context fills — a phenomenon called "context rot." This isn't just about hitting token limits; accuracy drops gradually as irrelevant tokens compete for the model's finite attention budget. Long-running tasks, multi-tool workflows, and large codebases all generate context pollution that makes agents less effective over time.

Without deliberate context management:
- Agents lose track of earlier instructions
- Tool selection accuracy drops above 30-50 loaded tools
- Research sessions consume context that implementation needs
- Old tool results from 20 steps ago crowd out current work
- Agents declare tasks complete without proper verification

## Solution

Treat context as a depletable resource with diminishing returns. Apply the **just-in-time context** principle: maintain lightweight references, load data at runtime, discard when no longer needed.

### Core Strategies

**1. Just-in-Time Retrieval**
Instead of pre-loading everything, maintain lightweight identifiers (file paths, IDs, queries) and load data dynamically at runtime using tools. This mirrors how humans use file systems and bookmarks — we don't memorize corpora, we know where to find things.

**2. Progressive Disclosure**
Each exploration step yields signals — file sizes indicate complexity, naming conventions hint purpose, timestamps suggest relevance. Layer understanding incrementally rather than reading everything upfront.

**3. Clean Before Entry**
Every tool result must be cleaned before it enters context. Strip HTML, trim unused fields, cap collection sizes. For large results, return a summary and store full data in a file (summarize-and-store pattern).

**4. Isolate Expensive Work**
Delegate research and read-heavy tasks to subagents. They explore in isolated context and return only summaries (typically 1-2K tokens vs. tens of thousands expended). The main agent stays clean for implementation.

**5. Compact Proactively**
After completing a batch of related tasks, compact the conversation. Don't wait for auto-compaction. Old tool results are the safest, lightest-touch content to clear.

**6. Structured Note-Taking**
The agent writes notes to files *during* work, not just at handoff. These persist outside the context window and can be retrieved later. This is agentic memory — the agent builds its own knowledge base as it works.

### Extension Mechanism Selection

Choose the cheapest mechanism that solves the problem:

| Mechanism | Context cost | When to use |
|-----------|-------------|-------------|
| CLAUDE.md | Every request | Always-on rules and conventions |
| Skills | Low (description until invoked) | On-demand knowledge, repeatable workflows |
| Subagents | Isolated | Research, read-heavy tasks, parallel work |
| MCP | Every request (schemas) | External system access only |
| Hooks | Zero | Deterministic automation |

### Long-Horizon Selection Criteria

| Technique | Best for |
|-----------|----------|
| Compaction | Extensive back-and-forth conversation tasks |
| Note-taking | Iterative development with clear milestones |
| Multi-agent | Complex research/analysis with parallel exploration |

## Files

| File | Purpose |
|------|---------|
| `~/.claude/CLAUDE.md` | Cross-project context management rules |
| `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md` | Continuous execution and durable state contract |
| `~/.claude/skills/tool-design/SKILL.md` | Tool optimization runbook |
| `~/.claude/skills/design-subagents/SKILL.md` | Subagent design guide |

## Setup

This pattern is already applied through the cross-project CLAUDE.md and skills. For new projects:

1. Ensure `~/.claude/CLAUDE.md` is loaded (it is by default)
2. For continuous work, select the smallest profile in the continuous execution contract; use `/start` after a restart or compaction
3. For tool-heavy projects, invoke `/tool-design` before designing new tools

## Customization

- Adjust compaction aggressiveness based on task complexity
- For very long sessions (>35 min), consider starting fresh with a better prompt rather than accumulating corrections
- For multi-agent setups, the file system is the shared context layer — standardize where progress files, research reports, and plans live

## Limitations

- Context rot is a structural constraint of transformer architecture, not a bug to fix
- Compaction always loses some information — tune what to preserve vs. discard
- Subagent isolation means they can't see what the parent or other subagents did
- "Do the simplest thing that works" — over-engineering context management adds its own overhead

## Cross-Platform Applicability

These patterns apply to any agent system (Claude Code, Codex CLI, Cursor, etc.). The principles — just-in-time context, clean results, subagent isolation, verify-before-done — are architectural, not platform-specific. Platform differences (context window size, tool loading strategy, sandbox model) affect tuning but not the core patterns.

Both Anthropic and OpenAI independently converged on the same guidance: plan before complex work, use subagents for research, compact proactively, maintain one thread per task, and verify before declaring done.

## Origin

Synthesized from Anthropic's "Effective Context Engineering for AI Agents" (2026), OpenAI's "Harness Engineering" and Codex best practices, Anthropic's "Advanced Tool Use" engineering blog, Chroma Research on context rot, and practical experience across 70+ projects in Brian's workspace. Formalized as an enforced-planning pattern after discovering that context management failures were the root cause of most agent quality issues.
