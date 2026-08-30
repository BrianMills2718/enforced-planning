# Mac Mini Continuous Automation Bootstrap

## Purpose

Use the current `enforced-planning` source repo as the bootstrap point for a
controlled Mac mini rollout without skipping the framework's safety model.

This guide is intentionally conservative. It prepares the Mac mini for
continuous automation, but it does **not** claim that unattended multi-repo
upgrade automation is ready yet.

## Read This As

- source-repo bootstrap first
- one governed-repo pilot second
- only then continuous overnight execution lanes

## Preconditions

Before using this guide, the framework source repo should already have:

- a clean committed branch tip
- `python scripts/self_test.py` passing
- the current Phase 8 design queue landed
- one operator who will own the first Mac mini pilot lane

## Phase 1: Bootstrap the Source Repo on the Mac Mini

1. Resolve the workspace root from the host configuration or its Project Graph
   record, then clone the framework. `~/projects` is one possible host layout;
   it is not a framework requirement. Use absolute paths for the selected host:

```bash
WORKSPACE_ROOT=/absolute/path/to/registered-workspace
FRAMEWORK_ROOT="$WORKSPACE_ROOT/enforced-planning"
mkdir -p "$WORKSPACE_ROOT"
git clone <framework-remote> "$FRAMEWORK_ROOT"
cd "$FRAMEWORK_ROOT"
```

2. Create the local environment and install the repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

3. Verify the source repo before touching any consumer repo:

```bash
python scripts/self_test.py
pytest -q tests/test_install_governed_repo.py tests/test_audit_governed_repo.py
```

If those do not pass, stop and fix the framework repo first. Do not start the
consumer rollout from an unverified source tree.

## Phase 2: Choose the First Pilot Repo

Choose only one repo for the first pilot. Prefer a repo that:

- already has a canonical `CLAUDE.md`
- is small enough to audit quickly
- is not carrying large unrelated local dirt
- can tolerate a dedicated worktree lane for upgrade and verification

Do **not** start with a broad fleet rollout.

## Phase 3: Create a Sanctioned Worktree Lane

Run the first governed-repo rollout from a dedicated worktree, not from the
framework main checkout and not from the target repo's main branch.

Example shape:

```bash
cd "$FRAMEWORK_ROOT"
python scripts/worktree-coordination/create_worktree.py \
  --repo-root "$FRAMEWORK_ROOT" \
  --branch mac-mini-pilot-install \
  --path "$FRAMEWORK_ROOT/worktrees/mac-mini-pilot-install"
cd "$FRAMEWORK_ROOT/worktrees/mac-mini-pilot-install"
```

That worktree is the operator lane for the install/audit cycle.

## Phase 4: Install the Governed Contract Into the Pilot Repo

From the worktree lane, set the pilot repository to its resolved absolute path;
do not infer it from the framework workspace layout:

```bash
PILOT_REPO_ROOT=/absolute/path/to/registered-pilot-repo
python scripts/install_governed_repo.py --repo-root "$PILOT_REPO_ROOT" --write
python scripts/audit_governed_repo.py --repo-root "$PILOT_REPO_ROOT" --strict-governed
```

If the strict audit fails:

- record the failure class
- fix the repo in a bounded lane
- rerun the audit

Do not paper over the failure by weakening the audit.

## Phase 5: Verify the Installed Repo In Place

Move into the target repo and check the installed surfaces directly:

```bash
cd "$PILOT_REPO_ROOT"
python scripts/meta/check_agents_sync.py --repo-root . --check
python scripts/meta/file_context.py --json CLAUDE.md
git status --short --branch
```

Then run the repo-local validation stack that repo expects. The minimum checks
are:

- generated `AGENTS.md` is in sync
- plan/doc validator entrypoints run
- repo-local tests still pass

## Phase 6: Commit and Preserve the Pilot Slice

Keep rollback cheap:

- commit every verified framework-side slice in the worktree lane
- commit target-repo changes in the target repo separately
- do not batch unrelated fixes into the same pilot commit

If the pilot needs to be abandoned, drop the worktree lane or revert the pilot
commit. Do not hand-edit files back into place.

## Phase 7: Start Continuous Overnight Execution Only After the Pilot Passes

Continuous overnight automation on the Mac mini should begin only after:

1. source repo bootstrap passes
2. one governed-repo pilot install passes
3. the operator can repeat the install/audit/verify flow from a worktree lane
4. commit/rollback behavior is proven in practice

At that point, continuous execution lanes should follow this pattern:

- one worktree per active overnight mission
- one numbered plan or sprint tracker per lane
- regular verified commits
- no direct work on dirty primary checkouts

## What Is Still Not Ready

These are intentionally out of scope for the first Mac mini bootstrap:

- unattended fleet-wide governed-repo upgrades
- automatic multi-repo write-mode rollout
- financial ROI reporting
- a finished `ecosystem-status` renderer/metrics implementation

Those remain follow-on implementation work.

## First Follow-On Work After Bootstrap

After the Mac mini pilot succeeds, the next highest-value items are:

1. implement `make ecosystem-status` and the generated operator status artifact
2. add metric collection/rendering on top of that status surface
3. run a second governed-repo pilot only after the first lane is repeatable

## Canonical Commands

```bash
# Framework verification
python scripts/self_test.py
pytest -q tests/test_install_governed_repo.py tests/test_audit_governed_repo.py

# Governed-repo rollout
python scripts/install_governed_repo.py --repo-root "$PILOT_REPO_ROOT" --write
python scripts/audit_governed_repo.py --repo-root "$PILOT_REPO_ROOT" --strict-governed

# Installed repo verification
python scripts/meta/check_agents_sync.py --repo-root . --check
python scripts/meta/file_context.py --json CLAUDE.md
```
