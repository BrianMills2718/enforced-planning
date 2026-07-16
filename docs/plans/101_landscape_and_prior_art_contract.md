# Plan #101: Landscape And Prior-Art Planning Contract

**Status:** Complete
**Type:** implementation
**Priority:** High
**Landscape disposition:** linked
**research_citations:** []
**Blocked By:** None
**Blocks:** [future] governed-repo landscape adoption and calibrated enforcement

## Gap

**Current:** The canonical method recommends research, but a plan can satisfy the
validator with generic references or a research-skip sentence. It does not have
a stable way to distinguish a linked landscape, a compact inline comparison, or
a justified trivial exemption. Relationship scaffolding also does not show how
landscape findings inform requirements, architecture, ADRs, and plans.

**Target:** Make landscape and prior-art review an explicit reusable planning
input, expose its disposition in plan validation without blocking existing
plans, and prove the contract on the background-agent runtime decision.

**Why:** Projects should begin from what already exists and make build, buy,
adopt, extend, and defer choices deliberately instead of hand-rolling by
default.

## References Reviewed

- `PLANNING_OPERATING_MODEL.md` - canonical artifact graph and research rules
- `docs/plans/TEMPLATE.md` - canonical authored-plan template
- `templates/plan.md.template` - installed plan template
- `templates/CLAUDE.md.root` - installed repository methodology
- `templates/relationships.yaml.minimal` - installed relationship scaffold
- `enforced_planning/plan_validation.py` - current plan validation contract
- `tests/test_validate_plan.py` - current both-sign validator coverage
- `inside-success/plan/PLANNING_METHOD.md` - consumer method with the stronger landscape flow

## Landscape And Prior Art

- `docs/research/2026-07-16-background-agent-runtime-landscape.md` - dogfood
  comparison of stable Codex execution, app-server, hooks, and a queue wrapper

**Alternatives:** Keep landscape review as unstructured prose; enforce it as a
hard gate immediately; or add a small classified contract with report-only
validation.

**Project implications:** Use the classified report-only contract. Promote any
warning to enforcement only after governed-repo dogfood demonstrates low noise,
clear remediation, and a meaningful failure it prevents.

## Research Basis For This Slice

- `https://learn.chatgpt.com/docs/non-interactive-mode` - stable non-interactive Codex execution
- `https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md` - official app-server protocol
- `https://github.com/openai/codex/issues/25552` - app-server documentation drift report
- `https://github.com/openai/codex/issues/24542` - daemon/proxy conflict report

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| Plan metadata and warnings | Deductive | Structural states and failure cases are enumerable. | Define a parser and both-sign tests first. |
| Landscape quality | Hybrid | Required shape is predictable; usefulness is judgment-dependent. | Validate structure now and defer semantic enforcement until dogfood. |

**Exploratory readout:** Dogfood plans reveal whether warnings identify missing
comparisons without pushing trivial work into unnecessary research.

**Step-down path:** Every warning reports the missing disposition, reference,
inline implication, or exemption reason directly.

## Boundaries

- This slice validates plan structure, not the truth or quality of research.
- Existing plans remain valid; new findings are warnings only.
- `relationships.yaml` records reviewed lineage and maintenance intent; it does
  not make the landscape artifact a runtime authority.
- No live consumer repository relationship file is modified in this slice.

## Contract

Every new non-trivial plan declares one landscape disposition:

- `linked`: section links at least one local artifact or external source;
- `inline`: section contains explicit alternatives and project implications;
- `exempt-trivial`: section records why additional landscape work would not
  change a small, local, reversible decision.

The validator reports missing or malformed states through its existing warning
channel. Warnings do not affect exit status.

## Files Affected

- `PLANNING_OPERATING_MODEL.md` (modify)
- `ROADMAP.md` (modify)
- `docs/plans/101_landscape_and_prior_art_contract.md` (create)
- `docs/plans/CLAUDE.md` (modify)
- `docs/plans/TEMPLATE.md` (modify)
- `docs/research/2026-07-16-background-agent-runtime-landscape.md` (create)
- `enforced_planning/plan_validation.py` (modify)
- `templates/CLAUDE.md.root` (modify)
- `templates/plan.md.template` (modify)
- `templates/relationships.yaml.minimal` (modify)
- `tests/test_validate_plan.py` (modify)

## Plan

1. Define the canonical landscape role, scope, outputs, and refresh discipline.
2. Add matching authored and installed plan-template contracts.
3. Add reviewed relationship examples from landscape to downstream artifacts.
4. Implement report-only disposition parsing and structural warnings.
5. Add both-sign tests and dogfood the contract on the background-agent choice.
6. Run focused tests and framework self-test, then publish the verified slice.

## Required Tests

| Test | What It Verifies |
|------|------------------|
| linked disposition positive | A local path or URL satisfies linked landscape structure. |
| linked disposition negative | A linked declaration without a reference warns. |
| inline disposition both-sign | Alternatives plus implications pass; either missing warns. |
| trivial exemption both-sign | A reason passes; a bare exemption warns. |
| missing/invalid disposition | Legacy omission and unknown values are visible but non-blocking. |
| CLI JSON projection | Disposition, references, and warnings are agent-readable. |

## Acceptance Criteria

| ID | Criterion | Evidence | Target grade |
|----|-----------|----------|--------------|
| C101-1 | Canonical methodology places landscape before stable requirements and architecture and defines scope, outputs, and refresh triggers. | source review + self-test | A |
| C101-2 | Authored and installed plan templates expose the same three dispositions. | template comparison test/self-test | A |
| C101-3 | Relationship scaffolding demonstrates reviewed landscape lineage to requirements, architecture, ADRs, and plans. | source review | B |
| C101-4 | Validator reports all malformed dispositions without failing otherwise valid plans. | both-sign unit and CLI tests | A |
| C101-5 | A dated background-agent landscape records alternatives, primary sources, implications, recommendation, and refresh trigger. | artifact review | B |

## Failure Modes

| Failure | Control | Next action |
|---------|---------|-------------|
| Legacy plans produce noisy warnings | Report-only rollout | Measure and narrow before enforcement. |
| Inline prose satisfies a shallow keyword check | Do not claim semantic quality | Add semantic review only after a demonstrated decision failure. |
| Research goes stale | Dated artifact plus explicit refresh trigger | Refresh when the trigger fires. |
| Landscape becomes ceremony | Allow explicit trivial exemption | Review exemptions during dogfood, not request-time blocking. |

## Promotion Gate

Hard enforcement is explicitly out of scope. A later plan may propose it only
after at least two governed projects use the contract and a coverage report
shows warning precision, remediation cost, and a concrete prevented mistake.

## Completion Record

| Criterion | Grade | Evidence |
|-----------|-------|----------|
| C101-1 | A | Canonical dependency graph, artifact table, strict sequencing, and installed methodology now place landscape before stable requirements and architecture; framework self-test passes. |
| C101-2 | A | Authored and installed plan templates expose the same three dispositions; installer self-test passes. |
| C101-3 | B | Minimal relationship scaffold now shows reviewed landscape lineage to requirements, architecture, ADRs, and plans; no consumer rollout was attempted. |
| C101-4 | A | 18 validator tests pass, including linked local/URL sources, inline and exemption both-sign controls, malformed metadata, JSON projection, and non-blocking CLI behavior. |
| C101-5 | B | Dated background-agent landscape retains primary sources, alternatives, effort/lock-in estimates, implications, recommendation, uncertainty, and refresh trigger; runtime alternatives have not been benchmarked locally. |

**Verification:** `pytest -q tests/test_validate_plan.py`, Ruff on changed Python,
strict mypy on the changed module with imports skipped, `git diff --check`, and
`python scripts/self_test.py` pass. The full suite has eight failures that
reproduce on the unchanged default branch: governed-repo fixture classification
and the retired `_worktrees` canonical-link fallback. They are outside this
plan's write scope and do not exercise the landscape contract.
