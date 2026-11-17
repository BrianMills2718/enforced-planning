# canonical-repo-resolution Specification

## Purpose
Characterize the existing path helper `enforced_planning.worktree_paths`, which maps a main checkout or a linked git worktree to its canonical repository root. This is existing behavior, scoped as the first capability under the code2 format; it is not a new requirement.

## Requirements

### Requirement: Canonical repository root

The path helper SHALL resolve a linked worktree to the main checkout named by its `.git` gitfile, SHALL fall back to directory naming conventions only when no usable gitfile exists, and SHALL return a path that is not a linked worktree unchanged.

Source: inferred by agent, 2026-11-17: behavior and tests already in `enforced_planning/worktree_paths.py` and `tests/test_worktree_paths.py` (issue #610 comment there) (Brian, 2026-11-17: "option B is what i want").

#### Scenario: Linked worktree outside the repository folder

- **WHEN** a linked worktree lives anywhere on disk and its `.git` gitfile points at the main checkout
- **THEN** the canonical root is the main checkout

#### Scenario: Main checkout

- **WHEN** the path is a main checkout with a `.git` directory
- **THEN** the path is returned unchanged

#### Scenario: Submodule gitfile

- **WHEN** the path holds a gitfile that points into `.git/modules`
- **THEN** it is not resolved to the superproject
