# Mission: Safe worktree closeout enforcement

## Objective

Make the portable framework refuse destructive closeout until a clean branch
is proven integrated into the canonical default branch or carries an explicit,
validated non-merge disposition.

## Acceptance Criteria

- [ ] Closeout validates every precondition before mutating worktree, branch,
      claim, or tracker state.
- [ ] A clean unmerged branch is rejected by a negative-control test.
- [ ] A branch merged into the canonical default branch closes atomically in a
      positive-control test.
- [ ] A supported explicit non-merge disposition has durable recovery evidence
      before local branch deletion.
- [ ] Default closeout uses safe branch deletion and never treats `-D` as merge
      evidence.
- [ ] Operator and continuous-execution docs distinguish worktree lifecycle
      from branch lifecycle and use `<repo>/worktrees/<branch>/`.
- [ ] Installer tests prove governed consumers receive the same behavior.

## Constraints

- Visibility and both signs of control precede enforcement.
- No silent fallback from missing default-branch or upstream evidence.
- No live repository is used as a test fixture.
- Preserve idempotent recovery for already-missing worktrees and branches.

## Current Phase

Full framework verification before commit, merge, and consumer rollout.

## Completed

- 2026-07-09: Created a sanctioned in-repo claimed worktree for Plan #59.
- 2026-07-09: Reviewed Plan #42 and confirmed it solved atomicity but did not
  require merge or disposition evidence.
- 2026-07-09: Project-meta Plan #212 established baseline lifecycle coverage at
  A=1, C=1, D=2, F=3 and identified the missing controls.
- 2026-07-09: Five real-Git controls first failed against the unsafe baseline:
  clean unmerged deletion, missing disposition payload/history, lost canonical
  root after worktree removal, unknown disposition, and durable recovery-ref
  closeout.
- 2026-07-09: Implemented validate-before-mutate preflight, in-repo canonical
  root resolution, safe merged deletion, constrained non-merge recovery or
  explicit abandonment, and completed claim audit history. Added two more
  negative controls for missing recovery ref and discard authorization.
- 2026-07-09: `tests/test_session_cli.py` passes 19 real/fixture lifecycle
  tests. Installer/create/session focused set passes 39 tests before the final
  two negative controls were added; full rerun remains next.
- 2026-07-09: Final focused run passes 44/44 tests. Framework self-test, ruff,
  py_compile, and strict mypy pass. Full pytest reports 512 passed, 1 skipped,
  and 7 governed-repo audit failures; a representative failure reproduces on
  untouched `main` and matches existing issue MP-015, so Plan #59 introduced
  no new full-suite failure class.
- 2026-07-09: Pre-landing review passed after adding default-branch push
  verification, strict `1|true|yes` parsing for destructive Make authorization,
  a real abandonment positive control, and a fail-loud configurable lifecycle
  vocabulary installed from `enforced_planning/worktree_lifecycle.yaml`.

## Next

1. Commit, push, merge, and push the verified framework slice.
2. Mark Plan #59 complete after the merge is observed on `main`.
3. Propagate the canonical framework into a claimed `llm_client` worktree.
4. Re-grade Plan #212 coverage from live consumer evidence.
