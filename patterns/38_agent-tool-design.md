# Pattern: Agent Tool Design

## Problem

Poorly designed tools are the #1 cause of agent failures (Amazon production data). Agents select tools based on descriptions and schemas — if these are ambiguous, agents pick wrong tools, pass wrong parameters, or call tools unnecessarily. Meanwhile, tool definitions and results consume context, and bloated tool sets degrade both selection accuracy and overall agent performance.

## Solution

Design tools as if writing system prompts. Every tool definition is a context budget decision.

### Tool Description Principles

Descriptions deserve the same care as system prompts. Every description must answer:
- **What** does this tool do?
- **When** should the agent use it vs. alternatives?
- **What** does it return? (field names, types, structure)
- **What** are the constraints and edge cases?

With deferred tool loading, descriptions also become the search corpus — invest heavily in semantic keywords that match how users describe tasks.

### Tool Architecture

- **Task-oriented, not REST wrappers** — one `research_topic()` beats five `get_X()` calls
- **Prefer generic over specialized** — models perform better with tools they natively understand (bash, file read/write). Build specialized tools only when generic ones provably fail. (Vercel: 80% → 100% success by removing specialized tools.)
- **MCP wrappers are thin adapters** — business logic stays in implementation, never in the server file
- **Parameterize, don't hardcode** — limits as tool parameters with sensible defaults

### Result Management

- **Clean before context entry** — strip HTML, trim fields, cap sizes. Raw API responses are never acceptable.
- **Return readable text, not raw JSON** — agents reason about text. Include human-readable context alongside IDs.
- **Summarize-and-store for large results** — return summary, store full data in file.

### Scaling Tools

When tool count exceeds ~10:
- Enable deferred loading / tool search
- Keep 3-5 most-used tools always loaded
- Write descriptions optimized for search
- Consider consolidating related tools into task-oriented compound tools

### Structured Output

When tools return data for LLM consumption:
- Use `json_schema` response_format with descriptive Field descriptions
- Schema field descriptions constrain LLM behavior at decode time
- Design prompt and schema together — two halves of one contract
- Parse permissively with a separate lenient model

## Files

| File | Purpose |
|------|---------|
| `~/.claude/skills/tool-design/SKILL.md` | Full tool design runbook |
| `~/projects/project-meta/research_synthesis/agent_tools/` | Deep reference library |

## Setup

1. Before designing new tools, invoke `/tool-design` to load the runbook
2. For MCP servers, follow the thin adapter pattern
3. Test tools in agent loops, not just isolation

## Limitations

- Tool search adds latency (extra search step before tool use)
- Deferred loading and tool use examples are currently incompatible on the same tool
- Generic tools work better for most tasks, but some domains genuinely need specialized tools

## Origin

Derived from Anthropic's "Advanced Tool Use" (2026), Amazon's production agent failure analysis, Vercel's text-to-SQL agent redesign, and the tool_Calling_optimization_guide written for OpenClaw. Formalized after the onto-canon6 structured output discovery (18.8% → 87.8% resolution via schema descriptions alone).
