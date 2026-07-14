# Enforced Planning — Issue Tracker

Observed problems, concerns, and technical debt for the **enforced-planning** framework itself.

Items start as **unconfirmed** observations and get triaged into confirmed issues, plans, or dismissed.

**Last reviewed:** 2026-04-04

---

## Status Key

| Status | Meaning | Next Step |
|--------|---------|-----------|
| `unconfirmed` | Observed, needs investigation | Investigate to confirm/dismiss |
| `monitoring` | Confirmed concern, watching for signals | Watch for trigger conditions |
| `confirmed` | Real problem, needs a fix | Create a plan |
| `planned` | Has a plan (link to plan) | Implement |
| `resolved` | Fixed | Record resolution |
| `dismissed` | Investigated, not a real problem | Record reasoning |

---

## Open

### MP-019: Local concern routing writes into the caller checkout

| Field | Value |
|-------|-------|
| Status | `confirmed` |
| Severity | medium |
| Reported | 2026-07-14 |

Routing a concern to another active branch without an open PR writes the inbox
file beneath the `--repo-root` supplied by the caller. From a linked worktree,
that dirties the sender checkout; from the canonical root, it dirties `main`.
Neither location is a durable target-session inbox, and the reported `ok: true`
can therefore overstate delivery.

**Next:** Define one canonical ignored cross-session inbox or route through the
coordination/session store, then add a two-worktree delivery test that proves
the target runtime can discover the message without dirtying either checkout.

### MP-018: Registered worktree residency is not a lifecycle invariant

| Field | Value |
|-------|-------|
| Status | `planned` — Plan #68 |
| Severity | high |
| Reported | 2026-07-14 |

The coordination consistency checker reports unclaimed linked worktrees only
as warnings, ordinary session status is claim-centric, and the July 9 path
migration did not disposition the historical sibling-layout backlog. Twelve
clean but claimless worktrees therefore remained registered under the retired
`<repo>_worktrees/` convention until a manual audit archived their exact remote
heads and removed the checkouts.

**Next:** Plan #68 adds a repository-local audit path, distinct sanctioned-root
classification, and tested opt-in enforcement without pretending Git can make
semantic merge/discard decisions.

### MP-017: Repository-wide Ruff target has 123 baseline errors

| Field | Value |
|-------|-------|
| Status | `confirmed` |
| Severity | medium |
| Reported | 2026-07-09 |

`make lint` reports 123 errors, primarily `E402` in package-backed
compatibility facades plus six fixable `F541` findings. It therefore cannot
currently serve as a truthful whole-repository gate. Until a dedicated cleanup
restores the gate, plans must state and run the complete affected and
installer-propagated Python closure instead of an arbitrary edited subset.

**Next:** Create a repository-wide wrapper lint cleanup plan, then restore
`make lint` as an enforceable gate.

### MP-016: Atomic closeout can delete unmerged work and lose its root anchor

| Field | Value |
|-------|-------|
| Status | `resolved` — Plan #59 |
| Severity | critical |
| Reported | 2026-07-09 |

`session-close` currently treats a clean worktree as deletion-safe and calls
`git branch -D` without proving integration or recording a non-merge
disposition. A live Plan #212 closeout also removed its worktree before branch
deletion, then failed because an updated claim lacked `repo_root` and canonical
root resolution returned the soon-to-be-removed in-repo worktree. Plan #59 adds
real-Git positive/negative controls, worktree-aware root resolution, and a
validate-before-mutate merge/disposition preflight.

**Resolution:** Plan #59 added real-Git merge and non-merge controls, safe
default deletion, explicit recovery/discard evidence, in-repo canonical-root
resolution, completed claim audit history, and installer propagation. The 44
focused lifecycle/installer/location tests, framework self-test, ruff, and
strict mypy checks pass.

### MP-014: Default terminology check points to a missing generated pack/generator

| Field | Value |
|-------|-------|
| Status | `confirmed` |
| Severity | medium |
| Reported | 2026-07-08 |
| Next Step | Create a plan to either generate `generated/vocab_pack.jsonl` in enforced-planning or point the terminology linter at the canonical ecosystem vocab pack. |

`python scripts/check_terminology.py --glob '**/*.md'` fails before scanning
because `generated/vocab_pack.jsonl` is absent and the suggested
`scripts/generate_vocab_pack.py` entrypoint does not exist in this repo.

---

### MP-015: Full pytest has pre-existing governed-repo audit failures

| Field | Value |
|-------|-------|
| Status | `confirmed` |
| Severity | medium |
| Reported | 2026-07-08 |
| Next Step | Create a focused plan to reconcile audit classification expectations with the current `audit_governed_repo.py` behavior, and separately harden `scripts/meta/render_agents_md.py` import-root detection. |

`PYTHONPATH=. python -m pytest tests/test_audit_governed_repo.py -q` fails in
the clean primary checkout with 7 audit-classification failures. Plain
`python -m pytest tests/test_agents_sync.py -q` also fails in the primary
checkout because `scripts/meta/render_agents_md.py` calculates its import root
as `scripts/` instead of the repo root when executed by path.

---

## Resolved

### MP-003: Large scripts untested

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

Dedicated test files now exist for the plan/governance scripts that previously
lacked direct coverage, including `parse_plan.py`, `complete_plan.py`,
`sync_plan_status.py`, and `check_plan_tests.py`.

---

### MP-004: Claude-Code-specific hooks not disclosed in README

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | low |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

The top-level docs now explicitly describe the support matrix: Claude Code has
the strongest native hook surface, while other tools use generated `AGENTS.md`
and deterministic validators.

---

### MP-005: meta-process.yaml.example has unimplemented config keys

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | low |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

The config surface is now split: `templates/meta-process.yaml.example` is the
minimal functional starter surface, while
`templates/meta-process.future.yaml.example` carries broader planned/advisory
vocabulary.

---

### MP-006: TRAYCER_COMPARISON.md at wrong location

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | low |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

The repo root no longer carries the stray research document that triggered this
issue.

---

### MP-007: Planning hierarchy defined in 3+ places with variations

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

`PLANNING_OPERATING_MODEL.md` is now explicitly canonical, Pattern 42 is the
compressed view, and the adoption docs point back to the canonical source
instead of trying to redefine the hierarchy independently.

---

### MP-008: docs/ops/ has stale sprint documents cluttering root

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | low |
| Reported | 2026-04-03 |
| Resolved | 2026-04-04 |

The earlier `OVERNIGHT_SPRINT_*` and `TRUTH_SURFACE_*_TODO` clutter was moved
out of the root operator surface. Those retired records are recoverable through
`~/archive/enforced-planning/wiki/log.md`. Remaining `docs/ops/` files are a
much smaller set of operator artifacts and sprint records.

---

### MP-011: Adoption docs disagree on installed paths, config keys, and support model

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | high |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

`README.md`, `GETTING_STARTED.md`, `docs/guides/NEW_PROJECT_SETUP.md`, and
`hooks/README.md` now agree on the canonical installer, installed paths,
support matrix, and config vocabulary.

---

### MP-012: Top-level docs still over-center `agent_ecology2`

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

Top-level docs now keep `agent_ecology2` as provenance only instead of using it
as the explanatory frame for adoption.

---

### MP-013: Roadmap and plan queue do not form a compendious forward-looking status surface

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

The roadmap and plan index now expose the live execution queue directly instead
of relying on stale "what's next" prose.

---

### MP-009: Installer authority split between `install.sh` and `install_governed_repo.py`

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | high |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

`scripts/install_governed_repo.py` is now the canonical governed-repo
installer/upgrader. `install.sh` delegates the default path and clearly scopes
legacy compatibility modes.

---

### MP-010: Two live semantic truth-surface review stacks

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | high |
| Reported | 2026-04-04 |
| Resolved | 2026-04-04 |

The config-driven semantic review path is now canonical:
`scripts/review_truth_surface_semantic.py --config ...`. The repo-wide
`review_truth_surfaces.py` path remains only as a deprecated compatibility
wrapper, and promotion now consumes canonical append-only review history.

---

### MP-001: Plan #12 file missing from docs/plans/

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | medium |
| Reported | 2026-04-03 |
| Resolved | 2026-04-03 |

`docs/plans/CLAUDE.md` index listed Plan #12 as complete but the file didn't exist.
**Fix:** Created `docs/plans/12_cross-repo-plan-registry.md` (Phase 1b of sprint).

---

### MP-002: verify_coupling.py API mismatch

| Field | Value |
|-------|-------|
| Status | `resolved` |
| Severity | high |
| Reported | 2026-04-03 |
| Resolved | 2026-04-03 |

`_load_llm_client()` imported `from llm_client import complete` which doesn't exist.
Same bug previously fixed in `review_truth_surfaces.py`.
**Fix:** Changed to `call_llm_structured`; updated `verify_coupling()` to use `response_model=`
and unpack `(judgment, _llm_result)` tuple. Updated 3 test mocks. 288 tests pass.

---

## Dismissed

(No dismissed items yet.)
## 2026-07-09 — broad test suite has eight unrelated governance/worktree failures

`PYTHONPATH=/home/brian/projects/enforced-planning pytest -q` after Plan #62
reported 538 passed, 1 skipped, and 8 failed. Seven failures are governed-repo
classification/read-gating fixture expectations; one is legacy
`<repo>_worktrees/<branch>` canonical-link fallback. Diagnose these separately
before claiming the entire repository green.

Update 2026-07-09 (audit): the failing count is not stable — a full-suite run
also surfaced up to four additional `tests/test_agents_sync.py` failures (total
8–12) that do not reproduce when that file is run alone, indicating a
test-isolation/ordering issue in the agents-sync fixtures. Still unrelated to
the clean-room work. The clean-room targeted suite passes 30/30 (three new
audit negative controls: tampered loop-spec on run and verify, and a
root-inside-projects verify that no longer crashes).
