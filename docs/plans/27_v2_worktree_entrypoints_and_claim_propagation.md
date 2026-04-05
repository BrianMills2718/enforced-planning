# Plan #27: V2 Worktree Entrypoints And Claim Propagation

**Status:** ✅ Complete
**Type:** implementation
**Priority:** High
**Blocked By:** None
**Blocks:** truthful governed-repo lane creation through the canonical v2 coordination surface

---

## Gap

The canonical coordination model is now v2 claim-first, but the sanctioned
governed-repo worktree interface still routes through the legacy
`scripts/meta/worktree-coordination/check_claims.py` surface. That leaves the
installer, Makefile template, governed-repo audit, and operator docs out of
agreement with the current package-backed claim model.

There is also a concrete runtime bug in the installed surface: the installed
`create_worktree.py` looks for a sibling
`scripts/meta/check_coordination_claims.py` entrypoint, but the installer does
not sync that file into governed repos.

## Desired Outcome

Governed repos created or upgraded by the canonical installer expose one
sanctioned worktree path that routes through the package-backed v2 claim CLI.
The installed surface, the audit, and the operator docs all agree on that
contract.

---

## Research

- `templates/Makefile.worktree.block.template`
- `scripts/install_governed_repo.py`
- `enforced_planning/governed_repo_audit.py`
- `scripts/check_coordination_claims.py`
- `scripts/worktree-coordination/create_worktree.py`
- `tests/test_install_governed_repo.py`
- `tests/test_audit_governed_repo.py`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/guides/NEW_PROJECT_SETUP.md`
- `README.md`
- `GETTING_STARTED.md`
- `docs/plans/24_coordination-state-packageization-and-consistency-gate.md`
- `docs/plans/25_lane-model-and-active-lane-registry.md`
- `docs/plans/26_claim-session-auto-hydration-and-weak-lane-remediation.md`

---

## Decisions Pre-Made

| Topic | Decision | Why |
|---|---|---|
| Installed claim CLI | `scripts/meta/check_coordination_claims.py` is the canonical installed entrypoint | Matches the package-backed v2 coordination surface and the path already expected by installed `create_worktree.py` |
| Legacy surface | `scripts/meta/worktree-coordination/check_claims.py` remains compatibility-only | Avoids treating two installed claim surfaces as co-equal authorities |
| Default worktree claim type | `make worktree` creates a v2 `program` claim by default | Keeps lane visibility and health metadata truthful without inventing fake broad repo-root write ownership |
| Agent identity | `WORKTREE_AGENT` auto-detects from known runtime env vars and stays overridable | Works for supported tools while still failing loud outside those runtimes |
| Audit migration | Governed-repo audit accepts the new canonical installed path and the legacy one as compatibility | Lets the framework move forward without instantly breaking every previously governed repo |

---

## Scope

In scope:

- installer support-file sync
- sanctioned Makefile worktree block
- governed-repo audit contract
- operator/setup/framework docs that describe the installed worktree surface
- focused installer/audit tests

Out of scope:

- removing all legacy compatibility scripts from the framework repo
- retrofitting every already-governed repo in the ecosystem in this same slice
- automatic narrow write-path claim capture during worktree creation

---

## Files Affected

- `README.md`
- `GETTING_STARTED.md`
- `ROADMAP.md`
- `docs/guides/NEW_PROJECT_SETUP.md`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/27_v2_worktree_entrypoints_and_claim_propagation.md`
- `docs/plans/CLAUDE.md`
- `enforced_planning/governed_repo_audit.py`
- `scripts/check_coordination_claims.py`
- `scripts/install_governed_repo.py`
- `templates/CLAUDE.md.scripts`
- `templates/Makefile.worktree.block.template`
- `tests/test_audit_governed_repo.py`
- `tests/test_install_governed_repo.py`

---

## Acceptance Criteria

1. `scripts/install_governed_repo.py --write` installs
   `scripts/meta/check_coordination_claims.py` into governed repos.
2. The sanctioned Makefile block uses the v2 claim CLI shape:
   `--claim --agent --project --scope --intent --branch --worktree-path`
   instead of legacy `--claim --id --task`.
3. The sanctioned Makefile block releases claims using
   `--release --agent --project --scope`.
4. The governed-repo audit recognizes the new installed canonical claim
   entrypoint and no longer requires the legacy installed path as canonical.
5. Focused installer/audit tests pass.
6. The operator docs clearly state that `make worktree` creates a healthy v2
   program claim by default and that the installed canonical claim entrypoint is
   `scripts/meta/check_coordination_claims.py`.

---

## Required Tests

| Command | What It Verifies |
|---|---|
| `PYTHONPATH=. pytest -q tests/test_install_governed_repo.py tests/test_audit_governed_repo.py` | Installer and governed-repo audit agree on the new installed coordination surface |
| `python scripts/self_test.py --docs` | Touched docs and plans remain internally coherent |
| `python scripts/self_test.py --install` | The canonical installer still bootstraps a governed repo cleanly |
| `python scripts/check_markdown_links.py README.md GETTING_STARTED.md docs/guides/NEW_PROJECT_SETUP.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/plans/CLAUDE.md docs/plans/27_v2_worktree_entrypoints_and_claim_propagation.md` | Touched docs link cleanly |

---

## Verification

- `PYTHONPATH=. pytest -q tests/test_install_governed_repo.py tests/test_audit_governed_repo.py`
- `python scripts/self_test.py --docs`
- `python scripts/self_test.py --install`
- `python scripts/validate_plan.py --plan-file docs/plans/27_v2_worktree_entrypoints_and_claim_propagation.md --warn-only`
- `python scripts/check_markdown_links.py README.md GETTING_STARTED.md docs/guides/NEW_PROJECT_SETUP.md docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md docs/plans/CLAUDE.md docs/plans/27_v2_worktree_entrypoints_and_claim_propagation.md`

## Completion

- [x] Installer syncs `scripts/meta/check_coordination_claims.py`
- [x] Sanctioned Makefile worktree block uses the v2 claim CLI
- [x] Governed-repo audit matches the new installed contract
- [x] Operator/setup docs reflect the canonical installed surface
- [x] Focused verification passes
