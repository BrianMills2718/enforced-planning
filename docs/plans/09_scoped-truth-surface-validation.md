# Plan #9: Scoped Truth-Surface Validation By Canonical Repo Identity

**Status:** Complete
**Type:** implementation
**Priority:** High
**Blocked By:** 6, 8
**Blocks:** cleaner governed-repo adoption beyond the first pilot

---

## Gap

**Current:** The first governed-repo pilot in `prompt_eval` proved that the
validator and renderer work in a real repo, but the measured findings were
polluted by unrelated ecosystem registry drift from other repos. That makes a
repo-local truth-surface run less actionable than it should be.

**Target:** Add scope-aware filtering based on canonical repo identity so a
repo-local config can say "show me truth-surface drift for this governed repo"
without silently swallowing the distinction between local drift and ecosystem
background noise.

**Why:** Without scoped validation, every governed-repo pilot is vulnerable to
false urgency from unrelated global registry state. The framework needs one
clear way to separate repo-local contradictions from broader coordination
cleanup work.

---

## References Reviewed

- `docs/plans/06_governed-repo-truth-surface-adoption-pilot.md`
- `docs/plans/08_truth-surface-adoption-pilot-execution-sprint.md`
- `docs/plans/07_llm-semantic-truth-surface-review.md`
- `STATIC_GRAPH_AND_RUNTIME_TRUTH.md`
- `scripts/check_truth_surface_drift.py`
- `templates/truth_surface_drift.yaml.example`
- `~/projects/prompt_eval_worktrees/plan-15-truth-surface-pilot/truth_surface_drift.yaml`
- `~/projects/prompt_eval_worktrees/plan-15-truth-surface-pilot/docs/ops/TRUTH_SURFACE_RENDERED_STATUS.md`

---

## Files Affected

- `scripts/check_truth_surface_drift.py`
- `scripts/render_truth_surface_status.py` if output shape changes
- `templates/truth_surface_drift.yaml.example`
- `tests/test_truth_surface_drift.py`
- pilot repo-local config/docs if scoped replay changes the recommendation

---

## Plan

### Phase A — Scope Model

Success criteria:
- one clear config shape exists for repo-local scoping
- scope is based on canonical repo identity rather than machine-local worktree paths
- the model is documented before code changes widen behavior

### Phase B — Validator Implementation

Success criteria:
- the validator can derive canonical repo identity from repo roots/worktree roots
- active-work and reservation checks can be scoped to one or more canonical repos
- tests cover normal repo roots and `*_worktrees/<branch>` roots

### Phase C — Pilot Replay

Success criteria:
- `prompt_eval` can rerun the pilot with scoped config
- unrelated `project-meta` / `agentic_scaffolding` drift stops dominating the repo-local result
- any remaining local finding is clearly attributable to the target repo or its own historical worktrees

### Phase D — Framework Guidance

Success criteria:
- docs explain when to use scoped repo-local validation versus full global review
- the pilot recommendation is updated if scoping materially changes the operator signal

---

## Required Tests

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_truth_surface_drift.py` | `test_scope_filters_by_canonical_repo_identity` | unrelated registry entries are excluded when scope is set |
| `tests/test_truth_surface_drift.py` | `test_scope_derives_canonical_name_from_worktree_repo_root` | worktree roots map back to canonical repo identity |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `python scripts/self_test.py` | framework integrity stays green |
| `pytest tests/test_truth_surface_drift.py tests/test_render_truth_surface_status.py -q` | validator/render behavior remains verified |
| scoped `prompt_eval` rerun | proves the new scope model helps a real governed repo |

---

## Acceptance Criteria

- [x] Repo-local configs can scope checks by canonical repo identity.
- [x] Canonical repo identity is derived correctly for normal roots and worktree roots.
- [x] The scoped `prompt_eval` replay removes unrelated ecosystem drift from the main repo-local output.
- [x] Docs clearly distinguish repo-local scoped validation from broader global coordination review.

---

## Measured Findings

- Canonical repo identity can be derived cheaply from both normal repo roots and
  `*_worktrees/<branch>` paths.
- Scoping `prompt_eval` to `repo_names: [prompt_eval]` reduced the repo-local
  output from three failures to one actionable local historical reservation
  issue.
- Scoped mode is now the right default operator view for repo-local runs.
- Unscoped mode still matters for broader ecosystem hygiene and should not be
  removed.

## Open Questions

- [ ] Should global out-of-scope findings disappear entirely under scoped mode, or be downgraded into a background section later?
- [ ] Is canonical repo identity best expressed as one name, multiple aliases, or a future registry-backed map?
