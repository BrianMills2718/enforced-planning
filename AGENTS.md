# Enforced Planning

<!-- GENERATED FILE: DO NOT EDIT DIRECTLY -->
<!-- generated_by: scripts/render_agents_md.py -->
<!-- canonical_claude: CLAUDE.md -->
<!-- canonical_relationships: scripts/relationships.yaml -->
<!-- canonical_relationships_sha256: 6d327667b0b7 -->
<!-- sync_check: python scripts/check_agents_sync.py --check -->

This file is a generated Codex-oriented projection of repo governance.
Edit the canonical sources instead of editing this file directly.

Canonical governance sources:
- `CLAUDE.md` — human-readable project rules, workflow, and references
- `scripts/relationships.yaml` — machine-readable ADR, coupling, and required-reading graph

## Purpose

Status: active

Source repo for the portable planning and governance framework.

## Commands

```bash
# Canonical governed-repo install / upgrade
python scripts/install_governed_repo.py --repo-root /path/to/project --check
python scripts/install_governed_repo.py --repo-root /path/to/project --write
python scripts/audit_governed_repo.py --repo-root /path/to/project --strict-governed

# Convenience / legacy shell wrapper
./install.sh /path/to/project
./install.sh /path/to/project --worktree-only
./install.sh /path/to/project --pre-commit
./install.sh /path/to/project --full

# Framework validation
python scripts/self_test.py
python scripts/validate_plan.py --plan-file docs/plans/NN_example.md --warn-only
python scripts/check_plan_capabilities.py docs/plans/

# Source-repo maintenance
python scripts/render_agents_md.py --stdout
python scripts/sync_plan_status.py
python scripts/complete_plan.py --plan N
python scripts/outcome_admission.py --help
python scripts/session_start.py --help
python scripts/session_heartbeat.py --help
python scripts/session_status.py --help
python scripts/prewrite_claim_gate.py --help
python scripts/check_coordination_claims.py --progress --help
python scripts/session_end.py --help
python scripts/session_finish.py --help
python scripts/session_close.py --help
python scripts/session_resume.py --help
python scripts/session_narrow.py --help

# Tests
pytest -q
make test
```

Plan #123 activates hard selected-outcome admission only in this source
repository through
`meta_process.claims.outcome_admission_mode: enforce_selected`. Session
start/heartbeat and supported native pre-write now derive the exact selected
claim state without an outcome flag and deny before mutation or success.
`make outcome-bootstrap PLAN=N ...` is the only sanctioned **planned** new-lane
path: its entire claim must resolve to one Plan-numbered bootstrap surface
before it may create the restricted worktree/session. The unplanned exceptions
are the strictly parsed maintenance-worktree and brand-new local-repository
bootstraps documented in the operator guide. Both require a native top-level
client, a safe literal branch, and `claim_type: program`; maintenance also
requires a canonical governed repository, while local initialization is
restricted to an absent direct child of a non-Git workspace and creates no
remote. Neither admits composed shell, unknown JSON fields, borrowed subagent
identity, or ordinary unclaimed mutations. An exact maintenance claim that
still matches that typed root-and-tracker contract may pass source-repository
selected-outcome admission only after the ordinary pre-write gate selects the
sole claim whose declared write paths cover every target. Generic `UNPLANNED`
claims, overlapping target authority, and mutations spanning disjoint child
claims remain denied. After the graph is canonical, bind,
allocate, select, and only then expand that same claim. The canonical
`scripts/session_start.py` and `scripts/session_heartbeat.py` own source Make
execution; their `scripts/meta/` mirrors must remain byte-identical through the
installer-declared lineage. Setting the mode to `off` or reverting the
activation commit is the recoverable rollback. This source activation does not
configure a downstream repo, execute an installer target, or establish fleet
adoption.

## Operating Rules

This projection keeps the highest-signal rules in always-on Codex context.
For full project structure, detailed terminology, and any rule omitted here,
read `CLAUDE.md` directly.

### Principles

- Governance is discriminating: checks report deterministic facts, and block
  only when the candidate can violate the protected contract and the selected
  execution mode requires blocking.
- Every repo gets the smallest stage-appropriate contract surface; development
  does not inherit coordinated or release controls solely because the framework
  can install them.
- Install is idempotent: running it twice leaves the repo in the same state
- Source truth is in this repo; installed repos are consumers of generated artifacts

### Workflow

1. Make changes to framework source
2. Run `python scripts/self_test.py` to validate
3. Run `python scripts/install_governed_repo.py --repo-root <consumer> --write` to propagate

## Machine-Readable Governance

`scripts/relationships.yaml` is the source of truth for machine-readable governance in this repo: ADR coupling, required-reading edges, and doc-code linkage. This generated file does not inline that graph; it records the canonical path and sync marker, then points operators and validators back to the source graph. Prefer deterministic validators over prompt-only memory when those scripts are available.

## References

- `PLANNING_OPERATING_MODEL.md` — canonical methodology
- `docs/plans/CLAUDE.md` — implementation plan queue
- `ROADMAP.md` — forward queue and phase map
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` — worktree and lane lifecycle
