# Getting Started with Enforced Planning

Status: active

Governance and derived knowledge navigation default on. For a disposable
repository, set `meta_process.governance.enabled: false`; this preserves the
installed framework and per-control settings while making them effectively off.
Run `python scripts/meta/effective_project_profile.py --repo-root .` to inspect
the resolved state. Generated wiki pages are navigation, not authority.

This guide is the shortest truthful path from a normal git repo to a
mechanically governed repo.

It describes the **installed consumer** perspective only:

- commands you run against your target repo
- installed paths such as `scripts/meta/...`
- behavior after the canonical installer has run

For framework-source details, see [README.md](README.md).

## Tool Support

- **`native-interactive`:** Claude Code currently has the full minimum
  governed-repo experience, including read-gating
- **`portable-governed`:** other tools can use plans, `AGENTS.md`, and
  deterministic validators, but do not yet share the same native hook surface
- **`legacy-compatible`:** legacy bootstrap modes still exist, but are not the
  canonical sync path

See [docs/designs/PHASE8_TOOL_SUPPORT_MATRIX.md](docs/designs/PHASE8_TOOL_SUPPORT_MATRIX.md)
for the canonical support-tier definitions.

## Before You Install

Your target repo needs:

- a git repository
- Python 3.9+
- a canonical `CLAUDE.md`

The installer will not invent `CLAUDE.md` for you.

Minimal example:

````markdown
# My Project

## Commands

```bash
pytest -q
```

## Principles

1. Fail loud.
2. Keep contracts explicit.

## Workflow

1. Read governing docs before edits.

## References

- `CLAUDE.md` - canonical governance
````

## Install The Minimum Governed-Repo Contract

Run this from the `enforced-planning` repo:

```bash
python scripts/install_governed_repo.py --repo-root /path/to/your/project --write
python scripts/audit_governed_repo.py --repo-root /path/to/your/project --strict-governed
```

Equivalent convenience wrapper:

```bash
./install.sh /path/to/your/project
```

That wrapper delegates to the same canonical minimum installer.

The installer activates the repository's versioned `hooks/` directory when no
hook path is configured. An existing relative or absolute `core.hooksPath` is
preserved when it resolves to that same directory; a genuinely custom hook
directory remains a blocking ownership decision and is never overwritten.
The installed `make worktree` target also accepts `SESSION_WORK_GRAPH` and
`SESSION_WORK_UNIT_ID` so a numbered plan lane can bind its claim and session
to the exact ready work unit at creation time.

If the target opts into Planning Integrity, the same entrypoint validates the
plan and repository configuration from one resolved Git start revision before
it queries graph readiness or creates a claim, branch, worktree, or tracker.
The operator must supply the repository's canonical plan-graph query command;
the portable installer cannot guess where that owner is installed.

## What Gets Installed

After a successful minimum install, your repo should have:

- `meta-process.yaml`
- `docs/plans/CLAUDE.md`
- `docs/plans/TEMPLATE.md`
- `scripts/relationships.yaml`
- `scripts/meta/check_agents_sync.py`
- `scripts/meta/check_coordination_claims.py`
- `scripts/meta/check_doc_coupling.py`
- `scripts/meta/check_reachability.py`
- `scripts/meta/repo_stats_block.py`
- `scripts/meta/file_context.py`
- `scripts/meta/render_agents_md.py`
- `scripts/meta/session_finish.py`
- `scripts/meta/session_heartbeat.py`
- `scripts/meta/session_start.py`
- `scripts/meta/session_status.py`
- `scripts/meta/sync_plan_status.py`
- `scripts/meta/validate_plan.py`
- `.claude/hooks/gate-edit.sh`
- `.claude/hooks/track-reads.sh`
- `.claude/settings.json`
- generated `AGENTS.md`

If the repo enables sanctioned worktree coordination, the canonical installed
claim entrypoint is `scripts/meta/check_coordination_claims.py`. The sanctioned
`make worktree` path creates a healthy v2 **program** claim by default so lane
metadata stays truthful without inventing fake broad write ownership.
The same sanctioned flow also starts a linked session contract and tracker, and
it uses the same claim/tracker model for Codex and Claude Code.

The Enforced Planning source repository additionally sets
`meta_process.claims.outcome_admission_mode: enforce_selected`. New source
outcome work starts with the restricted wrapper:

```bash
make outcome-bootstrap \
  PLAN=124 \
  BRANCH=plan-124-example \
  TASK="Create the bounded Plan 124 bootstrap" \
  SESSION_GOAL=deliver-the-selected-source-outcome \
  SESSION_PHASE="adopt plan and allocate outcome" \
  SESSION_WRITE_PATHS="docs/plans/124_example.md docs/plans/124_example_work_graph.json docs/plans/CLAUDE.md ROADMAP.md"
```

The target rejects empty, mixed-Plan, traversal, source, test, evidence, or
foreign-Plan write scope before protected work. After the plan and graph are
canonical, upgrade the same claim to that work unit, allocate and select its
outcome, and only then expand its write paths. Subsequent `make session-start`,
`make session-heartbeat`, and supported native writes enforce selected state
without outcome flags. Set the source config back to `off` or revert the
activation commit for the recoverable rollback. This is a source-only workflow;
installing the framework does not opt a consumer into it.

## Verify The Install

From your target repo root:

```bash
python scripts/meta/check_agents_sync.py --repo-root . --check
python scripts/meta/file_context.py --json CLAUDE.md
```

From the framework repo, you can also re-run the mechanical audit:

```bash
python scripts/audit_governed_repo.py --repo-root /path/to/your/project --strict-governed
```

## Configure `meta-process.yaml`

Start with the minimum keys that are already meaningful today:

```yaml
meta_process:
  version: "1.0"

  plans:
    enabled: true
    require_tests: true
    plans_dir: "docs/plans"
    integrity:
      # off | observe | enforce
      mode: "enforce"
      contract_version: "1.0.0"
      minimum_plan_number: 1

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

Use [docs/reference/CONFIG_REFERENCE.md](docs/reference/CONFIG_REFERENCE.md) to
distinguish live keys from planned vocabulary. The template contains broader
advisory/planned fields; omit them unless you are intentionally documenting
future policy rather than configuring current script behavior. Those broader
fields now live in `templates/meta-process.future.yaml.example`.

## First Successful Workflow

From the target repo:

```bash
git checkout -b plan-1-my-feature
cp docs/plans/TEMPLATE.md docs/plans/01_my-feature.md
```

Before implementing, make sure the plan includes:

- current vs target gap framing
- references reviewed
- research basis for the slice, or an explicit statement that none was needed
- required tests declared before code starts

Then work normally:

```bash
git add -A
git commit -m "[Plan #1] implement my feature"
```

For sanctioned worktree repos, the bounded session flow is:

```bash
make worktree BRANCH=plan-1-my-feature \
  TASK="implement my feature" \
  SESSION_GOAL="broader objective" \
  SESSION_PHASE="first implementation slice" \
  PLAN=1 \
  PLAN_READINESS_COMMAND="/path/to/plan-graph-python /path/to/plan_graph.py"

make session-heartbeat BRANCH=plan-1-my-feature SESSION_PHASE="verification"
make session-status
make worktree-remove BRANCH=plan-1-my-feature
```

The same Make targets work for Codex and Claude Code. The runtime adapter
chooses the `session_id`; the tracker and claim structure stay identical.

With Planning Integrity configured, `make worktree` first resolves the
canonical default-integration tip to one full commit. It reads the plan,
`meta-process.yaml`, work graph, and approvals from that commit—not from later
worktree bytes—and retains the same revision in the claim, worktree, and
session tracker. An incomplete or malformed plan fails before coordination
mutation. A structural `pass` proves only that the plan's declared frontier and
required fields conform; it does not prove that every material area was named
or that the plan is optimal.

For an already-in-progress numbered plan with no live lane, add
`PLAN_RESUME=1`; the readiness provider must return `already_active`, and the
claim registry still performs the final no-live-owner check. In a repository
that also enforces selected outcomes, a staged planned lane that will own
specific files must use `SESSION_CLAIM_TYPE=write` plus explicit
`SESSION_WRITE_PATHS`. The broader default `program` claim is intentionally
insufficient for selection-pending write activation.

## Optional And Legacy Installer Modes

The canonical minimum installer does not yet ship every framework module.

For a bounded worktree-runtime upgrade, use the canonical installer with
`--worktree-only`. If the consumer declares an installed `enforced-planning`
dependency, this syncs wrappers and Make targets without copying a competing
package into the repository. Update the consumer's exact dependency pin and
installed environment separately through its package workflow. An unchanged
`mode:installed-package` receipt is informational, not installer drift.
For external plan ownership, the upgraded runtime and wrappers must both
support the operator guide's explicit plan-authority root/revision inputs.

- `./install.sh /path/to/your/project --worktree-only`
  - canonical bounded sync for sanctioned worktree entrypoints only
- `./install.sh /path/to/your/project --full`
  - legacy compatibility bootstrap for broader rollout surfaces
- `./install.sh /path/to/your/project --pre-commit`
  - legacy compatibility bootstrap for pre-commit-based hook distribution

Use those only when you intentionally need the older rollout surfaces. They are
not the long-term sync authority.

## Truth-Surface Tooling

Truth-surface validation and semantic review are not part of the minimum
canonical install yet.

The canonical semantic-review path is:

```bash
python scripts/review_truth_surface_semantic.py --config /path/to/your/project/scripts/truth_surface_drift.yaml
```

Use that directly from the framework repo, or use the legacy `install.sh --full`
bootstrap only if you deliberately want the older broader installed surface.

## Next Reading

- [PLANNING_OPERATING_MODEL.md](PLANNING_OPERATING_MODEL.md)
- [patterns/15_plan-workflow.md](patterns/15_plan-workflow.md)
- [patterns/28_question-driven-planning.md](patterns/28_question-driven-planning.md)
- [patterns/43_topic-research-synthesis.md](patterns/43_topic-research-synthesis.md)
- [docs/guides/NEW_PROJECT_SETUP.md](docs/guides/NEW_PROJECT_SETUP.md)
