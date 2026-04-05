# Enforced Planning and Development Alignment

A portable framework for AI-assisted software development that enforces
three layers of discipline:

## AUTONOMOUS EXECUTION CONTRACT

> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
> ⚠️  NEVER STOP — ABSOLUTE RULE, NO EXCEPTIONS  ⚠️
> ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
>
> Per Brian's explicit standing instruction: execute all sprint phases
> continuously without pausing, confirming, summarizing-and-waiting,
> or asking "should I continue?" A completed phase is NOT a stop
> condition. A green test run is NOT a stop condition. Finishing a
> commit is NOT a stop condition. Update the tracker and move
> immediately to the next phase.
>
> **ONLY TWO LEGITIMATE STOP CONDITIONS — nothing else qualifies:**
> 1. An action that is BOTH irreversible AND affects shared state
>    (force push to main, drop production table, delete prod data)
> 2. A genuine architectural decision that is NOT pre-made in the
>    active sprint plan AND cannot be safely defaulted
>
> **EVERYTHING ELSE IS NOT A STOP CONDITION — keep executing:**
> - Completed phase or sub-phase → commit, update checklist, next phase
> - Green test suite → commit, continue
> - File not found → read the directory, find it, proceed
> - Uncertainty about wording → read the source file, pick the clearer option
> - Transient tool failure → retry once, then proceed
> - "Should I continue?" → the answer is always YES
> - "Is this the right approach?" → if it's in the sprint plan, YES
> - Any question answerable by reading the sprint doc → read it, proceed

Active sprint tracker:
- **COMPLETE:** `docs/ops/SPRINT_2026_04_03_AUDIT_FOLLOWUP.md` — audit follow-up sprint. All 6 phases done.
- **COMPLETE:** `docs/ops/SPRINT_2026_04_03_ALL_ISSUES.md` — prior sprint, all done.

Phase checklist (current sprint — update as completed):
- [x] Phase 1a: Add patterns 34+35 to 01_README.md
- [x] Phase 1b: Fix NEW_PROJECT_SETUP.md Step 3 broken commands
- [x] Phase 1c: Delete ISSUES_LEGACY_agent_ecology2.md
- [x] Phase 1d: Document verify_coupling.py model choice rationale
- [x] Phase 1e: Fix stale CLAUDE.md References section
- [x] Phase 2a: Bump pyproject.toml to 1.0.0
- [x] Phase 2b: Create and push v1.0.0 git tag
- [x] Phase 3a: Define notebook required threshold in POM
- [x] Phase 3b: Mirror notebook threshold in Pattern 36
- [x] Phase 3c: Define "governed repo" in README and GETTING_STARTED
- [x] Phase 3d: Fix Makefile infer-all (replace ls -d with find)
- [x] Phase 4a: Write scripts/render_agents_md.py
- [x] Phase 4b: Add make agents-md target; regenerate AGENTS.md
- [x] Phase 5a: Make Phase 8 gate measurable in ROADMAP.md
- [x] Phase 5b: Move permanently-deferred items to docs/backlog/
- [x] Phase 6a: Write tests/test_complete_plan.py (≥12 tests)

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

## Commands

```bash
# Install enforced-planning into any project
./install.sh /path/to/project                   # default (git hooks)
./install.sh /path/to/project --pre-commit      # pre-commit framework mode
./install.sh /path/to/project --minimal         # minimal baseline only

# Render AGENTS.md (for Codex / non-CC tools)
make agents-md                                   # regenerate AGENTS.md
python scripts/render_agents_md.py --stdout     # preview to stdout

# Run enforcement scripts
python scripts/check_locked_couplings.py --strict   # locked coupling check
python scripts/check_plan_capabilities.py           # plan capabilities check
python scripts/sync_plan_status.py                  # sync plan index status

# Tests
pytest tests/ -v                                # full test suite (26 tests)
make test                                       # same via Makefile

# Pre-commit hooks
pre-commit run --all-files                      # run all hooks (CI mode)
pre-commit install                              # install into current repo
```

## Principles

1. **Plan before code** — specifications locked before implementation
2. **Fail loud** — no silent fallbacks; violations block commit or CI
3. **Read-gate first** — agents must read governing docs before editing coupled files
4. **Doc-code coupling** — when code changes, coupled docs must update
5. **Observability** — every agent action is logged and traceable
6. **Simplest thing that works** — don't over-engineer; three similar lines beat a premature abstraction

## Workflow

1. `git checkout -b plan-N-description`
2. Open `docs/plans/NN_name.md` (copy from template)
3. Fill in gap, acceptance criteria, steps
4. Implement → test → commit with `[Plan #N]` prefix
5. `make check` or `pre-commit run --all-files` before PR
6. `python scripts/meta/complete_plan.py --plan N` to mark done

## Core Patterns (always recommended)

- Plans: Track work with `[Plan #N]` commits and acceptance criteria
- Git Hooks: Catch issues before CI
- Doc-Code Coupling: Fail CI when docs drift from code
- Question-Driven Planning: AI investigates before implementing
- Read-Gating: Required reading enforced at edit time

## References

- `PLANNING_OPERATING_MODEL.md` — Canonical methodology and artifact dependency model
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md` — Canonical split between static graph and runtime coordination state
- `GETTING_STARTED.md` — Full adoption guide
- `patterns/01_README.md` — Pattern index with dependencies
- `adr/` — Framework architecture decisions
- `docs/ops/SPRINT_2026_04_03_AUDIT_FOLLOWUP.md` — Active sprint (audit follow-up, phases 1–4 done)
- `docs/ops/archive/` — All prior sprint documents
