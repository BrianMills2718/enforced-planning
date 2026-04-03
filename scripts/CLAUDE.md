# enforced-planning/scripts

This directory contains the portable baseline scripts shipped by the
enforced-planning framework.

## Use This Directory For

- baseline validators and helpers that should work in any governed repo
- logic that installed repos import or call from `scripts/meta/`
- portable coordination claim-v2 and active-work registry surfaces shared
  across governed repos

## Route Narrower Work

- optional worktree-coordination operational helpers -> `worktree-coordination/`

## Do Not Use This Directory For

- `project-meta`-specific extensions that belong in the repo-root `scripts/`
  tree
