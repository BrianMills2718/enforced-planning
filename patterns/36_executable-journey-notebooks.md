# Pattern #36: Executable Journey Notebooks

**Complexity:** Medium
**Prerequisites:** Pattern #03 (Testing Strategy), Pattern #10 (Doc-Code Coupling), Pattern #15 (Plan Workflow), Pattern #34 (Engineering Workflow)

## When Is a Notebook Required?

> **Canonical threshold:** [`../PLANNING_OPERATING_MODEL.md`](../PLANNING_OPERATING_MODEL.md)
> Compression Rules → "When Is a Journey Notebook Required?" — this pattern mirrors that
> definition. When they conflict, the POM wins.

A journey notebook is **required** when:
- Implementation spans ≥ 2 distinct phases or stages (e.g., parse → validate → store)
- AND at least one of: ≥ 2 scripts/modules being created or significantly modified;
  work crosses a subsystem or repo boundary; phase sequence has non-obvious
  output-to-input dependencies

**Optional but recommended** for a single linear script with clear input/output.

**Never required** for trivial changes (≤ 20 lines, no new APIs) or single-file fixes.

---

## Problem

Planning documents, code, tests, and notebook explorations often drift apart:

- plans describe phases, but there is no concrete way to step through them
- notebooks become one-off scratchpads instead of durable process artifacts
- unfinished phases disappear into prose instead of showing their intended input/output contracts
- later stages cannot be inspected until all earlier infrastructure is fully built
- humans trying to understand "what the system actually does" have to read many large files

This is especially painful for AI-assisted systems with multi-stage pipelines:

- natural language → intermediate artifact
- intermediate artifact → refined contract
- contract → generated code or actions
- generated result → validation or evidence

Without a disciplined notebook representation, teams lose three things at once:

1. **understanding** — the system is hard to inspect end to end
2. **planning quality** — phase boundaries stay vague until implementation
3. **verification discipline** — there is no visible way to tell which phases are real, stubbed, or still only planned

## Solution

Use **one notebook per end-to-end user journey** as an **executable phase specification**.

The notebook is not the runtime. It is the clearest human-readable rendering of:

1. the journey's phases
2. the input and output artifact for each phase
3. the acceptance criteria for each phase
4. the current implementation mode for each phase
5. the expected output shape even when a phase is not fully implemented yet

The notebook should stay runnable from the beginning, even if some phases are not yet implemented, by making unfinished phases emit **explicit provisional artifacts** rather than blocking the whole journey.

### Core idea

For each phase in a journey:

1. define the input artifact
2. define the output artifact
3. define what counts as pass/fail
4. define the current execution mode
5. run the phase through either:
   - a live implementation
   - a dry-run implementation
   - a fixture/golden artifact
   - a stub implementation
   - a planned-only pseudocode block

This creates a **continuous notebook** where later sections can still run even if an earlier phase is unfinished, because the earlier phase still emits a contract-shaped provisional artifact.

### What this is not

- Not a license to keep critical implementation only in notebooks
- Not proof that a phase works just because the notebook runs
- Not a replacement for plans, ADRs, tests, or evidence artifacts

The notebook is a **journey representation**, not the sole source of truth.

### Workspace and archive truthfulness

Journey registries and notebook-facing validators must resolve paths correctly
from both the main repo checkout and `*_worktrees/*` checkouts. When a linked
supporting document has moved to archive, the registry should point to the real
archived source rather than a dead former active path.

## Key Concepts

### 1. One notebook per user journey

A "journey" means a real end-to-end capability from user input to user-visible result.

Examples:

- For a compiler-like system: `natural language → working code → validation evidence`
- For an LLM utility library: `request embeddings`, `run structured extraction`, `run workspace agent`

Do **not** split one journey into many notebooks just because it has many phases.
Split only when a phase deep dive becomes too large for the main notebook.

### 2. Phase sections, not isolated cells

Each phase should be a **section of cells**, not necessarily one cell.

Recommended phase section structure:

1. markdown: purpose
2. markdown: `input -> output`
3. markdown: acceptance criteria
4. markdown: current status and execution mode
5. code: load/build input artifact
6. code: run phase
7. code: inspect/assert output artifact
8. markdown: current gap or promotion path

### 3. Execution modes

Every phase should declare one of these modes explicitly:

| Mode | Meaning |
|------|---------|
| `live` | Real implementation executes now |
| `dry_run` | Real planning/preparation executes, but expensive or external execution is skipped |
| `fixture` | A committed golden/reference artifact stands in for a real run |
| `stub` | A provisional implementation emits the intended artifact shape |
| `planned` | Only pseudocode/specification exists; no executable artifact yet |

This prevents false confidence. A runnable notebook section is not automatically a proven phase.

### 4. Status vs execution mode

Track both:

| Field | Example values |
|------|-----------------|
| `status` | `planned`, `partial`, `proven` |
| `execution_mode` | `planned`, `stub`, `fixture`, `dry_run`, `live` |

Why both?

- `status` tells you maturity
- `execution_mode` tells you how the notebook is currently producing artifacts

Example:

- status = `partial`
- execution_mode = `stub`

This means the phase exists in the journey and can be inspected, but it is not yet proof-worthy.

### 5. Explicit provisional artifacts

If phase 3 is unfinished but phase 4 should still run, phase 3 must emit an explicit provisional artifact.

Bad:

- phase 4 reads hidden notebook state
- phase 4 silently invents what phase 3 should have produced

Good:

- phase 3 outputs a stub/fixture artifact with the same schema the real phase will later produce
- phase 4 consumes that artifact normally

This rule makes notebook continuity honest.

### 6. Planning mode vs proof mode

The same notebook can support both:

- **Planning mode**
  - stub/fixture phases are allowed
  - focus is understanding, design, and schema shaping
- **Proof mode**
  - proof-critical phases must be live
  - notebook should fail loudly if a required phase is still stubbed

This separation avoids pretending that design-oriented notebook runs are benchmark evidence.

## Alignment Model

Executable journey notebooks work best when three artifacts stay aligned:

1. **Planning docs**
   - narrative, architecture, rationale, tradeoffs
2. **Journey notebooks**
   - human-readable phase walkthrough with runnable sections
3. **Machine-readable registry**
   - structured metadata linking phases to code, tests, docs, and evidence

The notebook should never be the only place phase contracts live.

### Recommended alignment triangle

| Layer | Purpose | Format |
|------|---------|--------|
| Planning docs | Why the journey and phases exist | Markdown |
| Journey notebook | How the journey flows end to end | Jupyter notebook |
| Phase registry | What each phase is linked to | YAML or JSON |

## Files

| File | Purpose |
|------|---------|
| `notebooks/00_master_<journey>.ipynb` | Primary end-to-end notebook for one user journey |
| `notebooks/<phase>_deep_dive.ipynb` | Optional notebook for one complex phase |
| `notebooks/notebook_registry.yaml` | Machine-readable registry of journeys, phases, statuses, links, and evidence |
| `docs/plans/*.md` | Planning and acceptance rationale that the notebook renders operationally |
| `tests/` | Real proof of live phases |
| `evidence/` | Durable measured outputs produced by later phases |

## Setup

### 1. Choose the journey

Define one real end-to-end capability:

- not one helper function
- not one module
- not one architecture layer
- a real user-visible journey

Example:

```text
raw natural language -> refined intermediate representation -> blueprint ->
generated code -> runtime acceptance -> evidence
```

### 2. Define the phase list

For each phase, write down:

1. phase id
2. phase title
3. input artifact
4. output artifact
5. acceptance criteria
6. current status
7. current execution mode

### 3. Create a phase registry

Example:

```yaml
# notebooks/notebook_registry.yaml
journeys:
  - journey_id: nl_to_working_code
    title: Natural Language To Working Code
    notebook: notebooks/00_master_nl_to_working_code.ipynb
    status: partial
    phases:
      - phase_id: draft_ir
        title: Draft Intermediate Representation
        status: proven
        execution_mode: live
        input_artifact: raw_input
        output_artifact: draft_ir
        acceptance:
          - "Goals, assumptions, and candidate components are visible."
          - "Blocking unknowns fail loudly."
        code:
          - ac11/discovery_ir.py
        tests:
          - tests/test_discovery_harness.py

      - phase_id: refine_ir
        title: Critique, Revise, Freeze
        status: proven
        execution_mode: live
        input_artifact: draft_ir
        output_artifact: refined_ir
        acceptance:
          - "Critique issues are recorded."
          - "Revision history is explicit."
          - "Freeze fails when blockers remain."
        code:
          - ac11/discovery_refinement.py
        tests:
          - tests/test_discovery_refinement.py

      - phase_id: blueprint
        title: Freeze Blueprint
        status: partial
        execution_mode: fixture
        input_artifact: refined_ir
        output_artifact: blueprint
        acceptance:
          - "Blueprint is the canonical contract."
        code:
          - ac11/blueprint_v2.py
```

### 4. Build the journey notebook around the registry

Each phase section should:

1. show the intended contract
2. show the current mode
3. run the current implementation or placeholder
4. inspect the resulting artifact
5. state what must change for promotion to the next mode

### 5. Keep the whole notebook runnable

This is the key rule:

- later phases may depend on earlier unfinished phases
- but only through explicit provisional artifacts

Never through hidden notebook state or silent fallbacks.

## Usage

### Day-to-day workflow

1. open the journey notebook
2. run from the top
3. inspect which phases are `live`, `fixture`, `stub`, or `planned`
4. confirm that the output artifact of each completed phase matches expectations
5. when implementing a new phase, replace the provisional phase implementation behind the same notebook contract

### Phase promotion workflow

Typical lifecycle:

```text
planned -> stub -> fixture/dry_run -> live -> proven
```

Example:

1. **planned**
   - markdown + pseudocode only
2. **stub**
   - cell returns a hardcoded contract-shaped artifact
3. **fixture**
   - cell loads a committed reference artifact
4. **live**
   - cell runs the real implementation
5. **proven**
   - linked tests/evidence exist and the notebook can point to them

### Notebook section template

```markdown
## Phase: Refine Intermediate Representation

**Input:** `draft_ir`
**Output:** `refined_ir`
**Status:** partial
**Execution Mode:** stub

### Acceptance Criteria
1. Critique issues are explicit
2. Revision history is recorded
3. Freeze decision is visible
```

```python
# Load or construct the input artifact for this phase.
draft_ir = load_draft_ir_example()
```

```python
# Run the phase. In early development this may be a stub implementation that
# emits the correct output schema.
refined_ir = run_refine_ir_phase(draft_ir)
```

```python
# Inspect or assert the output shape.
assert "freeze_decision" in refined_ir
assert "revision_history" in refined_ir
refined_ir
```

### Sub-notebooks

If one phase becomes too large, create a deep-dive notebook for that phase.

Use this when:

- the phase has many sub-steps
- the phase needs richer debugging or exploration
- the main journey notebook is becoming hard to read

Do **not** use sub-notebooks to hide essential contracts. The master journey notebook should still summarize the phase contract clearly.

## Customization

### Systems with one main journey

Use:

- one master notebook for the whole system
- optional deep-dive notebooks per complex phase
- one roadmap notebook for long-term strategy
- one registry file for machine-readable linkage

This is a good fit for compiler-like or pipeline-like products.

### Systems with many distinct capabilities

Use:

- one master overview notebook
- one journey notebook per distinct capability
- one registry file linking all notebooks, tests, and evidence

This is a good fit for utility libraries or platforms with multiple unrelated flows.

### When to stub vs fixture

Use `stub` when:

- you want to establish the schema and plumbing early
- the output shape matters more than the concrete content

Use `fixture` when:

- you already know the exact reference artifact
- downstream phases should work against a committed golden output

Use `dry_run` when:

- the real code can plan or prepare the phase
- but running the expensive/external side is undesirable during routine notebook use

## Limitations

1. **Can create false confidence**
   A fully runnable notebook is not the same as a fully proven system. This is why status and execution mode must always be explicit.

2. **Can drift if registry/docs/notebook are not maintained together**
   The notebook should render a process, not become its only definition.

3. **Can become too large**
   Master notebooks need phase summaries, not every debugging detail. Use deep-dive notebooks when complexity grows.

4. **Not every phase is naturally executable**
   Some phases are design-oriented. For those, provisional artifacts are acceptable, but they should be labeled honestly.

5. **Requires discipline about artifact contracts**
   The value of this pattern comes from explicit input/output schemas. If phases use hidden notebook state, the pattern collapses.


## Integration with Capabilities and Data Contracts

Journey notebooks are the **executable specification** of capabilities defined in the plan template's Capabilities section. Each notebook cell corresponds to one capability from the plan's Capabilities table. A capability IS a tool IS a boundary IS a notebook cell — one definition, multiple views.

| Planning Layer | Artifact | Detail Level |
|---------------|----------|-------------|
| Plan template `## Capabilities` | Summary table | "capability X: input → output, producer → consumer(s)" |
| Journey notebook cells | Executable pseudocode → real code | Pydantic schemas, input/output shapes, contract validation |
| `@boundary` decorator in code | Runtime enforcement | Validates schemas at every call |
| `@tool` decorator in code | Agent discoverability | Registers callable capability in tool registry |
| Contract registry | Machine-readable state | Tracks all boundaries, call counts, violations |
| Dashboard `/contracts` page | Human visibility | Shows schemas, compatibility, violations |

### Schema validation cells

Between any two cells that cross a project boundary, add a **contract validation cell**:

```python
# CONTRACT CHECK: research_v3.findings → onto-canon6.import_research_v3_memo
from research_v3.loop_models import Finding
from onto_canon6.adapters.research_v3_import import ResearchV3ImportInput  # consumer schema

producer_fields = set(Finding.model_json_schema().get("properties", {}).keys())
consumer_required = set(ResearchV3ImportInput.model_json_schema().get("required", []))
missing = consumer_required - producer_fields
assert not missing, f"Contract violation: consumer needs {missing}"
print(f"✓ Contract valid: {len(consumer_required)} required fields provided")
```

These cells run in **Phase 2** (schema validation) before any implementation begins. If a schema mismatch is found, the contract negotiation happens immediately — not after weeks of coding.

### Notebook lifecycle maps to contract lifecycle

| Notebook Phase | Contract State |
|---------------|---------------|
| Phase 1: Pseudocode | Schemas proposed (Pydantic models drafted) |
| Phase 2: Schema validation | Schemas locked (validation cells pass) |
| Phase 3: Real code | `@boundary` decorators added, registry populated |
| Phase 4: End-to-end | Contracts enforced at runtime, dashboard shows green |

### Cell header convention for capabilities

Each notebook cell that implements a capability should reference the capability name from the plan's Capabilities table. This links the executable cell back to the plan, the tool registry, and the contract registry:

```python
# CAPABILITY: investigate(question) → InvestigationMemo
# Plan: docs/plans/01_research_pipeline.md
# Registry: research_v3.investigate (tool + boundary)
```

### Cell header convention for boundaries

For cells that validate schema compatibility between producer and consumer (as opposed to implementing a capability), use the boundary header:

```python
# BOUNDARY: {producer_project}.{function_name} → {ConsumerSchema}
# Contract: {contract_registry_name}
# Status: ✓ validated | ○ proposed | ✗ mismatched
# Plan: docs/plans/NN_name.md, Step N.N
```

## Relationship to Other Patterns

| Pattern | Relationship |
|---------|--------------|
| [Testing Strategy](03_testing-strategy.md) | Provides the pass/fail mindset and TDD discipline that phase sections should reflect |
| [Doc-Code Coupling](10_doc-code-coupling.md) | Helps keep notebook-backed planning and real implementation aligned |
| [Acceptance-Gate-Driven Development](13_acceptance-gate-driven-development.md) | Journey notebooks can render gate progression phase by phase |
| [Plan Workflow](15_plan-workflow.md) | Plans define the work; journey notebooks render that work as runnable phase sections |
| [Engineering Workflow](34_engineering-workflow.md) | Journey notebooks can act as the visible walkthrough surface for the workflow outputs |
| Capabilities and Data Contracts (`@tool`, `@boundary`, `BoundaryModel`) | Journey notebooks are the executable specification of capabilities and boundary contracts; each cell maps to one capability from the plan's Capabilities table |

## Origin

This pattern emerged from trying to make long AI-assisted build plans easier to understand, easier to inspect, and harder to let drift into disconnected prose. The key insight was that even unfinished phases can add value if they emit explicit provisional artifacts and stay visible inside an end-to-end journey notebook.
