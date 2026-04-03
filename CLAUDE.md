# Enforced Planning and Development Alignment

A portable framework for AI-assisted software development that enforces
three layers of discipline:

## AUTONOMOUS EXECUTION CONTRACT

> ⚠️ **NEVER STOP — THIS IS AN ABSOLUTE RULE FOR THIS PROJECT** ⚠️
>
> Per Brian's explicit instruction (2026-04-03): run continuously through all
> sprint phases. Do not pause, do not ask for confirmation, do not summarize
> and wait. A completed phase is NOT a stop condition — update the tracker and
> move immediately to the next phase.
>
> **Legitimate stop conditions (ONLY these two):**
> 1. Irreversible action affecting shared state (force push, drop table, delete prod data)
> 2. Genuine architectural decision NOT pre-made in the active sprint plan
>
> **NOT stop conditions (keep going):**
> - Completed phase or sub-phase → commit and continue
> - Green test run → commit and continue
> - Uncertainty about file location → check it and proceed
> - Transient tool failure → retry once and proceed
> - "Should I continue?" → YES, continue
> - Any question answerable by reading the sprint plan → read and proceed

Active sprint tracker:
- **COMPLETE:** `docs/ops/SPRINT_2026_04_03_ALL_ISSUES.md` — full documentation
  and technical debt resolution sprint. 7 phases, all 23 sub-phases done.
- Last completed: 2026-04-03 sprint — all phases 1-7 complete, 307 tests passing.

Phase checklist (update as completed):
- [x] Phase 1a: Fix verify_coupling.py API
- [x] Phase 1b: Create Plan #12 file
- [x] Phase 1c: Replace ISSUES.md
- [x] Phase 2a: Archive docs/ops/ sprint docs
- [x] Phase 2b: Move TRAYCER_COMPARISON.md
- [x] Phase 2c: Add Claude-Code disclaimer to README/GETTING_STARTED
- [x] Phase 2d: Audit meta-process.yaml.example
- [x] Phase 2e: Define "trivial" concretely in Pattern 15
- [x] Phase 2f: Create V1→V2 migration guide
- [x] Phase 3a: Make POM explicitly canonical
- [x] Phase 3b: Reduce Pattern 42 to summary
- [x] Phase 3c: Update GETTING_STARTED to lead with POM
- [x] Phase 4a: Write "New Project Setup" guide
- [x] Phase 4b: Document functional config keys
- [x] Phase 5a: Create .pre-commit-hooks.yaml
- [x] Phase 5b: Create pre-commit-config.yaml.example template
- [x] Phase 5c: Update install.sh --pre-commit mode
- [x] Phase 5d: Update docs for pre-commit
- [x] Phase 6a: Tests for parse_plan.py
- [x] Phase 6b: Tests for sync_plan_status.py
- [x] Phase 6c: Tests for check_plan_tests.py
- [x] Phase 7a: Add Phase 8 to ROADMAP
- [x] Phase 7b: Document deferred item blockers

**Sprint complete — 2026-04-03. All 23 phases done. 307 tests pass.**

Rules during continuous execution:
- complete the current phase, update the tracker, and move immediately to the next phase
- log uncertainties in the tracker instead of silently stopping
- commit every verified slice as its own rollback point
- treat stale tracker pointers as governance regressions and fix them before relying on them

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
├── patterns/        # Core patterns + opt-in modules (see patterns/01_README.md)
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

- `docs/ops/OVERNIGHT_SPRINT_2026_04_02_TRUTH_SURFACE.md` — Completed sprint (Plans #2-5)
- `PLANNING_OPERATING_MODEL.md` — Canonical methodology and artifact dependency model
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md` — Canonical split between static graph and runtime coordination state
- `GETTING_STARTED.md` — Full adoption guide
- `patterns/01_README.md` — Pattern index with dependencies
- `adr/` — Framework architecture decisions
- Thesis: `project-meta/vision/ENFORCED_PLANNING_AND_DEV_ALIGNMENT_THESIS.md`
