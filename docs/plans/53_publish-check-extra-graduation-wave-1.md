# Plan #53: Publish-Check-Extra Graduation Wave 1

**Status:** Complete
**Type:** implementation
**Priority:** High
**phase_ref:** "Phase 9"
**goal_ref:** "fleet-adoption"
**adrs_referenced:** ["ADR-0010"]
**Blocked By:** #52
**Blocks:** Phase 9 stronger repo-local publish enforcement across governed repos

---

## Gap

**Current:** The shared governed publish path now enforces `push-check`, `dead-code`, and `dead-code-validate` across the governed fleet. That is enough to make dead-code governance and branch-publish discipline real, but it is intentionally weaker than each repo's full `make check`. Repo-specific `publish-check-extra` is available as an opt-in extension, yet no governed repo has been truthfully graduated to it.

**Target:** Governed repos whose real `make check` baseline is already green, or can be made green by a bounded truthful repair, add `publish-check-extra` so publish is blocked on the repo's own full quality gate in addition to the shared governance contract. Repos with broad historical debt are explicitly documented and deferred.

**Why:** Instructions alone do not enforce quality. The publish path has to encode the real contract. But a repo should only inherit stricter publish blocking when the repo's own `make check` is trustworthy; otherwise the gate becomes noisy process theater instead of an accurate signal.

---

## References Reviewed

- `docs/plans/52_coordination-publish-discipline-and-reviewed-dead-code-rollout.md` - completed publish-discipline and reviewed dead-code rollout
- `docs/plans/CLAUDE.md` - current plan index and status surface
- `ROADMAP.md` - Phase 9 fleet-adoption framing
- `templates/Makefile.publish.block.template` - shared publish contract with optional `publish-check-extra`
- `hooks/git/pre-push` - enforced publish entrypoint
- `investigations/enforced-planning/2026-04-12-publish-check-extra-graduation-baseline-assessment.md` - repo-by-repo blocker classification
- `agentic_scaffolding/Makefile` - current `check` target fails on stale `mypy src`
- `prompt_eval/Makefile` and `prompt_eval/pyproject.toml` - current `check` / mypy import-path baseline
- `research_v3/Makefile` and `research_v3/pyproject.toml` - current test/bootstrap baseline
- `llm_client/Makefile` and `llm_client/pyproject.toml` - current broad lint baseline
- Memory context: `agent-memory recall 'active decisions' --project enforced-planning` — 0 findings

---

## Research Basis For This Slice

- `investigations/enforced-planning/2026-04-12-publish-check-extra-graduation-baseline-assessment.md` - assessed real blocker types and defined the promotion rule

---

## Multi-Repo Coordination

| Repo | Files Modified | Merge Strategy |
|------|---------------|----------------|
| `enforced-planning` | `docs/plans/53_publish-check-extra-graduation-wave-1.md`, `docs/plans/CLAUDE.md`, `ROADMAP.md` | Merge first |
| `agentic_scaffolding` | `Makefile`, repo-local docs if coupling checks require them | Wave 1 first repo |
| `prompt_eval` | `Makefile`, repo-local config/docs if needed for truthful `make check` | Wave 1 second repo |
| `research_v3` | `Makefile`, repo-local bootstrap/config only if dependency repair is deterministic | Optional Wave 1 follow-on |
| `llm_client` | none in Wave 1 unless the baseline assessment is overturned by evidence | Defer by default |

**Coordination notes:** Each consumer repo gets its own claimed worktree branch. Do not modify shared default branches. `research_v3` and `llm_client` are not entitled to stricter gating unless the blocker class changes under investigation.

**Write-claim footprint:** `enforced-planning/docs/plans/53_publish-check-extra-graduation-wave-1.md`, `enforced-planning/docs/plans/CLAUDE.md`, `enforced-planning/ROADMAP.md`, plus one repo-local branch per graduated repo.

---

## Files Affected

- `docs/plans/52_coordination-publish-discipline-and-reviewed-dead-code-rollout.md` (modify)
- `docs/plans/53_publish-check-extra-graduation-wave-1.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `ROADMAP.md` (modify)
- `investigations/enforced-planning/2026-04-12-publish-check-extra-graduation-baseline-assessment.md` (create)
- `agentic_scaffolding/Makefile` (modify)
- `prompt_eval/Makefile` (modify)
- `prompt_eval/pyproject.toml` or repo-local bootstrap/docs if needed (modify, only if required)
- `research_v3/Makefile` or repo-local bootstrap/docs if needed (modify only if deterministic environment repair is proven)

---

## Plan

### Steps

1. Freeze the planning truth surfaces.
   - Mark Plan #52 complete.
   - Add Plan #53 to the plan index.
   - Update `ROADMAP.md` so Phase 9 distinguishes the shared publish contract from repo-specific gate graduation.
2. Graduate `agentic_scaffolding`.
   - Repair the stale `make check` path so the repo's existing quality gate is truthful.
   - Add `publish-check-extra` that runs `make check`.
   - Verify `make check`, `make publish-check`, and `git push` through the enforced hook.
3. Graduate `prompt_eval` if the blocker is bounded.
   - Make the repo's mypy/import baseline truthful without weakening the gate.
   - Add `publish-check-extra` that runs `make check`.
   - Verify `make check`, `make publish-check`, and `git push`.
4. Re-assess `research_v3`.
   - Only proceed if the missing dependency problem is a deterministic repo-local bootstrap repair.
   - If not, document the blocker and leave the shared minimum gate in place.
5. Defer `llm_client` unless the broad lint-debt diagnosis is overturned.
   - Record the defer reason explicitly.
   - Do not add `publish-check-extra` while `make check` still represents a large unrelated cleanup backlog.

---

## Required Tests

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/check_markdown_links.py ROADMAP.md docs/plans/52_coordination-publish-discipline-and-reviewed-dead-code-rollout.md docs/plans/53_publish-check-extra-graduation-wave-1.md docs/plans/CLAUDE.md` | Plan/doc surfaces remain valid |
| `python scripts/self_test.py --links --docs` | Shared doc/link validation stays green |
| `make check` in each graduated repo | Repo-local quality gate is truthful |
| `make publish-check` in each graduated repo | Shared + repo-specific publish contract passes |
| `git push` from each graduated repo branch | Hook-enforced publish path works end-to-end |

---

## Acceptance Criteria

- [x] Plan #52 is marked complete in the plan surface
- [x] Plan #53 exists and defines the repo-graduation rule, order, and defer policy
- [x] `ROADMAP.md` Phase 9 distinguishes the shared minimum publish contract from repo-specific `publish-check-extra` graduation
- [x] `agentic_scaffolding` publishes through `publish-check-extra := make check`
- [x] `prompt_eval` publishes through `publish-check-extra := make check`, or is explicitly documented as deferred with a truthful blocker
- [x] `research_v3` is either graduated or explicitly deferred with a truthful blocker classification
- [x] `llm_client` is explicitly deferred unless `make check` is proven cheaply repairable
- [x] Required tests pass for `enforced-planning` and every graduated repo

---

## Verification Notes

- `enforced-planning`
  - `python scripts/check_markdown_links.py ROADMAP.md docs/plans/52_coordination-publish-discipline-and-reviewed-dead-code-rollout.md docs/plans/53_publish-check-extra-graduation-wave-1.md docs/plans/CLAUDE.md`
  - `python scripts/self_test.py --links --docs`
- `agentic_scaffolding`
  - branch `plan-53-agentic-scaffolding-publish-check-extra`
  - commits `e4a4f86` and `16b9fcd`
  - `make check`
  - `make publish-check`
  - `git push -u origin plan-53-agentic-scaffolding-publish-check-extra`
- `prompt_eval`
  - branch `plan-53-prompt-eval-publish-check-extra`
  - commit `2d1bd2d`
  - `make check`
  - `python scripts/meta/check_doc_coupling.py`
  - `python scripts/check_markdown_links.py CLAUDE.md docs/plans/CLAUDE.md scripts/CLAUDE.md docs/plans/12_governed-baseline-repair-for-active-stack-candidacy.md docs/plans/13_linkage-deepening-and-capability-ownership.md`
  - `make publish-check`
  - `git push -u origin plan-53-prompt-eval-publish-check-extra`
- `research_v3`
  - `PATH=.venv/bin:$PATH make check`
  - result: explicitly deferred for this wave because test collection fails with `ModuleNotFoundError: No module named 'followthemoney'`
- `llm_client`
  - `PATH=.venv/bin:$PATH make check`
  - result: deferred because `ruff check llm_client/ tests/` reports 317 issues

---

## Notes

- The promotion rule is strict on purpose: a repo only earns stricter publish blocking when its full quality gate is already credible.
- This plan does not redefine `make check` to make graduation easier. If a gate is noisy, fix the gate or defer the graduation.
