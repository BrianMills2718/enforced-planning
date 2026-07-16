# Planning Operating Model

> **Canonical source.** This document defines the authoritative planning hierarchy
> for the enforced-planning framework. Pattern 42 (planning-hierarchy) and Pattern 15
> (plan-workflow) are compressed views of this document. GETTING_STARTED.md is the
> adoption guide. When any of them conflict with this document, **this document wins.**

## Purpose

`enforced-planning` is not just “write a plan before coding.” It is a planning
operating model for autonomous and human-guided development. The model must tell
an agent:

- what to understand before planning
- what artifacts define enduring system shape
- what artifacts define the next bounded slice
- what must exist before code starts
- what proves the slice is done

## Core Principles

1. **Modality diagnosis before design.** Before planning a non-trivial slice,
   classify each part as deductive/plan-first, exploratory/ladder, or hybrid.
   Use plan-first contracts where consequences are predictable; use instruments
   and readouts where behavior is emergent or parameter values would be guesses.
2. **Question-driven before planning.** Unknowns are surfaced and investigated
   before committing to an implementation plan.
3. **Research should compound, not reset.** Dated investigations answer a
   specific question; topic research syntheses preserve reusable conclusions so
   future ADRs and plans can build on them.
4. **Gap-driven planning.** Plans implement an explicit delta between current
   state and target state.
5. **Capabilities and boundaries define enduring shape.** The reusable
   capability or boundary contract comes before roadmap sequencing because it
   determines what the system is trying to become.
6. **Roadmaps sequence validated gaps.** Phases exist to order major gates once
   the enduring shape is clear enough.
7. **Plans are bounded execution contracts.** They pre-make local decisions,
   define tests, and state acceptance criteria.
8. **Journey notebooks are decision-scoped projections.** When a non-obvious
   multi-stage seam needs an executable walkthrough to resolve a named review
   decision, a notebook renders the journey by importing canonical contracts
   and fixtures. It is not a second contract authority or a permanent gate.
9. **Tests and gates are pre-code artifacts.** They should be defined before
   implementation and follow TDD where feasible.
10. **Observability is part of the contract.** It is not a postscript. Long-lived
   or production-facing work is incomplete without a visibility surface.
11. **ADRs are cross-cutting decisions, not just another linear level.** They
   record durable choices whenever a capability, boundary, roadmap, or plan
   needs one, and they must record the research basis behind the choice or say
   explicitly that research was skipped.
12. **Verification is stage-aware.** Protect irreversible boundaries when they
   occur, verify the affected surface at each increment, and reserve broad
   authority and closeout suites for terminal claims. A check that does not
   protect the current decision is ceremony, not rigor.
13. **Controls follow an explicit execution profile.** Select controls from the
   claim, exposure, reversibility, and shared-state effect of the current slice.
   A specialized procedure cannot silently promote a PoC into production work.

## Execution Profiles

Every non-trivial plan declares one execution profile. The profile controls the
minimum planning and verification bundle for that slice; it does not describe
the maturity of the entire repository. A mature product can run a `poc` slice,
and one plan can promote to a stronger profile only after its stated trigger.

| Profile | Use when | Required now | Normally deferred |
|---------|----------|--------------|-------------------|
| `poc` | A reversible experiment must answer one bounded technical or product question | Frozen hypothesis and success criterion, bounded inputs/execution, focused checks, one smallest-real-path readout, and full traces before interpreting LLM output | Held-out/golden-set expansion, comparative quality thresholds or model selection, independent eval sign-off, global authority expansion, full-suite closeout, generalized infrastructure, deployment, and controls unrelated to the experiment—unless the named PoC decision is itself a quality-based kill/continue or selection decision |
| `pilot` | Representative users, data, or integrations must show that an end-to-end workflow is usable and repeatable | Explicit boundaries and contracts, representative evaluation, replayable evidence, integration checks, and an operator or agent path | Production scale, broad compatibility, and operational controls not exercised by the pilot |
| `production-internal` | Trusted operators use a long-lived capability in a controlled environment | Reliability, data integrity, recovery, actionable observability, migration/dependency handling, and the concrete access or secret protections required by its real boundaries | Public threat modeling, external compatibility guarantees, release ceremony, and distribution controls without a demonstrated need |
| `production-external` | Untrusted users, public access, distribution, or shared critical state creates external obligations | The internal-production bundle plus explicit threat model, authentication/authorization where applicable, release and rollback controls, compatibility, and operational response | Only controls shown irrelevant by a recorded boundary analysis |

Profile selection is not a security waiver. Every profile still protects secrets,
requires confirmation for destructive shared-state actions, fails loudly, retains
evidence proportional to its claims, and reviews full LLM traces before semantic
use. Additional security or release work requires a concrete boundary, threat,
distribution, legal, or recovery reason; “production” alone is not sufficient.

Plans record:

- execution profile and the claim it permits
- users/exposure, reversibility, and shared-state effect
- controls required now and controls explicitly deferred
- the observable trigger for promotion to another profile

When rules conflict, the universal protections above apply first, then the
declared execution profile, then specialized procedures. A skill may refine how
an applicable control is performed; it may not expand the slice or import a
higher profile without naming the failure mode it protects.

## The Model

This is a **partial-order dependency graph**, not a rigid one-pass waterfall.
Some artifacts are iterative, and some can be developed in parallel. What
matters is the dependency structure.

### Dependency Order

```text
North Star / Thesis
    -> Modality Diagnosis
    -> Questions
    -> Investigation Memos
    -> Topic Research Syntheses
    -> Current-State Assessment
    -> Gap Analysis
    -> Capabilities / Boundary Docs / PRD surfaces
    -> Roadmap / Phases
    -> Bounded Plan
    -> Journey Notebook (only when an executable walkthrough resolves a named decision)
    -> Tests / Gates
    -> Code
    -> Observability / Runtime evidence
```

`ADRs` cut across this flow. An ADR can be introduced after investigation,
during capability definition, during roadmap design, or during plan shaping,
provided it records a durable architectural choice.

## Artifact Roles

| Artifact | Primary question | Must exist before | Notes |
|----------|------------------|-------------------|-------|
| North star / thesis | Why does this system exist? | Roadmap | May be brief in small repos; still must exist |
| Modality diagnosis | Which parts are predictable enough to specify, and which need instruments/readouts first? | Design, investigation, or plan | Required for non-trivial design/planning. Split hybrid work: specify known contracts, instrument unknown behavior. |
| Questions | What do we need to verify first? | Investigation | Surface unknowns before planning |
| Investigation memos | What did we learn when we looked? | ADR or plan | Dated, question-specific, usually immutable |
| Topic research syntheses | What reusable conclusions already exist on this topic? | ADR, capability doc, or plan | Living topic memory; links investigations, prior art, and freshness triggers |
| Current-state assessment | What exists now? | Gap analysis | Critical for legacy repos. Must include agent-memory recall for repos with prior session history (ADR-0010). |
| Gap analysis | What delta matters now? | Roadmap or plan | Can be repeated throughout project life |
| Capabilities / boundary docs / PRD surfaces | What enduring capability or contract are we shaping? | Roadmap | Cross-project work should define this early |
| Roadmap / phases | What major gates and sequence matter? | Plan | Can be lightweight in small repos |
| Roadmap goal handoff | Which roadmap-owned goal, revision, evidence target, and governing references are entering a distinct design procedure? | Separate bounded design packet | Optional transport snapshot; never current roadmap or execution authority. See `docs/reference/PLANNING_HANDOFF_V1.md`. |
| ADRs | What durable design choice did we make? | Implementation of affected change | Cross-cutting; must include research basis or explicit skip |
| Plan | What bounded slice are we executing now? | Code | Must define acceptance criteria, required tests, and the research basis for the slice when the work is non-trivial |
| Design packet result | Which detailed-design references, delta proposals, concern dispositions, and next slices return to roadmap review? | Roadmap change based on design | Delta-only handback; roadmap implications become current only when the roadmap owner adopts them. |
| Journey notebook | Which named decision becomes clearer when this slice runs end to end? | Resolution of that decision, when no cheaper artifact suffices | Review projection only; canonical contracts and proof remain in package code, fixtures, tests, and evidence |
| Tests / gates | What counts as pass/fail? | Code | Should be predeclared and preferably written first |
| Code | What is the implementation? | Closeout | Must follow canonical plans and contracts; notebooks may render but do not own them |
| Observability | How do we see behavior and drift? | Operational use / long-running execution | Required for runtime confidence |

The roadmap/design handoff is required only when project direction and bounded
design are distinct procedures or artifacts. A trivial local change does not
need transport ceremony. The roadmap retains goal selection, priority, and
project dependency authority; the design packet owns detailed requirements,
boundaries, contracts, schema disposition, and slices.

Planning must preserve one canonical owner **per concern class and scope**, not
invent one universal concern register. Strategy, architecture, policy,
implementation, verification, and live execution concerns may have different
native authorities. Packet-local concerns must close, be promoted to their
native authority, or leave with an owner and exact resume condition.

`relationships.yaml` records reviewed artifact intent and maintenance
obligations. Inferred code relationships, live coordination state, capability
ownership, and policy applicability remain separate sources even when a
generated context view joins them. Automation may propose relationships; it
does not silently establish purpose or authority.

## What Is Strict vs. What Is Recommended

### Strict dependencies

These are hard ordering rules:

- No non-trivial design or bounded plan without a modality diagnosis:
  deductive/plan-first, exploratory/ladder, or hybrid with explicit partition.
- No bounded plan without prior investigation or explicit unresolved questions.
- No non-trivial ADR without a research basis section or explicit research skip.
- No bounded plan without current vs target framing.
- No cross-project plan without capability or boundary clarity.
- No design, cross-project, or externally-informed plan without a declared
  research basis for the slice or explicit research skip.
- No implementation without declared required tests and acceptance criteria.
- No exploratory slice without a declared instrument, readout, and step-down path
  to concrete cases. The readout is the exploratory analog of an acceptance
  criterion: it defines what signal will end or redirect the exploration.
- No closeout without verification evidence.
- **No current-state assessment without a memory recall step.** For any project
  with prior session history, run `agent-memory recall '{topic}' --project
  {project}` (or equivalent MCP call) before writing the assessment. Undiscovered
  operational findings from prior sessions are a correctness risk, not a
  convenience. (ADR-0010)
- When prior agent-session findings materially inform a bounded plan, record
  the specific cited memory entry IDs in the plan header as
  `research_citations: ["agent_memory:<entry_id>"]` so provenance is visible to
  validators and reviewers.

### Recommended sequencing

These are defaults that can be compressed for trivial work:

- Define or refine the north star before expanding roadmap detail.
- Diagnose modality before choosing the planning protocol. Do not force
  plan-first detail onto emergent behavior, and do not build exploratory
  instruments for facts the field or local code already makes knowable.
- Write or refresh the relevant topic research synthesis before creating ADRs for
  cross-project or externally-informed work.
- Write capability/boundary surfaces before phase sequencing.
- Create a journey notebook before coding only when a named decision needs an
  executable view of non-obvious phase dependencies and a typed fixture, test,
  probe, diagram, or real UI is insufficient.
- Write tests before code whenever feasible; at minimum, define them before code.
- Start topic freshness metadata as advisory. Add blocking enforcement only
  after the repo has enough stable topic research to validate it meaningfully.

### Modality-Aware Planning

The operating model is plan-first only for the parts of work where design
consequences are predictable. Before design, classify the work:

| Mode | Use when | Planning artifact |
|------|----------|-------------------|
| Deductive / plan-first | Correctness and failure modes are knowable before implementation; tests can be written up front. | Contracts, schemas, pre-made decisions, required tests, acceptance criteria. |
| Exploratory / ladder | Behavior is emergent; parameter values would be guesses; the right shape cannot be predicted from theory alone. | Simplest defensible guess, cheapest instrument, readout, and step-down path from aggregate signal to concrete cases. |
| Hybrid | Architecture and contracts are specifiable, but some parameters or effects must be learned from the running system. | Partition: specify and gate the known surfaces; instrument and read out the unknown surfaces. |

This does not weaken the plan requirement. It prevents fake precision. A plan
for exploratory work still states what will be built and how progress will be
read, but it does not pretend to know a threshold or schema that only the
running system can reveal.

### LLM System Design: Pattern-First Sizing

When designing any LLM-based system, identify which composable pattern it is
**before** designing its implementation. Start at the simplest pattern that could
address the problem; add complexity only when you have measured that the simpler
pattern is insufficient.

**Anthropic's six patterns (from "Building Effective Agents", Dec 2024),
ordered simplest to most complex:**

1. **Augmented LLM** — single call with retrieval, tools, memory
2. **Prompt chaining** — sequence of calls, each processing the previous output
3. **Routing** — classify input, dispatch to specialized handler
4. **Parallelization** — independent subtasks run concurrently, outputs aggregated
5. **Orchestrator-workers** — central LLM dynamically delegates to worker LLMs
6. **Evaluator-optimizer** — generator + evaluator in a feedback loop

Most systems that feel like they need an "orchestrator" are actually prompt
chaining (2) or routing (3). Most "evaluation" systems are evaluator-optimizer (6).
The right pattern usually needs 50–200 lines of code, not a framework.

**Ecosystem shared infra by pattern:**

| Pattern | Shared infra |
|---------|-------------|
| Augmented LLM | `llm_client` |
| Prompt chaining | `llm_client` directly |
| Routing | (none yet — hand-roll) |
| Parallelization | (none yet — asyncio directly) |
| Orchestrator-workers | OpenClaw (heavy) |
| Evaluator-optimizer | `agentic_scaffolding/pipeline/` (Plan 0001) |

## New System Initialization

For a new system or major new subsystem, use this order:

1. Define the north star. **For any project with prior session history, run
   `agent-memory recall '{topic}' --project {project}` first** — operational
   findings from prior sessions are source material, not noise. (ADR-0010)
2. Diagnose the modality of each major part: deductive, exploratory, or hybrid.
3. List and investigate critical questions.
4. Write the investigation memo(s) that answer those questions.
5. Write or refresh the relevant topic research synthesis when conclusions
   should compound beyond the current task.
6. Describe the desired capabilities and boundaries.
7. Record ADRs for major architectural choices.
8. Create the roadmap and phase gates.
9. Write the first bounded plan.
10. Create a journey notebook only if it satisfies the decision-scoped threshold.
11. Define tests/gates or exploratory readouts.
12. Implement code.
13. Add observability and evidence collection.

## Legacy Repo Bootstrap

For an existing repo, bootstrap in this order:

1. Investigate the current implementation and documentation. **Run `agent-memory
   recall '{topic}' --project {project}` first** — prior session findings are
   source material, not noise.
2. Write the investigation memo(s) that preserve what was learned.
3. Write a current-state assessment (requires memory recall — see Strict
   Dependencies).
4. Define the north-star or intended target model.
5. Diagnose the modality of each meaningful gap before deciding whether it needs
   plan-first specification or exploratory instrumentation.
6. Run gap analysis against current vs target.
7. Write or refresh the relevant topic research synthesis when the findings
   should be reusable outside the immediate task.
8. Write capability/boundary docs for the enduring surfaces that matter.
9. Derive or refresh the roadmap.
10. Write the first bounded plan against the highest-value gap.
11. Create the smallest useful contract artifact, tests/gates, or exploratory
    readouts for that slice; add a notebook only when it satisfies the
    decision-scoped threshold.
12. Implement and verify.

This bootstrap order matters because legacy repos often fail when agents plan
against aspirational architecture without assessing the actual current state.

## Relationship Between Investigations, Topic Research, ADRs, Plans, and Notebooks

- **Investigation memos** capture what was learned in a dated question-driven
  pass.
- **Topic research syntheses** preserve reusable conclusions, related
  investigations, and freshness triggers for a domain.
- **ADRs** record the durable choice and point back to the evidence base.
- **Capabilities** describe enduring reusable value and typed exchange surfaces.
- **Boundary docs** describe ownership and contract edges between components or
  repos.
- **Plans** describe the next bounded change against those surfaces.
- **Journey notebooks** render a bounded change end-to-end when that executable
  view resolves a named decision. They import the real phase contracts rather
  than defining copies.

A good rule of thumb:

- If the question is “what did we learn while investigating?” use an
  investigation memo.
- If the question is “what should future work reuse on this topic?” use a topic
  research synthesis.
- If the question is “what durable choice did we make?” use an ADR.
- If the question is “what is this thing for the ecosystem?” use a capability
  or boundary doc.
- If the question is “what are we changing this week?” use a plan.
- If the question is “show me the end-to-end flow and artifacts” use a journey
  notebook.

## TDD and Verification Position

`enforced-planning` treats tests and gates as planning artifacts, not just code
artifacts.

That means:

- required tests belong in the plan before implementation starts
- journey notebooks should state phase-level acceptance conditions before live
  code is written
- notebook execution is explanatory evidence, not a substitute for ordinary
  tests or runtime evidence
- acceptance gates define what “done” means at feature level
- writing tests first is the default expectation where feasible

Not every task can be fully test-first in practice, but no task should start
implementation without a declared verification strategy.

### Verification Lanes and Gate Budgets

Every planned check belongs to one of three lanes. The plan records the lane,
trigger, decision protected, and evidence reuse key.

| Lane | Trigger | Minimum evidence | What it does not prove |
|------|---------|------------------|------------------------|
| **Boundary** | Immediately before an irreversible, shared-state, external, or one-use action | Exact input, configuration, model, budget, permission, and resource-availability checks relevant to that action | That the feature or phase is complete |
| **Increment** | Before an intermediate commit or handoff | Affected tests plus focused type, lint, contract, and documentation checks | That unrelated surfaces or the whole project remain ready to ship |
| **Terminal** | Phase closeout, merge, release, or a claim that the capability works or is done | Full relevant suite, evidence/coverage reconciliation, authority projections, trace review, and cleanup required by the claim | Future production qualities outside the declared stage |

The following rules prevent both under-verification and gate inflation:

- **Apply the declared execution profile first.** Verification lanes schedule
  the controls required by that profile; they do not add every control available
  to later profiles. Profile promotion is a separate, explicit decision.

- **Declare a gate-time budget and stopping rule per slice.** State how much
  verification time or how many gate passes are proportionate to the next
  decision. When the budget is exceeded, remove, defer, or narrow controls that
  do not protect that decision. Immediate safety, legal, data-loss, and
  irreversible shared-state risks may override the budget.
- **Name the protected decision.** For every gate, ask: if this check were
  removed, could the current decision become invalid? If not, move it to the
  appropriate later lane or delete it.
- **Reuse unchanged evidence.** Broad evidence may be reused only when its
  source commit, dependency revision or lock, configuration, and command are
  unchanged. Record those values rather than rerunning a suite by habit.
- **Freeze terminal verification as an immutable batch.** When a terminal suite
  or independent review begins, bind the protected decision and command to the
  exact clean branch head. Reject untracked files by default; any narrowly
  allowlisted operational path is part of the freeze record. Queue later ready work into the next integration
  batch; shared-authority ownership is not permission to expand the frozen
  batch. Reopen only for a blocker in the frozen scope, record why the prior
  evidence was invalidated, apply the fix, and start a new batch. Never absorb
  unrelated work and treat repeated full-suite runs as the normal remedy.
- **Separate executing dependencies from moving upstream refs.** Evidence binds
  to the exact clean revision whose bytes executed and to any required
  capability ancestry. Forward movement of an upstream branch whose new bytes
  did not execute is an observation, not execution drift. At integration,
  record the reviewed snapshot and its semantic relevance, but do not
  invalidate or rerun an exact green batch merely because later upstream
  commits exist. Assess the new range before changing the authorized execution
  pin or making a claim that includes that range. Reuse the exact batch when the
  range is irrelevant to its protected decision; invalidate it when candidate
  bytes, executing dependency bytes, required ancestry, configuration, or the
  protected claim changes. At release, use an immutable pin and block unresolved
  drift. Non-forward movement may create a separate durability or reproducibility
  blocker, but it does not retroactively change the bytes that executed. The
  invoking command must bind the required stage; a manifest cannot weaken a
  terminal gate merely by labeling itself exploratory.
- **Do not manufacture authority transitions.** A new authority pass is needed
  when permission changes, a one-use external resource is about to be consumed,
  shared state changed, or a terminal claim is issued. Producing another
  deterministic intermediate artifact does not itself create a new authority
  boundary.
- **Record LLM traces during observation; review before interpretation.** The
  exact full trace must exist when an observation is collected. Semantic
  interpretation, selection, promotion, or a claim that the pipeline works must
  wait for full-trace review. A bounded PoC may use direct exact-trace review;
  it need not first build a generic trace-gating framework.
- **Treat the full suite as terminal by default.** Run it earlier only when a
  shared contract changed, the affected surface cannot be isolated, or an
  existing repository hook requires it.

## Compression Rules

Small or trivial work can compress layers, but the compression must stay
truthful:

- a tiny internal refactor may not need a roadmap update
- a trivial local plan may not need a journey notebook
- a local implementation may not need a separate capability doc

Compression is allowed only when it does not hide a real cross-project,
multi-stage, or architectural concern.

### When Is a Journey Notebook Required?

A journey notebook is **required** only when ALL of the following are true:

- implementation spans at least two phases with a non-obvious output-to-input
  dependency;
- the plan names a concrete human or agent decision that an executable
  walkthrough will license; and
- a typed fixture, ordinary test, direct probe, diagram, or real UI cannot answer
  that decision as clearly for less maintenance cost.

A journey notebook is **optional** when it materially improves onboarding or
explanation after the contracts are already canonical elsewhere. Optional
notebooks must not become merge, implementation, or release gates.

A journey notebook is **never required** merely because work is multi-stage,
crosses modules or repositories, or exceeds a line-count threshold. It is also
not required for trivial changes, self-contained fixes, exploratory probes, or
work whose seams are already made concrete by typed fixtures and tests.

### Notebook Authority and Retirement

- The notebook is a projection of canonical package models, fixtures, and
  functions. Do not redefine schemas, digests, compiler logic, or acceptance
  invariants in cells.
- A notebook approval gate applies only to the named unresolved decision and
  expires when that decision is recorded. It must not block unrelated compiler
  or runtime implementation afterward.
- Once ordinary tests own the accepted invariant, verification targets those
  tests. The notebook may remain as a thin import-and-render walkthrough.
- Retire the notebook when it no longer changes a review decision or explains
  the journey more effectively than maintained documentation and tests.

## Relationship to Other Framework Artifacts

- `patterns/28_question-driven-planning.md` defines investigation discipline.
- `patterns/43_topic-research-synthesis.md` defines how research compounds over
  time beyond one investigation.
- `patterns/30_gap-analysis.md` defines current-vs-target framing.
- `patterns/15_plan-workflow.md` defines bounded plan structure.
- `patterns/36_executable-journey-notebooks.md` defines notebook execution
  modes and alignment.
- `patterns/42_planning-hierarchy.md` is the hierarchy pattern view of this
  operating model.
- `templates/plan.md.template` is the bounded-plan scaffold derived from this
  operating model.
- `adr/0010-agent-memory-as-planning-input.md` (ADR-0010) defines the required
  agent-memory recall step inside Current-State Assessment and New System
  Initialization. The strict dependency added in this document ("No
  current-state assessment without a memory recall step") is governed by
  ADR-0010.

## Non-Goals

This document does not define:

- specific claim, lane, or worktree lifecycle mechanics — see
  `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md` and Plans #24-#42
- session identity, heartbeat, and authority-drift contracts — implemented in
  Plans #29-#31, #38
- `relationships.yaml` schema details — see `docs/designs/RELATIONSHIPS_V2_DESIGN.md`

Note: "runtime coordination state storage" and "tracker/registry drift
validation" were listed here as future work but have since been implemented
(Plans #24-#42). Those items have been removed from this non-goals list.
