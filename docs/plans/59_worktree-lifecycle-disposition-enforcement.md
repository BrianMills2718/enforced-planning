# Plan #59: Worktree lifecycle disposition enforcement

**Status:** Complete
**Type:** implementation
**Priority:** Critical
**phase_ref:** "Phase 9 fleet adoption"
**goal_ref:** "truthful-governed-repo-lifecycle"
**adrs_referenced:** ["ADR-0010"]
**research_citations:** []
**Blocked By:** project-meta#212 policy baseline
**Blocks:** safe `llm_client` worktree cleanup and fleet rollout
**trace_evaluable:** false # infrastructure-only

---

## Gap

**Current:** Plan #42 made worktree removal, local branch deletion, and claim
release atomic. It checks dirt and authority obligations, then removes the
worktree and calls `git branch -D`. It does not prove the branch is integrated
or explicitly dispositioned. The operator guide also still documents the
retired sibling worktree layout.

**Target:** Closeout performs a complete read-only preflight before mutation.
The default path accepts only branches integrated into the canonical default
branch. Explicit non-merge closeout uses a constrained disposition vocabulary
and requires durable recovery evidence when unique commits are retained.

**Why:** Cleanliness and integration are different invariants. Treating a clean
worktree as deletion-safe can destroy committed work.

---

## References Reviewed

- `CLAUDE.md` — source-repo workflow and mandatory closeout discipline.
- `docs/plans/42_atomic-closeout-and-claimed-worktree-removal.md` — existing
  atomicity contract and tests.
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — canonical operator
  surface and stale sibling-location instruction.
- `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md` — existing merge/push/remove
  sequence.
- `enforced_planning/session_lifecycle.py` — current closeout implementation.
- `tests/test_session_cli.py` — existing positive closeout behavior, including
  the unsafe clean-unmerged case.
- `scripts/install_governed_repo.py` and installer tests — consumer propagation
  boundary.
- `agent-memory recall 'active decisions worktree lifecycle session close'
  --project enforced-planning` — prior import-closure/rollout finding.
- `project-meta/docs/plans/212_worktree-lifecycle-disposition-and-safe-closeout.md`
  — approved cross-repo policy and coverage baseline.

No additional external research was needed; the gate is derived from Git's
deterministic branch, ancestry, and worktree state.

---

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| Merge preflight | Deductive | Default branch and ancestry are deterministic | Test both signs before implementation |
| Non-merge vocabulary | Deductive | Allowed outcomes and evidence can be enumerated | Validate explicit values and required evidence |
| Historical intent | Outside this implementation | Git cannot decide whether old work is desired | Report evidence; disposition remains operator judgment |

---

## Multi-Repo Coordination

| Repo | Files Modified | Merge Strategy |
|---|---|---|
| `project-meta` | Plan #212 policy/coverage surfaces | Merge first |
| `enforced-planning` | Canonical implementation, docs, tests, installer | Merge second |
| `llm_client` | Installed consumer and live proof | Propagate only after framework verification |

This lane owns only the paths in its narrow coordination claim. Consumer
changes occur in a separate `llm_client` worktree after this branch lands.

---

## Files Affected

- `enforced_planning/session_lifecycle.py`
- `enforced_planning/worktree_lifecycle.yaml`
- `enforced_planning/worktree_paths.py`
- `Makefile`
- `scripts/session_close.py`
- `scripts/meta/session_close.py`
- `scripts/check_coordination_claims.py`
- `scripts/meta/check_coordination_claims.py`
- `scripts/session_finish.py`
- `scripts/meta/session_finish.py`
- `scripts/session_heartbeat.py`
- `scripts/meta/session_heartbeat.py`
- `scripts/session_start.py`
- `scripts/meta/session_start.py`
- `scripts/session_status.py`
- `scripts/meta/session_status.py`
- `scripts/worktree-coordination/safe_worktree_remove.py`
- `scripts/meta/worktree-coordination/safe_worktree_remove.py`
- `scripts/install_governed_repo.py`
- `templates/Makefile.worktree.block.template`
- `tests/test_session_cli.py`
- `tests/test_install_governed_repo.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/guides/CONTINUOUS_EXECUTION_CONTRACT.md`
- `docs/plans/CLAUDE.md`

---

## Plan

| Step | What | Status |
|---|---|---|
| 1 | Record baseline evidence and missing controls in Plans #212/#59. | Complete |
| 2 | Convert the existing clean-unmerged closeout fixture into a negative control. | Complete |
| 3 | Add a merged-branch positive control and non-merge validation controls. | Complete |
| 4 | Implement read-only preflight and safe branch deletion. | Complete |
| 5 | Update CLI/templates/operator docs and installer propagation. | Complete |
| 6 | Run focused and full verification; commit and merge the framework slice. | Complete |

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|---|---|---|
| `tests/test_session_cli.py` | `test_close_session_rejects_clean_unmerged_branch_before_mutation` | Negative control: clean does not mean deletion-safe |
| `tests/test_session_cli.py` | `test_close_session_closes_branch_merged_to_default` | Positive control: merged lane still closes atomically |
| `tests/test_session_cli.py` | `test_close_session_rejects_unknown_disposition` | Disposition vocabulary fails loud |
| `tests/test_session_cli.py` | `test_close_session_requires_durable_ref_for_retained_unique_commits` | Non-merge deletion cannot strand unique commits |
| `tests/test_install_governed_repo.py` | existing worktree-only propagation tests | Installed consumer receives updated CLI/templates |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|---|---|
| `pytest -q tests/test_session_cli.py` | Session lifecycle behavior and idempotence |
| `pytest -q tests/test_install_governed_repo.py tests/test_create_worktree.py` | Installer and location contract |
| `python scripts/self_test.py` | Framework-wide source/install consistency |
| worktree-only installer test with Ruff | Every portable Python file copied into consumers passes Ruff, not only the edited subset |
| `PYTHONPATH=. pytest -q` | Full regression suite; known MP-015 baseline failures must not increase |

---

## Acceptance Criteria

| Criterion | Baseline grade | Closure evidence |
|---|---|---|
| AC1: Unmerged clean branch fails before mutation. | A / test | Real-Git negative control passes |
| AC2: Merged branch closes atomically and idempotently. | A / test | Real-Git positive and partial-rerun controls pass |
| AC3: Unknown or incomplete non-merge disposition fails loud. | A / test | Unknown, missing recovery, and missing discard-authorization controls pass |
| AC4: Local branch deletion is safe by default. | A / test | Merged path uses safe delete; force is licensed only after non-merge recovery/discard proof |
| AC5: Installed consumer exposes the same CLI contract. | A / test | Worktree-only installer import-closure and `--help` controls pass |
| AC6: Operator docs and creator location agree. | A / test | Source location tests and reconciled operator docs pass |

Enforcement promotion is allowed only after AC1 and AC2 both pass.

Verification evidence on 2026-07-09:

- 44/44 focused session, installer, configuration, and worktree-location tests
  passed.
- `python scripts/self_test.py` passed all five framework checks.
- ruff passed on all changed Python files.
- strict mypy passed on the canonical modules/wrapper and copied wrapper.
- full pytest reported 512 passed, 1 skipped, and the same 7 governed-repo
  audit failures reproduced on untouched `main` and already tracked as MP-015.

---

## Failure Modes And Recovery

| Failure | Detection | Recovery |
|---|---|---|
| Default branch missing or ambiguous | preflight cannot resolve configured/canonical default | fail before mutation; require explicit configured branch |
| Branch has unique commits | ancestry check fails | merge first or provide validated non-merge disposition |
| Worktree already missing after partial close | path absent but claim/branch remains | preserve Plan #42 idempotent recovery, still validate branch safety |
| Branch already missing | ref absent | treat as already missing and release claim after other obligations pass |
| Invalid disposition | parser rejects value | correct the explicit operator input; no fallback |
| Durable recovery ref missing | local branch is sole ref for unique commit | push/tag/archive first; do not delete |
| Claim update omits `repo_root` | closeout resolves the linked path as canonical and loses cwd after removal | derive the canonical root from the in-repo worktree convention before mutation |

---

## Decisions Pre-Made

- Default closeout means merge-first, then close.
- `session-close` validates; it does not automatically merge.
- Branch and worktree lifecycles are separate. A long-lived branch may remain
  remotely while its local worktree is removed.
- Non-merge dispositions are explicit and constrained; free-text notes alone
  are not sufficient.
- All validation happens before the claim status changes to `closing`.
- Safe deletion uses `git branch -d`; force deletion requires an explicit
  non-merge path with durable recovery evidence and is never the default.

---

## Open Questions

- [x] Should every stale branch be merged? — **Resolved:** No. Desired completed
      work merges by default; superseded, abandoned, archived, or migrated work
      receives an explicit non-merge disposition.
- [x] Should a serious feature keep a permanent worktree? — **Resolved:** No.
      Branch durability and checkout durability are independent; keep a
      worktree only while the lane is actively owned.
