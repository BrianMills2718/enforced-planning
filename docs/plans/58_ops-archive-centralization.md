# Plan #58: Ops Archive Centralization

**Status:** ✅ Complete
**Type:** implementation
**Priority:** Medium
**phase_ref:** "Phase 9"
**goal_ref:** "governance-archive-cleanup"
**adrs_referenced:** []
**research_citations:** []
**Blocked By:** None
**Blocks:** None

---

## Gap

**Current:** `docs/ops/archive/` holds nine completed sprint/TODO artifacts
inside the active repo. That solved root `docs/ops/` clutter, but still leaves
retired material in normal agent search and trips ecosystem policy reporting
for in-repo archive directories.

**Target:** Completed ops sprint artifacts live in the central archive under
`~/archive/enforced-planning/`, active repo references point to the archive log
or current planning surface, and the repo no longer needs a terminology-linter
exception for `docs/ops/archive/`.

**Why:** Historical sprint records should be recoverable without remaining part
of the active authority surface. Keeping retired trackers in the repo makes
agents more likely to read stale operational state as current guidance.

---

## References Reviewed

- `CLAUDE.md` - continuous execution and sanctioned-worktree requirements.
- `docs/plans/CLAUDE.md` - numbered implementation plan index.
- `docs/plans/TEMPLATE.md` - current plan document contract.
- `docs/ops/archive/*.md` - archive candidates and live-claim check.
- `docs/ops/SPRINT_2026_04_03_ALL_ISSUES.md` - prior cleanup acceptance note.
- `docs/ops/SPRINT_2026_04_03_AUDIT_FOLLOWUP.md` - stale archive pointer.
- `ISSUES.md` - resolved clutter issue that mentions the in-repo archive.
- `scripts/check_terminology.py` - linter exclusion for the in-repo archive.

---

## Research Basis For This Slice

No additional research beyond repo-local references was needed.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Archive disposition | Deductive / plan-first | The candidates are closed sprint/TODO documents already marked as archived historical artifacts. | Check active references and live claims before moving. |
| Reference cleanup | Deductive / plan-first | Known references are exact strings and can be updated directly. | Replace active repo pointers with the central archive log or current planning surface. |
| Verification | Deductive / plan-first | The repo has deterministic plan/status/self-test checks. | Run focused checks plus framework self-test before landing. |

**Exploratory readout:** Not applicable; this is a deterministic docs hygiene
slice.

**Step-down path:** If a check fails, inspect the concrete failing path or
plan-index row, then update only the active reference or status surface causing
the failure.

---

## Files Affected

- `docs/plans/58_ops-archive-centralization.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `docs/ops/SPRINT_2026_04_03_ALL_ISSUES.md` (modify)
- `docs/ops/SPRINT_2026_04_03_AUDIT_FOLLOWUP.md` (modify)
- `ISSUES.md` (modify)
- `scripts/check_terminology.py` (modify)
- `docs/ops/archive/` (move to central archive)
- `~/archive/enforced-planning/wiki/log.md` (append)

---

## Plan

### Steps

1. Add this numbered plan and index it in `docs/plans/CLAUDE.md`.
2. Replace active references to `docs/ops/archive/` with the central archive
   log/recovery path.
3. Remove `docs/ops/archive/` from terminology-linter exclusions because it
   will no longer exist in the active repo.
4. Move the nine completed sprint/TODO artifacts to
   `~/archive/enforced-planning/<timestamp>/docs/ops/archive/`.
5. Log source commit, content hashes, disposition, live-claim disposition, and
   reference updates in the central archive wiki.
6. Run focused plan/status checks and `python scripts/self_test.py`.

---

## Required Tests

### New Tests (TDD)

No new tests are needed. This slice removes historical docs and one obsolete
path exclusion without changing product behavior.

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/validate_plan.py --plan-file docs/plans/58_ops-archive-centralization.md --warn-only` | The new plan follows the repo planning contract. |
| `python scripts/sync_plan_status.py --check` | The plan index and plan files agree. |
| `python scripts/check_terminology.py --files ... --vocab-pack /home/brian/projects/project-meta/generated/vocab_pack.jsonl` | Removing the archive exclusion does not introduce terminology violations in touched files. |
| `python scripts/self_test.py` | Framework-level validation remains green. |
| `git diff --check` | The docs move and edits have no whitespace damage. |

---

## Acceptance Criteria

> Feature-level criteria:
- [x] [Evidence: test, Grade A] `docs/ops/archive/` no longer exists in the active repo.
- [x] [Evidence: test, Grade A] Live references no longer point agents at `docs/ops/archive/` as an active in-repo path.
- [x] [Evidence: observed, Grade B] Central archive log records source paths, destination, disposition, source commit, content hashes, and reference updates.
- [x] [Evidence: test, Grade A] Touched files pass the terminology linter without a `docs/ops/archive/` exclusion.

> Process criteria:
- [x] [Evidence: test, Grade A] Required plan/status checks pass.
- [x] [Evidence: test, Grade A] Framework self-test passes.
- [x] [Evidence: observed, Grade B] Verification gaps found during closeout are recorded in `ISSUES.md`.

---

## Open Questions

None. The previous archive contents are completed historical trackers with
replacement/recovery through the central archive log and current plan index.

---

## Notes

Pre-archive live-claim check found one historical "Deferred Unless Needed" note
in `TRUTH_SURFACE_PILOT_TODO.md`. Its semantic-review item is covered by later
completed semantic-review plans, and the workflow-wiring question remains
tracked as future advisory wiring in the active plan index rather than inside
the retired TODO file.

---

## Verification Results

- `find . -path './.git' -prune -o -path './worktrees' -prune -o -path '*/archive' -type d -print` - passed; no archive directories remain in this worktree.
- `rg -n --fixed-strings 'docs/ops/archive' . ...` - passed for active references; remaining occurrences are only in this Plan #58 completion record.
- `python scripts/validate_plan.py --plan-file docs/plans/58_ops-archive-centralization.md --warn-only` - passed before closeout update.
- `python scripts/sync_plan_status.py --check` - passed before closeout update.
- `python scripts/check_terminology.py --files ISSUES.md docs/ops/SPRINT_2026_04_03_ALL_ISSUES.md docs/ops/SPRINT_2026_04_03_AUDIT_FOLLOWUP.md docs/plans/58_ops-archive-centralization.md docs/plans/CLAUDE.md scripts/check_terminology.py --vocab-pack /home/brian/projects/project-meta/generated/vocab_pack.jsonl` - passed.
- `python -m py_compile scripts/check_terminology.py` - passed.
- `python scripts/self_test.py` - passed in the sanctioned worktree.
- `git diff --check` - passed.

Verification gaps:

- `python scripts/check_terminology.py --glob '**/*.md'` is blocked by a pre-existing missing default vocab pack and missing `scripts/generate_vocab_pack.py`; recorded as MP-014.
- `python scripts/check_terminology.py --glob '**/*.md' --vocab-pack /home/brian/projects/project-meta/generated/vocab_pack.jsonl` reports two pre-existing violations in `patterns/37_context-engineering.md` and `patterns/43_topic-research-synthesis.md`, outside this cleanup diff.
- `python -m pytest tests/ -q` is not green before this slice's changes: the primary checkout has 7 governed-repo audit failures, and `scripts/meta/render_agents_md.py` has a path-execution import-root bug; recorded as MP-015.
