# Implementation Plans

See `ROADMAP.md` for the full phase map and recommended priority order.

| # | Gap | Priority | Status | Blocks |
|---|-----|----------|--------|--------|
| 1 | Capabilities enforcement in plan template (`01_boundary_enforcement.md`) | High | ✅ Complete (template + pre-commit hook wired, wires into check #6) | ecosystem-ops audit, DIGIMON audit |
| 2 | Canonical Planning Operating Model (`02_canonical-planning-operating-model.md`) | High | ✅ Complete | #3, #4 |
| 3 | Static Graph / Runtime Truth Split (`03_static-planning-graph-and-runtime-truth-surface-split.md`) | High | ✅ Complete | #4 |
| 4 | Truth-Surface Drift Validation (`04_truth-surface-drift-validation-and-enforcement.md`) | High | ✅ Complete | [future] project-meta rollout |
| 5 | Validator Completion Sprint (`05_truth-surface-validator-completion-sprint.md`) | High | ✅ Complete | [future] portable rollout guidance |
| 6 | Governed Repo Adoption Pilot (`06_governed-repo-truth-surface-adoption-pilot.md`) | High | ✅ Complete | [future] workflow wiring beyond advisory |
| 7 | LLM Semantic Truth-Surface Review (`07_llm-semantic-truth-surface-review.md`) | High | ✅ Complete | — |
| 8 | Adoption Pilot Execution Sprint (`08_truth-surface-adoption-pilot-execution-sprint.md`) | High | ✅ Complete | #6, #7 |
| 9 | Scoped Validation By Repo Identity (`09_scoped-truth-surface-validation.md`) | High | ✅ Complete | [future] broader governed adoption |
| 10 | Framework Onboarding Reconciliation (`10_framework-truth-surface-and-onboarding-reconciliation.md`) | Medium | ✅ Complete | [future] consumer adoption |
| — | Relationships V2: inference engine + schema + migration (design doc, no numbered plan) | High | ✅ Complete | V2 adoption pilot |
| 11 | Agent Verification Protocol for Validated Couplings (`11_agent-verification-protocol.md`) | High | ✅ Complete | #7 |
| 12 | Cross-Repo Plan Registry (`build_plan_registry.py`, `make plan-registry`) | Medium | ✅ Complete (327 plans, 22 repos) | check_plan_deps cross-repo |

## Status Key

| Status | Meaning |
|--------|---------|
| 📋 Planned | Ready to implement |
| 🚧 In Progress | Being worked on |
| ✅ Complete | Implemented and verified |
