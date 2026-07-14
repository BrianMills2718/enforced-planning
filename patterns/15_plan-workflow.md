# Pattern: Plan Workflow

## Problem

Work happens without tracking. AI assistants implement features without:
- Recording what changed
- Linking to requirements
- Following consistent structure
- Ensuring tests exist before code starts
- Distinguishing predictable engineering work from exploratory work where the
  running system must reveal the right value or shape

Result: orphan code, undocumented features, missed requirements.

## Solution

1. Every significant change has a "plan" document
2. Plans define: modality, gap (current vs target), changes, tests/readouts,
   verification
3. Status tracked in plan file AND index
4. Commit messages link to plans: `[Plan #N]`
5. TDD: define tests in plan before implementing when the slice is deductive;
   define instruments and readouts before exploring when the slice is exploratory
6. Plans distinguish **repo-local references reviewed** from the broader
   **research basis for the slice**
7. Cross-project plans declare a **Capabilities** section when they create or
   modify callable surfaces other projects use
8. This pattern is one layer inside the canonical operating model in
   `PLANNING_OPERATING_MODEL.md`; it does not replace investigation, gap
   analysis, capability/boundary definition, or journey notebooks where those
   are required
9. Plans assign checks to boundary, increment, or terminal verification lanes
   and declare a gate-time budget. Broad terminal evidence is not rerun at every
   deterministic intermediate checkpoint.

## Modality Diagnosis Rule

Before writing the plan body, classify the work:

- **Deductive / plan-first:** correctness and failure modes are knowable before
  implementation. Pre-make decisions, write contracts, and define tests.
- **Exploratory / ladder:** behavior is emergent or parameter values would be
  guesses. Build the cheapest instrument, define the readout, and include a way
  to step from aggregate signal down to concrete cases.
- **Hybrid:** split the work. Specify and gate the predictable architecture or
  contracts; instrument the unknown behavior. Do not fake precision on open
  surfaces.

The plan requirement still applies in exploratory mode. The plan states what
instrument will be built, what observable readout will guide the next decision,
and when the exploratory surface can be promoted back into specified + gated
deductive mode.

## Files

| File | Purpose |
|------|---------|
| `docs/plans/CLAUDE.md` | Master index of all plans |
| `docs/plans/NN_name.md` | Individual plan files |
| `scripts/check_plan_tests.py` | Verify plan test requirements |
| `scripts/check_plan_capabilities.py` | Verify cross-project plans declare capabilities |
| `scripts/sync_plan_status.py` | Keep plan/index in sync |

## Setup

### 1. Create the plans directory

```bash
mkdir -p docs/plans
```

### 2. Create the master index

```markdown
<!-- docs/plans/CLAUDE.md -->
# Implementation Plans

| # | Gap | Priority | Status | Blocks |
|---|-----|----------|--------|--------|
| 1 | Feature A (`01_feature_a.md`) | High | 📋 Planned | #2 |
| 2 | Feature B (`02_feature_b.md`) | Medium | ⏸️ Blocked | - |

## Status Key

| Status | Meaning |
|--------|---------|
| 📋 Planned | Ready to implement |
| 🚧 In Progress | Being worked on |
| ⏸️ Blocked | Waiting on dependency |
| ❌ Needs Plan | Gap identified, no plan yet |
| ✅ Complete | Implemented and verified |
```

### 3. Create a plan template

```markdown
<!-- docs/plans/NN_name.md -->
# Gap N: [Name]

**Status:** 📋 Planned
**Priority:** High | Medium | Low
**Blocked By:** None | #X, #Y
**Blocks:** None | #A, #B

---

## Gap

**Current:** What exists now

**Target:** What we want

---

## Modality

**Mode:** Deductive | Exploratory | Hybrid

**Rationale:** Why this mode fits the work.

**Protocol:** For deductive parts, list the contracts/tests that can be
specified before implementation. For exploratory parts, list the simplest
defensible guess, the instrument to build, the readout, and the step-down path
to concrete cases. For hybrid work, partition both.

---

## References Reviewed

> **REQUIRED:** Cite specific code/docs reviewed before planning.
> Forces exploration before coding - prevents guessing.

- `src/world/executor.py:45-89` - existing action handling
- `src/world/ledger.py:120-150` - balance update logic
- `docs/architecture/current/actions.md` - action design
- `CLAUDE.md` - project conventions

---

## Research Basis For This Slice

> **RECOMMENDED for all plans; REQUIRED for design, cross-project, or
> externally-informed work.**
> Use this section for dated investigations, topic syntheses, external sources,
> production references, or an explicit research skip statement.

- `investigations/cross-project/2026-04-04-example.md` - compared existing options
- `research/orchestration/SYNTHESIS.md` - reusable current recommendation
- `https://example.com/paper` - external prior art

If no additional research beyond repo-local references was needed, write:
`No additional research beyond References Reviewed.`

---

## Capabilities

> **REQUIRED if this plan creates or modifies callable functions that other
> projects use.**

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|-----------|-------------|---------------|----------|-------------|-----------|
| `investigate(question)` | `str` | `InvestigationMemo` | research_v3 | grounded-research, onto-canon6 | expensive |

> Skip this section for internal-only changes that do not create callable
> capabilities.

---

## Files Affected

> **REQUIRED:** Declare upfront what files will be touched.
> Creates traceability and enables claim-based file locking.
> Note: Don't use backticks around paths - the parser needs plain text.

- src/module.py (modify)
- src/new_feature.py (create)
- tests/test_feature.py (create)
- config/config.yaml (modify)

---

## Plan

### Steps

1. Create X
2. Modify Y
3. Add tests
4. Update docs

---

## Required Tests

For exploratory work, replace or supplement tests with the readout/instrument
checks that prove the exploration is agent-drivable and inspectable.

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_module.py` | `test_basic_function` | Happy path |
| `tests/test_module.py` | `test_error_handling` | Error cases |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_related.py` | Integration unchanged |

---

## Verification

**Current stage:** PoC | Pilot | Product | Production
**Next decision:** [decision]
**Gate-time budget:** [time or number of gate passes]
**Stopping rule:** [condition]

| Lane | Trigger | Checks / Evidence | Evidence Reuse Key | Decision Protected |
|------|---------|-------------------|--------------------|--------------------|
| Boundary | Before irreversible/shared/one-use action, if any | Exact action-specific checks | commit + dependency/config identity | [decision] |
| Increment | Before intermediate commit | Affected tests and focused checks | commit + dependency/config/command identity | [decision] |
| Terminal | Closeout, merge, release, or works/done claim | Full relevant suite and evidence reconciliation | commit + dependency/config/command identity | [decision] |

- [ ] Any declared boundary gate passed immediately before its protected action
- [ ] Increment gate passed for the affected surface
- [ ] Exploratory readouts/instruments were exercised, if applicable
- [ ] Terminal gate passed before closeout or a works/done claim
- [ ] Reused evidence matches its declared reuse key
- [ ] Docs updated
- [ ] If this plan deleted files/classes: checked for orphaned references (imports, iterations, tests)

---

## Notes

[Design decisions, alternatives considered]
```

### 4. Create the plan tests script

```python
#!/usr/bin/env python3
"""Check plan test requirements."""

import re
import sys
import subprocess
from pathlib import Path

def get_plan_tests(plan_path: Path) -> list[tuple[str, str]]:
    """Extract required tests from plan file."""
    content = plan_path.read_text()
    tests = []

    # Find tests in "## Required Tests" section
    in_tests = False
    for line in content.split("\n"):
        if "## Required Tests" in line:
            in_tests = True
        elif line.startswith("## ") and in_tests:
            in_tests = False
        elif in_tests and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[1].startswith("tests/"):
                tests.append((parts[1], parts[2]))

    return tests

def run_tests(tests: list[tuple[str, str]]) -> bool:
    """Run specified tests."""
    all_passed = True
    for test_file, test_func in tests:
        target = f"{test_file}::{test_func}" if test_func else test_file
        result = subprocess.run(
            ["pytest", target, "-v"],
            capture_output=True
        )
        if result.returncode != 0:
            all_passed = False
    return all_passed

def main():
    plans_dir = Path("docs/plans")

    if "--list" in sys.argv:
        for plan in sorted(plans_dir.glob("[0-9]*.md")):
            tests = get_plan_tests(plan)
            print(f"{plan.name}: {len(tests)} required tests")
        return 0

    if "--plan" in sys.argv:
        idx = sys.argv.index("--plan")
        plan_num = sys.argv[idx + 1]
        plan_files = list(plans_dir.glob(f"{plan_num.zfill(2)}*.md"))
        if not plan_files:
            print(f"Plan {plan_num} not found")
            return 1

        tests = get_plan_tests(plan_files[0])
        if "--tdd" in sys.argv:
            print("Tests to write:")
            for test_file, test_func in tests:
                print(f"  {test_file}::{test_func}")
            return 0

        if not run_tests(tests):
            return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
```

### 5. Add status sync script

```python
#!/usr/bin/env python3
"""Sync plan status between plan files and index."""

import re
import sys
from pathlib import Path

def get_plan_status(plan_path: Path) -> str:
    """Extract status from plan file."""
    content = plan_path.read_text()
    match = re.search(r'\*\*Status:\*\*\s*(.+)', content)
    return match.group(1).strip() if match else "Unknown"

def main():
    plans_dir = Path("docs/plans")
    index_path = plans_dir / "CLAUDE.md"

    mismatches = []
    for plan in sorted(plans_dir.glob("[0-9]*.md")):
        status = get_plan_status(plan)
        # Check against index...
        # (simplified - real script parses index table)

    if "--check" in sys.argv and mismatches:
        print("Status mismatches found:")
        for m in mismatches:
            print(f"  {m}")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
```

## Usage

### Creating a new plan

```bash
# 1. Create plan file
cp docs/plans/template.md docs/plans/33_my_feature.md

# 2. Edit with gap description, steps, required tests
vim docs/plans/33_my_feature.md

# 3. Add to index
vim docs/plans/CLAUDE.md
```

### Implementing a plan (4-step workflow)

```bash
# 1. START - Create feature branch
git checkout -b plan-33-my-feature

# 2. IMPLEMENT - TDD approach
python scripts/check_plan_tests.py --plan 33 --tdd  # See what tests to write
# Write tests first (they fail), then implement until they pass
# Update plan status: **Status:** 🚧 In Progress

# 3. VERIFY - All CI checks locally
make check                 # Runs: test, mypy, lint, doc-coupling

# 4. SHIP - PR + merge + cleanup
make pr-ready && make pr   # Rebase, push, create PR
# Wait for CI to pass, then:
make finish BRANCH=plan-33-my-feature PR=N
```

### Checking plan status

```bash
# List all plans with test counts
python scripts/check_plan_tests.py --list

# Check specific plan's tests
python scripts/check_plan_tests.py --plan 33

# Check status sync
python scripts/sync_plan_status.py --check
```

## Customization

### Plan numbering

```bash
# Option 1: Sequential (01, 02, 03...)
docs/plans/01_auth.md

# Option 2: Categorical (1xx for core, 2xx for UI...)
docs/plans/101_auth.md
docs/plans/201_dashboard.md

# Option 3: Date-based
docs/plans/2024-01-auth.md
```

### Status symbols

```markdown
| Status | Meaning |
|--------|---------|
| ⬜ Backlog | Not yet planned |
| 📋 Planned | Ready to start |
| 🚧 Building | In progress |
| 🔍 Review | PR open |
| ✅ Done | Merged |
| ❌ Won't Do | Cancelled |
```

### Add priority labels

```markdown
**Priority:** 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low
```

### Integrate with GitHub Issues

```markdown
# Gap N: [Name]

**Status:** 📋 Planned
**GitHub Issue:** #123
**PR:** (pending)
```

## Trivial Exemption

Not everything needs a plan. Use `[Trivial]` prefix for tiny changes:

```bash
git commit -m "[Trivial] Fix typo in README"
git commit -m "[Trivial] Update copyright year"
git commit -m "[Trivial] Fix formatting in config"
```

**Trivial criteria — ALL of the following must be true:**

1. **≤ 20 lines changed** (diff stat: `git diff --stat HEAD` line count, not file count)
2. **No changes to production code directories** (`src/`, `lib/`, any directory your project considers production code)
3. **No new public APIs, schemas, or behavioral changes** — adding a function, changing a return type, or altering observable behavior requires a plan even if < 20 lines
4. **No new files created** — new files almost always represent new capability; use a plan
5. **Reviewer judgment confirms genuinely minor** — when in doubt, use `[Plan #N]`

**Edge cases:**
- Renaming a variable across 25 files = NOT trivial (behavioral risk, needs plan)
- Fixing a typo in 1 comment = trivial
- Adding a `# type: ignore` = NOT trivial (hiding a type error may be a real bug)
- Updating a version number in a comment = trivial

**CI validates trivial commits** — if a `[Trivial]` commit exceeds limits, CI warns.

**Why this exists:** Plans add value for significant work but create friction for tiny fixes. The 80/20 principle: most value comes from planning significant work, not typo fixes.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Test requirement format | **Plain English + pytest path** | Both: description for humans, path for automation |
| Trivial exemption | **`[Trivial]` prefix** | Reduces friction; CI validates size limits |
| Files Affected section | **Required** | Forces planning, creates traceability, enables file-level claims |
| References Reviewed section | **Required** | Forces exploration before coding, prevents CC guessing |
| Research Basis For This Slice | **Context-dependent** | Makes reused research explicit without forcing heavy process onto every trivial local plan |

## Limitations

- **Manual status updates** - Must remember to update both plan file and index.
- **No enforcement** - Plans are advisory unless combined with hooks/CI.
- **Stale plans** - Old plans may reference outdated code/structure.
- **Research strictness is contextual** - not every trivial local plan needs
  external or topic-level research, but the plan should say so explicitly

## Best Practices

1. **Use `[Trivial]` for tiny changes** - Typos, formatting, comments
2. **Use `[Unplanned]` sparingly** - CI blocks these; reserved for emergencies
3. **Keep plans small** - One feature per plan, not epics
4. **Archive completed plans** - Move to external archive to keep repo lean for AI navigation
5. **Link PRs to plans** - PR description should reference plan

## Archival Policy

Completed and historical documentation should be moved out of the repo to an
external archive. This prevents AI coding assistants (Claude Code, etc.) from
wasting context on irrelevant material during grep/glob/exploration.

**What to archive:**
- Completed plan files (after merge)
- Historical design discussions and research notes
- Deprecated documentation (old handbooks, superseded specs)

**What stays in repo:**
- Active plans (planned, in-progress, deferred)
- Current architecture docs (`docs/architecture/current/`)
- ADRs (immutable historical record, actively referenced)
- Glossary, security docs, design clarifications (living documents)
- Conceptual model (`docs/CONCEPTUAL_MODEL.yaml`)

**Archive location:** External directory outside the git repo (e.g.,
`/path/to/archive/project/docs/`). Content is preserved but doesn't
pollute searches or exploration.

**Principle:** If a file is only useful for historical reference and not
for current development decisions, it belongs in the external archive.

## See Also

- [Git hooks pattern](06_git-hooks.md) - Enforces plan references in commits
- [PR coordination pattern](worktree-coordination/21_pr-coordination.md) - Auto-updates plan status on merge
- [Claim system pattern](worktree-coordination/18_claim-system.md) - Tracks who's working on which plan
- [Question-Driven Planning](28_question-driven-planning.md) - The principle behind "References Reviewed"
- [Topic Research Synthesis](43_topic-research-synthesis.md) - How reusable research feeds ADRs and plans
- [Uncertainty Tracking](29_uncertainty-tracking.md) - Track open questions in plans
- [Gap Analysis](30_gap-analysis.md) - Systematic gap identification that informs plan creation
