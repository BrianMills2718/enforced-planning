# Plan #38: Authority-Drift Reconciliation Gates

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** Plan #41 and the existing doc-authority architecture
**Blocks:** truthful authority-surface ownership and safe lane closeout under concurrent work

## Gap

The coordination model can prevent overlapping writes to claimed authority
surfaces, but it still needs a formal answer to this case:

- Lane A lands a new authoritative artifact in its own claimed scope
- Lane B owns the authority surface that indexes or governs that artifact
- Lane A correctly avoids editing Lane B's claimed authority surface
- but the resulting drift is only discussed conversationally or in ad hoc notes

That makes authority drift easy to forget and too easy to ignore at closeout.

## Desired Outcome

Authority drift becomes a first-class, machine-visible reconciliation
obligation, and closing the lane that owns an affected authority surface fails
until the obligation is resolved.

## Research

Reviewed before freezing this plan:

- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/designs/COORDINATION_RUNTIME_TARGET_ARCHITECTURE.md`
- existing doc-authority lane design direction and validator surfaces
- `project-meta` examples where new authoritative artifacts and separately owned
  indexes can drift

The gap is not overlap prevention alone. The gap is durable, validator-visible
reconciliation debt when overlap is forbidden but drift still exists.

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| No silent overlap | Landing lanes do not edit separately claimed authority surfaces | Preserves lane ownership and reduces merge conflicts |
| No silent drift | Landing lanes must record a formal reconciliation obligation when drift is created | Avoids hidden inconsistencies |
| Gate strength | Closeout of the owning authority lane fails, not merely warns, while obligations remain unresolved | Warnings are too easy to ignore |
| Scope of obligation | Obligation must name the landed artifact, the skipped authority surface, and the required reconciliation action | Keeps handoff precise and auditable |
| Near-term target | Start with high-value authority indexes like plan indexes and current-status surfaces | Immediate operational value without boiling the ocean |
| Long-term simplification | Prefer generated authority indexes where practical | Reduces this entire class of coordination debt |

## Files Expected

- `docs/designs/DOC_AUTHORITY_GOVERNANCE_ARCHITECTURE.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `scripts/validate_doc_authority.py`
- new drift-obligation storage/rendering surface if needed
- `tests/test_validate_doc_authority.py`

## Acceptance Criteria

1. Validators can detect newly landed authoritative artifacts that are missing
   required reconciliation against authority surfaces.
2. When the affected authority surface is actively claimed by another lane, the
   drift is recorded as a formal reconciliation obligation instead of requiring
   opportunistic overlap.
3. The lane owning the authority surface cannot close while unresolved
   obligations remain against that surface.
4. Operator docs define the distinction between authoritative content,
   authoritative index, and reconciliation obligation unambiguously.
5. The design explicitly supports generated authority indexes as the preferred
   long-term simplification path.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_validate_doc_authority.py` | Authority-drift obligations and closeout gates are enforced deterministically |
| `python scripts/self_test.py --docs` | Shared docs and policy surfaces stay coherent |

## Failure Modes And Recovery

| Failure Mode | Expected Handling |
|---|---|
| Lane lands plan doc but skips separately claimed plan index | create formal reconciliation obligation; do not edit the claimed index |
| Owning lane tries to close with open obligation | fail closeout until reconciliation is complete |
| Drift exists but no authority owner is active | validator fails because the drift is unowned and unreconciled |
| Authority index is generated | regenerate it instead of recording durable manual debt |

## Notes

This plan turns "leave a note for the other lane" into a real coordination
contract. The note must be machine-visible, durable, and closure-blocking.

Implemented on 2026-04-05:

- `enforced_planning/doc_authority.py` now validates indexed authority drift
  and persists reconciliation obligations under
  `~/.claude/coordination/authority_obligations/`
- `scripts/validate_doc_authority.py` exposes check/record/list/resolve
  lifecycle commands for the authority-drift surface
- `session-finish` now fails closed when the lane owns an authority surface
  with unresolved obligations
- the framework's own plan-index authority surface now validates cleanly under
  the new checker
