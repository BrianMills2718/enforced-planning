# Pattern: Verification Enforcement

## Problem

Without mandatory verification:
- Plans get marked "complete" without running tests
- Integration failures accumulate undetected
- "Big bang" testing reveals many issues at once
- No evidence that verification actually happened
- AI assistants may claim completion without proof

## Solution

Require a verification script to mark plans as complete. The script:
1. Runs the plan-declared required tests as an always-blocking change gate
2. Runs the repository-wide non-E2E suite as a separately reported health check
3. If repository health is red, reruns the identical suite at the merge base in
   a detached sibling worktree and blocks only new or changed-test failures
4. Runs applicable E2E and doc-code coupling checks
5. Records both verdicts and updates status only when the change gate passes and
   repository evidence is green or baseline-degraded without regression

**Key principle:** Completion proves the bounded change and reports repository
health honestly. It does not silently pass missing evidence or make one plan
repair every unrelated pre-existing failure.

## Files

| File | Purpose |
|------|---------|
| `scripts/complete_plan.py` | Enforcement script |
| `tests/e2e/test_smoke.py` | Basic E2E verification |
| `tests/e2e/conftest.py` | Mocked LLM fixtures |
| `docs/plans/NN_*.md` | Plan files with evidence |

## Setup

1. Create the E2E test directory:
```bash
mkdir -p tests/e2e
```

2. Copy or create the verification script:
```bash
# scripts/complete_plan.py
# See implementation in this project
```

3. Create E2E smoke tests that verify basic functionality:
```python
# tests/e2e/test_smoke.py
def test_basic_functionality(mock_llm):
    """Verify core system works end-to-end."""
    # Your basic smoke test here
    pass
```

4. Update CLAUDE.md to require the script:
```markdown
### Plan Completion (MANDATORY)

> **Never manually set a plan status to Complete.**
> Always use: `python scripts/complete_plan.py --plan N`
```

## Usage

### Completing a plan

```bash
# Standard completion
python scripts/complete_plan.py --plan 35

# Dry run (check without updating)
python scripts/complete_plan.py --plan 35 --dry-run

# Skip E2E for documentation-only plans
python scripts/complete_plan.py --plan 35 --skip-e2e

# Stronger release/promotion claim: baseline debt is not accepted
python scripts/complete_plan.py --plan 35 --require-repository-green
```

### What the script does

1. **Required tests** - Runs `check_plan_tests.py --plan N`; missing/failing tests block
2. **Repository health** - Runs `pytest tests/ --ignore=tests/e2e/` with JUnit evidence
3. **Baseline comparison** - On failure, repeats step 2 at the merge base in a
   same-layout sibling worktree
4. **Regression decision** - Blocks current-only failures and baseline failures
   whose test file changed
5. **E2E/doc coupling** - Preserves the plan's applicable blocking checks
6. **Evidence/status** - Records `green` or `baseline_degraded`; unavailable
   comparison evidence blocks

### Evidence format

After completion, plan files include:

```markdown
**Status:** ✅ Complete
**Verified:** 2026-01-12T10:30:00Z
**Verification Evidence:**
```yaml
completed_by: scripts/complete_plan.py
timestamp: 2026-01-12T10:30:00Z
completion_scope: scoped
tests:
  required: All required tests pass!
  repository_non_e2e: 145 passed, 0 skipped, 2 failed
  e2e_smoke: PASSED (8.2s)
  doc_coupling: passed
repository_health:
  status: baseline_degraded
  evidence: docs/evidence/plan35_repository_health.json
commit: a9ba628
```
```

## Customization

### Adding more verification steps

Edit `complete_plan.py` to add checks:

```python
def run_custom_check(project_root: Path) -> tuple[bool, str]:
    """Add your custom verification."""
    result = subprocess.run(["your-command"], ...)
    return result.returncode == 0, "summary"
```

### Plan-specific tests

Plans can define required tests in their `## Required Tests` section. The `check_plan_tests.py` script validates these.

### Skipping E2E for specific plan types

For documentation-only or process plans:
```bash
python scripts/complete_plan.py --plan N --skip-e2e
```

## Limitations

- **Not a substitute for thorough testing** - Smoke tests catch crashes, not subtle bugs
- **Requires test infrastructure** - You need working tests first
- **Pytest-specific comparison** - Other runners need a machine-readable result adapter
- **Identity is not root cause** - A same-named failing test can change cause; changed
  test files therefore block, and required-test scope remains important
- **Degraded runs cost more** - A red current suite requires a second merge-base run
- **Can be bypassed** - Determined users can edit files manually (git history shows this)
- **Doesn't verify correctness** - Only verifies that tests pass, not that implementation is right

## Integration with Other Patterns

| Pattern | Integration |
|---------|-------------|
| Plan Workflow | Verification is the final step |
| Claim System | Release claim only after verification |
| Git Hooks | Could add pre-commit check for unverified completions |
| Doc-Code Coupling | Verification includes coupling check |

## Lessons Learned (Plan #41)

This pattern had enforcement gaps that allowed unverified work through. Documented here for future reference.

### Gap 1: Test Parser Only Handled Tables

**Problem:** `check_plan_tests.py` only parsed markdown table format:
```markdown
| Test File | Test Function | Description |
|-----------|---------------|-------------|
| `tests/foo.py` | `test_bar` | Does X |
```

But Claude instances often wrote bullet format:
```markdown
- `tests/foo.py::test_bar`
```

**Result:** Tests defined in bullets were invisible to CI. Plan #40 had 6 required tests that were never validated.

**Fix:** Updated parser to handle both table and bullet formats (Plan #41).

### Gap 2: No CI Enforcement of complete_plan.py

**Problem:** The script was documented as "mandatory" but nothing enforced it:
- PRs could merge without running the script
- Plan status could stay "In Progress" after implementation merged
- No post-merge check verified evidence existed

**Result:** Plan #40 was merged without ever running `complete_plan.py`.

**Fix:** Added CI job to check for verification evidence (Plan #41).

### Gap 3: "No Tests Defined" Passed CI

**Problem:** When a plan had no parseable tests:
- CI reported "No test requirements defined"
- This was treated as **pass**, not fail
- Plans without proper test sections slipped through

**Fix:** CI now warns on plans with no tests. PRs referencing such plans require explicit acknowledgment.

### Key Insight

Process compliance is only as good as automated enforcement. Documented requirements without tooling support will be violated—not maliciously, but because AI instances vary in format and sessions end mid-workflow.

**Enforcement must be:**
- **Format-agnostic** - Parse what's written, not what you wish was written
- **Positive verification** - Require evidence, not absence of failure
- **Defense in depth** - Multiple checks, not single points of failure

## Origin

Emerged from agent_ecology after multiple "complete" plans were found to have failing tests. The cost of late integration testing exceeded the overhead of mandatory verification.
