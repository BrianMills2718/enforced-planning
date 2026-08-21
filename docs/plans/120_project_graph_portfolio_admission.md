# Plan #120: Project Graph-Bound Outcome Portfolio Admission

**Status:** In Progress
**Type:** implementation (hard allocation/selection admission; write observation remains advisory)
**Priority:** Critical
**phase_ref:** "Progress-bound coding-agent continuation"
**goal_ref:** "project-graph-portfolio-admission"
**adrs_referenced:** []
**research_citations:** []
**Landscape disposition:** inline
**Execution profile:** pilot
**Overlays:** deductive, repository governance
**Blocked By:** #119
**Blocks:** mandatory outcome binding for new claims/plans and hard selected-outcome pre-write enforcement

---

## Gap

**Current:** Plans #114–#119 provide strict outcome contracts, leases, durable
selection, causal restart, runtime transfer, and append-only current-head
progress. Portfolio admission is still absent. `OutcomeContractV1.owner_class`
is caller-supplied, no contract field distinguishes product from maintenance or
external-obligation work, and no global state deliberately allocates the one
allowed slot. Project Graph revision `4db70b44` has 18 active repositories with
reviewed `repository_governance.owner_class: brian`. Letting the first selected
scenario choose among them would make accidental write order the portfolio
allocator.

**Target:** Evolve the contract family compatibly so new classed contracts
explicitly declare `product`, `maintenance`, or `external_obligation`. Resolve
project identity, active lifecycle, repository record kind, reviewed owner
class, and project predecessor relations from an exact Project Meta Git
revision. Add a separate append-only portfolio allocation ledger in existing
coordination state. One explicit allocation command binds an exact live claim,
scenario/contract, decision request, graph revision/file/record, owner class,
and WIP bucket before selection. Product allocations are capped at one active
slot per reviewed owner class; maintenance and external obligations share one
global slot. A new classed selection without its exact active allocation fails
hard. Legacy `1.0.0` contracts remain readable but cannot be described as
portfolio-admitted.

**Why:** The one-product ceiling only changes behavior if owner identity and
slot choice are external to the writer attempting the next task. Binding the
decision to Project Graph prevents self-declared owner labels and unregistered
successor repositories from resetting WIP. Keeping live allocations in the
coordination state avoids turning Project Meta into a second claim registry.

## User Outcome

Brian can deliberately allocate one product slot and one bounded global
maintenance/external-obligation slot, while a coding agent that merely creates
another project, plan, or selected scenario is rejected before it can acquire a
new classed outcome lease.

## Canonical Behavioral Example

**Starting input/state:** Exact Project Meta revision `4db70b44` identifies
`enforced-planning` as an active repository owned by `brian`. The Plan #120 live
claim contains one schema-`1.1.0` maintenance scenario and an immutable
allocation request. The portfolio ledger has no active allocation.

**Action:** First invoke selected-outcome admission without allocating the
scenario, then invoke the explicit allocation command against the exact Project
Graph revision, replay it, select the scenario, and exercise selected pre-write.
In isolated controls, attempt a second Brian-owned product allocation and an
external-obligation allocation while maintenance is active. Finally park the
authentic maintenance allocation through an append-only disposition.

**Expected observable result:** Selection first fails
`portfolio_allocation_required`. Allocation then succeeds, exact replay does
not change ledger bytes, and selection succeeds with the exact allocation
digest retained in its binding. Selected pre-write resolves the same active
allocation without changing ordinary claim authority. A second product for
owner class `brian` fails `portfolio_product_slot_occupied`; maintenance and
external-obligation allocations contend for one global bucket. Unregistered,
inactive, pointer, owner-mismatched, graph-tampered, request-changed, and
disposed allocations fail visibly. Parking releases the global slot without
deleting history.

**Behavioral evidence:** Unobserved. Acceptance requires one real Plan #120
maintenance allocate/replay/select/observe/park journey plus fixture-equivalent
product, competing-owner, global-maintenance, lifecycle, tamper, and legacy
compatibility controls.

**Substrate/process evidence:** Typed models, exact Git-object loading,
append-only atomic ledger mutation, focused tests, Ruff, mypy, plan validation,
and retained revision-bound evidence support but do not replace the journey.

**Failure signal:** A caller-supplied owner label bypasses Project Graph; the
first writer can claim a product slot without a separate allocation command;
two active products share an owner class; maintenance and external obligations
occupy separate global slots; replay rewrites the ledger; disposition deletes
history; classed selection succeeds without an exact active allocation; or the
result is described as mandatory fleet write enforcement.

## References Reviewed

- `CLAUDE.md` — exact claim, worktree, verification, and closeout authority.
- `docs/plans/119_durable_selected_outcome_progress.md` — current-head custody
  and the accepted next frontier.
- `enforced_planning/outcome_continuation.py` at `9c9d0bf2` — current schema
  `1.0.0` contract with free caller-supplied `owner_class`.
- `enforced_planning/outcome_selection.py` at `9c9d0bf2` — create-once selected
  lease and current-head resolver.
- `project-meta@4db70b44:PROJECT_GRAPH.json` — current exact project identity,
  lifecycle, predecessor, and reviewed repository-governance authority.
- `project-meta@f6091b6b:policy/proposals/2026-08-20-outcome-continuation-lease-hard-gate.yaml`
  — approved WIP ceiling and live-state ownership decision.
- `project-meta@e2cb509c:learnings/entries/lrn-20260821T063558270519Z-bb1048ff9a.json`
  — observed 18-repository Brian owner-class collision and accidental-first-writer risk.
- Memory recall: `agent-memory recall 'Project Graph outcome portfolio admission lease class' --project enforced-planning`
  returned three low-similarity historical execution summaries and no relevant
  design decision.

## Research Basis For This Slice

No web research is needed. The governing policy, authority data, failure, and
runtime seams are local and revision-bound.

## Landscape And Prior Art

| Alternative | Boundary consequence | Disposition |
|---|---|---|
| Trust `OutcomeContractV1.owner_class` | Lets the writer choose its own WIP bucket. | Rejected. |
| Put active allocations in `PROJECT_GRAPH.json` | Turns static project identity into a second live claim registry and requires commits for runtime release. | Rejected. |
| Let first successful selection acquire the slot | Makes task ordering, not a deliberate decision, the allocator. | Rejected. |
| Use `portfolio_tier` as product/maintenance class | Confuses reviewer relevance with current work authority. | Rejected. |
| Separate product, maintenance, and external-obligation ceilings | Violates the approved single global non-product slot. | Rejected. |
| Exact Project Graph authority plus separate append-only coordination allocation | Preserves authority ownership, makes allocation explicit, and composes with selected leases. | Adopted. |

**Alternatives:** The table covers self-declared identity, static-graph live
state, first-writer allocation, overloaded taxonomy, separate non-product WIP,
and the adopted split-authority model.

**Project implications:** Project Meta remains unchanged and authoritative for
static graph facts. Enforced Planning owns typed allocation and selection
admission. Existing coordination state owns live allocation events. Contract
schema `1.1.0` adds an explicit class; `1.0.0` remains legacy-readable.

**Refresh trigger:** Revisit if Project Graph changes repository-governance or
lifecycle fields, if a second live allocation consumer appears, or before
mandatory claim/worktree/pre-write rollout.

**Decision method:** This is a deductive authority and state-transition design;
the approved policy fixes the caps and ownership boundaries. Comparative
evaluation would not resolve an empirical uncertainty.

## Modality Assessment

| Part | Mode | Why | Planning Treatment |
|---|---|---|---|
| Contract version and lease class | Deductive | Backward compatibility and explicit class invariants are knowable. | Validate exact schema/class combinations. |
| Project Graph resolution | Deductive | Git revision, file bytes, record identity, lifecycle, and governance are exact. | Fail closed on every missing or mismatched field. |
| Allocation ledger and WIP caps | Deductive | The approved policy specifies one product per owner class and one global non-product slot. | Append-only events, deterministic current-state reconstruction, both-sign tests. |
| Future fleet false-block rate | Exploratory, deferred | Representative adoption behavior is not yet observed. | Keep writes advisory and retain exact pilot receipts for the next promotion decision. |

**Exploratory readout:** A later representative observe run must show genuine
product and maintenance starts allowed and synthetic competing starts rejected
before mandatory write enforcement.

**Step-down path:** Every denial reports the allocation, owner/bucket, graph
record, and exact recovery command or disposition needed.

## Capabilities

| Capability | Input | Output | Producer | Consumer |
|---|---|---|---|---|
| project authority resolution | Project Meta Git repo + exact commit + project id | digest-bound active repository authority | `outcome_portfolio` | allocation command |
| deliberate portfolio allocation | exact claim + scenario + request + graph authority + ledger | recorded/idempotent allocation or stable denial | `outcome_portfolio` | outcome CLI, selection |
| append-only allocation disposition | exact active allocation + disposition request | parked/completed event and released bucket | `outcome_portfolio` | operator closeout |
| classed selection admission | schema-1.1 contract + active allocation | selected binding with allocation digest | `outcome_selection` | selected pre-write and continuation |

All models use the repository's Pydantic boundary. No LLM call is involved.

## Capability Adoption

**Disposition: extend existing owners.** Extend `OutcomeContractV1` and the
existing selected-outcome CLI/resolver rather than create a parallel lease
framework. Reuse Project Meta's reviewed Project Graph fields without modifying
or duplicating them. Add one Enforced Planning allocation owner because no
existing capability owns live portfolio-slot events; store those events beside
the existing coordination/session state and prove the intended selection
consumer reads the accepted allocation before describing adoption.

## Boundaries And Contracts

1. `OutcomeContractV1` accepts legacy schema `1.0.0` only without a portfolio
   class and schema `1.1.0` only with one of `product`, `maintenance`, or
   `external_obligation`.
2. An exact Project Meta commit is a full Git object id. Allocation reads
   `PROJECT_GRAPH.json` from that object, never from an assumed current sibling
   checkout. The file and selected record digests are retained.
3. Eligible records are unique, `status: active`, `record_kind: repository`,
   and contain reviewed `repository_governance.owner_class`. Contract project
   and owner class must match exactly. Missing records are `unregistered` and
   cannot allocate a product lease.
4. Allocation requires an exact healthy live claim whose project equals the
   contract project, with scenario and request files inside that claim's
   worktree. The request binds the contract, class, outcome, lineage, decision
   reference, purpose, and stopping condition.
5. Allocation is a separate explicit command. Selection never auto-allocates.
6. Active `product` allocations share a bucket by Project Graph owner class.
   Active `maintenance` and `external_obligation` allocations share one global
   bucket. Exact accepted replay is byte-idempotent.
7. The ledger retains immutable allocations and dispositions. A disposition
   releases a bucket but never removes or edits the allocation. Conflicting ids,
   changed files, double disposition, malformed history, or digest mismatch
   fail before mutation.
8. A schema-1.1 selection binding retains allocation id/digest. Selection and
   later resolution require that allocation to remain exact and active. Legacy
   schema-1.0 selections preserve existing behavior and are not portfolio proof.
9. Allocation/selection denial is hard at those explicit entrypoints. Ordinary
   pre-write admission remains authoritative in this pilot; no automatic hook,
   claim, worktree, commit, installer, or fleet enforcement is claimed.
10. Cost and elapsed time are decision-inert.

## Files Affected

- `enforced_planning/outcome_continuation.py`
- `enforced_planning/outcome_portfolio.py`
- `enforced_planning/outcome_selection.py`
- `scripts/outcome_continuation.py`
- `tests/test_outcome_continuation.py`
- `tests/test_outcome_portfolio.py`
- `tests/test_outcome_selection.py`
- `examples/owner-real-outcome-observe/plan120-maintenance-scenario.json`
- `examples/owner-real-outcome-observe/plan120-maintenance-allocation.json`
- `examples/owner-real-outcome-observe/plan120-maintenance-disposition.json`
- `docs/evidence/plan120_project_graph_portfolio_admission.json`
- `docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md`
- `docs/plans/120_project_graph_portfolio_admission.md`
- `docs/plans/120_project_graph_portfolio_admission_work_graph.json`
- `docs/plans/CLAUDE.md`
- `ROADMAP.md`

## Plan

### Critical Path Classification

| Increment | Class | Behavior or blocker changed |
|---|---|---|
| Exact graph authority and allocation ledger | `vertical` | A separate command, not the first writer, chooses a bounded WIP slot. |
| Classed selected-outcome admission | `vertical` | A new selected lease cannot exist without that exact active allocation. |
| Real maintenance allocate/select/observe/park journey | `vertical` | The same operator boundary is exercised against the real graph and claim. |
| Mandatory claim/worktree/pre-write rollout | deferred direct blocker | Requires representative false-block evidence after this hard admission pilot. |

### Work Unit OPAD-01 — Graph-bound portfolio admission

Implement the schema evolution, exact Git-backed graph resolver, append-only
allocation/disposition ledger, CLI, selection integration, authentic evidence,
and truthful documentation as one owned vertical.

Pass when:

- the canonical example is observed through the real Plan #120 claim;
- exact allocation and disposition replay preserve ledger bytes;
- product and global non-product caps reject competing allocations;
- graph/owner/lifecycle/request/contract tamper and unregistered projects fail;
- schema-1.1 selection requires the exact active allocation while legacy
  schema-1.0 behavior remains green; and
- evidence names the advisory write boundary and remaining fleet gate.

## Required Tests

| Test surface | Required behavior |
|---|---|
| contract models | 1.0 rejects class, 1.1 requires controlled class |
| graph resolver | exact revision succeeds; missing/inactive/pointer/unreviewed/owner mismatch fails |
| allocation ledger | record, byte-idempotent replay, conflict, tamper, product cap, global non-product cap |
| disposition ledger | park/complete, byte-idempotent replay, changed request and double-disposition denial |
| selected outcome | missing allocation denied; exact allocation retained; disposed allocation invalidates resolution; legacy selection remains compatible |
| public CLI | allocate and dispose emit machine-readable results and stable errors |
| regression | focused Plans #114/#117/#118/#119 continuation, selection, restart, transfer, and progress tests pass |

## Acceptance Criteria

1. A new classed contract cannot self-declare an owner class that differs from
   exact Project Graph authority.
2. A separate explicit allocation is mandatory before classed selection.
3. One active product per owner class and one global maintenance/external slot
   are enforced deterministically.
4. Allocation and disposition histories are append-only, conflict-safe, and
   exact-replay byte-idempotent.
5. The real Plan #120 maintenance scenario allocates, replays, selects,
   observes, and parks against current Project Meta Git evidence.
6. Legacy contracts remain readable without being promoted to portfolio proof.
7. Focused tests, Ruff, mypy, plan validation, and digest-bound evidence pass.

## Promotion Boundary

This plan proves hard portfolio admission at the explicit allocation and
selected-outcome entrypoints. It does not make outcome selection mandatory for
every claim, block ordinary writes when no selection exists, activate a host
hook, choose Brian's one product project, independently verify receipt meaning,
or claim installer/fleet adoption. The next promotion integrates this admitted
state into new plan/claim/worktree creation and selected pre-write enforcement
after representative false-block review.

## Trace Evaluation

`trace_evaluable: false # deterministic contracts and local Git/state transitions`

## Terminal Closeout

Retain one authentic allocation ledger snapshot and selected observation,
append a parking disposition so the pilot does not leak the global maintenance
slot, merge the coherent vertical, close the claim/worktree atomically, and
continue to mandatory new-work binding if the evidence remains both-sign and
no authority decision is required.
