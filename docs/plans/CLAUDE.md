# Implementation Plans

See `ROADMAP.md` for the full phase map and recommended priority order.

| # | Gap | Priority | Status | Blocks |
|---|-----|----------|--------|--------|
| 1 | Capabilities enforcement in plan template (`01_boundary_enforcement.md`) | High | ✅ Complete | ecosystem-ops audit, DIGIMON audit |
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
| 13 | Rename-Safe Merge Cleanup (`13_rename-safe-merge-cleanup.md`) | High | ✅ Complete | — |
| 14 | Research-Backed ADRs and Topic Research Integration (`14_research-backed-adr-and-topic-research-integration.md`) | High | ✅ Complete | [future] project-meta topic research adoption |
| 15 | Selective Plan-10 Truth-Surface Salvage (`15_selective-plan10-truth-surface-salvage.md`) | High | ✅ Complete | — |
| 16 | Documentation and Adoption Surface Convergence (`16_documentation-and-adoption-surface-convergence.md`) | High | ✅ Complete | — |
| 17 | Governed-Repo Installer Convergence (`17_governed-repo-installer-convergence.md`) | High | ✅ Complete | — |
| 18 | Truth-Surface Semantic Review Convergence (`18_truth-surface-semantic-review-convergence.md`) | High | ✅ Complete | — |
| 19 | Multi-Tool Support Matrix and Rollout (`19_multi-tool-support-matrix-and-rollout.md`) | High | ✅ Complete | — |
| 20 | Governed-Repo Upgrade Automation (`20_governed-repo-upgrade-automation.md`) | High | ✅ Complete | — |
| 21 | Ecosystem Dashboard and Status Surfaces (`21_ecosystem-dashboard-and-status-surfaces.md`) | Medium | ✅ Complete | — |
| 22 | Framework Self-Measurement and ROI (`22_framework-self-measurement-and-roi.md`) | Medium | ✅ Complete | #21 |
| 23 | Mac Mini Transfer and Continuous Automation Bootstrap (`23_mac-mini-transfer-and-continuous-automation-bootstrap.md`) | High | ✅ Complete | — |
| 24 | Coordination-State Packageization and Consistency Gate (`24_coordination-state-packageization-and-consistency-gate.md`) | High | ✅ Complete | — |
| 25 | Lane Model and Active-Lane Registry (`25_lane-model-and-active-lane-registry.md`) | High | ✅ Complete | — |
| 26 | Claim Session Auto-Hydration and Weak-Lane Remediation (`26_claim-session-auto-hydration-and-weak-lane-remediation.md`) | High | ✅ Complete | — |
| 27 | V2 Worktree Entrypoints and Claim Propagation (`27_v2_worktree_entrypoints_and_claim_propagation.md`) | High | ✅ Complete | Canonical governed-repo propagation of the v2 coordination surface |
| 28 | Stale Claim Lifecycle and Cleanup Automation (`28_stale_claim_lifecycle_and_cleanup_automation.md`) | High | ✅ Complete | Truthful stale-lane diagnosis and bounded cleanup automation |
| 29 | Session Heartbeats and Agent Liveness (`29_session_heartbeats_and_agent_liveness.md`) | High | ✅ Complete | Heartbeat-backed session liveness for cross-agent lane ownership |
| 30 | Session Bootstrap Contract and Tracker (`30_session_bootstrap_contract_and_tracker.md`) | High | ✅ Complete | Claim-linked session intent/tracker contract |
| 31 | Session CLI and Governed-Repo Entrypoint Enforcement (`31_session_cli_and_governed_repo_entrypoint_enforcement.md`) | High | ✅ Complete | Mandatory session lifecycle in sanctioned repo flows |
| 32 | Cross-Tool Session Adapters and Adoption Rollout (`32_cross_tool_session_adapters_and_adoption_rollout.md`) | High | ✅ Complete | Codex/Claude Code adapter parity and rollout |
| 33 | Assignment-Layer Session Contract Integration (`33_assignment-layer-session-contract-integration.md`) | High | ✅ Complete | Make downstream routing consumers use canonical session identity |
| 34 | Weak-Claim Remediation And Live-Lane Migration (`34_weak-claim-remediation-and-live-lane-migration.md`) | High | ✅ Complete | Registry now healthy; no further remediation required for the current backlog |
| 35 | Queue-Based Assignment And Session Routing Architecture (`35_queue-based-assignment-and-session-routing-architecture.md`) | Medium | ✅ Complete | Freeze the long-term routing layer on top of the claim/session model |
| 36 | Research Synthesis Downstream Consistency (`36_research-synthesis-downstream-consistency.md`) | Medium | ✅ Complete | Keep portable active guidance aligned with project-meta's research-synthesis hot path |
| 37 | Plan-Bound Session Identity And Resume Lifecycle (`37_plan-bound-session-identity-and-resume-lifecycle.md`) | High | ✅ Complete | Plan-bound recovery lifecycle with resume, handoff, and abandon commands |
| 38 | Authority-Drift Reconciliation Gates (`38_authority-drift-reconciliation-gates.md`) | High | ✅ Complete | Turn authority drift into closure-blocking reconciliation debt instead of warning-only residue |
| 39 | Worktree-Aware Markdown-Link Validation And Root Resolution (`39_worktree-aware-markdown-link-validation-and-root-resolution.md`) | High | ✅ Complete | Shared checker now owns worktree/canonical-root path semantics with focused fallback tests |
| 40 | Overnight Coordination Implementation Sprint (`40_overnight-coordination-implementation-sprint.md`) | High | ✅ Complete | Freeze slice order, blocker handling, and sprint-closeout rules for the current coordination push |
| 41 | Documentation Authority Governance And Enforcement (`41_doc-authority-governance-and-enforcement.md`) | High | ✅ Complete | Freeze the canonical authority model, schema, and rollout shape for follow-on enforcement |
| 42 | Atomic Closeout And Claimed Worktree Removal (`42_atomic-closeout-and-claimed-worktree-removal.md`) | High | ✅ Complete | Make claimed-lane cleanup one sanctioned operation instead of split release/remove steps |
| 43 | Publish-Lane Safety And Dirty Primary Checkout Handling (`43_publish-lane-safety-and-dirty-primary-checkout-handling.md`) | High | ✅ Complete | Make publish worktree creation fail loud when the canonical primary checkout is unsafe |
| 44 | Interactive Startup Mode And Session-Owned Surface Policy (`44_interactive-startup-mode-and-session-owned-surface-policy.md`) | High | ✅ Complete | Distinguish interactive startup truth from autonomous routing/ownership semantics |
| 45 | Planning Operating Model Fixes — ADR-0010 follow-through (`45_planning-operating-model-fixes.md`) | High | ✅ Complete | New-system-init memory recall, non-goals update, ADR-0010 link |
| 46 | CLAUDE.md Ops-State Cleanup (`46_claude-md-ops-state-cleanup.md`) | High | ✅ Complete | Remove sprint order, fix canonical-surface contradiction |
| 47 | Phase 9 Roadmap Definition (`47_phase9-roadmap-definition.md`) | Medium | ✅ Complete | Phase 9 fleet-adoption section added to ROADMAP.md |
| 48 | ADR-0010 Guide Propagation (`48_adr0010-guide-propagation.md`) | High | ✅ Complete | WORKTREE guide + ROADMAP Phase 6 label |
| 49 | Canonical Continuous Execution Contract (`49_canonical-execution-contract.md`) | Medium | ✅ Complete | Canonical execution contract pattern in enforced-planning |
| 50 | Ecosystem Status Renderer (`50_ecosystem-status-renderer.md`) | Medium | ✅ Complete | `make ecosystem-status` builds fleet JSON + Markdown summary |
| 51 | Upgrade Automation Implementation and Write-Mode Rollout (`51_upgrade-automation-implementation-and-write-mode-rollout.md`) | High | ✅ Complete (impl shipped; write-mode rollout deferred to Mac mini pilot) | Phase 9 fleet write-mode rollout |
| 53 | Agent-Memory Research Citations And Validation (`53_agent-memory-research-citations-and-validation.md`) | High | ✅ Complete | Structured prior-session provenance field and validator coverage |
| 54 | Recursive Documentation Spine And Required-Read Closure (`54_recursive-documentation-spine-and-required-read-closure.md`) | High | 📋 Planned | [future] recursive doc-spine validation and read-gating rollout |
| 55 | Enforced-Planning Recursive Doc Spine Dogfood (`55_enforced-planning_recursive_doc_spine_dogfood.md`) | High | 📋 Planned | [future] downstream recursive doc-spine rollout to governed repos |
| 56 | Modality-Aware Planning Protocol (`56_modality-aware-planning-protocol.md`) | High | ✅ Complete | Design-plan skill folded into canonical planning methodology |
| 57 | Plan Status Index Parser Compatibility (`57_plan-status-index-parser-compatibility.md`) | High | ✅ Complete | sync_plan_status parser now supports current Implementation Plans index |
| 58 | Ops Archive Centralization (`58_ops-archive-centralization.md`) | Medium | ✅ Complete | Completed ops sprint notes moved to central archive |
| 59 | Worktree Lifecycle Disposition Enforcement (`59_worktree-lifecycle-disposition-enforcement.md`) | Critical | ✅ Complete | Merge-or-disposition preflight and safe closeout propagation |
| 60 | Loop-Engineering Clean-Room Alpha Slice 1 (`60_loop_engineering_cleanroom_alpha.md`) | High | ✅ Complete | External materialize/verify/reset alpha for shareable ecosystem fixture |
| 61 | Clean-Room Deterministic Verified Loop (`61_cleanroom_deterministic_verified_loop.md`) | High | ✅ Complete | C3/A5 loop, trace, verifier, and stop-contract proof |
| 62 | User-Neutral Ecosystem Instantiation (`62_user_neutral_ecosystem_instantiation.md`) | High | 📋 Planned | Consumer-owned inventory/config boundary for shareable adoption |
| 63 | Relationship Context and Docstring Wiki (`63_relationship_context_and_docstring_wiki.md`) | Critical | ✅ Complete (report-only rollout; hard enforcement deferred by evidence) | Portable relationship context and source-derived docstring inventory |
| 64 | Scoped Plan Completion and Repository Health (`64_scoped-plan-completion-and-repository-health.md`) | High | 🚧 In Progress | Relevant-regression completion without inheriting unrelated repository debt |

## Status Key

| Status | Meaning |
|--------|---------|
| 📋 Planned | Ready to implement |
| 🚧 In Progress | Being worked on |
| ✅ Complete | Implemented and verified |
| ✅ Complete (scoped; repository baseline degraded) | Required change evidence passed; unchanged repository debt remains visible |
