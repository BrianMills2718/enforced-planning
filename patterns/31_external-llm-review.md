# Pattern 31: External LLM Review

## Problem

You want an external LLM (Gemini, GPT, etc.) with a large context window to review your codebase or enforced-planning framework. But repos contain a mix of:
- **Core system** — the actual code and architecture docs
- **Enforced planning** — coordination tooling for CC instances
- **Infrastructure** — dependencies, build artifacts, runtime output

Dumping everything into context wastes tokens and confuses the reviewer.

## Solution

Use [repomix](https://github.com/yamadashy/repomix) with curated config files that define exactly what to include for each review purpose.

### Config Files

| Config | Purpose | Typical size |
|--------|---------|--------------|
| `repomix.core.json` | System code + architecture docs | ~200-300K tokens |
| `repomix.meta-process.json` | Enforced-planning patterns + scripts | ~100-150K tokens |

### Usage

```bash
# Generate core system bundle
npx repomix --config repomix.core.json
# Output: repomix-core.md

# Generate enforced-planning bundle
npx repomix --config repomix.meta-process.json
# Output: repomix-meta-process.md
```

Upload the generated `.md` file to your external LLM.

### What to Include

**Core system review:**
- `src/` — implementation code (selective, not all)
- `docs/architecture/current/` — what's built
- `docs/adr/` — key design decisions (first few are usually foundational)
- `config/` — runtime configuration
- `docs/GLOSSARY.md` — terminology

**Enforced-planning review:**
- `enforced-planning/patterns/` — all patterns
- `enforced-planning/scripts/` — coordination scripts
- `enforced-planning/hooks/` — hook implementations
- `CLAUDE.md` — CC instructions
- `Makefile` — workflow commands
- `meta-process.yaml` — enforcement config

### What to Exclude

- Tests (usually too large, not needed for architecture review)
- `node_modules/`, `venv/`, build artifacts
- Runtime output (`logs/`, `*.jsonl`)
- Session state (`.claude/`)

## Config Structure

```json
{
  "$schema": "https://repomix.com/schemas/latest/schema.json",
  "include": [
    "src/world/*.py",
    "docs/architecture/current/*.md"
  ],
  "ignore": {
    "useGitignore": true,
    "useDefaultPatterns": true
  },
  "output": {
    "filePath": "repomix-core.md",
    "style": "markdown"
  }
}
```

## Maintenance

When you add significant new modules or patterns, update the relevant repomix config to include them. No enforcement — this is a convenience tool.

## Related Patterns

- None (standalone utility pattern)
