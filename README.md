# Enforced Planning: AI-Assisted Development Framework

A portable framework for coordinating AI coding assistants on shared codebases.

> **Tool compatibility:** Currently **Claude Code only**. Hooks (`.claude/hooks/`),
> CLAUDE.md convention, and read-gating are Claude Code-specific. Patterns and git
> hooks are tool-agnostic. Cursor/Windsurf/Cline support is planned (Phase 8).

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

### Recommended: pre-commit mode

```bash
# Install using the pre-commit framework (recommended)
./install.sh /path/to/your/project --pre-commit

# Configure
vim meta-process.yaml
vim .pre-commit-config.yaml   # enable/disable hooks, pin rev to a release

# Verify
pre-commit run --all-files

# Work
git checkout -b plan-N-description
git commit -m "[Plan #1] my change"   # hooks enforce format
```

### Alternative: raw bash hooks

```bash
# Install without pre-commit (for environments where pip is unavailable)
./install.sh /path/to/your/project --minimal   # core patterns
./install.sh /path/to/your/project --full      # all patterns + worktree coordination

vim meta-process.yaml
git checkout -b plan-N-description
make pr-auto-check && make pr-auto   # ship
```

## What Is a "Governed Repo"?

A **governed repo** is any git repository that has this framework installed:

```bash
ls meta-process.yaml docs/plans/CLAUDE.md   # both present = governed
```

Specifically:
1. `meta-process.yaml` exists at the repo root (installed by `./install.sh`)
2. `docs/plans/CLAUDE.md` exists as the plan index
3. Commits use `[Plan #N]` or `[Trivial]` prefixes (enforced by commit-msg hook)

That's the minimum. The framework's scripts (dependency inference, plan registry,
coupling checks) all use `meta-process.yaml` presence to discover governed repos.

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

Authoritative operator workflow:
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`

Portable coordination now has two layers:
- root `scripts/` owns the newer claim-v2, active-work registry, and shared
  worktree-path helpers
- `scripts/worktree-coordination/` owns the optional operational helpers such
  as worktree creation, safe removal, PR finish, and messaging

> **Most projects don't need the multi-CC module.** A branch-based workflow with one AI instance at a time is simpler and works well. When you do need the module, use `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` as the day-to-day workflow doc and `patterns/worktree-coordination/README.md` as the structural reference.

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
cp templates/truth_surface_drift.yaml.example truth_surface_drift.yaml
python scripts/check_truth_surface_drift.py --config truth_surface_drift.yaml
python scripts/render_truth_surface_status.py --config truth_surface_drift.yaml
```

When deterministic findings are clean enough structurally but the authority set
still feels stale, misleading, or non-compendious, run the optional semantic
review layer:

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
`truth_surface_drift.yaml` if a repo needs a different posture.

The semantic review layer is optional and advisory-only. It sits on top of
deterministic validation for semantic drift, misleading prose, and missing
cross-surface updates that exact rules cannot capture robustly.

See `templates/truth_surface_drift.yaml.example` for the scaffold.

## Portable Coordination Surfaces

The first portable coordination wave now lives in these scripts:

- `scripts/check_coordination_claims.py` — claim-v2 schema, overlap detection,
  and claim management against `~/.claude/coordination/claims/`
- `scripts/generate_active_work_registry.py` — generated JSON/markdown registry
  from live claims
- `scripts/worktree_paths.py` — canonical repo/worktree-root resolution helpers
- `scripts/worktree-coordination/create_worktree.py` — sanctioned worktree
  creation with optional scoped write-claim enforcement

The older `scripts/worktree-coordination/check_claims.py` active-work system is
still present for legacy/module compatibility. This wave does not delete or
replace it.

Use `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` for one
operator-facing workflow description. Treat pattern docs and rollout docs as
design and migration context, not as competing primary instructions.

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
