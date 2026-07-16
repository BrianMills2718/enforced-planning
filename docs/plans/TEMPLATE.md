# Plan #N: [Name]

**Status:** Planned
**Type:** implementation  <!-- implementation | design -->
**Priority:** High | Medium | Low
**phase_ref:** "Phase X.Y"  <!-- roadmap phase -->
**goal_ref:** "goal-id"     <!-- see vision/08_GOAL_TAXONOMY.md -->
**adrs_referenced:** []     <!-- e.g. ["ADR-0010"] -->
**research_citations:** []  <!-- e.g. ["agent_memory:sm-0123"] -->
**Landscape disposition:** linked  <!-- linked | inline | exempt-trivial -->
**Blocked By:** None
<!-- Dependency format:
  - #N              same-project plan reference (checker validates it resolves)
  - project#N       cross-project plan reference (checker validates project + plan exist)
  - #N — condition  plan ref with human-readable condition (condition not parsed)
  - [future] desc   conceptual/aspirational block, not a real plan reference
  Examples:
  - #5 — extraction pipeline must be proven first
  - llm_client#17 — structured output API must ship
  - [future] improved benchmark infrastructure
-->
**Blocks:** None

---

## Gap

**Current:** What exists now

**Target:** What we want

**Why:** Why this matters

---

## User Outcome

> **REQUIRED for non-trivial implementation plans.** In one plain-language
> sentence, state what a user, operator, or consuming system can do when this
> slice succeeds. Supporting infrastructure is not the outcome.

[The user can ...]

---

## Canonical Behavioral Example

> **REQUIRED for non-trivial implementation plans.** Preserve the smallest
> representative example that would expose a false completion claim. Attempt or
> replay it before reviewing substrate evidence.

**Starting input/state:** [smallest representative input]

**Action:** [what the user/operator/system does]

**Expected observable result:** [specific externally inspectable behavior]

**Behavioral evidence:** Unobserved | fixture | test | observed real slice

**Substrate/process evidence:** [schemas/tests/traces/governance that support but do not replace the behavior]

**Failure signal:** [what exact output proves the outcome still does not work]

---

## References Reviewed

> **REQUIRED:** Cite specific code/docs reviewed before planning.
> For any project with prior session history, run memory recall first:
> `agent-memory recall '{topic}' --project {project}` (ADR-0010)

- `src/example.py:45-89` - existing implementation
- `docs/architecture/current/example.md` - current design
- `CLAUDE.md` - project conventions
- Memory context: `agent-memory recall '{topic}' --project {project}` — N findings

---

## Research Basis For This Slice

> **RECOMMENDED for all plans; REQUIRED for design, cross-project, or
> externally-informed work.**
> Use this for dated investigations, topic syntheses, external sources, or an
> explicit research skip statement.

- `investigations/cross-project/2026-04-04-example.md` - investigation that informed this slice
- `research/orchestration/SYNTHESIS.md` - reusable topic conclusion
- `https://example.com/prior-art` - external prior art

If no additional research beyond repo-local references was needed, write:
`No additional research beyond References Reviewed.`

If this slice materially relies on prior agent-session findings, record those
IDs in `research_citations` using `agent_memory:<entry_id>`. Use this section
for repo-local, investigation, synthesis, and external references as usual.

---

## Landscape And Prior Art

> **REQUIRED for non-trivial work before requirements and architecture
> stabilize.** Choose one disposition in the plan header:
> - `linked`: link a dated landscape artifact or external source here;
> - `inline`: include explicit `Alternatives` and `Project implications` below;
> - `exempt-trivial`: include an explicit `Reason` for a local, reversible change.

- `docs/research/YYYY-MM-DD-topic-landscape.md` - retained comparison and recommendation

**Alternatives:** Adopt, extend, build, buy, defer, or reject the relevant options.

**Project implications:** State which assumptions, requirements, boundaries,
architecture, ADRs, or plan decisions change because of the comparison.

**Refresh trigger:** Name the date, dependency change, new evidence, or decision
that requires this landscape to be reviewed again.

**Decision method:** Resolve alternatives from goals, requirements, failure
modes, boundaries, reversibility, and established evidence by default. A
blocking decision does not itself justify a bakeoff. Add comparative evaluation
only for an irreducibly empirical uncertainty when candidates meet a common
minimum capability contract, the result can change the decision, and testing is
cheaper than choosing behind a replaceable boundary. If fair comparison requires
fully building and polishing multiple options, make the reversible choice and
validate it against its own requirements.

---

## Modality Assessment

> **REQUIRED for non-trivial design or bounded implementation plans.** Classify
> each meaningful part before choosing a planning protocol.

| Part | Mode | Why | Planning Treatment |
|------|------|-----|--------------------|
| `known-contract-surface` | Deductive / plan-first | Correctness and failure modes are predictable. | Specify contracts, tests, acceptance criteria, and failure modes before implementation. |
| `unknown-behavior-surface` | Exploratory / ladder | Behavior is emergent or parameter values would be guesses. | Build the cheapest instrument, define the readout, and preserve step-down to concrete cases. |
| `mixed-surface` | Hybrid | Architecture is knowable, but some parameter/effect must be learned. | Gate the known contract; instrument the unknown part until it can be promoted. |

**Exploratory readout:** What observable signal will end, redirect, or promote
the exploration?

**Step-down path:** How will a failing aggregate, metric, or gate lead back to
the concrete cases that explain it?

---

## Multi-Repo Coordination

> **Required for plans that touch more than one repository.** Delete this section
> for single-repo plans.

| Repo | Files Modified | Merge Strategy |
|------|---------------|----------------|
| `repo-a` | `src/file.py` (modify) | Merge first |
| `repo-b` | `src/other.py` (create) | Merge after repo-a |

**Coordination notes:** e.g., "repo-b Step 3 reads the output of repo-a Step 2;
sequence strictly."

**Write-claim footprint:** e.g., "claim `repo-a/src/file.py` and `repo-b/src/other.py`;
release both before handing off."

---

## Capabilities

> **REQUIRED if this plan creates or modifies callable functions that other projects use.**
> Each capability is simultaneously: a feature, a tool, a boundary, and a notebook cell.

| Capability | Input Schema | Output Schema | Producer | Consumer(s) | Cost Tier |
|-----------|-------------|---------------|----------|-------------|-----------|
| `investigate(question)` | `str` | `InvestigationMemo` | research_v3 | grounded-research, onto-canon6 | expensive |
| `export_findings(memo)` | `InvestigationMemo` | `list[FindingExport]` | research_v3 | onto-canon6 | free |

### Capability Validation

- [ ] Input/output schemas defined as Pydantic models with Field(description=...)
- [ ] Each capability registered in tool registry (@tool) or contract registry (@boundary)
- [ ] Schema validation passes between producer and consumer
- [ ] Journey notebook has a cell for each capability

> Skip this section for internal-only changes that don't create callable capabilities.

---

## Files Affected

> **REQUIRED:** Declare upfront what files will be touched.

- src/example.py (modify)
- src/new_feature.py (create)
- tests/test_feature.py (create)

---

## Plan

### Critical Path Classification

> Classify every increment. Before the canonical example is observed, only
> `vertical` and reproduced `direct_blocker` work belongs on the critical path.
> `enabler` and `hardening` completion does not advance product status.

| Increment | Class | Behavior or named blocker changed |
|-----------|-------|-----------------------------------|
| [smallest end-to-end slice] | `vertical` | [new observable behavior] |
| [reproduced failure repair] | `direct_blocker` | [exact blocker removed] |
| [supporting substrate, if justified] | `enabler` | [why it is not completion] |

### Steps

1. Create X
2. Modify Y
3. Add tests
4. Update docs

---

## Required Tests

> **REQUIRED BEFORE IMPLEMENTATION:** declare the tests and gates that will prove
> the plan. Write them first where feasible.

### New Tests (TDD)

| Test File | Test Function | What It Verifies |
|-----------|---------------|------------------|
| `tests/test_example.py` | `test_happy_path` | Basic functionality works |
| `tests/test_example.py` | `test_error_case` | Errors handled correctly |

### Existing Tests (Must Pass)

| Test Pattern | Why |
|--------------|-----|
| `tests/test_related.py` | Integration unchanged |

---

## Acceptance Criteria

> Feature-level criteria (what the plan accomplishes):
- [ ] [Feature criterion 1]
- [ ] [Feature criterion 2]

> Process criteria (quality gates):
- [ ] Required tests pass
- [ ] Full test suite passes
- [ ] Type check passes
- [ ] Docs updated

---

## Open Questions

> Optional. Use when unknowns exist before implementation. See Pattern #28.

- [ ] [Question 1] — Status: OPEN | Why it matters: [...]
- [ ] [Question 2] — Status: RESOLVED | Answer: [...]

---

## Notes

[Design decisions, alternatives considered, risks]
