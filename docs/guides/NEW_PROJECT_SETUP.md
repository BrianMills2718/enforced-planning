# New Project Setup Guide

**Goal:** Go from zero to your first governed commit in 15 minutes.

> **Tool requirement:** Claude Code is required for AI enforcement hooks. Git and Python
> 3.9+ are required for all modes.

---

## 1. Prerequisites

| Requirement | Version | Check |
|------------|---------|-------|
| Git | ≥ 2.30 | `git --version` |
| Python | ≥ 3.9 | `python3 --version` |
| Claude Code | any | `claude --version` |
| pydantic | ≥ 2.0 | `pip show pydantic` |
| pyyaml | any | `pip show pyyaml` |

Install Python deps if needed:
```bash
pip install pydantic pyyaml
```

---

## 2. Install

```bash
# Clone the framework (or use it as a dependency)
git clone git@github.com:BrianMills2718/enforced-planning.git ~/enforced-planning

# Go to your project root
cd /path/to/your/project

# Install in minimal mode (recommended starting point)
~/enforced-planning/install.sh . --minimal

# OR install everything including acceptance gates and worktree coordination
~/enforced-planning/install.sh . --full
```

**What `--minimal` installs:**
- `meta-process.yaml` — your configuration file
- `docs/plans/CLAUDE.md` — plan index template
- `hooks/commit-msg` — commit prefix validation (git hook)
- `hooks/pre-commit` — doc-coupling and plan checks (git hook)
- `.claude/hooks/` — read-gating enforcement (Claude Code hooks)
- `scripts/meta/` — utility scripts

**What `--full` adds:**
- `acceptance_gates/` — acceptance criteria YAML templates
- `docs/adr/` — architecture decision record template
- `scripts/meta/worktree-coordination/` — multi-agent worktree scripts

### Install git hooks

```bash
# Symlink the hooks (or copy them)
ln -sf "$(pwd)/hooks/commit-msg" .git/hooks/commit-msg
ln -sf "$(pwd)/hooks/pre-commit" .git/hooks/pre-commit
chmod +x .git/hooks/commit-msg .git/hooks/pre-commit
```

---

## 3. Verify

```bash
# Test that the plan check works
python scripts/meta/check_plan_tests.py . --list

# Test that locked coupling check works
python scripts/meta/check_locked_couplings.py .

# Make a test commit (should pass with [Trivial] prefix)
echo "# test" >> /tmp/test_file_delete_me.md
git add /tmp/test_file_delete_me.md 2>/dev/null || true
git commit -m "[Trivial] test hook setup" --allow-empty
# If this fails with "invalid prefix", the commit-msg hook is working correctly
# and your meta-process.yaml needs configuring (see next step)
```

---

## 4. Configure

Edit `meta-process.yaml` in your project root. The keys that matter most for initial setup:

| Key | Default | What it does | Functional? |
|-----|---------|-------------|-------------|
| `plans.plans_dir` | `docs/plans` | Where plan files live | ✅ Yes |
| `plans.require_tests` | `true` | Require "Required Tests" section | ✅ Yes (check_plan_tests.py) |
| `commits.require_prefix` | `true` | Enforce `[Plan #N]`/`[Trivial]` prefix | ✅ Yes (commit-msg hook) |
| `commits.valid_prefixes` | see file | Regex patterns for valid prefixes | ✅ Yes (commit-msg hook) |
| `quality.dead_code.enabled` | `false` | Vulture dead-code scan | ✅ Yes (check_dead_code.py) |
| `quality.dead_code.strict` | `false` | Block vs warn on dead code | ✅ Yes |
| `plans.trivial_threshold_lines` | `20` | Reference for what "trivial" means | 📋 Planned |
| `planning.question_driven_planning` | `advisory` | Investigation enforcement | 📋 Planned |
| `planning.uncertainty_tracking` | `advisory` | Open question tracking | 📋 Planned |
| `capability_ownership.*` | `false` | Capability registry enforcement | 📋 Planned |
| `messaging.*` | `false` | Multi-agent inbox coordination | 📋 Planned |

> **📋 Planned** = key exists in config file but no script reads it yet. Setting it has no effect.

**Minimum viable config** (what you actually need):
```yaml
meta_process:
  version: "1.0"
  plans:
    enabled: true
    plans_dir: "docs/plans"
  commits:
    require_prefix: true
    valid_prefixes:
      - "\\[Plan #\\d+\\]"
      - "\\[Trivial\\]"
```

---

## 5. Your First Plan

```bash
# Create your first plan from template
cp ~/enforced-planning/templates/plan.md.template docs/plans/01_my-first-feature.md

# Edit the plan
vim docs/plans/01_my-first-feature.md
# Fill in: Gap, Target, Acceptance Criteria, Required Tests, Files Affected

# Create a branch
git checkout -b plan-1-my-first-feature

# Do your work...

# Commit with plan prefix
git add src/my_feature.py tests/test_my_feature.py
git commit -m "[Plan #1] implement my first feature"
```

**Commit prefix rules:**
- `[Plan #N]` — requires an existing plan file with that number
- `[Trivial]` — for tiny changes (≤ 20 lines, no src/, no new APIs)
- `[Unplanned]` — emergency escape hatch; CI may warn

---

## 6. Common Errors

### "Invalid commit prefix"

```
ERROR: Commit message must start with [Plan #N], [Trivial], or [Unplanned].
```

**Fix:** Add the prefix. Check `meta-process.yaml` `commits.valid_prefixes` if you
want custom prefixes.

### "Locked coupling violation"

```
ERROR: src/core.py is in a locked coupling. docs/architecture.md must also be staged.
```

**Fix:** Stage the coupled doc along with your source change:
```bash
git add docs/architecture.md
git commit -m "[Plan #1] update core + doc"
```

### "Plan #N not found"

```
ERROR: [Plan #5] referenced in commit but docs/plans/05_*.md not found
```

**Fix:** Create the plan file first, or use `[Trivial]` if the change is genuinely minor.

### "Required Tests section missing"

```
WARNING: Plan #3 has no Required Tests section
```

**Fix:** Add a `## Required Tests` section to your plan file listing what tests cover this plan.

### "pyyaml not found"

**Fix:** `pip install pyyaml`

---

## Full Config Reference

See [`docs/reference/CONFIG_REFERENCE.md`](../reference/CONFIG_REFERENCE.md) for
the complete table of every config key, which script reads it, and the default
behavior when absent.
