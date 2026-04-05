# Enforced Planning: AI-Assisted Development Framework

A portable framework for coordinating AI coding assistants on shared codebases.

> **Tool support:** Claude Code currently has the strongest native support
> because read-gating is enforced through `.claude/hooks/`. Other tools can
> still consume the planning model, generated `AGENTS.md`, and deterministic
> validators, but they do not yet share the same native interactive hook
> surface.

## What This Solves

When AI instances work on a codebase:

- **drift** - agents forget constraints mid-implementation
- **guessing** - agents assume instead of investigating
- **unverified completion** - "done" work passes weak checks but not real requirements
- **documentation rot** - code changes without coupled doc updates
- **missing traceability** - hard to answer why a decision was made or what verifies it

## Core Idea

Move human review upstream. Humans review requirements, acceptance criteria,
plans, and ADRs before implementation. Deterministic checks and tests verify
the implementation after the fact. The full artifact dependency model lives in
[PLANNING_OPERATING_MODEL.md](PLANNING_OPERATING_MODEL.md).

## Installer Authority

The canonical governed-repo installer and upgrader is:

```bash
python scripts/install_governed_repo.py --repo-root /path/to/your/project --write
```

That command owns the minimum governed-repo contract and ongoing sync story.

`install.sh` still exists, but its role is narrower:

- `./install.sh /path/to/your/project`
  - convenience wrapper around the canonical minimum installer
- `./install.sh /path/to/your/project --worktree-only`
  - bounded sync for sanctioned worktree entrypoints only
- `./install.sh ... --full` and `./install.sh ... --pre-commit`
  - legacy compatibility bootstrap modes, not the canonical long-term sync path

## Quick Start

1. In the target repo, author a canonical `CLAUDE.md`.
2. From this framework repo, run:

```bash
python scripts/install_governed_repo.py --repo-root /path/to/your/project --write
python scripts/audit_governed_repo.py --repo-root /path/to/your/project --strict-governed
```

3. In the target repo, verify the installed surfaces:

```bash
cd /path/to/your/project
python scripts/meta/check_agents_sync.py --repo-root . --check
python scripts/meta/file_context.py --json CLAUDE.md
```

For the shortest adoption path, continue with
[GETTING_STARTED.md](GETTING_STARTED.md).

## What Counts As A Governed Repo?

The minimum mechanical governed-repo contract is:

- `CLAUDE.md`
- `meta-process.yaml`
- `docs/plans/CLAUDE.md`
- `docs/plans/TEMPLATE.md`
- `scripts/relationships.yaml`
- generated `AGENTS.md`
- installed validator/support files under `scripts/meta/`
- read-gating surfaces under `.claude/hooks/` and `.claude/settings.json`

`scripts/audit_governed_repo.py --strict-governed` is the mechanical check for
that contract.

## Installed Layout

The canonical minimum installer produces an installed repo shaped like this:

```text
your-project/
├── AGENTS.md
├── CLAUDE.md
├── Makefile
├── meta-process.yaml
├── docs/
│   └── plans/
│       ├── CLAUDE.md
│       └── TEMPLATE.md
├── enforced_planning/
│   ├── __init__.py
│   ├── agents_rendering.py
│   └── file_context.py
├── scripts/
│   ├── relationships.yaml
│   └── meta/
│       ├── check_agents_sync.py
│       ├── check_doc_coupling.py
│       ├── file_context.py
│       ├── render_agents_md.py
│       ├── sync_plan_status.py
│       ├── validate_plan.py
│       └── worktree-coordination/
├── .claude/
│   ├── hooks/
│   └── settings.json
└── meta-process/
    └── templates/
        └── agents.md.template
```

The target repo does contain a small installed `enforced_planning/` support
package used by generated entrypoints. It does **not** contain a vendored copy
of this full framework repo.

## Configuration

The installed config file is `meta-process.yaml`. The authoritative reference
is [docs/reference/CONFIG_REFERENCE.md](docs/reference/CONFIG_REFERENCE.md).
The example below is limited to keys that have script effect today; the
template and reference also document broader planned/advisory vocabulary.

Example:

```yaml
meta_process:
  version: "1.0"

  plans:
    enabled: true
    require_tests: true
    plans_dir: "docs/plans"

  quality:
    doc_coupling:
      enabled: true
      config_file: "scripts/relationships.yaml"
```

## Optional And Legacy Rollout Surfaces

The canonical minimum installer does **not** currently ship every framework
module.

- Truth-surface validation and semantic-review tooling are not part of the
  minimum canonical install yet.
- The canonical semantic-review entrypoint is
  `python scripts/review_truth_surface_semantic.py --config ...`, which writes a
  current JSON payload plus append-only review history.
- Raw git-hook bootstrap and pre-commit bootstrap currently live behind legacy
  `install.sh --full` and `install.sh --pre-commit` flows.
- Worktree-only sync is canonical, but broader multi-agent coordination remains
  an opt-in layer.

That boundary is intentional until the installer and semantic-review surfaces
finish converging.

## Canonical Docs

- [PLANNING_OPERATING_MODEL.md](PLANNING_OPERATING_MODEL.md) - canonical methodology
- [GETTING_STARTED.md](GETTING_STARTED.md) - first successful adoption path
- [patterns/01_README.md](patterns/01_README.md) - pattern catalog
- [ROADMAP.md](ROADMAP.md) - forward queue and phase map
- [STATIC_GRAPH_AND_RUNTIME_TRUTH.md](STATIC_GRAPH_AND_RUNTIME_TRUTH.md) - truth-surface architecture
- [docs/reference/CONFIG_REFERENCE.md](docs/reference/CONFIG_REFERENCE.md) - config key reference

## Origin

This framework was extracted from work first developed in
`agent_ecology2`. That project is provenance, not the explanatory frame for
adoption.

## License

MIT
