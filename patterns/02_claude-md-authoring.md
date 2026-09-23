# Pattern: AGENTS.md Authoring

## Problem

AI coding assistants (Claude Code, Cursor, etc.) start each session without project context. They:
- Don't know your conventions
- Don't know your architecture
- Don't know what terminology you use
- Make assumptions that conflict with your design

Result: Wasted time correcting the AI, inconsistent code, violated principles.

## Solution

Create a `AGENTS.md` file at project root that AI assistants automatically read. Include:
1. Project overview (what this is, what it's NOT)
2. Key commands (how to build, test, run)
3. Design principles (fail loud, no magic numbers, etc.)
4. Terminology (canonical names for concepts)
5. Coordination protocol (if multiple AI instances)

## Files

| File | Purpose |
|------|---------|
| `AGENTS.md` | Root context file (always loaded) |
| `*/AGENTS.md` | Directory-specific context (loaded when working in that directory) |

## Setup

### 1. Create root AGENTS.md

```markdown
# Project Name - Claude Code Context

This file is always loaded. Keep it lean. Reference other docs for details.

## What This Is

[1-2 sentences: what the project does]

## What This Is NOT

[Common misconceptions to prevent]

## Project Structure

```
project/
  src/           # Source code
  tests/         # Test suite
  docs/          # Documentation
  config/        # Configuration
```

## Key Commands

```bash
pip install -e .              # Install
pytest tests/                 # Test
python -m mypy src/           # Type check
```

## Design Principles

### 1. [Principle Name]
[Brief explanation]

### 2. [Principle Name]
[Brief explanation]

## Terminology

| Use | Not | Why |
|-----|-----|-----|
| `term_a` | `term_b` | Consistency |

## References

| Doc | Purpose |
|-----|---------|
| `docs/architecture/` | How things work |
| `docs/GLOSSARY.md` | Full terminology |
```

### 2. Add directory-specific context (optional)

```markdown
# src/AGENTS.md

## This Directory

Source code for [component].

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point |
| `utils.py` | Shared utilities |

## Conventions

- All functions must have type hints
- Use `raise RuntimeError()` not `assert` for runtime checks
```

### 3. Keep it lean

The root AGENTS.md is **always in context**. Every token counts:
- Reference other docs, don't duplicate
- Use tables for dense information
- Omit obvious things

## Usage

### For AI assistants

The file is automatically loaded. No action needed.

### For humans

Review and update when:
- Adding new conventions
- Changing architecture
- Onboarding reveals missing context

### Maintenance

```bash
# Check if AGENTS.md references exist
grep -r "See \`" AGENTS.md | while read line; do
  # Verify referenced files exist
done
```

## Content Guidelines

### DO Include

| Content | Example |
|---------|---------|
| Build/test commands | `pytest tests/ -v` |
| Design principles | "Fail loud, no silent fallbacks" |
| Terminology | "Use 'scrip' not 'credits'" |
| File purposes | "config.yaml has runtime values" |
| Anti-patterns | "Never use `except: pass`" |

### DON'T Include

| Content | Why |
|---------|-----|
| Implementation details | Changes frequently, goes stale |
| Full API docs | Too verbose, use references |
| Tutorial content | Not context, it's documentation |
| Aspirational features | Confuses current vs future |

### Size Guidelines

| Section | Target Size |
|---------|-------------|
| Root AGENTS.md | 200-400 lines |
| Directory AGENTS.md | 50-100 lines |
| Any single section | <50 lines |

## Customization

### For multi-AI coordination

Add coordination sections:

```markdown
## Active Work

| Instance | Task | Claimed |
|----------|------|---------|
| - | - | - |

## Coordination Protocol

1. Claim before starting
2. Release when done
3. Check claims before starting
```

### For monorepos

```
monorepo/
  AGENTS.md           # Repo-wide context
  packages/
    api/AGENTS.md     # API-specific
    web/AGENTS.md     # Web-specific
```

### For different AI tools

| Tool | File Name | Notes |
|------|-----------|-------|
| Claude Code | `AGENTS.md` | Auto-loaded when the project has no CLAUDE.md |
| Codex | `AGENTS.md` | Auto-loaded as the authored project instruction |
| Cursor | `.cursorrules` | Different format |
| GitHub Copilot | No equivalent | Use comments |

### Canonical instructions

Author `AGENTS.md` once for Claude Code and Codex. Keep
`scripts/relationships.yaml` as the machine-readable coupling and
required-reading graph. Existing repositories can retain a legacy
`CLAUDE.md` while migrating, but new repositories use authored `AGENTS.md`.

## Validation

Use `scripts/check_agents_sync.py --check` to validate the root authored file
in an AGENTS-only repository. In a repository that maintains a subtree
registry, use `scripts/check_subtree_instructions.py` with that registry to
check that registered directories contain `AGENTS.md` and no legacy
`CLAUDE.md`. The legacy `CLAUDE.md` path remains supported during migration.

## Limitations

- **Token cost** - Large files consume context window
- **Not enforced** - AI may still ignore instructions; use deterministic
  validators and hooks for correctness-critical guarantees

## Anti-Patterns

| Anti-Pattern | Problem |
|--------------|---------|
| Duplicating docs | Goes stale, wastes tokens |
| Too verbose | Crowds out actual work context |
| Aspirational content | Confuses AI about current state |
| No structure | Hard to scan, find information |

## Examples

### Minimal (small project)

```markdown
# MyApp - Project Instructions

Python CLI tool for X.

## Commands
```bash
pip install -e . && pytest
```

## Principles
- Type hints required
- No silent failures
```

### Full (large project)

See this project's [AGENTS.md](../../AGENTS.md) for a complete example.

## See Also

- [Claim system pattern](worktree-coordination/18_claim-system.md) - Coordination tables in AGENTS.md
- [Plan workflow pattern](15_plan-workflow.md) - Linking AGENTS.md to plans
- [Uncertainty Tracking](29_uncertainty-tracking.md) - Session continuity across sessions
