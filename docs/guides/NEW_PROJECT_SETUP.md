# New Project Setup Guide

Detailed operator guide for adopting the minimum governed-repo contract.

This is the longer companion to [GETTING_STARTED.md](../../GETTING_STARTED.md).
It stays in the installed-consumer perspective and focuses on operator
verification, ongoing maintenance, troubleshooting, and optional rollout modes.

## 1. Prerequisites

Your target repo needs:

- git
- Python 3.9+
- a canonical `CLAUDE.md`

The canonical installer will not invent project governance for you.

## 2. Bootstrap The Minimum Governed Contract

From the `enforced-planning` repo:

```bash
python scripts/install_governed_repo.py --repo-root /path/to/your/project --write
python scripts/audit_governed_repo.py --repo-root /path/to/your/project --strict-governed
```

Equivalent convenience wrapper:

```bash
./install.sh /path/to/your/project
```

The shell wrapper is not a separate authority. Its default mode delegates to
the canonical Python installer.

## 3. Operator-Facing Additions Beyond The Short Guide

[GETTING_STARTED.md](../../GETTING_STARTED.md) is the canonical first-success
inventory for the minimum governed contract. Operators usually care about the
additional control surfaces the install makes available:

- `Makefile`
  - shared entrypoints for validation and worktree operations
- `scripts/meta/worktree-coordination/check_claims.py`
  - validates sanctioned worktree claims
- `scripts/meta/worktree-coordination/create_worktree.py`
  - creates governed worktrees through the sanctioned path
- `scripts/meta/worktree-coordination/safe_worktree_remove.py`
  - bounded worktree cleanup path
- `.claude/settings.json`
  - read-gating hook wiring
- `AGENTS.md`
  - generated Codex/non-Claude projection of `CLAUDE.md`

## 4. Verify The Result

From the target repo root:

```bash
python scripts/meta/check_agents_sync.py --repo-root . --check
python scripts/meta/file_context.py --json CLAUDE.md
```

From the framework repo:

```bash
python scripts/audit_governed_repo.py --repo-root /path/to/your/project --strict-governed
```

If the audit passes, the repo satisfies the minimum mechanical governed-repo
contract.

## 5. Configure `meta-process.yaml`

Use [docs/reference/CONFIG_REFERENCE.md](../reference/CONFIG_REFERENCE.md) for
the authoritative key table. The example below is intentionally limited to
keys that have script effect today. Broader planned/advisory vocabulary lives
in `templates/meta-process.future.yaml.example`.

Mechanically meaningful starting point:

```yaml
meta_process:
  version: "1.0"

  plans:
    enabled: true
    require_tests: true
    plans_dir: "docs/plans"

  commits:
    require_prefix: true
    valid_prefixes:
      - "\\[Plan #\\d+\\]"
      - "\\[Trivial\\]"
      - "\\[Unplanned\\]"

  quality:
    doc_coupling:
      enabled: true
      config_file: "scripts/relationships.yaml"
```

## 6. First Plan

From the target repo:

```bash
git checkout -b plan-1-my-first-feature
cp docs/plans/TEMPLATE.md docs/plans/01_my-first-feature.md
```

Before implementation, make sure the plan declares:

- gap framing
- references reviewed
- research basis for the slice, or an explicit skip statement
- required tests

Then implement and commit:

```bash
git add -A
git commit -m "[Plan #1] implement my first feature"
```

## 7. Optional And Legacy Modes

These are not the canonical minimum install path:

- `./install.sh /path/to/your/project --worktree-only`
  - canonical bounded sync for sanctioned worktree entrypoints only
- `./install.sh /path/to/your/project --full`
  - legacy compatibility bootstrap for broader rollout surfaces
- `./install.sh /path/to/your/project --pre-commit`
  - legacy compatibility bootstrap for pre-commit hook distribution

Truth-surface tooling also remains outside the minimum canonical install for
now. The canonical semantic-review entrypoint is:

```bash
python scripts/review_truth_surface_semantic.py --config /path/to/your/project/scripts/truth_surface_drift.yaml
```

Use that directly from the framework repo, or use the legacy `--full`
bootstrap only if you intentionally want the older broader installed surface.

## 8. Common Problems

### Audit says `missing canonical CLAUDE.md`

Create the root `CLAUDE.md` first. The installer will not invent it.

### Audit says `missing scripts/relationships.yaml`

Re-run the canonical installer in write mode:

```bash
python scripts/install_governed_repo.py --repo-root /path/to/your/project --write
```

### `AGENTS.md` drifts later

From the target repo:

```bash
python scripts/meta/check_agents_sync.py --repo-root . --check
python scripts/meta/render_agents_md.py --repo-root . > AGENTS.md
```

### `file_context.py` fails

Check that the installed repo still has:

- `CLAUDE.md`
- `scripts/relationships.yaml`
- `scripts/meta/file_context.py`

## 9. Reference Docs

- [GETTING_STARTED.md](../../GETTING_STARTED.md)
- [PLANNING_OPERATING_MODEL.md](../../PLANNING_OPERATING_MODEL.md)
- [docs/reference/CONFIG_REFERENCE.md](../reference/CONFIG_REFERENCE.md)
- [templates/meta-process.future.yaml.example](../../templates/meta-process.future.yaml.example)
- [patterns/01_README.md](../../patterns/01_README.md)
