# Enforced Planning and Development Alignment

A portable framework for AI-assisted software development that enforces
three layers of discipline:

1. **Enforced Planning** — Specifications locked before implementation.
   Question-driven investigation, plan workflow with `[Plan #N]` commits,
   acceptance gates.

2. **Enforced Context (Read-Gating)** — Agents must read governing docs
   before editing coupled source files. Claude Code hooks enforce this
   at edit time.

3. **Enforced Alignment (Doc-Code Coupling)** — When code changes,
   coupled documentation must update too. CI and pre-commit hooks catch
   drift.

## Previously: meta-process

This framework was extracted from `project-meta/meta-process/` on
2026-04-01. The name "meta-process" described the mechanism; "enforced
planning" describes the value. All patterns, scripts, hooks, and
templates are identical to the source.

## Structure

```
enforced-planning/
├── patterns/        # 27 core patterns + opt-in modules
├── scripts/         # Baseline enforcement scripts
├── hooks/           # Git + Claude Code hook templates
├── templates/       # File templates for governed repos
├── adr/             # Framework-level architecture decisions
├── ci/              # CI workflow templates
├── install.sh       # Install into a target project
└── GETTING_STARTED.md
```

## Quick Start

```bash
# Install into any project
./install.sh /path/to/project

# Configure
vim /path/to/project/meta-process.yaml

# Work
git checkout -b plan-N-description
# ... implement ...
make pr-auto  # ship
```

## Core Patterns (always recommended)

- Plans: Track work with `[Plan #N]` commits and acceptance criteria
- Git Hooks: Catch issues before CI
- Doc-Code Coupling: Fail CI when docs drift from code
- Question-Driven Planning: AI investigates before implementing
- Read-Gating: Required reading enforced at edit time

## References

- `GETTING_STARTED.md` — Full adoption guide
- `patterns/01_README.md` — Pattern index with dependencies
- `adr/` — Framework architecture decisions
- Thesis: `project-meta/vision/ENFORCED_PLANNING_AND_DEV_ALIGNMENT_THESIS.md`
