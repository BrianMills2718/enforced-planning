# Enforced Planning Issues

Observed problems, concerns, and technical debt for the enforced-planning framework itself.

Items start as **unconfirmed** observations and get triaged through investigation into
confirmed issues, plans, or dismissed.

**Last reviewed:** 2026-03-21

---

## Status Key

| Status | Meaning | Next Step |
|--------|---------|-----------|
| `unconfirmed` | Observed, needs investigation | Investigate to confirm/dismiss |
| `monitoring` | Confirmed concern, watching for signals | Watch for trigger conditions |
| `confirmed` | Real problem, needs a fix | Create a plan |
| `planned` | Has a plan (link to plan) | Implement |
| `resolved` | Fixed | Record resolution |
| `dismissed` | Investigated, not a real problem | Record reasoning |

---

## Unconfirmed

(All items have been investigated. New observations go here.)

---

## Monitoring

### MP-018: Uncommitted changes accumulating in main

**Observed:** 2026-01-31
**Updated:** 2026-01-31 (recurrence #2)
**Status:** `monitoring`

**Recurrence #2 (2026-01-31):**

Found 3 more uncommitted files in main:
- `src/simulation/runner.py` - genesis import removal, method rename
- `tests/integration/test_component_agents.py` - test skip added
- `tests/integration/test_runner.py` - test class skip added

These appear to be incomplete genesis removal work. The genesis/ directory still exists
with 20 files, so these changes would break the build if committed. Cleaned up via
`git checkout`.

**Pattern:** Both occurrences involve genesis-related refactoring work leaking into main.
The hook (`protect-main.sh`) should block this, but somehow these edits are getting through.

**Finding (updated after investigation):**

Original report of orphaned `kernel_contracts.py` files was misleading — those files
exist properly in `worktrees/trivial-kernel-contracts-rename/` as staged renames from
`genesis_contracts.py`. That work is proceeding correctly.

However, there ARE 4 uncommitted modified files in main that shouldn't be there:
- `src/simulation/runner.py` - modified Jan 31 22:55
- `src/world/__init__.py` - modified Jan 31 22:55
- `src/world/invoke_handler.py` - modified Jan 31 22:57
- `src/world/permission_checker.py` - modified Jan 31 22:56

These look like Plan #247 work (removing genesis-related code) that was accidentally
done in main instead of the `plan-247-legacy-tick-removal` worktree.

**Deep investigation findings (2026-02-01):**

1. **Hook IS working correctly:**
   Transcript evidence from session `12c67bbd` (2026-01-22) shows the hook successfully
   blocking an edit to `src/simulation/runner.py` in main:
   ```
   "BLOCKED: Cannot edit files in main directory"
   ```
   The hook executed, blocked the edit, and Claude correctly created a worktree instead.

2. **Files have been cleaned up:**
   The 4 uncommitted files were restored via `git checkout`. Current state is clean.

3. **Root cause unclear:**
   The modifications from Jan 31 22:55-22:57 were made by an unknown mechanism.
   Given that the hook is proven to work correctly in session transcripts,
   possible causes:
   - Direct filesystem edit outside Claude Code
   - Git merge/rebase operation that introduced unstaged changes
   - Another tool editing files
   - Edge case in hook execution (timeout, script error) not captured in logs

**Resolution:**
Files have been cleaned up via `git checkout`. Main is now clean.

The hook has been proven to work correctly in both old (2.1.15, 2.1.19) and current
(2.1.29) Claude Code sessions. The Jan 31 modifications likely came from outside
Claude Code's control.

**Why monitoring (not resolved):** While the immediate issue is fixed, the root cause
of how files were modified is unclear. Monitoring to detect any future occurrences.

**Trigger:** Revisit if uncommitted files appear in main again.

**Potential improvement (if recurs):**
Add hook execution logging to `protect-main.sh`:
```bash
echo "[$(date -Iseconds)] BLOCKED: $FILE_PATH" >> .claude/hook-blocks.log
```
This would help trace future incidents without digging through session transcripts.

**Update (2026-03-21):** Hook logging is now implemented in `hook_log.py`
(commit 9d16a02). All gate decisions write structured JSONL to
`.claude/hook_log.jsonl` with session identity, context emission metadata, and
experiment stamping. The suggested improvement is effectively superseded by the
richer observability now in place. Original agent_ecology2 context may no longer
apply — monitoring continues for the general pattern in any governed repo.

---

### MP-012: No success metrics

**Observed:** 2026-01-31
**Investigated:** 2026-01-31
**Status:** `monitoring`

**Finding:** Real gap. `meta_status.py` reports operational status (active claims, open
PRs, plan progress) but nothing tracks process effectiveness: rework rate, time-to-merge,
claim conflict frequency, or whether acceptance gates catch real issues vs adding ceremony.

The framework's philosophy emphasizes "observability over control" but doesn't observe
itself. No CI effectiveness tracking, no process ROI analysis.

**Why monitoring (not confirmed):** At current scale (1-2 CC instances), process overhead
is low and problems are visible without metrics. Metrics become important when the project
scales or when multiple adopters need to compare effectiveness.

**Trigger:** Revisit when (a) 3+ CC instances run concurrently, (b) time-to-merge
exceeds 24h regularly, or (c) a second project adopts the framework.

---

### MP-014: No convention for project-specific extensions

**Observed:** 2026-01-31
**Investigated:** 2026-01-31
**Status:** `monitoring`

**Finding:** The gap is real but not currently causing problems. Project-specific
directories (`logs/`, `llm_logs/`, `dashboard-v2/`) are properly documented in architecture
docs. `src/agents/catalog.yaml` (Plan #227) works fine as an ad-hoc domain catalog —
it tracks agent lineage, versions, and genotypes without formal framework integration.

The lack of convention means no discoverability pattern, no schema validation for
project-specific catalogs, and no integration with evidence recording or gap closure.
But these aren't causing friction yet.

**Relates to:** MP-001 (identity crisis). If the framework becomes truly portable,
extension conventions become critical.

**Trigger:** Revisit when (a) another project-specific catalog or tracking structure
is created, (b) Plan #227 Phase 2 (experiments/, metrics scripts) is implemented,
or (c) a second project adopts the framework.

---

### MP-017: CONTEXT.md is optional and often forgotten

**Observed:** 2026-01-31
**Investigated:** 2026-01-31
**Status:** `monitoring`
**Source:** Traycer.ai's "Ralph" pattern

**Finding:** CONTEXT.md is systematically created by `create_worktree.sh` but zero
evidence of being updated after creation (0 commits referencing CONTEXT.md updates in
a 6-day window with 50+ commits merged). The feature is inert.

**Root causes:** (1) Advisory with no enforcement — every other practice has hooks but
CONTEXT.md has none. (2) No workflow integration — not staged in git, not included in
PR descriptions. (3) Most work completes in a single session, so session continuity
isn't needed.

**When it would help:** Multi-session work (3+ sessions on same branch), complex
explorations with decision branches, handoffs between developers. These are currently
rare.

**Fix options (when triggered):** Lighten the template to 2 sections ("What Changed &
Why" + "Open Questions"), integrate into PR workflow (`make pr` pulls from CONTEXT.md),
or add a hook that only warns on branches older than 24h.

**Trigger:** Revisit when multi-session work exceeds 20% of PRs, or when handoffs
between CC instances become common.

---

## Planned

### MP-007: Script testing gap (Plan #248 not yet ported in this repo)

**Observed:** 2026-01-31
**Investigated:** 2026-01-31
**Status:** `planned`

49 Python scripts (~17,881 lines), ~20% tested. Critical destructive scripts untested:
`cleanup_orphaned_worktrees.py`, `cleanup_claims_mess.py`, `recover.py`, `check_plan_blockers.py`.

**Update (2026-03-21):** Canonical project-meta now has 161 tests covering
audit, hook wiring, plan validation, install, subtree audit, and governance
scripts. The portable enforced-planning scripts still have lower coverage than the
project-meta-specific tooling. Original plan #248 reference is from
agent_ecology2 and is not ported.

---

### MP-015: Plan-to-diff verification (Plan #249 not yet ported in this repo)

**Observed:** 2026-01-31
**Investigated:** 2026-01-31
**Status:** `planned`
**Source:** Traycer.ai research

`parse_plan.py` parses "Files Affected" but no merge-time check compares actual diff
to declarations. Plan drift (declared files never touched) is undetected.

---

## Confirmed

(No confirmed issues at this time.)

---

## Resolved

### MP-008: install.sh — largely superseded by install_governed_repo.py

**Observed:** 2026-01-31
**Investigated:** 2026-01-31
**Status:** `resolved` (superseded)

The original `install.sh` issues (6 items, 4 fixed, 2 deferred) are largely
superseded by `scripts/install_governed_repo.py` (commit f1e9a39, Plan 09
Step 3). The new installer:

- has dry-run mode (`--json` without `--write`)
- has upgrade/drift-repair mode (idempotent re-run)
- scaffolds `relationships.yaml`, vendors validators, installs hooks, refreshes
  AGENTS.md, and re-audits in one command
- does not have the CWD, duplication, or hardcoding issues from the original

The portable `install.sh` in enforced-planning still exists for framework-only
installations but is no longer the primary governed-repo installer.

| ID | Description | Resolution | Date |
|----|-------------|------------|------|
| MP-002 | GETTING_STARTED.md config examples wrong | Updated config examples to match actual `meta-process.yaml` format (`weight:`, `hooks:`, `enforcement:`, `planning:` sections). Fixed `scripts/meta/` → `scripts/` path references. | 2026-01-31 |
| MP-004 | Phantom script/file references | Annotated all 5 phantom references as "not yet implemented" in Patterns 09, 13, 14. Added status note to Pattern 14 explaining `features.yaml` is not yet built. | 2026-01-31 |
| MP-005 | Pattern 12 unlabeled as PROPOSED in index | Added *(proposed)* annotation to Pattern 12 entry in `01_README.md` index. | 2026-01-31 |
| MP-009 | Undocumented pattern dependencies; 3 non-patterns | Added `Requires` column to pattern index in `01_README.md` with prerequisite numbers for 14 patterns. Added note identifying 3 convention/infrastructure entries (06, 11, 26). | 2026-01-31 |
| MP-016 | No implementation-time escalation convention | Added "Escalation: When Plan Meets Reality" section to Pattern 28 with 3-step process (record in CONTEXT.md, update plan, decide continue/reduce/stop). Added "Discovered Conflicts" section to CONTEXT.md template. | 2026-01-31 |
| MP-011 | Circular docs with no linear reading path | Added "Core Concepts" glossary before adoption path in GETTING_STARTED.md. Reordered Day 1-2 reading list to follow dependency order (18 before 19). Pattern index Requires column (MP-009) addresses prerequisite visibility. | 2026-01-31 |
| MP-013 | ~30% of infrastructure unused at current scale | Added "Multi-CC only" tier to pattern index "When to Use" section, listing 5 patterns + 4 scripts to skip for solo/small setups. Added "skip for solo" note to GETTING_STARTED.md adoption stage. Features remain available but clearly marked as scale-dependent. | 2026-01-31 |
| MP-001 | Portable framework, project-specific examples | Added "Customizing for Your Project" section to README.md with find-replace table for 8 agent_ecology2-specific terms. Identified the 4 most affected patterns. Low-effort fix; medium/high-effort options (example rewrites, core/project split) remain as future work. | 2026-01-31 |
| MP-006 | Pattern 13 too large (730 lines, mixed concerns) | Trimmed to 629 lines (~14%): removed redundant problem restatement, replaced 76-line ASCII process flow with 8-line compact list, replaced 23-line CI YAML with 3-line summary, removed incomplete enterprise patterns table. YAML schema extraction to separate doc deferred as future work. | 2026-01-31 |

---

## Dismissed

| ID | Description | Why Dismissed | Date |
|----|-------------|---------------|------|
| MP-003 | Competing "single source of truth" architectures | Not competing. `relationships.yaml` (Pattern 09) is the unified source of truth for doc-code coupling, actively enforced by `check_doc_coupling.py` and `sync_governance.py`. `doc_coupling.yaml` and `governance.yaml` are deprecated (have explicit headers). Acceptance gates (`meta/acceptance_gates/*.yaml`, Patterns 13/14) serve an orthogonal purpose: feature completion verification, not doc-code relationships. The patterns describe different concerns, not contradictory architectures. | 2026-01-31 |
| MP-010 | Documentation repetition across files | Intentional audience segmentation, not accidental drift. CWD rule appears in 5 places but each serves a distinct audience: CLAUDE.md (canonical rules), UNDERSTANDING_CWD.md (deep reference), CWD_INCIDENT_LOG.md (forensic/historical), GETTING_STARTED.md (onboarding with cross-refs to deep docs), Pattern 19 (enforcement mechanism). Claims similarly follow progressive disclosure. Minor issue: GETTING_STARTED.md line 103 references `scripts/meta/check_claims.py` (wrong path, should be `scripts/check_claims.py`). | 2026-01-31 |

---

## How to Use This File

1. **Observe something off?** Add an entry under Unconfirmed with what you saw and
   what investigation would look like
2. **Investigating?** Update the entry with findings, move to appropriate status
3. **Confirmed and needs a fix?** Create a plan, link it, move to Confirmed/Planned
4. **Not actually a problem?** Move to Dismissed with reasoning
5. **Watching a concern?** Move to Monitoring with trigger conditions

This file tracks issues with the **enforced-planning framework itself**, not the
agent_ecology2 system. For system-level issues, see `docs/CONCERNS.md` and
`docs/architecture/TECH_DEBT.md`.

---

## Confirmed

### MP-026: validate_plan.py strict gap check fails on already-committed generated files
- **Status:** `confirmed`
- **Observed:** 2026-03-24
- **Description:** The plan validator's strict doc gap check requires `generated/agent_docs/README.md` and `generated/agent_docs/subtrees/**/*.md` to appear in Plan 09's "Files Affected" list. These files are committed but weren't part of Plan 09's original scope. The `.doc-coupling-acks` mechanism doesn't suppress the gap because the ack file is loaded by `check_doc_coupling.load_ack_file()` but the path matching in `validate_plan.py` (line 464-474) doesn't find matches.
- **Impact:** Cannot commit changes to Plan 09 without `--no-verify`.
- **Root cause:** The plan validator checks if required docs are "covered" by the plan's affected files list, not whether the files exist on disk. Generated files added after a plan was written are flagged as gaps.
- **Fix options:** (a) Add generated/agent_docs/ to Plan 09's affected files retroactively, (b) Fix the ack matching logic in validate_plan.py, (c) Skip gap check for Complete plans.
- **Recommendation:** Option (c) — completed plans shouldn't block new edits with stale gap checks.

### MP-027: llm_client pre-commit hook API reference check race condition
- **Status:** `confirmed`
- **Observed:** 2026-03-24
- **Description:** The llm_client pre-commit hook runs `generate_api_reference.py`, then immediately checks if the output is in sync. The hook's own regeneration creates new output that it then detects as stale. Cannot commit any changes to llm_client.
- **Impact:** All llm_client commits require `--no-verify`.
- **Location:** llm_client `.git/hooks/pre-commit` or equivalent hook config.
- **Fix:** The hook should either (a) stage its own regenerated output before checking, or (b) skip the check when it just regenerated.
