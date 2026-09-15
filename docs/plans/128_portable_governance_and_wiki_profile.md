---
plan_id: "enforced-planning#128"
dependencies: []
dependencies_reviewed: "2026-09-15"
---
# Plan #128: Portable Governance And Wiki Profile

**Status:** In Progress — effective-profile resolver implemented; native runtime consumer binding active
**Type:** portable framework implementation
**Priority:** Critical
**phase_ref:** "Phase 9: Fleet Adoption and Framework Maintenance"
**goal_ref:** "portable-governed-project-wikis"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Blocked By:** None
**Blocks:** default-on governed-project knowledge navigation and second-project proof

`trace_evaluable: false # deterministic configuration, installer, and consumer behavior`

## Gap

**Current:** The installer ships relationship context, a deterministic source-derived
docstring wiki, freshness checks, and individually configurable controls. Defaults are
scattered across readers. There is no single project switch for disposable work and no
typed receipt proving whether governance and derived-wiki maintenance are on.

**Target:** One typed profile owns the master switch. Governance defaults on.
`governance.enabled: false` forces governed controls and derived-wiki checks effectively
off without deleting files or rewriting per-control settings. Re-enabling restores the
configured modes. Installer and audit expose the same result.

## User Outcome

Brian can install one portable governance/context package into any project and get an
automatically checkable derived agent wiki by default, while turning the whole system
off with one obvious setting for disposable experimentation. Canonical code, plans,
policy, tests, and evidence remain authority; the wiki remains navigation.

## Canonical Behavioral Example

**Starting input/state:** A disposable Git repository with canonical `CLAUDE.md` and no
`meta-process.yaml` is installed through `install_governed_repo.py`.

**Action:** Audit the default install, set `meta_process.governance.enabled: false`,
audit again, restore true, change one documented symbol, and check wiki freshness.

**Expected observable result:** Default reports governance/wiki enabled; master-off
reports governed controls effectively off without removing files; re-enable restores
configured modes; source change makes the wiki stale until its generator refreshes it.

**Behavioral evidence:** Focused resolver/installer tests and one executed disposable
consumer journey with a machine-readable receipt.

**Substrate/process evidence:** Exact candidate revision, installer/audit JSON, and wiki
freshness both-sign output.

**Failure signal:** Missing config defaults off; disabled profile blocks; configured
modes are lost; generated wiki becomes authority; or the journey needs a personal path.

## References Reviewed

- `CLAUDE.md`, `docs/reference/CONFIG_REFERENCE.md`, and `templates/meta-process.yaml.example`.
- `scripts/install_governed_repo.py` and `enforced_planning/governed_repo_audit.py`.
- `enforced_planning/docstring_wiki.py`, `templates/Makefile.meta`, and Plan #63.
- Project Meta `docs/ops/WIKI_AND_DOCS_POLICY.md` and the 2026-08-28 hook-message dogfood.

## Landscape And Prior Art

**Alternatives:** Adding another wiki duplicates Plan #63. A generic policy language
revives superseded Plan #71. Requiring operators to toggle every control preserves the
current error-prone state. Extend the existing installer, audit, config, and wiki seams
with one small typed resolver.

**Project implications:** Enforced Planning gains one portable configuration contract;
installed repositories retain their current files and per-control modes; Project Meta
remains policy authority. Revisit only if another client cannot express the contract.

## Capability Adoption

**Disposition: extend.** Extend existing owners; do not add another installer, policy
language, wiki format, feedback store, or authority source.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| effective project profile | config or absence | master state, effective modes, reasons | typed resolver | installer, audit, hooks |
| derived wiki maintenance | tracked source/docs | deterministic wiki/freshness result | existing docstring wiki | agents and checks |
| portable adoption receipt | disposable journey | install/off/re-enable/freshness evidence | consumer test | operator and rollout |

## Epistemic Planning Frontier

| Area | State | Current contract | Trigger or stopping rule | Downstream update |
|---|---|---|---|---|
| master semantics | fully_specifiable_now | absent/true on; false forces effective off | both-sign tests pass | config and resolver |
| per-control preservation | fully_specifiable_now | settings survive off/re-enable | round-trip passes | resolver consumers |
| wiki authority | fully_specifiable_now | generated navigation is non-authoritative | audit/docs agree | installer/audit |
| automatic trigger | exploration_required | installer generation plus freshness check | stop after consumer reveals noise | later hook slice |
| second project | conditional | disposable proof precedes named real project | resume after clean-room pass | rollout plan |

## Reassessment Contract

- **Triggers:** first consumer failure, two non-outcome increments, master-off false block,
  or discovery of an existing master-profile owner.
- **Autonomous action:** reuse the owner, narrow the consumer, preserve default/on/off.
- **Plan revision required:** master-key location, authority role, installer owner, or hard enforcement changes.
- **Human decision required:** consequential real-project choice, publication, deployment, or spend.
- **Stopping rule:** focused tests, self-test, and disposable install/off/re-enable/wiki pass.

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| resolution | Deductive | precedence is explicit | typed contract and both-sign tests |
| consumer | Empirical | installed entrypoints must run | disposable end-to-end journey |
| hard automation | Exploratory | noise requires observation | report-only here |

## Files Affected

- `enforced_planning/effective_project_profile.py`, `scripts/effective_project_profile.py` (create)
- `enforced_planning/governed_repo_audit.py`, `scripts/install_governed_repo.py` (modify)
- `templates/meta-process.yaml.example`, `docs/reference/CONFIG_REFERENCE.md` (modify)
- `GETTING_STARTED.md` (modify)
- `tests/test_effective_project_profile.py`, `tests/test_install_governed_repo.py` (test)
- `scripts/prewrite_claim_gate.py`, `enforced_planning/artifact_creation.py`,
  `enforced_planning/plan_validation.py`, `enforced_planning/hook_wiring.py`, and
  `hooks/git/pre-commit` (bind native consumers to the effective profile)
- focused prewrite, artifact-creation, hook-wiring, and pre-commit tests (test)
- `examples/owner-real-outcome-admission/plan128-runtime-{scenario,allocation,disposition}.json`
  (runtime allocation lifecycle)
- this plan, work graph, plan index, and roadmap (modify)

## Plan

1. Define the typed resolver. 2. Join installer and audit. 3. Preserve modes while
forcing effective off. 4. Run the disposable wiki journey. 5. Bind the effective
profile into native enforcement consumers. 6. Prove default-on, master-off, and
re-enabled behavior through an installed disposable project. 7. Record exact evidence.

## Critical Path Classification

**Critical-path classification: vertical.** One disposable consumer traverses install,
off, re-enable, stale detection, and refresh.

## Required Tests

- `pytest -q tests/test_effective_project_profile.py tests/test_install_governed_repo.py`
- `python scripts/self_test.py`
- one temporary installed-consumer journey using canonical CLI entrypoints
- focused native-consumer checks for prewrite, artifact creation, hook generation,
  plan validation, and pre-commit behavior

## Acceptance Criteria

1. Missing/true master enables; false disables effectively.
2. Master-off blocks no governed control and deletes no installed/configured state.
3. Re-enable restores explicit per-control modes.
4. Installer and audit expose matching machine-readable profile fields.
5. Disposable consumer detects stale derived wiki and passes after refresh.
6. Documentation keeps generated wiki non-authoritative.
7. A fresh restricted bootstrap and stale-projection recovery command are admissible;
   denials name the exact executable recovery action instead of creating a circular gate.

## Documentation Updates

Update the config reference, starter template, installer/audit output, plan index, and
roadmap. Do not create a second wiki policy.

## ADR

No ADR: existing configuration, installer, audit, and Plan #63 authority are extended.

## Implementation Approval

Authorized by the user's 2026-08-28 default-on, easy-off, derived-not-authority, and
first-dogfood decisions.

## Verification

- `pytest -q tests/test_effective_project_profile.py tests/test_install_governed_repo.py::test_install_governed_repo_write_bootstraps_minimum_repo_and_passes_audit` — 5 passed.
- Source audit resolved master governance and derived navigation enabled.
- Disposable installed-consumer journey passed: default on, master off, re-enable,
  stale wiki detection, regeneration, and fresh check.
- The broader installer file passed 42 tests and exposed three pre-existing
  dependency-closure failures; they are not evidence for or against this resolver.
- Runtime hook readers do not yet consume the master switch, so whole-stack runtime
  disablement is not yet claimed.
- A fresh Codex Plan 128 session reproduced two prewrite bootstrap failures: stale
  projection recovery blocked its own refresh command, and restricted Plan-only
  bootstrap was outcome-gated before it could define the selectable work unit. These
  observations are acceptance inputs for `pgw-02-runtime-consumer-binding`.

## Progress

- 2026-08-28: Project Meta dogfood merged as PR 977.
- 2026-08-28: restricted Plan 128 bootstrap created and existing owners confirmed.
- 2026-08-29: typed resolver, installed CLI, audit field, starter configuration,
  and default/off/re-enable focused tests implemented.
