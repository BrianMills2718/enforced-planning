# Getting Started with Enforced Planning

A step-by-step guide to adopting the enforced-planning framework for AI-assisted development.

## What is Enforced Planning?

Enforced planning is a collection of patterns for coordinating AI coding assistants (Claude Code, Cursor, etc.) on shared codebases. It solves problems like:

- **Context loss** - AI forgetting project conventions mid-session
- **Documentation drift** - Docs diverging from code over time
- **Unverified completions** - "Done" work that doesn't actually work
- **AI drift** - AI guessing instead of investigating, making wrong assumptions

---

## Choose Your Weight Level

Before starting, decide how much process overhead you want:

| Weight | Best For | Planning Patterns | Enforcement |
|--------|----------|-------------------|-------------|
| **minimal** | Quick experiments, spikes | None | Almost nothing |
| **light** | Prototypes, solo work | Advisory (warnings) | Warnings only |
| **medium** | Most projects (default) | Advisory + templates | Balanced |
| **heavy** | Critical/regulated projects | Required + validation | Full enforcement |

### Planning Patterns

These patterns improve planning quality and reduce AI drift. The canonical
artifact order and dependency model lives in
[`PLANNING_OPERATING_MODEL.md`](PLANNING_OPERATING_MODEL.md).

| Pattern | What It Does | When to Use |
|---------|--------------|-------------|
| [Question-Driven Planning](patterns/28_question-driven-planning.md) | Surface questions BEFORE solutions | Always (low overhead) |
| [Uncertainty Tracking](patterns/29_uncertainty-tracking.md) | Track unknowns across sessions | Medium+ projects |
| [Conceptual Modeling](patterns/27_conceptual-modeling.md) | Define "what things ARE" | Complex architectures |

**The core principle:** Don't guess, verify. Every "I believe" should become "I verified by reading X".

### Configure in meta-process.yaml

```yaml
# Choose your weight
weight: medium  # minimal | light | medium | heavy

# Fine-tune planning patterns
planning:
  question_driven_planning: advisory  # disabled | advisory | required
  uncertainty_tracking: advisory
  conceptual_modeling: disabled       # Enable for complex projects
  warn_on_unverified_claims: true     # Warn on "I believe", "might be"
  dependency_probe_policy: strict     # strict | warn | ignore
```

---

## Quick Start (30 minutes)

### Step 1: Install

```bash
# From the enforced-planning repo root, targeting your project root
./install.sh . --minimal
```

This creates:
- `meta-process.yaml` - Configuration
- `docs/plans/` - Work tracking
- `hooks/` - Git hooks
- `.claude/hooks/` - Claude Code hooks
- `scripts/` - Utility scripts

### Step 2: Configure

Edit `meta-process.yaml`:

```yaml
weight: medium  # minimal | light | medium | heavy

planning:
  question_driven_planning: advisory  # disabled | advisory | required
  uncertainty_tracking: advisory
  dependency_probe_policy: strict     # strict | warn | ignore

enforcement:
  strict_doc_coupling: false  # Start with warnings, enable later
```

### Step 3: Verify

```bash
make status    # Should show clean state
make test      # Tests should pass
```

### Step 4: Test the Workflow

```bash
# 1. Create a feature branch
git checkout -b test-setup

# 2. Make a trivial change
echo "# Test" >> README.md

# 3. Commit with convention
git add README.md
git commit -m "[Trivial] Test setup"

# 4. Clean up
git checkout main
git branch -d test-setup
```

If that worked, you're ready!

### Step 5: Optional Truth-Surface Validation (`--full` mode only)

For repos with runtime coordination, rollout trackers, or reservation state,
install with `--full` to get truth-surface tooling:

```bash
./install.sh /path/to/your/project --full
```

This installs `check_truth_surface_drift.py` and `render_truth_surface_status.py`
into `scripts/meta/`, plus a config template at `scripts/truth_surface_drift.yaml.example`.
Copy and customize the template, then run:

```bash
cp scripts/truth_surface_drift.yaml.example scripts/truth_surface_drift.yaml
python scripts/meta/check_truth_surface_drift.py --config scripts/truth_surface_drift.yaml
python scripts/meta/render_truth_surface_status.py --config scripts/truth_surface_drift.yaml
```

This gives you a generated current-state summary driven by measured surfaces
instead of hand-maintained tracker prose alone.

Or call the scripts directly from the enforced-planning repo without installing:

```bash
python ~/projects/enforced-planning/scripts/check_truth_surface_drift.py --config scripts/truth_surface_drift.yaml
```

---

## Core Concepts

| Concept | What It Is |
|---------|------------|
| **Plan** | A markdown file in `docs/plans/` describing what to build. Required for significant work. |
| **Pattern** | A reusable solution to a coordination problem. See the [Pattern Index](patterns/01_README.md). |
| **Weight** | How much process enforcement — from `minimal` (almost nothing) to `heavy` (full validation). |
| **Commit Convention** | `[Plan #N] Description` for planned work, `[Trivial] Description` for tiny changes. |

---

## First Week Adoption Path

### Day 1-2: Core Workflow

**Goal:** Get comfortable with branches and plans.

1. **Read methodology docs** (in this order):
   - [Planning Operating Model](PLANNING_OPERATING_MODEL.md) - canonical artifact dependency model
   - [CLAUDE.md Authoring](patterns/02_claude-md-authoring.md) - project context
   - [Plan Workflow](patterns/15_plan-workflow.md) - bounded work tracking
   - [Question-Driven Planning](patterns/28_question-driven-planning.md) - investigate before planning

2. **Set up your CLAUDE.md:**
   ```markdown
   # Project Name

   ## Quick Reference
   - `make test` - Run tests
   - `make check` - Run all checks

   ## Design Principles
   1. Fail loud - No silent errors
   2. Test first - Write tests before code

   ## Key Rules
   - Commit messages: `[Plan #N]` or `[Trivial]`
   ```

3. **Practice the workflow:**
   ```bash
   git checkout -b plan-1-my-feature   # Create branch
   # ... edit files ...
   git add -A && git commit -m "[Plan #1] Add feature"
   make pr-auto-check
   make pr-auto
   # if auto-merge is disabled by repo policy:
   make finish BRANCH=plan-1-my-feature PR=N
   ```

### Day 3-4: Plans

**Goal:** Track work in plan files.

1. **Read patterns:**
   - [Plan Status Validation](patterns/23_plan-status-validation.md)

2. **Create your first plan:**
   ```bash
   cp docs/plans/TEMPLATE.md docs/plans/001_my_first_plan.md
   # Edit to describe your task
   ```

   Before implementing, make sure the plan has:
   - current vs target gap framing
   - references reviewed
   - required tests declared before code starts
   - any capability/boundary notes needed for cross-project work

### Day 5-7: Git Hooks

**Goal:** Catch issues before CI.

1. **Read:** [Git Hooks](patterns/06_git-hooks.md)

2. **Install hooks:**
   ```bash
   git config core.hooksPath hooks
   ```

3. **Test hooks:**
   ```bash
   # Try a bad commit message
   git commit --allow-empty -m "bad message"
   # Should fail with: "Commit message must start with [Plan #N] or [Trivial]"
   ```

---

## Second Week: Enhanced Quality

### Enable Doc-Code Coupling

1. **Read:** [Doc-Code Coupling](patterns/10_doc-code-coupling.md)

2. **Configure mappings in `scripts/relationships.yaml`:**
   ```yaml
   couplings:
     - sources: ["src/api/*.py"]
       docs: ["docs/api.md"]
       description: "API documentation"
   ```

3. **Enable strict enforcement in meta-process.yaml:**
   ```yaml
   enforcement:
     strict_doc_coupling: true  # Soft couplings also block
   ```

### Add Mock Enforcement

1. **Read:** [Mock Enforcement](patterns/05_mock-enforcement.md)

2. **Run check:**
   ```bash
   python scripts/check_mock_usage.py
   ```

---

## Troubleshooting

### "Commit message must start with [Plan #N] or [Trivial]"

Your commit message doesn't follow the convention:

```bash
git commit -m "[Trivial] Fix typo in README"
# or
git commit -m "[Plan #1] Add user authentication"
```

### Hooks not running

```bash
# Check hook path
git config core.hooksPath
# Should be: hooks

# Fix if wrong
git config core.hooksPath hooks
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Check status | `make status` |
| Run tests | `make test` |
| Run all checks | `make check` |
| Preflight autonomous PR | `make pr-auto-check` |
| Non-interactive PR | `make pr-auto` |
| Prepare PR (manual flow) | `make pr-ready` |
| Create PR (manual flow) | `make pr` |
| Finish work | `make finish BRANCH=X PR=N` |

---

## Patterns by Adoption Stage

| Stage | Patterns | Effort |
|-------|----------|--------|
| **Week 1** | CLAUDE.md, Plans, Question-Driven Planning | Low |
| **Week 1** | Git Hooks, Commit Convention | Low |
| **Week 2** | Doc-Code Coupling, Uncertainty Tracking | Low |
| **Month 1** | Mock Enforcement, Plan Verification | Medium |
| **When needed** | ADRs, Acceptance Gates, Conceptual Modeling | Medium-High |

Start small. Add patterns when you feel the pain they solve.

### Planning Pattern Adoption

The planning patterns have minimal overhead:

1. **Question-Driven Planning** - Just use the updated plan template. Fill in "Open Questions" before "Plan".
2. **Uncertainty Tracking** - Track uncertainties in the plan's table. Update status as you resolve them.
3. **Conceptual Modeling** - Only add when AI instances repeatedly misunderstand your architecture.

---

## Advanced: Multi-CC Coordination

If you run **multiple AI instances concurrently** on the same codebase and experience conflicts, see the [Worktree Coordination Module](patterns/worktree-coordination/README.md). It provides:

- **Claims** — Prevents two instances from working on the same task
- **Worktrees** — File isolation via git worktrees
- **Inter-CC Messaging** — Async communication between instances

Most projects don't need this. Try the branch-based workflow first.
