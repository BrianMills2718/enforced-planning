# Enforced Planning: AI-Assisted Development Framework

A portable framework for coordinating AI coding assistants (Claude Code, etc.) on shared codebases.

## What This Solves

When AI instances work on a codebase:
- **Drift** - AI forgets constraints mid-implementation
- **Cheating** - AI writes weak tests that pass but don't verify requirements
- **No traceability** - Can't answer "what tests cover this feature?"
- **Documentation rot** - Docs diverge from code over time
- **AI guessing** - AI assumes instead of investigating

## Core Idea

**Move human review upstream.** Humans can't review code at AI speed, but CAN:
- Review requirements in plain English (Given/When/Then)
- See green/red CI
- Approve specs before implementation

If you trust the spec (human-reviewed) and trust CI (automated), you can trust implementation (green = done) without reading code.

The canonical methodology for how thesis, investigation, gap analysis,
capabilities, plans, notebooks, tests, code, and observability fit together is
[`PLANNING_OPERATING_MODEL.md`](PLANNING_OPERATING_MODEL.md).

## Quick Start

```bash
# 1. Install into your project
./install.sh /path/to/your/project

# 2. Configure what patterns to enable
vim meta-process.yaml

# 3. Start using
git checkout -b plan-N-description   # Create feature branch
# ... do work ...
make pr-auto-check && make pr-auto   # Non-interactive ship
# or: make pr-ready && make pr        # Interactive ship
make finish BRANCH=X PR=N            # Merge + cleanup
```

## Patterns (Pick What You Need)

### Always Recommended (Low Overhead)
| Pattern | What It Does |
|---------|--------------|
| Plans | Track work with `[Plan #N]` commits |
| Git Hooks | Catch issues before CI |
| Doc-Code Coupling | Fail CI when docs drift from code |
| Question-Driven Planning | AI investigates before coding |

### Add When Needed (More Setup)
| Pattern | What It Does |
|---------|--------------|
| ADR Governance | Link architecture decisions to code |
| Mock Policy | Enforce real tests over mocked tests |
| Acceptance Gates | Lock specs before implementation |
| Uncertainty Tracking | Preserve context across sessions |

### Multi-CC Coordination (Opt-In Module)
| Pattern | What It Does |
|---------|--------------|
| Claims + Worktrees | Prevent parallel AI instances from conflicting |
| Inter-CC Messaging | Async communication between AI instances |

> **Most projects don't need the multi-CC module.** A branch-based workflow with one AI instance at a time is simpler and works well. See `patterns/worktree-coordination/README.md` if you need it.

## Configuration

All patterns are configured in `meta-process.yaml`:

```yaml
weight: medium  # minimal | light | medium | heavy

planning:
  question_driven_planning: advisory  # disabled | advisory | required
  uncertainty_tracking: advisory
  dependency_probe_policy: strict     # strict | warn | ignore

enforcement:
  strict_doc_coupling: false  # true = soft couplings also block
```

See `templates/meta-process.yaml.example` for all options.

### Shared Policy Vocabulary

Some planning and gate behaviors should be configurable once and then consumed
by project-specific implementations. One example is dependency evidence:

```yaml
planning:
  dependency_probe_policy: strict  # strict | warn | ignore
```

- `strict` means blocked dependency probes should block planning/freeze gates
- `warn` means keep blocked probes visible but non-blocking
- `ignore` means record probe evidence but do not use it in gating decisions

The enforced-planning framework owns the vocabulary. Each project decides how to map that policy
into its own artifacts and gates.

## Directory Structure (After Install)

```
your-project/
├── meta-process.yaml        # Your configuration
├── enforced-planning/       # Portable framework (copy this to new projects)
│   ├── scripts/             # Baseline scripts (portable)
│   ├── patterns/            # Pattern documentation
│   │   └── worktree-coordination/  # Optional multi-CC module
│   └── hooks/               # Hook templates
├── scripts/                 # Project-specific scripts (may extend enforced-planning/)
├── docs/
│   └── plans/               # Implementation plans
├── hooks/                   # Git hooks
└── .claude/
    └── hooks/               # Claude Code hooks
```

## Portable vs. Project-Specific Scripts

The framework separates **portable** scripts from **project-specific** extensions:

| Directory | Purpose | When to Modify |
|-----------|---------|----------------|
| `enforced-planning/scripts/` | Baseline scripts that work in any project | Never (modify upstream) |
| `scripts/` | Project-specific scripts that extend the baseline | Add features specific to your project |

**When adopting the enforced-planning framework:**
1. Copy `enforced-planning/` directory to your project
2. Create project-specific scripts in `scripts/` as needed
3. Project scripts can import from enforced-planning or replace them entirely

## Truth-Surface Validation Workflow

For coordination-heavy repos, keep one config file that names the active tracker,
plan index, runtime registry, and any measured audit surface.

```bash
python scripts/check_truth_surface_drift.py --config path/to/truth_surface_drift.yaml
python scripts/render_truth_surface_status.py --config path/to/truth_surface_drift.yaml
```

Use the validator to detect contradictions. Use the renderer to produce a compact
current-state summary from validator output instead of hand-maintaining status
prose.

This workflow is deterministic by design. It is the right default for hard
contradictions and machine-checkable parity. A later optional LLM/agent review
layer should sit on top of it for semantic drift, misleading prose, and missing
cross-surface updates that exact rules cannot capture robustly.

See `templates/truth_surface_drift.yaml.example` for the scaffold.

## Full Documentation

See `patterns/` directory for detailed documentation of each pattern:
- `PLANNING_OPERATING_MODEL.md` - Canonical methodology and artifact dependency model
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md` - Static graph vs runtime coordination architecture
- `patterns/01_README.md` - Pattern index (core + optional modules)
- `patterns/15_plan-workflow.md` - How bounded plans work inside the operating model
- `patterns/13_acceptance-gate-driven-development.md` - Full acceptance gate system

## Customizing for Your Project

The patterns are generic but examples come from [agent_ecology2](https://github.com/BrianMills2718/agent_ecology2), the project where this framework was developed. When adopting, replace project-specific terms in pattern documentation:

| agent_ecology2 term | Replace with |
|----------------------|--------------|
| `scrip` | Your currency/points system (or remove) |
| `principal` | Your user/account concept |
| `artifact` | Your entity/object concept |
| `kernel` | Your core/engine module |
| `ledger` | Your transaction/state store |

## Origin

Emerged from the [agent_ecology](https://github.com/BrianMills2718/agent_ecology2) project while coordinating Claude Code instances.

## License

MIT
