# Plan #39: Worktree-Aware Markdown-Link Validation And Root Resolution

**Status:** 📋 Planned
**Type:** investigation + implementation
**Priority:** High
**Blocked By:** Plan #24 and the existing shared markdown-link checker
**Blocks:** truthful markdown-link validation in active worktree lanes across governed repos

## Gap

Markdown-link validation is already effectively shared infrastructure because
the canonical checker lives in `enforced-planning` and downstream repos such as
`project-meta` invoke it through thin wrappers.

The remaining friction is worktree-aware path resolution:

- docs may be rendered in one checkout and validated in another
- wrappers may resolve targets relative to the active worktree root while some
  intentionally canonical content still lives at the main checkout root
- sibling-repo references and canonical-root fallbacks can fail for reasons
  that are really workspace/worktree semantics, not markdown syntax

If that is solved ad hoc per repo, the coordination model will drift again.

## Desired Outcome

We have one explicit ownership answer and one bounded implementation path:

- markdown-link / root-resolution semantics are owned by shared coordination
  tooling in `enforced-planning`
- downstream repos keep only thin wrappers
- failure modes are documented and tested instead of patched piecemeal

## Research

Reviewed before freezing this plan:

- `enforced-planning/scripts/check_markdown_links.py`
- `enforced-planning/scripts/worktree_paths.py`
- `project-meta/scripts/check_markdown_links.py`
- current coordination registry state and worktree usage patterns

The current evidence says ownership is already effectively shared; the missing
piece is a truthful worktree/canonical-root resolution contract.

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Ownership | Treat this as shared coordination/worktree infrastructure | Canonical checker already lives in `enforced-planning` |
| Downstream repos | Keep repo-local changes minimal and wrapper-only where possible | Avoid drift and duplicate policy |
| Investigation scope | Explicitly review worktree root vs canonical repo root behavior before changing code | Path resolution bugs are easy to "fix" incorrectly |
| Non-goal | Do not solve this by banning legitimate cross-root docs patterns if shared tooling can model them cleanly | Documentation style restrictions should be last resort |
| Non-goal | Do not add repo-specific hacks for `project-meta` unless a shared fix is impossible | Preserves a single truth surface |

## Expected Files

- `enforced-planning/scripts/check_markdown_links.py`
- `enforced-planning/scripts/worktree_paths.py`
- any shared helper promoted into `enforced_planning/` if needed
- `project-meta/scripts/check_markdown_links.py` only if wrapper forwarding must change
- focused tests for root-resolution/worktree cases

## Acceptance Criteria

1. We have a documented ownership decision: shared coordination fix, repo-local
   fix, or explicit doc-style restriction, with reasons.
2. If a shared fix is needed, it lands in `enforced-planning` with tests.
3. The implemented behavior distinguishes at least these cases:
   - active worktree root
   - canonical repo root
   - sibling-repo relative links
   - generated docs validated from a different checkout than the one that
     rendered them
4. Remaining edge cases are written down explicitly instead of living in chat.

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/...markdown... tests/...worktree...` | Shared checker resolves path/root semantics truthfully |
| `python scripts/check_markdown_links.py ...` from at least one main checkout and one worktree checkout | Real CLI behavior matches the intended ownership model |

## Failure Modes And Recovery

| Failure Mode | Expected Handling |
|---|---|
| Worktree wrapper forwards the wrong repo root | fix shared resolution contract or wrapper forwarding, not local docs |
| Checker assumes active worktree is canonical root | add explicit canonical-root/workspace-root semantics |
| A doc pattern is genuinely too ambiguous to support safely | document and restrict it explicitly rather than silently accepting false negatives |
| Repo-specific patch is proposed first | reject unless shared ownership is proven impossible |

## Notes

This plan exists to stop a coordination/worktree problem from being mistaken for
a local documentation quirk.
