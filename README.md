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
vim /path/to/your/project/meta-process.yaml

# 3. Start using
cd /path/to/your/project
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
├── meta-process.yaml                # Your configuration
├── truth_surface_drift.yaml.example # Optional truth-surface scaffold
├── scripts/
│   ├── check_truth_surface_drift.py # Repo-local truth-surface validator
│   ├── render_truth_surface_status.py
│   └── meta/                        # Baseline enforced-planning scripts
├── docs/
│   ├── plans/                       # Implementation plans
│   └── meta-patterns/               # Copied pattern documentation
├── hooks/                           # Git hooks
└── .claude/
    └── hooks/                       # Claude Code hooks
```

## Portable vs. Project-Specific Scripts

The installer copies portable framework scripts directly into the governed repo.
Use these conventions after install:

| Directory | Purpose | When to Modify |
|-----------|---------|----------------|
| `scripts/meta/` | Baseline enforced-planning workflow scripts copied from the framework | Modify upstream in `enforced-planning`, then re-install or replay intentionally |
| `scripts/` | Repo-local entrypoints and project-specific scripts | Add repo-specific tools here |

Truth-surface tools are installed as top-level `scripts/*.py` because they are
meant to be invoked directly from the governed repo root.

## Truth-Surface Validation Workflow

For coordination-heavy repos, keep one config file that names the active tracker,
plan index, runtime registry, and any measured audit surface.

```bash
cp truth_surface_drift.yaml.example truth_surface_drift.yaml
python scripts/check_truth_surface_drift.py --config truth_surface_drift.yaml
python scripts/render_truth_surface_status.py --config truth_surface_drift.yaml
```

When deterministic findings are green but the authority set still feels stale,
misleading, or non-compendious, run the optional semantic review layer:

```bash
python scripts/review_truth_surface_semantic.py \
  --config truth_surface_drift.yaml \
  --output-json semantic_truth_surface_review.json
python scripts/render_truth_surface_status.py \
  --config truth_surface_drift.yaml \
  --semantic-json semantic_truth_surface_review.json
```

Use the validator to detect contradictions. Use the renderer to produce a compact
current-state summary from validator output instead of hand-maintaining status
prose.

This workflow is deterministic by design. It is the right default for hard
contradictions and machine-checkable parity. For repo-local runs, prefer a
scoped config with `scope.repo_names` so unrelated ecosystem registry drift does
not dominate the local result. Full unscoped runs are still useful for broader
global coordination review.

Consumed reservations are lineage-aware. Canonical landed contradictions should
still fail, but `historical-unlanded` records should normally render as hygiene
warnings rather than hard repo-local failures. Use
`checks.consumed_reservations_exist.historical_unlanded_severity` in
`truth_surface_drift.yaml` if a repo needs a different local posture.

The semantic review layer is optional and advisory-only. It should sit on top of
deterministic validation for semantic drift, misleading prose, and missing
cross-surface updates that exact rules cannot capture robustly.

See `truth_surface_drift.yaml.example` for the installed scaffold.

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
