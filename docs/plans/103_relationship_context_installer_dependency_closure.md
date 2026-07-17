# Plan #103: Relationship-Context Installer Dependency Closure

**Status:** Planned
**Type:** implementation
**Priority:** High
**Landscape disposition:** exempt-trivial
**Blocked By:** None
**Blocks:** project-meta#224 — report-only relationship-context adoption

## Gap

**Current:** The bounded `--relationship-context-only` installer selects the
relationship inventory, packet, impact, and wiki modules, but omits the local
`file_context` runtime that its hook preflight requires. A clean Project Meta
dry run therefore plans the intended narrow surface and then blocks with:
`missing scripts/meta/file_context.py` and
`missing enforced_planning/file_context.py`.

**Target:** The scoped installer ships the smallest complete local runtime
closure required by its selected context/hook surfaces. A clean existing
governed consumer can dry-run and write that profile without unrelated
framework synchronization, then execute the installed context and
relationship commands.

**Why:** A consumer must be able to adopt the report-only context compiler
without hand-copying dependencies, bypassing hook validation, or installing
the broader framework surface.

## User Outcome

> A repository maintainer can install the relationship-context-only profile and
> receive a runnable, bounded context surface without manually repairing a
> missing dependency.

## Canonical Behavioral Example

**Starting input/state:** An existing governed repository has `CLAUDE.md`, a
`Makefile`, and `scripts/relationships.yaml`, but has none of the local
relationship-context or `file_context` modules.

**Action:** Run
`python scripts/install_governed_repo.py --repo-root <consumer> --relationship-context-only --write`.

**Expected observable result:** The installer writes only its declared scoped
runtime, wrappers, Make block, and supported hook wiring; it reports no missing
`file_context` blocker. `make relationship-context` and the installed
`scripts/meta/file_context.py` command execute successfully.

**Behavioral evidence:** test

**Substrate/process evidence:** Exact installer action-set assertions and a
clean temporary-consumer write/run test.

**Failure signal:** A clean consumer reports a missing local `file_context`
path, or an installed context command raises an import error.

## References Reviewed

- `scripts/install_governed_repo.py:53-165, 433-716` — source manifest,
  relationship-only selector, preflight, and hook-generation flow.
- `enforced_planning/file_context.py:20-22` — direct `doc_authority`
  dependency.
- `enforced_planning/doc_authority.py:22-25` — transitive coordination and
  worktree-path dependencies.
- `enforced_planning/hook_wiring.py:15-17, 174-191` — local file-context
  requirement for a functional read/edit hook surface.
- `tests/test_install_governed_repo.py:330-423` — existing bounded-rollout
  test currently pre-seeds the missing modules and hides the consumer defect.
- `docs/plans/63_relationship_context_and_docstring_wiki.md:186-193` —
  intended narrow-rollout contract and non-destructive scope.
- Project Meta Plan #224 progress record — current reproduction in a clean
  consumer worktree.

## Research Basis For This Slice

No additional research beyond the exact repository sources above is needed.

## Landscape And Prior Art

**Reason:** This is a local, deterministic installer-selection defect. The
contract, direct import closure, failure signal, and representative consumer
are all inspectable; no external build/buy or comparative decision could change
the repair.

## Modality Assessment

| Part | Mode | Why | Planning treatment |
|---|---|---|---|
| Scoped runtime selection | Deductive | The selected modules and their imports are inspectable. | Define the minimum closure and exact action-set assertions. |
| Consumer rollout | Deductive | A clean temporary repository reproduces the failure. | Remove pre-seeded dependencies and execute the installed commands. |

**Exploratory readout:** None; behavior is deterministic.

**Step-down path:** If the clean consumer still fails, retain its exact command
and traceback, add only the named missing dependency to the declared closure,
and rerun the same fixture. Do not broaden to a full installer rollout.

## Boundaries And Contract

| Boundary | Owner | Rule |
|---|---|---|
| Scoped installer selection | `scripts/install_governed_repo.py` | `--relationship-context-only` must select the exact local runtime closure required by the profile and no unrelated framework support file. |
| Hook generation | `enforced_planning/hook_wiring.py` | Hook preflight may require `file_context`; the scoped installer must supply it before asking hook generation to run. |
| Consumer runtime | Installed `enforced_planning/` and `scripts/meta/` files | Installed wrapper commands must import and run against the consumer's own local package, not the framework source checkout. |

The closure must include the `file_context` module and its direct local import
closure (`doc_authority`, `coordination_claims`, and `worktree_paths`) together
with the package marker and corresponding `scripts/meta/file_context.py`
wrapper. Keep the existing relationship-context modules and wrappers. Do not
introduce a generic runtime dependency resolver or silently fall back to the
framework checkout.

## Non-Goals

- No hard enforcement of relationship or docstring findings.
- No full governed-repository upgrade, `AGENTS.md` regeneration, or unrelated
  hook/template synchronization.
- No change to consumer-authored `relationships.yaml` semantics.
- No Project Meta installation in this plan; that remains a report-only
  consumer decision after this repair is merged.

## Files Affected

- `docs/plans/103_relationship_context_installer_dependency_closure.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `scripts/install_governed_repo.py` (modify)
- `tests/test_install_governed_repo.py` (modify)

## Plan

1. Change the existing relationship-context consumer fixture so it starts
   without pre-seeded `file_context` files, preserving the reproduced failure
   as the negative baseline.
2. Extend the scoped selection with the explicit minimal local dependency
   closure required by the relationship-context commands and hook preflight.
3. Assert the exact bounded action set, clean write/run behavior, negative
   missing-dependency failure, and idempotence before updating the completion
   record.

### Risk-Ordered Slices

| Slice | Class | Behavior or named blocker changed |
|---|---|---|
| 1. Reproduce from a consumer with no pre-seeded file-context modules | `direct_blocker` | Locks the actual broken adoption path into a negative test. |
| 2. Declare the minimum scoped runtime closure | `vertical` | Lets the installer reach functional hook generation without broad sync. |
| 3. Write/run and idempotence checks | `vertical` | Proves the installed—not source-checkout—consumer commands work. |

## Required Tests

| Test | What it verifies |
|---|---|
| Clean scoped dry run | Reports no blocker and lists every required closure path, including `file_context` and its local imports. |
| Clean scoped write/run | Writes the same bounded set, executes `make relationship-context` and `scripts/meta/file_context.py`, and proves no framework-checkout import is needed. |
| Negative closure control | Remove one declared local dependency from the fixture or installed target; the relevant command fails loudly. |
| Scope regression | The scoped action set excludes unrelated support modules, `AGENTS.md` generation, and consumer-local files. |
| Idempotence | A second scoped dry run reports no actions. |

Run focused installer tests, Ruff and strict mypy for the touched installer, and
`python scripts/self_test.py` before claiming the repair complete.

## Acceptance Criteria

| ID | Criterion | Evidence | Target grade |
|---|---|---|---|
| C103-1 | A clean relationship-context-only dry run has no missing `file_context` blocker and names the complete declared local closure. | direct regression test | A |
| C103-2 | A clean scoped write produces runnable local context and relationship commands without a source-checkout import. | temporary-consumer execution test | A |
| C103-3 | The installer remains bounded: no unrelated framework files, AGENTS rendering, or consumer-authored relationship rewrite. | exact action-set test | A |
| C103-4 | Missing a declared local dependency fails loudly at the consuming command. | negative control | A |
| C103-5 | The second dry run is idempotent and the framework self-test remains green. | focused test + self-test | A |

## Failure And Rollback

If the closure pulls in an unexpected transitive local module, stop and add a
specific disposition before broadening the profile. If the scoped profile
cannot remain bounded, retain the report-only consumer posture and make the
broader installer an explicit future decision. Rollback is removal of the added
selection entries; no consumer state is modified until a subsequent consumer
rollout is separately authorized.

## Completion Record

Not started. Implementation is separately authorized; this plan is the
handoff for that bounded repair.

## Known Validation Baseline

`python scripts/sync_plan_status.py --check` currently reports pre-existing
index omissions for Plans #65 and #66. This packet adds its own Plan #103 index
row and must not rewrite unrelated historical index debt to manufacture a green
whole-index result. The implementing agent should run the focused Plan #103
validation and record the inherited result separately; repair the #65/#66 index
only under its own bounded authority.
